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
    load_data, load_active_data, load_trash_data,
    get_image_bytes, extract_file_id, trash_photo, restore_photo, log_action, is_activity_open,
    get_activity_visibility, set_activity_visibility, activity_shares, add_share, delete_share,
    VIS_PUBLIC, VIS_PRIVATE, group_duplicates,
)
from page_gallery import build_zip, COLS_PER_ROW

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
    tab_act, tab_gallery, tab_trash, tab_dash = st.tabs(
        ["🎯 กิจกรรมของฉัน", "🖼️ คลังภาพกิจกรรม", "🗑️ ถังขยะ", "📊 ภาพรวม"]
    )
    with tab_act:
        _render_activities(username)
    with tab_gallery:
        _render_gallery(username)
    with tab_trash:
        _render_trash(username)
    with tab_dash:
        _render_dashboard(username)


# --------------------------------------------------------------------------
# แท็บ 1: กิจกรรมของฉัน
# --------------------------------------------------------------------------
def _render_activities(username):
    st.subheader("🎯 กิจกรรมของฉัน")

    # กล่องโชว์รหัสกิจกรรมที่เพิ่งสร้าง (ให้ก๊อปไปแจกลูกน้อง)
    last = st.session_state.get("admin_last_code")
    if last:
        st.success(f"✅ สร้างกิจกรรม “{last['name']}” แล้ว — แจกรหัสนี้ให้ลูกน้องเข้าร่วม:")
        st.code(last["code"], language=None)
        if st.button("รับทราบ / ปิดข้อความนี้", key="dismiss_code"):
            del st.session_state["admin_last_code"]
            st.rerun()

    # ฟอร์มสร้างกิจกรรมใหม่
    with st.expander("➕ สร้างกิจกรรมใหม่", expanded=not last):
        with st.form("create_activity", clear_on_submit=True):
            name = st.text_input("ชื่อกิจกรรม")
            code = st.text_input("รหัสเข้ากิจกรรม (เว้นว่าง = สุ่มให้อัตโนมัติ)")
            ok = st.form_submit_button("สร้างกิจกรรม", width="stretch")
        if ok:
            _create_activity(username, name, code)

    st.divider()

    # รายการกิจกรรมของตัวเอง
    df = load_activities()
    mine = _my_activities(df, username)
    if mine.empty:
        st.info("คุณยังไม่ได้สร้างกิจกรรม — สร้างอันแรกด้านบนได้เลย")
        return

    photos = load_data()
    for _, a in mine.iterrows():
        aid = str(a["activity_id"])
        n = _count_photos(photos, aid)
        # ปิดอัตโนมัติแล้วหรือยัง (สถานะเปิดในชีต แต่ครบ 7 วันจากวันสร้าง → ผู้เข้าร่วม login ไม่ได้แล้ว)
        auto_closed = str(a["สถานะ"]) == "เปิด" and not is_activity_open(a)
        note = " · ⏰ ปิดอัตโนมัติแล้ว (ครบ 7 วัน)" if auto_closed else ""
        c1, c2, c3 = st.columns([5, 2, 2])
        c1.markdown(
            f"**{a['ชื่อกิจกรรม']}**  \n"
            f"สถานะ: {a['สถานะ']}{note} · {n} รูป · สร้างเมื่อ {a['วันที่สร้าง']}"
        )
        if str(a["สถานะ"]) == "เปิด":
            if c2.button("⏸️ ปิดกิจกรรม", key=f"close_{aid}", width="stretch"):
                set_activity_status(aid, "ปิด")
                st.rerun()
        else:
            if c2.button("▶️ เปิดกิจกรรม", key=f"open_{aid}", width="stretch"):
                set_activity_status(aid, "เปิด")
                st.rerun()

        # ลบกิจกรรม — admin ลบได้ "เฉพาะกิจกรรมที่ยังไม่มีรูป" (ไว้แก้ตอนสร้างผิด)
        # ถ้ามีรูปแล้วลบไม่ได้ ต้องให้ superuser ลบ (กันเผลอลบรูปของลูกน้องหลุดมือ)
        if n > 0:
            c3.button("🗑️ ลบกิจกรรม", key=f"adm_delact_{aid}", width="stretch",
                      disabled=True, help="มีรูปแล้ว ลบไม่ได้ — แจ้ง superuser ให้ลบแทน")
        else:
            del_key = f"adm_confirm_delact_{aid}"
            if st.session_state.get(del_key):
                st.warning(f"⚠️ ลบกิจกรรม **{a['ชื่อกิจกรรม']}** ถาวร? (ยังไม่มีรูปในกิจกรรมนี้)")
                y, no = st.columns(2)
                if y.button("✅ ลบเลย", key=f"adm_delact_yes_{aid}", width="stretch"):
                    try:
                        # อ่านสดอีกครั้ง กันมีรูปเพิ่งถูกส่งเข้ามาหลังหน้าโหลด → ถ้ามีรูปแล้ว admin ลบไม่ได้
                        load_data.clear()
                        if _count_photos(load_data(), aid) > 0:
                            st.error("❌ มีรูปเข้ามาในกิจกรรมนี้แล้ว — ลบไม่ได้ ต้องให้ superuser ลบ")
                            st.session_state.pop(del_key, None)
                        else:
                            delete_activity(aid)
                            log_action(username, "admin", "ลบกิจกรรม",
                                       detail=str(a["ชื่อกิจกรรม"]), activity_id=aid)
                            st.session_state.pop(del_key, None)
                            st.cache_data.clear()
                            st.rerun()
                    except Exception as e:
                        st.error(f"ลบไม่สำเร็จ: {e}")
                if no.button("❌ ยกเลิก", key=f"adm_delact_no_{aid}", width="stretch"):
                    st.session_state.pop(del_key, None)
                    st.rerun()
            else:
                if c3.button("🗑️ ลบกิจกรรม", key=f"adm_delact_{aid}", width="stretch"):
                    st.session_state[del_key] = True
                    st.rerun()

        # กล่องแชร์อัลบั้ม (ทุกคน/เฉพาะคน + รายชื่อคนดู + รหัสส่วนตัว)
        render_share_panel(aid, str(a["ชื่อกิจกรรม"]), "adm")
        st.divider()


