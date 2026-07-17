# -*- coding: utf-8 -*-
"""
google_utils.py — รวมฟังก์ชันสำหรับเชื่อมต่อ Google (Drive + Sheets) ไว้ที่เดียว
หน้าอื่นๆ ของแอปจะ import ไฟล์นี้ไปใช้ จะได้ไม่เขียนซ้ำ

หลักการ:
- อ่านค่า client_id / client_secret / refresh_token จาก st.secrets (ไฟล์ .streamlit/secrets.toml)
- เอา refresh token มาสร้าง "ตั๋วเข้า Google" (Credentials) ที่ต่ออายุ access token ให้เองอัตโนมัติ
- ใช้ @st.cache_resource เพื่อให้สร้างการเชื่อมต่อแค่ครั้งเดียว (เร็วขึ้น ไม่ต่อใหม่ทุกครั้ง)
"""

import io
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
import gspread
import pandas as pd
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

from image_utils import hamming_distance   # เทียบลายนิ้วมือรูป (phash) หาซ้ำ

# ระยะ phash ที่ถือว่า "รูปเดียวกัน/เกือบเหมือน" (0-64 ยิ่งน้อยยิ่งเหมือน)
PHASH_DUP_THRESHOLD = 5

# สิทธิ์ที่ใช้ ต้องตรงกับตอนขอ refresh token (get_refresh_token.py)
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


def _retry(fn, *args, attempts: int = 4, **kwargs):
    """
    เรียกฟังก์ชันที่ต้องต่อเน็ต แล้วลองใหม่อัตโนมัติถ้าเน็ตสะดุดชั่วคราว
    (เช่น WinError 10053/10054 ที่ antivirus/firewall หรือเน็ตตัดการเชื่อมต่อกลางคัน)
    ลองสูงสุด `attempts` ครั้ง เว้นช่วงถี่ขึ้นเรื่อยๆ ถ้ายังไม่ได้ค่อยโยน error จริงออกไป
    """
    last_err = None
    for i in range(attempts):
        try:
            return fn(*args, **kwargs)
        except (ConnectionError, TimeoutError) as e:
            # ConnectionError ครอบคลุม ConnectionAbortedError/ResetError (WinError 10053/10054)
            last_err = e
            time.sleep(1.5 * (i + 1))  # 1.5s, 3s, 4.5s ...
    raise last_err


@st.cache_resource
def get_credentials():
    """สร้าง Credentials จาก refresh token ใน secrets (ใช้ซ้ำได้ทั้งแอป)"""
    g = st.secrets["google_oauth"]
    creds = Credentials(
        None,  # ไม่มี access token ตอนเริ่ม เดี๋ยวระบบขอให้เองจาก refresh token
        refresh_token=g["refresh_token"],
        client_id=g["client_id"],
        client_secret=g["client_secret"],
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return creds


@st.cache_resource
def get_worksheet():
    """เปิด Google Sheet (ชีตแรก) ที่ใช้เป็นฐานข้อมูล แล้วคืน worksheet object"""
    gc = gspread.authorize(get_credentials())
    spreadsheet = gc.open_by_url(st.secrets["SHEET_URL"])
    return spreadsheet.sheet1  # ใช้ชีตแรก (แท็บแรก)


@st.cache_resource
def get_drive_service():
    """สร้างตัวเชื่อม Google Drive (ไว้อัปโหลด/ตั้งสิทธิ์ไฟล์รูป)"""
    return build("drive", "v3", credentials=get_credentials())


def check_connection():
    """ทดสอบว่าเชื่อม Sheet ได้จริงไหม — คืน (ชื่อชีต, จำนวนแถว)"""
    ws = get_worksheet()
    return ws.spreadsheet.title, ws.row_count


def upload_to_drive(file_buffer, filename: str):
    """
    อัปโหลดไฟล์รูปขึ้นโฟลเดอร์ Google Drive แล้วตั้งสิทธิ์ให้ "ใครมีลิงก์ก็ดูได้"
    คืนค่า (file_id, ลิงก์ดูรูป)
    """
    service = get_drive_service()
    folder_id = st.secrets["DRIVE_FOLDER_ID"]

    # ข้อมูลไฟล์: ชื่อ + วางในโฟลเดอร์ที่กำหนด
    metadata = {"name": filename, "parents": [folder_id]}

    def _do_create():
        # seek กลับต้นไฟล์ทุกครั้ง เผื่อรอบ retry ก่อนหน้าอ่าน buffer ไปแล้ว (กันอัปไฟล์เปล่า)
        file_buffer.seek(0)
        media = MediaIoBaseUpload(file_buffer, mimetype="image/jpeg", resumable=False)
        return service.files().create(
            body=metadata, media_body=media, fields="id"
        ).execute(num_retries=5)

    # num_retries ให้ Google client ลองใหม่เองเมื่อเจอ error ชั่วคราว + _retry กันเน็ตหลุดอีกชั้น
    created = _retry(_do_create)
    file_id = created["id"]

    # ตั้งสิทธิ์: anyone with link → reader (เพื่อให้แอปแสดงรูปได้)
    _retry(
        lambda: service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
        ).execute(num_retries=5)
    )

    link = f"https://drive.google.com/file/d/{file_id}/view"
    return file_id, link


