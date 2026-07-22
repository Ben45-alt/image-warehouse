# -*- coding: utf-8 -*-
"""
page_activity_superuser.py — หน้าของ "ผู้ดูแลระบบ / superuser" (role = superuser)
superuser เห็น/จัดการได้ทุกอย่าง มี 7 แท็บ:
  1) 📊 Dashboard       — พื้นที่ Google Drive (15GB) + ภาพรวมกิจกรรม + กิจกรรมที่ต้องดูแล
  2) 🎯 จัดการกิจกรรม    — สร้างกิจกรรมเอง + เปิด/ปิดได้ทุกกิจกรรม (ของทุก admin)
  3) 🖼️ คลังภาพทุกกิจกรรม — เห็นรูปของ "ทุก" admin/กิจกรรม + ดาวน์โหลด/ลบ(→ถังขยะ)
  4) 🗑️ ถังขยะ          — รูปที่ลบทั้งระบบ (ทุกกิจกรรม+คลังทั่วไป) กู้คืน/ลบถาวร
  5) 👥 จัดการบัญชี admin  — สร้าง/ปิด/ลบบัญชี admin (เขียนลงแท็บ Users)
  6) 📋 Log             — บันทึกการใช้งาน (ใคร/ทำอะไร/เมื่อไหร่) + กรอง/ค้นหา
  7) 📁 คลังภาพทั่วไป (เดิม) — เข้าระบบเก่า 3 หน้าได้ (ส่งรูป/คลังภาพ/Dashboard)

หมายเหตุ layout: หน้านี้ไม่มี sidebar — ปุ่มรีเฟรช/ออกจากระบบอยู่ที่ top bar (จัดการใน app.py)
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd

import auth
from google_utils import (
    load_activities, load_users, load_data, load_active_data, load_trash_data, load_log,
    add_user, set_user_status, delete_user, find_user, pending_users,
    reset_requests, set_user_password,
    EMAIL_HEADER, RESET_REQ_HEADER, USER_ACTIVE,
    set_activity_join, JOIN_HEADER, JOIN_OPEN, JOIN_CODE,
    set_activity_status, delete_activity, is_activity_open,
    get_storage_quota, get_image_bytes, extract_file_id,
    delete_photo, trash_photo, restore_photo, log_action,
)
from page_gallery import build_zip, COLS_PER_ROW
# reuse จากหน้า admin: สร้างกิจกรรม (กันรหัสซ้ำ/สุ่มรหัส) + กล่องแชร์อัลบั้ม จะได้ไม่เขียนซ้ำ
from page_activity_admin import (
    _create_activity, render_share_panel, render_duplicate_scan, render_code_with_qr,
    render_publish_toggle,
)

import page_upload
import page_gallery
import page_dashboard

# 15 GB อ้างอิง (เผื่อบางบัญชี API ไม่คืน limit มา จะได้มีตัวหารสำรอง)
_DEFAULT_LIMIT = 15 * (1024 ** 3)


def _gb(num_bytes) -> float:
    """แปลง bytes → GB (ทศนิยม)"""
    return (num_bytes or 0) / (1024 ** 3)


def render():
    tab_dash, tab_act, tab_gallery, tab_trash, tab_admin, tab_log, tab_general = st.tabs(
        ["📊 Dashboard", "🎯 จัดการกิจกรรม", "🖼️ คลังภาพทุกกิจกรรม",
         "🗑️ ถังขยะ", "👥 จัดการบัญชี admin", "📋 Log", "📁 คลังภาพทั่วไป"]
    )
    with tab_dash:
        _render_dashboard()
    with tab_act:
        _render_manage_activities()
    with tab_gallery:
        _render_all_gallery()
    with tab_trash:
        _render_trash()
    with tab_admin:
        _render_admin_accounts()
    with tab_log:
        _render_log()
    with tab_general:
        _render_general()


# ==========================================================================
# แท็บ 1: Dashboard (เฉพาะ superuser)
# ==========================================================================
def _render_dashboard():
    activities = load_activities()
    photos = load_data()
    # รูปของ "กิจกรรม" = แถวที่ activity_id มีค่า (ไม่ว่าง) ; ที่เหลือคือคลังทั่วไปเดิม
    # ใช้ active data (ไม่รวมถังขยะ) สำหรับนับ/ภาพรวมกิจกรรม
    act_photos = _activity_photos(load_active_data())

    # ---------- ส่วนที่ 1: พื้นที่ Google Drive ----------
    st.subheader("☁️ พื้นที่ Google Drive")
    try:
        q = get_storage_quota()
        used = q["used"]
        limit = q["limit"] or _DEFAULT_LIMIT
        free = max(0, limit - used)
        ratio = min(1.0, used / limit) if limit else 0.0
        st.progress(ratio, text=f"ใช้ไป {_gb(used):.2f} GB / {_gb(limit):.0f} GB ({ratio*100:.1f}%)")
        c1, c2, c3 = st.columns(3)
        c1.metric("ใช้ไปแล้ว", f"{_gb(used):.2f} GB")
        c2.metric("เหลือ", f"{_gb(free):.2f} GB")
        # ขนาดเฉลี่ยต่อรูป (ประมาณจากพื้นที่ใช้จริง ÷ จำนวนรูปทั้งหมดในคลัง)
        total_photos = len(photos)
        avg_mb = (used / total_photos / (1024 ** 2)) if total_photos else 0
        c3.metric("รูปทั้งหมด", f"{total_photos:,}", help=f"เฉลี่ย ~{avg_mb:.2f} MB/รูป (ประมาณ)")
    except Exception as e:
        st.error(f"ดึงข้อมูลพื้นที่ Drive ไม่ได้: {e}")

    st.divider()

    # ---------- ส่วนที่ 2: ภาพรวมกิจกรรม ----------
    st.subheader("🎯 ภาพรวมกิจกรรม")
    open_count = _open_count(activities)
    admins = load_users()
    admin_count = 0
    if not admins.empty and "สถานะ" in admins.columns:
        admin_count = int((admins["สถานะ"].astype(str) == "ใช้งาน").sum())

    # รูปกิจกรรมเดือนนี้
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    month_photos = 0
    if not act_photos.empty:
        dt = pd.to_datetime(act_photos["วันเวลา"], errors="coerce")
        month_photos = int(((dt.dt.year == now.year) & (dt.dt.month == now.month)).sum())

    c1, c2, c3 = st.columns(3)
    c1.metric("🟢 กิจกรรมที่เปิดอยู่", open_count)
    c2.metric("🆕 รูปกิจกรรมเดือนนี้", month_photos)
    c3.metric("👤 admin ที่ใช้งาน", admin_count)

    # ตารางกิจกรรม: ชื่อ · คนสร้าง · จำนวนรูป (มาก→น้อย)
    st.markdown("**ตารางกิจกรรม (เรียงตามจำนวนรูปมากไปน้อย)**")
    if activities.empty:
        st.caption("ยังไม่มีกิจกรรมในระบบ")
    else:
        counts = _counts_by_activity(act_photos)
        table = activities.copy()
        table["จำนวนรูป"] = table["activity_id"].astype(str).map(counts).fillna(0).astype(int)
        show = table[["ชื่อกิจกรรม", "คนสร้าง", "สถานะ", "จำนวนรูป"]] \
            .sort_values("จำนวนรูป", ascending=False)
        st.dataframe(show, width="stretch", hide_index=True)

    st.divider()

    # ---------- ส่วนที่ 3: กิจกรรมที่ต้องดูแล (แจ้งเตือน) ----------
    st.subheader("🔔 กิจกรรมที่ต้องดูแล")
    if activities.empty:
        st.caption("— ไม่มี —")
        return

    last_dt = _last_photo_dt(act_photos)            # activity_id -> วันเวลารูปล่าสุด (Timestamp/NaT)
    counts = _counts_by_activity(act_photos)
    cutoff = now.replace(tzinfo=None) - timedelta(days=30)

    empty_open, stale_open = [], []
    for _, a in activities.iterrows():
        if not is_activity_open(a):   # ข้ามกิจกรรมที่ปิด/หมดอายุ auto-close แล้ว
            continue
        aid = str(a["activity_id"])
        n = int(counts.get(aid, 0))
        if n == 0:
            empty_open.append(a["ชื่อกิจกรรม"])
        else:
            latest = last_dt.get(aid)
            if latest is not None and pd.notna(latest) and latest < cutoff:
                days = (now.replace(tzinfo=None) - latest).days
                stale_open.append(f"{a['ชื่อกิจกรรม']} (ล่าสุด {days} วันก่อน)")

    if not empty_open and not stale_open:
        st.success("✅ ทุกกิจกรรมที่เปิดอยู่มีความเคลื่อนไหวปกติ")
    if empty_open:
        st.warning("📭 เปิดแล้วยังไม่มีรูปเลย: " + " · ".join(empty_open))
    if stale_open:
        st.warning("🕸️ เปิดค้างนาน ไม่มีรูปใหม่เกิน 30 วัน: " + " · ".join(stale_open))


# ==========================================================================
# แท็บ 2: จัดการกิจกรรม (superuser สร้างเอง + เปิด/ปิดได้ทุกกิจกรรม)
# ==========================================================================
def _render_manage_activities():
    su = st.session_state.get("identity", {}).get("username", "superuser")

    # กล่องโชว์รหัสกิจกรรมที่เพิ่งสร้าง (ใช้ session key เดียวกับหน้า admin — reuse _create_activity)
    last = st.session_state.get("admin_last_code")
    if last:
        if last.get("join", JOIN_CODE) == JOIN_OPEN:
            st.success(
                f"✅ สร้างกิจกรรม “{last['name']}” แล้ว — **ไม่ต้องแจกรหัส** "
                "บอกให้เข้าเว็บแล้วกดชื่อกิจกรรมที่หน้าแรกได้เลย"
            )
            with st.expander("อยากได้ QR ไว้แปะหน้างานไหม (ไม่บังคับ)"):
                render_code_with_qr(last["code"], "su_actcode", kind="act")
        else:
            st.success(f"✅ สร้างกิจกรรม “{last['name']}” แล้ว — แจกรหัสนี้ให้ผู้เข้าร่วม:")
            render_code_with_qr(last["code"], "su_actcode", kind="act")
        if st.button("รับทราบ / ปิดข้อความนี้", key="su_dismiss_code"):
            del st.session_state["admin_last_code"]
            st.rerun()

    with st.expander("➕ สร้างกิจกรรมใหม่", expanded=not last):
        with st.form("su_create_activity", clear_on_submit=True):
            name = st.text_input("ชื่อกิจกรรม")
            join = st.radio(
                "ใครส่งรูปเข้ากิจกรรมนี้ได้",
                [JOIN_OPEN, JOIN_CODE],
                captions=["กดจากหน้าแรกส่งได้เลย เหมาะกับงานทั้งโรงงาน เช่น แห่เทียนพรรษา",
                          "ต้องมีรหัสถึงส่งได้ เหมาะกับงานเฉพาะกลุ่ม เช่น ลูกค้าเข้าเยี่ยมชม"],
            )
            code = st.text_input("รหัสเข้ากิจกรรม (เว้นว่าง = สุ่มให้อัตโนมัติ)",
                                 help="ใช้เฉพาะกิจกรรมแบบ 'ต้องมีรหัส'")
            ok = st.form_submit_button("สร้างกิจกรรม", width="stretch")
        if ok:
            _create_activity(su, name, code, join)   # creator = username ของ superuser

    st.divider()

    # รายการ "ทุก" กิจกรรมในระบบ (ของทุก admin) + เปิด/ปิดได้
    st.markdown("**กิจกรรมทั้งหมดในระบบ**")
    df = load_activities()
    if df.empty:
        st.info("ยังไม่มีกิจกรรม — สร้างอันแรกด้านบนได้เลย")
        return

    # นับจากทุกแถว (รวมถังขยะ) เพราะลบกิจกรรม = ลบทุกรูปของมันจริง คำเตือนจะได้ตรงจำนวน
    counts = _counts_by_activity(_activity_photos(load_data()))
    for _, a in df.iterrows():
        aid = str(a["activity_id"])
        n = int(counts.get(aid, 0))
        auto_closed = str(a["สถานะ"]) == "เปิด" and not is_activity_open(a)
        note = " · ⏰ ปิดอัตโนมัติแล้ว (ครบ 7 วัน)" if auto_closed else ""
        join_now = str(a.get(JOIN_HEADER, "")).strip() or JOIN_CODE
        join_label = "🌐 ใครก็ส่งได้" if join_now == JOIN_OPEN else "🔒 ต้องมีรหัส"
        c1, c2, c3 = st.columns([5, 2, 2])
        c1.markdown(
            f"**{a['ชื่อกิจกรรม']}**  \n"
            f"สถานะ: {a['สถานะ']}{note} · {join_label} · 🛠️ {a.get('คนสร้าง','?')} · {n} รูป · สร้างเมื่อ {a.get('วันที่สร้าง','')}"
        )
        _other = JOIN_CODE if join_now == JOIN_OPEN else JOIN_OPEN
        if st.button(("🔒 เปลี่ยนเป็น 'ต้องมีรหัส'" if _other == JOIN_CODE
                      else "🌐 เปลี่ยนเป็น 'ใครก็ส่งได้'"), key=f"su_join_{aid}"):
            set_activity_join(aid, _other)
            st.rerun()
        if str(a["สถานะ"]) == "เปิด":
            if c2.button("⏸️ ปิดกิจกรรม", key=f"su_close_{aid}", width="stretch"):
                set_activity_status(aid, "ปิด")
                st.rerun()
        else:
            if c2.button("▶️ เปิดกิจกรรม", key=f"su_open_{aid}", width="stretch"):
                set_activity_status(aid, "เปิด")
                st.rerun()

        # ลบกิจกรรม "ถาวร" (superuser เท่านั้น) — มีขั้นยืนยัน + เตือนว่ารูปทั้งหมดจะถูกลบด้วย
        del_key = f"su_confirm_delact_{aid}"
        if st.session_state.get(del_key):
            st.error(
                f"⚠️ ลบกิจกรรม **{a['ชื่อกิจกรรม']}** ถาวร? "
                f"รูปทั้งหมด **{n} รูป** จะถูกลบทั้งใน Google Drive และ Sheet — กู้คืนไม่ได้"
            )
            y, no = st.columns(2)
            if y.button("✅ ลบกิจกรรม + รูปทั้งหมด", key=f"su_delact_yes_{aid}", width="stretch"):
                try:
                    su = st.session_state.get("identity", {}).get("username", "superuser")
                    with st.spinner("กำลังลบกิจกรรมและรูปทั้งหมด..."):
                        removed = delete_activity(aid)
                    log_action(su, "superuser", "ลบกิจกรรมถาวร",
                               detail=f"{a['ชื่อกิจกรรม']} (รูป {removed} ใบ)", activity_id=aid)
                    st.session_state.pop(del_key, None)
                    st.cache_data.clear()
                    st.rerun()
                except Exception as e:
                    st.error(f"ลบไม่สำเร็จ: {e}")
            if no.button("❌ ยกเลิก", key=f"su_delact_no_{aid}", width="stretch"):
                st.session_state.pop(del_key, None)
                st.rerun()
        else:
            if c3.button("🗑️ ลบกิจกรรม", key=f"su_delact_{aid}", width="stretch"):
                st.session_state[del_key] = True
                st.rerun()

        # กล่องแชร์อัลบั้ม (superuser จัดการได้ทุกกิจกรรม)
        render_share_panel(aid, str(a["ชื่อกิจกรรม"]), "su")
        st.divider()


# ==========================================================================
# แท็บ 3: คลังภาพทุกกิจกรรม (ของทุก admin)
# ==========================================================================
def _render_all_gallery():
    st.subheader("🖼️ คลังภาพทุกกิจกรรม")

    activities = load_activities()
    sub = _activity_photos(load_active_data())   # ไม่รวมรูปในถังขยะ
    if sub.empty:
        st.info("ยังไม่มีรูปกิจกรรมในระบบ")
        return

    # map activity_id -> ชื่อกิจกรรม / คนสร้าง (ไว้โชว์ใต้รูป + ทำตัวกรอง)
    id2name, id2creator = {}, {}
    if not activities.empty:
        id2name = dict(zip(activities["activity_id"].astype(str), activities["ชื่อกิจกรรม"].astype(str)))
        id2creator = dict(zip(activities["activity_id"].astype(str), activities["คนสร้าง"].astype(str)))

    # ตัวกรอง: เลือกกิจกรรม
    names = ["ทั้งหมด"] + (list(activities["ชื่อกิจกรรม"]) if not activities.empty else [])
    sel = st.selectbox("เลือกกิจกรรม", names, key="su_sel_act")
    if sel != "ทั้งหมด":
        sel_ids = {k for k, v in id2name.items() if v == sel}
        sub = sub[sub["activity_id"].astype(str).isin(sel_ids)]
    if sub.empty:
        st.info("ยังไม่มีรูปในกิจกรรมที่เลือก")
        return

    sub["_dt"] = pd.to_datetime(sub["วันเวลา"], errors="coerce")
    sub = sub.sort_values("_dt", ascending=False)
    st.markdown(f"**พบ {len(sub)} รูป**")

    # ZIP ทั้งหมดที่กรอง
    if st.button("📦 เตรียมไฟล์ ZIP", key="su_zip_btn"):
        with st.spinner("กำลังรวมรูปเป็นไฟล์ ZIP..."):
            items = tuple(
                (extract_file_id(r["ลิงก์รูป"]), r["ชื่อไฟล์"]) for _, r in sub.iterrows()
            )
            st.session_state["su_zip_bytes"] = build_zip(items)
    if st.session_state.get("su_zip_bytes"):
        st.download_button("⬇️ ดาวน์โหลด .zip", data=st.session_state["su_zip_bytes"],
                           file_name="all_activities.zip", mime="application/zip", key="su_zip_dl")

    su = st.session_state.get("identity", {}).get("username", "superuser")
    render_duplicate_scan(sub, "su", su, "superuser")

    st.divider()

    rows = sub.to_dict("records")
    for i in range(0, len(rows), COLS_PER_ROW):
        cols = st.columns(COLS_PER_ROW)
        for col, item in zip(cols, rows[i:i + COLS_PER_ROW]):
            with col:
                file_id = extract_file_id(item["ลิงก์รูป"])
                try:
                    st.image(get_image_bytes(file_id), width="stretch")
                except Exception:
                    st.caption("⚠️ โหลดรูปไม่ได้")
                aid = str(item.get("activity_id"))
                st.caption(
                    f"🎯 {id2name.get(aid, aid)} · 🛠️ {id2creator.get(aid, '?')}  \n"
                    f"👤 {item.get('ผู้ส่ง','')} · 🗓️ {item.get('วันเวลา','')}"
                )
                download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                st.link_button("⬇️ ดาวน์โหลด", download_url, width="stretch")

                render_publish_toggle(item, "su", su, "superuser")

                # ลบรูป → ย้ายไปถังขยะ (กู้คืนได้ ~30 วัน) มีขั้นยืนยัน
                del_key = f"su_confirm_del_{file_id}"
                if st.session_state.get(del_key):
                    st.warning("⚠️ ย้ายรูปนี้ไปถังขยะ? (กู้คืนได้ที่แท็บถังขยะ ~30 วัน)")
                    y, no = st.columns(2)
                    if y.button("✅ ย้ายไปถังขยะ", key=f"su_yes_{file_id}", width="stretch"):
                        try:
                            su = st.session_state.get("identity", {}).get("username", "superuser")
                            trash_photo(file_id, item["ลิงก์รูป"], deleted_by=su)
                            log_action(su, "superuser", "ลบรูป(ถังขยะ)",
                                       detail=str(item.get("ชื่อไฟล์", "")),
                                       activity_id=str(item.get("activity_id", "")))
                            st.session_state.pop(del_key, None)
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"ลบไม่สำเร็จ: {e}")
                    if no.button("❌ ยกเลิก", key=f"su_no_{file_id}", width="stretch"):
                        st.session_state.pop(del_key, None)
                        st.rerun()
                else:
                    if st.button("🗑️ ลบรูปนี้", key=f"su_del_{file_id}", width="stretch"):
                        st.session_state[del_key] = True
                        st.rerun()


# ==========================================================================
# แท็บ 4: ถังขยะ (ทุกกิจกรรม + คลังทั่วไป) — กู้คืน / ลบถาวร
# ==========================================================================
def _render_trash():
    st.subheader("🗑️ ถังขยะ (ทั้งระบบ)")
    st.caption(
        "รูปที่ลบจากทุกที่มารวมกันที่นี่ ~30 วัน แล้ว Google ลบถาวรอัตโนมัติ — "
        "กู้คืนได้ หรือกดลบถาวรทันทีเพื่อคืนพื้นที่"
    )

    trash = load_trash_data()
    if trash.empty:
        st.success("✅ ถังขยะว่าง — ไม่มีรูปที่ถูกลบ")
        return

    activities = load_activities()
    id2name = {}
    if not activities.empty:
        id2name = dict(zip(activities["activity_id"].astype(str), activities["ชื่อกิจกรรม"].astype(str)))

    trash["_dt"] = pd.to_datetime(trash.get("วันที่ลบ"), errors="coerce")
    trash = trash.sort_values("_dt", ascending=False)
    st.markdown(f"**พบ {len(trash)} รูปในถังขยะ**")

    su = st.session_state.get("identity", {}).get("username", "superuser")
    rows = trash.to_dict("records")
    for i in range(0, len(rows), COLS_PER_ROW):
        cols = st.columns(COLS_PER_ROW)
        for col, item in zip(cols, rows[i:i + COLS_PER_ROW]):
            with col:
                file_id = extract_file_id(item["ลิงก์รูป"])
                try:
                    st.image(get_image_bytes(file_id), width="stretch")
                except Exception:
                    st.caption("⚠️ โหลดรูปไม่ได้")
                aid = str(item.get("activity_id", "")).strip()
                where = id2name.get(aid, aid) if aid else "คลังทั่วไป"
                st.caption(
                    f"🎯 {where} · 🗑️ {item.get('วันที่ลบ','')}  \n"
                    f"โดย {item.get('ลบโดย','')}"
                )
                r1, r2 = st.columns(2)
                if r1.button("♻️ กู้คืน", key=f"su_restore_{file_id}", width="stretch"):
                    try:
                        restore_photo(file_id, item["ลิงก์รูป"])
                        log_action(su, "superuser", "กู้คืนรูป",
                                   detail=str(item.get("ชื่อไฟล์", "")), activity_id=aid)
                        st.cache_data.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"กู้คืนไม่สำเร็จ: {e}")

                purge_key = f"su_confirm_purge_{file_id}"
                if st.session_state.get(purge_key):
                    if r2.button("⚠️ ยืนยันลบถาวร", key=f"su_purge_yes_{file_id}", width="stretch"):
                        try:
                            delete_photo(file_id, item["ลิงก์รูป"])
                            log_action(su, "superuser", "ลบรูปถาวร",
                                       detail=str(item.get("ชื่อไฟล์", "")), activity_id=aid)
                            st.session_state.pop(purge_key, None)
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"ลบไม่สำเร็จ: {e}")
                else:
                    if r2.button("🔥 ลบถาวร", key=f"su_purge_{file_id}", width="stretch"):
                        st.session_state[purge_key] = True
                        st.rerun()


# ==========================================================================
# แท็บ 5: จัดการบัญชี admin
# ==========================================================================
def _render_admin_accounts():
    st.subheader("👥 จัดการบัญชี admin")

    _render_pending_approvals()
    _render_reset_requests()

    # ---- ฟอร์มสร้างบัญชีใหม่ ----
    with st.expander("➕ สร้างบัญชี admin ใหม่ (ตั้งรหัสให้เลย)", expanded=False):
        with st.form("create_admin", clear_on_submit=True):
            username = st.text_input("อีเมล (ใช้อีเมลนี้เข้าสู่ระบบ)")
            fullname = st.text_input("ชื่อ-นามสกุล")
            pw = st.text_input("รหัสผ่าน", type="password")
            ok = st.form_submit_button("สร้างบัญชี", width="stretch")
        if ok:
            _create_admin(username, fullname, pw)

    st.divider()

    # ---- รายชื่อบัญชี admin ----
    admins = load_users()
    if admins.empty:
        st.info("ยังไม่มีบัญชี admin — สร้างอันแรกด้านบนได้เลย")
        return

    st.markdown("**รายชื่อบัญชี admin ทั้งหมด**")
    for _, u in admins.iterrows():
        uname = str(u["username"])
        status = str(u.get("สถานะ", ""))
        c1, c2, c3 = st.columns([5, 2, 2])
        email = str(u.get(EMAIL_HEADER, "") or "")
        c1.markdown(
            f"**{uname}** · {u.get('ชื่อ-นามสกุล','')}  \n"
            f"role: {u.get('role','admin')} · สถานะ: {status}"
            + (f" · 📧 {email}" if email else "")
        )
        # ปุ่มเปิด/ปิด (พักการใช้งานชั่วคราว — ข้อมูลยังอยู่)
        if status == "ใช้งาน":
            if c2.button("⏸️ ปิดบัญชี", key=f"su_disable_{uname}", width="stretch"):
                set_user_status(uname, "ปิด")
                st.rerun()
        else:
            if c2.button("▶️ เปิดใช้งาน", key=f"su_enable_{uname}", width="stretch"):
                set_user_status(uname, "ใช้งาน")
                st.rerun()

        # ปุ่มลบถาวร (มีขั้นยืนยันก่อน กันกดพลาด)
        del_key = f"su_confirm_deluser_{uname}"
        if st.session_state.get(del_key):
            st.warning(
                f"⚠️ ลบบัญชี **{uname}** ถาวร? "
                "(กิจกรรมที่บัญชีนี้เคยสร้างและรูปยังอยู่ครบ ไม่ถูกลบ)"
            )
            y, no = st.columns(2)
            if y.button("✅ ลบเลย", key=f"su_deluser_yes_{uname}", width="stretch"):
                delete_user(uname)
                st.session_state.pop(del_key, None)
                st.rerun()
            if no.button("❌ ยกเลิก", key=f"su_deluser_no_{uname}", width="stretch"):
                st.session_state.pop(del_key, None)
                st.rerun()
        else:
            if c3.button("🗑️ ลบบัญชี", key=f"su_deluser_{uname}", width="stretch"):
                st.session_state[del_key] = True
                st.rerun()

        # ตั้งรหัสใหม่ให้ได้ตลอด ไม่ต้องรอเขากดปุ่มลืมรหัส (เผื่อโทรมาบอก/เดินมาบอก)
        with st.expander(f"🔑 ตั้งรหัสใหม่ให้ {uname}"):
            _reset_password_form(uname, "list")


def _render_pending_approvals():
    """
    รายการคนที่ขอเปิดบัญชี admin — "ตั้งรหัสให้ + อนุมัติ" ในปุ่มเดียว หรือ ปฏิเสธ (ลบทิ้ง)

    🔑 คนขอไม่ได้ตั้งรหัสเอง (รหัสในชีตว่าง = login ไม่ได้) → คุณพิมพ์รหัสให้ตรงนี้
       แล้วบอกเจ้าตัวเอง เช่นใช้รหัสเข้าเครื่องของแผนกที่เขาจำได้อยู่แล้ว

    ⚠️ อีเมลในรายการนี้ ระบบ "ไม่ได้ยืนยัน" ว่าเป็นเจ้าของจริง (ไม่ได้ส่งเมลไปเช็ค)
    → อนุมัติเฉพาะคนที่รู้จักตัวจริงเท่านั้น
    """
    pend = pending_users()
    if pend.empty:
        return

    su = st.session_state.get("identity", {}).get("username", "superuser")
    st.warning(f"⏳ มี {len(pend)} คนขอเปิดบัญชี รอคุณตั้งรหัสให้")
    st.caption("อนุมัติเฉพาะคนที่คุณรู้จักตัวจริง — ระบบไม่ได้ส่งเมลยืนยันเจ้าของอีเมล")
    for _, u in pend.iterrows():
        uname = str(u["username"])
        # username = อีเมลอยู่แล้วสำหรับบัญชีใหม่ → ไม่ต้องโชว์ซ้ำ 2 บรรทัด
        mail = str(u.get(EMAIL_HEADER, "") or "")
        st.markdown(f"📧 **{mail or uname}**")

        with st.form(f"su_approve_form_{uname}", clear_on_submit=True):
            f1, f2 = st.columns([5, 2])
            pw = f1.text_input("รหัสที่จะให้เขาใช้", type="password", key=f"su_pw_{uname}",
                               label_visibility="collapsed", placeholder="พิมพ์รหัสที่จะให้เขาใช้")
            go = f2.form_submit_button("✅ อนุมัติ", width="stretch")
        if go:
            if len(str(pw).strip()) < 4:
                st.error("⚠️ พิมพ์รหัสที่จะให้เขาใช้ก่อน (อย่างน้อย 4 ตัว)")
            else:
                # ตั้งรหัสก่อน ค่อยเปิดใช้งาน — ถ้าตั้งรหัสพลาด บัญชีจะยังเข้าไม่ได้ (ปลอดภัยไว้ก่อน)
                if set_user_password(uname, auth.hash_secret(pw)):
                    set_user_status(uname, USER_ACTIVE)
                    log_action(su, "superuser", "อนุมัติบัญชี admin", uname)
                    st.success(f"✅ เปิดบัญชี “{uname}” แล้ว — บอกรหัสให้เจ้าตัวได้เลย")
                    st.rerun()
                else:
                    st.error("❌ ตั้งรหัสไม่สำเร็จ — ลองใหม่อีกครั้ง")

        # ปฏิเสธ = ลบแถวทิ้ง (ยังไม่เคยใช้งาน ไม่มีข้อมูลผูกอยู่) — มีขั้นยืนยันกันกดพลาด
        rej_key = f"su_confirm_reject_{uname}"
        if st.session_state.get(rej_key):
            st.warning(f"⚠️ ปฏิเสธคำขอของ **{uname}**? (ลบทิ้ง เขาสมัครใหม่ได้)")
            y, no = st.columns(2)
            if y.button("✅ ปฏิเสธเลย", key=f"su_reject_yes_{uname}", width="stretch"):
                delete_user(uname)
                log_action(su, "superuser", "ปฏิเสธคำขอสมัคร admin", uname)
                st.session_state.pop(rej_key, None)
                st.rerun()
            if no.button("❌ ยกเลิก", key=f"su_reject_no_{uname}", width="stretch"):
                st.session_state.pop(rej_key, None)
                st.rerun()
        else:
            if st.button("🚫 ปฏิเสธคำขอนี้", key=f"su_reject_{uname}"):
                st.session_state[rej_key] = True
                st.rerun()
        st.divider()


def _reset_password_form(username, key_prefix):
    """ช่องตั้งรหัสใหม่ให้บัญชีหนึ่ง — พิมพ์รหัสที่เจ้าตัวจำได้อยู่แล้ว (เช่นรหัสเข้าเครื่อง) ได้เลย"""
    su = st.session_state.get("identity", {}).get("username", "superuser")
    with st.form(f"{key_prefix}_reset_{username}", clear_on_submit=True):
        pw = st.text_input(f"รหัสใหม่ของ {username}", type="password",
                           help="ใส่รหัสที่เจ้าตัวจำได้อยู่แล้วก็ได้ เช่นรหัสเข้าเครื่องของแผนก")
        ok = st.form_submit_button("🔑 ตั้งรหัสนี้ให้เลย", width="stretch")
    if not ok:
        return
    if len(pw) < 4:
        st.error("⚠️ รหัสสั้นเกินไป (อย่างน้อย 4 ตัว)")
        return
    if set_user_password(username, auth.hash_secret(pw)):
        log_action(su, "superuser", "ตั้งรหัสใหม่ให้ admin", username)
        st.success(f"✅ ตั้งรหัสใหม่ให้ “{username}” แล้ว — บอกเจ้าตัวได้เลย")
        st.rerun()
    else:
        st.error("❌ ไม่พบบัญชีนี้")


def _render_reset_requests():
    """คิว "ลืมรหัสผ่าน" — ใครกดขอมาบ้าง ตั้งรหัสใหม่ให้ได้ตรงนี้เลย"""
    reqs = reset_requests()
    if reqs.empty:
        return
    st.error(f"🔑 มี {len(reqs)} คนลืมรหัส รอคุณตั้งรหัสใหม่ให้")
    for _, u in reqs.iterrows():
        uname = str(u["username"])
        st.markdown(f"**{uname}** · {u.get('ชื่อ-นามสกุล','')} · ขอเมื่อ {u.get(RESET_REQ_HEADER,'')}")
        _reset_password_form(uname, "queue")
    st.divider()


def _create_admin(username, fullname, pw):
    """สร้างบัญชีให้เลย (ไม่ต้องรออนุมัติ) — ใช้ "อีเมล" เป็นชื่อผู้ใช้ เหมือนทางสมัครเอง"""
    username = (username or "").strip().lower()
    fullname = (fullname or "").strip()
    if not username or not pw:
        st.error("⚠️ กรอกอีเมลและรหัสผ่านให้ครบ")
        return
    if find_user(username):
        st.error(f"❌ “{username}” มีบัญชีอยู่แล้ว")
        return
    add_user(username, auth.hash_secret(pw), fullname, role="admin", status="ใช้งาน",
             email=username if "@" in username else "")
    st.success(f"✅ สร้างบัญชี admin “{username}” แล้ว")
    st.rerun()


# ==========================================================================
# แท็บ 6: Log (บันทึกการใช้งาน) — ดู/ค้นว่าใครทำอะไรเมื่อไหร่
# ==========================================================================
def _render_log():
    st.subheader("📋 บันทึกการใช้งาน (Audit Log)")
    st.caption("บันทึกทุกการอัปโหลด/ลบ/กู้คืน — ไว้สืบย้อนว่าใคร ทำอะไร เมื่อไหร่")

    if st.button("🔄 รีเฟรช log", key="log_refresh"):
        load_log.clear()
        st.rerun()

    df = load_log()
    if df.empty:
        st.info("ยังไม่มีบันทึกการใช้งาน")
        return

    df = df.copy()
    # แปลง activity_id → ชื่อกิจกรรม (อ่านง่ายขึ้น)
    acts = load_activities()
    id2name = {}
    if not acts.empty and "activity_id" in acts.columns:
        id2name = dict(zip(acts["activity_id"].astype(str), acts["ชื่อกิจกรรม"].astype(str)))
    if "activity_id" in df.columns:
        df["กิจกรรม"] = df["activity_id"].astype(str).map(
            lambda a: id2name.get(a, a) if str(a).strip() else "-")

    # เรียงใหม่สุดก่อน
    df["_dt"] = pd.to_datetime(df.get("เวลา"), errors="coerce")
    df = df.sort_values("_dt", ascending=False)

    # ---- ตัวกรอง ----
    c1, c2, c3 = st.columns(3)
    with c1:
        actions = ["ทั้งหมด"] + sorted(a for a in df.get("การกระทำ", pd.Series(dtype=str)).astype(str).unique() if a)
        fa = st.selectbox("การกระทำ", actions, key="log_f_action")
    with c2:
        roles = ["ทั้งหมด"] + sorted(r for r in df.get("role", pd.Series(dtype=str)).astype(str).unique() if r)
        fr = st.selectbox("role", roles, key="log_f_role")
    with c3:
        kw = st.text_input("ค้นหา (ผู้ทำ / รายละเอียด)", key="log_f_kw")

    f = df
    if fa != "ทั้งหมด" and "การกระทำ" in f.columns:
        f = f[f["การกระทำ"].astype(str) == fa]
    if fr != "ทั้งหมด" and "role" in f.columns:
        f = f[f["role"].astype(str) == fr]
    if kw.strip():
        k = kw.strip().lower()
        m = pd.Series(False, index=f.index)
        for col in ("ผู้ทำ", "รายละเอียด"):
            if col in f.columns:
                m = m | f[col].astype(str).str.lower().str.contains(k, na=False)
        f = f[m]

    st.markdown(f"**{len(f)} รายการ** (ใหม่สุดก่อน · โชว์สูงสุด 500)")
    show_cols = [c for c in ["เวลา", "ผู้ทำ", "role", "การกระทำ", "รายละเอียด", "กิจกรรม"] if c in f.columns]
    st.dataframe(f[show_cols].head(500), width="stretch", hide_index=True)


# ==========================================================================
# แท็บ 7: คลังภาพทั่วไป (ระบบเดิม) — reuse 3 หน้าเดิม
# ==========================================================================
def _render_general():
    st.subheader("📁 คลังภาพทั่วไป (ระบบเดิม)")
    st.caption("superuser เข้าถึงคลังเก่าได้เต็มรูปแบบ")
    sub_up, sub_gal, sub_dash = st.tabs(["📤 ส่งรูป", "🖼️ คลังภาพ", "📊 Dashboard"])
    with sub_up:
        page_upload.render()
    with sub_gal:
        page_gallery.render()
    with sub_dash:
        page_dashboard.render()


# ==========================================================================
# helper
# ==========================================================================
def _activity_photos(photos: pd.DataFrame) -> pd.DataFrame:
    """กรองเฉพาะรูปที่เป็นของ 'กิจกรรม' (activity_id ไม่ว่าง)"""
    if photos.empty or "activity_id" not in photos.columns:
        return photos.iloc[0:0] if not photos.empty else pd.DataFrame()
    aid = photos["activity_id"].astype(str).str.strip()
    return photos[aid != ""].copy()


def _counts_by_activity(act_photos: pd.DataFrame) -> dict:
    """นับจำนวนรูปต่อ activity_id — คืน dict {activity_id: count}"""
    if act_photos.empty:
        return {}
    return act_photos["activity_id"].astype(str).value_counts().to_dict()


def _last_photo_dt(act_photos: pd.DataFrame) -> dict:
    """วันเวลารูปล่าสุดต่อ activity_id — คืน dict {activity_id: Timestamp}"""
    if act_photos.empty:
        return {}
    tmp = act_photos.copy()
    tmp["_dt"] = pd.to_datetime(tmp["วันเวลา"], errors="coerce")
    return tmp.groupby(tmp["activity_id"].astype(str))["_dt"].max().to_dict()


def _open_count(activities: pd.DataFrame) -> int:
    """นับกิจกรรมที่ 'เปิดอยู่จริง' (รวมผล auto-close) — ไม่ใช่แค่สถานะในชีต"""
    if activities.empty or "สถานะ" not in activities.columns:
        return 0
    return int(activities.apply(is_activity_open, axis=1).sum())
