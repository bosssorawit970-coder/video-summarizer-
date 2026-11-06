"""สร้างโน้ตบุ๊ก Colab ที่ฝังโปรแกรมทั้งหมดไว้ข้างใน (ไม่ต้องดาวน์โหลดไฟล์อื่น)"""
import base64, io, json, sys, zipfile
from pathlib import Path

SRC = Path(__file__).resolve().parent
OUT = Path(sys.argv[1])
REPO = sys.argv[2] if len(sys.argv) > 2 else ""

buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
    for f in ["app.py", "pipeline.py", "game.py", "story.py", "imagegen.py", "requirements.txt", "static/index.html"]:
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
#@markdown คีย์ Claude API (ใช้เมื่อเลือก `claude`) — หรือเก็บไว้ใน 🔑 Secrets ชื่อ `ANTHROPIC_API_KEY` จะปลอดภัยกว่า
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

step("1/4 ติดตั้งไลบรารี…")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "-r", f"{APP}/requirements.txt"], check=True)
# วาดภาพด้วย AI (โหมดข้อความ → คลิป) — torch มีใน Colab อยู่แล้ว
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "diffusers", "transformers", "accelerate"], capture_output=True)
# ฟอนต์ไทย สำหรับซับไตเติล ชื่อช่อง และภาพปก (Colab ไม่มีมาให้) — Kanit (Google Fonts) + สำรอง tlwg
subprocess.run("apt-get install -y -qq fonts-thai-tlwg > /dev/null 2>&1", shell=True)
os.makedirs(f"{APP}/fonts", exist_ok=True)
for w in ("Bold", "SemiBold"):
    f = f"{APP}/fonts/Kanit-{w}.ttf"
    if not os.path.exists(f):
        try:
            urllib.request.urlretrieve(f"https://github.com/google/fonts/raw/main/ofl/kanit/Kanit-{w}.ttf", f)
        except Exception as e:
            step(f"   ⚠️ โหลดฟอนต์ Kanit ไม่ได้ ({e}) ใช้ฟอนต์สำรองแทน")
os.makedirs(os.path.expanduser("~/.fonts"), exist_ok=True)
subprocess.run(f"cp {APP}/fonts/*.ttf ~/.fonts/ 2>/dev/null; fc-cache -f > /dev/null 2>&1", shell=True)
# ตัวรัน JavaScript ที่ yt-dlp ต้องใช้กับ YouTube (ถ้าติดตั้งไม่ได้ จะใช้ node ที่มีใน Colab แทน)
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "deno"], capture_output=True)

gpu = subprocess.run("nvidia-smi", shell=True, capture_output=True).returncode == 0
step("   การ์ดจอ: " + ("มี ✓ (ถอดเสียงเร็ว)" if gpu else "ไม่มี — ถอดเสียงจะช้า แนะนำเปลี่ยนเป็น T4 GPU"))

env = os.environ.copy()
env["HOST"], env["PORT"] = "127.0.0.1", "8000"
key = ANTHROPIC_API_KEY.strip()
if not key:
    try:
        from google.colab import userdata
        key = userdata.get("ANTHROPIC_API_KEY") or ""
    except Exception:
        key = ""
if key:
    env["ANTHROPIC_API_KEY"] = key
elif AI == "claude":
    step("   ⚠️ ยังไม่ได้ใส่คีย์ Claude — จะใช้โหมดเขียนบทเอง")

pex = PEXELS_API_KEY.strip()
if not pex:
    try:
        from google.colab import userdata
        pex = userdata.get("PEXELS_API_KEY") or ""
    except Exception:
        pex = ""
if pex:
    env["PEXELS_API_KEY"] = pex
pin = APP_PIN.strip()
if not pin:  # สุ่ม PIN 6 หลัก (ใช้ค่าเดิมถ้ารันซ้ำในรอบเดียวกัน)
    pin = open("/content/.pin").read().strip() if os.path.exists("/content/.pin") else f"{random.randint(0, 999999):06d}"
    open("/content/.pin", "w").write(pin)
env["APP_PIN"] = pin

