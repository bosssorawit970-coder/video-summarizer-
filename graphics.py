"""
โมชันกราฟิกเล็กๆ ช่วยให้คนดูเข้าใจ (โหมดข้อความ → คลิป) วาดด้วย libass (.ass) ทับบนภาพ
  stat     ตัวเลขสำคัญ นับขึ้น + หน่วย + คำอธิบาย          {"type":"stat","value":"1","unit":"มม./ปี","label":"ฝนเฉลี่ยต่อปี"}
  compare  แท่งเปรียบเทียบ ค่อยๆ ยืดออก                    {"type":"compare","unit":"มม.","items":[{"label":"อาตากามา","value":1},…]}
  list     หัวข้อย่อยทีละข้อ                               {"type":"list","items":["ไม่มีฝน","ไม่มีพืช"]}
  keyword  คำสำคัญในกล่องสีเด้งขึ้น                         {"type":"keyword","text":"แห้งแล้งที่สุดในโลก"}
พร้อมเสียงเอฟเฟกต์เบาๆ (วูบ/ป๊อป/ติ๊ก/ติ๊ง) ที่สร้างด้วย ffmpeg — ปิดได้ในหน้าตรวจบท
"""
from __future__ import annotations

import re

import pipeline as P

TYPES = {"stat": "ตัวเลขเด่น", "compare": "แท่งเปรียบเทียบ", "list": "หัวข้อย่อย", "keyword": "คำสำคัญ",
         "score": "ป้ายสกอร์"}
ACCENTS = ["FFD43B", "4DD4FF", "FF7AB6", "7CF29A"]
CARD, WHITE, DARK = "0B1020", "FFFFFF", "111318"
MUTED, TRACK = "C9D1E0", "2A3247"  # ตัวหนังสือรอง · รางแท่งกราฟ


def text_w(text: str, px: float) -> float:
    """กว้างของข้อความ (พิกเซล) ไว้วาดกล่องมุมมนพอดีตัวหนังสือ — วัดจากฟอนต์จริงถ้ามี ไม่งั้นประมาณ"""
    try:
        from PIL import ImageFont
        f = None
        for c in (P.FONT_DIR / "Kanit-Bold.ttf", P.FONT_DIR / "Kanit-SemiBold.ttf"):
            if c.exists():
                f = str(c)
                break
        f = f or P.thai_font_file(True)
        if f:
            import re as _re
            base = _re.sub("[\u0E31\u0E34-\u0E3A\u0E47-\u0E4E]", "", text)  # สระบน/ล่าง วรรณยุกต์ ไม่กินที่
            ft = ImageFont.truetype(f, 100)
            asc, desc = ft.getmetrics()  # libass ย่อฟอนต์ให้ (ascent+descent) = ขนาด \\fs
            return ft.getlength(base) * px / (asc + desc) * 1.03
    except Exception:
        pass
    return len(text) * px * 0.52

GRAPHIC_RULES = """- "graphic": an optional small motion graphic that helps viewers UNDERSTAND this scene, or null.
  Use it only when the narration has a number, a comparison, a list of points, or one key idea — roughly 1 in 3 scenes, never two "keyword" in a row.
  All text in THAI, short. Numbers must be copied exactly from the narration — never invent or estimate numbers.
  {"type":"stat","value":"1","unit":"มม./ปี","label":"ฝนเฉลี่ยต่อปี"}   (one key number from the narration)
  {"type":"compare","unit":"มม.","items":[{"label":"อาตากามา","value":1},{"label":"กรุงเทพฯ","value":1500}]}   (2-4 numbers stated in the narration)
  {"type":"list","items":["ไม่มีฝน","ไม่มีพืช","คล้ายดาวอังคาร"]}   (2-4 points, 2-5 words each)
  {"type":"keyword","text":"แห้งแล้งที่สุดในโลก"}   (one key phrase, 2-6 words)
  {"type":"score","left":"บาร์ซ่า","right":"ลิเวอร์พูล","a":3,"b":0}   (a match/vote result stated in the narration, short side names)"""


def _num(v) -> float | None:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _digits(text: str) -> set[str]:
    return {re.sub(r"[,\s]", "", m) for m in re.findall(r"\d[\d,]*(?:\.\d+)?", text or "")}


def clean(g, narration: str = "", strict: bool = True) -> dict | None:
    """ตรวจ/ทำความสะอาดกราฟิกที่ AI ให้มา — strict: ตัวเลขต้องมีอยู่จริงในบท (กัน AI แต่งตัวเลข)
    strict=False: ผู้ใช้แก้เองในหน้าเว็บ เชื่อตามที่พิมพ์"""
    if not isinstance(g, dict):
        return None
    t = str(g.get("type") or "").lower()
    nums = _digits(narration)
    txt = lambda v, n=24: P.clean_text(str(v or ""))[:n]  # noqa: E731
    if t == "stat":
        value = str(g.get("value") or "").strip()
        if not value or (strict and _num(value) is not None and re.sub(r"[,\s]", "", value) not in nums):
            return None
        return {"type": "stat", "value": value[:16], "unit": txt(g.get("unit"), 14), "label": txt(g.get("label"), 30)}
    if t == "compare":
        items = []
        for it in (g.get("items") or [])[:4]:
            v = _num((it or {}).get("value")) if isinstance(it, dict) else None
            if v is None or v < 0:
                continue
            if strict and re.sub(r"\.0$", "", f"{v:g}") not in {re.sub(r"\.0$", "", n) for n in nums}:
                continue  # ตัวเลขไม่มีในบท = AI แต่งเอง → ไม่ใช้
            items.append({"label": txt(it.get("label"), 18), "value": v})
        return {"type": "compare", "unit": txt(g.get("unit"), 10), "items": items} if len(items) >= 2 else None
    if t == "list":
        items = [txt(x, 28) for x in (g.get("items") or [])[:4] if txt(x)]
        return {"type": "list", "items": items} if len(items) >= 2 else None
    if t == "keyword":
        text = txt(g.get("text"), 30)
        return {"type": "keyword", "text": text} if text else None
    if t == "score":
        a, b = _num(g.get("a")), _num(g.get("b"))
        left, right = txt(g.get("left"), 14), txt(g.get("right"), 14)
        if a is None or b is None or not left or not right or a < 0 or b < 0:
            return None
        if strict and not ({f"{a:g}", f"{b:g}"} <= nums | {"0"}):
            return None  # สกอร์ไม่มีในบท = AI แต่งเอง
        return {"type": "score", "left": left, "right": right, "a": int(a), "b": int(b)}
    return None


