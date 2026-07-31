# -*- coding: utf-8 -*-
"""
page_activity_admin.py — หน้าของ "admin / หัวหน้า" (role = admin)
3 แท็บ:
  1) กิจกรรมของฉัน — สร้างกิจกรรม (ตั้ง/สุ่มรหัส) + เปิด/ปิด
  2) คลังภาพกิจกรรม — เห็นเฉพาะกิจกรรมที่ตัวเองสร้าง + ดาวน์โหลด/ลบรูป
  3) ภาพรวม — สรุปจำนวนกิจกรรม/รูปของตัวเอง

admin เห็นเฉพาะกิจกรรมที่ "คนสร้าง" = username ของตัวเองเท่านั้น
"""

import secrets as pysecrets
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd

import auth
from google_utils import (
    load_activities, add_activity, set_activity_status, delete_activity,
    archive_activity, restore_activity, sync_auto_closed, filter_activities,
    ACT_OPEN, ACT_CLOSED, ACT_ARCHIVED, ACT_DELETED, AUTO_CLOSE_DAYS,
    load_data, load_active_data, load_trash_data,
    get_image_bytes, get_thumbnail, extract_file_id, trash_photo, restore_photo, log_action, is_activity_open, is_activity_expired,
    activity_status_label, nav_tabs,
    get_activity_visibility, set_activity_visibility, activity_shares, add_share, delete_share,
    VIS_PUBLIC, VIS_PRIVATE, group_duplicates,
    set_activity_join, JOIN_HEADER, JOIN_OPEN, JOIN_CODE,
    set_photo_published, PUBLISHED_HEADER, PUBLISHED_YES,
)
from page_gallery import build_zip, COLS_PER_ROW
from qr_utils import qr_png

# URL ของแอป (ใช้ทำ QR deep-link) — ตั้ง APP_URL ใน secrets ได้ ถ้าไม่ตั้งใช้ค่าเริ่มต้นนี้
_DEFAULT_APP_URL = "https://image-warehouse-mis.streamlit.app"


def _app_url() -> str:
    try:
        u = str(st.secrets.get("APP_URL", "")).strip().rstrip("/")
        return u or _DEFAULT_APP_URL
    except Exception:
        return _DEFAULT_APP_URL

# ตัวอักษรสำหรับสุ่มรหัส (ตัด 0/O/1/I ที่สับสนง่ายออก)
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _gen_code(n: int = 6) -> str:
    """สุ่มรหัสกิจกรรม n ตัว"""
    return "".join(pysecrets.choice(_CODE_ALPHABET) for _ in range(n))


def _gen_activity_id() -> str:
    """สร้าง activity_id ที่ไม่ซ้ำ (เวลา + สุ่มท้าย)"""
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    return "ACT_" + now.strftime("%Y%m%d_%H%M%S") + "_" + pysecrets.token_hex(2)


def render():
    username = st.session_state.get("identity", {}).get("username", "")
    # nav_tabs (จำหน้าที่เปิดข้าม rerun) แทน st.tabs ที่เด้งกลับแท็บแรกหลังกดปุ่ม (#K)
    T_ACT = "🎯 กิจกรรมของฉัน"
    T_GALLERY = "🖼️ คลังภาพกิจกรรม"
    T_TRASH = "🗑️ ถังขยะ"
    T_DASH = "📊 ภาพรวม"
    choice = nav_tabs("adm_nav", [T_ACT, T_GALLERY, T_TRASH, T_DASH])
    if choice == T_ACT:
        _render_activities(username)
    elif choice == T_GALLERY:
        _render_gallery(username)
    elif choice == T_TRASH:
        _render_trash(username)
    elif choice == T_DASH:
        _render_dashboard(username)