def append_row(row_values: list):
    """บันทึกข้อมูล 1 แถวต่อท้าย Google Sheet (ลองใหม่อัตโนมัติถ้าเน็ตสะดุด)"""
    ws = get_worksheet()
    _retry(lambda: ws.append_row(row_values, value_input_option="USER_ENTERED"))


def append_activity_row(datetime_str, sender, link, filename, activity_id, phash=""):
    """
    บันทึกรูปที่ส่งผ่าน "กิจกรรม" ลง Sheet เดิม (reuse append_row)
    ลำดับคอลัมน์: วันเวลา, แผนก, หมวด, ชื่อเรื่อง, แท็ก, ผู้ส่ง, ลิงก์รูป, ชื่อไฟล์, activity_id, phash
    → แผนก/หมวด/ชื่อเรื่อง/แท็ก ปล่อยว่าง (เป็นรูปของกิจกรรม ไม่ใช่คลังทั่วไป)
    """
    append_row([datetime_str, "", "", "", "", sender, link, filename, activity_id, phash])


def delete_photo(file_id: str, link: str):
    """
    ลบรูป 1 รายการ = ลบไฟล์ใน Drive + ลบแถวข้อมูลใน Sheet
    - หาแถวใน Sheet จากคอลัมน์ "ลิงก์รูป" (คอลัมน์ที่ 7) เพราะลิงก์ไม่ซ้ำกัน (ชื่อไฟล์อาจซ้ำได้ถ้าอัปวินาทีเดียวกัน)
    - ถ้าไฟล์ใน Drive ถูกลบไปแล้ว ก็ข้ามไปลบแถวต่อ ไม่ให้พังทั้งกระบวนการ
    """
    # 1) ลบไฟล์ใน Drive
    if file_id:
        try:
            service = get_drive_service()
            _retry(lambda: service.files().delete(fileId=file_id).execute(num_retries=5))
        except Exception:
            pass  # ไฟล์อาจไม่มีแล้ว ไม่เป็นไร ไปลบแถวใน Sheet ต่อ

    # 2) ลบแถวใน Sheet (คอลัมน์ 7 = ลิงก์รูป)
    ws = get_worksheet()
    try:
        cell = ws.find(link, in_column=7)
    except Exception:
        cell = None
    if cell:
        _retry(lambda: ws.delete_rows(cell.row))


# ---------------------------------------------------------------------------
# ถังขยะ (soft delete) — ลบ = ย้ายเข้าถังขยะ Drive (auto-purge 30 วัน) + ทำเครื่องหมายในชีต
# ---------------------------------------------------------------------------
def _now_str() -> str:
    """เวลาปัจจุบัน (ไทย) เป็นสตริง — ใช้จดวันที่ลบ/บันทึก log"""
    return datetime.now(ZoneInfo("Asia/Bangkok")).strftime("%Y-%m-%d %H:%M:%S")


def _update_row_fields(link: str, fields: dict) -> bool:
    """
    หาแถวในชีตจากคอลัมน์ 'ลิงก์รูป' (คอลัมน์ 7) แล้วอัปเดตค่าตามชื่อหัวตาราง
    fields = {ชื่อหัวคอลัมน์: ค่าใหม่} — ข้ามคอลัมน์ที่ยังไม่มีในหัวตาราง คืน True ถ้าเจอแถว
    """
    ws = get_worksheet()
    header = ws.row_values(1)
    try:
        cell = ws.find(link, in_column=7)
    except Exception:
        cell = None
    if not cell:
        return False
    row = cell.row
    for name, val in fields.items():
        if name in header:
            col = header.index(name) + 1
            _retry(lambda c=col, v=val: ws.update_cell(row, c, v))
    return True


def trash_photo(file_id: str, link: str, deleted_by: str = "") -> None:
    """
    ย้ายรูป 1 รายการเข้า "ถังขยะ" (กู้คืนได้ ~30 วัน):
      1) Drive: ตั้ง trashed=True → Google ล้างไฟล์ทิ้งเองอัตโนมัติเมื่อครบ 30 วัน
      2) Sheet: ทำเครื่องหมายแถว (สถานะ=ถังขยะ, วันที่ลบ, ลบโดย) — ไม่ลบแถวจริง
    รูปจะหายจากคลังทันที แต่ยังกู้คืนได้จากหน้าถังขยะ
    """
    if file_id:
        try:
            service = get_drive_service()
            _retry(lambda: service.files().update(
                fileId=file_id, body={"trashed": True}).execute(num_retries=5))
        except Exception:
            pass  # ไฟล์อาจไม่มีแล้ว — ไปทำเครื่องหมายในชีตต่อ
    _update_row_fields(link, {
        STATUS_HEADER: TRASH_STATUS,
        DELETED_AT_HEADER: _now_str(),
        DELETED_BY_HEADER: deleted_by,
    })
    load_data.clear()