_SKIP = set("เพียง มี ประมาณ กว่า ถึง ราว เกือบ แค่ ได้ ถึง ทั้งหมด เป็น คือ ที่ ของ และ ใน กับ".split())


def guess(narration: str) -> dict | None:
    """ไม่มี AI: ถ้าบทมีตัวเลขเด่น ทำกราฟิกตัวเลขให้ (ตัวเลข + หน่วยที่ตามมา + คำนำหน้า)"""
    text = narration or ""
    try:
        from pythainlp.tokenize import word_tokenize
        toks = [t for t in word_tokenize(text, engine="newmm", keep_whitespace=False) if t.strip()]
    except Exception:
        toks = re.findall(r"\d[\d,]*(?:\.\d+)?|[^\s\d]+", text)
    # รวมตัวเลขที่ถูกตัดแยก เช่น "12" "," "000"
    merged: list[str] = []
    for t in toks:
        if merged and re.fullmatch(r"[\d,.]+", t) and re.fullmatch(r"\d[\d,.]*", merged[-1]) and \
                (merged[-1].endswith((",", ".")) or t.startswith((",", "."))):
            merged[-1] += t
        else:
            merged.append(t)
    for k, t in enumerate(merged):
        m = re.fullmatch(r"(\d[\d,]*(?:\.\d+)?)([^\d]*)", t)
        if not m:
            continue
        value, rest = m.group(1), m.group(2)
        if re.fullmatch(r"(25|19|20)\d\d", value.replace(",", "")):
            continue  # น่าจะเป็นปี
        unit = rest
        nxt = merged[k + 1:k + 4]
        if not unit and nxt and re.search(r"[ก-๙A-Za-z%]", nxt[0]):
            unit = nxt[0]
            if len(nxt) >= 3 and nxt[1] == "ต่อ":
                unit += "/" + nxt[2]
        if len(value.replace(",", "")) < 2 and not unit:
            continue
        unit = re.split(r"(?<=[ก-๙])(?=ที่|และ|ซึ่ง|แต่|ของ|เลย|เท่านั้น|เมื่อ)", unit)[0]
        before = [w for w in merged[max(0, k - 4):k] if w not in _SKIP and re.search(r"[ก-๙A-Za-z]", w)]
        label = "".join(before[-2:])
        if len(label) > 18:  # ตัดคำไม่ได้ (ไม่มีตัวตัดคำ) → ไม่ใส่คำอธิบาย ดีกว่าตัดกลางคำ
            label = ""
        return {"type": "stat", "value": value, "unit": unit[:14], "label": label}
    return None


def summary(g: dict | None) -> str:
    if not g:
        return ""
    t = g.get("type")
    if t == "stat":
        return f"{g.get('value', '')} {g.get('unit', '')} — {g.get('label', '')}".strip(" —")
    if t == "compare":
        return " vs ".join(f"{i['label']} {i['value']:g}" for i in g.get("items", []))
    if t == "list":
        return " · ".join(g.get("items", []))
    if t == "score":
        return f"{g.get('left')} {g.get('a')} - {g.get('b')} {g.get('right')}"
    return g.get("text", "")


# ───────────────────────── วาด (ASS) ─────────────────────────

def _c(hex_rgb: str, alpha: int = 0) -> str:
    return P._ass_color(hex_rgb, alpha) + "&"


def _rect(w: float, h: float, r: float = 0) -> str:
    """สี่เหลี่ยมมุมมน (คำสั่งวาดของ ASS)"""
    w, h = int(w), int(h)
    r = int(min(r, w / 2, h / 2))
    if r <= 0:
        return f"m 0 0 l {w} 0 {w} {h} 0 {h}"
    k = int(r * 0.45)
    return (f"m {r} 0 l {w - r} 0 b {w - k} 0 {w} {k} {w} {r} l {w} {h - r} b {w} {h - k} {w - k} {h} {w - r} {h} "
            f"l {r} {h} b {k} {h} 0 {h - k} 0 {h - r} l 0 {r} b 0 {k} {k} 0 {r} 0")


def _fmt(v: float, like: str) -> str:
    dec = len(like.split(".")[1]) if "." in like else 0
    s = f"{v:,.{dec}f}" if ("," in like or abs(v) >= 10000) else f"{v:.{dec}f}"
    return s


