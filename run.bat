@echo off
chcp 65001 >nul
cd /d "%~dp0"
title สรุปคลิป

rem ── 1) ต้องมี Python ──
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY ( where python >nul 2>nul && set PY=python )
if not defined PY (
  echo [!] ยังไม่มี Python — ติดตั้งก่อน:  winget install Python.Python.3.12
  echo     หรือโหลดจาก python.org ^(ติ๊ก "Add python.exe to PATH" ตอนติดตั้ง^)
  echo     แล้วปิดหน้าต่างนี้ ดับเบิลคลิก run.bat ใหม่
  pause
  exit /b 1
)

rem ── 2) ต้องมี ffmpeg ──
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [!] ยังไม่มี ffmpeg — ติดตั้งด้วยคำสั่ง:  winget install Gyan.FFmpeg
  echo     แล้วปิดหน้าต่างนี้ เปิดใหม่อีกครั้ง
  pause
  exit /b 1
)

rem ── 3) ไฟล์ตั้งค่า (ครั้งแรก: เปิดให้ใส่คีย์) ──
if not exist "settings.txt" (
  copy /y "settings-example.txt" "settings.txt" >nul
  echo เปิดไฟล์ settings.txt ให้ใส่คีย์ Gemini / Pixabay แล้วกดบันทึก ^(ข้ามได้^)
  start /wait notepad "settings.txt"
)

rem ── 4) ติดตั้งครั้งแรก ──
if not exist .venv (
  echo กำลังติดตั้งครั้งแรก อาจใช้เวลา 5-15 นาที...
  %PY% -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt || (pause & exit /b 1)
)

start "" http://localhost:8000
.venv\Scripts\python app.py
pause
