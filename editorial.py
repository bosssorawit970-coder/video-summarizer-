"""📰 สไตล์ "สารคดีนิตยสาร" — ภาพจริง + ตัวหนังสือใหญ่ + ไดคัทคน + พื้นกระดาษ/พื้นสี (แบบคลิปสารคดีคอลลาจ)

build() ทำ "ภาพเคลื่อนไหวของฉาก" เป็นวิดีโอเงียบยาว D วินาที แล้ว story.render_scene ใส่เสียง ซับ กราฟิก ต่อตามปกติ
เลย์เอาต์ (เลือกเองตามเนื้อหา ไม่ซ้ำฉากติดกัน):
  title   ชื่อตัวใหญ่สองสี + ไดคัทคน          bigword  พื้นสีเต็มจอ + คำเดียวตัวยักษ์ + รูปเล็ก
  row     รูปจริงเรียงบนพื้นกระดาษ + คำบรรยาย   sepia    ภาพเต็มจอโทนซีเปีย + เส้นกรอบตัดต่อ
  vinyl   แผ่นเสียงหมุน (เรื่องเพลง)           tv       ทีวีเก่าจอขาวดำ (เรื่องเก่า)
  spot    ภาพมืด + วงไฟส่องตรงกลาง
ข้อความไทยทั้งหมดวาดด้วย libass (สระ/วรรณยุกต์ถูกตำแหน่ง)
"""
from __future__ import annotations

import math
import random
import re
from pathlib import Path

import graphics as G
import pipeline as P

PAPER = (239, 233, 221)
INK = (24, 22, 20)
BOLD = [(255, 197, 49), (230, 57, 70), (20, 20, 22), (38, 70, 143)]  # เหลือง แดง ดำ น้ำเงิน
LAYOUTS = ["title", "row", "bigword", "sepia", "vinyl", "tv", "spot"]
MUSIC = re.compile(r"เพลง|อัลบั้ม|ซิงเกิล|ดนตรี|แผ่นเสียง|นักร้อง|คอนเสิร์ต|ร้องเพลง|ชาร์ต|music|album|song|singer|concert", re.I)


def _hex(c) -> str:
    return "%02X%02X%02X" % c


# ───────────────────────── เลือกเลย์เอาต์ ─────────────────────────
def pick_layout(scene: dict, i: int, prev: str = "") -> str:
    if scene.get("ed_layout") in LAYOUTS:
        return scene["ed_layout"]
    text = f"{scene.get('narration', '')} {scene.get('search', '')} {scene.get('headline', '')}"
    mood = scene.get("mood") or ""
    years = [int(y) for y in re.findall(r"(?<!\d)(1[89]\d\d|20[0-2]\d)(?!\d)", f"{scene.get('badge', '')} {text}")]
    g = scene.get("graphic") or {}
    want = []
    if i == 0 or mood == "hook":
        want = ["title"]
    elif g and not g.get("off") and g.get("type") != "keyword":
        want = ["sepia", "spot"]  # มีการ์ดตัวเลข/รายการ → ภาพเต็มจอเรียบๆ ให้การ์ดเด่น
    elif MUSIC.search(text):
        want = ["vinyl", "row"]
    elif years and min(years) < 1990:
        want = ["tv", "row", "sepia"]
    elif mood in ("shock", "exciting", "twist"):
        want = ["bigword", "spot"]
    want += ["row", "title", "sepia", "spot", "bigword"][i % 5:] + ["row", "title", "sepia", "spot", "bigword"][:i % 5]
    for w in want:
        if w != prev:
            return w
    return "row"