def _create_activity(username, name, code):
    if not name.strip():
        st.error("⚠️ กรอกชื่อกิจกรรมก่อน")
        return
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
    add_activity(aid, name.strip(), code_hash, username, now, "เปิด")
    st.session_state["admin_last_code"] = {"name": name.strip(), "code": code}
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
        for col, item in zip(cols, rows[i:i + COLS_PER_ROW]):
            with col:
                file_id = extract_file_id(item["ลิงก์รูป"])
                try:
                    st.image(get_image_bytes(file_id), width="stretch")
                except Exception:
                    st.caption("⚠️ โหลดรูปไม่ได้")
                act_name = id2name.get(str(item.get("activity_id")), "")
                st.caption(f"🎯 {act_name} · 👤 {item.get('ผู้ส่ง','')} · 🗓️ {item.get('วันเวลา','')}")
                download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                st.link_button("⬇️ ดาวน์โหลด", download_url, width="stretch")

                # ลบรูป → ย้ายไปถังขยะ (กู้คืนได้ ~30 วัน) มีขั้นยืนยัน
                del_key = f"adm_confirm_del_{file_id}"
                if st.session_state.get(del_key):
                    st.warning("⚠️ ย้ายรูปนี้ไปถังขยะ? (กู้คืนได้ที่แท็บถังขยะ ~30 วัน)")
                    y, no = st.columns(2)
                    if y.button("✅ ย้ายไปถังขยะ", key=f"adm_yes_{file_id}", width="stretch"):
                        try:
                            trash_photo(file_id, item["ลิงก์รูป"], deleted_by=username)
                            log_action(username, "admin", "ลบรูป(ถังขยะ)",
                                       detail=str(item.get("ชื่อไฟล์", "")),
                                       activity_id=str(item.get("activity_id", "")))
                            st.session_state.pop(del_key, None)
                            st.cache_data.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"ลบไม่สำเร็จ: {e}")
                    if no.button("❌ ยกเลิก", key=f"adm_no_{file_id}", width="stretch"):
                        st.session_state.pop(del_key, None)
                        st.rerun()
                else:
                    if st.button("🗑️ ลบรูปนี้", key=f"adm_del_{file_id}", width="stretch"):
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
        for col, item in zip(cols, rows[i:i + COLS_PER_ROW]):
            with col:
                file_id = extract_file_id(item["ลิงก์รูป"])
                try:
                    st.image(get_image_bytes(file_id), width="stretch")
                except Exception:
                    st.caption("⚠️ โหลดรูปไม่ได้")
                act_name = id2name.get(str(item.get("activity_id")), "")
                st.caption(
                    f"🎯 {act_name} · 🗑️ ลบเมื่อ {item.get('วันที่ลบ','')}  \n"
                    f"โดย {item.get('ลบโดย','')}"
                )
                if st.button("♻️ กู้คืนรูปนี้", key=f"adm_restore_{file_id}", width="stretch"):
                    try:
                        restore_photo(file_id, item["ลิงก์รูป"])
                        log_action(username, "admin", "กู้คืนรูป",
                                   detail=str(item.get("ชื่อไฟล์", "")),
                                   activity_id=str(item.get("activity_id", "")))
                        st.cache_data.clear()
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

        last = st.session_state.get(f"{key_prefix}_last_share_{activity_id}")
        if last:
            st.success(f"✅ รหัสดูของ “{last['name']}” — ก๊อปส่งให้เขาเปิดที่หน้า 'ดูอัลบั้ม':")
            st.code(last["code"], language=None)
            if st.button("รับทราบ / ปิดข้อความ", key=f"{key_prefix}_dismiss_share_{activity_id}"):
                del st.session_state[f"{key_prefix}_last_share_{activity_id}"]
                st.rerun()

        shares = activity_shares(activity_id)
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
                    st.image(get_image_bytes(file_id), width="stretch")
                except Exception:
                    st.caption("⚠️ โหลดรูปไม่ได้")
                st.caption(f"{item.get('ชื่อไฟล์','')}  \n👤 {item.get('ผู้ส่ง','')} · {item.get('วันเวลา','')}")
                if st.button("🗑️ ลบใบนี้", key=f"{key_prefix}_dupdel_{file_id}", width="stretch"):
                    try:
                        trash_photo(file_id, item["ลิงก์รูป"], deleted_by=deleted_by)
                        log_action(deleted_by, role, "ลบรูป(ถังขยะ)",
                                   detail=str(item.get("ชื่อไฟล์", "")),
                                   activity_id=str(item.get("activity_id", "")))
                        st.cache_data.clear()
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
