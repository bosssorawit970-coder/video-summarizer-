"""
มาสคอตประจำช่อง: ตัวการ์ตูนของผู้ใช้ ลอยอยู่มุมจอตลอดคลิป + ติดบนภาพปก (ให้คนจำช่องได้)
  • อัปรูปพื้นขาว/พื้นเรียบได้ — ลบพื้นหลังที่ต่อกับขอบภาพให้เอง (สีขาวด้านในตัวการ์ตูนไม่หาย)
  • ในคลิป: เลื่อนเข้ามาตอนต้นคลิป แล้วโยกขึ้นลงเบาๆ ตลอด (ไม่บังเนื้อหา)
"""
from __future__ import annotations

from pathlib import Path

import pipeline as P

POSITIONS = {"top_right": "มุมขวาบน", "bottom_left": "มุมซ้ายล่าง", "bottom_right": "มุมขวาล่าง"}


def _main_only(im):
    """เก็บเฉพาะชิ้นที่ใหญ่ที่สุด (ตัวการ์ตูน) — ลบของประกอบที่ลอยแยกอยู่รอบๆ เช่น หลอดไฟ เครื่องหมาย ! ?"""
    import numpy as np
    from PIL import Image
    a = np.asarray(im.getchannel("A")) > 40
    k = max(1, max(a.shape) // 320)  # วิเคราะห์บนภาพย่อ (เร็ว ไม่ต้องใช้ไลบรารีเพิ่ม)
    small = a[::k, ::k]
    h, w = small.shape
    lab = np.zeros((h, w), np.int32)
    sizes, n = {}, 0
    for y0 in range(h):
        for x0 in range(w):
            if small[y0, x0] and not lab[y0, x0]:
                n += 1
                stack, cnt = [(y0, x0)], 0
                lab[y0, x0] = n
                while stack:
                    y, x = stack.pop()
                    cnt += 1
                    for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                        if 0 <= yy < h and 0 <= xx < w and small[yy, xx] and not lab[yy, xx]:
                            lab[yy, xx] = n
                            stack.append((yy, xx))
                sizes[n] = cnt
    if len(sizes) < 2:
        return im
    keep = max(sizes, key=sizes.get)
    mask = Image.fromarray(((lab == keep) * 255).astype("uint8"), "L")
    from PIL import ImageFilter
    mask = mask.resize((mask.width * k, mask.height * k), Image.NEAREST).crop((0, 0, im.width, im.height))
    full = Image.new("L", im.size, 0)
    full.paste(mask, (0, 0))
    full = full.filter(ImageFilter.MaxFilter(2 * k + 1))  # กันขอบตัวโดนกินจากการย่อ
    alpha = Image.fromarray(np.minimum(np.asarray(im.getchannel("A")), np.asarray(full)).astype("uint8"), "L")
    im = im.copy()
    im.putalpha(alpha)
    return im


def prepare(src: Path, out: Path, main_only: bool = False) -> Path:
    """รูปมาสคอต → PNG พื้นใส ตัดขอบว่าง (ถ้ารูปมีพื้นใสอยู่แล้วใช้ตามเดิม)
    main_only: ลบของประกอบที่ลอยแยกจากตัว (หลอดไฟ เครื่องหมาย ฯลฯ)"""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGBA")
    im.thumbnail((1200, 1200))
    a = np.asarray(im.getchannel("A"))
    if (a < 250).mean() < 0.02:  # ไม่มีพื้นใส → เทสีจากขอบภาพ หาพื้นหลังที่ต่อกับขอบ
        rgb = im.convert("RGB")
        mark = (255, 0, 255)
        w, h = rgb.size
        seeds = [(x, y) for x in range(0, w, max(1, w // 16)) for y in (0, h - 1)] + \
                [(x, y) for y in range(0, h, max(1, h // 16)) for x in (0, w - 1)]
        for sx, sy in seeds:
            if rgb.getpixel((sx, sy)) != mark:
                ImageDraw.floodfill(rgb, (sx, sy), mark, thresh=40)
        arr = np.asarray(rgb)
        bg = (arr[..., 0] == 255) & (arr[..., 1] == 0) & (arr[..., 2] == 255)
        alpha = Image.fromarray(np.where(bg, 0, 255).astype("uint8"), "L")
        alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
        im.putalpha(alpha)
    if main_only:
        im = _main_only(im)
    bb = im.getchannel("A").point(lambda v: 255 if v > 20 else 0).getbbox()
    if bb:
        im = im.crop(bb)
    out.parent.mkdir(parents=True, exist_ok=True)
    im.save(out)
    return out


def _box(W: int, H: int, pos: str) -> tuple[int, int, int]:
    """(ความสูงมาสคอต, x, y) — หลบปุ่ม/ข้อความของแอปที่ทับขอบจอ Shorts/TikTok"""
    vertical = H > W
    mh = int(H * (0.12 if vertical else 0.2)) // 2 * 2
    m = int(W * 0.03)
    if pos == "bottom_left":
        return mh, m, int(H * (0.80 if vertical else 0.95)) - mh
    if pos == "bottom_right":
        return mh, -1, int(H * (0.80 if vertical else 0.95)) - mh
    return mh, -1, int(H * (0.12 if vertical else 0.05))  # top_right


def overlay(video: Path, mascot: Path, out: Path, pos: str = "top_right") -> None:
    """ใส่มาสคอตทั้งคลิป: เลื่อนเข้ามาตอน 0.5 วิ แล้วโยกเบาๆ (เสียงไม่แปลงใหม่)"""
    info = P.probe(video)
    W, H = int(info["width"]), int(info["height"])
    mh, x, y = _box(W, H, pos)
    m = int(W * 0.03)
    right = x < 0
    # เลื่อนเข้าจากขอบ 0.5→0.8 วิ (ช้า-เร็ว-ช้า) · โยกขึ้นลง + ส่ายซ้ายขวานิดๆ
    p = "min(max((t-0.5)/0.3,0),1)"
    slide = f"(1-{p})*(1-{p})*(w+{m})"
    xs = f"W-w-{m}+{slide}" if right else f"{x}-{slide}"
    ys = f"{y}+6*sin(t*2.4)"
    fc = (f"[1:v]scale=-2:{mh},format=rgba[mc];"
          f"[0:v][mc]overlay=x='{xs}':y='{ys}':shortest=1:format=auto,format=yuv420p[v]")
    P.run(["ffmpeg", "-y", "-hide_banner", "-i", str(video), "-loop", "1", "-i", str(mascot),
           "-filter_complex", fc, "-map", "[v]", "-map", "0:a?", *P._final_video_args(P._has_nvenc()),
           "-r", "30", "-c:a", "copy", "-movflags", "+faststart", "-t", f"{info['duration']:.3f}", str(out)])


def sticker_layer(mascot: Path, W: int, H: int, vertical: bool):
    """มาสคอตสำหรับภาพปก: ใหญ่ขึ้น ขอบขาว มีเงา วางมุมล่าง (คืนเลเยอร์ RGBA ขนาด W×H)"""
    from PIL import Image, ImageFilter
    im = Image.open(mascot).convert("RGBA")
    th = int(H * (0.24 if vertical else 0.34))
    im = im.resize((max(1, int(im.width * th / im.height)), th), Image.LANCZOS)
    pad = max(6, int(th * 0.035))
    a = im.getchannel("A")
    big = Image.new("L", (im.width + pad * 4, im.height + pad * 4), 0)
    big.paste(a, (pad * 2, pad * 2))
    outline = big.filter(ImageFilter.MaxFilter(pad * 2 + 1))
    shadow = outline.filter(ImageFilter.GaussianBlur(pad * 1.5))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    x = int(W * 0.03) if vertical else W - big.width - int(W * 0.02)
    y = H - big.height - int(H * 0.03) if vertical else int(H * 0.03)  # แนวนอน: มุมขวาบน (ซ้ายเป็นข้อความ)
    layer.paste(Image.new("RGBA", big.size, (0, 0, 0, 140)), (x + pad, y + pad), shadow)
    layer.paste(Image.new("RGBA", big.size, (255, 255, 255, 255)), (x, y), outline)
    layer.paste(im, (x + pad * 2, y + pad * 2), im)
    return layer