def restore_photo(file_id: str, link: str) -> None:
    """
    กู้รูปจากถังขยะกลับมา:
      1) Drive: ตั้ง trashed=False (ต้องกู้ก่อนครบ 30 วัน ไม่งั้น Google ลบไฟล์จริงไปแล้ว)
      2) Sheet: ล้างสถานะ/วันที่ลบ/ลบโดย → รูปกลับมาโผล่ในคลังตามเดิม
    """
    if file_id:
        try:
            service = get_drive_service()
            _retry(lambda: service.files().update(
                fileId=file_id, body={"trashed": False}).execute(num_retries=5))
        except Exception:
            pass
    _update_row_fields(link, {STATUS_HEADER: "", DELETED_AT_HEADER: "", DELETED_BY_HEADER: ""})
    load_data.clear()


# ---------------------------------------------------------------------------
# Audit log — บันทึกการกระทำสำคัญ (อัป/ลบ/กู้คืน) ไว้สืบย้อน
# ---------------------------------------------------------------------------
@st.cache_data(ttl=30)
def load_log() -> pd.DataFrame:
    """อ่านบันทึกการใช้งานทั้งหมดจากแท็บ Log เป็น DataFrame (cache 30 วิ) — คืนว่างถ้ายังไม่มีแท็บ"""
    try:
        ws = get_spreadsheet().worksheet(LOG_TAB)
        return pd.DataFrame(ws.get_all_records())
    except Exception:
        return pd.DataFrame()


def log_action(who: str, role: str, action: str, detail: str = "", activity_id: str = "") -> None:
    """
    บันทึก 1 บรรทัดลงแท็บ Log: เวลา · ผู้ทำ · role · การกระทำ · รายละเอียด · activity_id
    ครอบ try/except ทั้งหมด — การจด log ต้องไม่ทำให้งานหลัก (อัป/ลบ) พังเด็ดขาด
    """
    try:
        ss = get_spreadsheet()
        try:
            ws = ss.worksheet(LOG_TAB)
        except gspread.WorksheetNotFound:
            ws = _ensure_tab(ss, LOG_TAB, LOG_HEADER)
        _retry(lambda: ws.append_row(
            [_now_str(), str(who), str(role), str(action), str(detail), str(activity_id)],
            value_input_option="USER_ENTERED",
        ))
        load_log.clear()  # ให้หน้า Log เห็นรายการใหม่ทันที
    except Exception:
        pass


# ---------------------------------------------------------------------------
# auto-close กิจกรรม — ปิดอัตโนมัติเมื่อครบ 7 วันนับจากวันสร้าง (ตรวจตอนใช้งาน ไม่แก้ชีต)
# ---------------------------------------------------------------------------
def is_activity_expired(created, now=None, days: int = None) -> bool:
    """หมดอายุ auto-close หรือยัง (ครบ `days` วันนับจากวันสร้าง). parse วันไม่ได้ = ยังไม่หมด (กันปิดมั่ว)"""
    # อ้าง AUTO_CLOSE_DAYS ตอนเรียก (ไม่ใช่ตอนนิยาม) — ค่าคงที่ถูกประกาศทีหลังในไฟล์
    if days is None:
        days = AUTO_CLOSE_DAYS
    dt = pd.to_datetime(str(created), errors="coerce")
    if pd.isna(dt):
        return False
    now = now or datetime.now(ZoneInfo("Asia/Bangkok"))
    return (now.date() - dt.date()).days >= days


def is_activity_open(row, now=None) -> bool:
    """เปิดอยู่จริงไหม = สถานะ 'เปิด' และยังไม่หมดอายุ auto-close (row = dict/Series ของกิจกรรม)"""
    if str(row.get("สถานะ")) != "เปิด":
        return False
    return not is_activity_expired(row.get("วันที่สร้าง"), now)


def open_activities(df: pd.DataFrame = None, now=None) -> pd.DataFrame:
    """DataFrame ของกิจกรรมที่ 'เปิดอยู่จริง' (สถานะเปิด + ยังไม่หมดอายุ) — ใช้ในหน้า login/dropdown"""
    if df is None:
        df = load_activities()
    if df.empty or "สถานะ" not in df.columns:
        return df.iloc[0:0] if not df.empty else df
    now = now or datetime.now(ZoneInfo("Asia/Bangkok"))
    mask = df.apply(lambda r: is_activity_open(r, now), axis=1)
    return df[mask].copy()


@st.cache_data(ttl=60)
def load_data() -> pd.DataFrame:
    """
    อ่านข้อมูลทั้งหมดจาก Google Sheet มาเป็นตาราง (DataFrame)
    ใช้ cache 60 วินาที เพื่อไม่ต้องอ่านชีตใหม่ทุกครั้ง (เร็วขึ้น)
    หลังอัปโหลดรูปใหม่ โค้ดจะสั่งล้าง cache ให้เอง
    """
    ws = get_worksheet()
    records = ws.get_all_records()  # แปลงแต่ละแถวเป็น dict โดยใช้หัวตารางเป็น key
    return pd.DataFrame(records)


def _not_trashed_mask(df: pd.DataFrame) -> pd.Series:
    """คืน mask ของแถวที่ 'ไม่ได้อยู่ในถังขยะ' — ถ้าชีตยังไม่มีคอลัมน์สถานะ ถือว่าปกติทั้งหมด"""
    if STATUS_HEADER not in df.columns:
        return pd.Series(True, index=df.index)
    return df[STATUS_HEADER].astype(str).str.strip() != TRASH_STATUS