# --------------------------------------------------------------------------
# แท็บ 1: กิจกรรมของฉัน
# --------------------------------------------------------------------------
def _render_activities(username):
    st.subheader("🎯 กิจกรรมของฉัน")

    # เปลี่ยนรหัสผ่านของตัวเอง — พับไว้ ไม่เกะกะ (ไม่บังคับ อยากเปลี่ยนค่อยกด)
    auth.render_change_password_box()

    # กล่องโชว์รหัสกิจกรรมที่เพิ่งสร้าง (ให้ก๊อปไปแจกลูกน้อง)
    last = st.session_state.get("admin_last_code")
    if last:
        if last.get("join", JOIN_CODE) == JOIN_OPEN:
            st.success(
                f"✅ สร้างกิจกรรม “{last['name']}” แล้ว — **ไม่ต้องแจกรหัส** "
                "บอกให้เข้าเว็บแล้วกดชื่อกิจกรรมที่หน้าแรกได้เลย"
            )
            with st.expander("อยากได้ QR ไว้แปะหน้างานไหม (ไม่บังคับ)"):
                render_code_with_qr(last["code"], "adm_actcode", kind="act")
        else:
            st.success(f"✅ สร้างกิจกรรม “{last['name']}” แล้ว — แจกรหัสนี้ให้ลูกน้องเข้าร่วม:")
            render_code_with_qr(last["code"], "adm_actcode", kind="act")
        if st.button("รับทราบ / ปิดข้อความนี้", key="dismiss_code"):
            del st.session_state["admin_last_code"]
            st.rerun()

    # ฟอร์มสร้างกิจกรรมใหม่
    with st.expander("➕ สร้างกิจกรรมใหม่", expanded=not last):
        with st.form("create_activity", clear_on_submit=True):
            name = st.text_input("ชื่อกิจกรรม")
            join = st.radio(
                "ใครส่งรูปเข้ากิจกรรมนี้ได้",
                [JOIN_OPEN, JOIN_CODE],
                captions=["กดจากหน้าแรกส่งได้เลย เหมาะกับงานทั้งโรงงาน เช่น แห่เทียนพรรษา",
                          "ต้องมีรหัสถึงส่งได้ เหมาะกับงานเฉพาะกลุ่ม เช่น ลูกค้าเข้าเยี่ยมชม"],
                horizontal=False,
            )
            code = st.text_input("รหัสเข้ากิจกรรม (เว้นว่าง = สุ่มให้อัตโนมัติ)",
                                 help="ใช้เฉพาะกิจกรรมแบบ 'ต้องมีรหัส' — แบบใครก็ได้ไม่ต้องใช้")
            ok = st.form_submit_button("สร้างกิจกรรม", width="stretch")
        if ok:
            _create_activity(username, name, code, join)

    st.divider()

    # ครบ 7 วัน → ปิดสถานะให้จริงในชีต ไม่ต้องให้คนสร้างมากดปิดเอง (#N)
    # ทำก่อนอ่านรายการ เพื่อให้ป้ายสถานะ/ตัวกรองด้านล่างตรงกับของจริงในรอบเดียวกัน
    try:
        closed_now = sync_auto_closed()
        if closed_now:
            st.info(f"🕐 ปิดกิจกรรมที่ครบ {AUTO_CLOSE_DAYS} วันให้อัตโนมัติแล้ว {closed_now} กิจกรรม "
                    "— ยังเปิดให้ดูรูปย้อนหลังได้ตามเดิม")
    except Exception:
        pass    # ปิดสถานะไม่สำเร็จก็แค่ยังโชว์ 'ปิดรับรูปแล้ว' เหมือนเดิม ไม่ให้หน้าพัง

    # รายการกิจกรรมของตัวเอง
    df = load_activities()
    mine = _my_activities(df, username)
    if mine.empty:
        st.info("คุณยังไม่ได้สร้างกิจกรรม — สร้างอันแรกด้านบนได้เลย")
        return

    total = len(mine)
    mine = filter_activities(mine, render_activity_filter("adm_act_filter"))
    if mine.empty:
        st.info(f"ไม่มีกิจกรรมในกลุ่มนี้ (คุณมีทั้งหมด {total} กิจกรรม — เลือก 'ทั้งหมด' เพื่อดูทุกอัน)")
        return

    photos = load_data()
    for _, a in mine.iterrows():
        aid = str(a["activity_id"])
        n = _count_photos(photos, aid)
        # ป้ายสถานะเดียวสื่อชัด ไม่โชว์ 'เปิด · ปิดอัตโนมัติแล้ว' ขัดกัน (#L)
        status_label = activity_status_label(a)
        join_now = str(a.get(JOIN_HEADER, "")).strip() or JOIN_CODE
        join_label = "🌐 ใครก็ส่งได้" if join_now == JOIN_OPEN else "🔒 ต้องมีรหัส"
        closed_out = str(a.get("สถานะ", "")).strip() in (ACT_ARCHIVED, ACT_DELETED)
        c1, c2 = st.columns([7, 2])
        c1.markdown(
            f"**{a['ชื่อกิจกรรม']}**  \n"
            f"สถานะ: {status_label} · {join_label} · {n} รูป · สร้างเมื่อ {a['วันที่สร้าง']}"
        )
        if not closed_out:
            if str(a["สถานะ"]) == ACT_OPEN:
                if c2.button("⏸️ ปิดกิจกรรม", key=f"close_{aid}", width="stretch"):
                    set_activity_status(aid, ACT_CLOSED)
                    st.rerun()
            elif is_activity_expired(a.get("วันที่สร้าง")):
                # ครบ 7 วันแล้วเปิดใหม่ไม่ได้ — กดไปก็ถูก sync ปิดกลับทันที (#N) จะงงเปล่าๆ
                c2.button("▶️ เปิดกิจกรรม", key=f"open_{aid}", width="stretch", disabled=True,
                          help=f"ครบ {AUTO_CLOSE_DAYS} วันแล้ว รับรูปเพิ่มไม่ได้ — "
                               "ถ้าต้องรับรูปอีก ให้สร้างกิจกรรมใหม่ (รูปเก่ายังดูย้อนหลังได้)")
            else:
                if c2.button("▶️ เปิดกิจกรรม", key=f"open_{aid}", width="stretch"):
                    set_activity_status(aid, ACT_OPEN)
                    st.rerun()

            # สลับโหมดการส่งรูปได้ทีหลัง (เผลอตั้งผิด/เปลี่ยนใจ)
            other = JOIN_CODE if join_now == JOIN_OPEN else JOIN_OPEN
            swap_label = ("🔒 เปลี่ยนเป็น 'ต้องมีรหัส'" if other == JOIN_CODE
                          else "🌐 เปลี่ยนเป็น 'ใครก็ส่งได้'")
            if st.button(swap_label, key=f"adm_join_{aid}"):
                set_activity_join(aid, other)
                st.rerun()

        # ปุ่มตอนจบกิจกรรม — admin ได้แค่ 🗑️ ลบ (กิจกรรมที่ยังไม่มีรูป) → ถังขยะ 30 วัน
        # "เก็บเข้าคลัง" ไม่ให้สิทธิ์ admin เพราะเป็นการเอารูปไปโชว์ในคลังภาพทั่วไปที่คนทั้งบริษัทเห็น
        render_activity_end_actions(a, n, "adm", username, "admin",
                                    delete_needs_empty=True, can_archive=False)

        # กล่องแชร์อัลบั้ม (ทุกคน/เฉพาะคน + รายชื่อคนดู + รหัสส่วนตัว)
        render_share_panel(aid, str(a["ชื่อกิจกรรม"]), "adm")
        st.divider()


