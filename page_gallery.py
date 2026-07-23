# -*- coding: utf-8 -*-
"""
page_gallery.py — หน้า "คลังภาพ" แบบโฟลเดอร์ 2 ชั้น

ชั้นนอก (หน้าโฟลเดอร์):
  - 📁 แผนก — โชว์เฉพาะแผนกที่มีรูป (กดปุ่มเพื่อดูแผนกที่ยังไม่มีรูปได้)
  - 🎉 รูปจากกิจกรรม — กิจกรรมที่ admin กด "เผยแพร่เข้าคลังทั่วไป" ไว้ (1 กิจกรรม = 1 โฟลเดอร์)
ชั้นใน (เปิดโฟลเดอร์): กริดรูป + ดาวน์โหลดเดี่ยว/zip + แบ่งหน้า
  - โฟลเดอร์แผนก   → กรองหมวด/คำค้น/ช่วงวันที่ได้ + ลบรูปได้ (ของคลังทั่วไปเอง)
  - โฟลเดอร์กิจกรรม → ดู+โหลดอย่างเดียว "ลบไม่ได้" (เจ้าของตัวจริงคือฝั่งกิจกรรม)

ไม่ใช้รูปปกในการ์ดโฟลเดอร์ตั้งใจ — ทุกรูปต้องโหลด bytes จริงจาก Drive (hotlink thumbnail
ของ Google ใช้ไม่ได้) ถ้าใส่รูปปกจะต้องโหลดรูปเท่าจำนวนโฟลเดอร์ก่อนหน้าจะขึ้น = ช้าเมื่อรูปเยอะ
"""

import io
import zipfile

import streamlit as st
import pandas as pd

from config import DEPARTMENTS, CATEGORIES
from google_utils import (
    load_general_data, load_published_activity_data, load_activities,
    download_file_bytes, extract_file_id, get_image_bytes, get_thumbnail,
    trash_photo, log_action,
)

PAGE_SIZE = 12          # จำนวนรูปต่อหน้า
COLS_PER_ROW = 4        # จำนวนรูปต่อแถว
FOLDER_KEY = "gal_folder"       # โฟลเดอร์ที่เปิดอยู่: None | ("dep", ชื่อแผนก) | ("act", activity_id)
SHOW_EMPTY_KEY = "gal_show_empty_deps"


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
    folder = st.session_state.get(FOLDER_KEY)
    if not folder:
        _render_home()
        return
    kind, value = folder
    if kind == "dep":
        _render_department(value)
    else:
        _render_activity_folder(value)


# ==========================================================================
# ชั้นนอก: หน้าโฟลเดอร์
# ==========================================================================
def _render_home():
    st.subheader("🖼️ คลังภาพ")

    general = load_general_data()
    counts = {}
    if not general.empty and "แผนก" in general.columns:
        counts = general["แผนก"].astype(str).value_counts().to_dict()

    # ลำดับแผนก: ตาม config ก่อน แล้วต่อด้วยแผนกที่โผล่ในข้อมูลแต่ไม่มีใน config (ข้อมูลเก่า)
    extras = [d for d in counts if d and d not in DEPARTMENTS]
    all_deps = DEPARTMENTS + sorted(extras)

    show_empty = st.session_state.get(SHOW_EMPTY_KEY, False)
    deps = all_deps if show_empty else [d for d in all_deps if counts.get(d, 0) > 0]

    st.markdown("**📂 แผนก**")
    if not deps:
        st.info("ยังไม่มีรูปในคลัง — ไปที่หน้า '📤 ส่งรูป' เพื่อเพิ่มรูปแรกได้เลย")
    else:
        _folder_grid([
            {"title": d, "count": counts.get(d, 0), "value": ("dep", d), "key": f"gal_dep_{d}"}
            for d in deps
        ])

    n_empty = len(all_deps) - len([d for d in all_deps if counts.get(d, 0) > 0])
    if n_empty > 0:
        label = "🔽 ซ่อนแผนกที่ยังไม่มีรูป" if show_empty else f"➕ แสดงแผนกที่ยังไม่มีรูป ({n_empty})"
        if st.button(label, key="gal_toggle_empty"):
            st.session_state[SHOW_EMPTY_KEY] = not show_empty
            st.rerun()

    st.divider()

    # ---------- โฟลเดอร์กิจกรรมที่เผยแพร่ ----------
    st.markdown("**🎉 รูปจากกิจกรรม (ที่เผยแพร่แล้ว)**")
    pub = load_published_activity_data()
    if pub.empty:
        st.caption("ยังไม่มีรูปจากกิจกรรมที่ถูกเผยแพร่เข้าคลังทั่วไป")
        return

    id2name = _activity_names()
    act_counts = pub["activity_id"].astype(str).value_counts().to_dict()
    _folder_grid([
        {
            "title": id2name.get(aid, aid),
            "count": n,
            "value": ("act", aid),
            "key": f"gal_act_{aid}",
        }
        for aid, n in act_counts.items()
    ])


