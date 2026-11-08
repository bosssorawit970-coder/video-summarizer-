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

TONES = {
    "natural": ("เป็นธรรมชาติ", "Read this Thai text naturally and clearly, like a friendly Thai TikTok narrator"),
    "caster": ("แคสเตอร์เกม ตื่นเต้น", "Read this Thai text like a hyped, energetic Thai esports caster"),
    "story": ("เล่าเรื่อง น่าติดตาม", "Read this Thai text like an engaging Thai storyteller, with natural pauses"),
    "horror": ("เรื่องผี หลอนๆ", "Read this Thai text slowly in a low, eerie, suspenseful whisper-like voice"),
    "bright": ("สดใส ร่าเริง", "Read this Thai text in a bright, cheerful and upbeat voice"),
    "calm": ("สุภาพ นุ่มนวล", "Read this Thai text calmly and warmly, like a gentle documentary narrator"),
}

GEMINI_TTS_MODELS = [m for m in [os.environ.get("GEMINI_TTS_MODEL"), "gemini-3.8-flash-tts",
                                 "gemini-2.5-flash-preview-tts"] if m]
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
    instruction = TONES.get(tone, TONES["natural"])[1]
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": f"{instruction}:\n{text}"}]}],
        "generationConfig": {"responseModalities": ["AUDIO"],
                             "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}},
    }).encode()
    last = "เรียกเสียง Gemini ไม่สำเร็จ"
    for model in GEMINI_TTS_MODELS:
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
                return
        last = "Gemini ไม่ส่งเสียงกลับมา"
    if "โควตา" in last:
        _gemini_off = last
    raise RuntimeError(last)


def reset() -> None:
    """เริ่มงานใหม่ → ลองเสียง Gemini ใหม่ (โควตาอาจกลับมาแล้ว)"""
    global _gemini_off
    _gemini_off = None


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