def load_active_data() -> pd.DataFrame:
    """ข้อมูลรูปทั้งหมด 'ที่ยังไม่ถูกลบ' (ไม่รวมถังขยะ) — ใช้ในทุกหน้าคลังภาพ"""
    df = load_data()
    if df.empty:
        return df
    return df[_not_trashed_mask(df)].copy()


def load_trash_data() -> pd.DataFrame:
    """ข้อมูลรูป 'ในถังขยะ' เท่านั้น — ใช้ในหน้าถังขยะ (admin/superuser)"""
    df = load_data()
    if df.empty or STATUS_HEADER not in df.columns:
        return df.iloc[0:0] if not df.empty else df
    return df[df[STATUS_HEADER].astype(str).str.strip() == TRASH_STATUS].copy()


def load_general_data() -> pd.DataFrame:
    """
    ข้อมูลเฉพาะ "คลังภาพทั่วไป" (ระบบเดิม) = แถวที่ activity_id ว่าง/ไม่มีค่า และไม่อยู่ในถังขยะ
    ใช้ในหน้าเดิม (คลังภาพ + Dashboard) เพื่อกัน "รูปกิจกรรม" (ที่แผนก/หมวดว่าง) หลุดมาโผล่ปนกัน
    ถ้าชีตยังไม่มีคอลัมน์ activity_id (ข้อมูลเก่าล้วน) ก็คืนทั้งหมดตามเดิม
    """
    df = load_data()
    if df.empty or ACTIVITY_ID_HEADER not in df.columns:
        return df
    is_general = df[ACTIVITY_ID_HEADER].astype(str).str.strip() == ""
    return df[is_general & _not_trashed_mask(df)].copy()


def load_published_activity_data() -> pd.DataFrame:
    """
    รูป "ของกิจกรรม" ที่เจ้าของกดเผยแพร่เข้าคลังทั่วไปแล้ว (และไม่อยู่ในถังขยะ)
    = แถวที่ activity_id มีค่า + คอลัมน์ 'เผยแพร่' = 'ใช่'
    รูปยังอยู่ในอัลบั้มกิจกรรมตามเดิม — ตัวนี้แค่ให้หน้าคลังทั่วไปหยิบไปโชว์เพิ่มเป็นโฟลเดอร์
    """
    df = load_data()
    if df.empty or ACTIVITY_ID_HEADER not in df.columns or PUBLISHED_HEADER not in df.columns:
        return df.iloc[0:0] if not df.empty else pd.DataFrame()
    is_activity = df[ACTIVITY_ID_HEADER].astype(str).str.strip() != ""
    is_pub = df[PUBLISHED_HEADER].astype(str).str.strip() == PUBLISHED_YES
    return df[is_activity & is_pub & _not_trashed_mask(df)].copy()


def set_photo_published(link: str, published: bool) -> bool:
    """
    เปิด/ปิดการเผยแพร่รูป 1 ใบเข้าคลังทั่วไป — แก้แค่คอลัมน์ 'เผยแพร่' ในชีต
    ไม่แตะไฟล์ใน Drive / ชื่อไฟล์ / metadata และรูปยังอยู่ในอัลบั้มกิจกรรมเหมือนเดิม
    คืน True ถ้าเจอแถวและอัปเดตแล้ว
    """
    ok = _update_row_fields(link, {PUBLISHED_HEADER: PUBLISHED_YES if published else ""})
    load_data.clear()
    return ok


def download_file_bytes(file_id: str) -> bytes:
    """ดาวน์โหลดไฟล์รูปจาก Drive มาเป็น bytes (ใช้ตอนทำไฟล์ ZIP)"""
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue()


@st.cache_data(ttl=600, show_spinner=False, max_entries=300)
def get_image_bytes(file_id: str) -> bytes:
    """
    โหลดรูปจาก Drive มาเป็น bytes สำหรับแสดงพรีวิวในหน้าคลังภาพ
    ใช้วิธีนี้แทน URL thumbnail ของ Drive เพราะ:
    - รูปที่เพิ่งอัปใหม่ Google ยังไม่ทันสร้าง thumbnail → URL จะขึ้นว่าง
    - บางครั้ง Google บล็อกการ hotlink รูปจาก drive.google.com โดยตรง
    cache ไว้ 10 นาที เพื่อไม่ต้องโหลดซ้ำทุกครั้งที่เปลี่ยนหน้า
    """
    return download_file_bytes(file_id)


def extract_file_id(link: str) -> str:
    """ดึง file_id ออกจากลิงก์ Drive (รองรับทั้งแบบ /d/xxx/ และ ?id=xxx)"""
    if not link:
        return ""
    m = re.search(r"/d/([A-Za-z0-9_-]+)", str(link))
    if m:
        return m.group(1)
    m = re.search(r"id=([A-Za-z0-9_-]+)", str(link))
    return m.group(1) if m else ""


