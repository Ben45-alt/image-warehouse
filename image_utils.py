# -*- coding: utf-8 -*-
"""
image_utils.py — ฟังก์ชันจัดการรูปด้วย Pillow (ย่อ/บีบอัด)
เป้าหมาย: ลดขนาดไฟล์ให้เหลือ ~100-300 KB เพื่อประหยัดพื้นที่และโหลดเร็ว
"""

import io
from PIL import Image, ImageOps


def compress_image(uploaded_file, max_width: int = 1200, quality: int = 80) -> io.BytesIO:
    """
    รับไฟล์รูปที่อัปโหลดเข้ามา แล้วคืนเป็นไฟล์ JPEG ที่ย่อแล้ว (อยู่ในหน่วยความจำ)
    - max_width: ความกว้างสูงสุด 1200px (ถ้าใหญ่กว่านี้จะย่อ โดยรักษาสัดส่วน)
    - quality: คุณภาพ JPEG (75-80 กำลังดี)
    """
    img = Image.open(uploaded_file)

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

    # เซฟลงหน่วยความจำเป็น JPEG (ไม่เขียนลงดิสก์)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=quality, optimize=True)
    buffer.seek(0)  # เลื่อนกลับไปต้นไฟล์ เพื่อให้อ่านต่อได้
    return buffer