class _Draw:
    def __init__(self, ass: "P.Ass", t0: float, t1: float):
        self.ass, self.t0, self.t1 = ass, t0, t1
        self.W, self.H = ass.W, ass.H
        self.vertical = ass.H > ass.W
        self.s = min(ass.W, ass.H) / 1080 * (1.3 if ass.W > ass.H else 1.0)  # แนวนอน: กราฟิกใหญ่ขึ้นให้อ่านง่าย
        self.font = P.thai_font()
        self.bottom = 0.69

    def ev(self, layer: int, a: float, b: float, tags: str, body: str, style: str = "Sub") -> None:
        a, b = max(self.t0, a), min(self.t1, b)
        if b - a > 0.01:
            self.ass.events.append(f"Dialogue: {layer},{P._ass_time(a)},{P._ass_time(b)},{style},,0,0,0,,{{{tags}}}{body}")

    def shape(self, layer, a, b, x, y, draw, color, alpha=0, extra="") -> None:
        pos = "" if "\\move(" in extra else f"\\pos({int(x)},{int(y)})"
        self.ev(layer, a, b, f"\\an7{pos}\\bord0\\shad0\\1c{_c(color)}\\1a&H{alpha:02X}&{extra}\\p1",
                draw + "{\\p0}")

    def text(self, layer, a, b, x, y, text, size, color=WHITE, align=7, extra="", bold=True, raw=False) -> None:
        body = text if raw else P.ass_text(text)
        pos = "" if "\\move(" in extra else f"\\pos({int(x)},{int(y)})"
        self.ev(layer, a, b, f"\\an{align}{pos}\\fn{self.font}\\fs{int(size * self.s)}\\b{1 if bold else 0}"
                             f"\\bord{max(2, int(3 * self.s))}\\3c{_c('000000')}\\shad0\\1c{_c(color)}{extra}", body)

    def clean(self, layer, a, b, x, y, text, size, color=WHITE, align=7, extra="", raw=False) -> None:
        """ตัวหนังสือแบบใหม่: ไม่มีขอบดำหนา (อยู่บนการ์ดเข้มแล้ว) มีเงานุ่มๆ นิดเดียว"""
        body = text if raw else P.ass_text(text)
        pos = "" if "\\move(" in extra else f"\\pos({int(x)},{int(y)})"
        self.ev(layer, a, b, f"\\an{align}{pos}\\fn{self.font}\\fs{int(size * self.s)}\\b1\\bord0"
                             f"\\shad{max(1, int(2 * self.s))}\\4c{_c('000000')}\\4a&H90&\\1c{_c(color)}{extra}", body)

    def pill(self, layer, a, b, x, y, w, h, color, alpha=0, extra="") -> None:
        self.shape(layer, a, b, x, y, _rect(w, h, h / 2), color, alpha, extra)

    def card(self, h: float) -> tuple[float, float, float, float]:
        """การ์ดแบบกระจกเข้ม: เงานุ่มใต้การ์ด + ขอบบางสว่าง + แถบสีเล็กมุมบน · เลื่อนขึ้นเบาๆ ตอนโผล่
        แนวตั้ง = ส่วนล่างของภาพ (เหนือซับ) · แนวนอน = มุมขวา"""
        s = self.s
        if self.vertical:
            w = 920 * s
            x0 = (self.W - w) / 2
            y0 = self.H * self.bottom - h * s
        else:
            w = 760 * s
            x0 = self.W - w - 60 * s
            y0 = self.H * 0.74 - h * s
        hh = h * s
        a, r = self.t0, 40 * s
        rise = int(26 * s)
        def mv(x, y):
            return f"\\move({int(x)},{int(y + rise)},{int(x)},{int(y)},0,320)\\fad(200,250)"
        self.shape(0, a, self.t1, 0, 0, _rect(w, hh, r), "000000", 0x70,
                   mv(x0, y0 + 18 * s) + f"\\blur{int(22 * s)}")                       # เงานุ่ม
        self.shape(0, a, self.t1, 0, 0, _rect(w + 3 * s, hh + 3 * s, r + 2 * s), "FFFFFF", 0xD8,
                   mv(x0 - 1.5 * s, y0 - 1.5 * s))                                    # ขอบบางสว่าง
        self.shape(1, a, self.t1, 0, 0, _rect(w, hh, r), CARD, 0x30, mv(x0, y0))       # ตัวการ์ด
        self.shape(2, a + 0.15, self.t1, 0, 0, _rect(64 * s, 8 * s, 4 * s), ACCENTS[0], 0,
                   mv(x0 + 44 * s, y0 + 24 * s) + "\\fscx0\\t(0,350,\\fscx100)")    # แถบสีเล็กมุมบน
        return x0, y0, w, hh


