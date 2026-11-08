"""
แกนประมวลผลของโปรแกรมสรุปคลิป
  1) ถอดเสียง   : faster-whisper
  2) สรุป/เลือกไฮไลต์ + เขียนบทพากย์ : Claude API / Ollama (ฟรี, ในเครื่อง) / ไม่ใช้ AI
  3) สร้างเสียงพากย์ : edge-tts (เสียงไทยของ Microsoft, ฟรี)
  4) ตัดต่อ     : ffmpeg (ตัดช่วง, ลดเสียงต้นฉบับ, ใส่เสียงพากย์, ซับไตเติล, เฟด, ต่อคลิป)
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Callable

Progress = Callable[[float, str], None]  # (0-100, ข้อความ)

THAI_VOICES = [
    {"id": "th-TH-PremwadeeNeural", "name": "เปรมวดี (หญิง)"},
    {"id": "th-TH-NiwatNeural", "name": "นิวัฒน์ (ชาย)"},
    {"id": "th-TH-AcharaNeural", "name": "อัจฉรา (หญิง)"},
]

DEFAULT_CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL") or "claude-sonnet-5-5"
DEFAULT_OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL") or "qwen2.5:7b"
OLLAMA_URL = os.environ.get("OLLAMA_URL") or "http://localhost:11434"


# ───────────────────────── ffmpeg helpers ─────────────────────────

def run(cmd: list[str], cwd: str | Path | None = None) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if p.returncode != 0:
        tail = "\n".join(p.stderr.strip().splitlines()[-15:])
        raise RuntimeError(f"คำสั่ง {cmd[0]} ล้มเหลว:\n{tail}")
    return p.stdout


def probe(path: str | Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_entries",
               "format=duration:stream=codec_type,codec_name,width,height,pix_fmt",
               "-of", "json", str(path)])
    data = json.loads(out)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    return {
        "duration": float(data.get("format", {}).get("duration") or 0),
        "has_video": v is not None,
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "width": (v or {}).get("width"),
        "height": (v or {}).get("height"),
        "vcodec": (v or {}).get("codec_name"),
        "pix_fmt": (v or {}).get("pix_fmt"),
        "acodec": next((x.get("codec_name") for x in streams if x.get("codec_type") == "audio"), None),
    }


def download_url(url: str, outdir: Path, progress: Progress) -> tuple[Path, str]:
    """ดาวน์โหลดวิดีโอจากลิงก์ (YouTube, TikTok, Facebook, IG, X ฯลฯ) ด้วย yt-dlp"""
    import yt_dlp

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total:
                progress(min(99, done / total * 100),
                         f"กำลังดาวน์โหลดวิดีโอ {done / 1048576:.0f}/{total / 1048576:.0f} MB")
        elif d.get("status") == "finished":
            progress(99, "ดาวน์โหลดเสร็จ กำลังรวมไฟล์")

    opts = {
        "outtmpl": str(outdir / "source.%(ext)s"),
        # ไม่เกิน 720p พอสำหรับคลิปสรุป และโหลดเร็ว
        "format": "bv*[height<=720]+ba/b[height<=720]/bv*+ba/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True, "no_warnings": True, "noprogress": True,
        "progress_hooks": [hook],
        "retries": 5, "fragment_retries": 5,
        # YouTube ต้องใช้ตัวรัน JavaScript (deno หรือ node) — yt-dlp ข้ามเองถ้าไม่มี
        "js_runtimes": {"deno": {}, "node": {}},
    }
    cookies = os.environ.get("YTDLP_COOKIES")
    if cookies and Path(cookies).exists():
        opts["cookiefile"] = cookies
    progress(0, "กำลังอ่านข้อมูลจากลิงก์")
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get("_type") == "playlist":
                entries = [x for x in (info.get("entries") or []) if x]
                if not entries:
                    raise RuntimeError("ลิงก์นี้เป็นเพลย์ลิสต์ที่ไม่มีคลิปให้ดาวน์โหลด")
                info = ydl.extract_info(entries[0].get("webpage_url") or entries[0]["url"],
                                        download=False)
            if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
                raise RuntimeError("ลิงก์นี้เป็นไลฟ์สดที่ยังไม่จบ — รอให้ไลฟ์จบแล้วใช้ลิงก์ย้อนหลัง "
                                   "(หรือตัดเฉพาะช่วงที่ต้องการแล้วอัปโหลดไฟล์)")
            dur = float(info.get("duration") or 0)
            if dur > MAX_SECONDS:
                raise RuntimeError(f"คลิปยาว {fmt_time(dur)} — เกินที่รองรับ "
                                   f"({MAX_SECONDS // 3600} ชั่วโมง) ใช้คลิปที่สั้นลง")
            if dur:
                progress(1, f"พบคลิปยาว {fmt_time(dur)} — เริ่มดาวน์โหลด")
            info = ydl.process_ie_result(info, download=True)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(_explain_download_error(error_text(e))) from e
    files = sorted(outdir.glob("source.*"), key=lambda f: f.stat().st_size, reverse=True)
    files = [f for f in files if f.suffix not in (".part", ".ytdl", ".json")]
    if not files:
        raise RuntimeError("ดาวน์โหลดไม่สำเร็จ ไม่พบไฟล์วิดีโอ")
    return files[0], str(info.get("title") or "วิดีโอจากลิงก์")


MAX_SECONDS = int(os.environ.get("MAX_SECONDS") or 3 * 3600)


def error_text(e: BaseException) -> str:
    """ข้อความ error ที่ไม่ว่างเปล่าเสมอ"""
    msg = str(e).strip()
    return msg if msg else f"{type(e).__name__} (ไม่มีข้อความจากระบบ)"


def _explain_download_error(msg: str) -> str:
    m = msg.lower()
    if "sign in to confirm" in m or "not a bot" in m:
        why = "YouTube บล็อกการดาวน์โหลดจากเซิร์ฟเวอร์นี้ชั่วคราว ลองใหม่ภายหลัง หรือดาวน์โหลดคลิปลงมือถือแล้วอัปโหลดไฟล์แทน"
    elif "private" in m or "login" in m or "log in" in m or "cookies" in m:
        why = "คลิปนี้ต้องล็อกอินหรือเป็นคลิปส่วนตัว ใช้ได้เฉพาะคลิปสาธารณะ"
    elif "unsupported url" in m:
        why = "ยังไม่รองรับลิงก์จากเว็บนี้ ตรวจว่าคัดลอกลิงก์ของคลิปมาครบ"
    elif "unavailable" in m or "removed" in m or "not available" in m:
        why = "คลิปนี้ถูกลบ ไม่เปิดให้ดูในประเทศนี้ หรือเปิดไม่ได้"
    elif "ffmpeg" in m:
        why = "ต้องติดตั้ง ffmpeg ก่อน"
    else:
        why = "ดาวน์โหลดไม่สำเร็จ ลองใหม่ หรือดาวน์โหลดคลิปลงเครื่องแล้วอัปโหลดไฟล์แทน"
    detail = re.sub(r"\x1b\[[0-9;]*m", "", msg).replace("ERROR: ", "")[:300]
    return f"{why}\n(รายละเอียด: {detail})"


def needs_preview(info: dict) -> bool:
    """ไฟล์ H.264 ขนาดไม่ใหญ่ เบราว์เซอร์มือถือเปิดได้เลย ไม่ต้องแปลง"""
    small = (info.get("height") or 9999) <= 1080 and (info.get("width") or 9999) <= 1920
    ok_audio = info.get("acodec") in (None, "aac", "mp3")
    return not (info.get("vcodec") == "h264" and info.get("pix_fmt") == "yuv420p"
                and small and ok_audio)


_nvenc: bool | None = None


def _has_nvenc() -> bool:
    global _nvenc
    if _nvenc is None:
        try:
            enc = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                                 capture_output=True, text=True).stdout
            _nvenc = "h264_nvenc" in enc and has_gpu()
        except Exception:
            _nvenc = False
    return _nvenc


def ffmpeg_progress(cmd: list[str], duration: float, progress: Progress | None) -> None:
    """รัน ffmpeg พร้อมรายงานความคืบหน้า (%)"""
    p = subprocess.Popen(cmd[:1] + ["-progress", "pipe:1", "-nostats"] + cmd[1:],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         encoding="utf-8", errors="replace")
    last = 0.0
    for line in p.stdout:
        if line.startswith("out_time_us=") and duration > 0 and progress:
            try:
                t = int(line.split("=", 1)[1]) / 1e6
            except ValueError:
                continue
            if t - last >= 2:
                last = t
                progress(min(99, t / duration * 100), "")
    err = p.stderr.read()
    if p.wait() != 0:
        tail = "\n".join(err.strip().splitlines()[-15:])
        raise RuntimeError(f"คำสั่ง ffmpeg ล้มเหลว:\n{tail}")


def make_preview(video: Path, out: Path, duration: float = 0,
                 progress: Progress | None = None) -> None:
    """วิดีโอตัวอย่างขนาดเล็ก (H.264 360p) ให้เปิดดูบนมือถือได้ทุกรุ่นและโหลดเร็ว"""
    vf = "scale=-2:'min(360,ih)':force_divisible_by=2,fps=24,format=yuv420p"
    tail = ["-c:a", "aac", "-b:a", "64k", "-ac", "2", "-movflags", "+faststart", str(out)]
    if _has_nvenc():  # การ์ดจอ Colab แปลงวิดีโอได้เร็วกว่า CPU หลายเท่า
        try:
            ffmpeg_progress(["ffmpeg", "-y", "-hide_banner", "-hwaccel", "cuda", "-i", str(video), "-vf", vf,
                             "-c:v", "h264_nvenc", "-preset", "p1", "-cq", "32", *tail],
                            duration, progress)
            return
        except RuntimeError as e:
            print("แปลงด้วยการ์ดจอไม่ได้ ใช้ CPU แทน:", e)
    ffmpeg_progress(["ffmpeg", "-y", "-hide_banner", "-threads", "0", "-i", str(video),
                     "-vf", vf, "-c:v", "libx264", "-preset", "ultrafast", "-tune", "fastdecode",
                     "-crf", "32", *tail], duration, progress)


def load_wav(wav: Path):
    """อ่าน WAV 16kHz mono 16-bit (ที่ extract_audio สร้าง) เป็น float32 array"""
    import wave
    import numpy as np
    with wave.open(str(wav), "rb") as w:
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def extract_audio(video: Path, wav: Path) -> None:
    run(["ffmpeg", "-y", "-hide_banner", "-i", str(video), "-vn",
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])


# ───────────────────────── 1) ถอดเสียง ─────────────────────────

_whisper_cache: dict = {}


def has_gpu() -> bool:
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


def _load_whisper(name: str, force_cpu: bool = False):
    key = (name, force_cpu)
    if key in _whisper_cache:
        return _whisper_cache[key]
    from faster_whisper import WhisperModel
    if has_gpu() and not force_cpu:
        model = WhisperModel(name, device="cuda", compute_type="float16")
    else:
        model = WhisperModel(name, device="cpu", compute_type="int8")
    _whisper_cache[key] = model
    return model


def transcribe(wav: Path, model_name: str, duration: float,
               progress: Progress) -> list[dict]:
    progress(0, f"กำลังโหลดโมเดลถอดเสียง ({model_name}) — ครั้งแรกจะดาวน์โหลดนานหน่อย")
    try:
        return _transcribe(_load_whisper(model_name), wav, duration, progress)
    except Exception as e:
        if not has_gpu():
            raise
        # ไลบรารี CUDA/cuDNN ไม่ตรงรุ่น → ถอดเสียงด้วย CPU แทน (ช้ากว่าแต่ใช้ได้)
        print("GPU ใช้ไม่ได้ เปลี่ยนเป็น CPU:", e)
        progress(0, "การ์ดจอใช้ไม่ได้ กำลังถอดเสียงด้วย CPU (ช้ากว่า)")
        return _transcribe(_load_whisper(model_name, force_cpu=True), wav, duration, progress)


def _transcribe(model, wav: Path, duration: float, progress: Progress) -> list[dict]:
    # ส่งเสียงเป็น array เอง ไม่ให้ faster-whisper ถอดไฟล์ผ่าน PyAV
    # (PyAV รุ่นใหม่ไม่รองรับ metadata_errors จนเกิด error)
    segments, _ = model.transcribe(load_wav(wav), language="th", vad_filter=True,
                                   beam_size=5)
    out = []
    for s in segments:
        text = s.text.strip()
        if text:
            out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": text})
        if duration > 0:
            progress(min(99, s.end / duration * 100),
                     f"ถอดเสียงแล้ว {fmt_time(s.end)} / {fmt_time(duration)}")
    return out


# ───────────────────────── 2) สรุป + เลือกไฮไลต์ ─────────────────────────

PLAN_PROMPT = """คุณเป็นบรรณาธิการวิดีโอมืออาชีพ ด้านล่างคือคำถอดเสียงของคลิปวิดีโอภาษาไทย แบ่งเป็นท่อน มีหมายเลขและเวลา (วินาที)

