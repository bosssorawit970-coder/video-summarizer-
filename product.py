"""
🛒 โหมดสินค้า (Shopee affiliate / ป้ายยา)
ข้อมูลสินค้า (+ ภาพหน้าจอหน้าร้านให้ AI อ่าน) + รูป/วิดีโอที่ถ่ายเอง → บทป้ายยา ฮุก-ปัญหา-จุดเด่น-ราคา-ชวนกดตะกร้า
หลักการ: เขียนจากข้อมูลจริงเท่านั้น ไม่แต่งรีวิว/ประสบการณ์ใช้จริง ไม่อ้างสรรพคุณเกินจริง และแคปชันบอกว่าเป็นลิงก์ affiliate
"""
from __future__ import annotations

import base64
import io
import re
import shutil
from pathlib import Path

import graphics as G
import imagegen
import pipeline as P
import story as ST

CTAS = {
    "cart": "กดตะกร้าเหลืองได้เลย",
    "profile": "ลิงก์อยู่ในโปรไฟล์",
    "comment": "ลิงก์อยู่ในคอมเมนต์",
    "desc": "ลิงก์อยู่ใต้คลิป",
}

PRODUCT_PROMPT = """คุณเป็นครีเอเตอร์คลิปป้ายยาสินค้าบน TikTok/Reels/Shorts ที่คนไทยชอบดู เขียนบทคลิปแนวตั้งภาษาไทยขายสินค้านี้

ข้อมูลสินค้า (ใช้เฉพาะข้อมูลนี้เท่านั้น):
ชื่อสินค้า: {name}
ราคาขาย: {price}
ราคาเต็ม/ก่อนลด: {full}
จุดเด่น/รายละเอียดจากผู้ใช้:
{points}
{shots_note}

โครงบท {n} ฉาก รวมยาวราว {target} วินาที:
1. ฮุก 3 วินาทีแรก — คำถามหรือปัญหาที่คนดูเจอจริง หรือผลลัพธ์ที่อยากได้ (ห้ามขึ้นต้นด้วย "สวัสดี")
2. ปัญหา/สถานการณ์ที่สินค้านี้ช่วยได้
3. จุดเด่นของสินค้า ฉากละ 1 ข้อ (เอาเฉพาะที่มีในข้อมูล)
4. ราคา/โปรโมชัน (ถ้ามีราคา) — พูดตัวเลขเป็นเลขอารบิก เช่น "เหลือแค่ 299 บาท"
5. ปิดท้ายชวนซื้อ: "{cta}"

กติกาสำคัญ:
- บทพากย์ทุกฉากรวมกันไม่เกิน {budget} ตัวอักษร ฉากละ 1-2 ประโยคสั้น ภาษาพูดเป็นกันเอง กระชับ มีพลัง ห้ามอีโมจิ
- ห้ามแต่งประสบการณ์ใช้จริง ("ใช้มา 3 เดือน", "ลองแล้วดีมาก") ห้ามแต่งรีวิว/ยอดขาย/คะแนน/ตัวเลขที่ไม่มีในข้อมูล
- ห้ามอ้างสรรพคุณเกินจริง รักษาโรค หรือรับประกันผล ห้ามใช้ "ดีที่สุด" "อันดับ 1" ถ้าข้อมูลไม่ได้บอก
- ถ้าเป็นอาหารเสริม ยา สมุนไพร หรือเครื่องสำอาง: ห้ามอ้างผลต่อร่างกาย สุขภาพ ความงาม น้ำหนัก หรือสมรรถภาพ
  (เช่น "ดูแลร่างกาย" "ผิวขาวใส" "เพิ่มพลัง") พูดได้เฉพาะข้อมูลบนฉลาก: ชื่อ ส่วนประกอบ ปริมาณ จำนวน วิธีใช้ ราคา โปรโมชัน
  ฮุกให้ใช้ความคุ้มค่า/โปร/ความสะดวกแทน (โฆษณาสรรพคุณผลิตภัณฑ์สุขภาพในไทยต้องขออนุญาต อย.)
- headline: ข้อความตัวใหญ่บนจอทุกฉาก 2-5 คำ สั้นและโดน เว้นวรรคระหว่างคำ เช่น "ลด 50%" "กันน้ำ ได้จริง" "ร้อน จนทนไม่ไหว"
- image: คำบรรยายภาพประกอบภาษาอังกฤษ (ใช้เมื่อไม่มีรูปสินค้าจริง)
- search: คำค้นภาพ/วิดีโอฟรีภาษาอังกฤษ 2-4 คำ ที่เข้ากับฉาก (เช่น "woman applying skincare")
{graphic_rules}
  (ฉากราคาควรใช้ stat เช่น {{"type":"stat","value":"299","unit":"บาท","label":"ราคาโปร"}} หรือ compare ราคาเต็ม vs ราคาโปร)

{box_rule}
ตอบเป็น JSON อย่างเดียว:
{{"title": "ชื่อคลิปดึงดูด", "summary": "สรุป 1 ประโยค",
 "scenes": [{{"narration": "...", "headline": "...", "image": "...", "search": "...", "graphic": null}}]{box_json}}}"""

