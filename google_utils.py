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

import streamlit as st
import gspread
import pandas as pd
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

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


def append_activity_row(datetime_str, sender, link, filename, activity_id):
    """
    บันทึกรูปที่ส่งผ่าน "กิจกรรม" ลง Sheet เดิม (reuse append_row)
    ลำดับคอลัมน์: วันเวลา, แผนก, หมวด, ชื่อเรื่อง, แท็ก, ผู้ส่ง, ลิงก์รูป, ชื่อไฟล์, activity_id
    → แผนก/หมวด/ชื่อเรื่อง/แท็ก ปล่อยว่าง (เป็นรูปของกิจกรรม ไม่ใช่คลังทั่วไป)
    """
    append_row([datetime_str, "", "", "", "", sender, link, filename, activity_id])


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


def load_general_data() -> pd.DataFrame:
    """
    ข้อมูลเฉพาะ "คลังภาพทั่วไป" (ระบบเดิม) = แถวที่ activity_id ว่าง/ไม่มีค่า
    ใช้ในหน้าเดิม (คลังภาพ + Dashboard) เพื่อกัน "รูปกิจกรรม" (ที่แผนก/หมวดว่าง) หลุดมาโผล่ปนกัน
    ถ้าชีตยังไม่มีคอลัมน์ activity_id (ข้อมูลเก่าล้วน) ก็คืนทั้งหมดตามเดิม
    """
    df = load_data()
    if df.empty or ACTIVITY_ID_HEADER not in df.columns:
        return df
    is_general = df[ACTIVITY_ID_HEADER].astype(str).str.strip() == ""
    return df[is_general].copy()


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
# ระบบกิจกรรม (Activity) — โครงข้อมูลใหม่ ทำงานคู่กับของเดิม (ไม่แก้ของเดิม)
# ===========================================================================

ACTIVITY_ID_HEADER = "activity_id"                 # คอลัมน์ที่ 9 เพิ่มใน sheet1
ACTIVITIES_TAB = "Activities"                      # แท็บเก็บรายการกิจกรรม
USERS_TAB = "Users"                                # แท็บเก็บบัญชี admin
ACTIVITIES_HEADER = [
    "activity_id", "ชื่อกิจกรรม", "รหัสเข้า_hash", "คนสร้าง", "วันที่สร้าง", "สถานะ",
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
    if ACTIVITY_ID_HEADER not in header:
        ws.update_cell(1, len(header) + 1, ACTIVITY_ID_HEADER)  # ต่อท้ายคอลัมน์สุดท้าย
    _ensure_tab(ss, ACTIVITIES_TAB, ACTIVITIES_HEADER)
    _ensure_tab(ss, USERS_TAB, USERS_HEADER)


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


def add_activity(activity_id, name, code_hash, creator, created_date, status="เปิด"):
    """เพิ่มกิจกรรมใหม่ 1 รายการ (รหัสเข้าเก็บเป็น hash แล้ว)"""
    ws = get_activities_ws()
    _retry(lambda: ws.append_row(
        [activity_id, name, code_hash, creator, created_date, status],
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