งานของคุณ:
1. ตั้งชื่อเรื่องสั้นๆ และเขียนสรุปเนื้อหาทั้งคลิป 3-5 ประโยค
2. เลือกช่วงไฮไลต์ที่สำคัญที่สุด เรียงตามเวลา ไม่ทับกัน รวมความยาวประมาณ {target} วินาที (แต่ละช่วงยาว 5-20 วินาที)
3. เขียนบทพากย์ภาษาไทยสำหรับแต่ละช่วง เป็นภาษาพูดที่เป็นธรรมชาติ เล่าเรื่องต่อเนื่องกันเมื่ออ่านเรียงกัน
   ความยาวบทพากย์ต้องอ่านจบทันในช่วงนั้น (ประมาณ 10-12 ตัวอักษรต่อวินาที) ห้ามใส่อีโมจิหรือสัญลักษณ์

ตอบเป็น JSON อย่างเดียว ไม่ต้องมีคำอธิบายอื่น ตามรูปแบบ:
{{"title": "...", "summary": "...", "clips": [{{"start_seg": 3, "end_seg": 5, "narration": "..."}}]}}
start_seg และ end_seg คือหมายเลขท่อนแรกและท่อนสุดท้ายของช่วงนั้น (รวมทั้งสองท่อน)

คำถอดเสียง:
{transcript}"""


def _transcript_block(segs: list[dict]) -> str:
    return "\n".join(f"[{i}] {s['start']:.1f}-{s['end']:.1f}: {s['text']}"
                     for i, s in enumerate(segs))


def merge_segments(segs: list[dict], limit: int) -> list[dict]:
    """คลิปยาวมีท่อนเยอะเกินที่ AI รับไหว → รวมท่อนที่ติดกันให้เหลือไม่เกิน limit"""
    if len(segs) <= limit:
        return segs
    size = -(-len(segs) // limit)  # ปัดขึ้น
    out = []
    for i in range(0, len(segs), size):
        g = segs[i:i + size]
        text = " ".join(x["text"] for x in g)
        out.append({"start": g[0]["start"], "end": g[-1]["end"], "text": text[:300]})
    return out


def _parse_json(text: str) -> dict:
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < 0:
        raise ValueError("AI ไม่ได้ตอบกลับเป็น JSON")
    return json.loads(text[a:b + 1])


# รุ่นสำรอง (ถ้าถามรายชื่อรุ่นจาก Google ไม่ได้) — รุ่น 2.5 ถูกปิดไปแล้ว (16 ต.ค. 2026)
GEMINI_FALLBACK = ["gemini-3-flash", "gemini-3-flash-preview", "gemini-3.1-flash", "gemini-3.1-flash-lite",
                   "gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
_gemini_list: list[dict] | None = None
_gemini_dead: set[str] = set()  # รุ่นที่ตอบ 404 แล้ว ไม่ต้องลองซ้ำ


def gemini_model_list() -> list[dict]:
    """รายชื่อรุ่น Gemini ที่คีย์นี้ใช้ได้จริง (ถาม Google ครั้งเดียวแล้วจำไว้)"""
    global _gemini_list
    if _gemini_list is not None:
        return _gemini_list
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    out, token = [], ""
    try:
        for _ in range(5):
            url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200" + \
                  (f"&pageToken={token}" if token else "")
            req = urllib.request.Request(url, headers={"x-goog-api-key": key})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read())
            out += data.get("models") or []
            token = data.get("nextPageToken") or ""
            if not token:
                break
    except Exception as e:
        print("ถามรายชื่อรุ่น Gemini ไม่ได้ (ใช้รายชื่อสำรอง):", e)
        return []  # ไม่จำ → ครั้งหน้าลองถามใหม่
    _gemini_list = out
    return out


def _gem_version(name: str) -> float:
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def gemini_models(kind: str = "text") -> list[str]:
    """เรียงรุ่นที่ควรลอง: kind="text" = flash รุ่นใหม่สุด (เสถียรก่อน preview) แล้วค่อย flash-lite · "tts" = รุ่นพากย์เสียง"""
    names = []
    for m in gemini_model_list():
        name = str(m.get("name", "")).split("/")[-1]
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue
        if kind == "tts":
            if "tts" in name:
                names.append(name)
        elif "flash" in name and not re.search(r"tts|image|live|audio|embed|thinking|exp|robotics|computer", name):
            names.append(name)
    if kind == "tts":
        names.sort(key=lambda n: (-_gem_version(n), "preview" in n, n))
        env = os.environ.get("GEMINI_TTS_MODEL")
        fallback = ["gemini-3.8-flash-tts", "gemini-3.1-flash-tts", "gemini-3-flash-tts", "gemini-2.5-flash-preview-tts"]
    else:
        names.sort(key=lambda n: ("lite" in n, -_gem_version(n), "preview" in n, bool(re.search(r"-\d{2,3}$", n)), n))
        env = os.environ.get("GEMINI_MODEL")
        fallback = GEMINI_FALLBACK
    order = ([env] if env else []) + names[:5] + ([] if names else fallback)
    return [m for m in dict.fromkeys(order) if m not in _gemini_dead]


def __getattr__(name):  # โค้ดเก่าที่อ้าง P.GEMINI_MODELS
    if name == "GEMINI_MODELS":
        return gemini_models()
    raise AttributeError(name)


def _ask_gemini(prompt: str, extra_parts: list | None = None) -> str:
    """Google Gemini (มีโควตาฟรี) — ขอคีย์ได้ที่ aistudio.google.com
    extra_parts: ส่วนเพิ่ม เช่น รูปภาพ {"inline_data": {"mime_type": "image/jpeg", "data": base64}}"""
    import urllib.error
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    body = json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}, *(extra_parts or [])]}],
                       "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json"}}).encode()
    last, tried = None, []
    for model in gemini_models() or GEMINI_FALLBACK:
        try:
            data = _gemini_post(model, body, key)
        except urllib.error.HTTPError as e:
            msg = getattr(e, "_msg_text", "") or e.read().decode("utf-8", "replace")[:300]
            if e.code in (500, 502, 503, 504):  # เซิร์ฟเวอร์ Google คนใช้เยอะชั่วคราว (ลองซ้ำแล้ว) → ลองรุ่นถัดไป
                tried.append(f"{model}: คนใช้เยอะ")
                last = "เซิร์ฟเวอร์ Gemini คนใช้เยอะชั่วคราว ลองใหม่อีกสักครู่ (" + ", ".join(tried[-3:]) + ")"
                continue
            if e.code == 404:  # รุ่นนี้ไม่มี/เลิกใช้ → ลองรุ่นถัดไป
                _gemini_dead.add(model)
                tried.append(f"{model}: ไม่มีรุ่นนี้แล้ว")
                last = "ไม่พบรุ่น Gemini ที่ใช้ได้ (" + "; ".join(tried[-3:]) + ")"
                continue
            if e.code == 429:
                tried.append(f"{model}: โควตาเต็ม")
                last = "โควตา Gemini ฟรีเต็มแล้ว ลองใหม่ภายหลัง (" + ", ".join(tried[-3:]) + ")"
                continue  # รุ่นเล็กกว่าอาจยังมีโควตา
            if e.code in (400, 401, 403) and ("API key" in msg or "API_KEY" in msg or e.code != 400):
                raise RuntimeError("คีย์ Gemini ไม่ถูกต้อง หรือยังใช้ในพื้นที่นี้ไม่ได้") from e
            raise RuntimeError(f"Gemini ตอบกลับผิดพลาด ({e.code}): {msg}") from e
        parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts)
        if text:
            return text
        last = "Gemini ไม่ตอบ (อาจถูกระบบกรองเนื้อหา)"
        tried.append(f"{model}: ไม่ตอบ")
    raise RuntimeError(last or "เรียก Gemini ไม่สำเร็จ")


def _gemini_post(model: str, body: bytes, key: str) -> dict:
    """เรียก Gemini 1 รุ่น — ถ้าเซิร์ฟเวอร์ยุ่ง (503/500) รอแล้วลองซ้ำ 3 ครั้ง (5, 12, 25 วิ)"""
    import time as _t
    import urllib.error
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    for wait in (5, 12, 25, None):
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json",
                                                              "x-goog-api-key": key})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (500, 502, 503, 504) and wait:
                print(f"Gemini {model} ยุ่ง ({e.code}) รอ {wait} วิแล้วลองใหม่")
                _t.sleep(wait)
                continue
            text = e.read().decode("utf-8", "replace")
            try:
                text = json.loads(text)["error"]["message"]
            except Exception:
                pass
            e._msg_text = text[:300]
            raise
    raise RuntimeError("unreachable")


def ask_ai(provider: str, prompt: str) -> str:
    """ส่งคำสั่งให้ AI ที่เลือก: claude / gemini / ollama"""
    if provider == "claude":
        return _ask_claude(prompt)
    if provider == "gemini":
        return _ask_gemini(prompt)
    return _ask_ollama(prompt)


POST_TAGS = {
    "game": ["#MLBB", "#MobileLegends", "#ไฮไลต์เกม", "#เกมมือถือ", "#fyp"],
    "story": ["#เรื่องเล่า", "#fyp", "#tiktokไทย"],
    "talk": ["#สรุปให้", "#สาระ", "#fyp", "#tiktokไทย"],
}


def make_post(plan: dict, mode: str, provider: str, note: str = "") -> dict:
    """แคปชัน + แฮชแท็กสำหรับโพสต์ TikTok/Reels"""
    post = _make_post(plan, mode, provider, note)
    src = plan.get("source") or {}
    if src.get("site"):  # ให้เครดิตต้นทาง (เนื้อหาแปล/เรียบเรียงจากโพสต์/ข่าว)
        post["caption"] = post["caption"].rstrip() + f"\n📌 ที่มา: {src['site']}"
        if post.get("youtube"):
            yt = post["youtube"]
            body, _, tags = yt["description"].rpartition("\n\n")
            yt["description"] = f"{body or yt['description']}\n📌 ที่มา: {src['site']} {src.get('url', '')}".strip() + \
                (f"\n\n{tags}" if body else "")
    return post


def _make_post(plan: dict, mode: str, provider: str, note: str = "") -> dict:
    title = (plan.get("title") or "").strip()
    summary = (plan.get("summary") or "").strip()
    items = plan.get("clips") or plan.get("scenes") or []
    lines = "\n".join(f"- {(c.get('label') or c.get('headline') or '')} {c.get('narration', '')}".strip()
                      for c in items[:12])[:2500]
    if provider != "none":
        kind = {"game": "คลิปไฮไลต์เกม Mobile Legends (MLBB)", "story": "คลิปสั้นเล่าเรื่อง",
                "talk": "คลิปสรุปเนื้อหา"}.get(mode, "คลิปสั้น")
        prompt = f"""เขียนแคปชันโพสต์ TikTok ภาษาไทยสำหรับ{kind}นี้