BOX_RULE = """- product_photo: หาตำแหน่ง "รูปสินค้าหลัก" ในภาพหน้าจอที่แนบมา (รูปตัวสินค้าใหญ่ที่สุด ไม่รวมแถบเมนู ปุ่ม ราคา หรือข้อความ)
  ตอบเป็น {"shot": ลำดับภาพที่ 1-4, "box_2d": [ymin, xmin, ymax, xmax]} พิกัด 0-1000 · ถ้าไม่มีรูปสินค้าชัดๆ ให้เป็น null"""


def _shot_parts(shots: list[Path]) -> list[dict]:
    from PIL import Image
    parts = []
    for f in shots[:4]:
        try:
            im = Image.open(f).convert("RGB")
            im.thumbnail((1024, 1024))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=80)
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}})
        except Exception as e:
            print("อ่านภาพหน้าจอสินค้าไม่ได้:", e)
    return parts


def _money(v: str) -> str:
    v = re.sub(r"[^\d.,]", "", str(v or ""))
    return v.strip(".,")


def make_product_plan(info: dict, provider: str, target: float, shots: list[Path] | None = None,
                      graphics: bool = True) -> dict:
    ST.GRAPHICS_ON = graphics
    name = P.clean_text(info.get("name", ""))[:120]
    price, full = _money(info.get("price")), _money(info.get("full"))
    points = str(info.get("points") or "").strip()[:3000]
    cta = CTAS.get(info.get("cta"), CTAS["cart"])
    if not name and not points and not shots:
        raise RuntimeError("ใส่ชื่อสินค้า หรือรายละเอียด/ภาพหน้าจอสินค้าอย่างน้อย 1 อย่าง")
    n = max(4, min(10, round(target / 6)))
    budget = ST.speech_budget(target)
    plan, ai_error = None, ""
    if provider != "none":
        parts = _shot_parts(shots or []) if provider == "gemini" else []
        prompt = PRODUCT_PROMPT.format(
            name=name or "(ดูจากภาพหน้าจอ)", price=f"{price} บาท" if price else "(ไม่ระบุ)",
            full=f"{full} บาท" if full else "(ไม่ระบุ)", points=points or "(ไม่ระบุ)",
            shots_note="ข้อมูลเพิ่มเติม: อ่านชื่อ ราคา และจุดเด่นจากภาพหน้าจอหน้าร้านที่แนบมาด้วย (เชื่อตัวเลขที่ผู้ใช้พิมพ์มากกว่า)"
            if parts else "", n=n, target=int(target), cta=cta, budget=budget, graphic_rules=ST._graphic_rules(),
            box_rule=BOX_RULE if parts else "", box_json=', "product_photo": null' if parts else "")
        facts = " ".join([name, price, full, points])
        plan, err = _ask_plan(prompt, parts, provider, facts, budget, name)
        if plan is None and parts and (name or points):  # ส่งรูปแล้วพัง → ลองแบบข้อความล้วน
            plan, err2 = _ask_plan(prompt.replace(BOX_RULE, ""), [], provider, facts, budget, name)
            err = err2 or err
        if plan is None and err:
            if not points and not name:
                raise RuntimeError(f"AI อ่านภาพหน้าจอสินค้าไม่สำเร็จ ({err}) — พิมพ์ชื่อ/จุดเด่นสินค้าเพิ่ม แล้วลองใหม่")
            ai_error = err
    if plan is None:
        plan = _template_plan(name, price, full, points, cta)
        if provider != "none":
            plan["note"] = (f"AI เขียนบทไม่สำเร็จ ({ai_error or 'ไม่ทราบสาเหตุ'}) จึงใช้บทพื้นฐานแทน — "
                            "กด 'เริ่มคลิปใหม่' ลองอีกครั้ง หรือแก้บทเองในหน้านี้")
    plan["product"] = {"name": name, "price": price, "full": full, "cta": info.get("cta") or "cart"}
    ST.finish_graphics(plan["scenes"])
    for s in plan["scenes"]:  # ฉากราคา: ถ้า AI ไม่ได้ใส่กราฟิก ใส่ให้ (ตัวเลขจากข้อมูลจริง)
        if price and price in s["narration"].replace(",", "") and not s.get("graphic") and graphics:
            s["graphic"] = ({"type": "compare", "unit": "บาท", "items": [
                {"label": "ราคาปกติ", "value": float(full.replace(",", ""))},
                {"label": "ราคาโปร", "value": float(price.replace(",", ""))}]}
                if full and full != price else {"type": "stat", "value": price, "unit": "บาท", "label": "ราคาโปร"})
            break
    return plan