# ===========================================================================
# ตั้งชื่อไฟล์ (ตามกิจกรรม / ตามแผนก-หมวด) — ทำความสะอาดชื่อให้ปลอดภัย
# ===========================================================================
# อักขระต้องห้ามในชื่อไฟล์ (Windows/Drive) + อักขระควบคุม → ตัดทิ้ง
_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_name(s, max_len: int = 40) -> str:
    """
    แปลงข้อความ (ชื่อกิจกรรม/แผนก/หมวด) ให้เป็นส่วนหนึ่งของชื่อไฟล์ที่ปลอดภัย
    - ตัดอักขระต้องห้าม + ยุบช่องว่างเป็นขีดล่าง + ตัดจุด/ช่องว่างหน้า-หลัง
    - เก็บภาษาไทย/อังกฤษ/ตัวเลขไว้ได้ปกติ ; ถ้าว่างคืน 'ไม่ระบุ' ; ตัดความยาวกันชื่อยาวเกิน
    """
    s = _UNSAFE_FILENAME.sub("", str(s))
    s = re.sub(r"\s+", "_", s.strip())   # ช่องว่าง → ขีดล่าง (กันชื่อไฟล์มีเว้นวรรค)
    s = s.strip("._ ")
    if not s:
        s = "ไม่ระบุ"
    return s[:max_len]


def make_activity_filename(activity_name, seq: int, now) -> str:
    """ชื่อไฟล์รูปกิจกรรม: <ชื่อกิจกรรม>_<ลำดับ3หลัก>_<HHMMSS>.jpg"""
    return f"{sanitize_name(activity_name)}_{int(seq):03d}_{now.strftime('%H%M%S')}.jpg"


def make_general_filename(department, category, now) -> str:
    """ชื่อไฟล์รูปคลังทั่วไป: <แผนก>_<หมวด>_<HHMMSS>.jpg"""
    return f"{sanitize_name(department)}_{sanitize_name(category)}_{now.strftime('%H%M%S')}.jpg"


def count_activity_photos(activity_id) -> int:
    """นับจำนวนรูปที่อยู่ในกิจกรรมนี้ (ไว้คิด 'ลำดับ' ของรูปถัดไป) — อ่านจากคอลัมน์ activity_id"""
    df = load_data()
    if df.empty or ACTIVITY_ID_HEADER not in df.columns:
        return 0
    return int((df[ACTIVITY_ID_HEADER].astype(str).str.strip() == str(activity_id).strip()).sum())


# ===========================================================================
# ตรวจรูปซ้ำด้วย phash (เตือนตอนอัป + สแกนหาซ้ำ)
# ===========================================================================
def find_similar_photo(phash: str, scope_df: pd.DataFrame, threshold: int = PHASH_DUP_THRESHOLD):
    """
    หารูปใน scope_df ที่ phash ใกล้เคียง (<= threshold) มากที่สุด — คืน dict ของรูปนั้น (มี _dist) หรือ None
    scope_df = ขอบเขตที่จะเทียบ (เช่น รูปในกิจกรรมเดียวกัน)
    """
    if not phash or scope_df is None or scope_df.empty or PHASH_HEADER not in scope_df.columns:
        return None
    best, best_dist = None, threshold + 1
    for _, r in scope_df.iterrows():
        d = hamming_distance(phash, str(r.get(PHASH_HEADER, "")))
        if d <= threshold and d < best_dist:
            best, best_dist = r.to_dict(), d
    if best is not None:
        best["_dist"] = best_dist
    return best


def group_duplicates(df: pd.DataFrame, threshold: int = PHASH_DUP_THRESHOLD) -> list:
    """
    จัดกลุ่มรูปที่ phash ใกล้กัน (<= threshold) เป็นกลุ่มๆ ด้วย union-find
    คืน list ของกลุ่ม (แต่ละกลุ่ม = list ของ dict แถวรูป) เฉพาะกลุ่มที่มีตั้งแต่ 2 รูปขึ้นไป
    """
    if df is None or df.empty or PHASH_HEADER not in df.columns:
        return []
    rows = df.to_dict("records")
    hashes = [str(r.get(PHASH_HEADER, "")).strip() for r in rows]
    n = len(rows)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        if not hashes[i]:
            continue
        for j in range(i + 1, n):
            if hashes[j] and hamming_distance(hashes[i], hashes[j]) <= threshold:
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[ri] = rj

    groups = {}
    for i in range(n):
        if hashes[i]:
            groups.setdefault(find(i), []).append(rows[i])
    return [g for g in groups.values() if len(g) >= 2]


# ===========================================================================
# ระบบกิจกรรม (Activity) — โครงข้อมูลใหม่ ทำงานคู่กับของเดิม (ไม่แก้ของเดิม)
# ===========================================================================

