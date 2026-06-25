# 📋 สถานะโปรเจกต์ "คลังภาพกลางของบริษัท"

> ไฟล์นี้ไว้จดว่าทำถึงไหนแล้ว + ติดปัญหาตรงไหน (อัปเดตล่าสุด: 2026-06-25)

---

## ✅ ทำเสร็จแล้ว

| เฟส | งาน | สถานะ |
|-----|-----|-------|
| C | OAuth + refresh token + verify เข้าถึง Sheet/Drive | ✅ |
| 1 | ติดตั้งไลบรารี (แก้ starlette ให้เข้ากับ Python 3.14) | ✅ |
| 2 | ระบบ login + ตัวเชื่อม Google + แก้หัวตาราง Sheet เป็น 8 คอลัมน์ | ✅ |
| 3 | หน้าส่งรูป (ย่อรูป → อัป Drive → บันทึก Sheet) — *ทดสอบ pipeline จริงผ่าน* | ✅ |
| 4 | หน้าคลังภาพ (filter + grid + ดาวน์โหลดเดี่ยว/zip + แบ่งหน้า) | ✅ |
| 5 | Dashboard + start.bat + README.md — *ทดสอบ AppTest ทั้ง 3 หน้าผ่าน* | ✅ |

โค้ดครบทุกไฟล์ compile ผ่านหมด

---

## ✅ Blocker ปลดล็อกแล้ว (2026-06-25)

**OAuth client เดิมกลับมาใช้ได้แล้ว** — Google เปิด client คืนหลังพ้นช่วง anti-abuse
- ทดสอบยิง refresh token **1 ครั้ง** → `REFRESH_OK` (ได้ access token)
- อ่าน Sheet `Image_Warehouse_DB` ได้ (998 rows)
- รัน AppTest: login ผ่าน, 3 แท็บเรนเดอร์, 0 error, sidebar ขึ้น "เชื่อม Google Sheet สำเร็จ"
- **ไม่ต้องสร้าง client ใหม่ / ไม่ต้องขอ refresh token ใหม่** — ค่าใน `.streamlit/secrets.toml` ใช้ได้เลย

---

## ▶️ เหลือทำต่อ

1. ✅ **เปลี่ยนรหัสผ่านแล้ว** (2026-06-25): `APP_PASSWORD` เปลี่ยนจาก `1234` เป็นรหัสใหม่ใน `.streamlit/secrets.toml` — ยืนยันด้วย AppTest ว่า login รหัสใหม่ผ่าน / รหัสเก่าใช้ไม่ได้แล้ว
2. ✅ **Deploy เสร็จสมบูรณ์ (2026-06-25)** 🎉
   - Live: **https://image-warehouse-mis.streamlit.app/**
   - โค้ด: https://github.com/Ben45-alt/image-warehouse (public, ไม่มีไฟล์ลับ)
   - Secrets วางใน Streamlit Cloud แล้ว
   - OAuth consent screen = **Production** → refresh token ไม่หมดอายุ 7 วัน

> หมายเหตุ: ตอนนี้พร้อมใช้งานเต็มรูปแบบบนเครื่องแล้ว — ดับเบิลคลิก `start.bat` → login ด้วยรหัสใหม่ → ใช้ได้ครบ 3 หน้า

---

## 🐛 บั๊กที่แก้แล้ว

**(2026-06-25) รูปค้างหลังบันทึก → เสี่ยงบันทึกซ้ำ** (`page_upload.py`)
- อาการ: ช่องอัปรูปอยู่ "นอก" `st.form` แต่ `clear_on_submit` ล้างได้แค่ช่องในฟอร์ม → หลังกดบันทึก รูปเดิมยังค้าง พอเปลี่ยนแผนก/หมวด/หัวข้อแล้วกดบันทึกอีกครั้ง รูปเดิมถูกอัปซ้ำเป็นรายการใหม่ (reproduce ยืนยันแล้ว)
- แก้: ย้ายช่องอัปรูป (`file_uploader`/`camera_input`) เข้าไป "ใน" `st.form` (radio เลือกวิธียังอยู่นอกฟอร์มเพื่อสลับได้ทันที) → frontend ล้างรูปให้พร้อมช่องอื่นตอน submit
- เช็คเพิ่ม: ลำดับหัวตาราง Sheet ตรงกับลำดับที่โค้ดเขียน + ค่าที่เลือก (แผนก/หมวด) บันทึกถูกช่อง — ไม่มีบั๊กแมปคอลัมน์

**(2026-06-25) config.py ตกคอมม่า → แผนกรวมกัน** (`config.py`)
- string หลายตัววางติดกันไม่มีคอมม่า → Python ต่อเป็นก้อนเดียว (เช่น HR+HRSL, และก้อนยาว MTN→CARRICHS)
- แก้: เติมคอมม่าครบทุกบรรทัด (24 ฝ่ายแยกกัน) + คอมเมนต์เตือน
- เคลียร์ข้อมูลทดสอบเก่า 3 แถวใน Sheet + ลบรูปใน Drive (เคยใช้ชื่อแผนกเก่าที่ไม่มีใน config ใหม่ ทำให้ Dashboard/ฟิลเตอร์เพี้ยน)

