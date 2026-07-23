# -*- coding: utf-8 -*-
"""
page_activity_user.py — หน้าของ "ผู้ส่งรูปเข้ากิจกรรม" (role = user)
2 แท็บ: ส่งรูป + ดู "รูปของฉัน" (เฉพาะรูปที่ตัวเองส่ง — ยังไม่เห็นของคนอื่น ตามหลัก ถ่าย≠ดู)
เลือก/ถ่ายได้ทีละหลายรูป (บนมือถือช่องแนบไฟล์มีปุ่มถ่ายรูปให้)
มีระบบเตือน "รูปซ้ำ" (phash) แบบชุด: ถ้ามีรูปคล้ายที่เคยส่ง/ซ้ำกันในชุด จะถามก่อนส่ง
"""

import io
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd

from image_utils import compress_image, compute_phash, hamming_distance
from google_utils import (
    upload_to_drive, append_activity_row, load_active_data, find_similar_photo,
    make_activity_filename, count_activity_photos, log_action, extract_file_id,
    get_image_bytes, get_thumbnail, PHASH_DUP_THRESHOLD,
)
from page_gallery import COLS_PER_ROW   # reuse จำนวนคอลัมน์กริด ให้หน้าตาเหมือนหน้าอื่น


def render():
    ident = st.session_state.get("identity", {})
    activity_id = ident.get("activity_id")
    activity_name = ident.get("activity_name", "")
    sender = ident.get("name", "")

    tab_send, tab_mine = st.tabs(["📤 ส่งรูป", "🖼️ รูปของฉัน"])
    with tab_send:
        _render_send(activity_id, activity_name, sender)
    with tab_mine:
        _render_my_photos(activity_id, sender)


def _render_my_photos(activity_id, sender):
    """
    รูปที่ "ตัวเองส่ง" ในกิจกรรมนี้ — ดู + ดาวน์โหลดได้ ลบไม่ได้

    ⚠️ กรอง 2 ชั้น: activity_id ตรง **และ** ผู้ส่งตรงกับชื่อที่ login มา
    → ยังคงเจตนาเดิม "ถ่าย ≠ ดู" คือไม่เห็นรูปของคนอื่นในกิจกรรม เห็นแค่ของตัวเอง
    """
    st.subheader("🖼️ รูปที่คุณส่งในกิจกรรมนี้")
    st.caption(f"เห็นเฉพาะรูปที่ส่งในชื่อ “{sender}” — ไม่เห็นรูปของคนอื่น")

    df = load_active_data()   # ไม่รวมรูปที่อยู่ในถังขยะ
    if df.empty or "activity_id" not in df.columns:
        st.info("ยังไม่มีรูปที่คุณส่ง")
        return

    mine = df[
        (df["activity_id"].astype(str) == str(activity_id))
        & (df["ผู้ส่ง"].astype(str).str.strip() == str(sender).strip())
    ].copy()
    if mine.empty:
        st.info("ยังไม่มีรูปที่คุณส่ง — ไปที่แท็บ “📤 ส่งรูป” เพื่อเริ่มส่ง")
        return

    mine["_dt"] = pd.to_datetime(mine["วันเวลา"], errors="coerce")
    mine = mine.sort_values("_dt", ascending=False)
    st.markdown(f"**คุณส่งไปแล้ว {len(mine)} รูป**")

    rows = mine.to_dict("records")
    for i in range(0, len(rows), COLS_PER_ROW):
        cols = st.columns(COLS_PER_ROW)
        for col, item in zip(cols, rows[i:i + COLS_PER_ROW]):
            with col:
                file_id = extract_file_id(item["ลิงก์รูป"])
                try:
                    st.image(get_thumbnail(file_id), width="stretch")
                except Exception:
                    st.caption("⚠️ โหลดรูปไม่ได้")
                st.caption(f"🗓️ {item.get('วันเวลา','')}")
                st.link_button(
                    "⬇️ ดาวน์โหลด",
                    f"https://drive.google.com/uc?export=download&id={file_id}",
                    width="stretch",
                )


def _upload_batch(activity_id, activity_name, sender, items) -> int:
    """อัปหลายรูปเข้ากิจกรรม (แสดง progress) — คืนจำนวนที่อัปสำเร็จ"""
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    datetime_str = now.strftime("%Y-%m-%d %H:%M:%S")
    base = count_activity_photos(activity_id)   # ลำดับเริ่มต้น (กันชื่อไฟล์ซ้ำในชุด)
    total = len(items)
    prog = st.progress(0.0, text="กำลังอัปโหลด...")
    ok = 0
    for i, it in enumerate(items):
        seq = base + i + 1
        filename = make_activity_filename(activity_name, seq, now)
        file_id, link = upload_to_drive(io.BytesIO(it["bytes"]), filename)
        append_activity_row(datetime_str, sender, link, filename, activity_id, it["phash"])
        log_action(sender, "user", "อัปโหลดรูป", detail=filename, activity_id=activity_id)
        ok += 1
        prog.progress((i + 1) / total, text=f"อัปโหลด {i + 1}/{total}")
    prog.empty()
    # append_activity_row (ผ่าน append_row) ล้าง load_data, log_action ล้าง load_log อยู่แล้ว
    return ok


