# -*- coding: utf-8 -*-
"""
auth.py — ฟังก์ชันเกี่ยวกับ "รหัสลับ" สำหรับระบบกิจกรรม
ใช้ hash รหัส (รหัสกิจกรรม / รหัส admin) ก่อนเก็บลง Google Sheet — ไม่เก็บรหัสจริง

วิธี hash: sha256 ของ (salt + รหัสจริง)
- salt เก็บไว้ใน st.secrets["HASH_SALT"] (ไม่ฮาร์ดโค้ดลงโค้ด)
- salt ตั้งครั้งเดียวแล้วห้ามเปลี่ยน ไม่งั้น hash เก่าในชีตจะเทียบไม่ตรงทั้งหมด
"""

import hashlib
import hmac

import streamlit as st

import session_store

# ข้อความบนช่อง "จำฉันไว้..." — อ้างค่าเดียวกับ session_store จะได้แก้ที่เดียวแล้วตรงกันทุกที่
REMEMBER_LABEL = f"{session_store.REMEMBER_DAYS} วัน"


def _get_salt() -> str:
    """อ่าน salt จาก secrets (ถ้าลืมตั้งจะ error ชัดเจน ให้รู้ว่าต้องเพิ่มใน secrets)"""
    try:
        return st.secrets["HASH_SALT"]
    except Exception:
        raise RuntimeError(
            "ไม่พบ HASH_SALT ใน secrets — ต้องเพิ่มบรรทัด HASH_SALT = \"...\" "
            "ใน .streamlit/secrets.toml (และใน Secrets ของ Streamlit Cloud)"
        )


def hash_secret(plain: str) -> str:
    """แปลงรหัสจริง → hash (เก็บลงชีต). คืนสตริง hex 64 ตัว"""
    salted = (_get_salt() + str(plain)).encode("utf-8")
    return hashlib.sha256(salted).hexdigest()


def verify_secret(plain: str, hashed: str) -> bool:
    """ตรวจว่ารหัสที่กรอก (plain) ตรงกับ hash ที่เก็บไว้ไหม — เทียบแบบกัน timing attack"""
    if not hashed:
        return False
    return hmac.compare_digest(hash_secret(plain), str(hashed))


def secrets_equal(a, b) -> bool:
    """
    เทียบรหัส 2 ตัวว่าตรงกันไหม แบบกัน timing attack — ใช้กับรหัสที่เก็บเป็น plain ใน secrets

    ⚠️ ห้ามเรียก hmac.compare_digest() กับสตริงตรงๆ: มันรองรับเฉพาะ ASCII
    ถ้ามีอักขระ non-ASCII (เช่นพิมพ์ตอนแป้นค้างภาษาไทย) จะโยน TypeError ใส่หน้าผู้ใช้
    แทนที่จะคืน False → เลย hash เป็น bytes ก่อน แล้วค่อยเทียบ (รับอักขระอะไรก็ได้)
    """
    return hmac.compare_digest(
        hashlib.sha256(str(a).encode("utf-8")).digest(),
        hashlib.sha256(str(b).encode("utf-8")).digest(),
    )


# ===========================================================================
# ระบบ Session + Login (ใช้ในหน้าแรก/router ของแอป)
# role ที่เป็นไปได้: None(ยังไม่ login) / "general" / "user" / "admin" / "superuser"
# ===========================================================================

def ensure_session():
    """ตั้งค่าเริ่มต้นให้ session_state (เรียกทุกครั้งตอนเปิดแอป)"""
    st.session_state.setdefault("view", None)      # หน้า login ที่กำลังเลือกอยู่ (general/user/staff)
    st.session_state.setdefault("role", None)      # สิทธิ์หลัง login
    st.session_state.setdefault("identity", {})    # ข้อมูลตัวตน (ชื่อ/username/กิจกรรม)