# ───────────────────────── เสียงเอฟเฟกต์เบาๆ ตอนกราฟิกขึ้น ─────────────────────────
# สร้างด้วย ffmpeg ทั้งหมด (ไม่ใช้ไฟล์จากเน็ต = ไม่ติดลิขสิทธิ์)  ชื่อ: (คำสั่ง lavfi, filter, ความดัง)
SFX = {
    "whoosh": ("anoisesrc=d=0.4:c=pink:a=0.6:r=44100",
               "highpass=f=700,lowpass=f=6000,afade=t=in:st=0:d=0.22:curve=exp,afade=t=out:st=0.22:d=0.18", 0.9),
    "pop": ("aevalsrc='sin(2*PI*(520*t+4200*t*t))*exp(-38*t)':d=0.12:s=44100", "lowpass=f=4000", 0.38),
    "tick": ("aevalsrc='sin(2*PI*2300*t)*exp(-260*t)':d=0.03:s=44100", "highpass=f=900", 0.18),
    "ding": ("aevalsrc='(0.6*sin(2*PI*1320*t)+0.4*sin(2*PI*1980*t))*exp(-5.5*t)':d=0.7:s=44100", "anull", 0.22),
    "hit": ("aevalsrc='sin(2*PI*(110-70*t)*t)*exp(-7*t)+0.25*sin(2*PI*55*t)*exp(-4*t)':d=0.6:s=44100", "lowpass=f=900", 0.7),
    "rise": ("aevalsrc='sin(2*PI*(260*t+700*t*t))*min(1,t*12)*exp(-2.6*t)':d=0.65:s=44100", "lowpass=f=2500", 0.25),
    # ── เสียงประกอบตามเนื้อหา (AI เลือกต่อฉาก) ──
    "boom": ("aevalsrc='sin(2*PI*(70-40*t)*t)*exp(-2.2*t)+0.4*sin(2*PI*35*t)*exp(-1.5*t)':d=1.8:s=44100",
             "lowpass=f=500,aecho=0.6:0.5:120:0.3", 0.85),
    "beep": ("aevalsrc='sin(2*PI*1050*t)*(lt(t,0.1)+between(t,0.22,0.32))':d=0.4:s=44100", "lowpass=f=5000", 0.22),
    "riser": ("anoisesrc=d=1.6:c=white:a=0.5:r=44100",
              "highpass=f=300,lowpass=f=5000,volume='pow(t/1.6,2)':eval=frame,afade=t=out:st=1.5:d=0.1", 0.5),
    "heart": ("aevalsrc='sin(2*PI*52*t)*(exp(-28*t)+0.75*gte(t,0.24)*exp(-28*(t-0.24)))':d=0.7:s=44100", "lowpass=f=160", 1.2),
    "shutter": ("anoisesrc=d=0.12:c=white:a=0.8:r=44100", "highpass=f=1500,afade=t=out:st=0.01:d=0.1", 0.35),
    "glitch": ("aevalsrc='sin(2*PI*(400+1800*gt(sin(2*PI*23*t),0))*t)*gt(sin(2*PI*11*t),-0.3)*0.6':d=0.35:s=44100",
               "highpass=f=200,lowpass=f=5000", 0.25),
}

# ───────────────────────── เสียงบรรยากาศ (เบาๆ คลอตลอดฉาก วนซ้ำได้) ─────────────────────────
# {ชื่อ: (ชื่อไทย, [แหล่งเสียง lavfi], กราฟ filter)} — สร้างด้วย ffmpeg ทั้งหมด ไม่ติดลิขสิทธิ์
AMB = {
    "space": ("🌌 อวกาศ (หึ่งลึกๆ)", ["anoisesrc=d=10:c=brown:a=0.5:r=44100",
              "aevalsrc='0.35*sin(2*PI*55*t)*(0.7+0.3*sin(2*PI*0.2*t))+0.2*sin(2*PI*82.5*t)':d=10:s=44100"],
              "[0]lowpass=f=220[n];[1]lowpass=f=300[d];[n][d]amix=inputs=2:normalize=0"),
    "signal": ("📡 สัญญาณวิทยุ ซ่า+บี๊บ", ["anoisesrc=d=9.6:c=white:a=0.15:r=44100",
               "aevalsrc='0.35*sin(2*PI*1050*t)*lt(mod(t,1.2),0.1)+0.25*sin(2*PI*1050*t)*between(mod(t,1.2),0.2,0.3)':d=9.6:s=44100"],
               "[0]bandpass=f=1800:width_type=h:w=1800,tremolo=f=7:d=0.4[n];[n][1]amix=inputs=2:normalize=0"),
    "tension": ("😰 ตึงเครียด/ลึกลับ", ["aevalsrc='0.4*sin(2*PI*65*t)+0.3*sin(2*PI*65.7*t)+0.15*sin(2*PI*97.5*t)*(0.6+0.4*sin(2*PI*0.1*t))':d=10:s=44100",
                "anoisesrc=d=10:c=brown:a=0.15:r=44100"],
                "[0]lowpass=f=400[d];[1]lowpass=f=250[n];[d][n]amix=inputs=2:normalize=0"),
    "heart": ("💓 หัวใจเต้น (ลุ้น)", ["aevalsrc='sin(2*PI*52*t)*(exp(-28*mod(t,0.9))+0.75*gte(mod(t,0.9),0.24)*exp(-28*(mod(t,0.9)-0.24)))':d=9:s=44100"],
              "[0]lowpass=f=160,volume=2"),
    "clock": ("⏰ นาฬิกาเดิน", ["aevalsrc='0.6*sin(2*PI*(2100+600*mod(floor(t),2))*t)*exp(-180*mod(t,1))':d=10:s=44100"],
              "[0]highpass=f=700"),
    "wind": ("🌬 ลม/หนาว", ["anoisesrc=d=10:c=pink:a=0.6:r=44100"],
             "[0]bandpass=f=450:width_type=o:w=2,tremolo=f=0.2:d=0.8,lowpass=f=1600"),
    "rain": ("🌧 ฝนตก", ["anoisesrc=d=10:c=white:a=0.25:r=44100", "anoisesrc=d=10:c=pink:a=0.3:r=44100"],
             "[0]highpass=f=900,lowpass=f=7000[a];[1]lowpass=f=400[b];[a][b]amix=inputs=2:normalize=0"),
    "waves": ("🌊 ทะเล/คลื่น", ["anoisesrc=d=10:c=brown:a=0.6:r=44100"],
              "[0]lowpass=f=700,volume='0.25+0.75*pow(sin(PI*t/5),2)':eval=frame"),
    "fire": ("🔥 ไฟปะทุ", ["anoisesrc=d=10:c=brown:a=0.35:r=44100", "aevalsrc='gt(random(0),0.9992)*(random(1)*1.6-0.8)':d=10:s=44100"],
             "[0]lowpass=f=320[n];[1]highpass=f=1200,lowpass=f=6000[c];[n][c]amix=inputs=2:normalize=0"),
    "war": ("💥 สงคราม (ระเบิดไกลๆ)", ["anoisesrc=d=10:c=brown:a=0.45:r=44100",
            "aevalsrc='sin(2*PI*38*t)*(exp(-2.5*mod(t,3.3))+0.6*exp(-3*mod(t+1.7,5)))':d=10:s=44100"],
            "[0]lowpass=f=140[n];[1]lowpass=f=120[b];[n][b]amix=inputs=2:normalize=0"),
    "night": ("🦗 กลางคืน/จิ้งหรีด", ["aevalsrc='0.3*sin(2*PI*4400*t)*gt(sin(2*PI*28*t),0.3)*gt(mod(t,1.3),0.75)':d=10.4:s=44100",
              "anoisesrc=d=10.4:c=pink:a=0.08:r=44100"],
              "[0]bandpass=f=4400:width_type=h:w=800[c];[1]lowpass=f=600[n];[c][n]amix=inputs=2:normalize=0"),
    "magic": ("✨ เวทมนตร์/ความฝัน", ["aevalsrc='0.2*sin(2*PI*1760*t)*(0.5+0.5*sin(2*PI*3*t))+0.15*sin(2*PI*2637*t)*(0.5+0.5*sin(2*PI*2.3*t))+0.1*sin(2*PI*880*t)':d=10:s=44100"],
              "[0]aecho=0.8:0.7:180|370:0.4|0.25"),
}
FX_NAMES = {"boom": "💥 ตึ้ง! (เปิดเผย/ช็อก)", "riser": "📈 ไต่ขึ้น (ก่อนเฉลย)", "beep": "📟 บี๊บ บี๊บ",
            "heart": "💓 หัวใจเต้น 1 ที", "shutter": "📸 ชัตเตอร์กล้อง", "glitch": "📺 สัญญาณรบกวน",
            "ding": "🔔 ติ๊ง", "whoosh": "💨 ฟิ้ว", "pop": "🫧 ป๊อป"}