def _create_activity(username, name, code, join=JOIN_OPEN):
    if not name.strip():
        st.error("⚠️ กรอกชื่อกิจกรรมก่อน")
        return
    # ออกรหัสให้เสมอ แม้เป็นแบบ "ใครก็ได้" — เผื่อวันหลังเปลี่ยนใจสลับเป็นแบบต้องมีรหัส จะได้มีรหัสพร้อมใช้
    code = code.strip() or _gen_code()
    code_hash = auth.hash_secret(code)

    # กันรหัสซ้ำกับกิจกรรมที่ "เปิด" อยู่ (ไม่งั้น user login แล้วสับสนว่าเข้ากิจกรรมไหน)
    df = load_activities()
    if not df.empty and "รหัสเข้า_hash" in df.columns:
        dup = df[(df["รหัสเข้า_hash"].astype(str) == code_hash)
                 & (df["สถานะ"].astype(str) == "เปิด")]
        if not dup.empty:
            st.error("❌ รหัสนี้ถูกใช้กับกิจกรรมที่เปิดอยู่แล้ว — เปลี่ยนรหัสใหม่")
            return

    aid = _gen_activity_id()
    now = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d %H:%M:%S")
    add_activity(aid, name.strip(), code_hash, username, now, "เปิด", join=join)
    st.session_state["admin_last_code"] = {"name": name.strip(), "code": code, "join": join}
    st.rerun()


# --------------------------------------------------------------------------
# แท็บ 2: คลังภาพกิจกรรม (เฉพาะของตัวเอง) + ลบรูป
# --------------------------------------------------------------------------
def _render_gallery(username):
    st.subheader("🖼️ คลังภาพกิจกรรมของฉัน")

    mine = _my_activities(load_activities(), username)
    if mine.empty:
        st.info("ยังไม่มีกิจกรรม — สร้างที่แท็บ 'กิจกรรมของฉัน' ก่อน")
        return

    names = list(mine["ชื่อกิจกรรม"])
    sel = st.selectbox("เลือกกิจกรรม", ["ทั้งหมด"] + names)

    photos = load_active_data()   # ไม่รวมรูปในถังขยะ
    if photos.empty or "activity_id" not in photos.columns:
        st.info("ยังไม่มีรูปในกิจกรรมของคุณ")
        return

    my_ids = set(mine["activity_id"].astype(str))
    sub = photos[photos["activity_id"].astype(str).isin(my_ids)].copy()
    if sel != "ทั้งหมด":
        sel_ids = set(mine[mine["ชื่อกิจกรรม"] == sel]["activity_id"].astype(str))
        sub = sub[sub["activity_id"].astype(str).isin(sel_ids)]
    if sub.empty:
        st.info("ยังไม่มีรูปในกิจกรรมที่เลือก")
        return

    sub["_dt"] = pd.to_datetime(sub["วันเวลา"], errors="coerce")
    sub = sub.sort_values("_dt", ascending=False)
    id2name = dict(zip(mine["activity_id"].astype(str), mine["ชื่อกิจกรรม"].astype(str)))
    st.markdown(f"**พบ {len(sub)} รูป**")

    # ZIP
    if st.button("📦 เตรียมไฟล์ ZIP", key="adm_zip_btn"):
        with st.spinner("กำลังรวมรูปเป็นไฟล์ ZIP..."):
            items = tuple(
                (extract_file_id(r["ลิงก์รูป"]), r["ชื่อไฟล์"]) for _, r in sub.iterrows()
            )
            st.session_state["adm_zip_bytes"] = build_zip(items)
    if st.session_state.get("adm_zip_bytes"):
        st.download_button("⬇️ ดาวน์โหลด .zip", data=st.session_state["adm_zip_bytes"],
                           file_name="activity_photos.zip", mime="application/zip", key="adm_zip_dl")

    render_duplicate_scan(sub, "adm", username, "admin")

    st.divider()

    rows = sub.to_dict("records")
    for i in range(0, len(rows), COLS_PER_ROW):
        cols = st.columns(COLS_PER_ROW)
        for j, (col, item) in enumerate(zip(cols, rows[i:i + COLS_PER_ROW])):
            with col:
                file_id = extract_file_id(item["ลิงก์รูป"])
                # ใส่ลำดับแถวในคีย์ด้วย: extract_file_id คืน "" ถ้าลิงก์เสีย → 2 ใบขึ้นไปคีย์ชนกัน แท็บล่ม
                uid = f"{i + j}_{file_id}"
                try:
                    st.image(get_thumbnail(file_id), width="stretch")
                except Exception:
                    st.caption("⚠️ โหลดรูปไม่ได้")
                act_name = id2name.get(str(item.get("activity_id")), "")
                st.caption(f"🎯 {act_name} · 👤 {item.get('ผู้ส่ง','')} · 🗓️ {item.get('วันเวลา','')}")
                download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                st.link_button("⬇️ ดาวน์โหลด", download_url, width="stretch")

                render_publish_toggle(item, f"adm{uid}", username, "admin")

                # ลบรูป → ย้ายไปถังขยะ (กู้คืนได้ ~30 วัน) มีขั้นยืนยัน
                del_key = f"adm_confirm_del_{uid}"
                if st.session_state.get(del_key):
                    st.warning("⚠️ ย้ายรูปนี้ไปถังขยะ? (กู้คืนได้ที่แท็บถังขยะ ~30 วัน)")
                    y, no = st.columns(2)
                    if y.button("✅ ย้ายไปถังขยะ", key=f"adm_yes_{uid}", width="stretch"):
                        try:
                            trash_photo(file_id, item["ลิงก์รูป"], deleted_by=username)
                            log_action(username, "admin", "ลบรูป(ถังขยะ)",
                                       detail=str(item.get("ชื่อไฟล์", "")),
                                       activity_id=str(item.get("activity_id", "")))
                            st.session_state.pop(del_key, None)
                            # trash_photo ล้าง load_data, log_action ล้าง load_log อยู่แล้ว
                            st.rerun()
                        except Exception as e:
                            st.error(f"ลบไม่สำเร็จ: {e}")
                    if no.button("❌ ยกเลิก", key=f"adm_no_{uid}", width="stretch"):
                        st.session_state.pop(del_key, None)
                        st.rerun()
                else:
                    if st.button("🗑️ ลบรูปนี้", key=f"adm_del_{uid}", width="stretch"):
                        st.session_state[del_key] = True
                        st.rerun()


