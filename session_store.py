# -*- coding: utf-8 -*-
"""
session_store.py — "จำฉันไว้" ข้าม refresh ด้วย cookie

ทำไมต้องมีไฟล์นี้:
  Streamlit เก็บสถานะ login ไว้ใน st.session_state ซึ่ง "หายทุกครั้งที่ refresh หน้า"
  → ผู้ใช้ต้องกรอกรหัสใหม่บ่อยมาก. เลยเก็บ token ลง cookie ของเบราว์เซอร์แทน

วิธีทำให้ปลอดภัย (สำคัญ):
  cookie อยู่ในเครื่องผู้ใช้ = แก้ไขได้เอง → **ห้ามเชื่อค่าใน cookie ตรงๆ**
  เลยเซ็นด้วย HMAC-SHA256 โดยใช้ HASH_SALT (ที่อยู่ใน secrets) เป็นกุญแจ
  ถ้าใครแก้ payload เอง (เช่น เปลี่ยน role เป็น superuser) ลายเซ็นจะไม่ตรง → ตีตกทันที
  และฝั่งเรียกใช้ (auth.restore_session) ยัง "เช็คสิทธิ์ซ้ำกับชีต" อีกชั้นด้วย

ข้อจำกัดที่ยอมรับ:
  - อ่าน cookie ใช้ st.context.cookies (อ่านตรงจาก request header = ไม่มีปัญหา race)
  - เขียน/ลบ cookie ต้องพึ่ง component ภายนอก (extra-streamlit-components)
    ถ้า lib หายหรือพัง → **แอปต้องยังใช้งานได้ปกติ แค่ไม่จำ login** (ทุกฟังก์ชันกลืน error หมด)
"""

import base64
import hashlib
import hmac
import json
import time

import streamlit as st

COOKIE_NAME = "iw_session"      # ชื่อ cookie ที่เก็บ token
REMEMBER_DAYS = 1               # จำไว้กี่วัน (ตกลงกับหัวหน้า = 1 วัน) — แก้ตัวเลขนี้ที่เดียวพอ
_COOKIE_KEY = "iw_cookie_mgr"   # key ของ component (ต้องคงที่ กัน duplicate widget id)


# ---------------------------------------------------------------------------
# สร้าง / ตรวจ token
# ---------------------------------------------------------------------------
def _salt() -> str:
    """กุญแจสำหรับเซ็น token — ใช้ HASH_SALT ตัวเดียวกับที่ hash รหัสผ่าน"""
    return str(st.secrets["HASH_SALT"])


def _b64e(raw: bytes) -> str:
    """base64 แบบ url-safe และตัด '=' ท้ายออก (กัน cookie มีอักขระแปลก)"""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(txt: str) -> bytes:
    """ถอด base64 — เติม '=' กลับให้ครบ 4 ตัวก่อน (เพราะตอนสร้างเราตัดทิ้ง)"""
    pad = "=" * (-len(txt) % 4)
    return base64.urlsafe_b64decode(txt + pad)


def make_token(role: str, identity: dict, days: int = REMEMBER_DAYS) -> str:
    """สร้าง token ที่เซ็นแล้ว: <payload_base64>.<ลายเซ็น hex>"""
    payload = {
        "role": role,
        "identity": identity or {},
        "exp": int(time.time()) + days * 86400,   # วันหมดอายุ (เก็บใน payload ด้วย ไม่เชื่อ cookie อย่างเดียว)
    }
    body = _b64e(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_salt().encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_token(token: str):
    """
    ตรวจ token → คืน dict {"role","identity"} ถ้าใช้ได้ / None ถ้าใช้ไม่ได้
    ตีตกเมื่อ: รูปแบบผิด / ลายเซ็นไม่ตรง (โดนแก้) / หมดอายุแล้ว
    """
    try:
        body, sig = str(token).split(".", 1)
    except (ValueError, AttributeError):
        return None

    expect = hmac.new(_salt().encode("utf-8"), body.encode("ascii"), hashlib.sha256).hexdigest()
    # เทียบลายเซ็นแบบกัน timing attack (ทั้งคู่เป็น hex ASCII จึงใช้ compare_digest กับ str ได้ปลอดภัย)
    if not hmac.compare_digest(sig, expect):
        return None

    try:
        payload = json.loads(_b64d(body).decode("utf-8"))
    except Exception:
        return None

    if int(payload.get("exp", 0)) < time.time():
        return None                      # หมดอายุ
    if not payload.get("role"):
        return None

    return {"role": payload["role"], "identity": payload.get("identity") or {}}


# ---------------------------------------------------------------------------
# อ่าน / เขียน cookie จริง
# ---------------------------------------------------------------------------
def _manager():
    """
    ตัวเขียน/ลบ cookie (component ภายนอก) — คืน None ถ้าใช้ไม่ได้
    ใช้ cache_resource ให้มีตัวเดียวทั้งแอป (สร้างซ้ำ = duplicate widget id)
    """
    try:
        return _get_manager()
    except Exception:
        return None


@st.cache_resource(show_spinner=False)
def _get_manager():
    import extra_streamlit_components as stx
    return stx.CookieManager(key=_COOKIE_KEY)


def load() -> dict | None:
    """
    อ่าน session ที่จำไว้จาก cookie — คืน {"role","identity"} หรือ None

    อ่านจาก st.context.cookies (ค่าจาก request header โดยตรง) แทนที่จะอ่านผ่าน component
    เพราะ component อ่านแบบ async → รอบแรกมักได้ค่าว่าง แล้วหน้า login จะกะพริบ
    """
    try:
        raw = st.context.cookies.get(COOKIE_NAME)
    except Exception:
        return None
    if not raw:
        return None
    return read_token(raw)


def save(role: str, identity: dict, days: int = REMEMBER_DAYS) -> None:
    """จำ login ลง cookie (เงียบไว้ถ้าทำไม่ได้ — ไม่ให้ล้มการ login)"""
    cm = _manager()
    if cm is None:
        return
    try:
        from datetime import datetime, timedelta, timezone
        cm.set(
            COOKIE_NAME,
            make_token(role, identity, days),
            expires_at=datetime.now(timezone.utc) + timedelta(days=days),
            key="iw_cookie_set",
        )
    except Exception:
        pass


def clear() -> None:
    """ลืม login (ตอนกดออกจากระบบ) — ทั้งลบ cookie และเขียนทับด้วยค่าหมดอายุกันลบไม่ติด"""
    cm = _manager()
    if cm is None:
        return
    try:
        cm.delete(COOKIE_NAME, key="iw_cookie_del")
    except Exception:
        # ลบไม่สำเร็จ (เช่น cookie ไม่มีอยู่) → เขียนทับด้วย token ที่หมดอายุแล้วแทน
        try:
            from datetime import datetime, timedelta, timezone
            cm.set(
                COOKIE_NAME, "",
                expires_at=datetime.now(timezone.utc) - timedelta(days=1),
                key="iw_cookie_kill",
            )
        except Exception:
            pass
