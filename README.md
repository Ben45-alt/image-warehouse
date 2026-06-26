# 📷 คลังภาพกลางของบริษัท (Image Warehouse)

เว็บแอปภายในองค์กรสำหรับเก็บรูปภาพของทุกแผนกไว้ที่เดียว — อัปโหลด / ค้นหา / ดาวน์โหลด
สร้างด้วย **Python + Streamlit**, เก็บไฟล์บน **Google Drive**, เก็บข้อมูลบน **Google Sheets**

---

## ✨ ฟีเจอร์

แอปนี้มี **2 ระบบทำงานคู่กัน** เลือกจากหน้าแรก (landing):

### 📁 คลังภาพทั่วไป (ระบบเดิม)
- 📤 **ส่งรูป**: เลือกแผนก/หมวด, ใส่ชื่อเรื่อง/แท็ก/ผู้ส่ง, แนบไฟล์หรือถ่ายจากกล้องมือถือ — ย่อรูปอัตโนมัติด้วย Pillow
- 🖼️ **คลังภาพ**: ค้นหาด้วย แผนก / หมวด / ช่วงวันที่ / คำค้น, แสดงเป็น grid, ดาวน์โหลดเดี่ยว/ทั้งหมดเป็น .zip, แบ่งหน้า, ลบรูป
- 📊 **Dashboard**: สรุปตัวเลข + กราฟแยกตามแผนก/หมวด/เดือน + รายการล่าสุด
- เข้าด้วยรหัสผ่านเดียว (`APP_PASSWORD`)

### 🎯 ระบบกิจกรรม (Activity) + สิทธิ์ 3 ระดับ
- **user** (ลูกน้อง): เลือกกิจกรรมที่เปิดอยู่ + กรอกรหัส → ถ่ายรูปส่งเข้ากิจกรรม + ดูรูปเฉพาะกิจกรรมตัวเอง
- **admin** (หัวหน้า): สร้าง/เปิด-ปิดกิจกรรมของตัวเอง (ตั้ง/สุ่มรหัสแจกลูกน้อง), เห็นคลังภาพ+ภาพรวมเฉพาะกิจกรรมที่ตัวเองสร้าง
- **superuser** (ผู้ดูแล): เห็น/จัดการทุกอย่าง — Dashboard (พื้นที่ Drive, ภาพรวม, แจ้งเตือน), สร้างกิจกรรม, คลังภาพทุกกิจกรรม, จัดการบัญชี admin, เข้าคลังทั่วไปได้
- 🔒 รหัสกิจกรรม/รหัส admin เก็บใน Sheet เป็น **hash (sha256 + salt)** ไม่เก็บรหัสจริง

---

## 📁 ไฟล์ในโปรเจกต์
| ไฟล์ | หน้าที่ |
|------|---------|
| `app.py` | ไฟล์หลัก (router: landing → route ตามสิทธิ์) |
| `auth.py` | หน้าแรก + ฟอร์ม login 4 แบบ + hash/verify รหัส (ระบบกิจกรรม) |
| `google_utils.py` | เชื่อม Google Drive/Sheets + อ่าน/เขียนข้อมูล (รวมแท็บ Activities/Users + โควตา Drive) |
| `image_utils.py` | ย่อ/บีบอัดรูป |
| `config.py` | รายชื่อแผนก/หมวด (แก้เพิ่มได้) |
| `page_upload.py` / `page_gallery.py` / `page_dashboard.py` | หน้าคลังภาพทั่วไป (ระบบเดิม) |
| `page_activity_user.py` / `page_activity_admin.py` / `page_activity_superuser.py` | หน้าระบบกิจกรรมตามสิทธิ์ |
| `get_refresh_token.py` | สคริปต์ขอ refresh token (รันครั้งเดียว) |
| `start.bat` | ดับเบิลคลิกเพื่อเปิดแอป |

---

## 🚀 วิธีติดตั้งและรัน (เครื่องตัวเอง)

### 1. ติดตั้งไลบรารี (ทำครั้งเดียว)
```powershell
pip install -r requirements.txt
```

### 2. ตั้งค่า Google OAuth (ทำครั้งเดียว)
> ถ้าตั้งค่าไว้แล้ว (มีไฟล์ `.streamlit/secrets.toml` ครบ) ข้ามขั้นนี้ได้เลย

1. สร้าง **OAuth consent screen** (External) ใน Google Cloud Console และเพิ่มอีเมลตัวเองเป็น **Test user**
2. สร้าง **OAuth Client ID** แบบ **Desktop app** → ดาวน์โหลดไฟล์ → เปลี่ยนชื่อเป็น `client_secret.json` วางไว้ในโฟลเดอร์นี้
3. รันสคริปต์ขอ token:
   ```powershell
   python get_refresh_token.py
   ```
   เบราว์เซอร์จะเด้งให้ login → กดอนุญาต → จะได้ค่า 3 ตัวมาแสดงในหน้าจอ
4. ก๊อปไฟล์ `secrets.toml.example` ไปเป็น `.streamlit/secrets.toml` แล้วเติมค่าที่ได้ลงไป

### 3. เปิดแอป
```powershell
streamlit run app.py
```
หรือ **ดับเบิลคลิก `start.bat`** ก็ได้ → เบราว์เซอร์จะเปิดหน้าแรกให้เลือกทางเข้า (คลังทั่วไป / เข้าร่วมกิจกรรม / เข้าสู่ระบบ)

---

## ☁️ วิธี Deploy ฟรีบน Streamlit Community Cloud

1. **อัป code ขึ้น GitHub**
   - สร้าง repo ใหม่บน GitHub แล้ว push โค้ดขึ้นไป
   - ⚠️ **ห้าม commit** ไฟล์ลับ! (`.gitignore` กันให้แล้ว) ตรวจให้แน่ใจว่า `.streamlit/secrets.toml` และ `client_secret.json` **ไม่ขึ้น** GitHub
2. เข้า **https://share.streamlit.io** → login ด้วย GitHub → **New app**
3. เลือก repo, branch, และไฟล์หลัก `app.py` → **Deploy**
4. ใส่ค่า Secrets: ไปที่ **App → Settings → Secrets** แล้ว**ก๊อปเนื้อหาทั้งหมดในไฟล์ `.streamlit/secrets.toml`** วางลงไป — ต้องครบทุกค่า:
   - `APP_PASSWORD`, `SHEET_URL`, `DRIVE_FOLDER_ID`
   - **`HASH_SALT`, `SUPERUSER_USER`, `SUPERUSER_PASS`** (ของระบบกิจกรรม — ถ้าขาด admin/superuser จะ login ไม่ได้)
   - กลุ่ม `[google_oauth]` (client_id / client_secret / refresh_token)
5. กด Save → แอปจะรันใหม่และพร้อมใช้งานผ่านลิงก์ public

> 💡 เปลี่ยน `APP_PASSWORD` และ `SUPERUSER_PASS` ใน Secrets เป็นรหัสที่เดายากก่อนเปิดให้คนอื่นใช้
> ⚠️ `HASH_SALT` ตั้งครั้งเดียวแล้ว **ห้ามเปลี่ยน** ไม่งั้นรหัสกิจกรรม/admin ที่ hash ไว้เดิมจะใช้ไม่ได้

---

## ⚠️ ไฟล์ที่ห้าม commit ขึ้น GitHub
- `.streamlit/secrets.toml` (ค่าลับทั้งหมด)
- `client_secret.json` (credential จาก Google)

มี `.gitignore` กันไว้ให้แล้ว แต่ควรเช็คทุกครั้งก่อน push
