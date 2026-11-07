"""
ภาพประกอบฉาก:
  • AI วาดภาพ — SDXL-Lightning (1024px คมและตรงคำสั่งกว่า) บนการ์ดจอ Colab
    ถ้าโหลดไม่ได้ ถอยไป SDXL-Turbo → SD-Turbo → ภาพพื้นหลังไล่สี ตามลำดับ
  • ภาพถ่ายจริงจาก Pexels (ฟรี ต้องมีคีย์ PEXELS_API_KEY)
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# (ชื่อไทย, คำนำหน้าคำสั่งวาด) — ใส่สไตล์ไว้หน้าคำสั่ง เพราะโมเดลอ่านได้แค่ ~77 คำแรก
STYLES = {
    "cinematic": ("ภาพสมจริงแบบหนัง", "cinematic film still, realistic photo"),
    "anime": ("การ์ตูนอนิเมะ", "anime illustration, vibrant colors"),
    "digital": ("ภาพวาดดิจิทัล", "digital painting, concept art"),
    "3d": ("การ์ตูน 3 มิติ", "3d animated movie still, cute, soft lighting"),
    "flat": ("ภาพกราฟิกแบน", "flat vector illustration, minimal, bold colors"),
}

MODELS = ["lightning", "stabilityai/sdxl-turbo", "stabilityai/sd-turbo"]
if os.environ.get("IMAGE_MODEL"):
    MODELS.insert(0, os.environ["IMAGE_MODEL"])

_pipe = None
_pipe_err: str | None = None
_model = ""
_lock = threading.Lock()


def _load_lightning(torch):
    """SDXL + Lightning 4 ขั้น (ByteDance) — คุณภาพระดับ SDXL ที่ 1024px แต่วาดเร็ว"""
    from diffusers import EulerDiscreteScheduler, StableDiffusionXLPipeline, UNet2DConditionModel
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file
    base = "stabilityai/stable-diffusion-xl-base-1.0"
    unet = UNet2DConditionModel.from_config(base, subfolder="unet").to("cuda", torch.float16)
    unet.load_state_dict(load_file(hf_hub_download("ByteDance/SDXL-Lightning",
                                                   "sdxl_lightning_4step_unet.safetensors"), device="cuda"))
    pipe = StableDiffusionXLPipeline.from_pretrained(base, unet=unet, torch_dtype=torch.float16,
                                                     variant="fp16").to("cuda")
    pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config, timestep_spacing="trailing")
    return pipe


def _load(progress=None):
    global _pipe, _pipe_err, _model
    if _pipe is not None or _pipe_err is not None:
        return _pipe
    try:
        import torch
        from diffusers import AutoPipelineForText2Image
    except Exception as e:
        _pipe_err = f"{type(e).__name__}: {e}"
        print("วาดภาพด้วย AI ไม่ได้ จะใช้ภาพพื้นหลังไล่สีแทน:", _pipe_err)
        return None
    cuda = torch.cuda.is_available()
    if not cuda and not os.environ.get("IMAGEGEN_CPU"):
        # ไม่มีการ์ดจอ: วาดบน CPU ช้ามาก (หลายนาที/ภาพ) และกิน RAM ~5 GB จน Colab ค้างได้ → ไม่วาด
        _pipe_err = "ไม่มีการ์ดจอ"
        print("ไม่มีการ์ดจอ — ข้ามการวาดภาพด้วย AI (ใช้ภาพถ่าย/รูปของคุณ/ภาพพื้นหลังแทน)")
        return None
    models = MODELS if cuda else MODELS[-1:]
    for m in models:
        try:
            if progress:
                progress(f"กำลังโหลดโมเดลวาดภาพ {m.split('/')[-1]} (ครั้งแรกดาวน์โหลดหลาย GB รอสักครู่)")
            if m == "lightning":
                pipe = _load_lightning(torch)
            else:
                kw = {"torch_dtype": torch.float16, "variant": "fp16"} if cuda else {}
                pipe = AutoPipelineForText2Image.from_pretrained(m, **kw).to("cuda" if cuda else "cpu")
            pipe.set_progress_bar_config(disable=True)
            _pipe, _model = pipe, m
            print("ใช้โมเดลวาดภาพ:", m)
            return _pipe
        except Exception as e:
            print(f"โหลดโมเดล {m} ไม่สำเร็จ:", e)
            _pipe_err = f"{type(e).__name__}: {e}"
            try:
                import gc
                gc.collect()
                torch.cuda.empty_cache()
            except Exception:
                pass
    print("วาดภาพด้วย AI ไม่ได้ จะใช้ภาพพื้นหลังไล่สีแทน:", _pipe_err)
    return None


def available() -> bool:
    """วาดภาพด้วย AI ได้ไหม (ต้องมีไลบรารี + การ์ดจอ)"""
    try:
        import diffusers  # noqa: F401
        import torch
        return bool(torch.cuda.is_available() or os.environ.get("IMAGEGEN_CPU"))
    except Exception:
        return False


def generate(prompt: str, out: Path, width: int = 1024, height: int = 1024, style: str = "cinematic",
             seed: int | None = None, progress=None) -> bool:
    """วาดภาพสี่เหลี่ยมจัตุรัส 1 ภาพ คืน True ถ้าวาดด้วย AI ได้ (False = ใช้ภาพไล่สีแทน)"""
    prefix = STYLES.get(style, STYLES["cinematic"])[1]
    full = f"{prefix}, {prompt.strip()}, highly detailed, sharp focus"
    if seed is None:
        seed = int(hashlib.md5(full.encode()).hexdigest()[:8], 16)
    with _lock:  # การ์ดจอใช้ทีละงาน
        pipe = _load(progress)
        if pipe is not None:
            try:
                import torch
                g = torch.Generator(device=pipe.device).manual_seed(seed)
                if _model == "lightning":
                    size, steps = 1024, 4
                elif "sdxl" in _model:
                    size, steps = 512, 4
                else:
                    size, steps = 512, 3
                img = pipe(prompt=full, num_inference_steps=steps, guidance_scale=0.0,
                           width=size, height=size, generator=g).images[0]
                img.save(out)
                return True
            except Exception as e:
                print("วาดภาพไม่สำเร็จ ใช้ภาพไล่สีแทน:", e)
    placeholder(out, width, height, seed)
    return False


# ───────────────────────── ภาพถ่ายจริง (Pexels) ─────────────────────────

def pexels_key() -> str:
    return (os.environ.get("PEXELS_API_KEY") or "").strip()


def _pexels(query: str, n: int, orientation: str | None) -> list[dict]:
    params = {"query": query, "per_page": n, "size": "medium"}
    if orientation:
        params["orientation"] = orientation
    req = urllib.request.Request("https://api.pexels.com/v1/search?" + urllib.parse.urlencode(params),
                                 headers={"Authorization": pexels_key(), "User-Agent": "Mozilla/5.0 sarupclip"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read()).get("photos", [])


def search_photos(query: str, outs: list[Path]) -> list[Path]:
    """ค้นภาพถ่ายจาก Pexels แล้วบันทึกเป็น PNG ตามรายชื่อไฟล์ที่ให้ คืนไฟล์ที่ได้จริง"""
    if not pexels_key():
        raise RuntimeError("ยังไม่ได้ใส่คีย์ Pexels (ใส่ในช่อง PEXELS_API_KEY ในหน้า Colab)")
    from PIL import Image
    query = " ".join(query.split()[:6]) or "nature"
    photos = []
    for q, ori in ((query, "square"), (query, None), (" ".join(query.split()[:2]), None)):
        try:
            photos = _pexels(q, len(outs), ori)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise RuntimeError("คีย์ Pexels ไม่ถูกต้อง") from e
            raise
        if photos:
            break
    got = []
    for ph, out in zip(photos, outs):
        url = ph["src"].get("large2x") or ph["src"].get("large") or ph["src"]["original"]
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 sarupclip"})
        tmp = out.with_suffix(".dl")
        with urllib.request.urlopen(req, timeout=30) as r:
            tmp.write_bytes(r.read())
        Image.open(tmp).convert("RGB").save(out)
        tmp.unlink(missing_ok=True)
        got.append(out)
    return got


def placeholder(out: Path, width: int, height: int, seed: int = 0) -> None:
    """ภาพพื้นหลังไล่สีสวยๆ (ใช้เมื่อวาดด้วย AI ไม่ได้)"""
    from PIL import Image, ImageDraw, ImageFilter
    import colorsys
    import random
    rnd = random.Random(seed)
    w, h = max(64, width // 4), max(64, height // 4)
    hue = rnd.random()
    c1 = tuple(int(x * 255) for x in colorsys.hsv_to_rgb(hue, 0.65, 0.55))
    c2 = tuple(int(x * 255) for x in colorsys.hsv_to_rgb((hue + 0.12) % 1, 0.75, 0.25))
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=tuple(int(c1[i] * (1 - t) + c2[i] * t) for i in range(3)))
    for _ in range(7):  # วงแสงฟุ้งๆ
        r = rnd.randint(w // 8, w // 3)
        x, y = rnd.randint(0, w), rnd.randint(0, h)
        col = tuple(int(v * 255) for v in colorsys.hsv_to_rgb((hue + rnd.random() * 0.3) % 1, 0.4, 0.9))
        layer = Image.new("RGB", (w, h), (0, 0, 0))
        ImageDraw.Draw(layer).ellipse((x - r, y - r, x + r, y + r), fill=col)
        img = Image.blend(img, Image.composite(layer, img, layer.convert("L")), 0.25)
    img = img.filter(ImageFilter.GaussianBlur(max(2, w // 40))).resize((width, height), Image.LANCZOS)
    img.save(out)