def _ask_plan(prompt: str, parts: list, provider: str, facts: str, budget: int, name: str):
    """เรียก AI 1 ครั้ง คืน (plan หรือ None, ข้อความผิดพลาด)"""
    try:
        raw = P._ask_gemini(prompt, parts) if parts else P.ask_ai(provider, prompt)
        data = P._parse_json(raw)
        scenes = []
        for s in data.get("scenes") or []:
            narr = P.clean_text(str(s.get("narration") or ""))
            if not narr:
                continue
            g = G.clean(s.get("graphic"), narr)
            if g and g["type"] in ("stat", "compare") and not parts:
                # ตัวเลขในกราฟิกต้องมาจากข้อมูลสินค้าจริงด้วย (ไม่ใช่แค่ในบท)
                nums = G._digits(facts)
                vals = [g.get("value", "")] if g["type"] == "stat" else [f"{i['value']:g}" for i in g["items"]]
                if any(re.sub(r"[,\s]", "", str(v)) not in nums for v in vals):
                    g = None
            scenes.append({"narration": narr, "headline": P.clean_text(str(s.get("headline") or ""))[:30],
                           "image": str(s.get("image") or "").strip()[:300], "img": "",
                           "search": str(s.get("search") or "").strip()[:60], "graphic": g})
        if not scenes:
            return None, "AI ไม่ได้ส่งบทกลับมา"
        ST.fit_length(scenes, budget)
        plan = {"title": P.clean_text(str(data.get("title") or name))[:80],
                "summary": str(data.get("summary") or ""), "scenes": scenes}
        box = data.get("product_photo")
        if isinstance(box, dict) and isinstance(box.get("box_2d"), list) and len(box["box_2d"]) == 4:
            plan["product_box"] = {"shot": int(box.get("shot") or 1), "box": [float(x) for x in box["box_2d"]]}
        return plan, ""
    except Exception as e:
        print("AI เขียนบทป้ายยาไม่สำเร็จ:", e)
        return None, P.error_text(e)[:150]


def _template_plan(name: str, price: str, full: str, points: str, cta: str) -> dict:
    """ไม่มี AI: บทป้ายยาแบบพื้นฐานจากข้อมูลที่พิมพ์มา"""
    feats = [P.clean_text(x) for x in re.split(r"[\n•\-–,]+", points) if len(P.clean_text(x)) >= 4][:3]
    sc = [{"narration": f"ใครกำลังหา{name or 'ของดีราคาโดน'}อยู่ ดูคลิปนี้ก่อน", "headline": "ของมันต้องมี"}]
    sc += [{"narration": f"จุดเด่นคือ {f}", "headline": ""} for f in feats]
    if price:
        sc.append({"narration": f"ตอนนี้ราคาแค่ {price} บาท" + (f" จากปกติ {full} บาท" if full and full != price else ""),
                   "headline": "ราคาโปร"})
    sc.append({"narration": f"สนใจ{cta}", "headline": "🛒"})
    for s in sc:
        s.update({"image": "", "img": "", "search": "", "graphic": None})
        s["headline"] = s["headline"].replace("🛒", "กดเลย")
    return {"title": name or "ของดีบอกต่อ", "summary": "", "scenes": sc}


