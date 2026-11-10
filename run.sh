#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null; then
  echo "[!] ไม่พบ ffmpeg — Mac: brew install ffmpeg | Ubuntu: sudo apt install ffmpeg"
  exit 1
fi

if [ ! -f "settings.txt" ]; then
  cp "settings-example.txt" "settings.txt"
  echo "สร้างไฟล์ settings.txt แล้ว — ใส่คีย์ Gemini / Pixabay ในไฟล์นี้ (ข้ามได้)"
fi

if [ ! -d .venv ]; then
  echo "กำลังติดตั้งครั้งแรก อาจใช้เวลาหลายนาที..."
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

( sleep 3; (open http://localhost:8000 || xdg-open http://localhost:8000) >/dev/null 2>&1 ) &
.venv/bin/python app.py
