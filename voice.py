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


def _norm(t: str) -> str:
    """เทียบข้อความ: ตัดช่องว่าง/เครื่องหมาย เหลือตัวอักษรไทย อังกฤษ ตัวเลข"""
    return re.sub(r"[^0-9A-Za-z\u0E01-\u0E4E]", "", t or "").lower()


def _align_cuts(texts: list[str], audio: Path) -> list[float]:
    """หาจุดตัดระหว่างท่อนจาก "คำที่ได้ยินจริง": ถอดเสียง (Whisper ระดับคำ) → เทียบตัวอักษรกับบท
    → ตัดตรงช่องว่างระหว่างคำที่ตรงกับรอยต่อของท่อน · ไม่แน่ใจ → raise (ให้ไปทำทีละท่อนแทน)"""
    import difflib
    import pipeline as P
    try:
        model = P._load_whisper("small")
    except Exception:
        model = P._load_whisper("small", force_cpu=True)
    w16 = audio.with_suffix(".16k.wav")
    P.extract_audio(audio, w16)
    segs, _ = model.transcribe(P.load_wav(w16), language="th", word_timestamps=True, beam_size=5,
                               initial_prompt=" ".join(texts)[:400])
    segs = list(segs)
    w16.unlink(missing_ok=True)
    words = [(w.start, w.end, _norm(w.word)) for sg in segs for w in (sg.words or []) if _norm(w.word)]
    if not words:
        raise RuntimeError("ถอดเสียงไม่ได้")
    S, owner = "", []  # ตัวอักษรของคำที่ได้ยิน → คำที่เท่าไร
    for k, (_, _, w) in enumerate(words):
        S += w
        owner += [k] * len(w)
    T = [_norm(t) for t in texts]
    full = "".join(T)
    sm = difflib.SequenceMatcher(None, full, S, autojunk=False)
    if sm.ratio() < 0.6:
        raise RuntimeError(f"เสียงที่ได้ไม่ตรงกับบท ({sm.ratio():.0%})")
    blocks = sm.get_matching_blocks()

    def to_s(pos: int) -> int:  # ตำแหน่งในบท → ตำแหน่งในคำที่ได้ยิน
        best = None
        for bl in blocks:
            if bl.size and bl.a <= pos < bl.a + bl.size:
                return bl.b + (pos - bl.a)
            if bl.size and bl.a >= pos:
                return bl.b
            best = bl
        return len(S) - 1

    cuts, acc = [], 0
    for t in T[:-1]:
        acc += len(t)
        k = owner[min(len(owner) - 1, to_s(acc))]  # คำแรกของท่อนถัดไป
        prev_end = words[k - 1][1] if k > 0 else words[0][0]
        cuts.append((prev_end + words[k][0]) / 2)
    # ตรวจ: ความยาวแต่ละท่อนต้องสมเหตุผลกับจำนวนตัวอักษร (ต่างกันไม่เกิน 2.5 เท่า)
    end = words[-1][1]
    pts = [0.0] + cuts + [end]
    rate = end / max(1, len(full))
    for t, x0, x1 in zip(T, pts, pts[1:]):
        want = len(t) * rate
        if x1 - x0 < 0.25 or not (want / 2.5 <= x1 - x0 <= want * 2.5 + 0.6):
            raise RuntimeError("ตัดแบ่งท่อนไม่แน่ใจ")
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
        cuts = [0.0] + _align_cuts(part, tmp) + [dur]
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
    globals()["_eleven_off"] = None


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


# ───────────────────────── 🎤 ElevenLabs (เสียงพากย์คุณภาพสูง จ่ายตามตัวอักษร) ─────────────────────────
ELEVEN_API = "https://api.elevenlabs.io/v1"
_eleven_off: str | None = None
_eleven_cache: dict = {}
# รุ่นที่อ่านไทยได้ เรียงจากเสียงดีสุด (โปรแกรมเช็กกับรายการรุ่นจริงของบัญชีก่อนใช้)
ELEVEN_MODEL_ORDER = ["eleven_v4", "eleven_v3", "eleven_multilingual_v2", "eleven_flash_v2_5", "eleven_turbo_v2_5"]
ELEVEN_GUESS = ["eleven_v3", "eleven_flash_v2_5", "eleven_multilingual_v2"]  # ดูรายการรุ่นไม่ได้ (คีย์ไม่ได้เปิด Models) → ลองตามนี้


def eleven_key() -> str:
    return "".join((os.environ.get("ELEVENLABS_API_KEY") or "").split())


def eleven_ready() -> bool:
    return bool(eleven_key())


def _eleven(path: str, body: dict | None = None, timeout: int = 120) -> bytes:
    req = urllib.request.Request(ELEVEN_API + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"xi-api-key": eleven_key(), "Content-Type": "application/json",
                                          "Accept": "*/*"}, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            det = json.loads(raw).get("detail") or {}
            msg = det.get("message") if isinstance(det, dict) else str(det)
            status = det.get("status", "") if isinstance(det, dict) else ""
        except Exception:
            msg, status = raw[:200], ""
        err = RuntimeError(f"ElevenLabs {e.code}: {msg or raw[:200]}")
        err.code, err.status = e.code, status
        raise err from None