# --------------------------------------------------------------------------
# แท็บ 3: ถังขยะ (เฉพาะกิจกรรมของตัวเอง) — กู้คืนได้
# --------------------------------------------------------------------------
def _render_trash(username):
    st.subheader("🗑️ ถังขยะกิจกรรมของฉัน")
    st.caption("รูปที่ลบจะพักที่นี่ ~30 วัน แล้ว Google จะลบถาวรอัตโนมัติ — กู้คืนได้ก่อนครบกำหนด")

    mine = _my_activities(load_activities(), username)
    if mine.empty:
        st.info("ยังไม่มีกิจกรรม")
        return

    my_ids = set(mine["activity_id"].astype(str))
    trash = load_trash_data()
    if not trash.empty and "activity_id" in trash.columns:
        trash = trash[trash["activity_id"].astype(str).isin(my_ids)].copy()
    if trash.empty:
        st.success("✅ ถังขยะว่าง — ไม่มีรูปที่ถูกลบ")
        return

    id2name = dict(zip(mine["activity_id"].astype(str), mine["ชื่อกิจกรรม"].astype(str)))
    trash["_dt"] = pd.to_datetime(trash.get("วันที่ลบ"), errors="coerce")
    trash = trash.sort_values("_dt", ascending=False)
    st.markdown(f"**พบ {len(trash)} รูปในถังขยะ**")

    rows = trash.to_dict("records")
    for i in range(0, len(rows), COLS_PER_ROW):
        cols = st.columns(COLS_PER_ROW)
        for j, (col, item) in enumerate(zip(cols, rows[i:i + COLS_PER_ROW])):
            with col:
                file_id = extract_file_id(item["ลิงก์รูป"])
                uid = f"{i + j}_{file_id}"      # ใส่ลำดับกันคีย์ชนตอนลิงก์เสีย
                try:
                    st.image(get_thumbnail(file_id), width="stretch")
                except Exception:
                    st.caption("⚠️ โหลดรูปไม่ได้")
                act_name = id2name.get(str(item.get("activity_id")), "")
                st.caption(
                    f"🎯 {act_name} · 🗑️ ลบเมื่อ {item.get('วันที่ลบ','')}  \n"
                    f"โดย {item.get('ลบโดย','')}"
                )
                if st.button("♻️ กู้คืนรูปนี้", key=f"adm_restore_{uid}", width="stretch"):
                    try:
                        restore_photo(file_id, item["ลิงก์รูป"])
                        log_action(username, "admin", "กู้คืนรูป",
                                   detail=str(item.get("ชื่อไฟล์", "")),
                                   activity_id=str(item.get("activity_id", "")))
                        # restore_photo ล้าง load_data, log_action ล้าง load_log อยู่แล้ว
                        st.rerun()
                    except Exception as e:
                        st.error(f"กู้คืนไม่สำเร็จ: {e}")


