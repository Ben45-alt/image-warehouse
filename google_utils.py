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