def add_media(plan: dict, media: list[Path], scene_dir: Path, progress=None) -> int:
    """รูป/วิดีโอสินค้าที่ถ่ายเอง → ใส่ทุกฉาก (วนใช้ซ้ำถ้าฉากเยอะกว่าไฟล์) คืนจำนวนไฟล์ที่ใช้ได้"""
    from PIL import Image, ImageOps
    scene_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for k, f in enumerate(media):
        if progress:
            progress(f"เตรียมรูป/วิดีโอสินค้า {k + 1}/{len(media)}")
        is_vid = f.suffix.lower() in (".mp4", ".mov", ".webm", ".m4v", ".3gp", ".mkv")
        out = scene_dir / f"product_{k + 1:02}{'.mp4' if is_vid else '.png'}"
        try:
            if is_vid:
                imagegen.normalize_video(f, out)
            else:
                im = ImageOps.exif_transpose(Image.open(f)).convert("RGB")
                im.thumbnail((1600, 1600))
                im.save(out)
            names.append(out.name)
        except Exception as e:
            print("ใช้ไฟล์สินค้าไม่ได้:", f.name, e)
    if not names:
        return 0
    for i, s in enumerate(plan["scenes"]):
        mine = names[i % len(names)]
        s["img"] = mine
        s["options"] = [mine] + [x for x in names if x != mine]
        s["generic"] = False
    return len(names)


STUDIO = [  # (ฉากหลังบน, ฉากหลังล่าง, แท่นวาง) — สีพาสเทลแบบถ่ายสินค้าในสตูดิโอ
    ("FDE2E4", "FAD2E1", "FFFFFF"), ("E2ECE9", "BEE1E6", "F8F9FA"), ("FFF1C1", "FFD6A5", "FFFDF7"),
    ("E4DFFD", "CDB4DB", "FFFFFF"), ("D7F9F1", "A0E7E5", "FFFFFF"), ("2B2D42", "4A4E69", "8D99AE"),
]
STUDIO_TOP = 0.665  # ระดับผิวบนของแท่นวาง (สัดส่วนความสูงจอ) — ใช้วางสินค้าตอนเรนเดอร์


def shine_band(out: Path) -> None:
    """แถบแสงเฉียงสีขาวโปร่ง (วิ่งผ่านตัวสินค้าแบบโฆษณา)"""
    from PIL import Image
    w, h = 220, 900
    band = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    alpha = Image.new("L", (w, h))
    alpha.putdata([int(150 * max(0.0, 1 - abs(x - w / 2) / (w / 2)) ** 1.6) for y in range(h) for x in range(w)])
    band.putalpha(alpha)
    band.rotate(-22, expand=True, resample=Image.BICUBIC).save(out)


