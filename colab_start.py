"""
ส่วนเริ่มโปรแกรมบน Google Colab — โน้ตบุ๊กดึงไฟล์นี้จาก GitHub แล้วรัน
(แก้ไฟล์นี้ใน GitHub = ทุกคนได้ขั้นตอนเริ่มโปรแกรมใหม่ทันที ไม่ต้องอัปโหลดโน้ตบุ๊กใหม่)
ต้องมีตัวแปรจากเซลล์ตั้งค่า: AI, ANTHROPIC_API_KEY, PEXELS_API_KEY, APP_PIN, SAVE_TO_DRIVE, BACKUP_LINK, APP
"""
import os, random, re, subprocess, sys, time, urllib.request
from IPython.display import HTML, display


def step(t):
    print(t, flush=True)


def wait_url(url, sec):
    import urllib.error
    for _ in range(sec):
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except urllib.error.HTTPError:
            return True  # เซิร์ฟเวอร์ตอบแล้ว (เช่น 401 ต้องใส่ PIN) = โปรแกรมทำงานอยู่
        except Exception:
            time.sleep(1)
    return False


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
    try:
        from google.colab import drive
        drive.mount("/content/drive")
        env["JOBS_DIR"] = "/content/drive/MyDrive/สรุปคลิป"
        step("   เก็บงานไว้ใน Google Drive โฟลเดอร์ \"สรุปคลิป\" ✓")
    except Exception as e:
        step(f"   ⚠️ เชื่อม Google Drive ไม่สำเร็จ ({e}) — ทำงานต่อโดยเก็บไฟล์ในเครื่อง Colab ชั่วคราวแทน")
        step("      (ถ้าอยากเก็บใน Drive: กดอนุญาตตอนมีหน้าต่างเด้งขึ้น หรือใช้บนคอมพิวเตอร์)")

if AI == "ollama":
    step("2/4 ติดตั้ง Ollama และโหลดโมเดล AI (ครั้งแรก 2–5 นาที)…")
    if subprocess.run("which ollama", shell=True, capture_output=True).returncode != 0:
        subprocess.run("apt-get install -y -qq zstd > /dev/null; curl -fsSL https://ollama.com/install.sh | sh > /dev/null",
                       shell=True)
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if wait_url("http://127.0.0.1:11434/api/tags", 60):
        # มีการ์ดจอ → รุ่น 14B เข้าใจภาษาไทยและคิดภาพได้ตรงกว่า 7B มาก (โหลดเพิ่ม ~9 GB)
        om = globals().get("OLLAMA_MODEL") or ("qwen2.5:14b" if gpu else "qwen2.5:7b")
        step(f"   โมเดล: {om}")
        r = subprocess.run(["ollama", "pull", om], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if r.returncode != 0 and om != "qwen2.5:7b":
            step("   ⚠️ โหลดรุ่นใหญ่ไม่สำเร็จ ใช้ qwen2.5:7b แทน")
            om = "qwen2.5:7b"
            subprocess.run(["ollama", "pull", om], stdout=subprocess.DEVNULL)
        env["OLLAMA_MODEL"] = om
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
# ลิงก์สำรอง (Cloudflare) ทำก่อน — ไม่ต้องรอหน้าเว็บ Colab ตอบ ใช้ได้แม้จอดับ/สลับแอป
backup = ""
if BACKUP_LINK:
    try:
        if not os.path.exists("/content/cloudflared"):
            urllib.request.urlretrieve("https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
                                       "/content/cloudflared")
            os.chmod("/content/cloudflared", 0o755)
        cf = open("/content/cloudflared.log", "w")
        subprocess.Popen(["/content/cloudflared", "tunnel", "--url", "http://127.0.0.1:8000", "--no-autoupdate"],
                         stdout=cf, stderr=cf)
        for _ in range(40):
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", open("/content/cloudflared.log").read())
            if m:
                backup = m.group(0)
                break
            time.sleep(1)
    except Exception as e:
        step(f"   ⚠️ สร้างลิงก์สำรองไม่ได้: {e}")
    if backup:
        print(f"   ลิงก์สำรอง: {backup}", flush=True)

# ลิงก์หลักต้องให้หน้าเว็บ Colab ตอบกลับ — รอไม่เกิน 20 วินาที (ถ้าหน้าเว็บหลุด จะไม่ค้าง)
main_url = ""
import threading
def _ask_proxy(box):
    try:
        from google.colab.output import eval_js
        box.append(eval_js("google.colab.kernel.proxyPort(8000, {'cache': false})"))
    except Exception:
        pass
_box = []
_t = threading.Thread(target=_ask_proxy, args=(_box,), daemon=True)
_t.start()
_t.join(20)
main_url = _box[0] if _box else ""
if not main_url and not backup:
    step("   ⚠️ สร้างลิงก์ไม่ได้ — หน้าเว็บ Colab หลุดการเชื่อมต่อ แตะหน้าจอให้เชื่อมต่อใหม่ แล้วกดรันเซลล์นี้อีกครั้ง")

btn = "display:block;text-align:center;padding:16px;border-radius:12px;font:600 18px sans-serif;text-decoration:none;margin:10px 0"
html = ""
if main_url:
    html += f'<a href="{main_url}" target="_blank" style="{btn};background:#d9480f;color:#fff">▶ เปิดโปรแกรม</a>'
if backup:
    style = "background:#d9480f;color:#fff" if not main_url else "border:2px solid #d9480f;color:#d9480f"
    label = "▶ เปิดโปรแกรม" if not main_url else "ลิงก์สำรอง (ถ้าปุ่มบนเปิดไม่ได้)"
    html += (f'<a href="{backup}" target="_blank" style="{btn};{style}">{label}</a>'
             '<div style="font:13px sans-serif;color:#888">ลิงก์เปลี่ยนทุกครั้งที่รันใหม่ · ต้องใส่ PIN ก่อนใช้ทั้งสองลิงก์</div>')
html += (f'<div style="text-align:center;font:15px sans-serif;margin-top:6px">รหัส PIN เข้าโปรแกรม</div>'
         f'<div style="text-align:center;font:700 34px monospace;letter-spacing:.3em">{pin}</div>')
display(HTML(html))
print(f"   รหัส PIN: {pin}", flush=True)
print("\n✅ พร้อมใช้งาน — เปิดหน้านี้ค้างไว้ระหว่างใช้ (กดปุ่ม ■ หยุดเซลล์นี้เมื่อเลิกใช้)")

# วนรอไว้เพื่อให้ Colab รู้ว่ายังใช้งานอยู่ และแจ้งถ้าโปรแกรมล่ม
try:
    while True:
        time.sleep(60)
        if not wait_url("http://127.0.0.1:8000/api/config", 5):
            print("⚠️ โปรแกรมหยุดทำงาน:\n" + open("/content/app.log").read()[-2000:]); break
except KeyboardInterrupt:
    subprocess.run("pkill -f 'python app.py'; pkill -f cloudflared; pkill -f 'ollama serve'", shell=True)
    print("ปิดโปรแกรมแล้ว")
