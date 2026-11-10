@echo off
rem Sarup Clip launcher (ASCII only + CRLF so Windows cmd reads it correctly)
cd /d "%~dp0"
title Sarup Clip

rem == 1) Find Python (prefer 3.12 / 3.11) ==
set PY=
py -3.12 -c "1" >nul 2>nul && set PY=py -3.12
if not defined PY ( py -3.11 -c "1" >nul 2>nul && set PY=py -3.11 )
if not defined PY ( py -3 -c "1" >nul 2>nul && set PY=py -3 )
if not defined PY ( python -c "1" >nul 2>nul && set PY=python )
if not defined PY (
  echo [!] Python not found. Install it:  winget install Python.Python.3.12
  echo     or from python.org - tick "Add python.exe to PATH"
  echo     then close this window and double-click run.bat again
  pause
  exit /b 1
)

rem == 1.1) Need 64-bit Python 3.10-3.13 ==
%PY% -c "import sys,struct; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,13) and struct.calcsize('P')==8 else 1)" >nul 2>nul
if errorlevel 1 (
  echo [!] This Python version is not supported - installing Python 3.12...
  winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
  py -3.12 -c "1" >nul 2>nul && set PY=py -3.12
  py -3.12 -c "1" >nul 2>nul || (
    echo [!] Could not install Python 3.12. Download it from python.org/downloads/release/python-3128/
    echo     - Windows installer 64-bit, tick Add python.exe to PATH - then run run.bat again
    pause
    exit /b 1
  )
  if exist .venv rmdir /s /q .venv
)

rem == 2) Need ffmpeg ==
where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [!] ffmpeg not found. Install it:  winget install Gyan.FFmpeg
  echo     then close this window and open run.bat again
  pause
  exit /b 1
)

rem == 3) Settings file - first run opens it for API keys ==
if not exist "settings.txt" (
  copy /y "settings-example.txt" "settings.txt" >nul
  echo Opening settings.txt - paste your Gemini / Pixabay keys, then save and close Notepad
  start /wait notepad "settings.txt"
)

rem == 4) Install libraries - redo until complete (.venv\installed.ok) ==
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python -c "import starlette, uvicorn, faster_whisper, edge_tts, PIL, pythainlp, yt_dlp, trafilatura" >nul 2>nul || del /q .venv\installed.ok >nul 2>nul
)
if not exist .venv\installed.ok (
  echo Installing libraries, this takes 5-15 minutes - only the first time...
  if not exist .venv\Scripts\python.exe %PY% -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install --upgrade -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [!] Install failed - take a screenshot of the red text above and send it to Claude
    echo     then delete the .venv folder and double-click run.bat again
    pause
    exit /b 1
  )
  echo ok> .venv\installed.ok
)

start "" http://localhost:8000
.venv\Scripts\python app.py
pause