**(2026-06-25) กด Enter ที่หน้า login ไม่ submit** (`app.py`)
- เดิมใช้ `text_input` + `button` แยกกัน → Enter ไม่กดปุ่ม
- แก้: ครอบด้วย `st.form` (ช่องเดียว) → Enter = submit ทันที

**(2026-06-25) พรีวิวรูปหน้าคลังภาพไม่ขึ้น** (`page_gallery.py`, `google_utils.py`)
- เดิมใช้ URL `drive.google.com/thumbnail?id=...` → รูปเพิ่งอัป Google ยังไม่สร้าง thumbnail / โดนบล็อก hotlink
- แก้: เพิ่ม `get_image_bytes()` (cache 10 นาที) โหลด bytes รูปจริงมาแสดงด้วย `st.image` — ยืนยัน round-trip ผ่าน

**(2026-06-25) บันทึกรูปล้มเหลว WinError 10053 (เน็ต/AV ตัดการเชื่อมต่อ)** (`google_utils.py`)
- อาการ: อัปรูปแล้วขึ้น `[WinError 10053] An established connection was aborted...` ระหว่างต่อ Google
- แก้: เพิ่ม `_retry()` ลองใหม่อัตโนมัติเมื่อเจอ ConnectionError/TimeoutError (1.5s,3s,4.5s) + ใส่ `num_retries=5` ใน Drive API
- ครอบ `upload_to_drive` (create + permission, seek buffer ก่อน retry กันอัปไฟล์เปล่า) และ `append_row`
- ยืนยัน: retry กู้คืนได้จริง / error ที่ไม่ใช่เน็ตไม่ถูก retry / อัปโหลดจริงยังทำงานปกติ

---

## ➕ ฟีเจอร์ที่เพิ่มหลัง deploy

**(2026-06-25) ปุ่มลบรูป ในหน้าคลังภาพ** (`page_gallery.py`, `google_utils.py`)
- แต่ละรูปมีปุ่ม **🗑️ ลบรูปนี้** → กดแล้วถามยืนยัน (✅ ลบเลย / ❌ ยกเลิก) กันกดพลาด
- ลบ = ลบไฟล์ใน Drive + ลบแถวใน Sheet (หาแถวจากคอลัมน์ "ลิงก์รูป" ที่ไม่ซ้ำกัน) ผ่าน `delete_photo()`
- ยืนยันแล้ว: round-trip ลบจริงครบ (Drive หาย + แถวหาย + ไม่มีตกค้าง) + กริดเรนเดอร์ปกติ

---

## ℹ️ ข้อควรรู้เรื่อง Hosting (Streamlit Community Cloud) — อ่านเมื่อสงสัย

**ฟรีไหม / ต้องต่ออายุไหม?**
- ✅ **ฟรีถาวร** สำหรับ public app — ไม่ต้องใส่บัตร ไม่มีค่ารายเดือน ไม่มีวันหมดอายุ ไม่ต้องต่ออายุ
- เงื่อนไข: repo บน GitHub ต้องยังอยู่และเป็น public (https://github.com/Ben45-alt/image-warehouse)

**แอป "หลับ" (sleep) — ปกติ ไม่ใช่แอปพัง**
- ถ้าไม่มีคนเข้าสักพัก แอปจะหลับเพื่อประหยัดทรัพยากร
- พอมีคนเปิดลิงก์อีกครั้ง จะ "ตื่น" เอง รอ ~30 วิ–1 นาที (บูตใหม่) แล้วใช้ได้ปกติ
- ถ้าทิ้งไว้นานมากๆ (เป็นเดือน) Streamlit อาจส่งอีเมลถามว่ายังใช้อยู่ไหม → กดยืนยัน/reboot ในเมลก็กลับมา

**ฝั่ง Google (สำคัญกว่า)**
- OAuth consent screen = **Production** แล้ว → refresh token ไม่หมดอายุตามเวลา
- ⚠️ Google จะเพิกถอน token ถ้า **ไม่ถูกใช้เลยเกิน 6 เดือน** → ถ้าใช้งานปกติไม่ต้องห่วง
- รูปเก็บใน Google Drive ของ `tfp.data.mis@gmail.com` (ฟรี 15 GB) → ถ้ารูปเยอะค่อยขยายทีหลัง

**อัปเดตแอปออนไลน์ยังไง?**
- แก้โค้ดในเครื่อง → `git add` → `git commit` → `git push` → Streamlit Cloud จะ redeploy ให้เองอัตโนมัติ

**ถ้าจะเปลี่ยน Secrets (เช่น เปลี่ยนรหัสผ่าน / refresh token ใหม่)**
- ต้องแก้ **2 ที่**: ไฟล์ `.streamlit/secrets.toml` ในเครื่อง + Secrets ใน Streamlit Cloud (App → Settings → Secrets)

---

## ⚠️ บทเรียน
อย่ารัน OAuth refresh token ถี่ๆ ในเวลาสั้น — Google จะ disable client ทดสอบกับ Google API เท่าที่จำเป็นพอ