def make_amb(workdir, name: str):
    """สร้างไฟล์เสียงบรรยากาศ (ความดังมาตรฐาน -26 LUFS วนซ้ำได้) คืน path หรือ None"""
    if name not in AMB:
        return None
    f = workdir / f"amb_{name}.wav"
    if not f.exists():
        _, ins, graph = AMB[name]
        args = []
        for src in ins:
            args += ["-f", "lavfi", "-i", src]
        P.run(["ffmpeg", "-y", "-hide_banner", *args, "-filter_complex", graph + ",loudnorm=I=-26:TP=-5[o]",
               "-map", "[o]", "-ac", "2", "-ar", "44100", str(f)])
    return f


def make_sfx(workdir) -> dict:
    """สร้างไฟล์เสียงเอฟเฟกต์ไว้ใน workdir (ครั้งเดียว) คืน {ชื่อ: (path, ความดัง)}"""
    out = {}
    for name, (src, af, vol) in SFX.items():
        f = workdir / f"gsfx_{name}.wav"
        if not f.exists():
            P.run(["ffmpeg", "-y", "-hide_banner", "-f", "lavfi", "-i", src, "-af", af, "-ac", "2", str(f)])
        out[name] = (f, vol)
    return out


def render(ass: "P.Ass", g: dict | None, t0: float, t1: float, bottom: float = 0.69) -> list[tuple[float, str]]:
    """วาดกราฟิกลงไฟล์ซับ ตั้งแต่ t0 ถึง t1 (วินาทีในฉาก) คืนจังหวะเสียงเอฟเฟกต์ [(เวลา, ชื่อเสียง)]
    bottom = ขอบล่างของกรอบกราฟิก (สัดส่วนความสูงจอ แนวตั้ง)"""
    g = clean(g, "", strict=False)
    if not g or t1 - t0 < 1.2:
        return []
    cues: list[tuple[float, str]] = []
    d = _Draw(ass, t0, t1)
    d.bottom = bottom
    s, fade = d.s, "\\fad(200,250)"
    t = g["type"]
    pop_in = "\\fscx70\\fscy70\\t(0,220,0.5,\\fscx100\\fscy100)"
    if t == "stat":
        has_label = bool(g.get("label"))
        x0, y0, w, h = d.card(330 if has_label else 250)
        cues.append((t0, "whoosh"))
        cx = x0 + w / 2
        unit = g.get("unit") or ""
        val = _num(g["value"])
        steps, dur = 16, 0.9
        unit_tag = f"{{\\fs{int(58 * s)}\\1c{_c(WHITE)}}} {P.ass_text(unit)}" if unit else ""
        ny = y0 + 52 * s
        glow = f"\\blur{int(14 * s)}\\1a&H90&"
        if val is not None and abs(val) > 0:
            for k in range(steps):  # นับเลขขึ้น (ค่อยๆ ช้าลงตอนใกล้ถึง)
                p = 1 - (1 - (k + 1) / steps) ** 3
                a = t0 + 0.25 + dur * k / steps
                b = t0 + 0.25 + dur * (k + 1) / steps if k < steps - 1 else t1
                num = P.ass_text(_fmt(val * p, g["value"]))
                end = "\\fad(0,250)" if k == steps - 1 else ""
                d.clean(3, a, b, cx, ny, num, 160, ACCENTS[0], 8, glow + end, raw=True)   # เรืองแสงหลังตัวเลข
                d.clean(4, a, b, cx, ny, num + unit_tag, 160, ACCENTS[0], 8, end, raw=True)
                if k % 3 == 0 and k < steps - 1:
                    cues.append((a, "tick"))
            cues.append((t0 + 0.25 + dur, "ding"))
        else:
            d.clean(4, t0 + 0.25, t1, cx, ny, P.ass_text(g["value"]) + unit_tag, 130, ACCENTS[0], 8,
                    pop_in + fade, raw=True)
            cues.append((t0 + 0.25, "pop"))
        if has_label:
            ly = y0 + h - 44 * s
            d.clean(4, t0 + 0.6, t1, cx, ly, g["label"], 52, MUTED, 2,
                    f"\\move({int(cx)},{int(ly + 24 * s)},{int(cx)},{int(ly)},0,300){fade}")
    elif t == "compare":
        items = g["items"][:4]
        row = 132
        x0, y0, w, h = d.card(78 + row * len(items))
        cues.append((t0, "whoosh"))
        top = max(i["value"] for i in items) or 1
        pad = 56 * s
        maxw = w - 2 * pad
        unit = g.get("unit") or ""
        for k, it in enumerate(items):
            a = t0 + 0.3 + 0.35 * k
            y = y0 + (56 + row * k) * s
            color = ACCENTS[k % len(ACCENTS)]
            cues.append((a, "rise"))
            label = f"{_fmt(it['value'], str(it['value']) if it['value'] % 1 else '0')} {unit}".strip()
            d.clean(4, a, t1, x0 + pad, y, it["label"], 46, WHITE, 7, fade)
            d.clean(4, a + 0.5, t1, x0 + w - pad, y, label, 46, color, 9, fade)
            by = y + 66 * s
            d.pill(3, a, t1, x0 + pad, by, maxw, 22 * s, TRACK, 0x20, fade)          # ราง
            bw = max(22 * s, maxw * it["value"] / top)
            d.pill(4, a, t1, x0 + pad, by, bw, 22 * s, color, 0, f"\\fscx0\\t(0,750,0.5,\\fscx100){fade}")
    elif t == "list":
        items = g["items"][:4]
        row = 100
        x0, y0, w, h = d.card(70 + row * len(items))
        cues.append((t0, "whoosh"))
        for k, item in enumerate(items):
            a = t0 + 0.3 + 0.45 * k
            cues.append((a, "pop"))
            y = y0 + (48 + row * k) * s
            x = x0 + 56 * s
            color = ACCENTS[k % len(ACCENTS)]
            dot = 58 * s
            d.shape(3, a, t1, x, y, _rect(dot, dot, dot / 2), color, 0,
                    "\\org(0,0)\\fscx0\\fscy0\\t(0,220,0.5,\\fscx100\\fscy100)" + fade)       # วงกลมเลขข้อ
            d.clean(4, a + 0.08, t1, x + dot / 2, y + dot / 2, str(k + 1), 36, DARK, 5, "\\shad0" + fade)
            tx = x + dot + 28 * s
            d.clean(4, a, t1, tx, y + dot / 2, item, 54, WHITE, 4,
                    f"\\move({int(tx - 36 * s)},{int(y + dot / 2)},{int(tx)},{int(y + dot / 2)},0,280)" + fade)
    elif t == "keyword":
        cx = d.W / 2 if d.vertical else d.W - 440 * s
        cy = d.H * ((bottom - 0.07) if d.vertical else 0.66)
        size = 84 if len(g["text"]) <= 12 else 72 if len(g["text"]) <= 18 else 60
        tw = text_w(g["text"], size * s)
        pw, ph = tw + 96 * s, size * s * 1.55
        a = t0 + 0.25
        zoom = "\\fscx60\\fscy60\\t(0,200,0.5,\\fscx104\\fscy104)\\t(200,320,\\fscx100\\fscy100)"
        d.shape(1, a, t1, cx - pw / 2, cy - ph / 2 + 14 * s, _rect(pw, ph, ph / 2), "000000", 0x60,
                f"\\blur{int(18 * s)}" + fade)
        d.ev(2, a, t1, f"\\an5\\pos({int(cx)},{int(cy)})\\bord0\\shad0\\1c{_c(ACCENTS[0])}\\p1" + zoom + fade,
             _rect(pw, ph, ph / 2).replace("m 0 0", "m 0 0", 1) + "{\\p0}")
        d.clean(3, a, t1, cx, cy, g["text"], size, DARK, 5, "\\shad0" + zoom + fade)
        cues.append((a, "pop"))
    elif t == "score":
        x0, y0, w, h = d.card(250)
        cues.append((t0, "whoosh"))
        cx, cy = x0 + w / 2, y0 + 76 * s
        d.clean(4, t0 + 0.2, t1, x0 + w * 0.2, cy, g["left"], 44, MUTED, 8, fade)
        d.clean(4, t0 + 0.2, t1, x0 + w * 0.8, cy, g["right"], 44, MUTED, 8, fade)
        for k, (v, x) in enumerate(((g["a"], x0 + w * 0.2), (g["b"], x0 + w * 0.8))):
            a = t0 + 0.45 + 0.35 * k
            d.clean(4, a, t1, x, cy + 100 * s, str(v), 130, ACCENTS[0], 5,
                    "\\fscx40\\fscy40\\t(0,180,\\fscx112\\fscy112)\\t(180,300,\\fscx100\\fscy100)" + fade)
            cues.append((a, "pop"))
        d.pill(3, t0 + 0.45, t1, cx - 30 * s, cy + 92 * s, 60 * s, 14 * s, TRACK, 0, fade)
        cues.append((t0 + 1.2, "ding"))
    return [(round(max(0.0, c), 3), n) for c, n in cues if c < t1 - 0.1]


