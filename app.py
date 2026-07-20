# -*- coding: utf-8 -*-
"""
คลังภาพกลางของบริษัท — ไฟล์หลักของแอป (router)

โครงสร้างใหม่: หน้าแรก (landing) ให้เลือก 3 ทางเข้า แล้ว route ตามสิทธิ์ (role)
- general   = คลังภาพทั่วไป (ระบบเดิม 3 หน้า) — ใช้ APP_PASSWORD
- user      = ผู้เข้าร่วมกิจกรรม (รหัสกิจกรรม + ชื่อ)
- admin     = หัวหน้า (username + password จากแท็บ Users)
- superuser = ผู้ดูแลระบบ (username + password จาก secrets)

ระบบเดิม (คลังภาพทั่วไป) ไม่ถูกแก้ logic — แค่ย้ายมาอยู่หลังการเลือก "คลังภาพทั่วไป"
"""

import streamlit as st

from google_utils import check_connection
import page_upload
import page_gallery
import page_dashboard
import page_activity_user
import page_activity_viewer
import page_activity_admin
import page_activity_superuser
import auth

# ตั้งค่าหน้าเว็บ (ต้องเป็นคำสั่ง streamlit แรกสุด)
st.set_page_config(
    page_title="คลังภาพกลางของบริษัท",
    page_icon="📷",
    layout="wide",
)


# ---------------------------------------------------------------------------
# คลังภาพทั่วไป (ระบบเดิม) — sidebar สถานะ + 3 แท็บ (ส่งรูป/คลังภาพ/Dashboard)
# ---------------------------------------------------------------------------
def render_general_warehouse():
    st.title("📷 คลังภาพกลางของบริษัท")

    with st.sidebar:
        st.header("⚙️ สถานะระบบ")
        try:
            sheet_name, _ = check_connection()
            st.success(f"เชื่อม Google Sheet สำเร็จ\n\n📊 {sheet_name}")
        except Exception as e:
            st.error(f"เชื่อม Google ไม่ได้: {e}")

        if st.button("🔄 รีเฟรชข้อมูล"):
            st.cache_data.clear()
            st.rerun()

        if st.button("🚪 ออกจากระบบ"):
            auth.logout()

    tab_upload, tab_gallery, tab_dashboard = st.tabs(
        ["📤 ส่งรูป", "🖼️ คลังภาพ", "📊 Dashboard"]
    )
    with tab_upload:
        page_upload.render()
    with tab_gallery:
        page_gallery.render()
    with tab_dashboard:
        page_dashboard.render()


# ---------------------------------------------------------------------------
# Router หลัก — ดูสิทธิ์แล้วพาไปหน้าที่ถูกต้อง
# ---------------------------------------------------------------------------
def main():
    auth.ensure_session()
    auth.handle_deeplink()   # อ่าน QR deep-link (?viewcode/?actcode) พาเข้าอัตโนมัติ
    auth.restore_session()   # ไม่ได้มาจาก QR → ลองคืน login ที่ "จำฉันไว้" จาก cookie
    role = st.session_state.get("role")
    ident = st.session_state.get("identity", {})

    # ยังไม่ login → หน้าแรก
    if not role:
        auth.render_landing()
        return

    if role == "general":
        render_general_warehouse()

    elif role == "user":
        auth.render_topbar_logout(
            f"📤 ส่งรูปเข้ากิจกรรม: {ident.get('activity_name','')} · คุณ: {ident.get('name','')}"
        )
        page_activity_user.render()

    elif role == "viewer":
        auth.render_topbar_logout(
            f"🖼️ ดูอัลบั้ม: {ident.get('activity_name','')} · {ident.get('viewer_name','')}"
        )
        page_activity_viewer.render()

    elif role == "admin":
        auth.render_topbar_logout(f"🛠️ admin: {ident.get('fullname') or ident.get('username','')}")
        page_activity_admin.render()

    elif role == "superuser":
        auth.render_topbar_logout(
            f"👑 superuser: {ident.get('username','')}", show_refresh=True
        )
        page_activity_superuser.render()


main()