def logout():
    """ออกจากระบบ — ล้างทุกอย่างกลับไปหน้าแรก + ลืม cookie ที่จำไว้"""
    session_store.clear()
    st.session_state["view"] = None
    st.session_state["role"] = None
    st.session_state["identity"] = {}
    for k in ("pending_act", "deeplink_error"):
        st.session_state.pop(k, None)
    st.rerun()


def _do_login(role: str, identity: dict, remember: bool):
    """ตั้ง session หลัง login ผ่าน + จำลง cookie ถ้าผู้ใช้ติ๊กไว้ (ใช้ร่วมทุกทางเข้า)"""
    st.session_state["role"] = role
    st.session_state["identity"] = identity
    st.session_state["view"] = None
    st.session_state.pop("pending_act", None)
    if remember:
        session_store.save(role, identity)
    st.rerun()


def render_topbar_logout(label: str = "", show_refresh: bool = False):
    """แถบบนสุด: ข้อความตัวตน (ซ้าย) + ปุ่มรีเฟรช/ออกจากระบบ (ขวา) — ใช้ในหน้าที่ไม่มี sidebar"""
    left, mid, right = st.columns([6, 2, 2])
    left.markdown(f"#### {label}")
    if show_refresh and mid.button("🔄 รีเฟรชข้อมูล", width="stretch", key="topbar_refresh"):
        st.cache_data.clear()
        st.rerun()
    if right.button("🚪 ออกจากระบบ", width="stretch", key="topbar_logout"):
        logout()
    st.divider()


def find_open_activity(code_plain: str):
    """หากิจกรรมที่ 'เปิดอยู่จริง' (สถานะเปิด + ยังไม่หมดอายุ auto-close) และรหัสตรง — คืน dict หรือ None"""
    import google_utils as gu  # import แบบ lazy กัน circular import
    df = gu.load_activities()
    if df.empty:
        return None
    code_hash = hash_secret(code_plain)
    for _, r in df.iterrows():
        if str(r.get("รหัสเข้า_hash")) == code_hash and gu.is_activity_open(r):
            return r.to_dict()
    return None


# ---------- ฟอร์ม login แต่ละแบบ ----------
def identify_code(code_plain: str):
    """
    หัวใจของ "ช่องเดียวจบ" — เดาให้เองว่ารหัสที่พิมพ์มาเป็นรหัสประเภทไหน
    คืน (ประเภท, ข้อมูล) โดยไล่เช็คตามลำดับ:
      1) "general" — รหัสผ่านคลังภาพทั่วไป (APP_PASSWORD)
      2) "user"    — รหัสกิจกรรมที่เปิดอยู่ → คืน dict ของกิจกรรม
      3) "viewer"  — รหัสดูอัลบั้มที่ถูกแชร์ → คืน dict ของการแชร์
      ไม่ตรงเลย → (None, None)

    ทำได้เพราะรหัส 3 แบบนี้เป็นคนละค่ากันอยู่แล้ว ผู้ใช้จึงไม่ต้องรู้ว่าตัวเองเป็นประเภทไหน
    """
    code = str(code_plain).strip()
    if not code:
        return None, None

    # 1) คลังทั่วไป — ใช้ secrets_equal กัน TypeError ตอนผู้ใช้พิมพ์อักขระไทย (บทเรียนเดิม)
    try:
        if secrets_equal(code, st.secrets["APP_PASSWORD"]):
            return "general", None
    except Exception:
        pass

    # 2) รหัสกิจกรรมที่ "เปิดอยู่จริง" (สถานะเปิด + ยังไม่หมดอายุ auto-close)
    act = find_open_activity(code)
    if act:
        return "user", act

    # 3) รหัสดูอัลบั้มส่วนตัว (ยังไม่ถูกถอนสิทธิ์)
    share = find_share_by_code(code)
    if share:
        return "viewer", share

    return None, None


