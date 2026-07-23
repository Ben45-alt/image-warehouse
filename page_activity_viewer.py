# -*- coding: utf-8 -*-
"""
page_activity_viewer.py — หน้าของ "ผู้ชมอัลบั้ม" (role = viewer)
ดู + ดาวน์โหลดรูปในอัลบั้มกิจกรรมที่ถูกแชร์ให้ (หรืออัลบั้มสาธารณะ) — ส่ง/ลบไม่ได้
identity: {activity_id, activity_name, viewer_name}
"""

import streamlit as st
import pandas as pd

from google_utils import load_active_data, get_image_bytes, get_thumbnail, extract_file_id
from page_gallery import build_zip, COLS_PER_ROW   # reuse zip + จำนวนคอลัมน์กริด


def render():
    ident = st.session_state.get("identity", {})
    activity_id = str(ident.get("activity_id", ""))
    activity_name = ident.get("activity_name", "")

    st.subheader(f"🖼️ อัลบั้ม: {activity_name}")

    df = load_active_data()   # ไม่รวมรูปในถังขยะ
    if df.empty or "activity_id" not in df.columns:
        st.info("ยังไม่มีรูปในอัลบั้มนี้")
        return

    album = df[df["activity_id"].astype(str) == activity_id].copy()
    if album.empty:
        st.info("ยังไม่มีรูปในอัลบั้มนี้")
        return

    album["_dt"] = pd.to_datetime(album["วันเวลา"], errors="coerce")
    album = album.sort_values("_dt", ascending=False)
    st.markdown(f"**พบ {len(album)} รูป**")

    # ปุ่มดาวน์โหลดทั้งอัลบั้มเป็น ZIP
    if st.button("📦 เตรียมไฟล์ ZIP ทั้งอัลบั้ม", key="viewer_zip_btn"):
        with st.spinner("กำลังรวมรูปเป็นไฟล์ ZIP..."):
            items = tuple(
                (extract_file_id(r["ลิงก์รูป"]), r["ชื่อไฟล์"]) for _, r in album.iterrows()
            )
            st.session_state["viewer_zip_bytes"] = build_zip(items)
    if st.session_state.get("viewer_zip_bytes"):
        st.download_button(
            "⬇️ ดาวน์โหลด .zip",
            data=st.session_state["viewer_zip_bytes"],
            file_name=f"{activity_name or 'album'}.zip",
            mime="application/zip",
            key="viewer_zip_dl",
        )

    st.divider()

    rows = album.to_dict("records")
    for i in range(0, len(rows), COLS_PER_ROW):
        cols = st.columns(COLS_PER_ROW)
        for col, item in zip(cols, rows[i:i + COLS_PER_ROW]):
            with col:
                file_id = extract_file_id(item["ลิงก์รูป"])
                try:
                    st.image(get_thumbnail(file_id), width="stretch")
                except Exception:
                    st.caption("⚠️ โหลดรูปไม่ได้")
                st.caption(f"👤 {item.get('ผู้ส่ง','')} · 🗓️ {item.get('วันเวลา','')}")
                download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                st.link_button("⬇️ ดาวน์โหลด", download_url, width="stretch")