ACTIVITY_ID_HEADER = "activity_id"                 # คอลัมน์ที่ 9 เพิ่มใน sheet1
PHASH_HEADER = "phash"                             # คอลัมน์ที่ 10 — ลายนิ้วมือรูป (ตรวจซ้ำ)
STATUS_HEADER = "สถานะ"                             # คอลัมน์ที่ 11 — ""(ปกติ) / "ถังขยะ"
DELETED_AT_HEADER = "วันที่ลบ"                       # คอลัมน์ที่ 12 — เวลาที่ย้ายเข้าถังขยะ
DELETED_BY_HEADER = "ลบโดย"                          # คอลัมน์ที่ 13 — ใครเป็นคนลบ
TRASH_STATUS = "ถังขยะ"                             # ค่าในคอลัมน์สถานะเมื่อรูปอยู่ในถังขยะ
PUBLISHED_HEADER = "เผยแพร่"                         # คอลัมน์ที่ 14 — ""(ไม่เผยแพร่) / "ใช่"
PUBLISHED_YES = "ใช่"                               # รูปกิจกรรมใบนี้ไปโผล่ในคลังทั่วไปด้วย
# คอลัมน์ที่เพิ่มต่อท้าย sheet1 (นอกเหนือจาก 8 คอลัมน์เดิม) — เรียงตามลำดับที่ ensure_schema เติม
_EXTRA_SHEET1_COLS = [
    ACTIVITY_ID_HEADER, PHASH_HEADER, STATUS_HEADER, DELETED_AT_HEADER, DELETED_BY_HEADER,
    PUBLISHED_HEADER,
]

LOG_TAB = "Log"                                    # แท็บบันทึกการกระทำ (audit log)
LOG_HEADER = ["เวลา", "ผู้ทำ", "role", "การกระทำ", "รายละเอียด", "activity_id"]
AUTO_CLOSE_DAYS = 7                                # กิจกรรมปิดอัตโนมัติเมื่อครบ 7 วันนับจากวันสร้าง

# การแชร์อัลบั้ม (Round 3): เจ้าของคุมว่าใครดูอัลบั้มได้
VISIBILITY_HEADER = "การมองเห็น"                     # คอลัมน์เพิ่มในแท็บ Activities
VIS_PUBLIC = "ทุกคน"                                # อัลบั้มสาธารณะ — ใครก็ดูได้
VIS_PRIVATE = "เฉพาะคน"                             # อัลบั้มเฉพาะคนที่แชร์ (ค่าเริ่มต้น)
SHARES_TAB = "Shares"                              # แท็บเก็บรายชื่อคนที่แชร์ให้ดู + รหัสดูส่วนตัว
SHARES_HEADER = ["activity_id", "ชื่อผู้ดู", "รหัสดู_hash", "วันที่เพิ่ม", "สถานะ"]

ACTIVITIES_TAB = "Activities"                      # แท็บเก็บรายการกิจกรรม
USERS_TAB = "Users"                                # แท็บเก็บบัญชี admin
ACTIVITIES_HEADER = [
    "activity_id", "ชื่อกิจกรรม", "รหัสเข้า_hash", "คนสร้าง", "วันที่สร้าง", "สถานะ",
    VISIBILITY_HEADER,
]
USERS_HEADER = ["username", "password_hash", "ชื่อ-นามสกุล", "role", "สถานะ"]


@st.cache_resource
def get_spreadsheet():
    """เปิด Google Spreadsheet (ทั้งไฟล์) — ใช้สำหรับเข้าถึงแท็บอื่นๆ"""
    gc = gspread.authorize(get_credentials())
    return gc.open_by_url(st.secrets["SHEET_URL"])


def _ensure_tab(ss, title: str, header: list):
    """สร้างแท็บถ้ายังไม่มี + ใส่หัวตารางถ้ายังว่าง (idempotent เรียกซ้ำได้ปลอดภัย)"""
    try:
        ws = ss.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = ss.add_worksheet(title=title, rows=200, cols=max(10, len(header)))
    if not ws.row_values(1):  # ยังไม่มีหัวตาราง → ใส่ให้
        ws.append_row(header, value_input_option="USER_ENTERED")
    return ws


def ensure_schema():
    """
    เตรียมโครงข้อมูลให้พร้อมสำหรับระบบกิจกรรม (เรียกครั้งเดียว/ซ้ำได้ ไม่ทำของเดิมพัง):
    1) เพิ่มคอลัมน์ activity_id ต่อท้าย sheet1 (ถ้ายังไม่มี)
    2) สร้างแท็บ Activities (ถ้ายังไม่มี)
    3) สร้างแท็บ Users (ถ้ายังไม่มี)
    """
    ss = get_spreadsheet()
    ws = ss.sheet1
    header = ws.row_values(1)
    # เติมคอลัมน์ที่เพิ่มทีหลังต่อท้ายทีละอัน (idempotent — มีแล้วข้าม) โดยคงลำดับที่กำหนด
    for col in _EXTRA_SHEET1_COLS:
        if col not in header:
            ws.update_cell(1, len(header) + 1, col)
            header.append(col)
    # แท็บ Activities: สร้างถ้ายังไม่มี + เพิ่มคอลัมน์ "การมองเห็น" ให้ชีตเก่าที่ยังไม่มี
    aws = _ensure_tab(ss, ACTIVITIES_TAB, ACTIVITIES_HEADER)
    ahead = aws.row_values(1)
    if VISIBILITY_HEADER not in ahead:
        aws.update_cell(1, len(ahead) + 1, VISIBILITY_HEADER)
    _ensure_tab(ss, USERS_TAB, USERS_HEADER)
    _ensure_tab(ss, LOG_TAB, LOG_HEADER)
    _ensure_tab(ss, SHARES_TAB, SHARES_HEADER)


