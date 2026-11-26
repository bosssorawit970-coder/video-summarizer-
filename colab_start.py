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
for w in ("Bold", "SemiBold", "Black"):
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
step("   การ์ดจอ: " + ("มี ✓ (ถอดเสียงเร็ว)" if gpu else "ไม่มี ⚠️"))
if not gpu:
    step("   ⚠️ ไม่มีการ์ดจอ: ทุกอย่างจะช้าลงมาก · AI วาดภาพไม่ได้ (ใช้ภาพถ่ายจริงจากคลังภาพฟรี / รูปของคุณแทน)")
    step("      ใช้ AI รุ่นเล็กให้อัตโนมัติ เพื่อไม่ให้ RAM เต็มจนเครื่องค้าง · ถ้ามีคีย์ Claude ใช้ Claude จะดีและเร็วกว่า")

env = os.environ.copy()
env["HOST"], env["PORT"] = "127.0.0.1", "8000"
key = ANTHROPIC_API_KEY.strip()
if not key:
    try:
        from google.colab import userdata
        key = userdata.get("ANTHROPIC_API_KEY") or ""
    except Exception:
        key = ""
# คีย์ Gemini (ฟรี): วางในช่อง ANTHROPIC_API_KEY ได้เลย หรือเก็บใน Secrets ชื่อ GEMINI_API_KEY
# คีย์ Gemini มี 2 แบบ: AIza… (แบบเก่า) และ AQ.… (แบบใหม่) — คีย์ Claude ขึ้นต้น sk-ant- เสมอ
key = "".join(key.split()).strip("\"'")  # ตัดช่องว่าง/ขึ้นบรรทัด/เครื่องหมายคำพูดที่ติดมาตอนวาง
gem = ""
if key and not key.startswith("sk-ant"):
    gem, key = key, ""
try:
    from google.colab import userdata
    gem = gem or "".join((userdata.get("GEMINI_API_KEY") or "").split())
except Exception:
    pass
if gem:
    env["GEMINI_API_KEY"] = gem
    # ทดสอบคีย์จริงก่อน จะได้รู้ตั้งแต่ตอนนี้ว่าใช้ได้ไหม
    import urllib.request as _ur, urllib.error as _ue
    try:
        _ur.urlopen(_ur.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1",
                                headers={"x-goog-api-key": gem}), timeout=20).read()
        step(f"   ใช้ Gemini ได้ ✓ (คีย์ {gem[:4]}…{gem[-4:]}) — เลือก \"Gemini\" ในหน้าโปรแกรม")
    except _ue.HTTPError as e:
        why = e.read().decode("utf-8", "replace")[:200]
        step(f"   ⚠️ คีย์ Gemini ใช้ไม่ได้ ({e.code}): {why}")
        step("      ลองกด Create API key ใหม่ใน aistudio.google.com แล้ววางใหม่ (คัดลอกด้วยปุ่ม Copy key)")
    except Exception as e:
        step(f"   ใส่คีย์ Gemini แล้ว (ทดสอบไม่ได้ตอนนี้: {e})")
if key:
    env["ANTHROPIC_API_KEY"] = key
elif AI == "claude" and not gem:
    step("   ⚠️ ยังไม่ได้ใส่คีย์ Claude — จะใช้โหมดเขียนบทเอง")

pex = PEXELS_API_KEY.strip()
if not pex:
    try:
        from google.colab import userdata
        pex = userdata.get("PEXELS_API_KEY") or ""
    except Exception:
        pex = ""
if pex:
    env["PEXELS_API_KEY"] = pex  # ใส่คีย์ Pixabay ในช่องนี้ก็ได้ (โปรแกรมแยกให้เอง)
try:
    from google.colab import userdata
    pix = userdata.get("PIXABAY_API_KEY") or ""
except Exception:
    pix = ""
if pix:
    env["PIXABAY_API_KEY"] = pix
# คีย์ ElevenLabs (ไม่บังคับ): ใส่ใน 🔑 Secrets ชื่อ ELEVENLABS_API_KEY หรือกดปุ่ม 🎤 ElevenLabs ในหน้าโปรแกรม
el = "".join(str(globals().get("ELEVENLABS_API_KEY", "") or "").split())
if not el:
    try:
        from google.colab import userdata
        el = "".join((userdata.get("ELEVENLABS_API_KEY") or "").split())
    except Exception:
        el = ""
if el:
    env["ELEVENLABS_API_KEY"] = el
    step(f"   ใส่คีย์ ElevenLabs แล้ว ✓ ({el[:5]}…{el[-4:]})")
pin = APP_PIN.strip()
if not pin:  # สุ่ม PIN 6 หลัก (ใช้ค่าเดิมถ้ารันซ้ำในรอบเดียวกัน)
    pin = open("/content/.pin").read().strip() if os.path.exists("/content/.pin") else f"{random.randint(0, 999999):06d}"
    open("/content/.pin", "w").write(pin)
env["APP_PIN"] = pin