def _name_from_search(scene: dict) -> str:
    """ชื่อเฉพาะภาษาอังกฤษในคำค้น (เช่น 'Michael Jackson 1983 concert' → MICHAEL JACKSON) ไว้ทำชื่อตัวใหญ่"""
    m = re.findall(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b", scene.get("search") or "")
    m = [x for x in m if " " in x] or m
    return m[0].upper() if m else ""


def _title_text(scene: dict, plan_title: str = "") -> tuple[str, str]:
    """(บรรทัด 1, บรรทัด 2 สีเด่น)"""
    name = _name_from_search(scene)
    if name:
        w = name.split()
        return " ".join(w[:-1]), w[-1]
    t = (scene.get("headline") or ((scene.get("graphic") or {}).get("text")) or "").strip()
    if not t:
        import story as S
        t = S.thai_keywords(scene.get("narration") or "", 2) or plan_title
    t = re.sub(r"\s+", " ", t)[:28]
    w = t.split(" ")
    if len(w) >= 2:
        k = max(1, len(w) // 2)
        return " ".join(w[:k]), " ".join(w[k:])
    return "", t


# ───────────────────────── ชิ้นส่วนภาพ (PIL) ─────────────────────────
def _paper(W: int, H: int, seed: int = 0):
    from PIL import Image, ImageFilter
    import numpy as np
    rng = np.random.default_rng(seed)
    base = np.array(PAPER, dtype=np.float32)[None, None, :] * np.ones((H // 4, W // 4, 1), np.float32)
    base += rng.normal(0, 5, (H // 4, W // 4, 1))
    im = Image.fromarray(base.clip(0, 255).astype("uint8")).resize((W, H), Image.BICUBIC)
    return im.filter(ImageFilter.GaussianBlur(0.6))


def _fill(im, w: int, h: int, focus_y: float = 0.4):
    from PIL import Image
    s = max(w / im.width, h / im.height)
    r = im.resize((max(w, int(im.width * s + 0.5)), max(h, int(im.height * s + 0.5))), Image.LANCZOS)
    x = (r.width - w) // 2
    y = int((r.height - h) * focus_y)
    return r.crop((x, y, x + w, y + h))


def _sepia(im, amt: float = 1.0):
    from PIL import Image, ImageOps
    g = ImageOps.grayscale(im)
    sep = ImageOps.colorize(g, (38, 26, 14), (246, 228, 196))
    return Image.blend(im.convert("RGB"), sep, amt)


def _print(im, w: int, h: int, border: float = 0.035, angle: float = 0.0, tone: str = ""):
    """รูปถ่ายขอบขาว + เงานุ่ม (RGBA)"""
    from PIL import Image, ImageFilter, ImageOps
    ph = _fill(im.convert("RGB"), w, h)
    if tone == "sepia":
        ph = _sepia(ph, 0.85)
    elif tone == "bw":
        ph = ImageOps.grayscale(ph).convert("RGB")
    b = max(6, int(min(w, h) * border))
    card = Image.new("RGB", (w + 2 * b, h + 2 * b), (250, 248, 243))
    card.paste(ph, (b, b))
    pad = int(b * 3)
    out = Image.new("RGBA", (card.width + 2 * pad, card.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    sh.paste((0, 0, 0, 110), (pad + b // 2, pad + b, pad + card.width + b // 2, pad + card.height + b))
    out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(b * 1.2)))
    out.alpha_composite(card.convert("RGBA"), (pad, pad))
    if angle:
        out = out.rotate(angle, resample=Image.BICUBIC, expand=True)
    return out


def _cutout(im, max_w: int, max_h: int):
    """ไดคัทตัวเด่น + ขอบขาวแบบสติกเกอร์ (RGBA) หรือ None"""
    from PIL import Image, ImageFilter
    try:
        import motion as M
        src = im.convert("RGB")
        src.thumbnail((1200, 1200))
        rgba, _ = M._subject(src)
    except Exception as e:
        print("ไดคัทไม่ได้:", str(e)[-150:])
        rgba = None
    if rgba is None:
        return None
    bb = rgba.getchannel("A").point(lambda v: 255 if v > 40 else 0).getbbox()
    if not bb:
        return None
    rgba = rgba.crop(bb)
    s = min(max_w / rgba.width, max_h / rgba.height)
    rgba = rgba.resize((max(1, int(rgba.width * s)), max(1, int(rgba.height * s))), Image.LANCZOS)
    pad = max(8, int(min(rgba.size) * 0.03))
    canvas = Image.new("RGBA", (rgba.width + 2 * pad, rgba.height + 2 * pad), (0, 0, 0, 0))
    canvas.alpha_composite(rgba, (pad, pad))
    a = canvas.getchannel("A").point(lambda v: 255 if v > 60 else 0)
    ring = a.filter(ImageFilter.MaxFilter(2 * (pad // 2) + 1))
    sticker = Image.new("RGBA", canvas.size, (255, 255, 255, 0))
    sticker.putalpha(ring)
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow.putalpha(ring.point(lambda v: v * 0.45).filter(ImageFilter.GaussianBlur(pad)))
    out = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    out.alpha_composite(shadow, (pad // 2, pad // 2))
    out.alpha_composite(sticker)
    out.alpha_composite(canvas)
    return out


def _vinyl(im, d: int):
    from PIL import Image, ImageDraw
    disc = Image.new("RGBA", (d, d), (0, 0, 0, 0))
    dr = ImageDraw.Draw(disc)
    dr.ellipse((0, 0, d - 1, d - 1), fill=(14, 14, 16, 255))
    for r in range(int(d * 0.2), int(d * 0.49), max(2, d // 160)):  # ร่องแผ่นเสียง
        c = 30 + (r * 7) % 14
        dr.ellipse((d / 2 - r, d / 2 - r, d / 2 + r, d / 2 + r), outline=(c, c, c + 2, 255), width=1)
    glare = Image.new("RGBA", (d, d), (0, 0, 0, 0))  # แสงสะท้อน (ผสมทับ ไม่ใช่เจาะรู)
    ImageDraw.Draw(glare).pieslice((d * 0.08, d * 0.08, d * 0.92, d * 0.92), 200, 240, fill=(255, 255, 255, 26))
    disc.alpha_composite(glare)
    lab = int(d * 0.36)
    face = _fill(im.convert("RGB"), lab, lab, 0.35)
    m = Image.new("L", (lab, lab), 0)
    ImageDraw.Draw(m).ellipse((0, 0, lab - 1, lab - 1), fill=255)
    disc.paste(face, ((d - lab) // 2, (d - lab) // 2), m)
    h = int(d * 0.025)
    dr.ellipse((d / 2 - h, d / 2 - h, d / 2 + h, d / 2 + h), fill=(240, 233, 220, 255))
    return disc


def _tv(im, w: int):
    """ทีวีเก่า: ตัวเครื่องไม้ + จอขาวดำมีเส้นสแกน"""
    from PIL import Image, ImageDraw, ImageOps, ImageFilter
    h = int(w * 0.78)
    tv = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dr = ImageDraw.Draw(tv)
    dr.rounded_rectangle((0, 0, w - 1, h - 1), radius=int(w * 0.06), fill=(112, 74, 44, 255))
    dr.rounded_rectangle((w * 0.02, h * 0.025, w - 1 - w * 0.02, h - 1 - h * 0.025), radius=int(w * 0.05),
                         outline=(150, 104, 66, 255), width=max(2, w // 120))
    sx0, sy0, sx1, sy1 = int(w * 0.07), int(h * 0.1), int(w * 0.74), int(h * 0.9)
    scr = ImageOps.grayscale(_fill(im.convert("RGB"), sx1 - sx0, sy1 - sy0)).convert("RGB")
    sd = ImageDraw.Draw(scr)
    for y in range(0, scr.height, 4):
        sd.line((0, y, scr.width, y), fill=(0, 0, 0), width=1)
    scr = scr.filter(ImageFilter.GaussianBlur(0.7))
    m = Image.new("L", scr.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, scr.width - 1, scr.height - 1), radius=int(w * 0.05), fill=255)
    dr.rounded_rectangle((sx0 - 8, sy0 - 8, sx1 + 8, sy1 + 8), radius=int(w * 0.055), fill=(30, 22, 16, 255))
    tv.paste(scr, (sx0, sy0), m)
    kx = int(w * 0.87)
    for k, ky in enumerate((0.25, 0.45)):
        r = int(w * 0.045)
        dr.ellipse((kx - r, h * ky - r, kx + r, h * ky + r), fill=(205, 190, 160, 255), outline=(60, 40, 24, 255), width=3)
    for y in range(int(h * 0.62), int(h * 0.86), max(3, h // 60)):
        dr.line((w * 0.8, y, w * 0.94, y), fill=(70, 46, 28, 255), width=2)
    return tv


def _spot_mask(W: int, H: int, cx: float, cy: float, r: float):
    from PIL import Image, ImageDraw, ImageFilter
    m = Image.new("RGBA", (W, H), (0, 0, 0, 175))
    hole = Image.new("L", (W, H), 255)
    ImageDraw.Draw(hole).ellipse((cx - r, cy - r, cx + r, cy + r), fill=0)
    m.putalpha(hole.point(lambda v: int(v * 175 / 255)).filter(ImageFilter.GaussianBlur(r * 0.12)))
    return m


# ───────────────────────── ประกอบฉาก ─────────────────────────
class _Scene:
    """เก็บชั้นภาพ (PNG + การเคลื่อนไหว) และตัวหนังสือ (ASS) แล้วเรนเดอร์ด้วย ffmpeg ครั้งเดียว"""

    def __init__(self, W, H, D, workdir: Path, i: int):
        self.W, self.H, self.D, self.wd, self.i = W, H, D, workdir, i
        self.layers = []  # (path, x_expr, y_expr, extra_filter)
        self.ass = P.Ass(W, H)
        self.d = G._Draw(self.ass, 0, D)
        self.u = min(W, H) / 1080

    def bg(self, im):
        p = self.wd / f"ed{self.i}_bg.png"
        im.convert("RGB").save(p)
        self.bgp = p

    def add(self, im, x: float, y: float, t0: float = 0.2, frm: str = "up", dist: float = 0.0, extra: str = ""):
        """วางภาพที่ (x,y) มุมซ้ายบน · เลื่อนเข้ามาจากทิศ frm ใน 0.5 วิ (ease-out)"""
        k = len(self.layers)
        p = self.wd / f"ed{self.i}_l{k}.png"
        im.save(p)
        dist = dist or 0.12 * max(self.W, self.H)
        e = f"(1-pow(1-min(max((t-{t0:.2f})/0.55,0),1),3))"
        dx, dy = {"up": (0, dist), "down": (0, -dist), "left": (-dist, 0), "right": (dist, 0), "none": (0, 0)}[frm]
        xe = f"{x:.0f}+{dx:.0f}*(1-{e})"
        ye = f"{y:.0f}+{dy:.0f}*(1-{e})"
        self.layers.append((p, xe, ye, extra, t0))

    def text(self, layer, t0, x, y, text, size, color, align=7, extra=""):
        self.d.clean(layer, t0, self.D, x, y, text, size / self.d.s, color, align,
                     "\\shad0\\fad(180,200)" + extra)

    def render(self, out: Path, push: float = 0.06, grain: bool = True) -> Path:
        W, H, D = self.W, self.H, self.D
        ins = ["-loop", "1", "-framerate", "30", "-t", f"{D:.3f}", "-i", str(self.bgp)]
        for p, *_ in self.layers:
            ins += ["-loop", "1", "-framerate", "30", "-t", f"{D:.3f}", "-i", str(p)]
        parts, last = ["[0:v]format=rgb24[b0]"], "b0"
        for k, (p, xe, ye, extra, t0) in enumerate(self.layers, 1):
            fade = f"fade=in:st={t0:.2f}:d=0.25:alpha=1"
            parts.append(f"[{k}:v]format=rgba{',' + extra if extra else ''},{fade}[l{k}]")
            parts.append(f"[{last}][l{k}]overlay=x='{xe}':y='{ye}':eval=frame:format=auto[b{k}]")
            last = f"b{k}"
        z = 1 + push  # กล้องค่อยๆ ดันเข้า
        sw, sh = int(W * z / 2) * 2, int(H * z / 2) * 2
        chain = (f"[{last}]scale={sw}:{sh},crop={W}:{H}:x='({sw}-{W})/2*(1-t/{D:.3f})':"
                 f"y='({sh}-{H})/2*(1-t/{D:.3f})'")
        if grain:
            chain += ",noise=alls=7:allf=t"
        if self.ass.write(self.wd / f"ed{self.i}.ass"):
            chain += "," + P.ass_filter(f"ed{self.i}.ass")
        parts.append(chain + ",fps=30,format=yuv420p[v]")
        P.run(["ffmpeg", "-y", "-hide_banner", *ins, "-filter_complex", ";".join(parts), "-map", "[v]",
               "-t", f"{D:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", out.name],
              cwd=self.wd)
        return out


def _photos(img: Path, scene: dict, scene_dir: Path, n: int) -> list:
    """ภาพหลัก + ภาพอื่นในตัวเลือกของฉาก (ไม่ใช่วิดีโอ ไม่ซ้ำกัน)"""
    from PIL import Image
    import story as S
    out, seen = [], []
    names = [img.name] + [o for o in scene.get("options") or [] if o != img.name]
    for nm in names:
        if len(out) >= n:
            break
        f = img if nm == img.name else scene_dir / nm
        if S.is_video(f.name):
            f = scene_dir / S.poster(f.name)
        if not f.exists():
            continue
        h = S._ahash(f)
        if any(S._same(h, x) for x in seen):
            continue
        try:
            out.append(Image.open(f).convert("RGB"))
            seen.append(h)
        except Exception:
            pass
    return out


def build(img: Path, scene: dict, i: int, W: int, H: int, D: float, workdir: Path,
          scene_dir: Path | None = None, layout: str = "", plan_title: str = "") -> Path:
    """ทำวิดีโอเงียบของฉาก (สไตล์สารคดีนิตยสาร) คืน path .mp4"""
    from PIL import Image, ImageDraw
    import story as S
    scene_dir = scene_dir or img.parent
    vertical = H > W
    if S.is_video(img.name):  # ฉากวิดีโอ → ใช้ภาพตัวอย่างของคลิปเป็นภาพนิ่ง
        img = img.parent / S.poster(img.name)
    photos = _photos(img, scene, scene_dir, 2 if (scene.get("quote") and vertical) else 3) or [Image.new("RGB", (800, 600), (90, 80, 70))]
    main = photos[0]
    lay = layout or pick_layout(scene, i)
    sc = _Scene(W, H, D, workdir, i)
    u = sc.u * (1.0 if vertical else 1.25)
    rnd = random.Random(i * 7 + 3)
    # พื้นที่ว่างสำหรับเนื้อหา (เว้นด้านล่างให้ซับ)
    top, bot = (0.13 * H, 0.70 * H) if vertical else (0.07 * H, 0.80 * H)
    kicker = (scene.get("badge") or "").strip()
    l1, l2 = _title_text(scene, plan_title)
    accent = "FFC531"

    def title_block(x, y, maxw, dark_bg: bool, size=150, align=7):
        nonlocal l1, l2
        c1 = "FFFFFF" if dark_bg else _hex(INK)
        s = size * u
        longest = max(len(l1), len(l2), 1)
        while s > 60 * u and max(G.text_w(l1, s), G.text_w(l2, s)) > maxw:
            s *= 0.92
        if kicker:
            sc.text(6, 0.35, x, y - 0.5 * s, kicker, max(36 * u, 0.24 * s), accent if dark_bg else "B5451B", align)
        if l1:
            sc.text(6, 0.2, x, y, l1, s, c1, align, "\\fscx94\\fscy112")
        sc.text(6, 0.38, x, y + (1.02 * s if l1 else 0), l2, s * 1.05, accent if dark_bg else "D9480F", align,
                "\\fscx94\\fscy112")
        return y + (1.02 * s if l1 else 0) + 1.2 * s

    if lay == "title":
        dark = i % 2 == 0
        sc.bg(Image.new("RGB", (W, H), (18, 18, 20)) if dark else _paper(W, H, i))
        cut = _cutout(main, int(W * (0.8 if vertical else 0.42)), int((bot - top) * (0.78 if vertical else 1.0)))
        if vertical:
            title_block(0.07 * W, top + 0.04 * H, 0.86 * W, dark, 190)
            if cut is not None:
                sc.add(cut, min(W * 0.98 - cut.width, (W - cut.width) / 2 + 0.12 * W), bot - cut.height + 0.06 * H, 0.15, "up")
            else:
                pr = _print(main, int(W * 0.7), int((bot - top) * 0.5), angle=rnd.uniform(-3, 3))
                sc.add(pr, (W - pr.width) / 2, bot - pr.height, 0.15, "up")
        else:
            title_block(0.07 * W, H * 0.3, 0.5 * W, dark, 170)
            if cut is not None:
                sc.add(cut, W * 0.93 - cut.width, bot - cut.height + 0.05 * H, 0.15, "up")
            else:
                pr = _print(main, int(W * 0.36), int(H * 0.5), angle=rnd.uniform(-3, 3))
                sc.add(pr, W * 0.93 - pr.width, H * 0.45 - pr.height / 2, 0.15, "right")

    elif lay == "row":
        sc.bg(_paper(W, H, i))
        n = len(photos)
        tone = "sepia" if i % 3 == 1 else ""
        if vertical:
            if n == 1:
                pr = _print(main, int(W * 0.78), int((bot - top) * 0.62), angle=rnd.uniform(-2.5, 2.5), tone=tone)
                sc.add(pr, (W - pr.width) / 2, top + 0.02 * H, 0.15, "up")
                cap_y = top + 0.02 * H + pr.height + 0.01 * H
            else:
                ph = int((bot - top) / n * 0.92)
                cap_y = top
                for k, im in enumerate(photos):
                    pr = _print(im, int(W * 0.56), int(ph * 0.84), angle=(-2.2 if k % 2 else 2.0), tone=tone)
                    x = (W * 0.03) if k % 2 == 0 else (W * 0.97 - pr.width)
                    y = top + k * ph * 1.0
                    sc.add(pr, x, y, 0.15 + 0.4 * k, "left" if k % 2 == 0 else "right")
                    cap_y = y + pr.height
            if kicker:
                sc.text(6, 0.5, 0.08 * W, min(cap_y, bot - 30 * u), kicker, 34 * u, "6B5B4B", 7)
        else:
            pw = int(W * (0.23 if n >= 3 else 0.33 if n == 2 else 0.46))
            prs = [_print(im, pw, int(pw * 0.72), angle=rnd.uniform(-1.5, 1.5), tone=tone) for im in photos]
            total = sum(p_.width for p_ in prs)
            gap = (0.9 * W - total) / max(1, n - 1) if n > 1 else 0
            x = 0.05 * W if n > 1 else (W - total) / 2
            for k, pr in enumerate(prs):
                sc.add(pr, x, H * 0.16, 0.15 + 0.4 * k, "up")
                x += pr.width + gap
            if kicker:
                sc.text(6, 0.5, 0.08 * W, H * 0.18 + pw * 0.72 + 70 * u, kicker, 30 * u, "6B5B4B", 7)
        hl = (scene.get("headline") or "").strip()
        if hl:
            yy = (top - 0.035 * H) if vertical else 0.08 * H
            sc.text(6, 0.25, 0.08 * W, yy, hl, (54 if vertical else 46) * u, _hex(INK), 7)

    elif lay == "bigword":
        col = BOLD[i % len(BOLD)]
        sc.bg(Image.new("RGB", (W, H), col))
        dark_bg = col != BOLD[0]
        word = l2 if len(l2) <= 14 else (l2.split(" ")[0] if " " in l2 else l2[:14])
        s = 260 * u
        while s > 90 * u and G.text_w(word, s) > 0.86 * W:
            s *= 0.92
        cy = (top + bot) / 2 + (0.08 * H if vertical else 0)
        sc.text(6, 0.2, W / 2, cy, word, s, "FFFFFF" if dark_bg else _hex(INK), 5,
                "\\fscx70\\fscy70\\t(0,220,0.5,\\fscx100\\fscy100)")
        if l1:
            sc.text(6, 0.45, W / 2, cy - 0.62 * s, l1, s * 0.28, "FFFFFF" if dark_bg else _hex(INK), 2)
        pr = _print(main, int(W * (0.42 if vertical else 0.22)), int(W * (0.3 if vertical else 0.15)),
                    angle=rnd.uniform(-6, 6))
        sc.add(pr, W * 0.96 - pr.width, top if vertical else H * 0.56, 0.55, "right")

    elif lay == "sepia":
        bgim = _sepia(_fill(main, W, H, 0.35), 0.9 if i % 2 else 0.55)
        dr = ImageDraw.Draw(bgim)
        m = int(0.045 * min(W, H))
        L = int(0.06 * min(W, H))
        for (cx, cy, sx, sy) in ((m, m, 1, 1), (W - m, m, -1, 1), (m, H - m, 1, -1), (W - m, H - m, -1, -1)):
            dr.line((cx, cy, cx + sx * L, cy), fill=(255, 255, 255), width=3)
            dr.line((cx, cy, cx, cy + sy * L), fill=(255, 255, 255), width=3)
        sc.bg(bgim)
        sc.push = 0.09
        hl = (scene.get("headline") or "").strip()
        if hl:
            sc.text(6, 0.4, 0.07 * W, top - 0.01 * H if vertical else 0.1 * H, hl, (60 if vertical else 50) * u,
                    "FFFFFF", 7, "\\bord0\\shad3\\4a&H60&")
        if kicker:
            sc.text(6, 0.6, W - 0.07 * W, (bot - 0.02 * H) if vertical else 0.86 * H, kicker, 40 * u, "F4E6C8", 3, "\\bord0\\shad3\\4a&H60&")

    elif lay == "vinyl":
        col = (232, 168, 44) if i % 2 == 0 else (24, 24, 28)
        sc.bg(Image.new("RGB", (W, H), col))
        dark_bg = col[0] < 100
        d = int(min(W * 0.78, (bot - top) * 0.62) if vertical else H * 0.66)
        disc = _vinyl(main, d)
        spin = f"rotate=a='t*0.9':c=none:ow={d}:oh={d}"
        if vertical:
            sc.add(disc, (W - d) / 2, top + 0.01 * H, 0.1, "left", extra=spin)
            title_block(0.08 * W, top + d + 0.06 * H, 0.84 * W, dark_bg, 110)
        else:
            sc.add(disc, W * 0.08, (H - d) / 2 - 0.03 * H, 0.1, "left", extra=spin)
            title_block(W * 0.55, H * 0.36, 0.4 * W, dark_bg, 130)

    elif lay == "tv":
        sc.bg(_paper(W, H, i) if i % 2 else Image.new("RGB", (W, H), (34, 30, 28)))
        tw = int(W * 0.84) if vertical else int(W * 0.46)
        tv = _tv(main, tw)
        if vertical:
            sc.add(tv, (W - tv.width) / 2, top + 0.05 * H, 0.15, "up")
            hl = (scene.get("headline") or kicker).strip()
            if hl:
                sc.text(6, 0.45, W / 2, top + 0.05 * H + tv.height + 0.04 * H, hl, 56 * u,
                        "FFFFFF" if i % 2 == 0 else _hex(INK), 8)
        else:
            sc.add(tv, W * 0.07, (H - tv.height) / 2 - 0.04 * H, 0.15, "left")
            title_block(W * 0.6, H * 0.36, 0.34 * W, i % 2 == 0, 120)

    else:  # spot
        bgim = _fill(main, W, H, 0.35)
        cx, cy = W / 2, (top + bot) / 2 - (0.03 * H if vertical else 0.05 * H)
        r = min(W, H) * (0.34 if vertical else 0.3)
        sc.bg(bgim)
        sc.add(_spot_mask(W, H, cx, cy, r), 0, 0, 0.0, "none")
        ring = G._rect(2 * r, 2 * r, r)
        sc.ass.events.append(  # วงแหวนสีเหลืองซูมเข้ามาล้อมจุดเด่น
            f"Dialogue: 5,{P._ass_time(0.35)},{P._ass_time(D)},Sub,,0,0,0,,{{\\an5\\pos({cx:.0f},{cy:.0f})"
            f"\\bord{max(3, int(7 * u))}\\shad0\\1a&HFF&\\3c&H{'31C5FF'}&\\fscx160\\fscy160"
            f"\\t(0,450,0.5,\\fscx100\\fscy100)\\fad(150,200)\\p1}}{ring}{{\\p0}}")
        hl = (scene.get("headline") or "").strip()
        if hl:
            sc.text(6, 0.6, W / 2, cy + r + 0.03 * H, hl, (58 if vertical else 48) * u, "FFFFFF", 8,
                    "\\bord0\\shad3\\4a&H50&")
    out = workdir / f"ed_{i:03}.mp4"
    return sc.render(out, push=getattr(sc, "push", 0.05))