def _folder_grid(folders: list):
    """วางการ์ดโฟลเดอร์เป็นกริด (ไม่มีรูปปก — ไอคอน + ชื่อ + จำนวนรูป เพื่อให้เปิดหน้าไว)"""
    for i in range(0, len(folders), COLS_PER_ROW):
        cols = st.columns(COLS_PER_ROW)
        for col, f in zip(cols, folders[i:i + COLS_PER_ROW]):
            with col:
                with st.container(border=True):
                    st.markdown("### 📁")
                    st.markdown(f"**{f['title']}**")
                    st.caption(f"{f['count']} รูป")
                    if st.button("เปิด", key=f["key"], width="stretch"):
                        st.session_state[FOLDER_KEY] = f["value"]
                        st.rerun()


def _back_button():
    if st.button("⬅️ กลับไปหน้าโฟลเดอร์", key="gal_back"):
        st.session_state.pop(FOLDER_KEY, None)
        st.rerun()


def _activity_names() -> dict:
    """map activity_id → ชื่อกิจกรรม (ไว้ตั้งชื่อโฟลเดอร์)"""
    acts = load_activities()
    if acts.empty or "activity_id" not in acts.columns:
        return {}
    return dict(zip(acts["activity_id"].astype(str), acts["ชื่อกิจกรรม"].astype(str)))


# ==========================================================================
# ชั้นใน: โฟลเดอร์แผนก (คลังทั่วไปเดิม — กรองหมวด/ค้นหา/ลบได้)
# ==========================================================================
def _render_department(dep: str):
    _back_button()
    st.subheader(f"📁 {dep}")

    df = load_general_data()
    if not df.empty and "แผนก" in df.columns:
        df = df[df["แผนก"].astype(str) == str(dep)].copy()
    if df.empty:
        st.info("ยังไม่มีรูปในแผนกนี้")
        return

    df["_dt"] = pd.to_datetime(df["วันเวลา"], errors="coerce")

    # กรองหมวด — ปุ่มเรียงแนวนอน (ไม่ทำเป็นโฟลเดอร์อีกชั้น จะได้ไม่ต้องกดลึก)
    cat = st.radio("หมวด", ["ทั้งหมด"] + CATEGORIES, horizontal=True, key=f"gal_cat_{dep}")
    if cat != "ทั้งหมด":
        df = df[df["หมวด"].astype(str) == cat]

    with st.expander("🔍 ตัวกรองเพิ่มเติม (คำค้น / ช่วงวันที่)"):
        keyword = st.text_input("คำค้น (ชื่อเรื่อง / แท็ก)", key=f"gal_kw_{dep}")
        valid_dates = df["_dt"].dropna()
        date_range = ()
        if not valid_dates.empty:
            date_range = st.date_input(
                "ช่วงวันที่",
                value=(valid_dates.min().date(), valid_dates.max().date()),
                key=f"gal_date_{dep}",
            )

    if keyword.strip():
        kw = keyword.strip().lower()
        title_match = df["ชื่อเรื่อง"].astype(str).str.lower().str.contains(kw)
        tag_match = df["แท็ก"].astype(str).str.lower().str.contains(kw)
        df = df[title_match | tag_match]
    if isinstance(date_range, tuple) and len(date_range) == 2:
        start, end = date_range
        df = df[(df["_dt"].dt.date >= start) & (df["_dt"].dt.date <= end)]

    df = df.sort_values("_dt", ascending=False)
    st.markdown(f"**พบ {len(df)} รูป**")
    if df.empty:
        st.warning("ไม่พบรูปที่ตรงกับเงื่อนไข ลองปรับตัวกรองดูครับ")
        return

    _zip_button(df, key_prefix=f"gal_dep_{dep}", filename="images.zip")
    st.divider()
    page_df = _paginate(df, key=f"gal_page_dep_{dep}")
    _photo_grid(page_df, allow_delete=True, kind="dep")