def badge(ass: "P.Ass", text: str, x: float, y: float, t0: float, t1: float, u: float) -> None:
    """ป้ายวันที่·สถานที่ แบบเม็ดยาเข้ม + จุดสีเหลือง เลื่อนเข้าจากซ้าย (มุมบนซ้ายของภาพ)"""
    d = _Draw(ass, 0, t1)
    size = 38 * u
    tw = text_w(text, size)
    h = size * 1.75
    w = tw + h * 0.9 + 44 * u
    mv = f"\\move({int(x - 40 * u)},{int(y)},{int(x)},{int(y)},0,300)\\fad(180,220)"
    d.ev(1, t0, t1, f"\\an7{mv}\\bord0\\shad0\\1c{_c('000000')}\\1a&H70&\\blur{int(10 * u)}\\p1",
         _rect(w, h, h / 2) + "{\\p0}")
    d.ev(2, t0, t1, f"\\an7{mv}\\bord0\\shad0\\1c{_c(CARD)}\\1a&H38&\\p1", _rect(w, h, h / 2) + "{\\p0}")
    dot = h * 0.34
    d.ev(3, t0, t1, f"\\an7\\move({int(x - 40 * u + h * 0.42)},{int(y + (h - dot) / 2)},{int(x + h * 0.42)},"
                    f"{int(y + (h - dot) / 2)},0,300)\\fad(180,220)\\bord0\\shad0\\1c{_c(ACCENTS[0])}\\p1",
         _rect(dot, dot, dot / 2) + "{\\p0}")
    tx = x + h * 0.42 + dot + 18 * u
    d.ev(3, t0, t1, f"\\an4\\move({int(tx - 40 * u)},{int(y + h / 2)},{int(tx)},{int(y + h / 2)},0,300)\\fad(180,220)"
                    f"\\fn{d.font}\\fs{int(size)}\\b1\\bord0\\shad0\\1c{_c(WHITE)}", P.ass_text(text))


