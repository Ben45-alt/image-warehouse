# -*- coding: utf-8 -*-
"""
page_activity_user.py — หน้าของ "ผู้ส่งรูปเข้ากิจกรรม" (role = user)
ส่งรูปอย่างเดียว (ถ่าย≠ดู) — ไม่เห็นอัลบั้มรวมของคนอื่น
การดูอัลบั้มแยกไปที่ role = viewer (เจ้าของแชร์ให้เฉพาะคน/สาธารณะ)
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st

from image_utils import compress_image, compute_phash
from google_utils import (
    upload_to_drive, append_activity_row,
    make_activity_filename, count_activity_photos, log_action,
)


def render():
    ident = st.session_state.get("identity", {})
    activity_id = ident.get("activity_id")
    activity_name = ident.get("activity_name", "")
    sender = ident.get("name", "")
    _render_send(activity_id, activity_name, sender)


def _render_send(activity_id, activity_name, sender):
    st.subheader(f"📤 ส่งรูปเข้ากิจกรรม: {activity_name}")
    st.caption(f"ผู้ส่ง: {sender}")

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
        with st.spinner("กำลังย่อรูปและอัปโหลด..."):
            now = datetime.now(ZoneInfo("Asia/Bangkok"))
            datetime_str = now.strftime("%Y-%m-%d %H:%M:%S")
            # 1) ชื่อไฟล์ตามกิจกรรม: <ชื่อกิจกรรม>_<ลำดับ>_<เวลา>.jpg (ลำดับ = รูปที่มีอยู่ + 1)
            seq = count_activity_photos(activity_id) + 1
            filename = make_activity_filename(activity_name, seq, now)
            # 2) ย่อรูป + ฝัง metadata (บริบท = ชื่อกิจกรรม/ผู้ส่ง/วันเวลา + เก็บ EXIF เดิม)
            compressed = compress_image(image_file, meta={
                "description": activity_name,
                "artist": sender,
                "datetime": now.strftime("%Y:%m:%d %H:%M:%S"),
            })
            phash = compute_phash(compressed.getvalue())        # 3) ลายนิ้วมือรูป (ตรวจซ้ำ)
            file_id, link = upload_to_drive(compressed, filename)   # 4) อัป Drive (reuse + retry)
            append_activity_row(datetime_str, sender, link, filename, activity_id, phash)  # 5) บันทึก
            log_action(sender, "user", "อัปโหลดรูป", detail=filename, activity_id=activity_id)
            st.cache_data.clear()

        st.success(f"✅ ส่งรูปสำเร็จ! (ไฟล์: {filename})")
        compressed.seek(0)
        st.image(compressed, width=320)
        st.caption("ส่งรูปเพิ่มได้เรื่อยๆ — การดูอัลบั้มให้ไปที่หน้า '🖼️ ดูอัลบั้ม' (ต้องถูกแชร์/เป็นอัลบั้มสาธารณะ)")
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาด: {e}")