def _activity_name_of(activity_id: str) -> str:
    """หาชื่อกิจกรรมจาก activity_id (ไว้โชว์ให้ผู้ใช้เห็นว่ากำลังเข้าอันไหน)"""
    import google_utils as gu
    acts = gu.load_activities()
    if acts.empty or "activity_id" not in acts.columns:
        return ""
    m = acts[acts["activity_id"].astype(str) == str(activity_id)]
    return str(m.iloc[0]["ชื่อกิจกรรม"]) if not m.empty else ""


def _render_name_step():
    """
    ขั้นที่ 2 ของผู้ส่งรูปกิจกรรม — รหัสถูกแล้ว เหลือถามว่า "คุณชื่ออะไร"
    จำเป็นต้องถาม เพราะต้องบันทึกว่าใครเป็นคนส่งรูป (และใช้กรองแท็บ "รูปของฉัน")
    """
    pend = st.session_state["pending_act"]
    st.success(f"✅ รหัสถูกต้อง — กิจกรรม: **{pend['activity_name']}**")
    with st.form("login_user_name"):
        name = st.text_input("ชื่อของคุณ (ให้รู้ว่าใครส่งรูป)")
        ok = st.form_submit_button("เข้าร่วมกิจกรรม", width="stretch")
    if st.button("← เปลี่ยนรหัส", key="back_from_name"):
        st.session_state.pop("pending_act", None)
        st.rerun()
    if not ok:
        return
    if not name.strip():
        st.error("⚠️ กรอกชื่อของคุณก่อน")
        return
    _do_login("user", {
        "name": name.strip(),
        "activity_id": pend["activity_id"],
        "activity_name": pend["activity_name"],
    }, pend.get("remember", True))


def _login_staff():
    """admin หรือ superuser — username + password"""
    import google_utils as gu
    with st.form("login_staff"):
        u = st.text_input("ชื่อผู้ใช้ (username)")
        p = st.text_input("รหัสผ่าน", type="password")
        remember = st.checkbox(f"จำฉันไว้ {REMEMBER_LABEL} ในเครื่องนี้", value=False,
                               help="อย่าติ๊กถ้าใช้เครื่องกลาง/เครื่องที่คนอื่นใช้ด้วย")
        ok = st.form_submit_button("เข้าสู่ระบบ", width="stretch")
    if not ok:
        return

    username = u.strip()

    # 1) เช็ค superuser ก่อน (รหัสอยู่ใน secrets, เก็บเป็น plain ได้เพราะ secrets ปลอดภัย)
    su_user = st.secrets.get("SUPERUSER_USER", "")
    su_pass = st.secrets.get("SUPERUSER_PASS", "")
    if username and username == su_user and secrets_equal(p, su_pass):
        _do_login("superuser", {"username": username}, remember)
        return

    # 2) เช็ค admin จากแท็บ Users (รหัสเก็บเป็น hash)
    acct = gu.find_user(username)
    if acct and str(acct.get("role")) == "admin" and verify_secret(p, acct.get("password_hash")):
        # รหัสถูกแล้ว — ค่อยบอกสถานะบัญชีได้ (ถ้าบอกก่อนเช็ครหัส = เผยว่ามี username นี้อยู่จริง)
        status = str(acct.get("สถานะ", "")).strip()
        if status == gu.USER_PENDING:
            st.info("⏳ บัญชีนี้สมัครไว้แล้ว **รอหัวหน้าอนุมัติ** — ติดต่อผู้ดูแลระบบให้กดอนุมัติให้ก่อน")
            return
        if status != gu.USER_ACTIVE:
            st.error("🚫 บัญชีนี้ถูกระงับการใช้งาน — ติดต่อผู้ดูแลระบบ")
            return
        _do_login("admin", {
            "username": username,
            "fullname": acct.get("ชื่อ-นามสกุล", ""),
        }, remember)
        return

    st.error("❌ ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")


