"""
ภาพปกคลิปแบบดึงสายตา (สไตล์ปก YouTube/TikTok)
  • ข้อความสั้นกระแทก 2-6 คำ (AI คิดจากชื่อ/สรุป หรือผู้ใช้พิมพ์เอง) ตัวใหญ่ ขอบดำหนา คำเด่นสีเหลือง
  • แบบ "ป๊อป": ตัดตัวเด่นออกมาใส่ขอบขาว ลอยเหนือฉากหลังที่มืด/เบลอลง
  • แบบ "ตัวหนา": ภาพเต็ม สีจัด + แถบไล่เงาให้อ่านง่าย · แบบ "แถบสี": ข้อความบนแถบสีเอียง
  • ทำ 3 แบบจากคนละเฟรม ให้ผู้ใช้เลือก
ภาพประกอบด้วย PIL · ตัวหนังสือไทยวาดด้วย libass (จัดสระ/วรรณยุกต์ไทยถูกต้องทุกเครื่อง)
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

import pipeline as P

COVER_PROMPT = """คุณเป็นนักออกแบบปกคลิปสั้น (YouTube Shorts / TikTok) ที่ทำให้คนหยุดเลื่อนแล้วกดดู
ชื่อคลิป: {title}
เนื้อหาโดยย่อ: {summary}

เขียน "ข้อความบนปก" ภาษาไทย 2-6 คำ (ไม่เกิน 22 ตัวอักษร) ที่สั้น กระแทก ชวนสงสัย
ไม่ต้องซ้ำชื่อคลิปทั้งหมด (เช่น "แฝดแต่ลายนิ้วมือไม่เหมือน?!", "ภารกิจสุดป่วน!", "ตัวใหญ่ผิดปกติ!")
และเลือก "คำเด่น" 1 คำจากข้อความนั้น (คำที่สำคัญที่สุด จะเป็นสีเหลือง)
ห้ามใส่อีโมจิ ห้ามโกหกหรือเกินจริงจากเนื้อหา