def studio_background(out: Path, W: int, H: int, k: int = 0) -> None:
    """ฉากถ่ายสินค้าแบบสตูดิโอ (วาดเองทั้งหมด): ฉากหลังไล่สี + สปอตไลต์ + พื้น + แท่นทรงกระบอก + เงาตรงจุดวาง"""
    from PIL import Image, ImageDraw, ImageFilter
    top, bot, pod = STUDIO[k % len(STUDIO)]
    rgb = lambda h: tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # noqa: E731
    c1, c2, cp = rgb(top), rgb(bot), rgb(pod)
    w, h = int(W * 1.15), int(H * 1.15)  # เผื่อขอบให้กล้องขยับ
    im = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * t) for a, b in zip(c1, c2)))
    floor = int(h * 0.74)  # พื้นเข้มขึ้นนิด
    for y in range(floor, h):
        t = (y - floor) / max(1, h - floor)
        d.line([(0, y), (w, y)], fill=tuple(int(c * (0.93 - 0.08 * t)) for c in c2))
    spot = Image.new("L", (w, h), 0)  # สปอตไลต์จากด้านบน
    ImageDraw.Draw(spot).ellipse([w * 0.12, -h * 0.15, w * 0.88, h * 0.75], fill=120)
    spot = spot.filter(ImageFilter.GaussianBlur(w * 0.12))
    im = Image.composite(Image.new("RGB", (w, h), (255, 255, 255)), im, spot)
    d = ImageDraw.Draw(im)
    cx, rx = w / 2, w * 0.33
    ty = h * STUDIO_TOP + (h - H) / 2 * 0  # ผิวบนแท่น
    ty = (H * STUDIO_TOP) + (h - H) / 2
    ry, body = rx * 0.17, h * 0.13
    side = Image.new("RGB", (int(rx * 2), int(body)))
    sd = ImageDraw.Draw(side)
    for x in range(side.width):  # ด้านข้างแท่น: ไล่แสงซ้าย→ขวา ให้ดูเป็นทรงกระบอก
        t = abs(x / side.width - 0.38) * 1.6
        sd.line([(x, 0), (x, side.height)], fill=tuple(int(c * (1 - 0.22 * min(1, t))) for c in cp))
    mask = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(mask)
    md.rectangle([cx - rx, ty, cx + rx, ty + body], fill=255)
    md.ellipse([cx - rx, ty + body - ry, cx + rx, ty + body + ry], fill=255)
    full = Image.new("RGB", (w, h))
    full.paste(side.resize((int(rx * 2), int(body + ry * 2))), (int(cx - rx), int(ty)))
    shadow = Image.new("L", (w, h), 0)  # เงาแท่นบนพื้น
    ImageDraw.Draw(shadow).ellipse([cx - rx * 1.15, ty + body - ry * 0.4, cx + rx * 1.15, ty + body + ry * 1.8], fill=90)
    im = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), im, shadow.filter(ImageFilter.GaussianBlur(30)))
    im = Image.composite(full, im, mask)
    d = ImageDraw.Draw(im)
    d.ellipse([cx - rx, ty - ry, cx + rx, ty + ry], fill=tuple(min(255, c + 12) for c in cp))  # ผิวบน
    d.ellipse([cx - rx, ty - ry, cx + rx, ty + ry], outline=tuple(int(c * 0.86) for c in cp), width=3)
    contact = Image.new("L", (w, h), 0)  # เงาตรงจุดที่สินค้าวาง
    ImageDraw.Draw(contact).ellipse([cx - rx * 0.62, ty - ry * 0.45, cx + rx * 0.62, ty + ry * 0.45], fill=85)
    im = Image.composite(Image.new("RGB", (w, h), (0, 0, 0)), im, contact.filter(ImageFilter.GaussianBlur(16)))
    im.save(out)


def add_animation(plan: dict, scene_dir: Path, layout: str = "vertical_crop", studio: bool = False) -> int:
    """ไม่มีสินค้าจริง → ทุกฉากเป็นแอนิเมชันกราฟิก: พื้นหลังสีสด + ข้อความใหญ่เด้งกลางจอ + รูปทรงลอย
    studio=True (มีรูปสินค้าที่ตัดพื้นหลังแล้ว): ฉากสตูดิโอ สินค้าวางบนแท่น มีแสงวิ้งวิ่งผ่าน + กล้องค่อยๆ ซูม"""
    W, H = ST.size_for(layout)
    scene_dir.mkdir(parents=True, exist_ok=True)
    studio = studio and (scene_dir / "prodcard.png").exists()
    for i, s in enumerate(plan["scenes"]):
        name = f"anim_{'studio_' if studio else ''}{i + 1:02}.png"
        if studio:
            studio_background(scene_dir / name, W, H, i)
            s["studio"] = True
        else:
            G.anim_background(scene_dir / name, W, H, i)
        if not (s.get("headline") or "").strip():  # แอนิเมชันต้องมีข้อความกลางจอ
            s["headline"] = ST.thai_keywords(s.get("narration", ""), 2)[:24]
        s["img"] = name
        s["options"] = [name] + [o for o in s.get("options") or [] if o != name]
        s["generic"] = False
        if (scene_dir / "prodcard.png").exists():
            s["product_img"] = "prodcard.png"
    return len(plan["scenes"])