def _forgot_password():
    """
    "ลืมรหัสผ่าน" — ส่งคำขอเข้าคิวให้ผู้ดูแลระบบตั้งรหัสใหม่ให้
    ไม่แตะรหัสเดิม (ถ้านึกออกทีหลังก็ยัง login ได้) และ
    ขึ้นข้อความเดียวกันเสมอไม่ว่าจะมี username นี้จริงไหม — กันคนไล่เดาว่ามีใครอยู่ในระบบบ้าง
    """
    import google_utils as gu
    st.caption("ระบบจะแจ้งผู้ดูแลให้ตั้งรหัสใหม่ให้ แล้วแจ้งคุณโดยตรง")
    with st.form("forgot_pw", clear_on_submit=True):
        u = st.text_input("username ของคุณ")
        ok = st.form_submit_button("ส่งคำขอรีเซ็ตรหัส", width="stretch")
    if not ok:
        return
    if not u.strip():
        st.error("⚠️ กรอก username ก่อน")
        return
    try:
        if gu.request_password_reset(u.strip()):
            gu.log_action(u.strip(), "admin", "ขอรีเซ็ตรหัส", "")
    except Exception:
        pass
    st.success("✅ ส่งคำขอแล้ว — ติดต่อผู้ดูแลระบบเพื่อรับรหัสใหม่ได้เลย")


def render_change_password_box():
    """กล่อง "เปลี่ยนรหัสผ่าน" ของเจ้าตัว (ใส่รหัสเดิมก่อน) — ใช้ในหน้า admin"""
    import google_utils as gu
    me = st.session_state.get("identity", {}).get("username", "")
    with st.expander("🔑 เปลี่ยนรหัสผ่านของฉัน"):
        with st.form("change_pw", clear_on_submit=True):
            old = st.text_input("รหัสผ่านเดิม", type="password")
            p1 = st.text_input("รหัสผ่านใหม่", type="password")
            p2 = st.text_input("ยืนยันรหัสผ่านใหม่", type="password")
            ok = st.form_submit_button("เปลี่ยนรหัสผ่าน", width="stretch")
        if not ok:
            return
        acct = gu.find_user(me)
        if not acct or not verify_secret(old, acct.get("password_hash")):
            st.error("❌ รหัสผ่านเดิมไม่ถูกต้อง")
            return
        if p1 != p2:
            st.error("⚠️ รหัสผ่านใหม่ 2 ช่องไม่ตรงกัน")
            return
        if len(p1) < 6:
            st.error("⚠️ รหัสผ่านต้องยาวอย่างน้อย 6 ตัว")
            return
        gu.set_user_password(me, hash_secret(p1))
        gu.log_action(me, "admin", "เปลี่ยนรหัสผ่านเอง", "")
        st.success("✅ เปลี่ยนรหัสผ่านแล้ว — ครั้งหน้าใช้รหัสใหม่")


