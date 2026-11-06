#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

if ! command -v ffmpeg >/dev/null; then
  echo "[!] ไม่พบ ffmpeg — Mac: brew install ffmpeg | Ubuntu: sudo apt install ffmpeg"
  exit 1
fi

if [ ! -d .venv ]; then
  echo "กำลังติดตั้งครั้งแรก อาจใช้เวลาหลายนาที..."
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
fi

( sleep 2; (open http://localhost:8000 || xdg-open http://localhost:8000) >/dev/null 2>&1 ) &
.venv/bin/python app.py
