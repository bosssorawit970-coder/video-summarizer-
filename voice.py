"""
เสียงพากย์ทางเลือก
  • Gemini TTS — เสียง AI เหมือนคนจริง สั่งอารมณ์ได้ (ใช้คีย์ GEMINI_API_KEY)
  • โคลนเสียงตัวเอง — ThonburianTTS (F5-TTS ภาษาไทย, biodatlab)
    ⚠️ สัญญาอนุญาตโมเดล CC BY-NC-SA 4.0 = ห้ามใช้เชิงพาณิชย์
ถ้าใช้ไม่ได้ (โควตาเต็ม/ไม่มีการ์ดจอ/ติดตั้งไม่สำเร็จ) ผู้เรียกจะถอยไปใช้เสียง Edge TTS เดิม
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

# ───────────────────────── Gemini TTS ─────────────────────────

GEMINI_VOICES = [
    ("Kore", "หญิง เสียงหนักแน่น"),
    ("Leda", "หญิง สดใส"),
    ("Aoede", "หญิง นุ่มสบาย"),
    ("Puck", "ชาย ร่าเริง"),
    ("Charon", "ชาย ทุ้ม น่าเชื่อถือ"),
    ("Fenrir", "ชาย ตื่นเต้น"),
]

# (ชื่อไทย, สไตล์การพูด) — สไตล์เป็น "คำกำกับ" ห้ามให้โมเดลอ่านออกเสียง (ดู _tts_prompt)
TONES = {
    "natural": ("เป็นธรรมชาติ", ""),
    "caster": ("แคสเตอร์เกม ตื่นเต้น", "Hyped, energetic Thai esports caster. Fast, punchy, rising excitement."),
    "story": ("เล่าเรื่อง น่าติดตาม", "Engaging Thai storyteller, warm and expressive, natural pauses between ideas."),
    "horror": ("เรื่องผี หลอนๆ", "Eerie Thai ghost-story narrator, low and suspenseful, slow with tense pauses."),
    "bright": ("สดใส ร่าเริง", "Bright, cheerful, upbeat Thai presenter with a smile in the voice."),
    "calm": ("สุภาพ นุ่มนวล", "Warm, gentle Thai documentary narrator, smooth and sincere."),
}


def _tts_prompt(text: str, tone: str) -> str:
    """สไตล์ใส่เป็นหัวข้อกำกับ + บอกชัดว่าพูดเฉพาะใต้ TRANSCRIPT
    (เดิมเขียนคำสั่งต่อหน้าบท → โมเดลอ่านคำสั่งภาษาอังกฤษออกเสียงไปด้วย)"""
    style = TONES.get(tone, TONES["natural"])[1]
    if not style:
        return text  # ไม่มีสไตล์ = ส่งบทล้วนๆ ปลอดภัยที่สุด
    return ("Synthesize speech for the performance below. Everything above the transcript is direction only, "
            "do NOT speak it. Speak ONLY the Thai lines under #### TRANSCRIPT, word for word.\n\n"
            f"### PERFORMANCE\nStyle: {style}\nLanguage: Thai (th-TH), native Thai pronunciation.\n\n"
            f"#### TRANSCRIPT\n{text}")


def _too_long(seconds: float, text: str) -> bool:
    """เสียงยาวผิดปกติเทียบกับความยาวบท = โมเดลน่าจะอ่านคำกำกับออกมาด้วย"""
    chars = len("".join(text.split()))
    return seconds > chars / 9 + 2.5

def _tts_models() -> list[str]:
    import pipeline as P
    return P.gemini_models("tts") or ["gemini-3.8-flash-tts", "gemini-2.5-flash-preview-tts"]
_pinned: str | None = None   # รุ่นเสียง Gemini ที่ใช้ในงานนี้
_spent: dict[str, str] = {}   # รุ่นที่โควตาฟรีวันนี้หมดแล้ว {รุ่น: วันที่ (เวลาแปซิฟิก)} — แต่ละรุ่นมีโควตาของตัวเอง


def _pt_day() -> str:
    import datetime as _dt
    return (_dt.datetime.utcnow() - _dt.timedelta(hours=8)).date().isoformat()  # โควตารีเซ็ตเที่ยงคืนแปซิฟิก


def _alive_models() -> list[str]:
    return [m for m in _tts_models() if _spent.get(m) != _pt_day()]


def switch_model() -> bool:
    """รุ่นที่ใช้อยู่โควตาวันนี้หมดกลางคลิป แต่ยังมีรุ่นอื่นเหลือ → ปลดล็อก ให้ทำใหม่ทั้งคลิปด้วยรุ่นใหม่"""
    global _pinned, _gemini_off
    if _pinned and _spent.get(_pinned) == _pt_day() and _alive_models():
        _pinned, _gemini_off = None, None
        return True
    return False
_gemini_off: str | None = None   # โควตาเต็ม/ใช้ไม่ได้ → ไม่ต้องลองซ้ำทุกฉากในรอบนี้


def gemini_ready() -> bool:
    return bool((os.environ.get("GEMINI_API_KEY") or "").strip())


def _to_mp3(raw: bytes, mime: str, out: Path, rate: int) -> None:
    """แปลงเสียงที่ Gemini ส่งมา (PCM 24kHz หรือ WAV) เป็น mp3 + ปรับความเร็ว"""
    tmp = out.with_suffix(".raw")
    tmp.write_bytes(raw)
    tempo = max(0.6, min(1.6, 1 + rate / 100))
    if raw[:4] == b"RIFF":
        src = ["-i", str(tmp)]
    else:
        m = re.search(r"rate=(\d+)", mime or "")
        src = ["-f", "s16le", "-ar", m.group(1) if m else "24000", "-ac", "1", "-i", str(tmp)]
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *src, "-af", f"atempo={tempo:.3f}",
                        "-c:a", "libmp3lame", "-q:a", "3", str(out)], check=True)
    finally:
        tmp.unlink(missing_ok=True)


def gemini_tts(text: str, out: Path, voice: str, tone: str = "natural", rate: int = 0) -> None:
    global _gemini_off
    if _gemini_off:
        raise RuntimeError(_gemini_off)
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("ยังไม่ได้ใส่คีย์ Gemini")
    if TONES.get(tone, TONES["natural"])[1]:
        try:
            _gemini_call(_tts_prompt(text, tone), out, voice, rate, key)
            dur = _duration(out)
            if not _too_long(dur, text):
                return
            print(f"เสียง Gemini ยาวผิดปกติ ({dur:.1f} วิ) อาจอ่านคำกำกับออกมา → สร้างใหม่แบบบทล้วน")
        except RuntimeError:
            if _gemini_off:
                raise
    _gemini_call(text, out, voice, rate, key)


def _silences(f: Path) -> list[tuple[float, float]]:
    """ช่วงเงียบในไฟล์เสียง [(เริ่ม, จบ)]"""
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(f), "-af", "silencedetect=noise=-35dB:d=0.15",
                        "-f", "null", "-"], capture_output=True, text=True)
    st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(st, en))


def _cut_points(texts: list[str], dur: float, sil: list[tuple[float, float]]) -> list[float]:
    """จุดตัดระหว่างท่อน: เดาจากสัดส่วนจำนวนตัวอักษร แล้วขยับไปช่วงเงียบที่ใกล้ที่สุด (เงียบนานได้เปรียบ)"""
    chars = [max(1, len("".join(t.split()))) for t in texts]
    total = sum(chars)
    cuts, acc, prev = [], 0, 0.0
    for k in range(len(texts) - 1):
        acc += chars[k]
        exp = dur * acc / total
        tol = max(0.9, 0.4 * dur * chars[k] / total)
        best, score = None, 1e9
        for a, b in sil:
            mid = (a + b) / 2
            if mid <= prev + 0.3 or abs(mid - exp) > tol:
                continue
            sc = abs(mid - exp) - 1.5 * min(b - a, 0.8)
            if sc < score:
                best, score = mid, sc
        cut = best if best is not None else max(prev + 0.3, exp)
        cuts.append(cut)
        prev = cut
    return cuts


def gemini_tts_batch(texts: list[str], outs: list[Path], voice: str, tone: str = "natural", rate: int = 0,
                     progress=None) -> None:
    """สร้างเสียง Gemini ทีละหลายท่อนในคำขอเดียว แล้วตัดแบ่งตามช่วงเงียบ
    (โควตาฟรีนับเป็น "จำนวนครั้งต่อวัน" ราว 10 ครั้ง — เดิมท่อนละ 1 ครั้ง คลิปเดียวก็หมด
    แบบนี้ทั้งคลิปใช้ 1-2 ครั้ง + น้ำเสียงต่อเนื่องเป็นคนเดียวกันทั้งคลิป)"""
    if _gemini_off:
        raise RuntimeError(_gemini_off)
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("ยังไม่ได้ใส่คีย์ Gemini")
    groups, cur, size = [], [], 0
    for k, t in enumerate(texts):
        n = len(t)
        if cur and size + n > 1500:
            groups.append(cur)
            cur, size = [], 0
        cur.append(k)
        size += n
    if cur:
        groups.append(cur)
    style = TONES.get(tone, TONES["natural"])[1]
    for g, idx in enumerate(groups):
        if progress:
            progress(f"สร้างเสียง Gemini ทั้งบทรวดเดียว ({g + 1}/{len(groups)})")
        part = [texts[k].strip() for k in idx]
        body = "\n\n".join(part)
        tmp = outs[idx[0]].with_name(f"gbatch_{g}.mp3")
        prompt = body
        if style or len(idx) > 1:
            prompt = ("Synthesize speech for the performance below. Everything above the transcript is direction only, "
                      "do NOT speak it. Speak ONLY the Thai lines under #### TRANSCRIPT, word for word, "
                      "with a short clear pause between paragraphs.\n\n"
                      f"### PERFORMANCE\nStyle: {style or 'Natural, clear Thai narrator.'}\n"
                      f"Language: Thai (th-TH), native Thai pronunciation.\n\n#### TRANSCRIPT\n{body}")
        _gemini_call(prompt, tmp, voice, rate, key)
        dur = _duration(tmp)
        if _too_long(dur * max(0.6, 1 + rate / 100), body):  # อ่านคำกำกับออกมาด้วย → ส่งบทล้วน
            print(f"เสียง Gemini ยาวผิดปกติ ({dur:.1f} วิ) → สร้างใหม่แบบบทล้วน")
            _gemini_call(body, tmp, voice, rate, key)
            dur = _duration(tmp)
        if len(idx) == 1:
            tmp.replace(outs[idx[0]])
            continue
        cuts = [0.0] + _cut_points(part, dur, _silences(tmp)) + [dur]
        for j, k in enumerate(idx):
            a, b = cuts[j], cuts[j + 1]
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp), "-ss", f"{a:.3f}", "-to", f"{b:.3f}",
                            "-c:a", "libmp3lame", "-q:a", "3", str(outs[k])], check=True)
        tmp.unlink(missing_ok=True)


def _duration(f: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _gemini_call(prompt: str, out: Path, voice: str, rate: int, key: str) -> None:
    global _gemini_off
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["AUDIO"],
                             "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}},
    }).encode()
    global _pinned
    last = "เรียกเสียง Gemini ไม่สำเร็จ"
    # รุ่นที่ใช้ได้แล้วในงานนี้ → ใช้รุ่นเดียวทั้งคลิป (คนละรุ่นเสียงต่างกันชัด ห้ามสลับรุ่นกลางคลิป)
    for model in ([_pinned] if _pinned else _alive_models()):
        tries = 0
        while True:
            req = urllib.request.Request(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                data=body, headers={"Content-Type": "application/json", "x-goog-api-key": key})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                full = e.read().decode("utf-8", "replace")
                msg = full[:200]
                if e.code == 429:
                    # โควตาต่อนาที → รอแล้วลองใหม่ (ไม่ให้เสียงสลับกลางคลิป) · โควตาต่อวันหมด → เลิก
                    m = re.search(r'"retryDelay":\s*"(\d+)', full)
                    if tries < 4 and "PerDay" not in full:
                        tries += 1
                        time.sleep(min(65, int(m.group(1)) + 2 if m else 20 * tries))
                        continue
                    last = "โควตาเสียง Gemini ฟรีเต็ม"
                    if "PerDay" in full:
                        _spent[model] = _pt_day()
                elif e.code in (500, 502, 503, 504) and tries < 3:  # เซิร์ฟเวอร์ยุ่งชั่วคราว → รอแล้วลองซ้ำ
                    tries += 1
                    time.sleep(5 * tries)
                    continue
                elif e.code in (400, 404):  # รุ่นนี้ไม่มี/ไม่รองรับรูปแบบนี้ → ลองรุ่นถัดไป
                    last = f"Gemini เสียงรุ่น {model}: {msg}"
                elif e.code in (401, 403):
                    _gemini_off = "คีย์ Gemini ใช้กับเสียงไม่ได้"
                    raise RuntimeError(_gemini_off) from e
                else:
                    last = f"Gemini เสียง ({e.code}): {msg}"
                data = None
                break
            except Exception as e:
                last = f"Gemini เสียง: {e}"
                data = None
                break
        if data is None:
            continue
        for part in ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                _to_mp3(base64.b64decode(inline["data"]), inline.get("mimeType") or inline.get("mime_type", ""),
                        out, rate)
                _pinned = model
                return
        last = "Gemini ไม่ส่งเสียงกลับมา"
    if "โควตา" in last and not _alive_models():  # ทุกรุ่นหมดแล้ว → ใช้เสียง Edge ทั้งคลิป
        _gemini_off = last + " (ทุกรุ่น — รีเซ็ตราวบ่าย 3 โมงเวลาไทย)"
    elif not _pinned and not _alive_models():
        _gemini_off = "โควตาเสียง Gemini ฟรีเต็ม (ทุกรุ่น — รีเซ็ตราวบ่าย 3 โมงเวลาไทย)"
    raise RuntimeError(_gemini_off or last)


def reset() -> None:
    """เริ่มงานใหม่ → ลองเสียง Gemini ใหม่ (โควตาอาจกลับมาแล้ว)"""
    global _gemini_off, _pinned
    _gemini_off = None
    _pinned = None


def gemini_off() -> bool:
    return bool(_gemini_off)


# ───────────────────────── โคลนเสียง (ThonburianTTS) ─────────────────────────

CLONE_CKPT = os.environ.get("CLONE_CKPT") or "hf://biodatlab/ThonburianTTS/megaF5/mega_f5_last.safetensors"
CLONE_VOCAB = os.environ.get("CLONE_VOCAB") or "hf://biodatlab/ThonburianTTS/megaF5/mega_vocab.txt"
REF_SENTENCE = ("สวัสดีครับทุกคน วันนี้ผมจะมาเล่าเรื่องสนุกๆ ให้ฟัง "
                "ถ้าชอบคลิปนี้ อย่าลืมกดติดตามกันด้วยนะครับ")
_clone = None
_clone_lock = threading.Lock()


def _has_cuda() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except Exception:
        return False


CLONE_SRC = Path(os.environ.get("CLONE_SRC") or Path.home() / ".cache" / "thonburian-tts")


def _install_clone(progress=None) -> None:
    if str(CLONE_SRC) not in sys.path and (CLONE_SRC / "flowtts").is_dir():
        sys.path.insert(0, str(CLONE_SRC))
    try:
        import flowtts.inference  # noqa: F401
        return
    except Exception:
        pass
    if progress:
        progress("กำลังติดตั้งระบบโคลนเสียง (ครั้งแรกใช้เวลา 2-4 นาที)")
    if not (CLONE_SRC / "flowtts").is_dir():
        # clone แทน pip install เพื่อไม่ให้มันติดตั้ง torch/gradio ทับของ Colab
        r = subprocess.run(["git", "clone", "-q", "--depth", "1", "https://github.com/biodatlab/thonburian-tts.git",
                            str(CLONE_SRC)], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError("ดาวน์โหลดระบบโคลนเสียงไม่สำเร็จ: " + (r.stderr or "")[-300:])
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "f5-tts", "cached-path", "vocos", "pydub",
                        "hydra-core", "omegaconf", "soundfile", "librosa"], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ติดตั้งระบบโคลนเสียงไม่สำเร็จ: " + (r.stderr or "")[-300:])
    import importlib
    importlib.invalidate_caches()
    if str(CLONE_SRC) not in sys.path:
        sys.path.insert(0, str(CLONE_SRC))
    import flowtts.inference  # noqa: F401


def _load_clone(progress=None):
    global _clone
    if _clone is not None:
        return _clone
    if not _has_cuda() and not os.environ.get("CLONE_CPU"):
        raise RuntimeError("โคลนเสียงต้องใช้การ์ดจอ (ตอนนี้เครื่องไม่มี)")
    _install_clone(progress)
    if progress:
        progress("กำลังโหลดโมเดลโคลนเสียง (ครั้งแรกดาวน์โหลด ~1.5 GB)")
    from flowtts.inference import AudioConfig, FlowTTSPipeline, ModelConfig
    _clone = FlowTTSPipeline(
        model_config=ModelConfig(language="th", model_type="F5", checkpoint=CLONE_CKPT, vocab_file=CLONE_VOCAB,
                                 vocoder="vocos", device="cuda" if _has_cuda() else "cpu"),
        audio_config=AudioConfig(silence_threshold=-45, cfg_strength=2.5, nfe_step=32, speed=1.0),
        temp_dir=str(Path(os.environ.get("JOBS_DIR") or ".") / "_clone_tmp"))
    return _clone


def clone_tts(text: str, out: Path, ref_wav: Path, ref_text: str, rate: int = 0, progress=None) -> None:
    with _clone_lock:
        pipe = _load_clone(progress)
        wav = out.with_suffix(".clone.wav")
        speed = max(0.7, min(1.4, 1 + rate / 100))
        pipe(text=text, ref_voice=str(ref_wav), ref_text=ref_text or None, output_file=str(wav),
             speed=speed, check_duration=True)
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-c:a", "libmp3lame",
                        "-q:a", "3", str(out)], check=True)
    finally:
        wav.unlink(missing_ok=True)


def prepare_reference(src: Path, out_wav: Path) -> float:
    """แปลงเสียงตัวอย่างเป็น WAV 24kHz mono ตัดช่วงเงียบหัวท้าย ยาวไม่เกิน 12 วินาที คืนความยาว"""
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                    "-af", "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.1,"
                           "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.2,areverse,"
                           "loudnorm=I=-18:TP=-2",
                    "-ac", "1", "-ar", "24000", "-t", "12", str(out_wav)], check=True)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                          str(out_wav)], capture_output=True, text=True).stdout.strip()
    return float(out or 0)