# ==========================================================================
# ชั้นใน: โฟลเดอร์กิจกรรมที่เผยแพร่ (ดู + โหลดเท่านั้น ลบไม่ได้)
# ==========================================================================
def _render_activity_folder(aid: str):
    _back_button()
    name = _activity_names().get(str(aid), str(aid))
    st.subheader(f"📁 {name}")
    st.caption("รูปจากกิจกรรมที่ผู้ดูแลเผยแพร่ให้ดูได้ — ดาวน์โหลดได้ แต่ลบจากที่นี่ไม่ได้")

    df = load_published_activity_data()
    if not df.empty:
        df = df[df["activity_id"].astype(str) == str(aid)].copy()
    if df.empty:
        # เจ้าของอาจยกเลิกเผยแพร่/ลบรูปไปหลังหน้าโหลด → โฟลเดอร์ว่างได้
        st.info("ไม่มีรูปที่เผยแพร่ในกิจกรรมนี้แล้ว")
        return

    df["_dt"] = pd.to_datetime(df["วันเวลา"], errors="coerce")
    df = df.sort_values("_dt", ascending=False)
    st.markdown(f"**พบ {len(df)} รูป**")

    _zip_button(df, key_prefix=f"gal_act_{aid}", filename="activity_photos.zip")
    st.divider()
    page_df = _paginate(df, key=f"gal_page_act_{aid}")
    _photo_grid(page_df, allow_delete=False, kind="act")


# ==========================================================================
# ส่วนที่ใช้ร่วมกัน: ZIP / แบ่งหน้า / กริดรูป
# ==========================================================================
def _zip_button(df: pd.DataFrame, key_prefix: str, filename: str):
    """ปุ่มเตรียม ZIP ของรูปทั้งหมดในโฟลเดอร์นี้ (เก็บ bytes ไว้ใน session ต่อโฟลเดอร์)"""
    bytes_key = f"{key_prefix}_zip_bytes"
    if st.button("📦 เตรียมไฟล์ ZIP ของรูปในโฟลเดอร์นี้", key=f"{key_prefix}_zip_btn"):
        with st.spinner("กำลังรวมรูปเป็นไฟล์ ZIP..."):
            items = tuple(
                (extract_file_id(r["ลิงก์รูป"]), r["ชื่อไฟล์"]) for _, r in df.iterrows()
            )
            st.session_state[bytes_key] = build_zip(items)
    if st.session_state.get(bytes_key):
        st.download_button(
            "⬇️ ดาวน์โหลด .zip",
            data=st.session_state[bytes_key],
            file_name=filename,
            mime="application/zip",
            key=f"{key_prefix}_zip_dl",
        )