def _signup_admin():
    """
    สมัครบัญชี admin เอง — บันทึกเป็นสถานะ "รออนุมัติ" ยัง login ไม่ได้
    จนกว่า superuser จะกดอนุมัติในหน้า "จัดการบัญชี admin"

    ⚠️ อีเมลที่กรอกเอง "ไม่ได้พิสูจน์" ว่าเป็นเจ้าของอีเมลจริง (ไม่ได้ส่งเมลยืนยัน)
    ความปลอดภัยมาจากขั้นที่หัวหน้าดูรายชื่อแล้วกดอนุมัติเฉพาะคนที่รู้จัก
    """
    import google_utils as gu
    import config

    # โดเมนบริษัท: ตรงอันใดอันหนึ่งก็ผ่าน ; list ว่าง = ไม่บังคับ
    domains = [str(d).strip() for d in getattr(config, "COMPANY_EMAIL_DOMAINS", []) if str(d).strip()]
    st.caption(
        "กรอกข้อมูลแล้วรอหัวหน้ากดอนุมัติ จึงจะเข้าใช้งานได้"
        + (f" · ต้องใช้อีเมลบริษัท ({' / '.join(domains)})" if domains else "")
    )
    with st.form("signup_admin", clear_on_submit=False):
        u = st.text_input("username ที่อยากใช้ (ภาษาอังกฤษ/ตัวเลข)")
        fullname = st.text_input("ชื่อ-นามสกุล")
        email = st.text_input("อีเมลบริษัท",
                              placeholder=f"yourname{domains[0] if domains else '@company.com'}")
        p1 = st.text_input("ตั้งรหัสผ่าน", type="password")
        p2 = st.text_input("ยืนยันรหัสผ่านอีกครั้ง", type="password")
        ok = st.form_submit_button("ส่งคำขอสมัคร", width="stretch")
    if not ok:
        return

    username, fullname, email = u.strip(), fullname.strip(), email.strip()
    if not username or not fullname or not email or not p1:
        st.error("⚠️ กรอกให้ครบทุกช่อง")
        return
    if p1 != p2:
        st.error("⚠️ รหัสผ่าน 2 ช่องไม่ตรงกัน")
        return
    if len(p1) < 6:
        st.error("⚠️ รหัสผ่านต้องยาวอย่างน้อย 6 ตัว")
        return
    if domains and not any(email.lower().endswith(d.lower()) for d in domains):
        st.error("⚠️ ต้องใช้อีเมลบริษัทที่ลงท้ายด้วย " + " หรือ ".join(domains) + " เท่านั้น")
        return
    if gu.find_user(username):
        st.error(f"❌ username “{username}” มีคนใช้แล้ว — เปลี่ยนชื่ออื่น")
        return
    if gu.email_taken(email):
        st.error("❌ อีเมลนี้เคยสมัครไว้แล้ว — ถ้าลืมรหัส ให้ติดต่อผู้ดูแลระบบ")
        return

    gu.add_user(username, hash_secret(p1), fullname,
                role="admin", status=gu.USER_PENDING, email=email)
    gu.log_action(username, "guest", "สมัครบัญชี admin", f"{fullname} · {email}")
    st.success("✅ ส่งคำขอแล้ว — รอหัวหน้าอนุมัติ แล้วค่อยกลับมา login ด้วย username/รหัสที่ตั้งไว้")


def find_share_by_code(code_plain: str):
    """หา 'การแชร์อัลบั้ม' ที่รหัสดูส่วนตัวตรง + ยังไม่ถูกถอนสิทธิ์ — คืน dict (activity_id, ชื่อผู้ดู) หรือ None"""
    import google_utils as gu  # lazy import กัน circular import
    df = gu.load_shares()
    if df.empty or "รหัสดู_hash" not in df.columns:
        return None
    code_hash = hash_secret(code_plain)
    for _, r in df.iterrows():
        if str(r.get("รหัสดู_hash")) == code_hash and str(r.get("สถานะ")) != "ปิด":
            return r.to_dict()
    return None


def _render_open_activities(remember: bool = True):
    """
    ปุ่มกิจกรรมที่ "ใครก็ส่งรูปได้" — กดชื่อแล้วข้ามไปกรอกชื่อตัวเองได้เลย ไม่ต้องมีรหัส
    (แนวคิดจากหัวหน้า: ให้ส่งง่ายเหมือนกลุ่มไลน์ ใครอยู่ก็ส่งๆ ไป)
    """
    import google_utils as gu  # lazy import กัน circular import
    opens = gu.open_join_activities()
    if opens.empty:
        return
    st.markdown("**📤 ส่งรูปเข้ากิจกรรมที่เปิดให้ทุกคน — กดได้เลย ไม่ต้องใช้รหัส**")
    for _, a in opens.iterrows():
        aid = str(a["activity_id"])
        nm = str(a["ชื่อกิจกรรม"])
        if st.button(f"📤 {nm}", key=f"openact_{aid}", width="stretch"):
            st.session_state["pending_act"] = {
                "activity_id": aid, "activity_name": nm, "remember": remember,
            }
            st.rerun()


