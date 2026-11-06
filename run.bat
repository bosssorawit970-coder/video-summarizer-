@echo off
chcp 65001 >nul
cd /d "%~dp0"

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [!] ไม่พบ ffmpeg — ติดตั้งด้วยคำสั่ง:  winget install Gyan.FFmpeg
  echo     แล้วปิดหน้าต่างนี้ เปิดใหม่อีกครั้ง
  pause
  exit /b 1
)

if not exist .venv (
  echo กำลังติดตั้งครั้งแรก อาจใช้เวลาหลายนาที...
  py -3 -m venv .venv || python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
)

start "" http://localhost:8000
.venv\Scripts\python app.py
pause
