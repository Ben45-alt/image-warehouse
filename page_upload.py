# -*- coding: utf-8 -*-
"""
page_upload.py — หน้า "ส่งรูป" (คลังภาพทั่วไป)
ขั้นตอนเมื่อกดบันทึก: ตรวจข้อมูล → ย่อรูป → ตรวจรูปซ้ำ(phash) → อัป Drive → บันทึก Sheet
ถ้ารูปคล้ายที่เคยส่งในคลังทั่วไป จะถามยืนยันก่อนบันทึก
"""

import io
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

from config import DEPARTMENTS, CATEGORIES
from image_utils import compress_image, compute_phash
from google_utils import (
    upload_to_drive, append_row, make_general_filename, log_action,
    load_general_data, find_similar_photo,
)


def _do_general_upload(department, category, title, tags, sender, comp_bytes, phash) -> str:
    """อัปรูปคลังทั่วไปที่บีบแล้วขึ้น Drive + บันทึก Sheet + log — คืนชื่อไฟล์"""
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    datetime_str = now.strftime("%Y-%m-%d %H:%M:%S")
    filename = make_general_filename(department, category, now)
    file_id, link = upload_to_drive(io.BytesIO(comp_bytes), filename)
    row = [datetime_str, department, category, title, tags, sender, link, filename, "", phash]
    append_row(row)
    log_action(sender, "general", "อัปโหลดรูป", detail=filename)
    st.cache_data.clear()
    return filename


def _render_dup_confirm(pend):
    """เจอรูปซ้ำ — ถามยืนยันก่อนบันทึกจริง"""
    st.warning(
        f"⚠️ รูปนี้คล้ายกับที่เคยส่งในคลังทั่วไปแล้ว "
        f"(ไฟล์ {pend['dup_file']} · {pend['dup_dep']}/{pend['dup_cat']} · {pend['dup_dt']}) — จะบันทึกซ้ำไหม?"
    )
    st.image(pend["bytes"], width=240, caption="รูปที่กำลังจะบันทึก")
    c1, c2 = st.columns(2)
    if c1.button("✅ ยืนยันบันทึกเลย", width="stretch", key="up_dup_yes"):
        try:
            fn = _do_general_upload(
                pend["department"], pend["category"], pend["title"], pend["tags"],
                pend["sender"], pend["bytes"], pend["phash"],
            )
            st.session_state.pop("up_pending", None)
            st.session_state["up_flash"] = f"✅ บันทึกสำเร็จ! (ไฟล์: {fn})"
            st.rerun()
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาด: {e}")
    if c2.button("❌ ยกเลิก (ไม่บันทึก)", width="stretch", key="up_dup_no"):
        st.session_state.pop("up_pending", None)
        st.rerun()


def render():
    st.subheader("📤 ส่งรูปเข้าคลัง")

    flash = st.session_state.pop("up_flash", None)
    if flash:
        st.success(flash)

    # มีรูปรอยืนยัน (เจอซ้ำ) → โชว์หน้ายืนยันแทนฟอร์ม
    pend = st.session_state.get("up_pending")
    if pend:
        _render_dup_confirm(pend)
        return

    # เลือกวิธีเพิ่มรูป (วางไว้นอก form เพื่อให้สลับ "แนบไฟล์/กล้อง" ได้ทันที)
    source = st.radio("วิธีเพิ่มรูป", ["แนบไฟล์", "ถ่ายด้วยกล้อง"], horizontal=True)

    # ช่องอัปรูปต้องอยู่ "ใน" form เพื่อให้ clear_on_submit ล้างรูปหลังกดบันทึก (กันบันทึกซ้ำ)
    with st.form("upload_form", clear_on_submit=True):
        if source == "แนบไฟล์":
            image_file = st.file_uploader("เลือกไฟล์รูป (JPG, JPEG, PNG)", type=["jpg", "jpeg", "png"])
        else:
            image_file = st.camera_input("ถ่ายรูปจากกล้อง")

        col1, col2 = st.columns(2)
        with col1:
            department = st.selectbox("แผนก", DEPARTMENTS)
        with col2:
            category = st.selectbox("หมวด", CATEGORIES)

        title = st.text_input("ชื่อเรื่อง / คำอธิบาย")
        tags = st.text_input("แท็ก (คั่นด้วยจุลภาค เช่น: ชั้น2, โกดังA, ด่วน)")
        sender = st.text_input("ชื่อผู้ส่ง")

        submitted = st.form_submit_button("💾 บันทึกข้อมูล", width="stretch")

    if not submitted:
        return

    # ----- ตรวจสอบว่ากรอกครบก่อนบันทึก -----
    if image_file is None:
        st.error("⚠️ ยังไม่ได้เลือกหรือถ่ายรูป")
        return
    if not title.strip():
        st.error("⚠️ กรุณากรอกชื่อเรื่อง")
        return
    if not sender.strip():
        st.error("⚠️ กรุณากรอกชื่อผู้ส่ง")
        return

    try:
        with st.spinner("กำลังย่อรูป + ตรวจรูปซ้ำ..."):
            now = datetime.now(ZoneInfo("Asia/Bangkok"))
            # ย่อ/บีบรูป + ฝัง metadata (เก็บ EXIF เดิม + ฝังชื่อเรื่อง/ผู้ส่ง/วันเวลา)
            compressed = compress_image(image_file, meta={
                "description": title.strip(),
                "artist": sender.strip(),
                "datetime": now.strftime("%Y:%m:%d %H:%M:%S"),
            })
            comp_bytes = compressed.getvalue()
            phash = compute_phash(comp_bytes)
            # ตรวจรูปซ้ำในคลังทั่วไป
            dup = find_similar_photo(phash, load_general_data())

        if dup:
            st.session_state["up_pending"] = {
                "department": department, "category": category,
                "title": title.strip(), "tags": tags.strip(), "sender": sender.strip(),
                "bytes": comp_bytes, "phash": phash,
                "dup_file": dup.get("ชื่อไฟล์", ""), "dup_dt": dup.get("วันเวลา", ""),
                "dup_dep": dup.get("แผนก", ""), "dup_cat": dup.get("หมวด", ""),
            }
            st.rerun()

        with st.spinner("กำลังอัปโหลด..."):
            fn = _do_general_upload(department, category, title.strip(), tags.strip(),
                                    sender.strip(), comp_bytes, phash)
        st.session_state["up_flash"] = f"✅ บันทึกสำเร็จ! (ไฟล์: {fn})"
        st.rerun()
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาด: {e}")