if SAVE_TO_DRIVE:
    try:
        from google.colab import drive
        if not os.path.isdir("/content/drive/MyDrive"):  # รันเซลล์ซ้ำ → เชื่อมไว้แล้ว ไม่ต้องขออนุญาตใหม่
            try:
                drive.mount("/content/drive")
            except Exception:  # เชื่อมค้างครึ่งๆ / โฟลเดอร์ไม่ว่าง → ล้างแล้วลองอีกครั้ง
                drive.mount("/content/drive", force_remount=True)
        env["JOBS_DIR"] = "/content/drive/MyDrive/สรุปคลิป"
        step("   เก็บงานไว้ใน Google Drive โฟลเดอร์ \"สรุปคลิป\" ✓")
    except Exception as e:
        step(f"   ⚠️ เชื่อม Google Drive ไม่สำเร็จ ({e}) — ทำงานต่อโดยเก็บไฟล์ในเครื่อง Colab ชั่วคราวแทน")
        step("      วิธีแก้: รันเซลล์ใหม่ → หน้าต่างเด้ง กด \"เชื่อมต่อกับ Google ไดรฟ์\" → เลือกบัญชี")
        step("      → ติ๊ก \"เลือกทั้งหมด\" ให้ครบทุกช่อง → ดำเนินการต่อ (ทำภายใน 1-2 นาที)")

if AI == "ollama" and gem:
    step("2/4 มีคีย์ Gemini แล้ว — ข้ามการโหลด Ollama (ประหยัดเวลาและการ์ดจอ)")