# --------------------------------------------------------------------------
# แท็บ 4: ภาพรวม (เฉพาะของตัวเอง)
# --------------------------------------------------------------------------
def _render_dashboard(username):
    st.subheader("📊 ภาพรวมกิจกรรมของฉัน")

    mine = _my_activities(load_activities(), username)
    if mine.empty:
        st.info("ยังไม่มีข้อมูล")
        return

    photos = load_active_data()   # นับเฉพาะรูปที่ยังไม่ถูกลบ (ไม่รวมถังขยะ)
    my_ids = set(mine["activity_id"].astype(str))
    my_photos = photos[photos["activity_id"].astype(str).isin(my_ids)].copy() \
        if (not photos.empty and "activity_id" in photos.columns) else pd.DataFrame()

    open_count = int((mine["สถานะ"].astype(str) == "เปิด").sum())
    c1, c2, c3 = st.columns(3)
    c1.metric("🎯 กิจกรรมทั้งหมด", len(mine))
    c2.metric("🟢 เปิดอยู่", open_count)
    c3.metric("📷 รูปรวม", len(my_photos))

    st.divider()
    st.markdown("**จำนวนรูปแยกตามกิจกรรม**")
    if my_photos.empty:
        st.caption("ยังไม่มีรูป")
        return
    id2name = dict(zip(mine["activity_id"].astype(str), mine["ชื่อกิจกรรม"].astype(str)))
    counts = my_photos["activity_id"].astype(str).map(id2name).value_counts()
    st.bar_chart(counts)


# --------------------------------------------------------------------------
# กล่องแชร์อัลบั้ม (ใช้ร่วมกันทั้งหน้า admin และ superuser)
# --------------------------------------------------------------------------
def render_activity_filter(key: str) -> str:
    """
    (#O) ตัวกรองรายการกิจกรรม — เปิด (ค่าเริ่มต้น) / ปิด / เก็บเข้าคลัง / ทั้งหมด

    หัวหน้าสั่ง: "default โชว์แต่กิจที่เปิด ไม่งั้นยาว" · เก็บค่าที่เลือกไว้ใน session_state
    (แบบเดียวกับ nav_tabs #K) → กดปุ่มอะไรแล้ว rerun ก็ยังอยู่ตัวกรองเดิม
    คืนค่าที่เลือก เอาไปส่งให้ google_utils.filter_activities()
    """
    labels = {
        ACT_OPEN: "🟢 ที่เปิดอยู่",
        ACT_CLOSED: "⏸️ ที่ปิดแล้ว",
        ACT_ARCHIVED: "📦 เก็บเข้าคลัง",
        "ทั้งหมด": "ทั้งหมด",
    }
    options = list(labels)
    if st.session_state.get(key) not in options:
        st.session_state[key] = ACT_OPEN      # ค่าเริ่มต้น = เฉพาะที่เปิดอยู่
    return st.radio("แสดงกิจกรรม", options, key=key, horizontal=True,
                    format_func=lambda v: labels[v],
                    help="ที่ปิด/เก็บเข้าคลัง/ลบแล้ว ถูกซ่อนไว้กันรายการยาว — เลือก 'ทั้งหมด' เพื่อดูทุกอัน")