def move_uploads(src_dir: Path, dest: Path) -> tuple[list[Path], list[Path], Path | None]:
    """ย้ายไฟล์ที่อัปโหลดมา (media_*, shot_*, pimg_*) เข้าโฟลเดอร์งาน คืน (สื่อ, ภาพหน้าจอ, รูปสินค้า)"""
    media, shots, pimg = [], [], None
    if not src_dir or not src_dir.exists():
        return media, shots, pimg
    dest.mkdir(parents=True, exist_ok=True)
    for f in sorted(src_dir.iterdir()):
        target = dest / f.name
        shutil.move(str(f), target)
        if f.name.startswith("shot_"):
            shots.append(target)
        elif f.name.startswith("pimg_"):
            pimg = target
        else:
            media.append(target)
    shutil.rmtree(src_dir, ignore_errors=True)
    return media, shots, pimg


def _load_crop(src: Path, box: list[float] | None):
    from PIL import Image, ImageOps
    try:
        im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    except Exception as e:
        print("เปิดรูปสินค้าไม่ได้:", e)
        return None
    if box:
        y0, x0, y1, x1 = [max(0.0, min(1000.0, v)) / 1000 for v in box]
        if x1 - x0 < 0.08 or y1 - y0 < 0.05:
            return None
        W, H = im.size
        im = im.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)))
    im.thumbnail((1000, 1000))
    return im


_rembg = None


def cutout(im):
    """ตัดพื้นหลังรูปสินค้า (rembg/U²-Net บน CPU — ติดตั้ง+โหลดโมเดลครั้งแรก ~1 นาที) คืน RGBA หรือ None"""
    global _rembg
    import subprocess
    import sys
    try:
        if _rembg is None:
            try:
                import rembg  # noqa: F401
            except ImportError:
                print("กำลังติดตั้งตัวตัดพื้นหลัง (rembg)…")
                subprocess.run([sys.executable, "-m", "pip", "install", "-q", "rembg", "onnxruntime"],
                               check=True, capture_output=True)
            from rembg import new_session
            _rembg = new_session("isnet-general-use")
        from rembg import remove
        out = remove(im, session=_rembg, post_process_mask=True)
        bbox = out.getchannel("A").point(lambda a: 255 if a > 40 else 0).getbbox()
        if not bbox:
            return None
        out = out.crop(bbox)
        # ตัดได้น้อยเกินไป (เหลือแต่เศษ) = ไม่น่าเชื่อถือ
        if out.width * out.height < im.width * im.height * 0.06:
            return None
        return out
    except Exception as e:
        print("ตัดพื้นหลังไม่ได้ (ใช้แบบการ์ดแทน):", str(e)[-200:])
        return None


def _sticker(rgba, out: Path, glow: bool = True) -> None:
    """สินค้าที่ตัดพื้นหลังแล้ว → สติกเกอร์ขอบขาว + แสงฟุ้งด้านหลัง + เงาตกพื้น"""
    from PIL import Image, ImageFilter
    rgba.thumbnail((900, 900))
    stroke, pad = 16, 90
    a = rgba.getchannel("A")
    W, H = rgba.width + pad * 2, rgba.height + pad * 2
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    if glow:  # แสงฟุ้งสีขาวด้านหลัง
        g = Image.new("L", (W, H), 0)
        g.paste(a, (pad, pad))
        g = g.filter(ImageFilter.MaxFilter(31)).filter(ImageFilter.GaussianBlur(40)).point(lambda v: int(v * 0.75))
        canvas.alpha_composite(Image.merge("RGBA", (*[Image.new("L", (W, H), 255)] * 3, g)))
    sh = Image.new("L", (W, H), 0)  # เงาตกพื้น
    sh.paste(a, (pad + 10, pad + 26))
    sh = sh.filter(ImageFilter.GaussianBlur(22)).point(lambda v: int(v * 0.45))
    canvas.alpha_composite(Image.merge("RGBA", (*[Image.new("L", (W, H), 0)] * 3, sh)))
    st = Image.new("L", (W, H), 0)  # ขอบขาวแบบสติกเกอร์
    st.paste(a, (pad, pad))
    st = st.filter(ImageFilter.MaxFilter(stroke * 2 + 1)).point(lambda v: 255 if v > 60 else 0)
    canvas.alpha_composite(Image.merge("RGBA", (*[Image.new("L", (W, H), 255)] * 3, st)))
    canvas.alpha_composite(rgba, (pad, pad))
    canvas.crop(canvas.getbbox()).save(out)


