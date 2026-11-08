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

TYPES = {"stat": "ตัวเลขเด่น", "compare": "แท่งเปรียบเทียบ", "list": "หัวข้อย่อย", "keyword": "คำสำคัญ"}
ACCENTS = ["FFD43B", "4DD4FF", "FF7AB6", "7CF29A"]
CARD, WHITE, DARK = "101828", "FFFFFF", "1A1A1A"

GRAPHIC_RULES = """- "graphic": an optional small motion graphic that helps viewers UNDERSTAND this scene, or null.
  Use it only when the narration has a number, a comparison, a list of points, or one key idea — roughly 1 in 3 scenes, never two "keyword" in a row.
  All text in THAI, short. Numbers must be copied exactly from the narration — never invent or estimate numbers.
  {"type":"stat","value":"1","unit":"มม./ปี","label":"ฝนเฉลี่ยต่อปี"}   (one key number from the narration)
  {"type":"compare","unit":"มม.","items":[{"label":"อาตากามา","value":1},{"label":"กรุงเทพฯ","value":1500}]}   (2-4 numbers stated in the narration)
  {"type":"list","items":["ไม่มีฝน","ไม่มีพืช","คล้ายดาวอังคาร"]}   (2-4 points, 2-5 words each)
  {"type":"keyword","text":"แห้งแล้งที่สุดในโลก"}   (one key phrase, 2-6 words)"""


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
        self.s = min(ass.W, ass.H) / 1080
        self.font = P.thai_font()
        self.bottom = 0.69

    def ev(self, layer: int, a: float, b: float, tags: str, body: str, style: str = "Sub") -> None:
        a, b = max(self.t0, a), min(self.t1, b)
        if b - a > 0.01:
            self.ass.events.append(f"Dialogue: {layer},{P._ass_time(a)},{P._ass_time(b)},{style},,0,0,0,,{{{tags}}}{body}")

    def shape(self, layer, a, b, x, y, draw, color, alpha=0, extra="") -> None:
        self.ev(layer, a, b, f"\\an7\\pos({int(x)},{int(y)})\\bord0\\shad0\\1c{_c(color)}\\1a&H{alpha:02X}&{extra}\\p1",
                draw + "{\\p0}")

    def text(self, layer, a, b, x, y, text, size, color=WHITE, align=7, extra="", bold=True, raw=False) -> None:
        body = text if raw else P.ass_text(text)
        pos = "" if "\\move(" in extra else f"\\pos({int(x)},{int(y)})"
        self.ev(layer, a, b, f"\\an{align}{pos}\\fn{self.font}\\fs{int(size * self.s)}\\b{1 if bold else 0}"
                             f"\\bord{max(2, int(3 * self.s))}\\3c{_c('000000')}\\shad0\\1c{_c(color)}{extra}", body)

    def card(self, h: float) -> tuple[float, float, float, float]:
        """กรอบพื้นหลังกราฟิก: แนวตั้ง = ส่วนล่างของภาพ (เหนือซับ) · แนวนอน = มุมขวา"""
        s = self.s
        if self.vertical:
            w = 900 * s
            x0 = (self.W - w) / 2
            y0 = self.H * self.bottom - h * s
        else:
            w = 760 * s
            x0 = self.W - w - 60 * s
            y0 = self.H * 0.74 - h * s
        hh = h * s
        a = self.t0
        self.shape(0, a, self.t1, x0, y0, _rect(w, hh, 28 * s), CARD, 0x38, "\\fad(220,250)")
        self.shape(1, a, self.t1, x0, y0 + 22 * s, _rect(12 * s, hh - 44 * s, 6 * s), ACCENTS[0], 0, "\\fad(220,250)")
        return x0, y0, w, hh