def _render_batch_confirm(pend):
    """เจอรูปซ้ำในชุด — ให้เลือกส่งทั้งหมด / เฉพาะไม่ซ้ำ / ยกเลิก"""
    items = pend["items"]
    dups = [it for it in items if it.get("dup")]
    st.warning(f"⚠️ พบ {len(dups)} รูปที่อาจซ้ำ จากทั้งหมด {len(items)} รูป — จะส่งแบบไหน?")

    st.caption("รูปที่อาจซ้ำ:")
    ncol = min(len(dups), 4) or 1
    cols = st.columns(ncol)
    for idx, it in enumerate(dups):
        with cols[idx % ncol]:
            st.image(it["bytes"], width="stretch")
            st.caption(f"คล้าย: {it.get('dup_file','')}")

    c1, c2, c3 = st.columns(3)
    if c1.button("✅ ส่งทั้งหมด (รวมที่ซ้ำ)", width="stretch", key="act_batch_all"):
        n = _upload_batch(pend["activity_id"], pend["activity_name"], pend["sender"], items)
        st.session_state.pop("act_pending", None)
        st.session_state["act_flash"] = f"✅ ส่ง {n} รูปสำเร็จ!"
        st.rerun()
    if c2.button(f"⏭️ ส่งเฉพาะไม่ซ้ำ (ข้าม {len(dups)})", width="stretch", key="act_batch_skip"):
        keep = [it for it in items if not it.get("dup")]
        n = _upload_batch(pend["activity_id"], pend["activity_name"], pend["sender"], keep) if keep else 0
        st.session_state.pop("act_pending", None)
        st.session_state["act_flash"] = f"✅ ส่ง {n} รูป (ข้ามที่ซ้ำ {len(dups)} รูป)"
        st.rerun()
    if c3.button("❌ ยกเลิก", width="stretch", key="act_batch_cancel"):
        st.session_state.pop("act_pending", None)
        st.rerun()


def _render_send(activity_id, activity_name, sender):
    st.subheader(f"📤 ส่งรูปเข้ากิจกรรม: {activity_name}")
    st.caption(f"ผู้ส่ง: {sender} · เลือกได้หลายรูป (บนมือถือ กดแล้วมีปุ่มถ่ายรูปให้)")

    flash = st.session_state.pop("act_flash", None)
    if flash:
        st.success(flash)

    pend = st.session_state.get("act_pending")
    if pend and pend.get("activity_id") == activity_id:
        _render_batch_confirm(pend)
        return

    with st.form("activity_upload_form", clear_on_submit=True):
        image_files = st.file_uploader(
            "เลือกรูป (JPG, JPEG, PNG) — เลือก/ถ่ายได้หลายรูป",
            type=["jpg", "jpeg", "png"], accept_multiple_files=True, key="act_files",
        )
        submitted = st.form_submit_button("💾 ส่งรูป", width="stretch")

    if not submitted:
        return
    if not image_files:
        st.error("⚠️ ยังไม่ได้เลือกรูป")
        return

    try:
        now = datetime.now(ZoneInfo("Asia/Bangkok"))
        scope = load_active_data()
        if not scope.empty and "activity_id" in scope.columns:
            scope = scope[scope["activity_id"].astype(str) == str(activity_id)]

        items = []
        prog = st.progress(0.0, text="กำลังย่อรูป + ตรวจรูปซ้ำ...")
        for i, f in enumerate(image_files):
            compressed = compress_image(f, meta={
                "description": activity_name, "artist": sender,
                "datetime": now.strftime("%Y:%m:%d %H:%M:%S"),
            })
            b = compressed.getvalue()
            ph = compute_phash(b)
            # ซ้ำกับรูปที่มีอยู่ในกิจกรรมนี้?
            dup = find_similar_photo(ph, scope)
            dup_file = dup.get("ชื่อไฟล์", "") if dup else ""
            is_dup = dup is not None
            # ซ้ำกับรูปอื่นในชุดที่กำลังจะส่ง?
            if not is_dup:
                for j, prev in enumerate(items):
                    if hamming_distance(ph, prev["phash"]) <= PHASH_DUP_THRESHOLD:
                        is_dup = True
                        dup_file = f"(รูปที่ {j + 1} ในชุดนี้)"
                        break
            items.append({"bytes": b, "phash": ph, "dup": is_dup, "dup_file": dup_file})
            prog.progress((i + 1) / len(image_files),
                          text=f"ย่อรูป + ตรวจซ้ำ {i + 1}/{len(image_files)}")
        prog.empty()

        # มีรูปซ้ำ → พักไว้ถามยืนยันแบบชุด
        if any(it["dup"] for it in items):
            st.session_state["act_pending"] = {
                "activity_id": activity_id, "activity_name": activity_name,
                "sender": sender, "items": items,
            }
            st.rerun()

        # ไม่ซ้ำเลย → ส่งทั้งหมด
        n = _upload_batch(activity_id, activity_name, sender, items)
        st.session_state["act_flash"] = f"✅ ส่ง {n} รูปสำเร็จ!"
        st.rerun()
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาด: {e}")
