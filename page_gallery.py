# -*- coding: utf-8 -*-
"""
page_gallery.py — หน้า "คลังภาพ"
มี filter (แผนก/หมวด/ช่วงวันที่/คำค้น) + แสดงเป็น grid + ดาวน์โหลดเดี่ยว/zip + แบ่งหน้า
"""

import io
import zipfile

import streamlit as st
import pandas as pd

from config import DEPARTMENTS, CATEGORIES
from google_utils import (
    load_data, download_file_bytes, extract_file_id, get_image_bytes, delete_photo,
)

PAGE_SIZE = 12          # จำนวนรูปต่อหน้า
COLS_PER_ROW = 4        # จำนวนรูปต่อแถว


@st.cache_data(ttl=300, show_spinner=False)
def build_zip(items: tuple) -> bytes:
    """
    รวมรูปทั้งหมดที่ filter เป็นไฟล์ ZIP เดียว (ทำในหน่วยความจำ)
    items = tuple ของ (file_id, ชื่อไฟล์) — ใช้ tuple เพื่อให้ cache ได้
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_id, filename in items:
            try:
                data = download_file_bytes(file_id)
                zf.writestr(filename, data)
            except Exception:
                # ถ้ารูปไหนโหลดไม่ได้ ข้ามไป ไม่ให้ทั้ง zip พัง
                continue
    return buffer.getvalue()


def render():
    st.subheader("🖼️ คลังภาพ")

    df = load_data()
    if df.empty:
        st.info("ยังไม่มีรูปในคลัง — ไปที่หน้า '📤 ส่งรูป' เพื่อเพิ่มรูปแรกได้เลย")
        return

    # แปลงคอลัมน์วันเวลาเป็นชนิดวันที่ (ไว้ filter ช่วงวันและเรียงลำดับ)
    df["_dt"] = pd.to_datetime(df["วันเวลา"], errors="coerce")

    # ---------------- แถบ Filter ----------------
    c1, c2, c3 = st.columns(3)
    with c1:
        dep = st.selectbox("แผนก", ["ทั้งหมด"] + DEPARTMENTS)
    with c2:
        cat = st.selectbox("หมวด", ["ทั้งหมด"] + CATEGORIES)
    with c3:
        keyword = st.text_input("คำค้น (ชื่อเรื่อง / แท็ก)")

    # ช่วงวันที่ (ตั้งค่าเริ่มต้นจากข้อมูลจริง)
    valid_dates = df["_dt"].dropna()
    if valid_dates.empty:
        date_range = ()
    else:
        min_d = valid_dates.min().date()
        max_d = valid_dates.max().date()
        date_range = st.date_input("ช่วงวันที่", value=(min_d, max_d))

    # ---------------- กรองข้อมูลตามเงื่อนไข ----------------
    filtered = df.copy()
    if dep != "ทั้งหมด":
        filtered = filtered[filtered["แผนก"] == dep]
    if cat != "ทั้งหมด":
        filtered = filtered[filtered["หมวด"] == cat]
    if keyword.strip():
        kw = keyword.strip().lower()
        title_match = filtered["ชื่อเรื่อง"].astype(str).str.lower().str.contains(kw)
        tag_match = filtered["แท็ก"].astype(str).str.lower().str.contains(kw)
        filtered = filtered[title_match | tag_match]
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        filtered = filtered[
            (filtered["_dt"].dt.date >= start) & (filtered["_dt"].dt.date <= end)
        ]

    # เรียงรูปใหม่สุดขึ้นก่อน
    filtered = filtered.sort_values("_dt", ascending=False)

    st.markdown(f"**พบ {len(filtered)} รูป**")
    if filtered.empty:
        st.warning("ไม่พบรูปที่ตรงกับเงื่อนไข ลองปรับ filter ดูครับ")
        return

    # ---------------- ปุ่มดาวน์โหลดทั้งหมดเป็น ZIP ----------------
    if st.button("📦 เตรียมไฟล์ ZIP ของรูปที่ filter ทั้งหมด"):
        with st.spinner("กำลังรวมรูปเป็นไฟล์ ZIP..."):
            items = tuple(
                (extract_file_id(r["ลิงก์รูป"]), r["ชื่อไฟล์"])
                for _, r in filtered.iterrows()
            )
            st.session_state["zip_bytes"] = build_zip(items)
    if st.session_state.get("zip_bytes"):
        st.download_button(
            "⬇️ ดาวน์โหลด .zip",
            data=st.session_state["zip_bytes"],
            file_name="images.zip",
            mime="application/zip",
        )

    st.divider()

    # ---------------- แบ่งหน้า (Pagination) ----------------
    total = len(filtered)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = st.number_input("หน้า", min_value=1, max_value=total_pages, value=1, step=1)
    start_i = (page - 1) * PAGE_SIZE
    page_df = filtered.iloc[start_i:start_i + PAGE_SIZE]
    st.caption(f"หน้า {page}/{total_pages}")

    # ---------------- แสดงผลแบบ Grid ----------------
    rows = page_df.to_dict("records")
    for i in range(0, len(rows), COLS_PER_ROW):
        cols = st.columns(COLS_PER_ROW)
        for col, item in zip(cols, rows[i:i + COLS_PER_ROW]):
            with col:
                file_id = extract_file_id(item["ลิงก์รูป"])
                # โหลด bytes รูปจริงมาแสดง (ชัวร์กว่า URL thumbnail ที่บางทีไม่ขึ้น)
                try:
                    st.image(get_image_bytes(file_id), width="stretch")
                except Exception:
                    st.caption("⚠️ โหลดรูปไม่ได้")
                st.markdown(
                    f"**{item['ชื่อเรื่อง']}**  \n"
                    f"{item['แผนก']} / {item['หมวด']}  \n"
                    f"🗓️ {item['วันเวลา']}"
                )
                # ปุ่มดาวน์โหลดรูปเดี่ยว (เปิดลิงก์ดาวน์โหลดตรงจาก Drive)
                download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                st.link_button("⬇️ ดาวน์โหลดรูปนี้", download_url, width="stretch")

                # ปุ่มลบรูป (มีขั้นยืนยันก่อน กันกดพลาด) — ใช้ file_id เป็น key กันชนกันในกริด
                del_key = f"confirm_del_{file_id}"
                if st.session_state.get(del_key):
                    st.warning("⚠️ ลบรูปนี้ถาวร?")
                    yes, no = st.columns(2)
                    if yes.button("✅ ลบเลย", key=f"yes_{file_id}", width="stretch"):
                        try:
                            delete_photo(file_id, item["ลิงก์รูป"])
                            st.session_state.pop(del_key, None)
                            st.cache_data.clear()  # ล้าง cache ให้รายการหายทันที
                            st.rerun()
                        except Exception as e:
                            st.error(f"ลบไม่สำเร็จ: {e}")
                    if no.button("❌ ยกเลิก", key=f"no_{file_id}", width="stretch"):
                        st.session_state.pop(del_key, None)
                        st.rerun()
                else:
                    if st.button("🗑️ ลบรูปนี้", key=f"del_{file_id}", width="stretch"):
                        st.session_state[del_key] = True
                        st.rerun()
