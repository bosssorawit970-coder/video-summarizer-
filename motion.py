"""
ภาพนิ่ง → วิดีโอสั้น 1-4 วินาทีที่มีโมชันนิดๆ
  • เอฟเฟกต์กล้อง (ฟรี เร็ว ไม่ต้องใช้การ์ดจอ): ซูม · แพน · 3D ลอยมิติ (แยกฉากหน้า/หลัง) · กล้องมือถือ · แสงวิ้ง · หายใจ
  • ✨ AI ขยับของในภาพ (Stable Video Diffusion) — ใช้การ์ด NVIDIA ในคอม (ติดตั้ง PyTorch ให้เองครั้งแรก) หรือ Colab GPU
ทำงานทีละเฟรมด้วย PIL (ซับพิกเซล ไม่สั่นเหมือน zoompan ของ ffmpeg) แล้วส่งให้ ffmpeg เข้ารหัส
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

FPS = 30
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")  # Windows: ไม่ต้องเตือนเรื่อง symlink

EFFECTS = {
    "auto": "🪄 อัตโนมัติ (มีตัวเด่น → 3D ลอยมิติ, ไม่มี → ซูมเข้า)",
    "parallax": "🧊 3D ลอยมิติ (ฉากหน้าขยับแยกจากฉากหลัง)",
    "zoom_in": "🔍 ซูมเข้าช้าๆ",
    "zoom_out": "🔎 ซูมออก",
    "pan_left": "⬅️ เลื่อนกล้องไปซ้าย",
    "pan_right": "➡️ เลื่อนกล้องไปขวา",
    "pan_up": "⬆️ เลื่อนกล้องขึ้น",
    "pan_down": "⬇️ เลื่อนกล้องลง",
    "handheld": "🤳 กล้องมือถือ (สั่นไหวเบาๆ เหมือนถ่ายจริง)",
    "light": "✨ แสงวิ้งพาดผ่าน + ซูมเบาๆ (เหมาะกับสินค้า)",
    "breathe": "🫧 หายใจ (ซูมเข้า-ออกเบาๆ วนลูปได้เนียน)",
    "ai": "🤖 AI ขยับของในภาพ (ผม/น้ำ/เมฆ/คนขยับ — ต้องมีการ์ดจอ)",
}

ASPECTS = {"original": "ขนาดเดิมของภาพ", "9:16": "แนวตั้ง 9:16 (TikTok/Reels)",
           "1:1": "จัตุรัส 1:1", "16:9": "แนวนอน 16:9 (YouTube)"}

STRENGTH = {"soft": 0.6, "normal": 1.0, "strong": 1.6}


# ───────────────────────── เตรียมภาพ ─────────────────────────

def _ease(t: float) -> float:
    """ช้า-เร็ว-ช้า (ดูเป็นกล้องจริง ไม่กระตุกตอนเริ่ม/จบ)"""
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def _size_for(w: int, h: int, aspect: str) -> tuple[int, int]:
    if aspect == "9:16":
        return 1080, 1920
    if aspect == "1:1":
        return 1080, 1080
    if aspect == "16:9":
        return 1920, 1080
    s = min(1.0, 1920 / max(w, h))
    if max(w, h) < 720:  # ภาพเล็กมาก → ขยายขึ้นหน่อยให้คมพอสำหรับมือถือ
        s = 1080 / max(w, h)
    return max(2, int(w * s) // 2 * 2), max(2, int(h * s) // 2 * 2)


def _fit_canvas(im, W: int, H: int):
    """วางภาพลงเฟรม W×H — สัดส่วนใกล้กัน: ครอบตัดเต็มจอ · ต่างกันมาก: ภาพเต็ม + พื้นหลังเบลอจากภาพเดิม"""
    from PIL import Image, ImageFilter, ImageOps
    r_im, r_fr = im.width / im.height, W / H
    if abs(math.log(r_im / r_fr)) < 0.25:
        return ImageOps.fit(im, (W, H), Image.LANCZOS)
    bg = ImageOps.fit(im, (W // 4, H // 4), Image.BILINEAR).filter(ImageFilter.GaussianBlur(14))
    bg = bg.resize((W, H), Image.BILINEAR)
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.25)
    fg = ImageOps.contain(im, (W, H), Image.LANCZOS)
    bg.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    return bg


def load(path: Path, aspect: str = "original"):
    from PIL import Image, ImageOps
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    W, H = _size_for(im.width, im.height, aspect)
    return _fit_canvas(im, W, H), (W, H)


# ───────────────────────── กล้องเสมือน ─────────────────────────

def _cam(src, W: int, H: int, s: float, cx: float, cy: float, rot: float = 0.0, clamp: bool = True):
    """มุมกล้อง: ซูม s เท่า โฟกัสจุด (cx, cy) เป็นสัดส่วนของภาพ, หมุน rot องศา → ภาพขนาด W×H"""
    from PIL import Image
    sw, sh = src.size
    # จุดกึ่งกลางกล้องต้องไม่ทำให้เห็นขอบภาพ
    half_w, half_h = sw / (2 * s), sh / (2 * s)
    px, py = cx * sw, cy * sh
    if clamp:
        px = min(max(px, half_w), sw - half_w)
        py = min(max(py, half_h), sh - half_h)
    k = sw / (W * s)  # พิกเซลภาพต้นทางต่อพิกเซลผลลัพธ์
    a = math.radians(rot)
    ca, sa = math.cos(a) * k, math.sin(a) * k
    # พิกัดผลลัพธ์ (x,y) → ต้นทาง: หมุน/ย่อรอบกึ่งกลางเฟรม
    c = px - ca * W / 2 + sa * H / 2
    f = py - sa * W / 2 - ca * H / 2
    return src.transform((W, H), Image.AFFINE, (ca, -sa, c, sa, ca, f), resample=Image.BICUBIC)


def _subject(img):
    """แยกตัวเด่น (คน/สัตว์/สินค้า) ออกจากฉากหลังด้วย rembg → (RGBA ขนาดเท่าภาพ, สัดส่วนพื้นที่) หรือ (None, 0)"""
    try:
        import product as PR
        if PR._rembg is None:  # ใช้ตัวตัดพื้นหลังตัวเดียวกับโหมดสินค้า (ติดตั้งเองครั้งแรก)
            PR.cutout(img.resize((96, 96)))
        if PR._rembg is None:
            raise RuntimeError("ติดตั้งตัวตัดพื้นหลัง (rembg) ไม่ได้")
        from rembg import remove
        rgba = remove(img, session=PR._rembg, post_process_mask=True)
        a = rgba.getchannel("A")
        frac = sum(a.point(lambda v: 1 if v > 128 else 0).getdata()) / (img.width * img.height)
        if not 0.04 < frac < 0.85:
            return None, frac
        return rgba, frac
    except Exception as e:
        print("แยกฉากหน้าไม่ได้:", str(e)[-200:])
        return None, 0.0


def _clean_plate(img, rgba):
    """ฉากหลังที่ลบตัวเด่นออก (เติมด้วยภาพเบลอรอบๆ) — ตอนฉากหน้าขยับจะไม่เห็นเงาซ้อน"""
    from PIL import Image, ImageFilter
    m = rgba.getchannel("A").point(lambda v: 255 if v > 30 else 0).filter(ImageFilter.MaxFilter(15))
    small = img.resize((max(8, img.width // 8), max(8, img.height // 8)), Image.BILINEAR)
    holes = small.filter(ImageFilter.GaussianBlur(6)).resize(img.size, Image.BILINEAR)
    plate = Image.composite(holes, img, m)
    return plate.filter(ImageFilter.GaussianBlur(1.2))


def _light_band(W: int, H: int, t: float, strength: float):
    """แถบแสงเฉียงวิ่งผ่านภาพ (คืน mask L)"""
    import numpy as np
    from PIL import Image
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = (xx + yy * 0.55) / (W + H * 0.55)  # 0..1 ตามแนวเฉียง
    pos = -0.25 + 1.5 * t
    band = np.exp(-((d - pos) / 0.07) ** 2) * 150 * strength
    return Image.fromarray(np.clip(band, 0, 255).astype("uint8"), "L")


def frames(img, effect: str, seconds: float, strength: str = "normal", loop: bool = False, fg=None):
    """สร้างเฟรมทั้งหมด (generator ของภาพ PIL) — parallax ต้องส่งภาพตัวเด่น fg (RGBA) มาด้วย"""
    from PIL import Image
    W, H = img.size
    n = max(8, int(round(seconds * FPS)))
    k = STRENGTH.get(strength, 1.0)
    plate = None
    if effect == "parallax":
        if fg is None:
            effect = "zoom_in"
        else:
            plate = _clean_plate(img, fg)
    # จุดศูนย์กลางของตัวเด่น (ให้ฉากหน้าซูมเข้าหาตัวเอง)
    if fg is not None:
        bb = fg.getchannel("A").point(lambda v: 255 if v > 128 else 0).getbbox() or (0, 0, W, H)
        fcx, fcy = (bb[0] + bb[2]) / 2 / W, (bb[1] + bb[3]) / 2 / H
    for i in range(n):
        u = i / (n - 1)
        if loop:  # ไป-กลับ ให้เฟรมแรกกับเฟรมสุดท้ายตรงกัน วนลูปเนียน
            u = 1 - abs(1 - 2 * u)
        t = _ease(u)
        if effect == "zoom_in":
            yield _cam(img, W, H, 1 + 0.12 * k * t, 0.5, 0.5)
        elif effect == "zoom_out":
            yield _cam(img, W, H, 1 + 0.12 * k * (1 - t), 0.5, 0.5)
        elif effect.startswith("pan_"):
            s = 1 + 0.12 * k
            span = (1 - 1 / s) / 2  # เลื่อนได้สุดขอบพอดี
            p = (t - 0.5) * 2 * span
            cx, cy = {"pan_left": (0.5 - p, 0.5), "pan_right": (0.5 + p, 0.5),
                      "pan_up": (0.5, 0.5 - p), "pan_down": (0.5, 0.5 + p)}[effect]
            yield _cam(img, W, H, s, cx, cy)
        elif effect == "handheld":
            T = i / FPS
            a = 0.004 * k
            cx = 0.5 + a * (math.sin(T * 2.1) + 0.5 * math.sin(T * 5.3 + 1))
            cy = 0.5 + a * (math.sin(T * 1.7 + 2) + 0.5 * math.sin(T * 4.1))
            rot = 0.35 * k * math.sin(T * 1.3 + 0.5)
            yield _cam(img, W, H, 1.06 + 0.02 * k * t, cx, cy, rot)
        elif effect == "breathe":
            w = (1 - math.cos(2 * math.pi * i / n)) / 2  # 0→1→0 ครบรอบพอดี
            yield _cam(img, W, H, 1.02 + 0.05 * k * w, 0.5, 0.5)
        elif effect == "light":
            fr = _cam(img, W, H, 1 + 0.06 * k * t, 0.5, 0.5)
            band = _light_band(W, H, u if not loop else i / (n - 1), min(1.4, k))
            yield Image.composite(Image.new("RGB", (W, H), (255, 250, 235)), fr, band)
        elif effect == "parallax":
            # กล้องเลื่อนเข้า + เอียงข้าง: ฉากหลังขยับน้อย ฉากหน้าขยับมาก → เกิดมิติ
            sb = 1.06 + 0.04 * k * t
            sf = 1.06 + 0.12 * k * t
            dx = (t - 0.5) * 0.03 * k
            fx, fy = 0.5 * 0.65 + fcx * 0.35, 0.5 * 0.65 + fcy * 0.35
            bgf = _cam(plate, W, H, sb, fx - dx * 0.4, fy)
            # ฉากหน้าใช้จุดกล้องเดียวกับฉากหลัง (ไม่บีบขอบ) → ตัวเด่นยังอยู่ตรงตำแหน่งเดิม แค่ใหญ่ขึ้น/เลื่อนมากกว่า
            bx = min(max(fx - dx * 0.4, 1 / (2 * sb)), 1 - 1 / (2 * sb))
            by = min(max(fy, 1 / (2 * sb)), 1 - 1 / (2 * sb))
            # จุดกล้องฉากหน้าที่ทำให้กึ่งกลางตัวเด่นอยู่ตำแหน่งเดียวกับรูของมันในฉากหลัง + เลื่อนเพิ่มตาม dx
            gx = fcx - (fcx - bx) * sb / sf - dx * 0.6
            gy = fcy - (fcy - by) * sb / sf
            fgf = _cam(fg, W, H, sf, gx, gy, clamp=False)
            bgf.paste(fgf, (0, 0), fgf)
            yield bgf
        else:
            raise ValueError(f"ไม่รู้จักเอฟเฟกต์ {effect}")


def encode(frame_iter, out: Path, W: int, H: int, fps: int = FPS) -> None:
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for fr in frame_iter:
            if fr.size != (W, H):  # กันเฟรมขนาดไม่ตรง (ไม่งั้นภาพออกมาเป็นลายเส้นเละ)
                fr = fr.resize((W, H))
            p.stdin.write(fr.convert("RGB").tobytes())
        p.stdin.close()
    except BrokenPipeError:
        pass
    err = p.stderr.read().decode("utf-8", "replace")
    if p.wait() != 0:
        raise RuntimeError(f"เข้ารหัสวิดีโอไม่ได้: {err[-400:]}")


def make_gif(mp4: Path, gif: Path, width: int = 480) -> None:
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(mp4), "-vf",
                    f"fps=15,scale={width}:-2:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];"
                    f"[b][p]paletteuse=dither=bayer:bayer_scale=4", "-loop", "0", str(gif)], check=True,
                   capture_output=True)


# ───────────────────────── ✨ AI (Stable Video Diffusion) ─────────────────────────

_svd = None


def nvidia_gpu() -> dict | None:
    """การ์ดจอ NVIDIA ในเครื่อง (ดูจาก nvidia-smi ไม่ต้องมี torch) → {"name", "vram_gb"} หรือ None"""
    import shutil
    exe = shutil.which("nvidia-smi")
    if not exe and sys.platform.startswith("win"):
        p = Path(r"C:\Windows\System32\nvidia-smi.exe")
        exe = str(p) if p.exists() else None
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15)
        name, mem = [x.strip() for x in r.stdout.strip().splitlines()[0].split(",")[:2]]
        cap = 0.0
        try:  # รุ่นสถาปัตยกรรมการ์ด (ไดรเวอร์เก่าไม่มีคำสั่งนี้)
            c = subprocess.run([exe, "--query-gpu=compute_cap", "--format=csv,noheader"],
                               capture_output=True, text=True, timeout=15)
            cap = float(c.stdout.strip().splitlines()[0])
        except Exception:
            pass
        return {"name": name, "vram_gb": round(float(mem) / 1024, 1), "cap": cap}
    except Exception:
        return None


def _torch_cuda() -> bool | None:
    """True = torch ใช้การ์ดจอได้ · False = มี torch แต่เป็นรุ่น CPU · None = ยังไม่มี torch"""
    try:
        import torch
    except Exception:
        return None
    if not torch.cuda.is_available():
        return False
    try:  # torch รุ่นเก่ากับการ์ดใหม่ (เช่น RTX 50) → is_available() ได้ True แต่รันจริงไม่ได้
        major, minor = torch.cuda.get_device_capability(0)
        archs = torch.cuda.get_arch_list()
        if archs and f"sm_{major}{minor}" not in archs and not any(a.startswith(f"sm_{major}") for a in archs):
            return False
    except Exception:
        pass
    return True


def ai_available() -> bool:
    """ใช้ AI ขยับภาพได้ไหม: มี torch+CUDA แล้ว หรือมีการ์ด NVIDIA (จะติดตั้ง torch ให้ตอนใช้ครั้งแรก)"""
    return bool(_torch_cuda()) or nvidia_gpu() is not None


def ai_status() -> str:
    g = nvidia_gpu()
    if _torch_cuda():
        return f"พร้อม ({g['name']} {g['vram_gb']} GB)" if g else "พร้อม"
    if g:
        warn = " — การ์ดจอหน่วยความจำน้อย อาจช้าหรือไม่พอ" if g["vram_gb"] < 6 else ""
        return f"ใช้การ์ดจอ {g['name']} {g['vram_gb']} GB ได้ (ครั้งแรกติดตั้งไลบรารี ~3 GB){warn}"
    return ""


def _ensure_torch(progress=None) -> None:
    """เครื่องมีการ์ด NVIDIA แต่ยังไม่มี torch รุ่นการ์ดจอ → ติดตั้งให้ (ครั้งเดียว ~2.5 GB)"""
    st = _torch_cuda()
    if st:
        return
    if not nvidia_gpu():
        raise RuntimeError("ไม่พบการ์ดจอ NVIDIA (AI ขยับภาพต้องใช้การ์ด NVIDIA หรือ Colab GPU)")
    if st is False and "torch" in sys.modules:
        # มี torch รุ่น CPU โหลดค้างอยู่แล้ว → ติดตั้งทับได้ แต่ต้องปิด-เปิดโปรแกรมใหม่
        pass
    if progress:
        progress("กำลังติดตั้ง PyTorch สำหรับการ์ดจอ (ครั้งแรกครั้งเดียว ~2.5 GB อาจใช้ 5-20 นาที)")
    g = nvidia_gpu() or {}
    # การ์ดใหม่ (RTX 20 ขึ้นไป รวม RTX 50 ซีรีส์ Blackwell) → PyTorch CUDA 12.8 (RTX 50 ใช้ได้แค่รุ่นนี้ขึ้นไป)
    # การ์ดเก่า (GTX 10/16 ซีรีส์ Pascal/Volta) → CUDA 12.6 ที่ยังรองรับ
    cap = g.get("cap") or (12.0 if "RTX 50" in g.get("name", "") else 7.5)
    cu = "cu128" if cap >= 7.5 else "cu126"
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "torch", "--index-url",
           f"https://download.pytorch.org/whl/{cu}"]
    if st is False:
        cmd.insert(5, "--force-reinstall")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ติดตั้ง PyTorch ไม่สำเร็จ: " + (r.stderr or r.stdout)[-300:])
    if "torch" in sys.modules:
        raise RuntimeError("ติดตั้ง PyTorch รุ่นการ์ดจอแล้ว — ปิดหน้าต่างดำแล้วเปิด run.bat ใหม่ 1 ครั้ง แล้วกดทำอีกรอบ")
    if not _torch_cuda():
        raise RuntimeError("ติดตั้ง PyTorch แล้วแต่ยังใช้การ์ดจอไม่ได้ — ลองอัปเดตไดรเวอร์การ์ดจอ NVIDIA แล้วเปิดโปรแกรมใหม่")


def _free_other_models() -> None:
    """ปล่อยโมเดลวาดภาพที่ค้างในการ์ดจอ (การ์ด Colab 15 GB ใส่สองโมเดลพร้อมกันไม่พอ)"""
    try:
        import gc

        import torch

        import imagegen
        if getattr(imagegen, "_pipe", None) is not None:
            imagegen._pipe = None
            imagegen._pipe_err = None
        gc.collect()
        torch.cuda.empty_cache()
    except Exception:
        pass


def _load_svd(progress=None):
    global _svd
    if _svd is not None:
        return _svd
    _ensure_torch(progress)
    import torch
    try:
        import diffusers  # noqa: F401
        from diffusers import StableVideoDiffusionPipeline  # noqa: F401
    except Exception:
        if progress:
            progress("กำลังติดตั้งไลบรารี AI วิดีโอ (ครั้งแรก ~1-2 นาที)")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U", "diffusers", "transformers", "accelerate"],
                       check=True, capture_output=True)
    from diffusers import StableVideoDiffusionPipeline
    _free_other_models()
    if progress:
        progress("กำลังโหลดโมเดล AI วิดีโอ (ครั้งแรกดาวน์โหลด ~4 GB ใช้เวลาหลายนาที)")
    name = "stabilityai/stable-video-diffusion-img2vid-xt"
    try:
        pipe = StableVideoDiffusionPipeline.from_pretrained(name, torch_dtype=torch.float16, variant="fp16")
    except TypeError:
        pipe = StableVideoDiffusionPipeline.from_pretrained(name, dtype=torch.float16, variant="fp16")
    pipe.enable_model_cpu_offload()
    pipe.unet.enable_forward_chunking()
    pipe.set_progress_bar_config(disable=True)
    _svd = pipe
    return pipe


def release_ai() -> None:
    global _svd
    _svd = None
    _free_other_models()


def ai_frames(img, strength: str = "normal", seed: int = 0, progress=None):
    """ให้ AI ขยับภาพ: คืน list ภาพ 25 เฟรม (ขนาดที่โมเดลถนัด 1024×576 หรือ 576×1024)"""
    from PIL import Image, ImageOps
    pipe = _load_svd(progress)
    import torch
    land = img.width >= img.height
    g = nvidia_gpu()
    small = bool(g and g["vram_gb"] < 10)  # การ์ดเกม 6-8 GB → ลดขนาดภาพ ไม่ให้หน่วยความจำเต็ม
    # ขนาดต้องหาร 64 ลงตัว (ไม่งั้นโมเดลให้ภาพเพี้ยน)
    w, h = ((768, 448) if small else (1024, 576)) if land else ((448, 768) if small else (576, 1024))
    if abs(img.width / img.height - 1) < 0.15:
        w, h = (576, 576) if small else (768, 768)
    src = ImageOps.fit(img, (w, h), Image.LANCZOS)
    motion = {"soft": 70, "normal": 127, "strong": 180}.get(strength, 127)
    if progress:
        progress("AI กำลังสร้างการเคลื่อนไหว (~2-5 นาที/ภาพ ขึ้นกับการ์ดจอ)")
    gen = torch.manual_seed(seed or 42)
    import time
    steps, t0 = 25, time.time()

    def on_step(_p, i, _t, kw):
        done = i + 1
        left = (time.time() - t0) / done * (steps - done)
        msg = f"AI กำลังสร้างการเคลื่อนไหว ขั้นที่ {done}/{steps} (เหลืออีกราว {max(1, round(left / 60))} นาที)"
        print(msg, flush=True)
        if progress:
            progress(msg)
        return kw

    kw = dict(height=h, width=w, decode_chunk_size=1 if small else 2, generator=gen, num_frames=25, motion_bucket_id=motion,
              noise_aug_strength=0.02, fps=12, num_inference_steps=steps)
    try:
        res = pipe(src, callback_on_step_end=on_step, **kw)
    except TypeError:  # diffusers รุ่นเก่าไม่มี callback
        res = pipe(src, **kw)
    if progress:
        progress("AI สร้างเสร็จแล้ว กำลังถอดเป็นภาพทีละเฟรม…")
    out = list(res.frames[0])
    if out and not hasattr(out[0], "size"):  # numpy → PIL
        out = [Image.fromarray((f * 255).clip(0, 255).astype("uint8") if f.dtype != "uint8" else f) for f in out]
    try:  # ภาพดำ/สีเดียวทั้งภาพ = การ์ดคำนวณพัง (NaN) → ไม่ส่งของเสียให้ผู้ใช้
        import numpy as np
        if float(np.asarray(out[len(out) // 2].convert("L")).std()) < 2:
            raise RuntimeError("AI ให้ภาพว่างเปล่า (การ์ดจอคำนวณผิดพลาด)")
    except RuntimeError:
        raise
    except Exception:
        pass
    return out, out[0].size if out else (w, h)


def ai_video(img, out: Path, W: int, H: int, seconds: float, strength: str, loop: bool, progress=None) -> None:
    """เฟรมจาก AI → ยืดให้ได้ความยาวที่ต้องการ + เติมเฟรมระหว่างกลาง (ลื่นแบบ 30 fps) + ขยายเป็นขนาดผลลัพธ์"""
    fr, (w, h) = ai_frames(img, strength, progress=progress)
    if loop:
        fr = list(fr) + list(fr[-2:0:-1])
    tmp = out.with_name(out.stem + "_raw.mp4")
    src_fps = len(fr) / max(0.5, seconds)
    encode(iter(fr), tmp, w, h, fps=max(1, round(src_fps)))
    if progress:
        progress("กำลังเติมเฟรมให้ลื่น และขยายภาพ")
    vf = (f"minterpolate=fps={FPS}:mi_mode=mci:mc_mode=aobmc:vsbmc=1,"
          f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},format=yuv420p")
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp), "-vf", vf,
                        "-t", f"{seconds:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
                        "-movflags", "+faststart", str(out)], capture_output=True, text=True)
    if r.returncode != 0:  # minterpolate ไม่มี/ช้า → แค่ปรับ fps
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(tmp), "-vf",
                        vf.replace(f"minterpolate=fps={FPS}:mi_mode=mci:mc_mode=aobmc:vsbmc=1", f"fps={FPS}"),
                        "-t", f"{seconds:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
                        "-movflags", "+faststart", str(out)], check=True, capture_output=True)
    tmp.unlink(missing_ok=True)


# ───────────────────────── ทางเข้าหลัก ─────────────────────────

def animate(src: Path, out: Path, effect: str = "auto", seconds: float = 2.0, aspect: str = "original",
            strength: str = "normal", loop: bool = False, gif: bool = False,
            progress: Callable[[str], None] | None = None) -> dict:
    """ภาพ 1 ภาพ → วิดีโอ mp4 (และ gif ถ้าขอ) คืน {"effect": เอฟเฟกต์ที่ใช้จริง, "note": ข้อความเตือน}"""
    seconds = min(6.0, max(1.0, float(seconds)))
    img, (W, H) = load(src, aspect)
    note = ""
    used = effect
    if effect == "ai":
        if ai_available():
            try:
                ai_video(img, out, W, H, seconds, strength, loop, progress)
            except Exception as e:
                note = f"AI ขยับภาพไม่สำเร็จ ({str(e)[-160:]}) — ใช้เอฟเฟกต์ 3D ลอยมิติแทน"
                print(note)
                used = "auto"
        else:
            note = "ไม่พบการ์ดจอ NVIDIA — AI ขยับภาพไม่ได้ (ใช้ได้บน Colab GPU) ใช้เอฟเฟกต์ 3D ลอยมิติแทน"
            used = "auto"
    if used in ("auto", "parallax"):
        if progress:
            progress("กำลังแยกตัวเด่นออกจากฉากหลัง (ครั้งแรกโหลดโมเดล ~1 นาที)")
        fg, _ = _subject(img)
        if fg is None:
            if used == "parallax":
                note = (note + " · " if note else "") + "ไม่เจอตัวเด่นชัดๆ ในภาพ — ใช้ซูมเข้าแทน 3D"
            used = "zoom_in"
        else:
            used = "parallax"
    else:
        fg = None
    if used != "ai":
        if progress:
            progress("กำลังสร้างวิดีโอ")
        encode(frames(img, used, seconds, strength, loop, fg), out, W, H)
    if gif:
        make_gif(out, out.with_suffix(".gif"))
    return {"effect": used, "note": note, "width": W, "height": H}