elif AI == "ollama":
    step("2/4 ติดตั้ง Ollama และโหลดโมเดล AI (ครั้งแรก 2–5 นาที)…")
    if subprocess.run("which ollama", shell=True, capture_output=True).returncode != 0:
        subprocess.run("apt-get install -y -qq zstd > /dev/null; curl -fsSL https://ollama.com/install.sh | sh > /dev/null",
                       shell=True)
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if wait_url("http://127.0.0.1:11434/api/tags", 60):
        # มีการ์ดจอ → รุ่น 14B เข้าใจภาษาไทยและคิดภาพได้ตรงกว่า 7B มาก (โหลดเพิ่ม ~9 GB)
        # ไม่มีการ์ดจอ → รุ่น 3B (เบา ~2 GB เร็วกว่า ไม่ทำให้ RAM เต็ม)
        om = globals().get("OLLAMA_MODEL") or ("qwen2.5:14b" if gpu else "qwen2.5:3b")
        step(f"   โมเดล: {om}")
        r = subprocess.run(["ollama", "pull", om], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if r.returncode != 0 and om == "qwen2.5:14b":
            step("   ⚠️ โหลดรุ่นใหญ่ไม่สำเร็จ ใช้ qwen2.5:7b แทน")
            om = "qwen2.5:7b"
            subprocess.run(["ollama", "pull", om], stdout=subprocess.DEVNULL)
        env["OLLAMA_MODEL"] = om
    else:
        step("   ⚠️ เปิด Ollama ไม่สำเร็จ — จะใช้โหมดเขียนบทเอง")
else:
    step("2/4 ข้ามการติดตั้ง Ollama")

step("3/4 เปิดโปรแกรม…")
def _start_app(mode="w"):
    lg = open("/content/app.log", mode)
    return subprocess.Popen([sys.executable, "app.py"], cwd=APP, env=env, stdout=lg, stderr=subprocess.STDOUT)


app_proc = _start_app()
if not wait_url("http://127.0.0.1:8000/api/config", 60):
    print(open("/content/app.log").read()); raise SystemExit("โปรแกรมเปิดไม่สำเร็จ ดูข้อความด้านบน")

step("4/4 สร้างลิงก์…")
# ลิงก์สำรอง (Cloudflare) ทำก่อน — ไม่ต้องรอหน้าเว็บ Colab ตอบ ใช้ได้แม้จอดับ/สลับแอป
backup = ""
cf_proc = None
if BACKUP_LINK:
    try:
        if not os.path.exists("/content/cloudflared"):
            urllib.request.urlretrieve("https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
                                       "/content/cloudflared")
            os.chmod("/content/cloudflared", 0o755)
        cf = open("/content/cloudflared.log", "w")
        cf_proc = subprocess.Popen(["/content/cloudflared", "tunnel", "--url", "http://127.0.0.1:8000", "--no-autoupdate"],
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

# วนรอไว้ + ปิด Colab อัตโนมัติเมื่อไม่มีคนใช้ (ประหยัดโควตาการ์ดจอฟรี)
# มีการ์ดจอ → ปิดเองเมื่อไม่มีคนใช้ 60 นาที (ประหยัดโควตา GPU) · ไม่มีการ์ดจอ (CPU) → ไม่ปิดเอง
_gpu = subprocess.run("nvidia-smi -L", shell=True, capture_output=True).returncode == 0
AUTO_STOP_MIN = float(globals().get("AUTO_STOP_MIN", 60 if _gpu else 0) or 0)   # 0 = ไม่ปิดเอง
CHECK_EVERY = int(globals().get("CHECK_EVERY", 60))
if AUTO_STOP_MIN:
    print(f"⏱ ถ้าปิด/ย่อหน้าโปรแกรมไว้ {AUTO_STOP_MIN:g} นาที (และไม่มีงานค้าง) จะปิด Colab ให้อัตโนมัติ เพื่อประหยัดโควตาการ์ดจอ", flush=True)
    print("   เปิดหน้าโปรแกรมค้างไว้บนจอ = ไม่ปิด · ไม่อยากให้ปิดเลย: เพิ่มบรรทัด AUTO_STOP_MIN = 0 ในช่องตั้งค่า", flush=True)
    if not SAVE_TO_DRIVE:
        print("   ไฟล์งานอยู่ในเครื่อง Colab ชั่วคราว — ดาวน์โหลดวิดีโอเก็บไว้ก่อนเลิกใช้", flush=True)


def _stop_all():
    subprocess.run("pkill -f 'python app.py'; pkill -f cloudflared; pkill -f 'ollama serve'", shell=True)


def _new_tunnel():
    """ลิงก์สำรองหลุด (Cloudflare ตัดเป็นพักๆ) → เปิดลิงก์ใหม่"""
    global cf_proc
    try:
        cf = open("/content/cloudflared.log", "w")
        cf_proc = subprocess.Popen(["/content/cloudflared", "tunnel", "--url", "http://127.0.0.1:8000", "--no-autoupdate"],
                                   stdout=cf, stderr=cf)
        for _ in range(40):
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", open("/content/cloudflared.log").read())
            if m:
                display(HTML(f'<a href="{m.group(0)}" target="_blank" style="{btn};background:#d9480f;color:#fff">'
                             '▶ ลิงก์สำรองใหม่ (อันเดิมหลุด)</a>'))
                print(f"🔗 ลิงก์สำรองหลุด — ลิงก์ใหม่: {m.group(0)}  (PIN เดิม)", flush=True)
                return
            time.sleep(1)
    except Exception as e:
        print("เปิดลิงก์สำรองใหม่ไม่ได้:", e)


restarts = 0
try:
    while True:
        time.sleep(CHECK_EVERY)
        if app_proc.poll() is not None:  # โปรแกรมพังจริง (ไม่ใช่แค่ยุ่ง) → เปิดใหม่ให้เอง
            tail = open("/content/app.log", errors="replace").read()[-1500:]
            mem = subprocess.run("free -m | head -2", shell=True, capture_output=True, text=True).stdout
            print(f"⚠️ โปรแกรมหยุดทำงาน (รหัส {app_proc.returncode}) ข้อความล่าสุด:\n{tail}\n{mem}", flush=True)
            if app_proc.returncode in (-9, 137):
                print("   น่าจะเป็นเพราะหน่วยความจำ (RAM) เต็ม — ปิดตัวเลือก AI ภาพเคลื่อนไหว/AI วาดภาพในเครื่องจะช่วยได้", flush=True)
            if restarts >= 5:
                print("   พังซ้ำหลายครั้ง — หยุดเปิดใหม่แล้ว แคปข้อความนี้ไปให้ดูได้", flush=True)
                break
            restarts += 1
            app_proc = _start_app("a")
            if wait_url("http://127.0.0.1:8000/api/config", 90):
                print(f"🔄 เปิดโปรแกรมใหม่ให้แล้ว (ครั้งที่ {restarts}) — ลิงก์และ PIN เดิม รีเฟรชหน้าโปรแกรม · งานที่ค้างกด 🔁 ลองใหม่", flush=True)
            continue
        if cf_proc is not None and cf_proc.poll() is not None:
            _new_tunnel()
        try:
            import json as _json
            st = _json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/idle", timeout=20).read())
        except Exception:
            continue  # ยุ่งอยู่ (กำลังทำคลิป) ตอบช้า ≠ พัง — รอบหน้าค่อยถามใหม่
        if AUTO_STOP_MIN and not st.get("busy") and st.get("idle_seconds", 0) >= AUTO_STOP_MIN * 60:
            print(f"💤 ไม่มีการใช้งาน {AUTO_STOP_MIN:g} นาที (หน้าโปรแกรมไม่ได้เปิดบนจอ) — ปิดโปรแกรมและคืนเครื่อง Colab แล้ว", flush=True)
            print("   ใช้ครั้งหน้า: กด เรียกใช้ทุกเซลล์ ใหม่ได้เลย", flush=True)
            _stop_all()
            try:
                from google.colab import runtime
                runtime.unassign()  # คืนเครื่อง = หยุดนับโควตาการ์ดจอ
            except Exception as e:
                print("   (คืนเครื่องเองไม่ได้ — ไปที่ รันไทม์ → ยกเลิกการเชื่อมต่อและลบรันไทม์)", e)
            break
except KeyboardInterrupt:
    _stop_all()
    print("ปิดโปรแกรมแล้ว")
