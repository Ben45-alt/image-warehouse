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
    """ออกจากระบบ — ล้างทุกอย่างกลับไปหน้าแรก"""
    st.session_state["view"] = None
    st.session_state["role"] = None
    st.session_state["identity"] = {}
    for k in ("prefill_actid", "prefill_actcode", "deeplink_error"):
        st.session_state.pop(k, None)
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
def _login_general():
    """คลังภาพทั่วไป (ระบบเดิม) — ใช้ APP_PASSWORD"""
    with st.form("login_general"):
        pw = st.text_input("รหัสผ่านคลังภาพ", type="password")
        ok = st.form_submit_button("เข้าสู่ระบบ", width="stretch")
    if ok:
        if pw == st.secrets["APP_PASSWORD"]:
            st.session_state["role"] = "general"
            st.session_state["view"] = None
            st.rerun()
        else:
            st.error("❌ รหัสผ่านไม่ถูกต้อง")


def _login_user():
    """
    ผู้เข้าร่วมกิจกรรม — เลือกชื่อกิจกรรมที่ 'เปิด' อยู่ (dropdown) + กรอกรหัส + ชื่อ
    โชว์เฉพาะกิจกรรมที่เปิด ; ต้องกรอกรหัสให้ตรงกับ "กิจกรรมที่เลือก" ถึงจะเข้าได้
    (รองรับหลายกิจกรรมเปิดพร้อมกัน — เลือกอันที่จะเข้าได้ชัดเจน)
    """
    import google_utils as gu  # lazy import กัน circular import

    # เฉพาะกิจกรรมที่ "เปิดอยู่จริง" = สถานะเปิด + ยังไม่หมดอายุ auto-close (7 วันจากวันสร้าง)
    open_acts = gu.open_activities(gu.load_activities())
    if open_acts.empty:
        st.info("ตอนนี้ยังไม่มีกิจกรรมที่เปิดอยู่ — ติดต่อหัวหน้า/ผู้ดูแลให้เปิดกิจกรรมก่อน")
        return

    # ใช้ activity_id เป็น "ค่าจริง" ของ dropdown (ไม่ซ้ำกันแน่นอน กันชื่อกิจกรรมซ้ำ) แต่โชว์เป็นชื่อ
    ids = list(open_acts["activity_id"].astype(str))
    id2name = dict(zip(ids, open_acts["ชื่อกิจกรรม"].astype(str)))
    id2hash = dict(zip(ids, open_acts["รหัสเข้า_hash"].astype(str)))

    # ค่าที่เติมมาจาก QR deep-link (?actcode) — เลือกกิจกรรม + เติมรหัสให้ เหลือแค่กรอกชื่อ
    prefill_id = st.session_state.get("prefill_actid", "")
    prefill_code = st.session_state.get("prefill_actcode", "")
    default_index = ids.index(prefill_id) if prefill_id in ids else 0
    if prefill_id in ids:
        st.info("📱 เปิดจาก QR แล้ว — เลือกกิจกรรมและใส่รหัสให้อัตโนมัติ เหลือแค่กรอกชื่อของคุณ")

    with st.form("login_user"):
        sel_id = st.selectbox("เลือกกิจกรรม", ids, index=default_index,
                              format_func=lambda i: id2name.get(i, i))
        code = st.text_input("รหัสกิจกรรม", value=prefill_code)
        name = st.text_input("ชื่อของคุณ")
        ok = st.form_submit_button("เข้าร่วมกิจกรรม", width="stretch")
    if not ok:
        return

    if not code.strip() or not name.strip():
        st.error("⚠️ กรอกรหัสกิจกรรมและชื่อให้ครบ")
        return
    # รหัสต้องตรงกับ "กิจกรรมที่เลือก" เท่านั้น (กันกรอกรหัสกิจกรรมอื่นแล้วหลุดเข้าผิดอัน)
    if not verify_secret(code.strip(), id2hash.get(sel_id)):
        st.error("❌ รหัสไม่ตรงกับกิจกรรมที่เลือก")
        return

    st.session_state["role"] = "user"
    st.session_state["identity"] = {
        "name": name.strip(),
        "activity_id": sel_id,
        "activity_name": id2name.get(sel_id, ""),
    }
    st.session_state["view"] = None
    st.session_state.pop("prefill_actid", None)
    st.session_state.pop("prefill_actcode", None)
    st.rerun()