def quote(ass: "P.Ass", text: str, cx: float, cy: float, t0: float, t1: float, u: float, maxw: float) -> None:
    """คำพูดดัง: ตัวหนังสือขาวตัวใหญ่ บนแถบเงาเข้มนุ่มๆ + เครื่องหมายคำพูดสีเหลืองตัวโต"""
    d = _Draw(ass, 0, t1)
    size = 58 * u
    while size > 32 * u and text_w(text, size) > maxw * 0.86:
        size -= 2 * u
    tw = min(maxw, text_w(text, size))
    bw, bh = tw + 120 * u, size * 2.1
    fade = "\\fad(220,250)"
    d.ev(1, t0, t1, f"\\an5\\pos({int(cx)},{int(cy)})\\bord0\\shad0\\1c{_c('000000')}\\1a&H68&"
                    f"\\blur{int(26 * u)}{fade}\\p1", _rect(bw, bh, bh / 2) + "{\\p0}")
    d.ev(2, t0 + 0.05, t1, f"\\an5\\pos({int(cx)},{int(cy - bh * 0.5)})\\fn{d.font}\\fs{int(size * 3)}\\b1"
                           f"\\bord0\\shad0\\1c{_c(ACCENTS[0])}\\fscx50\\fscy50\\t(0,220,0.5,\\fscx100\\fscy100){fade}", "“")
    d.ev(3, t0 + 0.12, t1, f"\\an5\\pos({int(cx)},{int(cy)})\\fn{d.font}\\fs{int(size)}\\b1\\bord0"
                           f"\\shad{max(1, int(2 * u))}\\4c{_c('000000')}\\4a&H80&\\1c{_c(WHITE)}"
                           f"\\fscx92\\fscy92\\t(0,260,0.5,\\fscx100\\fscy100){fade}", P.ass_text(text))


# ───────────────────────── แอนิเมชันตัวหนังสือ (โหมดไม่มีภาพจริง) ─────────────────────────

PALETTES = [  # (บน, ล่าง, สีเน้น) — สดใสแบบคลิปป้ายยา
    ("FF7A59", "FFB547", "FFF3B0"), ("7B5CFF", "FF6FB5", "FFE66D"), ("00B4D8", "48E5C2", "FFF3B0"),
    ("FF4E8B", "FF9A62", "FFFFFF"), ("2B2D6E", "6C4BD8", "FFD43B"), ("10B981", "84CC16", "FFFFFF"),
]


