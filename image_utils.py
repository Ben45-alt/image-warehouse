# -*- coding: utf-8 -*-
"""
image_utils.py — ฟังก์ชันจัดการรูปด้วย Pillow (ย่อ/บีบอัด + ฝัง metadata + ลายนิ้วมือรูป)
เป้าหมาย:
- ลดขนาดไฟล์ให้เหลือ ~100-300 KB เพื่อประหยัดพื้นที่และโหลดเร็ว
- ฝังข้อมูลบริบท (กิจกรรม/ผู้ส่ง/วันที่) ลง EXIF ของรูป + เก็บ EXIF เดิมจากกล้องไว้ด้วย
- คำนวณ perceptual hash (pHash/dHash) ไว้ตรวจ "รูปซ้ำ/เกือบเหมือน"
"""

import io

from PIL import Image, ImageOps

# piexif ใช้จัดการ EXIF: อ่านของเดิม (เก็บวันเวลาถ่ายจริง/GPS) + เขียนฟิลด์ที่เราอยากฝัง
import piexif


# ===========================================================================
# EXIF / metadata
# ===========================================================================
def _ascii_bytes(s) -> bytes:
    """ค่าสำหรับแท็ก EXIF มาตรฐาน (ImageDescription/Artist/...) — เก็บเป็น UTF-8 bytes"""
    return str(s).encode("utf-8")


def _xp_bytes(s) -> bytes:
    """
    ค่าสำหรับแท็ก 'XP' ของ Windows (XPTitle/XPComment/XPAuthor) = UTF-16LE + ปิดท้าย \\x00\\x00
    ข้อดี: Windows Explorer โชวภาษาไทยใน 'รายละเอียด' ได้ถูกต้อง (แท็กมาตรฐานบางตัวโชว์ไทยเพี้ยน)
    """
    return str(s).encode("utf-16-le") + b"\x00\x00"


def _apply_meta(exif_dict: dict, meta: dict) -> None:
    """เขียนข้อมูลบริบทของเราลงใน exif_dict (แก้ในตัว) — ครอบคลุมทั้งแท็กมาตรฐาน + แท็ก XP"""
    exif_dict.setdefault("0th", {})
    exif_dict.setdefault("Exif", {})

    # หมุนรูปฝังลงพิกเซลแล้ว (ผ่าน exif_transpose) → ตั้ง Orientation = 1 กันโปรแกรมหมุนซ้ำ
    exif_dict["0th"][piexif.ImageIFD.Orientation] = 1
    exif_dict["0th"][piexif.ImageIFD.Software] = _ascii_bytes("Image Warehouse")

    if not meta:
        return

    desc = str(meta.get("description", "")).strip()
    artist = str(meta.get("artist", "")).strip()
    dt = str(meta.get("datetime", "")).strip()  # รูปแบบ EXIF: "YYYY:MM:DD HH:MM:SS"

    if desc:
        exif_dict["0th"][piexif.ImageIFD.ImageDescription] = _ascii_bytes(desc)
        exif_dict["0th"][piexif.ImageIFD.XPTitle] = _xp_bytes(desc)
        exif_dict["0th"][piexif.ImageIFD.XPComment] = _xp_bytes(desc)
    if artist:
        exif_dict["0th"][piexif.ImageIFD.Artist] = _ascii_bytes(artist)
        exif_dict["0th"][piexif.ImageIFD.XPAuthor] = _xp_bytes(artist)
    if dt:
        # DateTime = เวลาที่ระบบบันทึก; DateTimeOriginal = เวลาถ่ายจริง (เก็บของเดิมไว้ก่อน ถ้าไม่มีค่อยเติม)
        exif_dict["0th"][piexif.ImageIFD.DateTime] = _ascii_bytes(dt)
        exif_dict["Exif"].setdefault(piexif.ExifIFD.DateTimeOriginal, _ascii_bytes(dt))


def _build_exif(original_bytes: bytes, meta: dict):
    """
    สร้าง EXIF bytes สำหรับฝังในรูปที่บีบอัดแล้ว:
    - พยายามอ่าน EXIF เดิมจากไฟล์ต้นฉบับก่อน (เก็บวันเวลาถ่ายจริง/GPS/รุ่นกล้อง)
    - เขียนบริบทของเราทับ/เติม
    คืน None ถ้าทำไม่ได้ (เช่นไฟล์ไม่มี EXIF อย่าง PNG จากกล้องเว็บ) → รูปยังเซฟได้ปกติ
    """
    # 1) พยายามต่อยอดจาก EXIF เดิม
    try:
        exif_dict = piexif.load(original_bytes)
    except Exception:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    _apply_meta(exif_dict, meta)

    try:
        return piexif.dump(exif_dict)
    except Exception:
        # EXIF เดิมบางตัวมีแท็กแปลกที่ dump ไม่ผ่าน (เช่น MakerNote) → สร้างใหม่เฉพาะฟิลด์ของเรา
        minimal = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
        _apply_meta(minimal, meta)
        try:
            return piexif.dump(minimal)
        except Exception:
            return None


