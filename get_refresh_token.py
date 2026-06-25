"""
สคริปต์นี้รัน "ครั้งเดียว" เพื่อขอ refresh token จาก Google
(refresh token = กุญแจถาวร ที่ทำให้แอป login Google ได้เองโดยไม่ต้องกรอกรหัสซ้ำ)

วิธีใช้ (ทำตามทีละขั้น):
1. โหลดไฟล์ credential จาก Google Cloud มาแล้วเปลี่ยนชื่อเป็น  client_secret.json
   วางไว้ในโฟลเดอร์เดียวกับไฟล์นี้
2. ติดตั้งไลบรารีก่อน (ครั้งเดียว):
       pip install -r requirements.txt
3. รันสคริปต์:
       python get_refresh_token.py
4. เบราว์เซอร์จะเด้งขึ้นมา → login ด้วย claude.mis.tfp@gmail.com → กด "อนุญาต/Allow"
   (ถ้ามีหน้าเตือน "Google hasn't verified this app" ให้กด Advanced → Go to ... (unsafe)
    ไม่อันตราย เพราะเป็นแอปของเราเอง)
5. กลับมาดูที่หน้าจอ terminal จะมีค่า 3 ตัว ให้ก๊อปไปใส่ใน .streamlit/secrets.toml
"""

from google_auth_oauthlib.flow import InstalledAppFlow

# สิทธิ์ที่ขอ: เข้าถึง Google Drive (อัปโหลดรูป) และ Google Sheets (เก็บข้อมูล)
# หมายเหตุ: SCOPES ตรงนี้ต้องตรงกับที่แอปใช้จริง
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]

# ชื่อไฟล์ credential ที่โหลดมาจาก Google Cloud (เปลี่ยนชื่อให้ตรงนี้)
CLIENT_SECRET_FILE = "client_secret.json"


def main():
    # สร้าง flow การ login จากไฟล์ client_secret.json
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRET_FILE,
        scopes=SCOPES,
    )

    # เปิดเบราว์เซอร์ให้ login
    # access_type="offline" + prompt="consent" = บังคับให้ Google ส่ง refresh token กลับมา
    creds = flow.run_local_server(
        port=0,
        access_type="offline",
        prompt="consent",
    )

    # แสดงค่าที่ต้องเก็บไว้
    print("\n===== คัดลอก 3 บรรทัดนี้ไปใส่ใน .streamlit/secrets.toml (ใต้ [google_oauth]) =====\n")
    print(f'client_id = "{creds.client_id}"')
    print(f'client_secret = "{creds.client_secret}"')
    print(f'refresh_token = "{creds.refresh_token}"')
    print("\n================================================================================\n")

    if not creds.refresh_token:
        print("⚠️ ไม่ได้ refresh token! ลองรันใหม่ และตอน login ให้กด 'อนุญาต' ทุกหน้า")


if __name__ == "__main__":
    main()