def _render_public_albums():
    """ปุ่มอัลบั้มสาธารณะ — กดชื่อเข้าดูได้เลย ไม่ต้องมีรหัส (ของเดิม ย้ายมาไว้ใต้ช่องรหัส)"""
    import google_utils as gu  # lazy import กัน circular import
    pub = gu.public_activities()
    if pub.empty:
        return
    st.markdown("**หรือดูอัลบั้มสาธารณะ (ใครก็ดูได้)**")
    for _, a in pub.iterrows():
        aid = str(a["activity_id"])
        nm = str(a["ชื่อกิจกรรม"])
        if st.button(f"🖼️ {nm}", key=f"pubalbum_{aid}", width="stretch"):
            _do_login("viewer", {
                "activity_id": aid, "activity_name": nm, "viewer_name": "(สาธารณะ)",
            }, remember=False)   # อัลบั้มสาธารณะไม่ต้องจำ เข้าใหม่ก็แค่กดปุ่ม


def handle_deeplink():
    """
    อ่าน query param จาก QR deep-link แล้วพาเข้าให้อัตโนมัติ (เรียกตอนเปิดแอป ก่อน render):
      ?viewcode=XXX → เข้าอัลบั้มเลย (role=viewer) ถ้ารหัสถูก
      ?actcode=XXX  → รหัสถูกแล้ว ข้ามไปขั้นถามชื่อเลย (เหลือกรอกชื่ออย่างเดียว)
    """
    if st.session_state.get("role"):
        return  # login อยู่แล้ว ไม่ต้องจัดการ deep-link ซ้ำ

    qp = st.query_params
    viewcode = str(qp.get("viewcode", "") or "").strip()
    actcode = str(qp.get("actcode", "") or "").strip()
    if not viewcode and not actcode:
        return

    if viewcode:
        share = find_share_by_code(viewcode)
        if share:
            aid = str(share.get("activity_id"))
            st.session_state["role"] = "viewer"
            st.session_state["identity"] = {
                "activity_id": aid, "activity_name": _activity_name_of(aid),
                "viewer_name": str(share.get("ชื่อผู้ดู", "")),
            }
            st.session_state["view"] = None
        else:
            st.session_state["deeplink_error"] = "❌ รหัสดูใน QR ไม่ถูกต้อง หรือถูกถอนสิทธิ์แล้ว"
    elif actcode:
        act = find_open_activity(actcode)
        if act:
            # รหัสถูกแล้ว → ข้ามช่องรหัสไปขั้นถามชื่อเลย
            st.session_state["pending_act"] = {
                "activity_id": str(act.get("activity_id")),
                "activity_name": str(act.get("ชื่อกิจกรรม", "")),
                "remember": True,
            }
        else:
            st.session_state["deeplink_error"] = "❌ รหัสกิจกรรมใน QR ไม่ถูกต้อง หรือกิจกรรมปิดแล้ว"

    # ล้าง query param ทิ้ง กัน refresh แล้วเข้าซ้ำ + URL สะอาด
    try:
        st.query_params.clear()
    except Exception:
        pass