@st.cache_resource
def get_activities_ws():
    """worksheet ของแท็บ Activities (ต้องเรียก ensure_schema มาก่อนแล้ว)"""
    return get_spreadsheet().worksheet(ACTIVITIES_TAB)


@st.cache_resource
def get_users_ws():
    """worksheet ของแท็บ Users"""
    return get_spreadsheet().worksheet(USERS_TAB)


def _find_row(ws, value, col: int):
    """หาเลขแถวในแท็บ จากค่าในคอลัมน์ที่กำหนด — คืน None ถ้าไม่เจอ"""
    try:
        cell = ws.find(str(value), in_column=col)
    except Exception:
        cell = None
    return cell.row if cell else None


# ---------- Activities ----------
@st.cache_data(ttl=60)
def load_activities() -> pd.DataFrame:
    """อ่านรายการกิจกรรมทั้งหมดเป็น DataFrame (cache 60 วิ)"""
    return pd.DataFrame(get_activities_ws().get_all_records())


def add_activity(activity_id, name, code_hash, creator, created_date, status="เปิด",
                 visibility=VIS_PRIVATE):
    """เพิ่มกิจกรรมใหม่ 1 รายการ (รหัสเข้าเก็บเป็น hash แล้ว) — ค่าเริ่มต้นอัลบั้ม = เฉพาะคน (private)"""
    ws = get_activities_ws()
    _retry(lambda: ws.append_row(
        [activity_id, name, code_hash, creator, created_date, status, visibility],
        value_input_option="USER_ENTERED",
    ))
    load_activities.clear()  # ล้าง cache เพื่อให้รายการใหม่ขึ้นทันที


def set_activity_status(activity_id, status):
    """เปลี่ยนสถานะกิจกรรม (เปิด/ปิด) — หาแถวจาก activity_id (คอลัมน์ 1) แก้คอลัมน์ 6"""
    ws = get_activities_ws()
    row = _find_row(ws, activity_id, 1)
    if row:
        _retry(lambda: ws.update_cell(row, 6, status))
        load_activities.clear()


def delete_activity(activity_id):
    """
    ลบกิจกรรม "ถาวร" (สำหรับ superuser เท่านั้น — ปุ่มอยู่เฉพาะหน้า superuser):
      1) ลบรูปทุกใบของกิจกรรมนี้ — ไฟล์ใน Drive + แถวใน Sheet1 (ผ่าน delete_photo)
      2) ลบแถวกิจกรรมในแท็บ Activities (คอลัมน์ 1 = activity_id)
    คืน "จำนวนรูปที่ลบ" ไว้แจ้งผล. หารูปจากคอลัมน์ activity_id ใน Sheet1
    """
    activity_id = str(activity_id).strip()
    df = load_data()
    deleted = 0
    if not df.empty and ACTIVITY_ID_HEADER in df.columns and "ลิงก์รูป" in df.columns:
        mine = df[df[ACTIVITY_ID_HEADER].astype(str).str.strip() == activity_id]
        for link in mine["ลิงก์รูป"].tolist():
            # delete_photo หาแถวจาก "ลิงก์" ใหม่ทุกครั้ง → เลขแถวเลื่อนหลังลบก็ไม่พลาด
            delete_photo(extract_file_id(link), link)
            deleted += 1

    # ลบแถวกิจกรรมในแท็บ Activities
    aws = get_activities_ws()
    row = _find_row(aws, activity_id, 1)
    if row and row > 1:  # กันเผลอลบแถวหัวตาราง (แถว 1)
        _retry(lambda: aws.delete_rows(row))

    load_data.clear()
    load_activities.clear()
    return deleted


# ---------- การแชร์อัลบั้ม (visibility + Shares) ----------
def get_activity_visibility(activity_id) -> str:
    """อัลบั้มกิจกรรมนี้แชร์แบบไหน — คืน VIS_PUBLIC/VIS_PRIVATE (ค่าว่าง/ไม่มี = เฉพาะคน)"""
    df = load_activities()
    if df.empty or VISIBILITY_HEADER not in df.columns:
        return VIS_PRIVATE
    m = df[df["activity_id"].astype(str) == str(activity_id)]
    if m.empty:
        return VIS_PRIVATE
    v = str(m.iloc[0].get(VISIBILITY_HEADER, "")).strip()
    return v if v in (VIS_PUBLIC, VIS_PRIVATE) else VIS_PRIVATE


def set_activity_visibility(activity_id, visibility) -> None:
    """ตั้งค่าการมองเห็นอัลบั้ม (ทุกคน/เฉพาะคน) — หาแถวจาก activity_id แก้คอลัมน์ การมองเห็น"""
    ws = get_activities_ws()
    header = ws.row_values(1)
    row = _find_row(ws, activity_id, 1)
    if row and VISIBILITY_HEADER in header:
        col = header.index(VISIBILITY_HEADER) + 1
        _retry(lambda: ws.update_cell(row, col, visibility))
        load_activities.clear()