def _card(im, out: Path) -> None:
    """แบบเดิม: การ์ดมุมมน ขอบขาว เงานุ่ม"""
    from PIL import Image, ImageDraw, ImageFilter
    im.thumbnail((900, 900))
    w, h = im.size
    r, border, pad = int(min(w, h) * 0.07), 14, 40
    card = Image.new("RGBA", (w + border * 2, h + border * 2), (0, 0, 0, 0))
    mask = Image.new("L", card.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, card.width - 1, card.height - 1], r + border, fill=255)
    card.paste(Image.new("RGBA", card.size, (255, 255, 255, 255)), (0, 0), mask)
    inner = Image.new("L", (w, h), 0)
    ImageDraw.Draw(inner).rounded_rectangle([0, 0, w - 1, h - 1], r, fill=255)
    card.paste(im, (border, border), inner)
    shadow = Image.new("RGBA", (card.width + pad * 2, card.height + pad * 2), (0, 0, 0, 0))
    sm = Image.new("L", shadow.size, 0)
    ImageDraw.Draw(sm).rounded_rectangle([pad, pad + 14, pad + card.width, pad + card.height + 14], r + border, fill=110)
    shadow.putalpha(sm.filter(ImageFilter.GaussianBlur(18)))
    shadow.alpha_composite(card, (pad, pad))
    shadow.save(out)


RESTAGE_PROMPT = """Product photography edit. Take the product shown in this image and place it in a brand-new,
eye-catching studio scene for a vertical social-media ad: {scene}.
STRICT RULES: keep the product itself exactly identical — same shape, colors, packaging, logo and every printed word/number.
Do not add or change any text on the product. Remove all original background, banners, badges, stickers and text that are
not printed on the product itself. Do not add any new text, prices or logos. Photorealistic, sharp, soft natural shadow."""
SCENES = ["on a clean pastel podium with soft gradient backdrop and gentle rim light",
          "on a marble tabletop with soft morning window light and a few out-of-focus leaves",
          "floating above a glossy surface with colorful bokeh lights behind"]


def restage(im, out: Path, k: int = 0) -> bool:
    """ให้ Gemini (รุ่นทำภาพ) จัดฉากถ่ายสินค้าใหม่ — ทดลอง: ใช้ได้เฉพาะคีย์ที่มีรุ่นทำภาพ/โควตาเหลือ"""
    import json as _json
    import os
    import urllib.request
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    models = P.gemini_models("image")
    if not key or not models:
        return False
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    body = _json.dumps({"contents": [{"role": "user", "parts": [
        {"text": RESTAGE_PROMPT.format(scene=SCENES[k % len(SCENES)])},
        {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}]}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}}).encode()
    for model in models[:3]:
        try:
            data = P._gemini_post(model, body, key)
        except Exception as e:
            print(f"Gemini จัดฉากสินค้าไม่ได้ ({model}):", getattr(e, "_msg_text", "") or e)
            continue
        for part in ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                from PIL import Image
                Image.open(io.BytesIO(base64.b64decode(inline["data"]))).convert("RGB").save(out)
                return True
    return False


def product_card(src: Path, out: Path, box: list[float] | None = None, style: str = "sticker") -> str:
    """รูปสินค้า → ภาพลอยในฉากแอนิเมชัน (PNG โปร่งใส) คืนแบบที่ทำได้จริง ("" = ไม่สำเร็จ)
    style: "sticker" ตัดพื้นหลังเป็นสติกเกอร์ · "restage" ให้ AI จัดฉากถ่ายใหม่ · "card" รูปเดิมในกรอบ
    box = [ymin, xmin, ymax, xmax] 0-1000 (กรอบรูปสินค้าในภาพหน้าจอที่ AI หาให้)"""
    im = _load_crop(src, box)
    if im is None:
        return ""
    if style == "restage":
        tmp = out.with_name("restaged.jpg")
        if restage(im, tmp):
            from PIL import Image
            _card(Image.open(tmp).convert("RGB"), out)
            return "restage"
        style = "sticker"  # ทำภาพไม่ได้ → ตัดพื้นหลังแทน
    if style == "sticker":
        cut = cutout(im)
        if cut is not None:
            _sticker(cut, out)
            return "sticker"
    _card(im, out)
    return "card"