def _paginate(df: pd.DataFrame, key: str) -> pd.DataFrame:
    """แบ่งหน้า — คืนเฉพาะแถวของหน้าที่เลือก"""
    total_pages = max(1, (len(df) + PAGE_SIZE - 1) // PAGE_SIZE)
    # บอกช่วงที่พิมพ์ได้ไปเลย — เดิมพิมพ์เกินแล้วได้แค่ขอบแดง ผู้ใช้งงว่าทำไมกด Enter แล้วเงียบ
    page = st.number_input(
        f"หน้า (1–{total_pages})", min_value=1, max_value=total_pages, value=1, step=1, key=key,
        help=f"มีทั้งหมด {total_pages} หน้า — พิมพ์ได้ตั้งแต่ 1 ถึง {total_pages}",
    )
    start_i = (page - 1) * PAGE_SIZE
    st.caption(f"หน้า {page}/{total_pages}")
    return df.iloc[start_i:start_i + PAGE_SIZE]


def _photo_grid(page_df: pd.DataFrame, allow_delete: bool, kind: str):
    """
    กริดรูป + ดาวน์โหลดเดี่ยว (+ ปุ่มลบถ้า allow_delete)
    kind = "dep" (รูปคลังทั่วไป โชว์ชื่อเรื่อง/แผนก/หมวด) | "act" (รูปกิจกรรม โชว์ผู้ส่ง)
    """
    rows = page_df.to_dict("records")
    for i in range(0, len(rows), COLS_PER_ROW):
        cols = st.columns(COLS_PER_ROW)
        for j, (col, item) in enumerate(zip(cols, rows[i:i + COLS_PER_ROW])):
            with col:
                file_id = extract_file_id(item["ลิงก์รูป"])
                # ใส่ลำดับแถวในคีย์ปุ่ม: file_id เป็น "" ได้ถ้าลิงก์เสีย → 2 ใบขึ้นไปคีย์ชนกัน หน้าล่ม
                uid = f"{i + j}_{file_id}"
                # โหลด bytes รูปจริงมาแสดง (ชัวร์กว่า URL thumbnail ที่บางทีไม่ขึ้น)
                try:
                    st.image(get_thumbnail(file_id), width="stretch")
                except Exception:
                    st.caption("⚠️ โหลดรูปไม่ได้")

                if kind == "dep":
                    st.markdown(
                        f"**{item['ชื่อเรื่อง']}**  \n"
                        f"{item['แผนก']} / {item['หมวด']}  \n"
                        f"🗓️ {item['วันเวลา']}"
                    )
                else:
                    st.caption(f"👤 {item.get('ผู้ส่ง','')} · 🗓️ {item.get('วันเวลา','')}")

                # ปุ่มดาวน์โหลดรูปเดี่ยว (เปิดลิงก์ดาวน์โหลดตรงจาก Drive)
                download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
                st.link_button("⬇️ ดาวน์โหลดรูปนี้", download_url, width="stretch")

                if allow_delete:
                    _delete_button(item, file_id, uid)


def _delete_button(item: dict, file_id: str, uid: str = ""):
    """ปุ่มลบรูป → ย้ายไปถังขยะ (กู้คืนได้ ~30 วัน) มีขั้นยืนยันกันกดพลาด"""
    uid = uid or file_id
    del_key = f"confirm_del_{uid}"
    if st.session_state.get(del_key):
        st.warning("⚠️ ย้ายรูปนี้ไปถังขยะ? (กู้คืนได้ ~30 วัน — แจ้งผู้ดูแลให้กู้)")
        yes, no = st.columns(2)
        if yes.button("✅ ย้ายไปถังขยะ", key=f"yes_{uid}", width="stretch"):
            try:
                trash_photo(file_id, item["ลิงก์รูป"], deleted_by="คลังทั่วไป")
                log_action("คลังทั่วไป", "general", "ลบรูป(ถังขยะ)",
                           detail=str(item.get("ชื่อไฟล์", "")))
                st.session_state.pop(del_key, None)
                st.cache_data.clear()  # ล้าง cache ให้รายการหายทันที
                st.rerun()
            except Exception as e:
                st.error(f"ลบไม่สำเร็จ: {e}")
        if no.button("❌ ยกเลิก", key=f"no_{uid}", width="stretch"):
            st.session_state.pop(del_key, None)
            st.rerun()
    else:
        if st.button("🗑️ ลบรูปนี้", key=f"del_{uid}", width="stretch"):
            st.session_state[del_key] = True
            st.rerun()
