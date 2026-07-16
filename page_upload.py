# -*- coding: utf-8 -*-
"""
page_upload.py — หน้า "ส่งรูป"
ขั้นตอนเมื่อกดบันทึก: ตรวจข้อมูล → ย่อรูป → อัปขึ้น Drive → บันทึกลง Sheet → แจ้งผล
"""

import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

from config import DEPARTMENTS, CATEGORIES
from image_utils import compress_image, compute_phash
from google_utils import upload_to_drive, append_row, make_general_filename, log_action


def render():
    st.subheader("📤 ส่งรูปเข้าคลัง")

    # เลือกวิธีเพิ่มรูป (วางไว้นอก form เพื่อให้สลับ "แนบไฟล์/กล้อง" ได้ทันที)
    source = st.radio("วิธีเพิ่มรูป", ["แนบไฟล์", "ถ่ายด้วยกล้อง"], horizontal=True)

    # ฟอร์มกรอกรายละเอียด
    # หมายเหตุ: ต้องวางช่องอัปรูปไว้ "ใน" form ด้วย เพื่อให้ clear_on_submit ล้างรูป
    # ไปพร้อมกับช่องอื่นหลังกดบันทึก — กัน bug รูปเก่าค้าง แล้วถูกบันทึกซ้ำเป็นรายการใหม่
    # ตอนผู้ใช้แค่เปลี่ยนแผนก/หมวด/หัวข้อ แล้วกดบันทึกอีกรอบ
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

    # ----- เริ่มทำงานจริง -----
    try:
        with st.spinner("กำลังย่อรูปและอัปโหลด..."):
            # 1) สร้างเวลาปัจจุบัน (เวลาไทย) + ชื่อไฟล์ตามแผนก/หมวด
            now = datetime.now(ZoneInfo("Asia/Bangkok"))
            datetime_str = now.strftime("%Y-%m-%d %H:%M:%S")
            filename = make_general_filename(department, category, now)

            # 2) ย่อ/บีบรูป + ฝัง metadata บริบท (เก็บ EXIF เดิม + ฝังชื่อเรื่อง/ผู้ส่ง/วันเวลา)
            compressed = compress_image(image_file, meta={
                "description": title.strip(),
                "artist": sender.strip(),
                "datetime": now.strftime("%Y:%m:%d %H:%M:%S"),
            })

            # 3) ลายนิ้วมือรูป (ไว้ตรวจซ้ำภายหลัง) — คำนวณจาก bytes ที่มีอยู่แล้ว ไม่ต้องโหลดใหม่
            phash = compute_phash(compressed.getvalue())

            # 4) อัปขึ้น Drive + ตั้งสิทธิ์ให้ดูได้
            file_id, link = upload_to_drive(compressed, filename)

            # 5) บันทึกลง Sheet (ลำดับต้องตรงกับหัวตาราง) — คลังทั่วไป activity_id เว้นว่าง
            row = [
                datetime_str,      # วันเวลา
                department,        # แผนก
                category,          # หมวด
                title.strip(),     # ชื่อเรื่อง
                tags.strip(),      # แท็ก
                sender.strip(),    # ผู้ส่ง
                link,              # ลิงก์รูป
                filename,          # ชื่อไฟล์
                "",                # activity_id (คลังทั่วไป = ว่าง)
                phash,             # ลายนิ้วมือรูป
            ]
            append_row(row)
            log_action(sender.strip(), "general", "อัปโหลดรูป", detail=filename)

            # ล้าง cache เพื่อให้หน้าคลังภาพเห็นรูปใหม่ทันที
            st.cache_data.clear()

        # 5) แจ้งผลสำเร็จ + แสดงรูปตัวอย่าง
        st.success(f"✅ บันทึกสำเร็จ! (ไฟล์: {filename})")
        compressed.seek(0)  # เลื่อนกลับต้นไฟล์เพื่อนำมาแสดง
        st.image(compressed, width=320, caption=title.strip())

    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาด: {e}")