# ───────────────────────── เสียงเอฟเฟกต์เบาๆ ตอนกราฟิกขึ้น ─────────────────────────
# สร้างด้วย ffmpeg ทั้งหมด (ไม่ใช้ไฟล์จากเน็ต = ไม่ติดลิขสิทธิ์)  ชื่อ: (คำสั่ง lavfi, filter, ความดัง)
SFX = {
    "whoosh": ("anoisesrc=d=0.4:c=pink:a=0.6:r=44100",
               "highpass=f=700,lowpass=f=6000,afade=t=in:st=0:d=0.22:curve=exp,afade=t=out:st=0.22:d=0.18", 0.9),
    "pop": ("aevalsrc='sin(2*PI*(520*t+4200*t*t))*exp(-38*t)':d=0.12:s=44100", "lowpass=f=4000", 0.38),
    "tick": ("aevalsrc='sin(2*PI*2300*t)*exp(-260*t)':d=0.03:s=44100", "highpass=f=900", 0.18),
    "ding": ("aevalsrc='(0.6*sin(2*PI*1320*t)+0.4*sin(2*PI*1980*t))*exp(-5.5*t)':d=0.7:s=44100", "anull", 0.22),
    "rise": ("aevalsrc='sin(2*PI*(260*t+700*t*t))*min(1,t*12)*exp(-2.6*t)':d=0.65:s=44100", "lowpass=f=2500", 0.25),
}


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
    if t == "stat":
        x0, y0, w, h = d.card(330)
        cues.append((t0, "whoosh"))
        cx = x0 + w / 2
        unit = g.get("unit") or ""
        val = _num(g["value"])
        steps, dur = 16, 0.9
        unit_tag = f"{{\\fs{int(62 * s)}\\1c{_c(WHITE)}}} {P.ass_text(unit)}" if unit else ""
        if val is not None and abs(val) > 0:
            for k in range(steps):  # นับเลขขึ้น (ค่อยๆ ช้าลงตอนใกล้ถึง)
                p = 1 - (1 - (k + 1) / steps) ** 3
                a = t0 + 0.25 + dur * k / steps
                b = t0 + 0.25 + dur * (k + 1) / steps if k < steps - 1 else t1
                d.text(2, a, b, cx, y0 + 40 * s, P.ass_text(_fmt(val * p, g["value"])) + unit_tag, 150,
                       ACCENTS[0], 8, "\\fad(0,250)" if k == steps - 1 else "", raw=True)
                if k % 3 == 0 and k < steps - 1:
                    cues.append((a, "tick"))
            cues.append((t0 + 0.25 + dur, "ding"))
        else:
            d.text(2, t0 + 0.25, t1, cx, y0 + 40 * s, P.ass_text(g["value"]) + unit_tag, 130, ACCENTS[0], 8,
                   "\\fscx70\\fscy70\\t(0,250,\\fscx100\\fscy100)" + fade, raw=True)
            cues.append((t0 + 0.25, "pop"))
        if g.get("label"):
            d.text(2, t0 + 0.6, t1, cx, y0 + h - 40 * s, g["label"], 58, WHITE, 2,
                   f"\\move({int(cx)},{int(y0 + h - 10 * s)},{int(cx)},{int(y0 + h - 40 * s)},0,300){fade}")
    elif t == "compare":
        items = g["items"][:4]
        row = 128
        x0, y0, w, h = d.card(60 + row * len(items))
        cues.append((t0, "whoosh"))
        top = max(i["value"] for i in items) or 1
        maxw = w - 120 * s
        unit = g.get("unit") or ""
        for k, it in enumerate(items):
            a = t0 + 0.3 + 0.35 * k
            y = y0 + (34 + row * k) * s
            color = ACCENTS[k % len(ACCENTS)]
            cues.append((a, "rise"))
            d.text(2, a, t1, x0 + 50 * s, y - 4 * s, it["label"], 50, WHITE, 7, fade)
            bw = max(14 * s, maxw * it["value"] / top)
            d.shape(2, a, t1, x0 + 50 * s, y + 58 * s, _rect(bw, 38 * s, 10 * s), color, 0,
                    f"\\fscx0\\t(0,700,0.6,\\fscx100){fade}")
            label = f"{_fmt(it['value'], str(it['value']) if it['value'] % 1 else '0')} {unit}".strip()
            if bw > maxw * 0.7:  # แท่งยาว → ใส่ตัวเลขไว้ในแท่ง (ไม่ล้นกรอบ)
                d.text(3, a + 0.7, t1, x0 + 50 * s + bw - 14 * s, y + 56 * s, label, 40, DARK, 9,
                       "\\bord0" + fade)
            else:
                d.text(3, a + 0.7, t1, x0 + 50 * s + bw + 16 * s, y + 56 * s, label, 42, color, 7, fade)
    elif t == "list":
        items = g["items"][:4]
        row = 96
        x0, y0, w, h = d.card(50 + row * len(items))
        cues.append((t0, "whoosh"))
        for k, item in enumerate(items):
            a = t0 + 0.3 + 0.45 * k
            cues.append((a, "pop"))
            y = y0 + (30 + row * k) * s
            x = x0 + 60 * s
            tx = x + 50 * s
            d.shape(2, a, t1, x, y + 20 * s, _rect(26 * s, 26 * s, 7 * s), ACCENTS[k % len(ACCENTS)], 0,
                    "\\fscx0\\fscy0\\t(0,200,\\fscx100\\fscy100)" + fade)
            d.text(2, a, t1, tx, y - 6 * s, item, 60, WHITE, 7,
                   f"\\move({int(tx - 40 * s)},{int(y)},{int(tx)},{int(y)},0,260)" + fade)
    elif t == "keyword":
        cx = d.W / 2 if d.vertical else d.W - 440 * s
        cy = d.H * ((bottom - 0.07) if d.vertical else 0.66)
        size = 92 if len(g["text"]) <= 12 else 80 if len(g["text"]) <= 18 else 66
        # กล่องสีพอดีข้อความ (BorderStyle 3 = libass วาดกล่องรอบตัวหนังสือให้เอง)
        d.ev(2, t0 + 0.25, t1, f"\\an5\\pos({int(cx)},{int(cy)})\\fs{int(size * s)}\\bord{int(18 * s)}"
                               f"\\fscx40\\fscy40\\t(0,180,\\fscx112\\fscy112)\\t(180,300,\\fscx100\\fscy100)"
                               f"\\frz-3{fade}", P.ass_text(g["text"]), style="GBox")
        cues.append((t0 + 0.25, "pop"))
    return [(round(max(0.0, c), 3), n) for c, n in cues if c < t1 - 0.1]


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
