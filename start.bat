@echo off
REM ===== ดับเบิลคลิกไฟล์นี้เพื่อเปิดแอปคลังภาพ =====
chcp 65001 >nul
cd /d "%~dp0"
echo กำลังเปิดแอปคลังภาพ... (ปิดแอปด้วยการกด Ctrl+C หรือปิดหน้าต่างนี้)
streamlit run app.py
pause