def render_activity_end_actions(a, n, key_prefix, who, role,
                                delete_needs_empty=False, can_archive=True):
    """
    ปุ่ม "ตอนจบกิจกรรม" ใช้ร่วมกันทั้งหน้า admin และ superuser — 2 ทางเลือกที่แยกกันชัด:
      ① 📦 เก็บเข้าคลัง (#P)  = จบงานปกติ **ไม่มีอะไรหาย** รูปไปรวมเป็นโฟลเดอร์ชื่อกิจกรรม
                                 ในคลังภาพทั่วไป · กิจกรรมหายจากรายการจัดการ  ← ปุ่มหลัก
      ② 🗑️ ลบกิจกรรม (#Q)   = อยากเอาออกจริง รูปลงถังขยะ 30 วัน กู้คืนได้     ← ปุ่มรอง

    delete_needs_empty=True (หน้า admin) = ลบได้เฉพาะกิจกรรมที่ยังไม่มีรูป — ของเดิม กันเผลอ
    ลบรูปลูกน้องหลุดมือ (กิจกรรมที่มีรูปต้องให้ superuser ลบ)
    can_archive=False (หน้า admin) = ไม่ให้สิทธิ์เก็บเข้าคลัง — การเอารูปกิจกรรมออกไปโชว์ใน
    "คลังภาพทั่วไป" ที่คนทั้งบริษัทเห็น ควรเป็นการตัดสินใจของผู้ดูแลระบบเท่านั้น
    """
    aid = str(a["activity_id"])
    name = str(a["ชื่อกิจกรรม"])
    status = str(a.get("สถานะ", "")).strip()

    # กิจกรรมที่เก็บเข้าคลัง/ลบแล้ว → เหลือปุ่มเดียวคือเอากลับมาจัดการ
    if status in (ACT_ARCHIVED, ACT_DELETED):
        if status == ACT_ARCHIVED and not can_archive:
            st.caption("📦 เก็บเข้าคลังแล้ว — ถ้าต้องเอากลับมาจัดการ แจ้งผู้ดูแลระบบ")
            return
        back = "♻️ กู้คืนกิจกรรม" if status == ACT_DELETED else "♻️ เอากลับมาจัดการ"
        if st.button(back, key=f"{key_prefix}_unarchive_{aid}", width="stretch"):
            try:
                with st.spinner("กำลังกู้คืน..."):
                    got = restore_activity(aid)
                log_action(who, role, "กู้คืนกิจกรรม",
                           detail=f"{name} (รูป {got} ใบ)" if got else name, activity_id=aid)
                st.rerun()
            except Exception as e:
                st.error(f"กู้คืนไม่สำเร็จ: {e}")
        return

    c_arch, c_del = st.columns(2) if can_archive else (None, st.columns(1)[0])

    # ---------- ① เก็บเข้าคลัง (เฉพาะผู้ดูแลระบบ) ----------
    arch_key = f"{key_prefix}_confirm_arch_{aid}"
    if can_archive and c_arch.button(
            "📦 เก็บเข้าคลัง", key=f"{key_prefix}_arch_{aid}", width="stretch",
            help="จบกิจกรรม แล้วย้ายรูปทั้งหมดไปเก็บเป็นโฟลเดอร์ในคลังภาพทั่วไป (ไม่มีรูปหาย)"):
        st.session_state[arch_key] = True
        st.rerun()
    if can_archive and st.session_state.get(arch_key):
        st.info(
            f"📦 เก็บกิจกรรม **{name}** เข้าคลัง? รูป **{n} ใบ** จะไปโผล่เป็นโฟลเดอร์ "
            f"“{name}” ในคลังภาพทั่วไป (ดู/ดาวน์โหลดได้ ไม่มีรูปหาย) · กิจกรรมจะถูกซ่อนจากรายการนี้ "
            "— เอากลับมาได้ทีหลัง"
        )
        y, no = st.columns(2)
        if y.button("✅ เก็บเข้าคลังเลย", key=f"{key_prefix}_arch_yes_{aid}", width="stretch"):
            try:
                with st.spinner("กำลังย้ายรูปเข้าคลังภาพทั่วไป..."):
                    moved = archive_activity(aid)
                log_action(who, role, "เก็บกิจกรรมเข้าคลัง",
                           detail=f"{name} (รูป {moved} ใบ)", activity_id=aid)
                st.session_state.pop(arch_key, None)
                st.rerun()
            except Exception as e:
                st.error(f"เก็บเข้าคลังไม่สำเร็จ: {e}")
        if no.button("❌ ยกเลิก", key=f"{key_prefix}_arch_no_{aid}", width="stretch"):
            st.session_state.pop(arch_key, None)
            st.rerun()

    # ---------- ② ลบกิจกรรม → ถังขยะ 30 วัน ----------
    del_key = f"{key_prefix}_confirm_delact_{aid}"
    busy_hint = ("มีรูปแล้ว ลบไม่ได้ — ใช้ '📦 เก็บเข้าคลัง' แทน" if can_archive
                 else "มีรูปแล้ว ลบไม่ได้ — แจ้งผู้ดูแลระบบให้จัดการแทน")
    if delete_needs_empty and n > 0:
        c_del.button("🗑️ ลบกิจกรรม", key=f"{key_prefix}_delact_{aid}", width="stretch",
                     disabled=True, help=busy_hint)
    elif c_del.button("🗑️ ลบกิจกรรม", key=f"{key_prefix}_delact_{aid}", width="stretch",
                      help="รูปจะไปอยู่ถังขยะ 30 วัน กู้คืนได้"):
        st.session_state[del_key] = True
        st.rerun()

    if st.session_state.get(del_key):
        st.warning(
            f"⚠️ ลบกิจกรรม **{name}**? รูป **{n} ใบ** จะถูกย้ายไป **ถังขยะ** "
            "(กู้คืนได้ ~30 วัน แล้ว Google จะลบถาวรอัตโนมัติ)"
        )
        y, no = st.columns(2)
        if y.button("✅ ลบเลย (ลงถังขยะ)", key=f"{key_prefix}_delact_yes_{aid}", width="stretch"):
            try:
                # อ่านสดอีกครั้ง กันมีรูปเพิ่งถูกส่งเข้ามาหลังหน้าโหลด (admin ลบได้เฉพาะกิจกรรมว่าง)
                if delete_needs_empty:
                    load_data.clear()
                    if _count_photos(load_data(), aid) > 0:
                        st.error(f"❌ มีรูปเข้ามาในกิจกรรมนี้แล้ว — {busy_hint}")
                        st.session_state.pop(del_key, None)
                        return
                with st.spinner("กำลังย้ายรูปเข้าถังขยะ..."):
                    moved = delete_activity(aid, deleted_by=who)
                log_action(who, role, "ลบกิจกรรม(ถังขยะ)",
                           detail=f"{name} (รูป {moved} ใบ)", activity_id=aid)
                st.session_state.pop(del_key, None)
                st.rerun()
            except Exception as e:
                st.error(f"ลบไม่สำเร็จ: {e}")
        if no.button("❌ ยกเลิก", key=f"{key_prefix}_delact_no_{aid}", width="stretch"):
            st.session_state.pop(del_key, None)
            st.rerun()


