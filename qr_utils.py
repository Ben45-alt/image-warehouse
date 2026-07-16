# -*- coding: utf-8 -*-
"""
qr_utils.py — สร้างรูป QR Code จากข้อความ (เช่น รหัสกิจกรรม / รหัสดูส่วนตัว)
ไว้ให้ admin โชว์ให้คนสแกนแทนการพิมพ์รหัสเอง
"""

import io

import qrcode


def qr_png(data: str, box_size: int = 8, border: int = 2) -> bytes:
    """แปลงข้อความเป็นรูป QR Code (PNG bytes) — คืน b'' ถ้าทำไม่ได้"""
    try:
        qr = qrcode.QRCode(box_size=box_size, border=border)
        qr.add_data(str(data))
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return b""
