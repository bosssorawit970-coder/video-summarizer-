@echo off
chcp 65001 >nul
cd /d "%~dp0"
title สรุปคลิป

rem ── 1) หา Python (ใช้ 3.12 / 3.11 ก่อน เพราะไลบรารีบางตัวยังไม่รองรับเวอร์ชันใหม่ล่าสุด) ──
set PY=
py -3.12 -c "1" >nul 2>nul && set PY=py -3.12
if not defined PY ( py -3.11 -c "1" >nul 2>nul && set PY=py -3.11 )
if not defined PY ( py -3 -c "1" >nul 2>nul && set PY=py -3 )
if not defined PY ( python -c "1" >nul 2>nul && set PY=python )
if not defined PY (
  echo [!] ยังไม่มี Python — ติดตั้งก่อน:  winget install Python.Python.3.12
  echo     หรือโหลดจาก python.org ^(ติ๊ก "Add python.exe to PATH" ตอนติดตั้ง^)
  echo     แล้วปิดหน้าต่างนี้ ดับเบิลคลิก run.bat ใหม่
  pause
  exit /b 1
)

rem ── 1.1) ไลบรารีถอดเสียง (onnxruntime) ยังไม่รองรับ Python ใหม่มาก/32 บิต → ใช้ 3.12 ──
%PY% -c "import sys,struct; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) and struct.calcsize('P')==8 else 1)" >nul 2>nul
if errorlevel 1 (
  echo [!] Python ที่มีอยู่เป็นเวอร์ชันที่ไลบรารียังไม่รองรับ — กำลังติดตั้ง Python 3.12 ให้...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  py -3.12 -c "1" >nul 2>nul && set PY=py -3.12
  py -3.12 -c "1" >nul 2>nul || (
    echo [!] ติดตั้ง Python 3.12 ไม่สำเร็จ — โหลดเองที่ python.org/downloads/release/python-3128/
    echo     ^(เลือก Windows installer 64-bit ติ๊ก Add python.exe to PATH^) แล้วเปิด run.bat ใหม่
    pause
    exit /b 1
  )
  if exist .venv rmdir /s /q .venv
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

rem ── 4) ติดตั้งไลบรารี — ทำใหม่จนกว่าจะสำเร็จครบ (มีไฟล์ .venv\installed.ok) ──
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python -c "import starlette, uvicorn, faster_whisper, edge_tts, PIL, pythainlp, yt_dlp, trafilatura" >nul 2>nul || del /q .venv\installed.ok >nul 2>nul
)
if not exist .venv\installed.ok (
  echo กำลังติดตั้งไลบรารี อาจใช้เวลา 5-15 นาที ^(ทำครั้งเดียว^)...
  if not exist .venv\Scripts\python.exe %PY% -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [!] ติดตั้งไม่สำเร็จ — แคปข้อความสีแดงด้านบนส่งให้ Claude ดู
    echo     ถ้าใช้ Python ใหม่มาก ลองติดตั้ง 3.12:  winget install Python.Python.3.12
    echo     แล้วลบโฟลเดอร์ .venv ทิ้ง ดับเบิลคลิก run.bat ใหม่
    pause
    exit /b 1
  )
  echo ok> .venv\installed.ok
)

start "" http://localhost:8000
.venv\Scripts\python app.py
pause
