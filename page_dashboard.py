# -*- coding: utf-8 -*-
"""
page_dashboard.py — หน้า "Dashboard" สรุปภาพรวมสถิติ
- การ์ดตัวเลข: รูปทั้งหมด / จำนวนแผนก / เพิ่มเดือนนี้
- กราฟแท่ง: แยกตามแผนก และ แยกตามหมวด
- กราฟเส้น: จำนวนรูปแต่ละเดือน
- ตาราง: รายการล่าสุด 10 รายการ
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd

from google_utils import load_general_data


def render():
    st.subheader("📊 Dashboard ภาพรวม")

    df = load_general_data()   # เฉพาะคลังทั่วไป (กันรูปกิจกรรมทำตัวเลขเพี้ยน)
    if df.empty:
        st.info("ยังไม่มีข้อมูล — เพิ่มรูปก่อนที่หน้า '📤 ส่งรูป'")
        return

    df["_dt"] = pd.to_datetime(df["วันเวลา"], errors="coerce")

    # ---------------- การ์ดสรุปตัวเลข ----------------
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    this_month = df[
        (df["_dt"].dt.year == now.year) & (df["_dt"].dt.month == now.month)
    ]

    c1, c2, c3 = st.columns(3)
    c1.metric("📷 รูปทั้งหมด", len(df))
    c2.metric("🏢 จำนวนแผนก", df["แผนก"].nunique())
    c3.metric("🆕 เพิ่มเดือนนี้", len(this_month))

    st.divider()

    # ---------------- กราฟแยกตามแผนก / หมวด ----------------
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**จำนวนรูปแยกตามแผนก**")
        by_dep = df["แผนก"].value_counts()
        st.bar_chart(by_dep)
    with col_b:
        st.markdown("**จำนวนรูปแยกตามหมวด**")
        by_cat = df["หมวด"].value_counts()
        st.bar_chart(by_cat)

    st.divider()

    # ---------------- กราฟเส้น จำนวนรูปแต่ละเดือน ----------------
    st.markdown("**จำนวนรูปที่ส่งในแต่ละเดือน**")
    month_df = df.dropna(subset=["_dt"]).copy()
    if not month_df.empty:
        month_df["เดือน"] = month_df["_dt"].dt.to_period("M").astype(str)
        by_month = month_df.groupby("เดือน").size()
        st.line_chart(by_month)
    else:
        st.caption("ยังไม่มีข้อมูลวันที่เพียงพอ")

    st.divider()

    # ---------------- ตารางรายการล่าสุด ----------------
    st.markdown("**🕘 รายการล่าสุด 10 รายการ**")
    latest = df.sort_values("_dt", ascending=False).head(10)
    show_cols = ["วันเวลา", "แผนก", "หมวด", "ชื่อเรื่อง", "ผู้ส่ง"]
    st.dataframe(latest[show_cols], width="stretch", hide_index=True)