if SAVE_TO_DRIVE:
    from google.colab import drive
    drive.mount("/content/drive")
    env["JOBS_DIR"] = "/content/drive/MyDrive/สรุปคลิป"

if AI == "ollama":
    step("2/4 ติดตั้ง Ollama และโหลดโมเดล AI (ครั้งแรก 2–5 นาที)…")
    if subprocess.run("which ollama", shell=True, capture_output=True).returncode != 0:
        subprocess.run("apt-get install -y -qq zstd > /dev/null; curl -fsSL https://ollama.com/install.sh | sh > /dev/null",
                       shell=True)
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if wait_url("http://127.0.0.1:11434/api/tags", 60):
        subprocess.run(["ollama", "pull", "qwen2.5:7b"], stdout=subprocess.DEVNULL)
    else:
        step("   ⚠️ เปิด Ollama ไม่สำเร็จ — จะใช้โหมดเขียนบทเอง")
else:
    step("2/4 ข้ามการติดตั้ง Ollama")

step("3/4 เปิดโปรแกรม…")
log = open("/content/app.log", "w")
subprocess.Popen([sys.executable, "app.py"], cwd=APP, env=env, stdout=log, stderr=subprocess.STDOUT)
if not wait_url("http://127.0.0.1:8000/api/config", 60):
    print(open("/content/app.log").read()); raise SystemExit("โปรแกรมเปิดไม่สำเร็จ ดูข้อความด้านบน")

step("4/4 สร้างลิงก์…")
from google.colab.output import eval_js
main_url = eval_js("google.colab.kernel.proxyPort(8000, {'cache': false})")
backup = ""
if BACKUP_LINK:
    if not os.path.exists("/content/cloudflared"):
        urllib.request.urlretrieve("https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
                                   "/content/cloudflared")
        os.chmod("/content/cloudflared", 0o755)
    cf = open("/content/cloudflared.log", "w")
    subprocess.Popen(["/content/cloudflared", "tunnel", "--url", "http://127.0.0.1:8000", "--no-autoupdate"],
                     stdout=cf, stderr=cf)
    for _ in range(40):
        m = re.search(r"https://[a-z0-9-]+\\.trycloudflare\\.com", open("/content/cloudflared.log").read())
        if m:
            backup = m.group(0); break
        time.sleep(1)

btn = "display:block;text-align:center;padding:16px;border-radius:12px;font:600 18px sans-serif;text-decoration:none;margin:10px 0"
html = f'<a href="{main_url}" target="_blank" style="{btn};background:#d9480f;color:#fff">▶ เปิดโปรแกรม</a>'
if backup:
    html += (f'<a href="{backup}" target="_blank" style="{btn};border:2px solid #d9480f;color:#d9480f">ลิงก์สำรอง (ถ้าปุ่มบนเปิดไม่ได้)</a>'
             '<div style="font:13px sans-serif;color:#888">ลิงก์เปลี่ยนทุกครั้งที่รันใหม่ · ต้องใส่ PIN ก่อนใช้ทั้งสองลิงก์</div>')
html += (f'<div style="text-align:center;font:15px sans-serif;margin-top:6px">รหัส PIN เข้าโปรแกรม</div>'
         f'<div style="text-align:center;font:700 34px monospace;letter-spacing:.3em">{pin}</div>')
display(HTML(html))
print("\\n✅ พร้อมใช้งาน — เปิดหน้านี้ค้างไว้ระหว่างใช้ (กดปุ่ม ■ หยุดเซลล์นี้เมื่อเลิกใช้)")

# วนรอไว้เพื่อให้ Colab รู้ว่ายังใช้งานอยู่ และแจ้งถ้าโปรแกรมล่ม
try:
    while True:
        time.sleep(60)
        if not wait_url("http://127.0.0.1:8000/api/config", 5):
            print("⚠️ โปรแกรมหยุดทำงาน:\\n" + open("/content/app.log").read()[-2000:]); break
except KeyboardInterrupt:
    subprocess.run("pkill -f 'python app.py'; pkill -f cloudflared; pkill -f 'ollama serve'", shell=True)
    print("ปิดโปรแกรมแล้ว")
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
