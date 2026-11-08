"""
โหมดเกม MLBB: หาช็อตเด็ดจากเสียงประกาศในเกม (Double Kill, Maniac, Savage …)
ร่วมกับช่วงที่เสียงไฟต์ดังขึ้น แล้วให้ AI เขียนบทพากย์แบบแคสเตอร์
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pipeline as P

# (รูปแบบคำในเสียงประกาศ, ป้ายที่แสดงบนจอ, คะแนนความเด็ด)
EVENTS = [
    (r"\bsavage\b", "SAVAGE", 10),
    (r"\bmaniac\b", "MANIAC", 8),
    (r"\bwiped?\s*out\b", "WIPED OUT", 8),
    (r"\btriple\s*kill", "TRIPLE KILL", 6),
    (r"\b(legendary|godlike|unstoppable|rampage|killing\s*spree|monster\s*kill|mega\s*kill)\b",
     "KILLING SPREE", 5),
    (r"\bvictory\b", "VICTORY", 5),
    (r"\bdouble\s*kill", "DOUBLE KILL", 4),
    (r"\blord\b", "LORD", 4),
    (r"\bshut\s*down\b", "SHUTDOWN", 3),
    (r"\bfirst\s*blood\b", "FIRST BLOOD", 3),
    (r"\bturtle\b", "TURTLE", 2),
    (r"(enemy has been slain|you have slain)", "KILL", 2),
]

BEFORE, AFTER = 7.0, 2.5   # ช็อตเริ่มก่อนเสียงประกาศ (จังหวะไฟต์) และจบหลังประกาศ


def loudness(wav: Path, hop: float = 0.5):
    """ความดังของเสียง (dB) ทุก 0.5 วินาที"""
    import numpy as np
    a = P.load_wav(wav)
    n = int(16000 * hop)
    frames = len(a) // n
    if frames == 0:
        return np.zeros(1), hop
    x = a[:frames * n].reshape(frames, n)
    db = 20 * np.log10(np.sqrt((x ** 2).mean(axis=1)) + 1e-6)
    k = np.ones(5) / 5  # เกลี่ยให้เรียบ
    return np.convolve(db, k, mode="same"), hop


def detect_events(wav: Path, model_name: str, duration: float, progress: P.Progress) -> list[dict]:
    """ถอดเสียงประกาศในเกม (ภาษาอังกฤษ) แล้วหาคำสำคัญพร้อมเวลา"""
    progress(0, f"กำลังโหลดโมเดลฟังเสียงเกม ({model_name})")
    try:
        model = P._load_whisper(model_name)
        return _detect(model, wav, duration, progress)
    except Exception as e:
        if not P.has_gpu():
            raise
        print("GPU ใช้ไม่ได้ เปลี่ยนเป็น CPU:", e)
        return _detect(P._load_whisper(model_name, force_cpu=True), wav, duration, progress)


def _detect(model, wav: Path, duration: float, progress: P.Progress) -> list[dict]:
    segments, _ = model.transcribe(
        P.load_wav(wav), language="en", vad_filter=False, word_timestamps=True,
        condition_on_previous_text=False, beam_size=5,
        initial_prompt="First Blood. Double Kill. Triple Kill. Maniac. Savage. "
                       "An enemy has been slain. Wiped out. Shutdown. Lord. Victory.")
    events = []
    for s in segments:
        if duration > 0:
            progress(min(99, s.end / duration * 100),
                     f"ฟังเสียงเกมแล้ว {P.fmt_time(s.end)} / {P.fmt_time(duration)}")
        words = list(s.words or [])
        text = " ".join(w.word.strip() for w in words).lower() if words else s.text.lower()
        for pat, label, score in EVENTS:
            for m in re.finditer(pat, text):
                t = s.start
                if words:  # หาเวลาของคำที่ตรงจริงๆ
                    pos = 0
                    for w in words:
                        pos += len(w.word.strip()) + 1
                        if pos > m.start():
                            t = w.start
                            break
                events.append({"t": round(float(t), 2), "label": label, "score": score})
    # ตัดซ้ำ: ป้ายเดียวกันห่างกันไม่ถึง 3 วินาที = ครั้งเดียวกัน
    events.sort(key=lambda e: e["t"])
    out = []
    for e in events:
        if out and out[-1]["label"] == e["label"] and e["t"] - out[-1]["t"] < 3:
            continue
        out.append(e)
    return out


def pick_clips(events: list[dict], loud, hop: float, duration: float,
               target: float) -> list[dict]:
    import numpy as np
    base = float(np.median(loud)) if len(loud) else 0.0

    def loud_bonus(a, b):
        i, j = int(a / hop), max(int(a / hop) + 1, int(b / hop))
        seg = loud[i:j]
        return max(0.0, (float(seg.mean()) - base) / 3) if len(seg) else 0.0

    cands = []
    if events:
        # รวมเหตุการณ์ต่อเนื่อง (Double → Triple → Maniac) เป็นช็อตเดียว
        for e in sorted(events, key=lambda e: e["t"]):
            a, b = max(0.0, e["t"] - BEFORE), min(duration, e["t"] + AFTER)
            if cands and a <= cands[-1]["end"] + 1.5:
                c = cands[-1]
                c["end"] = max(c["end"], b)
                c["events"].append(e)
            else:
                cands.append({"start": a, "end": b, "events": [e]})
        for c in cands:
            c["events"].sort(key=lambda e: -e["score"])
            top = c["events"][0]
            c["label"], c["mark"] = top["label"], top["t"]
            c["score"] = top["score"] + 0.5 * sum(e["score"] for e in c["events"][1:]) \
                + loud_bonus(c["start"], c["end"])
            c["end"] = min(c["end"], c["start"] + 22)  # ช็อตไม่ยาวเกิน
    else:
        # ไม่ได้ยินเสียงประกาศ → ใช้ช่วงที่เสียงดังที่สุด (ไฟต์)
        order = np.argsort(-loud)
        taken: list[float] = []
        for i in order:
            t = float(i) * hop
            if any(abs(t - x) < 15 for x in taken):
                continue
            taken.append(t)
            cands.append({"start": max(0.0, t - 5), "end": min(duration, t + 3),
                          "label": "", "mark": t, "score": float(loud[i]) - base, "events": []})
            if len(taken) >= 30:
                break

    chosen, total = [], 0.0
    for c in sorted(cands, key=lambda c: -c["score"]):
        if total >= target:
            break
        chosen.append(c)
        total += c["end"] - c["start"]
    chosen.sort(key=lambda c: c["start"])
    return [{"start": round(c["start"], 2), "end": round(c["end"], 2), "label": c["label"],
             "score": round(float(c["score"]), 2),
             "mark": round(c["mark"], 2), "events": [e["label"] for e in c["events"]],
             "narration": ""} for c in chosen]


GAME_PROMPT = """คุณเป็นแคสเตอร์เกม Mobile Legends: Bang Bang (MLBB) ชาวไทย พากย์มันส์ ใช้ศัพท์เกมเมอร์ไทยเป็นธรรมชาติ
ด้านล่างคือช็อตไฮไลต์จากคลิปเกมของผู้เล่น เรียงตามเวลา ระบบตรวจจับจากเสียงประกาศในเกม
{note}
งานของคุณ:
1. ตั้งชื่อคลิปสั้นๆ ดึงดูด สำหรับโพสต์ TikTok (มีอีโมจิได้ 1-2 ตัว)
2. เขียนแคปชันสรุปเกม 2-3 ประโยค พร้อมแฮชแท็ก 3-5 อัน
3. เขียนบทพากย์ช็อตละ 1 ท่อน ภาษาพูด มันส์ เล่าต่อเนื่องเหมือนแคสเตอร์ ท่อนแรกเปิดเรื่อง ท่อนสุดท้ายปิดท้าย
   ความยาวแต่ละท่อนต้องไม่เกินจำนวนตัวอักษรที่กำหนด ห้ามใส่อีโมจิในบทพากย์
   ห้ามแต่งข้อมูลที่ไม่รู้ เช่น ชื่อฮีโร่ฝั่งตรงข้าม หรือสกอร์