def eleven_voices() -> list[dict]:
    """เสียงในบัญชี (รวมเสียงที่กดเพิ่มจาก Voice Library เช่น เสียงคนไทย) — เก็บไว้ 10 นาที"""
    import time as _t
    c = _eleven_cache.get("voices")
    if c and _t.time() - c[0] < 600:
        return c[1]
    out = []
    try:
        data = json.loads(_eleven("/voices", timeout=20))
        for v in data.get("voices") or []:
            lab = v.get("labels") or {}
            desc = " · ".join(x for x in (lab.get("gender"), lab.get("accent") or lab.get("language"), lab.get("age")) if x)
            out.append({"id": v["voice_id"], "name": v.get("name", "?"), "desc": desc})
    except Exception as e:
        print("ดึงรายชื่อเสียง ElevenLabs ไม่ได้:", e)
    _eleven_cache["voices"] = (_t.time(), out)
    return out


def _eleven_model() -> str:
    if "model" in _eleven_cache:
        return _eleven_cache["model"]
    pick = ""
    try:
        models = json.loads(_eleven("/models", timeout=20))
        thai = [m["model_id"] for m in models if m.get("can_do_text_to_speech")
                and any((l.get("language_id") or "").lower().startswith("th") for l in m.get("languages") or [])]
        ranked = [m for m in ELEVEN_MODEL_ORDER if m in thai] + [m for m in thai if m not in ELEVEN_MODEL_ORDER]
        if ranked:
            pick = ranked[0]
    except Exception as e:
        print("ดูรุ่น ElevenLabs ไม่ได้ ใช้รุ่นมาตรฐาน:", e)
    _eleven_cache["model"] = pick
    return pick


def eleven_tts(text: str, out: Path, voice_id: str, rate: int = 0) -> None:
    """ElevenLabs → mp3 · โควตาหมด/คีย์ผิด → จำไว้ ไม่ลองซ้ำทั้งงาน"""
    global _eleven_off
    import time as _t
    if _eleven_off:
        raise RuntimeError(_eleven_off)
    if not eleven_ready():
        raise RuntimeError("ยังไม่ได้ใส่คีย์ ElevenLabs")
    model = _eleven_model() or (_eleven_cache.get("guess") or ELEVEN_GUESS)[0]
    body = {"text": text, "model_id": model,
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.0, "use_speaker_boost": True,
                               "speed": round(max(0.7, min(1.2, 1 + rate / 100)), 2)}}
    if "flash" in model or "turbo" in model:
        body["language_code"] = "th"
    last = None
    for attempt in range(4):
        try:
            data = _eleven(f"/text-to-speech/{voice_id}?output_format=mp3_44100_128", body)
            if len(data) < 500:
                raise RuntimeError("ElevenLabs ส่งเสียงว่างกลับมา")
            out.write_bytes(data)
            return
        except RuntimeError as e:
            last = e
            code, status = getattr(e, "code", 0), getattr(e, "status", "")
            if status in ("quota_exceeded",) or (code == 401 and "quota" in str(e).lower()):
                _eleven_off = "เครดิต ElevenLabs เดือนนี้หมดแล้ว"
                raise RuntimeError(_eleven_off) from None
            if code in (401, 403):
                why = str(e)
                if "permission" in why.lower() or "missing" in why.lower():
                    why += " — คีย์ไม่ได้เปิดสิทธิ์ Text to Speech: สร้างคีย์ใหม่แล้วตั้ง Text to Speech = Access"
                elif "unusual" in why.lower() or "free tier" in why.lower():
                    why += " — แพ็กฟรีถูกบล็อกเมื่อใช้ผ่าน Colab/VPN: ใช้ในคอม หรือแพ็กเสียเงิน"
                _eleven_off = f"ใช้ ElevenLabs ไม่ได้ ({why})"
                raise RuntimeError(_eleven_off) from None
            if code == 400 and "language_code" in body:
                body.pop("language_code")
                continue
            if code in (400, 404, 422) and not _eleven_cache.get("model"):  # รุ่นที่เดาใช้ไม่ได้ → ลองรุ่นถัดไป
                guess = [m for m in (_eleven_cache.get("guess") or ELEVEN_GUESS) if m != body["model_id"]]
                _eleven_cache["guess"] = guess
                if guess:
                    body["model_id"] = guess[0]
                    if "flash" in guess[0] or "turbo" in guess[0]:
                        body["language_code"] = "th"
                    continue
            if code in (400, 404, 422):
                raise
            _t.sleep(3 * (attempt + 1))  # 429 คนใช้เยอะ / 5xx → รอแล้วลองใหม่
        except Exception as e:
            last = e
            _t.sleep(3 * (attempt + 1))
    raise RuntimeError(f"สร้างเสียง ElevenLabs ไม่สำเร็จ ({last})")


def eleven_off() -> bool:
    return bool(_eleven_off)
