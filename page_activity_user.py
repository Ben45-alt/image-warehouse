# -*- coding: utf-8 -*-
"""
page_activity_user.py — หน้าของ "ผู้เข้าร่วมกิจกรรม" (role = user)
มี 2 แท็บ:
  1) ส่งรูปเข้ากิจกรรม — กรอกแค่รูป (ชื่อผู้ส่งมาจากตอน login) reuse pipeline เดิม
  2) ดูรูปในกิจกรรมนี้ — เห็นเฉพาะ activity_id ของตัวเอง + ดาวน์โหลดเดี่ยว/zip
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd

from image_utils import compress_image, compute_phash
from google_utils import (
    upload_to_drive, append_activity_row, load_active_data, get_image_bytes, extract_file_id,
    make_activity_filename, count_activity_photos, log_action,
)
from page_gallery import build_zip, COLS_PER_ROW   # reuse ฟังก์ชันทำ zip + จำนวนคอลัมน์กริด


def render():
    ident = st.session_state.get("identity", {})
    activity_id = ident.get("activity_id")
    activity_name = ident.get("activity_name", "")
    sender = ident.get("name", "")

    tab_send, tab_view = st.tabs(["📤 ส่งรูปเข้ากิจกรรม", "🖼️ รูปในกิจกรรมนี้"])
    with tab_send:
        _render_send(activity_id, activity_name, sender)
    with tab_view:
        _render_view(activity_id, activity_name)


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
            st.cache_data.clear()                              # ให้แท็บ "ดูรูป" เห็นทันที

        st.success(f"✅ ส่งรูปสำเร็จ! (ไฟล์: {filename})")
        compressed.seek(0)
        st.image(compressed, width=320)
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาด: {e}")


def _render_view(activity_id, activity_name):
    st.subheader(f"🖼️ รูปในกิจกรรม: {activity_name}")

    df = load_active_data()   # ไม่รวมรูปในถังขยะ
    if df.empty or "activity_id" not in df.columns:
        st.info("ยังไม่มีรูปในกิจกรรมนี้ — ไปแท็บ '📤 ส่งรูปเข้ากิจกรรม' เพื่อเพิ่มรูปแรก")
        return

    # เห็นเฉพาะรูปของกิจกรรมนี้เท่านั้น (กรองด้วย activity_id)
    mine = df[df["activity_id"].astype(str) == str(activity_id)].copy()
    if mine.empty:
        st.info("ยังไม่มีรูปในกิจกรรมนี้ — ไปแท็บ '📤 ส่งรูปเข้ากิจกรรม' เพื่อเพิ่มรูปแรก")
        return

    mine["_dt"] = pd.to_datetime(mine["วันเวลา"], errors="coerce")
    mine = mine.sort_values("_dt", ascending=False)
    st.markdown(f"**พบ {len(mine)} รูป**")

    # ปุ่มดาวน์โหลดทั้งหมดเป็น ZIP (reuse build_zip เดิม)
    if st.button("📦 เตรียมไฟล์ ZIP ของรูปทั้งหมด", key="act_zip_btn"):
        with st.spinner("กำลังรวมรูปเป็นไฟล์ ZIP..."):
            items = tuple(
                (extract_file_id(r["ลิงก์รูป"]), r["ชื่อไฟล์"]) for _, r in mine.iterrows()
            )
            st.session_state["act_zip_bytes"] = build_zip(items)
    if st.session_state.get("act_zip_bytes"):
        st.download_button(
            "⬇️ ดาวน์โหลด .zip",
            data=st.session_state["act_zip_bytes"],
            file_name=f"{activity_name or 'activity'}.zip",
            mime="application/zip",
            key="act_zip_dl",
        )

    st.divider()

    # แสดงเป็น grid
    rows = mine.to_dict("records")
    for i in range(0, len(rows), COLS_PER_ROW):
        cols = st.columns(COLS_PER_ROW)
        for col, item in zip(cols, rows[i:i + COLS_PER_ROW]):
            with col:
                file_id = extract_file_id(item["ลิงก์รูป"])
                try:
                    st.image(get_image_bytes(file_id), width="stretch")
                except Exception:
                    st.caption("⚠️ โหลดรูปไม่ได้")
                st.caption(f"👤 {item.get('ผู้ส่ง','')} · 🗓️ {item.get('วันเวลา','')}")
                download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                st.link_button("⬇️ ดาวน์โหลด", download_url, width="stretch")
