"""สร้างโน้ตบุ๊ก Colab ที่ฝังโปรแกรมทั้งหมดไว้ข้างใน (ไม่ต้องดาวน์โหลดไฟล์อื่น)"""
import base64, io, json, sys, zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parent
OUT = Path(sys.argv[1])
REPO = sys.argv[2] if len(sys.argv) > 2 else ""

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    for f in ["app.py", "pipeline.py", "game.py", "story.py", "imagegen.py", "voice.py", "graphics.py", "colab_start.py", "requirements.txt", "static/index.html"]:
        z.write(SRC / f, f"video-summarizer/{f}")
APP_ZIP = base64.b64encode(buf.getvalue()).decode()

intro = """# 🎬 สรุปคลิป — วางลิงก์ YouTube / TikTok / Facebook แล้วได้คลิปสรุปพากย์ไทย (ใช้บนมือถือได้)

**วิธีใช้ (ครั้งแรกใช้เวลา 3–8 นาที)**
1. แนะนำเปิดการ์ดจอฟรีก่อน: เมนู **Runtime → Change runtime type → T4 GPU** → Save
2. เลือกการตั้งค่าในช่องด้านล่าง
3. กด **Runtime → Run all** (บนมือถืออยู่ในเมนู ⋮ หรือ ☰)
4. รอจนขึ้นปุ่มสีส้ม **"เปิดโปรแกรม"** แล้วแตะเพื่อใช้งาน
5. วางลิงก์คลิป → กด **เริ่มสรุปคลิป** → รอรับวิดีโอ

🎮 **ไฮไลต์เกม MLBB:** เลือกโหมด "ไฮไลต์เกม MLBB" ในโปรแกรม แล้วใส่คลิปอัดหน้าจอ (ต้องมีเสียงเกม) → ได้คลิปแนวตั้งพร้อมป้าย SAVAGE / MANIAC สโลว์โมชัน และเสียงพากย์แคสเตอร์
📝 **ข้อความ → คลิป:** พิมพ์/วางบท → พากย์ตามบททุกคำ (หรือให้ AI เรียบเรียง) แบ่งฉาก หาภาพ (AI วาด ครั้งแรกโหลดโมเดล ~10 GB รอ 3-6 นาที / หรือภาพถ่ายจริงจาก Pexels) ทำแอนิเมชัน และพากย์ให้ — ต้องเปิด T4 GPU
🔒 ต้องใส่รหัส PIN (แสดงใต้ปุ่มเปิดโปรแกรม) ก่อนเข้าใช้
🎨 เปิด "ตกแต่งคลิป" เพื่อใส่เพลง ชื่อช่อง โลโก้ และภาพปก · ใส่หลายลิงก์/หลายไฟล์ได้ (แยกคลิปทุกเกม หรือรวมช็อตเด็ดเป็นคลิปเดียว)

⚠️ เปิดหน้านี้ค้างไว้ระหว่างใช้งาน ถ้าปิดหรือไม่ได้ใช้นาน Colab จะหยุดเครื่อง และไฟล์จะหายไป (เว้นแต่เลือกบันทึกลง Google Drive)"""

settings = '''#@title ⚙️ ตั้งค่า
#@markdown **ใช้อะไรสรุปเนื้อหา** — `ollama` = ฟรี (ดาวน์โหลดโมเดลเพิ่ม ~5 GB ครั้งแรก) · `claude` = สรุปดีที่สุด แต่จ่ายตามการใช้ · `none` = เขียนบทพากย์เอง
AI = "ollama"  #@param ["ollama", "claude", "none"]
#@markdown 🔑 คีย์ AI: วางคีย์ **Gemini (ฟรี ขึ้นต้น AIza… หรือ AQ.…)** หรือคีย์ Claude (sk-ant-…) ในช่องนี้ได้เลย — หรือเก็บไว้ใน 🔑 Secrets ชื่อ `GEMINI_API_KEY` / `ANTHROPIC_API_KEY` จะปลอดภัยกว่า
ANTHROPIC_API_KEY = ""  #@param {type:"string"}
#@markdown คีย์ Pexels สำหรับภาพถ่ายจริงในโหมดข้อความ → คลิป (ฟรี สมัครที่ pexels.com/api) — หรือเก็บใน 🔑 Secrets ชื่อ `PEXELS_API_KEY`
PEXELS_API_KEY = ""  #@param {type:"string"}
#@markdown รหัส PIN เข้าโปรแกรม (เว้นว่าง = สุ่มให้ทุกครั้ง แสดงใต้ปุ่มเปิดโปรแกรม)
APP_PIN = ""  #@param {type:"string"}
#@markdown บันทึกงานและวิดีโอลง Google Drive (โฟลเดอร์ "สรุปคลิป") — ไฟล์ไม่หายเมื่อ Colab ปิด
SAVE_TO_DRIVE = False  #@param {type:"boolean"}
#@markdown สร้างลิงก์สำรอง (ใช้เมื่อปุ่มหลักเปิดไม่ได้ เช่นบน iPhone/Safari)
BACKUP_LINK = True  #@param {type:"boolean"}
#@markdown ดึงโปรแกรมเวอร์ชันล่าสุดจาก GitHub ทุกครั้งที่รัน (เว้นว่าง = ใช้เวอร์ชันที่ฝังในไฟล์นี้)
GITHUB_REPO = "%REPO%"  #@param {type:"string"}
'''