def _login_staff():
    """admin หรือ superuser — username + password"""
    import google_utils as gu
    with st.form("login_staff"):
        u = st.text_input("ชื่อผู้ใช้ (username)")
        p = st.text_input("รหัสผ่าน", type="password")
        ok = st.form_submit_button("เข้าสู่ระบบ", width="stretch")
    if not ok:
        return

    username = u.strip()

    # 1) เช็ค superuser ก่อน (รหัสอยู่ใน secrets, เก็บเป็น plain ได้เพราะ secrets ปลอดภัย)
    su_user = st.secrets.get("SUPERUSER_USER", "")
    su_pass = st.secrets.get("SUPERUSER_PASS", "")
    if username and username == su_user and secrets_equal(p, su_pass):
        st.session_state["role"] = "superuser"
        st.session_state["identity"] = {"username": username}
        st.session_state["view"] = None
        st.rerun()
        return

    # 2) เช็ค admin จากแท็บ Users (รหัสเก็บเป็น hash)
    acct = gu.find_user(username)
    if (
        acct
        and str(acct.get("สถานะ")) == "ใช้งาน"
        and str(acct.get("role")) == "admin"
        and verify_secret(p, acct.get("password_hash"))
    ):
        st.session_state["role"] = "admin"
        st.session_state["identity"] = {
            "username": username,
            "fullname": acct.get("ชื่อ-นามสกุล", ""),
        }
        st.session_state["view"] = None
        st.rerun()
        return

    st.error("❌ ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")


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


def _login_viewer():
    """
    ดูอัลบั้มกิจกรรม 2 ทาง:
      1) อัลบั้มสาธารณะ (visibility=ทุกคน) — กดชื่อเข้าดูได้เลย ไม่ต้องมีรหัส
      2) รหัสดูส่วนตัว (ถูกแชร์เฉพาะคน) — กรอกรหัส → เข้าอัลบั้มที่ถูกแชร์
    """
    import google_utils as gu  # lazy import กัน circular import

    # ----- 1) อัลบั้มสาธารณะ -----
    st.markdown("**อัลบั้มสาธารณะ (ใครก็ดูได้)**")
    pub = gu.public_activities()
    if pub.empty:
        st.caption("— ยังไม่มีอัลบั้มสาธารณะ —")
    else:
        for _, a in pub.iterrows():
            aid = str(a["activity_id"])
            nm = str(a["ชื่อกิจกรรม"])
            if st.button(f"🖼️ {nm}", key=f"pubalbum_{aid}", width="stretch"):
                st.session_state["role"] = "viewer"
                st.session_state["identity"] = {
                    "activity_id": aid, "activity_name": nm, "viewer_name": "(สาธารณะ)",
                }
                st.session_state["view"] = None
                st.rerun()

    st.divider()

    # ----- 2) รหัสดูส่วนตัว -----
    st.markdown("**มีรหัสดูส่วนตัว? (ถูกแชร์เฉพาะคน)**")
    with st.form("login_viewer"):
        code = st.text_input("รหัสดูอัลบั้ม")
        ok = st.form_submit_button("เปิดดูอัลบั้ม", width="stretch")
    if not ok:
        return
    if not code.strip():
        st.error("⚠️ กรอกรหัสดูก่อน")
        return
    share = find_share_by_code(code.strip())
    if not share:
        st.error("❌ รหัสไม่ถูกต้อง หรือถูกถอนสิทธิ์แล้ว")
        return

    aid = str(share.get("activity_id"))
    # หาชื่อกิจกรรมจาก activity_id
    acts = gu.load_activities()
    nm = ""
    if not acts.empty and "activity_id" in acts.columns:
        m = acts[acts["activity_id"].astype(str) == aid]
        if not m.empty:
            nm = str(m.iloc[0]["ชื่อกิจกรรม"])
    st.session_state["role"] = "viewer"
    st.session_state["identity"] = {
        "activity_id": aid, "activity_name": nm,
        "viewer_name": str(share.get("ชื่อผู้ดู", "")),
    }
    st.session_state["view"] = None
    st.rerun()


