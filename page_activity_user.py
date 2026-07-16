# -*- coding: utf-8 -*-
"""
page_activity_user.py — หน้าของ "ผู้ส่งรูปเข้ากิจกรรม" (role = user)
ส่งรูปอย่างเดียว (ถ่าย≠ดู) — ไม่เห็นอัลบั้มรวมของคนอื่น
มีระบบเตือน "รูปซ้ำ" (phash) ก่อนส่ง: ถ้ารูปคล้ายที่เคยส่งในกิจกรรมนี้ จะถามยืนยันก่อน
"""

import io
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from image_utils import compress_image, compute_phash
from google_utils import (
    upload_to_drive, append_activity_row, load_active_data, find_similar_photo,
    make_activity_filename, count_activity_photos, log_action,
)


def render():
    ident = st.session_state.get("identity", {})
    activity_id = ident.get("activity_id")
    activity_name = ident.get("activity_name", "")
    sender = ident.get("name", "")
    _render_send(activity_id, activity_name, sender)


def _do_activity_upload(activity_id, activity_name, sender, comp_bytes, phash) -> str:
    """อัปรูปที่บีบแล้วขึ้น Drive + บันทึก Sheet + log — คืนชื่อไฟล์"""
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    datetime_str = now.strftime("%Y-%m-%d %H:%M:%S")
    seq = count_activity_photos(activity_id) + 1
    filename = make_activity_filename(activity_name, seq, now)
    file_id, link = upload_to_drive(io.BytesIO(comp_bytes), filename)
    append_activity_row(datetime_str, sender, link, filename, activity_id, phash)
    log_action(sender, "user", "อัปโหลดรูป", detail=filename, activity_id=activity_id)
    st.cache_data.clear()
    return filename


def _render_dup_confirm(pend):
    """เจอรูปซ้ำ — ถามยืนยันก่อนส่งจริง"""
    st.warning(
        f"⚠️ รูปนี้คล้ายกับที่เคยส่งในกิจกรรมนี้แล้ว "
        f"(ไฟล์ {pend['dup_file']} · โดย {pend['dup_by']} · {pend['dup_dt']}) — จะส่งซ้ำไหม?"
    )
    st.image(pend["bytes"], width=240, caption="รูปที่กำลังจะส่ง")
    c1, c2 = st.columns(2)
    if c1.button("✅ ยืนยันส่งเลย", width="stretch", key="act_dup_yes"):
        try:
            fn = _do_activity_upload(
                pend["activity_id"], pend["activity_name"], pend["sender"],
                pend["bytes"], pend["phash"],
            )
            st.session_state.pop("act_pending", None)
            st.session_state["act_flash"] = f"✅ ส่งรูปสำเร็จ! (ไฟล์: {fn})"
            st.rerun()
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาด: {e}")
    if c2.button("❌ ยกเลิก (ไม่ส่ง)", width="stretch", key="act_dup_no"):
        st.session_state.pop("act_pending", None)
        st.rerun()


def _render_send(activity_id, activity_name, sender):
    st.subheader(f"📤 ส่งรูปเข้ากิจกรรม: {activity_name}")
    st.caption(f"ผู้ส่ง: {sender}")

    # ข้อความสำเร็จจากรอบก่อน (หลัง rerun)
    flash = st.session_state.pop("act_flash", None)
    if flash:
        st.success(flash)

    # ถ้ามีรูปรอยืนยัน (เจอซ้ำ) → โชว์หน้ายืนยันแทนฟอร์ม
    pend = st.session_state.get("act_pending")
    if pend and pend.get("activity_id") == activity_id:
        _render_dup_confirm(pend)
        return

    # เลือกวิธีเพิ่มรูป (นอก form เพื่อสลับได้ทันที) — ช่องอัปรูปอยู่ "ใน" form เพื่อให้ล้างหลังส่ง
    source = st.radio("วิธีเพิ่มรูป", ["แนบไฟล์", "ถ่ายด้วยกล้อง"], horizontal=True, key="act_source")
    with st.form("activity_upload_form", clear_on_submit=True):
        if source == "แนบไฟล์":
            image_file = st.file_uploader("เลือกไฟล์รูป (JPG, JPEG, PNG)",
                                          type=["jpg", "jpeg", "png"], key="act_file")
        else:
            image_file = st.camera_input("ถ่ายรูปจากกล้อง", key="act_cam")
        submitted = st.form_submit_button("💾 ส่งรูป", width="stretch")

    if not submitted:
        return
    if image_file is None:
        st.error("⚠️ ยังไม่ได้เลือกหรือถ่ายรูป")
        return

    try:
        with st.spinner("กำลังย่อรูป + ตรวจรูปซ้ำ..."):
            # ย่อ + ฝัง metadata (บริบท = ชื่อกิจกรรม/ผู้ส่ง/วันเวลา + เก็บ EXIF เดิม)
            now = datetime.now(ZoneInfo("Asia/Bangkok"))
            compressed = compress_image(image_file, meta={
                "description": activity_name,
                "artist": sender,
                "datetime": now.strftime("%Y:%m:%d %H:%M:%S"),
            })
            comp_bytes = compressed.getvalue()
            phash = compute_phash(comp_bytes)

            # ตรวจรูปซ้ำ "ในกิจกรรมเดียวกัน"
            scope = load_active_data()
            if not scope.empty and "activity_id" in scope.columns:
                scope = scope[scope["activity_id"].astype(str) == str(activity_id)]
            dup = find_similar_photo(phash, scope)

        # เจอซ้ำ → พักไว้ถามยืนยัน
        if dup:
            st.session_state["act_pending"] = {
                "activity_id": activity_id, "activity_name": activity_name, "sender": sender,
                "bytes": comp_bytes, "phash": phash,
                "dup_file": dup.get("ชื่อไฟล์", ""), "dup_dt": dup.get("วันเวลา", ""),
                "dup_by": dup.get("ผู้ส่ง", ""),
            }
            st.rerun()

        # ไม่ซ้ำ → ส่งเลย
        with st.spinner("กำลังอัปโหลด..."):
            fn = _do_activity_upload(activity_id, activity_name, sender, comp_bytes, phash)
        st.session_state["act_flash"] = f"✅ ส่งรูปสำเร็จ! (ไฟล์: {fn})"
        st.rerun()
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาด: {e}")