start = '''#@title 🚀 เริ่มโปรแกรม — รอจนขึ้นปุ่ม "เปิดโปรแกรม"
import base64, io, os, random, re, shutil, subprocess, sys, time, urllib.request, zipfile
from IPython.display import HTML, display

APP_ZIP = "%s"

def step(t): print(t, flush=True)
def wait_url(url, sec):
    import urllib.error
    for _ in range(sec):
        try:
            urllib.request.urlopen(url, timeout=2); return True
        except urllib.error.HTTPError:
            return True  # เซิร์ฟเวอร์ตอบแล้ว (เช่น 401 ต้องใส่ PIN) = โปรแกรมทำงานอยู่
        except Exception:
            time.sleep(1)
    return False

os.chdir("/content")
APP = "/content/video-summarizer"
subprocess.run("pkill -f 'python app.py'; pkill -f cloudflared", shell=True)
repo = GITHUB_REPO.strip().removeprefix("https://github.com/").strip("/")
got = False
if repo:  # เวอร์ชันล่าสุดจาก GitHub
    step(f"0/4 ดึงโปรแกรมเวอร์ชันล่าสุดจาก github.com/{repo} …")
    tmp = "/content/_app_new"
    shutil.rmtree(tmp, ignore_errors=True)
    r = subprocess.run(["git", "clone", "--depth", "1", f"https://github.com/{repo}.git", tmp], capture_output=True, text=True)
    if r.returncode == 0 and os.path.exists(f"{tmp}/app.py"):
        keep = [x for x in ("jobs", "fonts") if os.path.exists(f"{APP}/{x}")]
        for x in keep:  # เก็บงานเดิมกับฟอนต์ไว้
            shutil.move(f"{APP}/{x}", f"{tmp}/{x}") if not os.path.exists(f"{tmp}/{x}") else None
        shutil.rmtree(APP, ignore_errors=True)
        shutil.move(tmp, APP)
        ver = subprocess.run(["git", "-C", APP, "log", "-1", "--format=%%cd", "--date=format:%%d/%%m %%H:%%M"], capture_output=True, text=True).stdout.strip()
        step(f"   ได้เวอร์ชันล่าสุดแล้ว ✓ (อัปเดตเมื่อ {ver})")
        got = True
    else:
        step("   ⚠️ ดึงจาก GitHub ไม่สำเร็จ ใช้เวอร์ชันที่ฝังในไฟล์นี้แทน: " + (r.stderr or "")[-200:])
if not got:
    zipfile.ZipFile(io.BytesIO(base64.b64decode(APP_ZIP))).extractall("/content")

# ขั้นตอนที่เหลือ (ติดตั้ง เปิดโปรแกรม สร้างลิงก์) อยู่ใน colab_start.py บน GitHub — แก้ที่นั่นแล้วทุกคนได้ทันที
exec(open(f"{APP}/colab_start.py", encoding="utf-8").read(), globals())
''' % APP_ZIP


def code(src, hide=True):
    return {"cell_type": "code", "execution_count": None, "metadata": {"cellView": "form"} if hide else {},
            "outputs": [], "source": src.splitlines(keepends=True)}


nb = {
    "nbformat": 4, "nbformat_minor": 0,
    "metadata": {"colab": {"provenance": [], "name": "สรุปคลิป.ipynb", "gpuType": "T4"}, "accelerator": "GPU",
                 "kernelspec": {"name": "python3", "display_name": "Python 3"}},
    "cells": [{"cell_type": "markdown", "metadata": {}, "source": intro.splitlines(keepends=True)},
              code(settings.replace("%REPO%", REPO)), code(start)],
}
OUT.write_text(json.dumps(nb, ensure_ascii=False, indent=1), encoding="utf-8")
print("wrote", OUT, OUT.stat().st_size, "bytes")