def handle_deeplink():
    """
    อ่าน query param จาก QR deep-link แล้วพาเข้าให้อัตโนมัติ (เรียกตอนเปิดแอป ก่อน render):
      ?viewcode=XXX → เข้าอัลบั้มเลย (role=viewer) ถ้ารหัสถูก
      ?actcode=XXX  → เปิดหน้าส่งรูป + เลือกกิจกรรม + เติมรหัสให้ (เหลือแค่กรอกชื่อ)
    """
    if st.session_state.get("role"):
        return  # login อยู่แล้ว ไม่ต้องจัดการ deep-link ซ้ำ

    qp = st.query_params
    viewcode = str(qp.get("viewcode", "") or "").strip()
    actcode = str(qp.get("actcode", "") or "").strip()
    if not viewcode and not actcode:
        return

    import google_utils as gu  # lazy import กัน circular import

    if viewcode:
        share = find_share_by_code(viewcode)
        if share:
            aid = str(share.get("activity_id"))
            nm = ""
            acts = gu.load_activities()
            if not acts.empty and "activity_id" in acts.columns:
                m = acts[acts["activity_id"].astype(str) == aid]
                if not m.empty:
                    nm = str(m.iloc[0]["ชื่อกิจกรรม"])
            st.session_state["role"] = "viewer"
            st.session_state["identity"] = {
                "activity_id": aid, "activity_name": nm,
                "viewer_name": str(share.get("ชื่อผู้ดู", "")),
            }
            st.session_state["view"] = None
        else:
            st.session_state["deeplink_error"] = "❌ รหัสดูใน QR ไม่ถูกต้อง หรือถูกถอนสิทธิ์แล้ว"
    elif actcode:
        act = find_open_activity(actcode)
        if act:
            st.session_state["view"] = "user"
            st.session_state["prefill_actid"] = str(act.get("activity_id"))
            st.session_state["prefill_actcode"] = actcode
        else:
            st.session_state["deeplink_error"] = "❌ รหัสกิจกรรมใน QR ไม่ถูกต้อง หรือกิจกรรมปิดแล้ว"

    # ล้าง query param ทิ้ง กัน refresh แล้วเข้าซ้ำ + URL สะอาด
    try:
        st.query_params.clear()
    except Exception:
        pass


def render_landing():
    """หน้าแรก: เลือกประเภทการเข้าใช้ → แสดงฟอร์ม login ที่เลือก"""
    view = st.session_state.get("view")

    # ข้อความ error จาก deep-link (QR รหัสผิด/หมดอายุ)
    err = st.session_state.pop("deeplink_error", None)
    if err:
        st.error(err)

    # ----- ยังไม่เลือก = โชว์ 4 การ์ดให้เลือก -----
    if view is None:
        st.title("📷 คลังภาพกลางของบริษัท")
        st.caption("เลือกประเภทการเข้าใช้งาน")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.markdown("### 📁 คลังทั่วไป")
            st.write("พนักงานทั่วไป — ส่ง/ค้นหารูปตามแผนก")
            if st.button("เข้าคลังทั่วไป", width="stretch", key="b_general"):
                st.session_state["view"] = "general"
                st.rerun()
        with c2:
            st.markdown("### 📤 ส่งรูปกิจกรรม")
            st.write("มีรหัสกิจกรรม — ถ่าย/ส่งรูป")
            if st.button("ส่งรูปกิจกรรม", width="stretch", key="b_user"):
                st.session_state["view"] = "user"
                st.rerun()
        with c3:
            st.markdown("### 🖼️ ดูอัลบั้ม")
            st.write("ดูรูป (สาธารณะ/ถูกแชร์)")
            if st.button("ดูอัลบั้มกิจกรรม", width="stretch", key="b_viewer"):
                st.session_state["view"] = "viewer"
                st.rerun()
        with c4:
            st.markdown("### 🔐 เข้าสู่ระบบ")
            st.write("admin / ผู้ดูแลระบบ")
            if st.button("เข้าสู่ระบบ", width="stretch", key="b_staff"):
                st.session_state["view"] = "staff"
                st.rerun()
        return

    # ----- เลือกแล้ว = ปุ่มย้อนกลับ + ฟอร์ม login -----
    if st.button("← กลับหน้าแรก", key="back_landing"):
        st.session_state["view"] = None
        st.rerun()

    if view == "general":
        st.subheader("📁 เข้าคลังภาพทั่วไป")
        _login_general()
    elif view == "user":
        st.subheader("📤 ส่งรูปเข้ากิจกรรม")
        _login_user()
    elif view == "viewer":
        st.subheader("🖼️ ดูอัลบั้มกิจกรรม")
        _login_viewer()
    elif view == "staff":
        st.subheader("🔐 เข้าสู่ระบบ (admin / ผู้ดูแล)")
        _login_staff()