def public_activities() -> pd.DataFrame:
    """กิจกรรมที่ตั้งเป็น 'ทุกคน' (อัลบั้มสาธารณะ) — ทุกสถานะ (เปิด/ปิดก็ดูได้)"""
    df = load_activities()
    if df.empty or VISIBILITY_HEADER not in df.columns:
        return df.iloc[0:0] if not df.empty else pd.DataFrame()
    return df[df[VISIBILITY_HEADER].astype(str).str.strip() == VIS_PUBLIC].copy()


@st.cache_resource
def get_shares_ws():
    """worksheet ของแท็บ Shares (รายชื่อคนที่แชร์อัลบั้มให้ดู)"""
    return get_spreadsheet().worksheet(SHARES_TAB)


@st.cache_data(ttl=60)
def load_shares() -> pd.DataFrame:
    """อ่านรายการแชร์ทั้งหมดเป็น DataFrame (cache 60 วิ)"""
    return pd.DataFrame(get_shares_ws().get_all_records())


def add_share(activity_id, viewer_name, code_hash, when) -> None:
    """เพิ่มคนที่ให้ดูอัลบั้ม 1 คน (รหัสดูเก็บเป็น hash)"""
    ws = get_shares_ws()
    _retry(lambda: ws.append_row(
        [activity_id, viewer_name, code_hash, when, "ใช้งาน"],
        value_input_option="USER_ENTERED",
    ))
    load_shares.clear()


def activity_shares(activity_id) -> pd.DataFrame:
    """รายชื่อคนที่แชร์อัลบั้มของกิจกรรมนี้ (เฉพาะที่ยังใช้งาน)"""
    df = load_shares()
    if df.empty or "activity_id" not in df.columns:
        return df.iloc[0:0] if not df.empty else pd.DataFrame()
    sub = df[df["activity_id"].astype(str) == str(activity_id)]
    if "สถานะ" in sub.columns:
        sub = sub[sub["สถานะ"].astype(str) != "ปิด"]
    return sub.copy()


def delete_share(activity_id, viewer_name) -> bool:
    """ถอนสิทธิ์คนดู 1 คน — ลบแถวใน Shares ที่ activity_id + ชื่อผู้ดู ตรงกัน (แถวแรกที่เจอ)"""
    ws = get_shares_ws()
    values = ws.get_all_values()  # รวมหัวตาราง (แถว 1)
    for i, r in enumerate(values[1:], start=2):
        if len(r) >= 2 and r[0] == str(activity_id) and r[1] == str(viewer_name):
            _retry(lambda rr=i: ws.delete_rows(rr))
            load_shares.clear()
            return True
    return False


# ---------- Users (บัญชี admin) ----------
@st.cache_data(ttl=60)
def load_users() -> pd.DataFrame:
    """อ่านบัญชี admin ทั้งหมดเป็น DataFrame (cache 60 วิ)"""
    return pd.DataFrame(get_users_ws().get_all_records())


def add_user(username, password_hash, fullname, role="admin", status="ใช้งาน"):
    """เพิ่มบัญชี admin (รหัสเก็บเป็น hash แล้ว)"""
    ws = get_users_ws()
    _retry(lambda: ws.append_row(
        [username, password_hash, fullname, role, status],
        value_input_option="USER_ENTERED",
    ))
    load_users.clear()  # ล้าง cache เพื่อให้บัญชีใหม่ขึ้นทันที


def set_user_status(username, status):
    """เปลี่ยนสถานะบัญชี (ใช้งาน/ปิด) — หาแถวจาก username (คอลัมน์ 1) แก้คอลัมน์ 5"""
    ws = get_users_ws()
    row = _find_row(ws, username, 1)
    if row:
        _retry(lambda: ws.update_cell(row, 5, status))
        load_users.clear()


def delete_user(username):
    """ลบบัญชี admin ออกจากแท็บ Users ถาวร — หาแถวจาก username (คอลัมน์ 1) แล้วลบทั้งแถว"""
    ws = get_users_ws()
    row = _find_row(ws, username, 1)
    if row and row > 1:  # กันเผลอลบแถวหัวตาราง (แถว 1)
        _retry(lambda: ws.delete_rows(row))
        load_users.clear()


def find_user(username):
    """หาบัญชี admin จาก username — คืน dict ของแถวนั้น หรือ None ถ้าไม่เจอ"""
    df = load_users()
    if df.empty:
        return None
    m = df[df["username"].astype(str) == str(username)]
    return m.iloc[0].to_dict() if not m.empty else None


# ---------- โควตา Google Drive (ใช้ในหน้า Dashboard superuser) ----------
def get_storage_quota() -> dict:
    """
    ดึงพื้นที่ Google Drive จริงจาก API (about.get → storageQuota)
    คืน dict: used / limit / free (หน่วยเป็น bytes) — limit/free เป็น None ถ้าบัญชีไม่จำกัดพื้นที่
    """
    service = get_drive_service()
    about = _retry(lambda: service.about().get(fields="storageQuota").execute())
    q = about.get("storageQuota", {})
    used = int(q.get("usage", 0))
    limit = int(q["limit"]) if q.get("limit") else None
    free = (limit - used) if limit is not None else None
    return {"used": used, "limit": limit, "free": free}
