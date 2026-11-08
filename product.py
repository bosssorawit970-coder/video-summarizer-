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


def add_animation(plan: dict, scene_dir: Path, layout: str = "vertical_crop") -> int:
    """ไม่มีสินค้าจริง → ทุกฉากเป็นแอนิเมชันกราฟิก: พื้นหลังสีสด + ข้อความใหญ่เด้งกลางจอ + รูปทรงลอย"""
    W, H = ST.size_for(layout)
    scene_dir.mkdir(parents=True, exist_ok=True)
    for i, s in enumerate(plan["scenes"]):
        name = f"anim_{i + 1:02}.png"
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


def product_card(src: Path, out: Path, box: list[float] | None = None) -> bool:
    """รูปสินค้า → การ์ดมุมมน ขอบขาว เงานุ่ม (PNG โปร่งใส) ไว้ลอยในฉากแอนิเมชัน
    box = [ymin, xmin, ymax, xmax] 0-1000 (กรอบรูปสินค้าในภาพหน้าจอที่ AI หาให้)"""
    from PIL import Image, ImageDraw, ImageFilter, ImageOps
    try:
        im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    except Exception as e:
        print("เปิดรูปสินค้าไม่ได้:", e)
        return False
    if box:
        y0, x0, y1, x1 = [max(0.0, min(1000.0, v)) / 1000 for v in box]
        if x1 - x0 < 0.08 or y1 - y0 < 0.05:
            return False
        W, H = im.size
        im = im.crop((int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)))
    im.thumbnail((900, 900))
    w, h = im.size
    r, border, pad = int(min(w, h) * 0.07), 14, 40
    card = Image.new("RGBA", (w + border * 2, h + border * 2), (0, 0, 0, 0))
    mask = Image.new("L", card.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, card.width - 1, card.height - 1], r + border, fill=255)
    white = Image.new("RGBA", card.size, (255, 255, 255, 255))
    card.paste(white, (0, 0), mask)
    inner = Image.new("L", (w, h), 0)
    ImageDraw.Draw(inner).rounded_rectangle([0, 0, w - 1, h - 1], r, fill=255)
    card.paste(im, (border, border), inner)
    shadow = Image.new("RGBA", (card.width + pad * 2, card.height + pad * 2), (0, 0, 0, 0))
    sm = Image.new("L", shadow.size, 0)
    ImageDraw.Draw(sm).rounded_rectangle([pad, pad + 14, pad + card.width, pad + card.height + 14], r + border, fill=110)
    shadow.putalpha(sm.filter(ImageFilter.GaussianBlur(18)))
    shadow.alpha_composite(card, (pad, pad))
    shadow.save(out)
    return True
