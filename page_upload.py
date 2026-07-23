# -*- coding: utf-8 -*-
"""
page_upload.py — หน้า "ส่งรูป" (คลังภาพทั่วไป)
เลือก/ถ่ายได้ทีละหลายรูป (บนมือถือช่องแนบไฟล์มีปุ่มถ่ายรูปให้) → ย่อ → ตรวจซ้ำ → อัป → บันทึก
ถ้ามีรูปคล้ายที่เคยส่ง/ซ้ำกันในชุด จะถามก่อนบันทึก
"""

import io
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo

from config import DEPARTMENTS, CATEGORIES
from image_utils import compress_image, compute_phash, hamming_distance
from google_utils import (
    upload_to_drive, append_row, make_general_filename, log_action,
    load_general_data, find_similar_photo, PHASH_DUP_THRESHOLD,
)


def _upload_batch(department, category, title, tags, sender, items) -> int:
    """อัปหลายรูปเข้าคลังทั่วไป (แสดง progress) — คืนจำนวนที่อัปสำเร็จ"""
    now = datetime.now(ZoneInfo("Asia/Bangkok"))
    datetime_str = now.strftime("%Y-%m-%d %H:%M:%S")
    total = len(items)
    prog = st.progress(0.0, text="กำลังอัปโหลด...")
    ok = 0
    for i, it in enumerate(items):
        filename = make_general_filename(department, category, now)
        if total > 1:  # หลายรูปวินาทีเดียวกัน → เติมลำดับกันชื่อซ้ำ
            filename = filename[:-4] + f"_{i + 1:02d}.jpg"
        file_id, link = upload_to_drive(io.BytesIO(it["bytes"]), filename)
        row = [datetime_str, department, category, title, tags, sender, link, filename, "", it["phash"]]
        append_row(row)
        log_action(sender, "general", "อัปโหลดรูป", detail=filename)
        ok += 1
        prog.progress((i + 1) / total, text=f"อัปโหลด {i + 1}/{total}")
    prog.empty()
    # append_row ล้าง load_data, log_action ล้าง load_log อยู่แล้ว
    return ok


def _render_batch_confirm(pend):
    """เจอรูปซ้ำในชุด — เลือกบันทึกทั้งหมด / เฉพาะไม่ซ้ำ / ยกเลิก"""
    items = pend["items"]
    dups = [it for it in items if it.get("dup")]
    st.warning(f"⚠️ พบ {len(dups)} รูปที่อาจซ้ำ จากทั้งหมด {len(items)} รูป — จะบันทึกแบบไหน?")

    st.caption("รูปที่อาจซ้ำ:")
    ncol = min(len(dups), 4) or 1
    cols = st.columns(ncol)
    for idx, it in enumerate(dups):
        with cols[idx % ncol]:
            st.image(it["bytes"], width="stretch")
            st.caption(f"คล้าย: {it.get('dup_file','')}")

    c1, c2, c3 = st.columns(3)
    if c1.button("✅ บันทึกทั้งหมด (รวมที่ซ้ำ)", width="stretch", key="up_batch_all"):
        n = _upload_batch(pend["department"], pend["category"], pend["title"],
                          pend["tags"], pend["sender"], items)
        st.session_state.pop("up_pending", None)
        st.session_state["up_flash"] = f"✅ บันทึก {n} รูปสำเร็จ!"
        st.rerun()
    if c2.button(f"⏭️ เฉพาะไม่ซ้ำ (ข้าม {len(dups)})", width="stretch", key="up_batch_skip"):
        keep = [it for it in items if not it.get("dup")]
        n = _upload_batch(pend["department"], pend["category"], pend["title"],
                          pend["tags"], pend["sender"], keep) if keep else 0
        st.session_state.pop("up_pending", None)
        st.session_state["up_flash"] = f"✅ บันทึก {n} รูป (ข้ามที่ซ้ำ {len(dups)} รูป)"
        st.rerun()
    if c3.button("❌ ยกเลิก", width="stretch", key="up_batch_cancel"):
        st.session_state.pop("up_pending", None)
        st.rerun()


def render():
    st.subheader("📤 ส่งรูปเข้าคลัง")

    flash = st.session_state.pop("up_flash", None)
    if flash:
        st.success(flash)

    pend = st.session_state.get("up_pending")
    if pend:
        _render_batch_confirm(pend)
        return

    # ช่องอัปรูปต้องอยู่ "ใน" form เพื่อให้ clear_on_submit ล้างรูปหลังกดบันทึก (กันบันทึกซ้ำ)
    with st.form("upload_form", clear_on_submit=True):
        image_files = st.file_uploader(
            "เลือกรูป (JPG, JPEG, PNG) — เลือก/ถ่ายได้หลายรูป",
            type=["jpg", "jpeg", "png"], accept_multiple_files=True,
        )
        col1, col2 = st.columns(2)
        with col1:
            department = st.selectbox("แผนก", DEPARTMENTS)
        with col2:
            category = st.selectbox("หมวด", CATEGORIES)

        title = st.text_input("ชื่อเรื่อง / คำอธิบาย")
        tags = st.text_input("แท็ก (คั่นด้วยจุลภาค เช่น: ชั้น2, โกดังA, ด่วน)")
        sender = st.text_input("ชื่อผู้ส่ง")

        submitted = st.form_submit_button("💾 บันทึกข้อมูล", width="stretch")

    if not submitted:
        return

    # ----- ตรวจสอบว่ากรอกครบก่อนบันทึก -----
    if not image_files:
        st.error("⚠️ ยังไม่ได้เลือกรูป")
        return
    if not title.strip():
        st.error("⚠️ กรุณากรอกชื่อเรื่อง")
        return
    if not sender.strip():
        st.error("⚠️ กรุณากรอกชื่อผู้ส่ง")
        return

    try:
        now = datetime.now(ZoneInfo("Asia/Bangkok"))
        scope = load_general_data()

        items = []
        prog = st.progress(0.0, text="กำลังย่อรูป + ตรวจรูปซ้ำ...")
        for i, f in enumerate(image_files):
            compressed = compress_image(f, meta={
                "description": title.strip(), "artist": sender.strip(),
                "datetime": now.strftime("%Y:%m:%d %H:%M:%S"),
            })
            b = compressed.getvalue()
            ph = compute_phash(b)
            dup = find_similar_photo(ph, scope)
            dup_file = dup.get("ชื่อไฟล์", "") if dup else ""
            is_dup = dup is not None
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

        if any(it["dup"] for it in items):
            st.session_state["up_pending"] = {
                "department": department, "category": category,
                "title": title.strip(), "tags": tags.strip(), "sender": sender.strip(),
                "items": items,
            }
            st.rerun()

        n = _upload_batch(department, category, title.strip(), tags.strip(), sender.strip(), items)
        st.session_state["up_flash"] = f"✅ บันทึก {n} รูปสำเร็จ!"
        st.rerun()
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาด: {e}")