ชื่อคลิป: {title}
สรุป: {summary}
{('ข้อมูลเพิ่ม: ' + note) if note else ''}
บทพากย์:
{lines}

กติกา:
- caption: 1-2 ประโยคสั้น เปิดด้วยฮุกที่ทำให้อยากดูจนจบ (คำถาม/ประโยคเร้าใจ) ใส่อีโมจิได้ 1-3 ตัว แล้วปิดด้วยชวนคอมเมนต์หรือกดติดตาม ไม่เกิน 150 ตัวอักษร ห้ามใส่แฮชแท็กในนี้
- hashtags: 5-8 อัน ผสมแท็กกว้าง (#fyp #tiktokไทย) กับแท็กเฉพาะเรื่อง ภาษาไทยหรืออังกฤษ ขึ้นต้นด้วย # ไม่มีช่องว่าง
- อย่าแต่งข้อมูลที่ไม่มีในบท

และเขียนสำหรับ YouTube Shorts ด้วย (คนดูค้นหาเจอจากชื่อ ต่างจาก TikTok):
- yt_title: ชื่อคลิปภาษาไทย ไม่เกิน 70 ตัวอักษร คำสำคัญที่คนจะค้นหาอยู่ต้นชื่อ ชวนสงสัยแต่ไม่หลอก อีโมจิได้ 1 ตัว ไม่ใส่แฮชแท็ก
- yt_description: 2-3 บรรทัด บรรทัดแรกสรุปว่าคลิปนี้เกี่ยวกับอะไร (มีคำค้นหาสำคัญ) บรรทัดถัดไปชวนกดไลก์/ติดตาม/คอมเมนต์ ห้ามใส่แฮชแท็กในนี้
- yt_hashtags: 3-5 อัน อันแรกเป็น #Shorts ที่เหลือเป็นแท็กเฉพาะเรื่อง
- yt_tags: คำค้นหา 8-15 คำ/วลี (ไทยและอังกฤษ) สำหรับช่อง "แท็ก" ใน YouTube Studio ไม่มี #
ตอบเป็น JSON เท่านั้น: {{"caption": "...", "hashtags": ["#...", "#..."],
 "yt_title": "...", "yt_description": "...", "yt_hashtags": ["#Shorts", "#..."], "yt_tags": ["...", "..."]}}"""
        try:
            data = _parse_json(ask_ai(provider, prompt))
            cap = clean_post(str(data.get("caption") or ""))
            tags = _tags(data.get("hashtags") or [])
            if cap:
                return {"caption": cap, "hashtags": tags or POST_TAGS.get(mode, POST_TAGS["talk"]), "ai": True,
                        "youtube": _youtube_post(data, title, summary, mode, tags)}
        except Exception as e:
            print("เขียนแคปชันด้วย AI ไม่ได้:", e)
    # ไม่มี AI: ใช้ชื่อ + ประโยคแรกของสรุป
    first = re.split(r"(?<=[.!?])\s|\n", re.sub(r"#\S+", "", summary).strip())[0][:120]
    cap = " ".join(x for x in [title, first if first != title else ""] if x) or "ดูให้จบ แล้วมาคุยกันในคอมเมนต์ 👇"
    found = re.findall(r"#[^\s#]+", summary)
    tags = _tags(found + POST_TAGS.get(mode, POST_TAGS["talk"]))
    return {"caption": cap + " 👇 ชอบกดติดตามด้วยนะ", "ai": False, "hashtags": tags,
            "youtube": _youtube_post({}, title, summary, mode, tags)}


YT_TAGS = {"game": ["MLBB", "Mobile Legends", "ไฮไลต์เกม", "เกมมือถือ", "MLBB ไทย"],
           "story": ["เรื่องเล่า", "เรื่องน่ารู้", "สาระ"], "talk": ["สรุป", "สาระ", "ความรู้"]}


def _youtube_post(data: dict, title: str, summary: str, mode: str, tk_tags: list[str]) -> dict:
    """ชื่อ + คำอธิบาย + แฮชแท็ก + แท็ก สำหรับ YouTube Shorts (ตรวจความยาวตามข้อจำกัดของ YouTube)"""
    yt_title = clean_post(str(data.get("yt_title") or "")) or clean_post(title) or "คลิปสั้นน่าดู"
    yt_title = re.sub(r"\s+", " ", yt_title).strip()[:95]  # YouTube รับไม่เกิน 100 ตัวอักษร
    desc = clean_post(str(data.get("yt_description") or "")).strip()
    if not desc:
        first = re.split(r"(?<=[.!?])\s|\n", re.sub(r"#\S+", "", summary).strip())[0][:150]
        desc = "\n".join(x for x in [first or yt_title, "ถ้าชอบ ฝากกดไลก์ กดติดตาม และคอมเมนต์บอกกันได้เลย 🙏"] if x)
    hashtags = _tags(data.get("yt_hashtags") or [])
    if not any(h.lower() == "#shorts" for h in hashtags):
        hashtags.insert(0, "#Shorts")
    for h in tk_tags:  # เติมแท็กเฉพาะเรื่องจาก TikTok (ข้ามแท็กเฉพาะ TikTok)
        if len(hashtags) >= 5:
            break
        if h.lower() not in {x.lower() for x in hashtags} and h.lower() not in ("#fyp", "#tiktokไทย", "#foryou"):
            hashtags.append(h)
    hashtags = hashtags[:5]
    raw = data.get("yt_tags") or []
    tags = [re.sub(r"[#<>,]", "", str(t)).strip() for t in (raw if isinstance(raw, list) else str(raw).split(","))]
    tags += [h.lstrip("#") for h in hashtags if h.lower() != "#shorts"] + YT_TAGS.get(mode, [])
    out, total = [], 0
    for t in dict.fromkeys(t for t in tags if t):
        if total + len(t) + 1 > 480:  # ช่องแท็กรวมไม่เกิน 500 ตัวอักษร
            break
        out.append(t[:60])
        total += len(t) + 1
    return {"title": yt_title, "description": desc + "\n\n" + " ".join(hashtags), "tags": out}


def clean_post(t: str) -> str:
    return re.sub(r"\s*#[^\s#]+", "", t).strip()


def _tags(tags) -> list[str]:
    out = []
    for t in tags if isinstance(tags, list) else str(tags).split():
        t = "#" + re.sub(r"[\s#]+", "", str(t))
        if len(t) > 1 and t.lower() not in {x.lower() for x in out}:
            out.append(t[:40])
    return out[:10]


def _ask_claude(prompt: str) -> str:
    import anthropic
    client = anthropic.Anthropic()  # อ่าน ANTHROPIC_API_KEY จาก environment
    msg = client.messages.create(model=DEFAULT_CLAUDE_MODEL, max_tokens=4000,
                                 messages=[{"role": "user", "content": prompt}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def _ask_ollama(prompt: str) -> str:
    # context พอดีกับความยาวคำสั่ง (ภาษาไทย ~1 token ต่อ 1-2 ตัวอักษร) — ใหญ่เกินจะช้าและกินการ์ดจอ
    ctx = min(32768, max(4096, 1 << (len(prompt) + 3000).bit_length()))
    body = json.dumps({"model": DEFAULT_OLLAMA_MODEL, "stream": False, "format": "json",
                       "options": {"num_ctx": ctx, "temperature": 0.3}, "keep_alive": 0,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(f"{OLLAMA_URL}/api/chat", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.loads(r.read())["message"]["content"]


def _plan_without_ai(segs: list[dict], target: float) -> dict:
    """ไม่มี AI: เลือกท่อนกระจายทั่วคลิป แล้วใช้คำพูดจริงเป็นบทพากย์ตั้งต้น (ผู้ใช้แก้ได้)"""
    total = segs[-1]["end"] if segs else 0
    n = max(1, round(target / 10))
    clips, last = [], -1  # last = หมายเลขท่อนสุดท้ายที่ใช้ไปแล้ว
    for k in range(n):
        t = total * (k + 0.5) / n
        free = [j for j in range(last + 1, len(segs))]
        if not free:
            break
        i = min(free, key=lambda j: abs(segs[j]["start"] - t))
        j = i
        while j + 1 < len(segs) and segs[j + 1]["end"] - segs[i]["start"] <= 12:
            j += 1
        last = j
        text = " ".join(s["text"] for s in segs[i:j + 1])
        clips.append({"start": segs[i]["start"], "end": segs[j]["end"], "narration": text[:150]})
    clips.sort(key=lambda c: c["start"])
    return {"title": "", "summary": "(โหมดไม่ใช้ AI — แก้บทพากย์ด้านล่างได้เลย)", "clips": clips}


def make_plan(segs: list[dict], provider: str, target: float,
              video_duration: float) -> dict:
    if not segs:
        raise RuntimeError("ไม่พบเสียงพูดในคลิป จึงสรุปไม่ได้")
    if provider == "none":
        return _plan_without_ai(segs, target)

    segs = merge_segments(segs, 350)
    prompt = PLAN_PROMPT.format(target=int(target), transcript=_transcript_block(segs))
    raw = ask_ai(provider, prompt)
    data = _parse_json(raw)

    clips = []
    for c in data.get("clips", []):
        try:
            a = max(0, min(int(c["start_seg"]), len(segs) - 1))
            b = max(a, min(int(c.get("end_seg", a)), len(segs) - 1))
        except (KeyError, ValueError, TypeError):
            continue
        clips.append({"start": segs[a]["start"],
                      "end": min(segs[b]["end"] + 0.3, video_duration),
                      "narration": clean_text(str(c.get("narration", "")))})
    clips.sort(key=lambda c: c["start"])
    # กันช่วงทับกัน
    for prev, cur in zip(clips, clips[1:]):
        if cur["start"] < prev["end"]:
            prev["end"] = cur["start"]
    clips = [c for c in clips if c["end"] - c["start"] >= 1]
    if not clips:
        raise RuntimeError("AI ไม่ได้เลือกช่วงไฮไลต์ที่ใช้ได้ ลองใหม่อีกครั้ง")
    return {"title": str(data.get("title", "")), "summary": str(data.get("summary", "")),
            "clips": clips}


def clean_text(t: str) -> str:
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿*#_`~]", "", t)
    return re.sub(r"\s+", " ", t).strip()


# ───────────────────────── 3) เสียงพากย์ ─────────────────────────

VOICE_DIR: Path | None = None   # โฟลเดอร์เสียงตัวอย่างสำหรับโคลน (app.py ตั้งให้)
TTS_NOTES: list[str] = []      # เหตุที่ต้องถอยไปใช้เสียงสำรอง (แจ้งผู้ใช้ตอนจบ)


def clone_voices() -> list[str]:
    if not VOICE_DIR or not VOICE_DIR.exists():
        return []
    return sorted(f.stem for f in VOICE_DIR.glob("*.wav"))


def voice_list() -> list[dict]:
    import voice as V
    out = [{**v, "group": "edge"} for v in THAI_VOICES]
    out += [{"id": f"gemini:{n}", "name": f"✨ Gemini {n} ({d})", "group": "gemini"} for n, d in V.GEMINI_VOICES]
    out += [{"id": f"clone:{n}", "name": f"🎙️ เสียงฉัน: {n}", "group": "clone"} for n in clone_voices()]
    return out


def valid_voice(v: str) -> bool:
    if not v:
        return False
    if v.startswith("gemini:"):
        import voice as V
        return v[7:] in {n for n, _ in V.GEMINI_VOICES}
    if v.startswith("clone:"):
        return v[6:] in clone_voices()
    return v in {x["id"] for x in THAI_VOICES}


def _note(msg: str) -> None:
    if msg not in TTS_NOTES:
        TTS_NOTES.append(msg)
        print("เสียงพากย์:", msg)


def _edge_tts(text: str, out_mp3: Path, voice: str, rate: int) -> None:
    import edge_tts

    async def go():
        comm = edge_tts.Communicate(text, voice, rate=f"{rate:+d}%")
        await comm.save(str(out_mp3))

    asyncio.run(go())


def tts(text: str, out_mp3: Path, voice: str, rate: int, tone: str = "natural",
        note: Callable[[str], None] | None = None) -> str:
    """สร้างเสียงพากย์ 1 ท่อน คืนชื่อเสียงที่ใช้จริง (อาจเป็นเสียงสำรอง)"""
    used = _tts_raw(text, out_mp3, voice, rate, tone, note) or voice
    _tidy_voice(out_mp3)
    return used


VOICE_NAMES = {"th-TH-PremwadeeNeural": "เปรมวดี", "th-TH-NiwatNeural": "นิวัฒน์", "th-TH-AcharaNeural": "อัจฉรา"}


def tts_all(texts: list[str], workdir: Path, voice: str, rate: int, tone: str,
            progress: Progress, total: float = 100) -> list[Path | None]:
    """สร้างเสียงพากย์ทุกท่อนก่อนตัดต่อ — ถ้าเสียง Gemini/โคลนใช้ไม่ได้กลางทาง (โควตาหมด)
    จะสร้างท่อนก่อนหน้าใหม่ด้วยเสียงสำรอง ให้ทั้งคลิปเป็นเสียงเดียวกัน ไม่สลับไปมา"""
    n = max(1, len(texts))
    outs: list[Path | None] = []
    used: list[str] = []
    for i, text in enumerate(texts):
        if not text:
            outs.append(None)
            used.append("")
            continue
        progress(i / n * total, f"สร้างเสียงพากย์ท่อนที่ {i + 1}/{n}")
        f = workdir / f"narr_{i:03}.mp3"
        v = voice
        if used and any(u and u != voice for u in used):  # สลับไปเสียงสำรองแล้ว → ใช้ต่อทั้งคลิป
            v = next(u for u in used if u and u != voice)
        used.append(tts(text, f, v, rate, tone, note=lambda m, i=i: progress(i / n * total, m)))
        outs.append(f)
    backup = next((u for u in used if u and u != voice), None)
    redo = [k for k, u in enumerate(used) if u == voice]
    if backup and redo:
        for j, k in enumerate(redo):
            progress(total, f"เสียงหลักใช้ไม่ได้กลางคลิป — ทำเสียงท่อนแรกๆ ใหม่ให้เป็นเสียงเดียวกัน ({j + 1}/{len(redo)})")
            tts(texts[k], outs[k], backup, rate, tone)
        _note(f"ทั้งคลิปใช้เสียง{VOICE_NAMES.get(backup, backup)}แทน เพื่อไม่ให้เสียงสลับกลางคลิป")
    return outs


def _tidy_voice(f: Path) -> None:
    """ตัดช่วงเงียบหัว-ท้ายที่ระบบเสียงแถมมา (ไม่งั้นรอยต่อฉากเงียบนาน ฟังสะดุด)
    + ปรับความดังให้เท่ากันทุกฉาก (เสียง AI แต่ละเจ้า/แต่ละท่อนดังไม่เท่ากัน)"""
    tmp = f.with_name(f.stem + "_tidy.mp3")
    try:
        run(["ffmpeg", "-y", "-hide_banner", "-i", str(f), "-af",
             "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
             "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.12,areverse,"
             "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-c:a", "libmp3lame", "-q:a", "2", str(tmp)])
        if probe(tmp)["duration"] > 0.3:
            tmp.replace(f)
    except Exception as e:
        print("ปรับเสียงพากย์ไม่ได้ (ใช้เสียงเดิม):", str(e)[-150:])
    finally:
        tmp.unlink(missing_ok=True)


def _tts_raw(text: str, out_mp3: Path, voice: str, rate: int, tone: str = "natural",
             note: Callable[[str], None] | None = None) -> None:
    """voice: th-TH-…Neural (Edge) | gemini:<ชื่อ> | clone:<ชื่อเสียงตัวอย่าง>
    ถ้าเสียง Gemini/โคลนใช้ไม่ได้ จะถอยไปใช้ Edge TTS ให้อัตโนมัติ (งานไม่พัง)"""
    import voice as V
    fallback = THAI_VOICES[0]["id"]
    if voice.startswith("gemini:"):
        name = voice[7:]
        if name in ("Puck", "Charon", "Fenrir"):
            fallback = "th-TH-NiwatNeural"
        try:
            V.gemini_tts(text, out_mp3, name, tone, rate)
            return voice
        except Exception as e:
            _note(f"ใช้เสียง Gemini ไม่ได้ ({e}) — ใช้เสียงเปรมวดี/นิวัฒน์แทน")
    elif voice.startswith("clone:"):
        fallback = "th-TH-NiwatNeural"
        name = voice[6:]
        ref = VOICE_DIR / f"{name}.wav" if VOICE_DIR else None
        try:
            if not ref or not ref.exists():
                raise RuntimeError("ไม่พบเสียงตัวอย่าง")
            txt = ref.with_suffix(".txt")
            V.clone_tts(text, out_mp3, ref, txt.read_text("utf-8").strip() if txt.exists() else "", rate,
                        progress=note)
            return voice
        except Exception as e:
            _note(f"โคลนเสียงไม่ได้ ({str(e)[:150]}) — ใช้เสียงนิวัฒน์แทน")
    elif voice not in {v["id"] for v in THAI_VOICES}:
        voice = fallback
    else:
        fallback = voice
    _edge_tts(text, out_mp3, fallback, rate)
    return fallback


# ───────────────────────── 4) ตัดต่อ ─────────────────────────

FONT_DIR = Path(os.environ.get("FONT_DIR") or Path(__file__).resolve().parent / "fonts")


def thai_font() -> str:
    """ชื่อฟอนต์ไทยสำหรับซับ/ข้อความ (Kanit ถ้าดาวน์โหลดไว้ ไม่งั้นใช้ฟอนต์ในเครื่อง)"""
    if os.environ.get("SUB_FONT"):
        return os.environ["SUB_FONT"]
    if (FONT_DIR / "Kanit-Bold.ttf").exists() or (FONT_DIR / "Kanit-SemiBold.ttf").exists():
        return "Kanit"
    if sys.platform.startswith("win"):
        return "Tahoma"
    if sys.platform == "darwin":
        return "Thonburi"
    return "Loma"


# ───── ข้อความไทยทั้งหมดวาดด้วย libass (ไฟล์ .ass) ─────
# drawtext ของ ffmpeg รุ่นเก่า (เช่น 4.4 บน Colab) จัดวางสระ/วรรณยุกต์ไทยไม่ได้ → ตัวอักษรเพี้ยน
# libass จัดวางภาษาไทยได้ถูกต้อง และทำแอนิเมชัน (เลื่อน/จาง) ได้

def _ff_path(p: Path) -> str:
    """path สำหรับใส่ใน filter ของ ffmpeg (รองรับ Windows C:\\...)"""
    return "'" + str(p).replace("\\", "/").replace(":", "\\:").replace("'", "") + "'"


def ass_filter(name: str) -> str:
    f = f"subtitles={name}"
    if FONT_DIR.exists():
        f += f":fontsdir={_ff_path(FONT_DIR)}"
    return f


def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _ass_time(t: float) -> str:
    t = max(0.0, t)
    cs = int(round(t * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def ass_text(text: str) -> str:
    return text.replace("\\", "/").replace("{", "(").replace("}", ")").replace("\n", "\\N")


class Ass:
    """สร้างไฟล์ซับ .ass: หน่วยเป็นพิกเซลของวิดีโอจริง (PlayRes = ขนาดวิดีโอ)"""

    def __init__(self, W: int, H: int):
        self.W, self.H = W, H
        self.styles: list[str] = []
        self.events: list[str] = []
        vertical = H > W
        f = thai_font()
        u = H if vertical else H * 1.25        # หน่วยอ้างอิงขนาดตัวอักษร
        white, black = _ass_color("FFFFFF"), _ass_color("000000")
        # Name,Font,Size,Primary,Secondary,Outline,Back,Bold,Italic,Underline,Strike,ScaleX,ScaleY,
        # Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
        self.style("Sub", f, u * 0.034, white, black, _ass_color("000000", 0x60), 1, 1, 4.5, 1, 2,
                   40, 40, int(H * (0.14 if vertical else 0.06)))
        self.style("Head", f, u * 0.040, white, _ass_color("D9480F"), _ass_color("D9480F"), 1, 3, 18, 0, 8,
                   60, 60, 0)
        self.style("Brand", f, u * 0.024, _ass_color("FFFFFF", 0x14), black, black, 1, 1, 3, 0, 7,
                   40, 40, int(H * (0.065 if vertical else 0.035)))
        self.style("Pop", f, u * (0.052 if vertical else 0.046), white, black, _ass_color("000000", 0x60), 1, 1, 7, 3, 2,
                   50, 50, int(H * (0.24 if vertical else 0.09)))
        # กล่องสีพอดีข้อความ (BorderStyle 3) สำหรับโมชันกราฟิก "คำสำคัญ"
        self.style("GBox", f, u * 0.04, _ass_color("1A1A1A"), _ass_color("FFD43B"), _ass_color("FFD43B"), 1, 3, 18, 0, 5,
                   40, 40, 0)
        self.style("Title", f, u * 0.05, white, black, _ass_color("000000", 0x70), 1, 3, 22, 0, 2,
                   50, 50, int(H * (0.2 if vertical else 0.12)))

    def style(self, name, font, size, primary, outline, back, bold, border_style, outline_w, shadow,
              align, ml, mr, mv):
        self.styles.append(
            f"Style: {name},{font},{int(size)},{primary},{primary},{outline},{back},{-1 if bold else 0},"
            f"0,0,0,100,100,0,0,{border_style},{outline_w},{shadow},{align},{ml},{mr},{mv},1")

    def add(self, style: str, t0: float, t1: float, text: str, tags: str = "") -> None:
        if not text.strip() or t1 <= t0:
            return
        self.events.append(f"Dialogue: 0,{_ass_time(t0)},{_ass_time(t1)},{style},,0,0,0,,"
                           f"{('{' + tags + '}') if tags else ''}{ass_text(text)}")

    def subs(self, narration: str, start: float, dur: float, max_chars: int, pop: bool = False) -> None:
        if pop:
            return self.pop_subs(narration, start, dur, max_chars)
        for t0, t1, chunk in sub_chunks(narration, start, dur, max_chars):
            self.add("Sub", t0, t1, chunk)

    def pop_subs(self, narration: str, start: float, dur: float, max_chars: int) -> None:
        """ซับเด้งทีละคำแบบคลิปไวรัล: ตัวใหญ่ทีละท่อนสั้นๆ คำที่กำลังพูดเป็นสีเหลือง + เด้งขยาย"""
        hi = _ass_color("FFD43B")
        limit = max(8, int(max_chars * 0.6))
        for chunk in pop_chunks(narration, start, dur, limit):
            c0 = chunk[0][1]
            for k, (_, t0, t1) in enumerate(chunk):
                t1 = chunk[k + 1][1] if k + 1 < len(chunk) else t1
                body = ""
                for m, (tok, _, _) in enumerate(chunk):
                    sep = " " if tok.startswith(" ") and m else ""
                    word = ass_text(tok.strip())
                    if m == k:
                        body += (sep + "{\\c" + hi + "&\\fscx112\\fscy112\\t(0,90,\\fscx122\\fscy122)"
                                 "\\t(90,200,\\fscx112\\fscy112)}" + word + "{\\r}")
                    else:
                        body += sep + word
                intro = "\\fscx70\\fscy70\\t(0,120,\\fscx100\\fscy100)" if t0 == c0 else ""
                if t1 > t0:
                    self.events.append(f"Dialogue: 0,{_ass_time(t0)},{_ass_time(t1)},Pop,,0,0,0,,"
                                       f"{{{intro}}}{body}" if intro else
                                       f"Dialogue: 0,{_ass_time(t0)},{_ass_time(t1)},Pop,,0,0,0,,{body}")

    def headline(self, text: str, t0: float, t1: float, y: int) -> None:
        """หัวข้อกล่องสี เลื่อนขึ้น + จางเข้า"""
        x = self.W // 2
        self.add("Head", t0, t1, text, f"\\an8\\move({x},{y + 70},{x},{y},0,450)\\fad(350,200)")

    def brand(self, text: str, t1: float, x: int = 40) -> None:
        self.add("Brand", 0, t1, text, f"\\an7\\pos({x},{int(self.H * (0.065 if self.H > self.W else 0.035))})")

    def write(self, path: Path) -> bool:
        if not self.events:
            return False
        path.write_text(
            "[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
            f"PlayResX: {self.W}\nPlayResY: {self.H}\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
            "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n" + "\n".join(self.styles) +
            "\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" +
            "\n".join(self.events) + "\n", encoding="utf-8")
        return True


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


# สระ/วรรณยุกต์ที่ต้องติดกับพยัญชนะข้างหน้า และสระที่ต้องติดกับพยัญชนะข้างหลัง
_TH_AFTER = set("ะัาำิีึืฺุู็่้๊๋์ํๅ")
_TH_BEFORE = set("เแโใไ")
_TH_MID = set("ัิีึืฺุู็่้๊๋")  # สระบน/ล่าง/วรรณยุกต์ — มักมีตัวสะกดตามหลัง อย่าตัดต่อจากตัวนี้


def _thai_cut(w: str, n: int) -> int:
    """หาจุดตัดคำไทยยาวที่ไม่ผ่ากลางสระ/วรรณยุกต์ (ถอยหลังไม่เกิน 8 ตัว)"""
    for k in range(n, max(n - 8, 1), -1):
        if w[k] not in _TH_AFTER and w[k - 1] not in _TH_BEFORE and w[k - 1] not in _TH_MID:
            return k
    return n


def _words(text: str) -> list[str]:
    """แยกคำ: ใช้ pythainlp ถ้ามี (ตัดคำไทยได้ถูก) ไม่งั้นแยกตามช่องว่าง"""
    try:
        from pythainlp.tokenize import word_tokenize
        toks = word_tokenize(text, engine="newmm", keep_whitespace=True)
        out, cur = [], ""
        for t in toks:  # รวมเป็น "คำ" ที่ไม่มีช่องว่าง แต่เก็บจุดตัดคำไทยไว้ด้วย \u200b
            if t.isspace():
                if cur:
                    out.append(cur)
                cur = ""
            else:
                cur += ("\u200b" if cur else "") + t
        if cur:
            out.append(cur)
        return out
    except Exception:
        return text.split()


_TH_SILENT = set("ัิีึืฺุู็่้๊๋์ํ")  # สระบน/ล่าง/วรรณยุกต์ ไม่กินเวลาพูดเพิ่ม


def _speak_len(t: str) -> float:
    return sum(0 if ch in _TH_SILENT else 0.3 if ch in " ,." else 1 for ch in t) + 0.6


def pop_chunks(text: str, start: float, dur: float, limit: int = 13) -> list[list[tuple[str, float, float]]]:
    """แบ่งเป็นท่อนสั้น (≤ limit ตัวอักษร) แต่ละคำมีเวลาของตัวเอง [(คำ, เริ่ม, จบ)]
    คำที่ขึ้นต้นด้วยช่องว่าง = ต้นฉบับเว้นวรรคไว้ (หยุดหายใจ → ให้เวลาเพิ่มนิดนึง)"""
    toks: list[str] = []
    for w in _words(text):
        for k, part in enumerate(p for p in w.split("\u200b") if p):
            if len(part) > limit + 4:  # คำยาวผิดปกติ → หั่นไม่ให้ล้นจอ
                while len(part) > limit + 4:
                    c = _thai_cut(part, limit)
                    toks.append(("" if k or not toks else " ") + part[:c])
                    part, k = part[c:], 1
            toks.append(("" if k or not toks else " ") + part)
    if not toks:
        return []
    weights = [_speak_len(t) + (1.2 if t.startswith(" ") else 0) for t in toks]
    total = sum(weights)
    t, timed = start, []
    for tok, w in zip(toks, weights):
        d = dur * w / total
        timed.append((tok, t, t + d))
        t += d
    chunks, cur, n = [], [], 0
    for tok, a, b in timed:
        ln = len(tok.strip())
        # ขึ้นท่อนใหม่เมื่อยาวเกิน หรือเจอช่องว่าง (ช่วงหายใจ) และท่อนเดิมยาวพอแล้ว
        if cur and (n + ln > limit or (tok.startswith(" ") and n >= limit * 0.35)):
            chunks.append(cur)
            cur, n = [], 0
        cur.append((tok if cur else tok.lstrip(), a, b))
        n += ln
    if cur:
        chunks.append(cur)
    return chunks


def write_srt(text: str, start: float, dur: float, path: Path, max_chars: int = 42) -> None:
    lines = [f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{c}\n"
             for i, (a, b, c) in enumerate(sub_chunks(text, start, dur, max_chars), 1)]
    path.write_text("\n".join(lines), encoding="utf-8")


def sub_chunks(text: str, start: float, dur: float, max_chars: int = 42) -> list[tuple[float, float, str]]:
    """แบ่งบทพากย์เป็นท่อนสั้นๆ (ไม่ตัดกลางคำ) แล้วกระจายเวลาตามจำนวนตัวอักษร"""
    chunks, cur = [], ""

    def flush():
        nonlocal cur
        if cur:
            chunks.append(cur.replace("\u200b", ""))
        cur = ""

    for w in _words(text):
        plain = w.replace("\u200b", "")
        if cur and len(cur.replace("\u200b", "")) + 1 + len(plain) <= max_chars:
            cur = f"{cur} {w}"
            continue
        flush()
        # คำ (หรือวลีไทยไม่เว้นวรรค) ยาวเกินบรรทัด → ตัดที่จุดตัดคำ หรือจุดที่ไม่ผ่ากลางสระ
        while len(w.replace("\u200b", "")) > max_chars + 6:  # ยาวเกินนิดหน่อยไม่ตัด (กันเศษคำ)
            parts = w.split("\u200b")
            if len(parts) > 1:
                acc = ""
                for k, part in enumerate(parts):
                    if acc and len(acc) + len(part) > max_chars:
                        break
                    acc += part
                k = max(k, 1)
                chunks.append("".join(parts[:k]))
                w = "\u200b".join(parts[k:])
            else:
                c = _thai_cut(w, max_chars)
                chunks.append(w[:c])
                w = w[c:]
        cur = w
    flush()
    chunks = [c.strip() for c in chunks if c.strip()]
    total = sum(len(c) for c in chunks) or 1
    t, out = start, []
    for c in chunks:
        d = dur * len(c) / total
        out.append((t, t + d, c))
        t += d
    return out



FADE = 0.3
LEAD_IN = 0.25  # เว้นช่วงก่อนเริ่มพากย์

LAYOUTS = {
    "original": "ตามต้นฉบับ",
    "vertical_blur": "แนวตั้ง 9:16 — ภาพกลางจอ + พื้นหลังเบลอ",
    "vertical_crop": "แนวตั้ง 9:16 — ครอปเต็มจอ (ซูมเข้าตรงกลาง)",
}

def _label_font() -> str | None:
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
              "C:/Windows/Fonts/arialbd.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/Library/Fonts/Arial Bold.ttf"):
        if Path(f).exists():
            return f
    try:
        out = subprocess.run(["fc-match", "sans:bold", "-f", "%{file}"],
                             capture_output=True, text=True).stdout.strip()
        return out or None
    except Exception:
        return None


def thai_font_file(bold: bool = True) -> str | None:
    """ไฟล์ฟอนต์ที่มีตัวอักษรไทย (สำหรับ drawtext: ชื่อช่อง, ภาพปก)"""
    if os.environ.get("THAI_FONT_FILE") and Path(os.environ["THAI_FONT_FILE"]).exists():
        return os.environ["THAI_FONT_FILE"]
    for f in ("C:/Windows/Fonts/tahomabd.ttf", "C:/Windows/Fonts/tahoma.ttf",
              "/System/Library/Fonts/Supplemental/Thonburi.ttc", "/System/Library/Fonts/Thonburi.ttc"):
        if Path(f).exists():
            return f
    try:
        out = subprocess.run(["fc-match", f":lang=th{':style=Bold' if bold else ''}", "-f",
                              "%{file}\\n%{lang}"], capture_output=True, text=True).stdout
        path, langs = (out.split("\n") + [""])[:2]
        if path and "th" in langs.split("|"):
            return path
    except Exception:
        pass
    return None


def _layout_filter(layout: str, src: str = "[0:v]") -> tuple[str, int]:
    """คืน (filter ที่เปลี่ยน src → [base], ความสูงวิดีโอ)"""
    if layout == "vertical_crop":
        return (f"{src}scale=1080:1920:force_original_aspect_ratio=increase,"
                "crop=1080:1920,setsar=1[base]"), 1920
    if layout == "vertical_blur":
        return (f"{src}split[s1][s2];"
                "[s1]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,"
                "boxblur=8:2,eq=brightness=-0.12,scale=1080:1920,setsar=1[bg];"
                # ภาพหลัก: ตัดกลางจอเกือบเป็นสี่เหลี่ยมจัตุรัส (เห็นฮีโร่ใหญ่ขึ้น แต่ยังเห็นรอบตัว)
                "[s2]crop='min(iw,ih*1.15)':ih,scale=1080:-2,setsar=1[fg];"
                "[bg][fg]overlay=(W-w)/2:(H-h)/2-80[base]"), 1920
    return f"{src}scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1[base]", 0


SLOW = 0.5          # ความเร็วช่วงสโลว์ (0.5 = ช้าลงครึ่งหนึ่ง)
SLOW_BEFORE, SLOW_AFTER = 1.4, 0.5   # ช่วงสโลว์รอบจังหวะเก็บคิล
FREEZE = 0.35       # หยุดภาพค้างตรงจังหวะเก็บคิล (วินาที)


def make_sfx(workdir: Path) -> tuple[Path, Path]:
    """สร้างเสียงเอฟเฟกต์ด้วย ffmpeg (ไม่ต้องโหลดไฟล์): วูบ (ก่อนคิล) + ตูม (ตอนคิล)"""
    whoosh, boom = workdir / "sfx_whoosh.wav", workdir / "sfx_boom.wav"
    if not whoosh.exists():
        run(["ffmpeg", "-y", "-hide_banner", "-f", "lavfi", "-i", "anoisesrc=d=0.55:c=pink:a=0.9:r=44100",
             "-af", "highpass=f=500,lowpass=f=5000,afade=t=in:st=0:d=0.42:curve=exp,"
                    "afade=t=out:st=0.43:d=0.12,volume=1.6", "-ac", "2", str(whoosh)])
    if not boom.exists():
        run(["ffmpeg", "-y", "-hide_banner",
             "-f", "lavfi", "-i", "aevalsrc='0.95*sin(2*PI*(95*t-45*t*t))*exp(-4.5*t)':d=0.9:s=44100",
             "-f", "lavfi", "-i", "anoisesrc=d=0.18:c=brown:a=0.8:r=44100",
             "-filter_complex", "[1]lowpass=f=900,afade=t=out:st=0:d=0.18[n];"
                                "[0][n]amix=inputs=2:duration=longest,volume=2.2", "-ac", "2", str(boom)])
    return whoosh, boom


def render_clip(src: Path, info: dict, clip: dict, narr: Path | None, out: Path,
                orig_volume: float, subtitles: bool, workdir: Path,
                layout: str = "original", extras: bool = True, fades: bool = True,
                fx: bool = False, brand: dict | None = None) -> None:
    """ตัดต่อ 1 ช็อต: ตัดช่วง → (สโลว์) → จัดภาพ → (ซูม/สั่น/แฟลช) → ป้าย/โลโก้/ซับ → ผสมเสียง"""
    configs = [(extras, fx)]
    if extras:
        configs.append((False, fx))
    if fx:
        configs.append((False, False))
    err = None
    for ex, f in configs:  # ถ้าล้ม (เช่นเครื่องไม่มีฟอนต์/libass) ลดลูกเล่นลงทีละขั้น
        try:
            _render_clip(src, info, clip, narr, out, orig_volume, subtitles, workdir,
                         layout, ex, fades, f, brand)
            return
        except RuntimeError as e:
            err = e
            print("ตัดต่อแบบเต็มไม่สำเร็จ ลองแบบลดลูกเล่น:", str(e)[-300:])
    raise err


def _render_clip(src, info, clip, narr, out, orig_volume, subtitles, workdir,
                 layout, extras, fades, fx, brand) -> None:
    start = float(clip["start"])
    want = float(clip["end"]) - start
    avail = max(0.1, info["duration"] - start)
    narr_dur = probe(narr)["duration"] if narr else 0.0
    vertical = layout.startswith("vertical")
    mark_rel = float(clip.get("mark") or start) - start if clip.get("mark") is not None else None

    src_len = max(0.1, min(want, avail))
    # ช่วงสโลว์โมชันรอบจังหวะเก็บคิล
    slow = None
    if fx and mark_rel is not None:
        sa = max(0.25, mark_rel - SLOW_BEFORE)
        sb = min(src_len - 0.15, mark_rel + SLOW_AFTER)
        if sb - sa >= 0.5:
            slow = (sa, sb)
    # หยุดภาพค้างตรงจังหวะคิล (อยู่ในช่วงสโลว์เสมอ)
    freeze = FREEZE if slow and fx and slow[0] < mark_rel < slow[1] else 0.0
    extra_slow = (slow[1] - slow[0]) * (1 / SLOW - 1) + freeze if slow else 0.0
    eff = src_len + extra_slow
    need = narr_dur + LEAD_IN + 0.4 if narr else 0.0
    if need > eff:  # บทพากย์ยาว → ใช้ภาพต้นฉบับต่ออีก ถ้าไม่มีก็หยุดภาพค้าง
        add = min(avail - src_len, need - eff)
        src_len += max(0.0, add)
        eff += max(0.0, add)
    length = max(eff, need)
    pad = max(0.0, length - eff)

    def out_t(t_rel: float) -> float:  # เวลาในต้นฉบับ → เวลาในคลิปที่สโลว์แล้ว
        if not slow or t_rel <= slow[0]:
            return t_rel
        if freeze and t_rel <= mark_rel:
            return slow[0] + (t_rel - slow[0]) / SLOW
        if t_rel <= slow[1]:
            return slow[0] + (t_rel - slow[0]) / SLOW + freeze
        return t_rel + extra_slow
    mark_out = out_t(mark_rel) if mark_rel is not None else None
    if freeze:  # จังหวะคิล = ตอนเริ่มภาพค้าง
        mark_out = slow[0] + (mark_rel - slow[0]) / SLOW

    norm = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"
    has_a = info["has_audio"] and orig_volume > 0
    parts = []
    # ── สโลว์โมชัน: แบ่ง 3 ท่อน ก่อน/ระหว่าง/หลัง แล้วต่อกัน (ภาพและเสียงตรงกัน) ──
    if slow and freeze:
        # ก่อน / สโลว์ถึงจังหวะคิล / ภาพค้าง / สโลว์ต่อ / หลัง
        sa, sb, m = slow[0], slow[1], mark_rel
        nf = max(1, round(freeze * 30))
        parts.append("[0:v]setpts=PTS-STARTPTS,fps=30,split=5[v1][v2][vf][v4][v3]")
        parts.append(f"[v1]trim=0:{sa:.3f},setpts=PTS-STARTPTS[p1]")
        parts.append(f"[v2]trim={sa:.3f}:{m:.3f},setpts=(PTS-STARTPTS)/{SLOW}[p2]")
        parts.append(f"[vf]trim={m:.3f}:{m + 0.034:.3f},setpts=PTS-STARTPTS,loop=loop={nf}:size=1:start=0,"
                     f"setpts=N/30/TB,trim=end_frame={nf}[pf]")
        parts.append(f"[v4]trim={m:.3f}:{sb:.3f},setpts=(PTS-STARTPTS)/{SLOW}[p4]")
        parts.append(f"[v3]trim={sb:.3f},setpts=PTS-STARTPTS[p3]")
        if has_a:
            parts.append(f"[0:a]asetpts=PTS-STARTPTS,{norm},asplit=4[x1][x2][x4][x3]")
            parts.append(f"[x1]atrim=0:{sa:.3f},asetpts=PTS-STARTPTS[q1]")
            parts.append(f"[x2]atrim={sa:.3f}:{m:.3f},asetpts=PTS-STARTPTS,atempo={SLOW}[q2]")
            parts.append(f"aevalsrc=0|0:d={nf / 30:.4f}:s=44100,{norm}[qf]")
            parts.append(f"[x4]atrim={m:.3f}:{sb:.3f},asetpts=PTS-STARTPTS,atempo={SLOW}[q4]")
            parts.append(f"[x3]atrim={sb:.3f},asetpts=PTS-STARTPTS[q3]")
            parts.append("[p1][q1][p2][q2][pf][qf][p4][q4][p3][q3]concat=n=5:v=1:a=1[vs][as]")
        else:
            parts.append("[p1][p2][pf][p4][p3]concat=n=5:v=1:a=0[vs]")
        vsrc, asrc = "[vs]", "[as]"
    elif slow:
        sa, sb = slow
        parts.append("[0:v]setpts=PTS-STARTPTS,split=3[v1][v2][v3]")
        parts.append(f"[v1]trim=0:{sa:.3f},setpts=PTS-STARTPTS[p1]")
        parts.append(f"[v2]trim={sa:.3f}:{sb:.3f},setpts=(PTS-STARTPTS)/{SLOW}[p2]")
        parts.append(f"[v3]trim={sb:.3f},setpts=PTS-STARTPTS[p3]")
        if has_a:
            parts.append(f"[0:a]asetpts=PTS-STARTPTS,{norm},asplit=3[x1][x2][x3]")
            parts.append(f"[x1]atrim=0:{sa:.3f},asetpts=PTS-STARTPTS[q1]")
            parts.append(f"[x2]atrim={sa:.3f}:{sb:.3f},asetpts=PTS-STARTPTS,atempo={SLOW}[q2]")
            parts.append(f"[x3]atrim={sb:.3f},asetpts=PTS-STARTPTS[q3]")
            parts.append("[p1][q1][p2][q2][p3][q3]concat=n=3:v=1:a=1[vs][as]")
        else:
            parts.append("[p1][p2][p3]concat=n=3:v=1:a=0[vs]")
        vsrc, asrc = "[vs]", "[as]"
    else:
        vsrc, asrc = "[0:v]", f"[0:a]"

    base, _ = _layout_filter(layout, vsrc)
    parts.append(base)
    cur = "[base]"
    # ── ซูมเข้า + สั่นจอ ช่วงสโลว์ ──
    if slow:
        a0, b0 = slow[0], slow[0] + (slow[1] - slow[0]) / SLOW + freeze
        parts.append(f"{cur}split[b1][b2]")
        parts.append("[b2]scale=iw*1.12:-2,"
                     "crop=iw/1.12:ih/1.12:"
                     f"x='(iw-ow)/2+if(between(t,{mark_out:.2f},{mark_out + 0.45:.2f}),14*sin(t*97),0)':"
                     f"y='(ih-oh)/2+if(between(t,{mark_out:.2f},{mark_out + 0.45:.2f}),14*cos(t*83),0)'[bz]")
        parts.append(f"[b1][bz]overlay=(W-w)/2:(H-h)/2:enable='between(t,{a0:.2f},{b0:.2f})'[base2]")
        cur = "[base2]"

    vf = []
    if pad > 0.01:
        vf.append(f"tpad=stop_mode=clone:stop_duration={pad:.3f}")
    if fx and mark_out is not None:  # แฟลชขาว + ภาพแยกสี (glitch) ตอนเก็บคิล
        vf.append(f"eq=brightness=0.35:enable='between(t,{mark_out:.2f},{mark_out + 0.1:.2f})'")
        vf.append(f"rgbashift=rh=-16:bh=16:enable='between(t,{mark_out:.2f},{mark_out + max(0.25, freeze):.2f})'")
    if fades:
        vf += [f"fade=t=in:st=0:d={FADE}", f"fade=t=out:st={length - FADE:.3f}:d={FADE}"]

    # ป้ายเหตุการณ์ เช่น SAVAGE / MANIAC ตอนจังหวะนั้นพอดี
    label, font = str(clip.get("label") or ""), _label_font()
    if extras and label and font and re.fullmatch(r"[A-Z ]+", label):
        at = (mark_out if mark_out is not None else 0.0)
        at = min(max(at - 0.3, 0.0), max(0.0, length - 2.2))
        size = "h*0.065" if vertical else "h*0.09"
        y = "h*0.16" if vertical else "h*0.12"
        vf.append(f"drawtext=fontfile='{font}':text='{label}!':fontsize={size}:"
                  f"fontcolor=#FFD43B:borderw=7:bordercolor=black:"
                  f"x=(w-text_w)/2:y={y}:enable='between(t,{at:.2f},{at + 2.0:.2f})'")

    # ข้อความไทย (ชื่อช่อง + ซับ) วาดด้วย libass ให้สระ/วรรณยุกต์ถูกตำแหน่ง
    brand = brand or {}
    logo = brand.get("logo") if extras else None
    text = (brand.get("text") or "").strip() if extras else ""
    logo_h = 96 if vertical else max(40, int((info.get("height") or 1080) * 0.08) // 2 * 2)
    W = 1080 if vertical else int(info.get("width") or 1920) // 2 * 2
    H = 1920 if vertical else int(info.get("height") or 1080) // 2 * 2
    ass = Ass(W, H)
    if text:
        ass.brand(text, length, x=(40 + logo_h + 18) if logo else 40)
    if extras and subtitles and narr:
        ass.subs(clip["narration"], LEAD_IN, narr_dur, 22 if vertical else 40, pop=subtitles == "pop")
    if ass.write(workdir / "text.ass"):
        vf.append(ass_filter("text.ass"))

    inputs = ["-ss", f"{start:.3f}", "-t", f"{src_len:.3f}", "-i", str(src)]
    n_in = 1
    idx_narr = idx_logo = idx_null = None
    if narr:
        inputs += ["-i", str(narr)]; idx_narr = n_in; n_in += 1
    if logo:
        inputs += ["-loop", "1", "-i", str(logo)]; idx_logo = n_in; n_in += 1
    idx_sfx = None
    if fx and mark_out is not None and extras:
        try:
            whoosh, boom = make_sfx(workdir)
            inputs += ["-i", str(whoosh), "-i", str(boom)]; idx_sfx = n_in; n_in += 2
        except Exception as e:
            print("ทำเสียงเอฟเฟกต์ไม่ได้:", e)

    if logo:
        parts.append(f"{cur}{','.join(vf) or 'null'}[pre]")
        ly = "h*0.075-20" if vertical else "40"
        parts.append(f"[{idx_logo}:v]scale=-2:{logo_h},format=rgba[lg]")
        parts.append(f"[pre][lg]overlay=40:{ly.replace('h', 'H')}:shortest=1,format=yuv420p[v]")
    else:
        vf.append("format=yuv420p")
        parts.append(f"{cur}{','.join(vf)}[v]")

    if narr:
        d = int(LEAD_IN * 1000)
        parts.append(f"[{idx_narr}:a]{norm},adelay={d}|{d},apad,asplit=2[nar][key]")
    if has_a:
        a_in = asrc if slow else f"{asrc}"
        pre = "" if slow else f"{norm},"
        parts.append(f"{a_in}{pre}volume={orig_volume:.3f},apad[bg0]")
        if narr:
            # ลดเสียงเกม/ต้นฉบับลงอัตโนมัติเฉพาะตอนมีเสียงพากย์
            parts.append("[bg0][key]sidechaincompress=threshold=0.015:ratio=10:"
                         "attack=15:release=350[bg]")
            parts.append("[bg][nar]amix=inputs=2:duration=longest:dropout_transition=0,"
                         "volume=2[mx]")
        else:
            parts.append("[bg0]anull[mx]")
    elif narr:
        parts.append("[key]anullsink")
        parts.append("[nar]anull[mx]")
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]; idx_null = n_in; n_in += 1
        parts.append(f"[{idx_null}:a]{norm}[mx]")
    if idx_sfx is not None:  # วูบก่อนคิล + ตูมตอนคิล
        dw, db = int(max(0.0, mark_out - 0.45) * 1000), int(mark_out * 1000)
        parts.append(f"[{idx_sfx}:a]{norm},volume=1.0,adelay={dw}|{dw}[sw]")
        parts.append(f"[{idx_sfx + 1}:a]{norm},volume=0.8,adelay={db}|{db}[sb]")
        parts.append("[sw][sb]amix=inputs=2:duration=longest:dropout_transition=0,volume=2,apad[sfx]")
        parts.append("[mx]apad[mx0]")
        parts.append("[mx0][sfx]amix=inputs=2:duration=shortest:dropout_transition=0,volume=2[mx2]")
        mx = "[mx2]"
    else:
        mx = "[mx]"
    af = 0.05 if not fades else FADE  # ไม่เฟดภาพ แต่เฟดเสียงสั้นๆ กันเสียงคลิก
    parts.append(f"{mx}apad,atrim=0:{length:.3f},afade=t=in:st=0:d={af},"
                 f"afade=t=out:st={length - af:.3f}:d={af}[a]")

    cmd = ["ffmpeg", "-y", "-hide_banner", *inputs,
           "-filter_complex", ";".join(parts), "-map", "[v]", "-map", "[a]",
           "-t", f"{length:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
           "-r", "30", "-video_track_timescale", "90000",
           "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", out.name]
    run(cmd, cwd=workdir)


# ───────────────────────── ภาพปก / เพลง ─────────────────────────

def _wrap(text: str, width: int) -> str:
    """ตัดบรรทัดโดยไม่ผ่ากลางคำไทย (ใช้วิธีเดียวกับซับ) สูงสุด 3 บรรทัด"""
    lines = [c for _, _, c in sub_chunks(text, 0, 1, width)]
    return "\n".join(lines[:3])

def make_thumbnail(src: Path, t: float, layout: str, title: str, label: str,
                   out: Path, workdir: Path, brand: dict | None = None) -> None:
    """ภาพปกคลิป: เฟรมจังหวะเด็ด + ตัวหนังสือใหญ่"""
    src, out, workdir = Path(src).resolve(), Path(out).resolve(), Path(workdir).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    vertical = layout.startswith("vertical")
    base, _ = _layout_filter(layout)
    vf = ["eq=brightness=-0.05:saturation=1.25"]
    lf = _label_font()
    if label and lf and re.fullmatch(r"[A-Z ]+", label):
        vf.append(f"drawtext=fontfile='{lf}':text='{label}!':fontsize=h*{0.085 if vertical else 0.13}:"
                  f"fontcolor=#FFD43B:borderw=10:bordercolor=black:x=(w-text_w)/2:y=h*{0.2 if vertical else 0.12}")
    if vertical:
        W, H = 1080, 1920
    else:
        i_ = probe(src)
        W, H = int(i_.get("width") or 1920) // 2 * 2, int(i_.get("height") or 1080) // 2 * 2
    ass = Ass(W, H)
    title = clean_text(title)
    if title:
        ass.add("Title", 0, 10, _wrap(title, 13 if vertical else 24))
    text = ((brand or {}).get("text") or "").strip()
    if text:
        ass.add("Brand", 0, 10, text, f"\\an2\\pos({W // 2},{int(H * 0.95)})")
    if ass.write(workdir / "thumb.ass"):
        vf.append(ass_filter("thumb.ass"))
    cmd = ["ffmpeg", "-y", "-hide_banner", "-ss", f"{max(0.0, t):.3f}", "-i", str(src),
           "-filter_complex", f"{base};[base]{','.join(vf)}[v]", "-map", "[v]",
           "-frames:v", "1", "-q:v", "3", str(out.resolve())]
    try:
        run(cmd, cwd=workdir)
    except RuntimeError:  # ไม่มีฟอนต์/drawtext → ภาพเปล่าๆ ก็ยังดี
        run(["ffmpeg", "-y", "-hide_banner", "-ss", f"{max(0.0, t):.3f}", "-i", str(src),
             "-filter_complex", f"{base}", "-map", "[base]", "-frames:v", "1", "-q:v", "3",
             str(out.resolve())], cwd=workdir)


def make_cover_clip(img: Path, like: Path, out: Path, seconds: float = 0.4) -> None:
    """ภาพปกเป็นวิดีโอสั้นๆ ไว้ต้นคลิป (TikTok เลือกเป็นปกได้ง่าย) — ต้องตรงสเปกกับคลิปอื่น"""
    i = probe(like)
    run(["ffmpeg", "-y", "-hide_banner", "-loop", "1", "-t", f"{seconds}", "-i", str(img),
         "-f", "lavfi", "-t", f"{seconds}", "-i", "anullsrc=r=44100:cl=stereo",
         "-vf", f"scale={i['width']}:{i['height']}:force_original_aspect_ratio=increase,"
                f"crop={i['width']}:{i['height']},setsar=1,format=yuv420p",
         "-r", "30", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
         "-video_track_timescale", "90000", "-c:a", "aac", "-b:a", "160k", "-ar", "44100",
         "-ac", "2", "-shortest", str(out)])


def add_music(video: Path, music: Path, volume: float, out: Path) -> None:
    """ใส่เพลงประกอบทั้งคลิป (วนซ้ำถ้าสั้น, เฟดเข้า-ออก) ภาพไม่ต้องแปลงใหม่"""
    dur = probe(video)["duration"]
    norm = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"
    fc = (f"[1:a]{norm},volume={volume:.3f},atrim=0:{dur:.3f},afade=t=in:st=0:d=1,"
          f"afade=t=out:st={max(0.0, dur - 1.5):.3f}:d=1.5[m];"
          f"[0:a]{norm}[g];[g][m]amix=inputs=2:duration=first:dropout_transition=0,volume=2[a]")
    run(["ffmpeg", "-y", "-hide_banner", "-i", str(video), "-stream_loop", "-1", "-i", str(music),
         "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-t", f"{dur:.3f}", str(out)])


# สเปกไฟล์สุดท้าย: H.264 High 4.1 / yuv420p / 30fps คงที่ / AAC 44.1kHz — มือถือทุกรุ่นเล่นได้
FINAL_AUDIO = ["-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2"]


def _final_video_args(nvenc: bool) -> list[str]:
    if nvenc:
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "22", "-b:v", "0",
                "-profile:v", "high", "-pix_fmt", "yuv420p"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-profile:v", "high",
            "-level:v", "4.1", "-pix_fmt", "yuv420p"]


def concat(clips: list[Path], out: Path, workdir: Path) -> None:
    """ต่อคลิปแล้วเข้ารหัสใหม่ทั้งไฟล์เป็นมาตรฐานเดียว
    ใช้ concat filter (ไม่ใช่ concat demuxer) — ไฟล์ที่ timebase ต่างกัน (เช่น ภาพปก + เนื้อคลิป)
    ต่อด้วย demuxer แล้วภาพจะสั้นกว่าเสียง/ค้าง · และให้ไฟล์มาตรฐานที่มือถือทุกรุ่นเล่นได้"""
    clips = [Path(c).resolve() for c in clips]
    W = H = None
    try:
        i0 = probe(clips[0])
        W, H = int(i0.get("width") or 0) // 2 * 2, int(i0.get("height") or 0) // 2 * 2
    except Exception:
        pass
    inputs, parts, joins = [], [], ""
    for k, c in enumerate(clips):
        inputs += ["-i", str(c)]
        size = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2," if W and H else ""
        parts.append(f"[{k}:v]{size}fps=30,format=yuv420p,setsar=1,setpts=PTS-STARTPTS[v{k}]")
        parts.append(f"[{k}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[a{k}]")
        joins += f"[v{k}][a{k}]"
    # ความดังมาตรฐาน TikTok/Reels (~-14 LUFS) — เดิมเบาไป ต้องเร่งเสียงมือถือ
    parts.append(f"{joins}concat=n={len(clips)}:v=1:a=1[v][a0]")
    parts.append("[a0]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[a]")
    script = workdir / "concat_filter.txt"
    script.write_text(";\n".join(parts), encoding="utf-8")
    base = ["ffmpeg", "-y", "-hide_banner", *inputs, "-filter_complex_script", str(script.resolve()),
            "-map", "[v]", "-map", "[a]", "-r", "30"]
    tail = [*FINAL_AUDIO, "-movflags", "+faststart", str(out.resolve())]
    if _has_nvenc():
        try:
            run(base + _final_video_args(True) + tail, cwd=workdir)
            return
        except RuntimeError as e:
            print("เข้ารหัสด้วยการ์ดจอไม่ได้ ใช้ CPU แทน:", str(e)[-200:])
    run(base + _final_video_args(False) + tail, cwd=workdir)


def render(src: Path, plan_clips: list[dict], workdir: Path, out: Path, *,
           voice: str, rate: int, orig_volume: float, subtitles: bool,
           progress: Progress, layout: str = "original", clean: bool = False,
           fx: bool = False, brand: dict | None = None, cover: Path | None = None,
           src_resolver=None, tone: str = "natural") -> list[Path]:
    """clean=True: สำหรับ CapCut — ไม่มีซับ ไม่มีป้าย/โลโก้ ไม่เฟดภาพ (ไปแต่งใน CapCut เอง)
    ช็อตที่มี "src" ใช้ต้นฉบับคนละไฟล์ได้ (คลิปรวมหลายเกม) — src_resolver แปลงเป็น path"""
    src, workdir, out = src.resolve(), workdir.resolve(), out.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    infos: dict[Path, dict] = {}
    clips = [c for c in plan_clips if float(c["end"]) > float(c["start"])]
    if not clips:
        raise RuntimeError("ไม่มีช่วงคลิปให้ตัดต่อ")
    n, files = len(clips), []
    texts = [clean_text(c.get("narration", "")) for c in clips]
    narrs = tts_all(texts, workdir, voice, rate, tone, progress, total=30)
    for i, c in enumerate(clips):
        s_path = Path(src_resolver(c["src"])).resolve() if c.get("src") and src_resolver else src
        if s_path not in infos:
            infos[s_path] = probe(s_path)
        text, narr = texts[i], narrs[i]
        progress(30 + (i + 0.5) / n * 69, f"ตัดต่อช่วงที่ {i + 1}/{n}" + (" (สโลว์+เอฟเฟกต์)" if fx and not clean else ""))
        f = workdir / f"clip_{i:03}.mp4"
        render_clip(s_path, infos[s_path], {**c, "narration": text}, narr, f,
                    orig_volume, (subtitles if not clean else False), workdir, layout=layout,
                    extras=not clean, fades=not clean, fx=fx and not clean,
                    brand=None if clean else brand)
        files.append(f)
    progress(99, "รวมคลิปเป็นวิดีโอเดียว")
    seq = list(files)
    if cover and not clean and Path(cover).exists():
        cv = workdir / "cover.mp4"
        try:
            make_cover_clip(Path(cover), files[0], cv)
            seq.insert(0, cv)
        except RuntimeError as e:
            print("ใส่ภาพปกต้นคลิปไม่ได้:", e)
    concat(seq, out, workdir)
    return files


def fmt_time(t: float) -> str:
    t = int(t)
    if t >= 3600:
        return f"{t // 3600}:{t % 3600 // 60:02}:{t % 60:02}"
    return f"{t // 60}:{t % 60:02}"