ตอบเป็น JSON อย่างเดียว:
{{"title": "...", "summary": "...", "narrations": ["ท่อนช็อต 1", "ท่อนช็อต 2", ...]}}
ต้องมี narrations {n} ท่อนพอดี

ช็อตไฮไลต์:
{shots}"""

TEMPLATES = {
    "SAVAGE": "ซาเวจจจ! เก็บครบห้าศพ โหดเกินต้าน!",
    "MANIAC": "มาเนียค! สี่ศพรวด คุมเกมอยู่หมัด!",
    "WIPED OUT": "กวาดเรียบทั้งทีม ไม่เหลือใครยืน!",
    "TRIPLE KILL": "ทริปเปิ้ลคิล! สามศพติด สวยมาก!",
    "KILLING SPREE": "ฟอร์มร้อนแรง ไล่เก็บไม่หยุด!",
    "VICTORY": "และนี่คือชัยชนะ! จบเกมสวยๆ",
    "DOUBLE KILL": "ดับเบิ้ลคิล! เก็บสองศพในจังหวะเดียว",
    "LORD": "ปิดลอร์ดได้! ได้เปรียบเต็มๆ",
    "SHUTDOWN": "ชัตดาวน์! หยุดตัวตึงฝั่งตรงข้ามได้",
    "FIRST BLOOD": "เฟิร์สบลัด! เปิดเกมก่อนเลย",
    "TURTLE": "เก็บเต่าได้ ทีมได้ทองเพิ่ม",
    "KILL": "เก็บคิลสวยๆ อีกหนึ่ง",
    "": "จังหวะไฟต์เดือด ดูกันชัดๆ",
}


def make_game_plan(clips: list[dict], provider: str, note: str) -> dict:
    if not clips:
        raise RuntimeError("หาช็อตไฮไลต์ไม่เจอ — คลิปอาจไม่มีเสียงเกม ลองใช้โหมดทั่วไปแทน")
    found = [c["label"] for c in clips if c["label"]]
    if provider != "none":
        shots = "\n".join(
            f"{i + 1}. เวลา {P.fmt_time(c['start'])}-{P.fmt_time(c['end'])} "
            f"เหตุการณ์: {', '.join(c['events']) or 'ไฟต์ (เสียงดัง)'} "
            f"(บทพากย์ไม่เกิน {max(20, int((c['end'] - c['start']) * 10))} ตัวอักษร)"
            for i, c in enumerate(clips))
        prompt = GAME_PROMPT.format(
            note=f"ข้อมูลจากผู้เล่น: {note}" if note.strip() else "", n=len(clips), shots=shots)
        try:
            raw = P.ask_ai(provider, prompt)
            data = P._parse_json(raw)
            narr = [P.clean_text(str(x)) for x in data.get("narrations", [])]
            if len(narr) >= len(clips):
                for c, t in zip(clips, narr):
                    c["narration"] = t
                return {"title": str(data.get("title", "")), "summary": str(data.get("summary", "")),
                        "clips": clips}
        except Exception as e:
            print("AI เขียนบทไม่สำเร็จ ใช้บทสำเร็จรูปแทน:", e)
    for c in clips:
        c["narration"] = TEMPLATES.get(c["label"], TEMPLATES[""])
    best = max(found, key=lambda l: next(s for _, lb, s in EVENTS if lb == l), default="")
    return {"title": f"{best.title()} ในเกม MLBB 🔥" if best else "ไฮไลต์เกม MLBB 🔥",
            "summary": f"ไฮไลต์เกมนี้: {', '.join(dict.fromkeys(found)) or 'ไฟต์เดือดๆ'}\n#MLBB #MobileLegends #ไฮไลต์",
            "clips": clips}
