# -*- coding: utf-8 -*-
"""
คลังภาพกลางของบริษัท — ไฟล์หลักของแอป
เฟส 2: ระบบ login ด้วยรหัสผ่าน + โครง 3 หน้า (ส่งรูป / คลังภาพ / Dashboard)
"""

import streamlit as st

from google_utils import check_connection
import page_upload
import page_gallery
import page_dashboard

# ตั้งค่าหน้าเว็บ (ต้องเป็นคำสั่ง streamlit แรกสุด)
st.set_page_config(
    page_title="คลังภาพกลางของบริษัท",
    page_icon="📷",
    layout="wide",
)


# ---------------------------------------------------------------------------
# ระบบ Login ด้วยรหัสผ่าน (อ่านรหัสจาก st.secrets กันคนนอก)
# ---------------------------------------------------------------------------
def check_password() -> bool:
    """คืน True ถ้า login ผ่านแล้ว, ถ้ายังไม่ผ่านจะแสดงช่องกรอกรหัสและคืน False"""

    # ถ้าเคย login ผ่านในรอบนี้แล้ว ไม่ต้องถามซ้ำ
    if st.session_state.get("logged_in"):
        return True

    st.title("🔒 เข้าสู่ระบบคลังภาพ")

    # ใช้ st.form เพื่อให้ "กด Enter" ในช่องรหัสผ่าน = กดปุ่มเข้าสู่ระบบ ได้ทันที
    with st.form("login_form"):
        password = st.text_input("กรอกรหัสผ่าน", type="password")
        submitted = st.form_submit_button("เข้าสู่ระบบ")

    if submitted:
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state["logged_in"] = True
            st.rerun()  # โหลดหน้าใหม่ เข้าสู่แอป
        else:
            st.error("❌ รหัสผ่านไม่ถูกต้อง")

    return False


# ---------------------------------------------------------------------------
# ส่วนหลักของแอป (จะทำงานก็ต่อเมื่อ login ผ่านแล้วเท่านั้น)
# ---------------------------------------------------------------------------
def main():
    st.title("📷 คลังภาพกลางของบริษัท")

    # แถบด้านข้าง: สถานะการเชื่อมต่อ + ปุ่มออกจากระบบ
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
            st.session_state["logged_in"] = False
            st.rerun()

    # 3 หน้า ด้วย st.tabs
    tab_upload, tab_gallery, tab_dashboard = st.tabs(
        ["📤 ส่งรูป", "🖼️ คลังภาพ", "📊 Dashboard"]
    )

    with tab_upload:
        page_upload.render()

    with tab_gallery:
        page_gallery.render()

    with tab_dashboard:
        page_dashboard.render()


# เริ่มทำงาน: เช็ค login ก่อน ถ้าผ่านค่อยเข้า main()
if check_password():
    main()