ตอบเป็น JSON อย่างเดียว: {{"text": "...", "accent": "..."}}"""

YELLOW, RED, WHITE = "FFD400", "FF3B30", "FFFFFF"


# ───────────────────────── ข้อความบนปก ─────────────────────────

def cover_text(title: str, summary: str = "", provider: str = "gemini") -> tuple[str, str]:
    """(ข้อความบนปก, คำเด่น) — AI ใช้ไม่ได้ → ตัดจากชื่อคลิป"""
    title = P.clean_text(title or "")
    if provider and provider != "none":
        try:
            d = P._parse_json(P.ask_ai(provider, COVER_PROMPT.format(title=title, summary=P.clean_text(summary or "")[:500])))
            t = P.clean_text(str(d.get("text") or ""))
            if 2 <= len(t) <= 40:
                a = P.clean_text(str(d.get("accent") or ""))
                return t, (a if a and a in t else "")
        except Exception as e:
            print("AI คิดข้อความปกไม่ได้ ใช้ชื่อคลิปแทน:", e)
    # ไม่มี AI: เอาท่อนแรกของชื่อ (ตัดที่เครื่องหมาย/เว้นวรรค) ไม่เกิน ~22 ตัว
    part = re.split(r"[!?！？:|—–\-,]| {2,}", title)[0].strip() or title
    if len(part) > 24:
        words, out = part.split(" "), ""
        for w in words:
            if len(out) + len(w) > 22:
                break
            out = (out + " " + w).strip()
        part = out or part[:22]
    return part, ""


def tag_from_top(top: str) -> str:
    """ข้อความหัวเรื่อง "Soul Eater | ตอนที่ 3" → ป้ายเล็ก "Soul Eater ตอนที่ 3" """
    return " ".join(x.strip() for x in re.split(r"\s*\|\s*", top or "") if x.strip())[:40]


def _tokens(text: str) -> list[str]:
    try:
        from pythainlp.tokenize import word_tokenize
        return [t for t in word_tokenize(text, keep_whitespace=True) if t]
    except Exception:
        return [c for _, _, c in P.sub_chunks(text, 0, 1, 4)]


def _lines(text: str, per_line: int, accent: str = "") -> list[str]:
    """ตัดบรรทัดตามคำ ไม่ตัดกลางคำเด่น · บรรทัดยาวพอๆ กัน"""
    if accent and accent in text:
        a = text.index(accent)
        toks = _tokens(text[:a]) + [accent] + _tokens(text[a + len(accent):])
    else:
        toks = _tokens(text)
    total = _vis_len(text)
    n = max(1, min(3, -(-total // per_line)))
    target = total / n
    lines, cur = [], ""
    for t in toks:
        if cur and _vis_len(cur + t) > target * 1.15 and len(lines) < n - 1:
            lines.append(cur.strip())
            cur = t.lstrip()
        else:
            cur += t
    if cur.strip():
        lines.append(cur.strip())
    return lines[:3]


def _vis_len(s: str) -> int:
    return len(re.sub(r"[ัิ-ฺ็-๎]", "", s))


# ───────────────────────── ภาพ ─────────────────────────

def grab_frame(src: Path, t: float, out: Path) -> Path:
    P.run(["ffmpeg", "-y", "-hide_banner", "-ss", f"{max(0.0, t):.3f}", "-i", str(src), "-frames:v", "1", str(out)])
    return out


def _cover_fit(im, W: int, H: int):
    from PIL import Image, ImageOps
    return ImageOps.fit(im.convert("RGB"), (W, H), Image.LANCZOS, centering=(0.5, 0.42))


def _punch(im):
    """สีจัด คมขึ้น (ปกที่ดึงสายตามักสีสดกว่าภาพจริง)"""
    from PIL import ImageEnhance, ImageFilter
    im = ImageEnhance.Contrast(im).enhance(1.15)
    im = ImageEnhance.Color(im).enhance(1.3)
    return im.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=3))


def _shade(im, top: float, bottom: float, strength: int = 200):
    """ไล่เงาดำจากขอบบน/ล่าง ให้ตัวหนังสืออ่านง่ายบนทุกภาพ"""
    import numpy as np
    from PIL import Image
    W, H = im.size
    y = np.linspace(0, 1, H)[:, None]
    a = np.zeros((H, 1))
    if top:
        a = np.maximum(a, np.clip(1 - y / top, 0, 1) ** 1.6)
    if bottom:
        a = np.maximum(a, np.clip((y - (1 - bottom)) / bottom, 0, 1) ** 1.6)
    mask = Image.fromarray((np.repeat(a, W, axis=1) * strength).astype("uint8"), "L")
    return Image.composite(Image.new("RGB", im.size, (0, 0, 0)), im, mask)


def _vignette(im, strength: int = 120):
    import numpy as np
    from PIL import Image
    W, H = im.size
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    mask = Image.fromarray((np.clip(d - 0.65, 0, 1) / 0.6 * strength).clip(0, 255).astype("uint8"), "L")
    return Image.composite(Image.new("RGB", im.size, (0, 0, 0)), im, mask)


def _subject(img):
    """ตัดตัวเด่น (คน/ตัวละคร/สัตว์/ของ) ด้วย rembg → RGBA หรือ None"""
    try:
        import motion as MO
        fg, _ = MO._subject(img)
        return fg
    except Exception as e:
        print("ตัดตัวเด่นสำหรับปกไม่ได้:", e)
        return None


def _sticker(fg, W: int, H: int, vertical: bool):
    """ตัวเด่น + ขอบขาวหนา + เงา → (RGBA ขนาด W×H)"""
    from PIL import Image, ImageFilter
    a = fg.getchannel("A")
    bb = a.point(lambda v: 255 if v > 100 else 0).getbbox()
    if not bb:
        return None
    sub = fg.crop(bb)
    # ขยายให้ตัวเด่นใหญ่ (ปกที่ดีมีตัวเด่นใหญ่ชัด) — แนวตั้งสูง ~58% ของจอ, แนวนอนสูง ~85%
    tgt_h = H * (0.58 if vertical else 0.85)
    k = min(tgt_h / sub.height, W * (0.95 if vertical else 0.55) / sub.width)
    sub = sub.resize((max(1, int(sub.width * k)), max(1, int(sub.height * k))), Image.LANCZOS)
    pad = max(10, int(min(W, H) * 0.012))
    al = sub.getchannel("A").point(lambda v: 255 if v > 90 else 0)
    big = Image.new("L", (sub.width + pad * 4, sub.height + pad * 4), 0)
    big.paste(al, (pad * 2, pad * 2))
    outline = big.filter(ImageFilter.MaxFilter(pad * 2 + 1)).filter(ImageFilter.GaussianBlur(1.2))
    shadow = big.filter(ImageFilter.MaxFilter(pad * 2 + 1)).filter(ImageFilter.GaussianBlur(pad * 1.5))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    x = (W - big.width) // 2 if vertical else int(W * 0.98 - big.width)
    y = H - big.height + pad * 2  # ชิดขอบล่าง (ตัดช่วงล่างของตัวละครได้ ดูเป็นธรรมชาติ)
    layer.paste(Image.new("RGBA", big.size, (0, 0, 0, 150)), (x + pad, y + pad), shadow)
    layer.paste(Image.new("RGBA", big.size, (255, 255, 255, 255)), (x, y), outline)
    layer.paste(sub, (x + pad * 2, y + pad * 2), sub)
    return layer


# ───────────────────────── ตัวหนังสือ (libass) ─────────────────────────

def _ass(W: int, H: int, events: list[str], path: Path) -> None:
    font = P.thai_font()
    # ใช้ชื่อตระกูลฟอนต์เดียวกับซับ ("Kanit") แล้วขอความหนาด้วย \\b900 — ถ้าเรียก "Kanit Black" ตรงๆ
    # บางเครื่องหาไม่เจอ → libass ไปยืมฟอนต์อื่นทีละตัวอักษร ทำให้สระ/วรรณยุกต์จมหรือหาย
    big = font
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\nScaledBorderAndShadow: yes\n"
        f"PlayResX: {W}\nPlayResY: {H}\n\n[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Hook,{big},80,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,0,0,1,10,6,5,20,20,20,1\n"
        f"Style: Box,{big},80,&H00000000,&H00000000,{P._ass_color(YELLOW)},{P._ass_color(YELLOW)},1,0,0,0,100,100,0,0,3,18,0,5,20,20,20,1\n"
        f"Style: Tag,{font},40,&H00FFFFFF,&H00FFFFFF,{P._ass_color(RED)},{P._ass_color(RED)},1,0,0,0,100,100,0,0,3,14,0,5,20,20,20,1\n"
        f"Style: Brand,{font},34,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,3,2,5,20,20,20,1\n"
        "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + "\n".join(events) + "\n", encoding="utf-8")


def _heavy() -> str:
    """ตัวหนาพิเศษถ้ามีไฟล์ Kanit Black (ไม่มี = ตัวหนาปกติ)"""
    return "\\b900" if (P.FONT_DIR / "Kanit-Black.ttf").exists() else ""


def _ev(style: str, text: str, tags: str, layer: int = 1) -> str:
    return f"Dialogue: {layer},0:00:00.00,0:00:05.00,{style},,0,0,0,,{{{tags}}}{text}"


def _hook_events(text: str, accent: str, W: int, H: int, style: str, cx: int, cy: int,
                 vertical: bool, max_w: float, accent_color: str) -> list[str]:
    """ข้อความหลัก 1-3 บรรทัด ตัวใหญ่สุดที่พอดีความกว้าง · คำเด่นเปลี่ยนสี"""
    per = 8 if vertical else 9
    lines = _lines(text, per, accent)
    longest = max(_vis_len(x) for x in lines) or 1
    size = int(min(H * (0.11 if vertical else 0.21), max_w / (longest * 0.58)))
    size = max(int(H * 0.04), size)
    step = size * 1.12
    y0 = cy - step * (len(lines) - 1) / 2
    ev = []
    acc = P._ass_color(accent_color)
    for k, ln in enumerate(lines):
        t = P.ass_text(ln)
        if accent and accent in ln:
            t = t.replace(P.ass_text(accent), "{\\c" + acc + "&}" + P.ass_text(accent) + "{\\c&H00FFFFFF&}", 1)
        y = int(y0 + k * step)
        if style == "band":  # ตัวดำบนแถบเหลือง เอียงนิดๆ
            t = t.replace("{\\c" + acc + "&}", "{\\c" + P._ass_color(RED) + "&}").replace("{\\c&H00FFFFFF&}", "{\\c&H000000&}")
            ev.append(_ev("Box", t, f"\\an5\\pos({cx},{y})\\fs{size}{_heavy()}\\frz3\\bord{int(size * 0.22)}"))
        else:
            ev.append(_ev("Hook", t, f"\\an5\\pos({cx},{y})\\fs{size}{_heavy()}\\bord{max(6, int(size * 0.11))}"
                                     f"\\shad{max(3, int(size * 0.06))}" + ("\\frz2" if style == "bold" else "")))
    return ev, int(y0 - size * 0.6), int(y0 + step * (len(lines) - 1) + size * 0.6)


def compose(img_path: Path, out: Path, W: int, H: int, text: str, accent: str = "", tag: str = "",
            brand: str = "", style: str = "pop", accent_color: str = YELLOW, workdir: Path | None = None) -> str:
    """ทำปก 1 ภาพ คืนแบบที่ใช้จริง (pop ตัดตัวเด่นไม่ได้ → bold)"""
    from PIL import Image, ImageFilter
    workdir = Path(workdir or out.parent)
    vertical = H > W
    src = Image.open(img_path).convert("RGB")
    bg = _punch(_cover_fit(src, W, H))
    layer = None
    if style == "pop":
        fg = _subject(_cover_fit(src, W, H))
        layer = _sticker(fg, W, H, vertical) if fg is not None else None
        if layer is None:
            style = "bold"
        else:  # ฉากหลังมืด+เบลอลง ให้ตัวเด่นเด้งออกมา
            from PIL import ImageEnhance
            bg = ImageEnhance.Brightness(bg.filter(ImageFilter.GaussianBlur(6))).enhance(0.6)
    if vertical:
        bg = _shade(bg, 0.5, 0.18, 210)
    else:
        bg = _shade(bg, 0, 0.55, 220) if style != "pop" else bg
    bg = _vignette(bg)
    if layer is not None:
        bg = bg.convert("RGBA")
        bg.alpha_composite(layer)
        bg = bg.convert("RGB")
    base = workdir / (out.stem + "_base.png")
    bg.save(base)
    # ตำแหน่งข้อความ: แนวตั้ง = ช่วงบน (ตัวเด่นอยู่ล่าง) · แนวนอน = ครึ่งซ้าย (ตัวเด่นขวา) หรือด้านล่าง
    if vertical:
        cx, cy, max_w = W // 2, int(H * 0.21), W * 0.92
    elif style == "pop":
        cx, cy, max_w = int(W * 0.29), int(H * 0.52), W * 0.56
    else:
        cx, cy, max_w = W // 2, int(H * 0.7), W * 0.94
    ev, top_y, bot_y = _hook_events(text, accent, W, H, style, cx, cy, vertical, max_w, accent_color)
    if tag:  # ป้ายแดงเล็กเหนือข้อความหลัก (เช่น ชื่อเรื่อง/ตอน)
        ts = int(H * (0.03 if vertical else 0.065))
        ev.append(_ev("Tag", P.ass_text(tag), f"\\an2\\pos({cx},{max(ts + 20, top_y - int(ts * 0.6))})\\fs{ts}\\bord{int(ts * 0.35)}"))
    if brand:
        bs = int(H * (0.022 if vertical else 0.04))
        ev.append(_ev("Brand", P.ass_text(brand), f"\\an2\\pos({W // 2},{int(H * 0.97)})\\fs{bs}"))
    ass = workdir / (out.stem + ".ass")
    _ass(W, H, ev, ass)
    try:
        P.run(["ffmpeg", "-y", "-hide_banner", "-i", base.name, "-vf", P.ass_filter(ass.name),
               "-frames:v", "1", "-q:v", "2", str(out.resolve())], cwd=workdir)
    except RuntimeError:  # ไม่มี libass → ปกไม่มีตัวหนังสือ ก็ยังดีกว่าไม่มี
        bg.save(out, quality=92)
    return style


def parse_user_text(s: str) -> tuple[str, str]:
    """ข้อความปกที่ผู้ใช้พิมพ์: ครอบคำเด่นด้วย *ดอกจัน* เช่น "ภารกิจ*สุดป่วน*!" """
    s = (s or "").strip()
    m = re.search(r"\*([^*]+)\*", s)
    return P.clean_text(s.replace("*", "")), (P.clean_text(m.group(1)) if m else "")


def make_covers(images: list[Path], outs: list[Path], W: int, H: int, text: str, accent: str,
                tag: str, brand: str, workdir: Path) -> list[Path]:
    """ทำปก 3 แบบ (คนละเฟรม/คนละสไตล์) — อย่างน้อย 1 แบบสำเร็จก็พอ"""
    styles = [("pop", YELLOW), ("band", YELLOW), ("bold", "FF5A36")]
    made = []
    for k, (img, out) in enumerate(zip(images, outs)):
        st, col = styles[k % len(styles)]
        try:
            compose(img, out, W, H, text, accent, tag, brand, st, col, workdir)
            made.append(out)
        except Exception as e:
            print(f"ทำปกแบบที่ {k + 1} ไม่ได้:", str(e)[-300:])
    return made


def choose(job_dir: Path, n: int) -> bool:
    """ผู้ใช้เลือกปกแบบที่ n → เป็น thumb.jpg"""
    f = job_dir / f"cover_{n}.jpg"
    if not f.exists():
        return False
    shutil.copyfile(f, job_dir / "thumb.jpg")
    return True