def compress_image(uploaded_file, max_width: int = 1200, quality: int = 80, meta: dict = None) -> io.BytesIO:
    """
    รับไฟล์รูปที่อัปโหลดเข้ามา แล้วคืนเป็นไฟล์ JPEG ที่ย่อแล้ว (อยู่ในหน่วยความจำ)
    - max_width: ความกว้างสูงสุด 1200px (ถ้าใหญ่กว่านี้จะย่อ โดยรักษาสัดส่วน)
    - quality: คุณภาพ JPEG (75-80 กำลังดี)
    - meta: dict บริบทที่จะฝังลง EXIF {description, artist, datetime} (ไม่ใส่ก็ได้)
    """
    raw = uploaded_file.read()  # อ่าน bytes ต้นฉบับไว้ (ใช้ทั้งเปิดรูป + อ่าน EXIF เดิม)
    try:
        uploaded_file.seek(0)   # เผื่อผู้เรียกอยากใช้ไฟล์ต่อ
    except Exception:
        pass

    img = Image.open(io.BytesIO(raw))

    # หมุนรูปให้ถูกด้านตามข้อมูล EXIF (รูปจากกล้องมือถือบางทีตะแคง)
    img = ImageOps.exif_transpose(img)

    # แปลงเป็นโหมด RGB (กัน PNG โปร่งใส/ภาพขาวดำ พังตอนเซฟเป็น JPEG)
    if img.mode != "RGB":
        img = img.convert("RGB")

    # ย่อความกว้างถ้าเกินกำหนด (รักษาสัดส่วนเดิม)
    if img.width > max_width:
        ratio = max_width / img.width
        new_height = int(img.height * ratio)
        img = img.resize((max_width, new_height))

    # เตรียม EXIF (เก็บของเดิม + ฝังบริบท)
    exif_bytes = _build_exif(raw, meta)

    # เซฟลงหน่วยความจำเป็น JPEG (ไม่เขียนลงดิสก์)
    buffer = io.BytesIO()
    save_kwargs = dict(format="JPEG", quality=quality, optimize=True)
    if exif_bytes:
        save_kwargs["exif"] = exif_bytes
    img.save(buffer, **save_kwargs)
    buffer.seek(0)  # เลื่อนกลับไปต้นไฟล์ เพื่อให้อ่านต่อได้
    return buffer


# ===========================================================================
# perceptual hash (dHash) — ลายนิ้วมือรูปไว้ตรวจ "ซ้ำ/เกือบเหมือน"
# ===========================================================================
def compute_phash(image_bytes: bytes) -> str:
    """
    คำนวณ dHash 64 บิต คืนเป็น hex 16 ตัว (เช่น 'f0e1c3...') — เบา ไม่ต้องพึ่งไลบรารีนอก
    หลักการ: ย่อรูปเป็นสีเทา 9x8 แล้วเทียบความสว่างพิกเซลซ้าย-ขวาทีละคู่ (8x8 = 64 บิต)
    จับรูปเดิม/เกือบเหมือนได้แม้ถูกย่อ/บีบอัด. คืน "" ถ้าคำนวณไม่ได้
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L").resize((9, 8))
        px = list(img.getdata())  # 72 ค่า (9 คอลัมน์ x 8 แถว)
        bits = 0
        for row in range(8):
            base = row * 9
            for col in range(8):
                left = px[base + col]
                right = px[base + col + 1]
                bits = (bits << 1) | (1 if left > right else 0)
        return format(bits, "016x")
    except Exception:
        return ""


def hamming_distance(h1: str, h2: str) -> int:
    """
    ระยะแฮมมิงระหว่าง pHash สองอัน (จำนวนบิตที่ต่างกัน 0-64)
    ยิ่งน้อยยิ่งเหมือน — ปกติ <= 5 ถือว่า "รูปเดียวกัน/เกือบเหมือน"
    ถ้าค่าใดว่าง/ยาวไม่เท่ากันคืน 64 (ถือว่าต่างสุด)
    """
    if not h1 or not h2 or len(h1) != len(h2):
        return 64
    try:
        return bin(int(h1, 16) ^ int(h2, 16)).count("1")
    except Exception:
        return 64
