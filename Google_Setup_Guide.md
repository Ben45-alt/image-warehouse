# คู่มือ Setup Google สำหรับโปรเจกต์คลังภาพ (Streamlit)

> เป้าหมาย: เตรียมฝั่ง Google ให้พร้อม ก่อนเริ่มเขียนโค้ด
> เราจะใช้วิธี **OAuth** (ให้แอป login ด้วยบัญชี Google ของเราเอง) เพราะ **ฟรี 100%** และอัปรูปขึ้น Drive ได้จริง
> บัญชีที่ใช้: claude.mis.tfp@gmail.com

---

## ภาพรวม ต้องทำอะไรบ้าง (3 ส่วน)

| ส่วน | ทำอะไร | ความยาก | ทำตอนไหน |
|------|--------|---------|----------|
| A | สร้าง Project + เปิด API | ง่าย | ทำเองได้เลย |
| B | สร้าง Google Sheet + โฟลเดอร์ Drive | ง่ายมาก | ทำเองได้เลย |
| C | สร้าง Credentials (OAuth) | ปานกลาง | **ทำด้วยกันกับ Claude** |

---

## ส่วน A — สร้าง Project และเปิด API

1. เข้า **Google Cloud Console**: https://console.cloud.google.com
   - login ด้วย claude.mis.tfp@gmail.com
   - (ครั้งแรกอาจให้กดยอมรับเงื่อนไข ก็กดยอมรับ)

2. **สร้าง Project ใหม่**
   - มุมบนซ้าย กดที่ชื่อโปรเจกต์ (ข้างๆ คำว่า Google Cloud) → กด **NEW PROJECT**
   - ตั้งชื่อ เช่น `image-warehouse` → กด **CREATE**
   - รอสักครู่ แล้วเลือกโปรเจกต์นี้ให้เป็นโปรเจกต์ปัจจุบัน

3. **เปิด API 2 ตัว** (สำคัญมาก ถ้าไม่เปิด โค้ดจะ error)
   - เข้า: https://console.cloud.google.com/apis/library
   - ค้นหา **"Google Drive API"** → กดเข้าไป → กด **ENABLE**
   - ค้นหา **"Google Sheets API"** → กดเข้าไป → กด **ENABLE**

✅ เสร็จส่วน A

---

## ส่วน B — สร้างที่เก็บข้อมูล

### B1. สร้าง Google Sheet (ฐานข้อมูล)
1. เข้า https://sheets.google.com → สร้างชีตใหม่
2. ตั้งชื่อ เช่น `Image_Warehouse_DB`
3. แถวแรก (หัวตาราง) ใส่คอลัมน์พวกนี้ (เดี๋ยว Claude จะปรับให้ตรงโค้ดอีกที):
   ```
   วันเวลา | แผนก | หมวด | ชื่อเรื่อง | แท็ก | ผู้ส่ง | ลิงก์รูป | ชื่อไฟล์
   ```
4. **คัดลอกลิงก์ URL ของชีต** เก็บไว้ (จะใช้ในโค้ด)

### B2. สร้างโฟลเดอร์ Drive (เก็บรูป)
1. เข้า https://drive.google.com → New → New folder
2. ตั้งชื่อ เช่น `Image_Warehouse_Photos`
3. เปิดเข้าไปในโฟลเดอร์ แล้ว **คัดลอก Folder ID** จาก URL
   - URL จะหน้าตาแบบ: `https://drive.google.com/drive/folders/`**`1AbcdEfgh1234XYZ`**
   - ตัวหนาคือ Folder ID เก็บไว้

✅ เสร็จส่วน B

---

## ส่วน C — สร้าง Credentials (OAuth)  ⚠️ ทำด้วยกันกับ Claude

> ส่วนนี้คือ "กุญแจ" ให้โปรแกรมเข้าถึง Google ของเราได้
> มีหลายจอ เดี๋ยว Claude พาทำทีละขั้นตอนตอนเริ่มเขียนโค้ด แต่บอกภาพรวมไว้ก่อน:

1. ตั้งค่า **OAuth consent screen** (External, ใส่อีเมลตัวเองเป็น test user)
2. สร้าง **OAuth Client ID** แบบ Desktop app → ดาวน์โหลดไฟล์ `.json`
3. รันสคริปต์เล็กๆ 1 ครั้ง เพื่อ login → ได้ "refresh token"
4. เก็บค่าพวกนี้ไว้ใน **Streamlit Secrets** (ปลอดภัย ไม่ต้องวางไฟล์โต้งๆ ในโค้ด)

❗ **อย่าเพิ่งทำส่วน C ตอนนี้** — ทำพร้อม Claude ตอนลงโค้ดจะง่ายกว่า

---

## เช็คลิสต์ก่อนเริ่มเขียนโค้ด

- [ ] A1: สร้าง Project แล้ว
- [ ] A3: เปิด Google Drive API แล้ว
- [ ] A3: เปิด Google Sheets API แล้ว
- [ ] B1: สร้าง Google Sheet + เก็บลิงก์แล้ว
- [x] B2: สร้างโฟลเดอร์ Drive + เก็บ Folder ID แล้ว
- [x] C: ตั้ง OAuth + ได้ refresh token + ตรวจสอบเข้าถึง Sheet/Drive ผ่านแล้ว ✅

> ✅ ส่วน C เสร็จสมบูรณ์ — บัญชีที่ใช้คือ tfp.data.mis@gmail.com
> ค่าทั้งหมดเก็บไว้ใน .streamlit/secrets.toml แล้ว ขั้นต่อไปคือเขียนโค้ดแอป (เฟส 1)