def render_landing():
    """
    หน้าแรก — "ช่องเดียวจบ"
    ผู้ใช้ไม่ต้องเลือกก่อนว่าตัวเองเป็นประเภทไหน แค่ใส่รหัสที่มีอยู่ในมือ
    ระบบเดาให้เอง (identify_code) แล้วพาไปหน้าที่ตรงกับสิทธิ์
    """
    # ข้อความ error จาก deep-link (QR รหัสผิด/หมดอายุ)
    err = st.session_state.pop("deeplink_error", None)
    if err:
        st.error(err)

    st.title("📷 คลังภาพกลางของบริษัท")

    # รหัสกิจกรรมถูกแล้ว → ข้ามมาขั้นถามชื่อ (ไม่ต้องโชว์ช่องรหัสอีก)
    if st.session_state.get("pending_act"):
        _render_name_step()
        return

    st.caption("ใส่รหัสที่คุณได้รับ — ระบบจะพาไปหน้าที่ตรงกับสิทธิ์ของคุณเอง")

    with st.form("login_main"):
        code = st.text_input("รหัสของคุณ", type="password",
                             placeholder="รหัสคลังภาพ / รหัสกิจกรรม / รหัสดูอัลบั้ม")
        remember = st.checkbox(f"จำฉันไว้ {REMEMBER_LABEL} ในเครื่องนี้", value=True,
                               help="อย่าติ๊กถ้าใช้เครื่องกลาง/เครื่องที่คนอื่นใช้ด้วย")
        ok = st.form_submit_button("เข้าใช้งาน", width="stretch")

    if ok:
        kind, data = identify_code(code)
        if kind == "general":
            _do_login("general", {}, remember)
        elif kind == "user":
            # รู้แล้วว่าเป็นกิจกรรมไหน เหลือถามชื่อ → ไปขั้นที่ 2
            st.session_state["pending_act"] = {
                "activity_id": str(data.get("activity_id")),
                "activity_name": str(data.get("ชื่อกิจกรรม", "")),
                "remember": remember,
            }
            st.rerun()
        elif kind == "viewer":
            aid = str(data.get("activity_id"))
            _do_login("viewer", {
                "activity_id": aid, "activity_name": _activity_name_of(aid),
                "viewer_name": str(data.get("ชื่อผู้ดู", "")),
            }, remember)
        else:
            st.error("❌ รหัสไม่ถูกต้อง หรือหมดอายุแล้ว")

    st.divider()
    _render_open_activities(remember)
    _render_public_albums()

    # admin / ผู้ดูแลระบบ — พับไว้ เพราะคนส่วนใหญ่ไม่ได้ใช้ทางนี้
    with st.expander("🔐 สำหรับ admin / ผู้ดูแลระบบ"):
        tab_in, tab_up, tab_forgot = st.tabs(
            ["เข้าสู่ระบบ", "สมัครบัญชี admin", "ลืมรหัสผ่าน"])
        with tab_in:
            _login_staff()
        with tab_up:
            _signup_admin()
        with tab_forgot:
            _forgot_password()


def restore_session():
    """
    คืน login จาก cookie ตอนเปิดแอป (เรียกก่อน render — เฉพาะตอนที่ยังไม่ได้ login)

    ⚠️ ไม่เชื่อ cookie อย่างเดียว — เช็คสิทธิ์ซ้ำกับชีตทุกครั้ง เพราะระหว่างที่จำไว้
    กิจกรรมอาจถูกปิด/ลบ หรือบัญชี admin อาจถูกระงับไปแล้ว ถ้าไม่เช็คสิทธิ์จะค้างอยู่
    """
    if st.session_state.get("role"):
        return

    data = session_store.load()
    if not data:
        return

    role = data.get("role")
    ident = data.get("identity") or {}

    if role in ("user", "viewer"):
        import google_utils as gu
        aid = str(ident.get("activity_id", ""))
        acts = gu.load_activities()
        if acts.empty or "activity_id" not in acts.columns:
            return
        m = acts[acts["activity_id"].astype(str) == aid]
        if m.empty:
            return                                   # กิจกรรมถูกลบไปแล้ว
        # คนส่งรูปต้องเข้าได้เฉพาะตอนกิจกรรมยังเปิด ; คนดูอัลบั้มดูย้อนหลังได้แม้ปิดแล้ว
        if role == "user" and not gu.is_activity_open(m.iloc[0]):
            return

    elif role == "admin":
        import google_utils as gu
        acct = gu.find_user(str(ident.get("username", "")))
        if not (acct and str(acct.get("สถานะ")) == gu.USER_ACTIVE and str(acct.get("role")) == "admin"):
            return                                   # บัญชีถูกปิด/ลบ/ลดสิทธิ์/ยังรออนุมัติ

    elif role == "superuser":
        if str(ident.get("username", "")) != str(st.secrets.get("SUPERUSER_USER", "")):
            return

    elif role != "general":
        return                                       # role แปลกปลอม ไม่รับ

    st.session_state["role"] = role
    st.session_state["identity"] = ident
    st.session_state["view"] = None