def render_code_with_qr(code, key_prefix, kind="view"):
    """
    โชว์รหัส (ตัวอักษร) + ปุ่มเปิด/ปิด QR แบบ deep-link ของรหัสนั้น
    - รหัสตัวอักษรโชว์เสมอ (ก๊อป/พิมพ์ได้ตามเดิม)
    - QR เก็บลิงก์ deep-link: kind="view" → ?viewcode (สแกนแล้วเข้าอัลบั้มเลย)
                              kind="act"  → ?actcode  (สแกนแล้วเปิดหน้าส่งรูป + เติมรหัสให้)
    """
    st.code(code, language=None)
    param = "viewcode" if kind == "view" else "actcode"
    link = f"{_app_url()}/?{param}={code}"
    hint = "เปิดอัลบั้ม" if kind == "view" else "เปิดหน้าส่งรูป"

    show_key = f"{key_prefix}_showqr"
    shown = st.session_state.get(show_key, False)
    if st.button("🔽 ซ่อน QR" if shown else "📱 แสดง QR (สแกนแล้วเข้าได้เลย)",
                 key=f"{key_prefix}_qrbtn", width="stretch"):
        st.session_state[show_key] = not shown
        st.rerun()
    if st.session_state.get(show_key):
        png = qr_png(link)
        if png:
            st.image(png, width=200, caption=f"สแกนเพื่อ{hint} (หรือใช้รหัส {code})")
        else:
            st.caption("⚠️ สร้าง QR ไม่ได้")


def render_share_panel(activity_id, activity_name, key_prefix):
    """
    กล่องตั้งค่าการแชร์อัลบั้มของ 1 กิจกรรม:
      - เลือก 🌐 ทุกคนดูได้ / 👤 เฉพาะคนที่เพิ่ม
      - ถ้าเฉพาะคน: เพิ่มคนดู (ระบบออกรหัสส่วนตัวให้ก๊อปแจก) + ถอนสิทธิ์รายคน
    key_prefix กันชน key ระหว่างหน้า admin ("adm") กับ superuser ("su")
    """
    with st.expander(f"🔗 แชร์อัลบั้ม: {activity_name}"):
        cur = get_activity_visibility(activity_id)
        options = [VIS_PUBLIC, VIS_PRIVATE]
        labels = {VIS_PUBLIC: "🌐 ทุกคนดูได้", VIS_PRIVATE: "👤 เฉพาะคนที่เพิ่ม"}
        idx = options.index(cur) if cur in options else options.index(VIS_PRIVATE)
        sel = st.radio(
            "ใครดูอัลบั้มนี้ได้", options, index=idx,
            format_func=lambda v: labels[v], horizontal=True,
            key=f"{key_prefix}_vis_{activity_id}",
        )
        if sel != cur:
            set_activity_visibility(activity_id, sel)
            st.rerun()

        if sel == VIS_PUBLIC:
            st.caption("🌐 ทุกคนเปิดดูอัลบั้มนี้ได้จากหน้า '🖼️ ดูอัลบั้ม' (ไม่ต้องมีรหัส)")
            return

        # โหมดเฉพาะคน — จัดการรายชื่อคนดู
        st.markdown("**เพิ่มคนที่ให้ดู** — ระบบออกรหัสส่วนตัวให้ก๊อปส่งเฉพาะคนนั้น")
        with st.form(f"{key_prefix}_addshare_{activity_id}", clear_on_submit=True):
            vname = st.text_input("ชื่อคนที่จะให้ดู")
            add_ok = st.form_submit_button("+ ออกรหัสให้", width="stretch")
        if add_ok:
            _add_share(activity_id, vname, key_prefix)

        shares = activity_shares(activity_id)

        # กล่องเขียว "รหัสดูของ X" — โชว์เฉพาะตอนที่คนนั้น **ยังมีสิทธิ์ดูอยู่จริง** (#M)
        # เดิมล้างได้ทางเดียวคือกดปุ่ม "รับทราบ" → กดถอนสิทธิ์แล้วกล่องยังค้าง
        # (ค้างข้ามการเปลี่ยนเมนูด้วย เพราะ session_state ไม่หาย) แถมโชว์รหัสที่ยกเลิกไปแล้วให้ก๊อป
        flash_key = f"{key_prefix}_last_share_{activity_id}"
        last = st.session_state.get(flash_key)
        names_now = set(shares["ชื่อผู้ดู"].astype(str)) if not shares.empty else set()
        if last and str(last.get("name", "")) not in names_now:
            del st.session_state[flash_key]      # ถอนสิทธิ์ไปแล้ว → รหัสใช้ไม่ได้ ไม่ต้องโชว์
            last = None
        if last:
            st.success(f"✅ รหัสดูของ “{last['name']}” — ก๊อปส่งให้เขาเปิดที่หน้า 'ดูอัลบั้ม':")
            render_code_with_qr(last["code"], f"{key_prefix}_sharecode_{activity_id}", kind="view")
            if st.button("รับทราบ / ปิดข้อความ", key=f"{key_prefix}_dismiss_share_{activity_id}"):
                del st.session_state[flash_key]
                st.rerun()

        if shares.empty:
            st.caption("ยังไม่มีใครถูกแชร์ให้ดู — เพิ่มด้านบน (คนไม่ถูกแชร์เปิดอัลบั้มไม่ได้)")
        else:
            st.markdown("**คนที่ดูอัลบั้มนี้ได้:**")
            for _, s in shares.iterrows():
                name = str(s.get("ชื่อผู้ดู", ""))
                cc1, cc2 = st.columns([6, 2])
                cc1.write(f"• {name} · เพิ่มเมื่อ {s.get('วันที่เพิ่ม','')}")
                if cc2.button("ถอนสิทธิ์", key=f"{key_prefix}_revoke_{activity_id}_{name}",
                              width="stretch"):
                    delete_share(activity_id, name)
                    st.rerun()