def anim_background(out, W: int, H: int, k: int = 0) -> None:
    """พื้นหลังแอนิเมชันแบบแฟลต: ไล่สี + วงกลมจางๆ + จุดลาย (ขยับด้วยกล้องตอนเรนเดอร์)"""
    import random
    from PIL import Image, ImageDraw, ImageFilter
    top, bot, acc = PALETTES[k % len(PALETTES)]
    c1, c2 = [tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) for h in (top, bot)]
    w, h = int(W * 1.15), int(H * 1.15)
    im = Image.new("RGB", (w, h))
    px = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(1, h - 1)
        px.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    rnd = random.Random(k * 7 + 3)
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(7):  # วงกลมใหญ่จางๆ
        r = rnd.randint(int(w * 0.12), int(w * 0.45))
        x, y = rnd.randint(-r // 2, w), rnd.randint(-r // 2, h)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, rnd.randint(18, 40)))
    layer = layer.filter(ImageFilter.GaussianBlur(18))
    dots = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    step = int(w / 14)
    for yy in range(0, h, step):  # จุดลายเบาๆ
        for xx in range((yy // step % 2) * step // 2, w, step):
            dd.ellipse([xx - 4, yy - 4, xx + 4, yy + 4], fill=(255, 255, 255, 34))
    im = Image.alpha_composite(Image.alpha_composite(im.convert("RGBA"), layer), dots).convert("RGB")
    im.save(out)


def sparkles(ass: "P.Ass", t0: float, t1: float, cx: float, cy: float, r: float, k: int = 0) -> None:
    """ประกายรูปดาว 4 แฉก วิ้งๆ รอบสินค้า (แบบโฆษณาสินค้า)"""
    import random
    d = _Draw(ass, t0, t1)
    rnd = random.Random(k * 31 + 7)
    for m in range(7):
        a = t0 + rnd.uniform(0, 1.6)
        x, y = cx + rnd.uniform(-r, r), cy + rnd.uniform(-r * 1.1, r * 0.9)
        z = rnd.uniform(28, 60) * d.s
        q = z * 0.18
        star = f"m 0 {-z:.0f} b {q:.0f} {-q:.0f} {q:.0f} {-q:.0f} {z:.0f} 0 b {q:.0f} {q:.0f} {q:.0f} {q:.0f} 0 {z:.0f} " \
               f"b {-q:.0f} {q:.0f} {-q:.0f} {q:.0f} {-z:.0f} 0 b {-q:.0f} {-q:.0f} {-q:.0f} {-q:.0f} 0 {-z:.0f}"
        period = rnd.randint(900, 1600)
        tw = "".join(f"\\t({p},{p + period // 2},\\fscx100\\fscy100\\alpha&H00&)"
                     f"\\t({p + period // 2},{p + period},\\fscx10\\fscy10\\alpha&HFF&)"
                     for p in range(0, int((t1 - a) * 1000), period))
        d.ev(4, a, t1, f"\\an7\\pos({int(x)},{int(y)})\\bord0\\shad0\\blur2\\1c{_c('FFFFFF')}"
                       f"\\fscx10\\fscy10\\alpha&HFF&{tw}\\p1", star + "{\\p0}")


def kinetic(ass: "P.Ass", text: str, t0: float, t1: float, k: int = 0,
            cy: float | None = None, shapes: bool = True) -> list[tuple[float, str]]:
    """ข้อความตัวใหญ่กลางจอ เด้งทีละคำ + รูปทรงตกแต่งลอยไปมา + วงแหวนระเบิดตอนขึ้น คืนจังหวะเสียงเอฟเฟกต์"""
    d = _Draw(ass, t0, t1)
    s, W, H = d.s, d.W, d.H
    acc = PALETTES[k % len(PALETTES)][2]
    cues: list[tuple[float, str]] = []
    cx, cy = W / 2, H * (cy if cy is not None else 0.33 if d.vertical else 0.4)
    # รูปทรงตกแต่ง: วงกลม/วงแหวน/สี่เหลี่ยมหมุน ลอยช้าๆ ทั้งฉาก
    import random
    rnd = random.Random(k * 13 + 1)
    for m in range(5 if shapes else 0):
        x1, y1 = rnd.uniform(0.05, 0.95) * W, rnd.uniform(0.08, 0.92) * H
        x2, y2 = x1 + rnd.uniform(-120, 120) * s, y1 + rnd.uniform(-160, 160) * s
        size = rnd.uniform(40, 110) * s
        shape = _rect(size, size, size / 2) if m % 3 == 0 else _rect(size, size, size * 0.18)
        rot = f"\\frz{rnd.randint(0, 40)}\\t(\\frz{rnd.randint(120, 300)})" if m % 3 else ""
        d.ev(0, t0, t1, f"\\an5\\move({int(x1)},{int(y1)},{int(x2)},{int(y2)})\\bord0\\shad0"
                        f"\\1c{_c('FFFFFF')}\\1a&H{rnd.choice([0xB0, 0xC8, 0xD8]):02X}&{rot}\\fad(300,300)\\p1",
             shape + "{\\p0}")
    # วงแหวนระเบิดหลังตัวหนังสือตอนเริ่ม
    ring = 360 * s
    d.ev(1, t0 + 0.1, t0 + 0.8, f"\\an5\\pos({int(cx)},{int(cy)})\\bord{int(10 * s)}\\shad0\\1a&HFF&"
                                f"\\3c{_c(acc)}\\fscx20\\fscy20\\t(0,600,\\fscx160\\fscy160\\3a&HFF&)\\p1",
         _rect(ring, ring, ring / 2) + "{\\p0}")
    # คำทีละคำ (ช่องว่างในหัวข้อ = แบ่งคำ) — คำสุดท้ายเป็นสีเน้น
    words = [w for w in re.split(r"\s+", text.strip()) if w][:6] or [text]
    lines, cur = [], ""
    for w in words:  # ห่อบรรทัด ~10 ตัวอักษร
        if cur and len(cur) + len(w) > (10 if d.vertical else 22):
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    lines.append(cur)
    size = 165 if max(len(x) for x in lines) <= 7 else 140 if max(len(x) for x in lines) <= 10 else 118
    gap = size * 1.12 * s
    y0 = cy - gap * (len(lines) - 1) / 2
    n = 0
    for li, line in enumerate(lines):
        for wi, w in enumerate(line.split(" ")):
            n += 1
        a = t0 + 0.15 + 0.22 * li
        last = li == len(lines) - 1
        d.text(3, a, t1, cx, y0 + gap * li, line, size, acc if last else WHITE, 5,
               f"\\bord{int(9 * s)}\\shad{int(6 * s)}\\4c{_c('000000')}\\4a&H70&"
               f"\\fscx30\\fscy30\\frz{-4 if li % 2 else 4}"
               f"\\t(0,170,\\fscx118\\fscy118\\frz0)\\t(170,300,\\fscx100\\fscy100)"
               f"\\t(300,{int((t1 - a) * 1000)},\\fscx106\\fscy106)\\fad(0,220)")
        cues.append((a, "pop"))
    cues.insert(0, (t0 + 0.05, "whoosh"))
    return cues