def render_publish_toggle(item, key_prefix, who, role):
    """
    ปุ่มเผยแพร่รูป 1 ใบเข้า "คลังทั่วไป" (ใช้ร่วมกัน admin/superuser)
    เผยแพร่แล้วรูปจะไปโผล่เป็นโฟลเดอร์ของกิจกรรมในหน้าคลังภาพ (คนที่มีรหัสคลังทั่วไปดู/โหลดได้
    แต่ลบไม่ได้) — รูปยังอยู่ในอัลบั้มกิจกรรมตามเดิม ยกเลิกเมื่อไหร่ก็หายจากคลังทั่วไปทันที
    """
    link = item["ลิงก์รูป"]
    file_id = extract_file_id(link)
    aid = str(item.get("activity_id", ""))
    published = str(item.get(PUBLISHED_HEADER, "")).strip() == PUBLISHED_YES

    label = "🌐 ยกเลิกเผยแพร่" if published else "🌐 เผยแพร่เข้าคลังทั่วไป"
    if st.button(label, key=f"{key_prefix}_pub_{file_id}", width="stretch"):
        try:
            set_photo_published(link, not published)
            log_action(who, role, "ยกเลิกเผยแพร่รูป" if published else "เผยแพร่รูป",
                       detail=str(item.get("ชื่อไฟล์", "")), activity_id=aid)
            # set_photo_published ล้าง load_data, log_action ล้าง load_log อยู่แล้ว
            st.rerun()
        except Exception as e:
            st.error(f"ทำรายการไม่สำเร็จ: {e}")
    if published:
        st.caption("🌐 เผยแพร่อยู่ในคลังทั่วไป")


def render_duplicate_scan(df, key_prefix, deleted_by, role):
    """
    เครื่องมือสแกนหารูปซ้ำ (phash) ในชุดรูปที่กำลังดูอยู่ — ใช้ร่วมกัน admin/superuser
    กดปุ่มแล้วจัดกลุ่มรูปที่คล้ายกัน โชว์ให้เลือกลบใบซ้ำ (ลงถังขยะ)
    """
    scan_key = f"{key_prefix}_dupscan"
    if st.button("🔍 หารูปซ้ำในชุดนี้", key=f"{key_prefix}_dupscan_btn"):
        st.session_state[scan_key] = True
    if not st.session_state.get(scan_key):
        return

    groups = group_duplicates(df)
    if not groups:
        st.success("✅ ไม่พบรูปซ้ำในชุดนี้")
        return
    st.warning(f"พบ {len(groups)} กลุ่มที่อาจซ้ำ — เก็บไว้ 1 ใบ ที่เหลือกดลบ (ลงถังขยะ กู้คืนได้)")
    for gi, group in enumerate(groups):
        st.markdown(f"**กลุ่มที่ {gi + 1} · {len(group)} รูปคล้ายกัน**")
        ncol = min(len(group), COLS_PER_ROW)
        cols = st.columns(ncol)
        for idx, item in enumerate(group):
            with cols[idx % ncol]:
                file_id = extract_file_id(item["ลิงก์รูป"])
                try:
                    st.image(get_thumbnail(file_id), width="stretch")
                except Exception:
                    st.caption("⚠️ โหลดรูปไม่ได้")
                st.caption(f"{item.get('ชื่อไฟล์','')}  \n👤 {item.get('ผู้ส่ง','')} · {item.get('วันเวลา','')}")
                if st.button("🗑️ ลบใบนี้", key=f"{key_prefix}_dupdel_{gi}_{idx}_{file_id}", width="stretch"):
                    try:
                        trash_photo(file_id, item["ลิงก์รูป"], deleted_by=deleted_by)
                        log_action(deleted_by, role, "ลบรูป(ถังขยะ)",
                                   detail=str(item.get("ชื่อไฟล์", "")),
                                   activity_id=str(item.get("activity_id", "")))
                        # trash_photo ล้าง load_data, log_action ล้าง load_log อยู่แล้ว
                        st.rerun()
                    except Exception as e:
                        st.error(f"ลบไม่สำเร็จ: {e}")
        st.divider()


def _add_share(activity_id, vname, key_prefix):
    """ออกรหัสดูส่วนตัวให้คน 1 คน + เก็บลง Shares (hash) + โชว์รหัสจริงให้ก๊อป"""
    vname = (vname or "").strip()
    if not vname:
        st.error("⚠️ กรอกชื่อคนที่จะให้ดูก่อน")
        return
    code = _gen_code()
    now = datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d %H:%M:%S")
    add_share(activity_id, vname, auth.hash_secret(code), now)
    st.session_state[f"{key_prefix}_last_share_{activity_id}"] = {"name": vname, "code": code}
    st.rerun()


# --------------------------------------------------------------------------
# helper
# --------------------------------------------------------------------------
def _my_activities(df, username):
    """กรองเฉพาะกิจกรรมที่ admin คนนี้สร้าง"""
    if df.empty or "คนสร้าง" not in df.columns:
        return df.iloc[0:0] if not df.empty else df
    return df[df["คนสร้าง"].astype(str) == str(username)]


def _count_photos(photos, activity_id):
    if photos.empty or "activity_id" not in photos.columns:
        return 0
    return int((photos["activity_id"].astype(str) == str(activity_id)).sum())
