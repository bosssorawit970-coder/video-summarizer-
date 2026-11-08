"""
โหมดข้อความ → คลิป: เรียบเรียงข้อความเป็นบทคลิปสั้น แบ่งฉาก วาดภาพประกอบ
แล้วทำแอนิเมชัน (ซูม/แพน, หัวข้อเลื่อนเข้า, ซับ, ทรานซิชัน) พร้อมเสียงพากย์
"""
from __future__ import annotations

import re
from pathlib import Path

import graphics as G
import imagegen
import pipeline as P

STORY_PROMPT = """คุณเป็นครีเอเตอร์คลิปสั้น TikTok ชาวไทยมืออาชีพ เปลี่ยนข้อมูลด้านล่างให้เป็นบทคลิปสั้นแนวตั้งที่น่าดูจนจบ

ข้อกำหนด:
- ความยาวรวมประมาณ {target} วินาที แบ่งเป็น {n} ฉาก (ฉากละ 4-9 วินาที)
- สำคัญมาก: บทพากย์ทุกฉากรวมกันต้องไม่เกิน {budget} ตัวอักษร (ไม่นับช่องว่าง) เพื่อให้คลิปยาวไม่เกิน {target} วินาที
  ถ้าข้อมูลยาว ให้สรุปเฉพาะประเด็นที่น่าสนใจที่สุด ไม่ต้องเล่าทุกรายละเอียด
- ฉากแรกต้องเปิดแรง ดึงความสนใจทันที (ตั้งคำถาม/ประโยคน่าตกใจ/สัญญาว่าจะได้อะไร)
- เล่าต่อเนื่อง ภาษาพูดเป็นกันเอง กระชับ ฉากสุดท้ายสรุปและชวนกดติดตาม/คอมเมนต์
- ยึดตามข้อมูลที่ให้มา ห้ามแต่งข้อเท็จจริง ตัวเลข หรือชื่อที่ไม่มีในข้อมูล
- ถ้าข้อมูลเป็นภาษาอื่น (เช่น อังกฤษ) ให้แปลและเล่าเป็นภาษาไทยที่เป็นธรรมชาติ ไม่แข็งแบบแปลตรงตัว ชื่อคน/สถานที่/แบรนด์ให้ทับศัพท์
{extra}
- เก็บใจความสำคัญจากข้อมูลให้ครบ ไม่ตัดประเด็นทิ้ง
- บทพากย์แต่ละฉาก (narration) 1-2 ประโยค ยาวประมาณ {per_scene} ตัวอักษร ห้ามมีอีโมจิ
- headline: ข้อความสั้นบนจอ 2-6 คำ สรุปฉากนั้น (ไม่ต้องซ้ำบทพากย์) เว้นว่างได้
- image: คำบรรยายภาพประกอบเป็นภาษาอังกฤษ 10-25 คำ บรรยายสิ่งที่เห็นชัดๆ (คน สถานที่ สิ่งของ แสง มุมกล้อง)
  ห้ามใส่ชื่อคนจริง คนดัง ตัวละครหรือโลโก้ที่มีลิขสิทธิ์ — ให้บรรยายแบบทั่วไปแทน และห้ามให้มีตัวหนังสือในภาพ
- search: คำค้นภาพถ่ายในคลังภาพ ภาษาอังกฤษ 2-4 คำ (เช่น "black coffee cup", "woman jogging park")
{graphic_rules}

ตอบเป็น JSON อย่างเดียว:
{{"title": "ชื่อคลิปดึงดูด (อีโมจิได้ 1-2 ตัว)", "summary": "แคปชัน 1-2 ประโยค + แฮชแท็ก 3-5 อัน",
 "scenes": [{{"narration": "...", "headline": "...", "image": "...", "search": "...", "graphic": null}}]}}

ข้อมูล:
{text}"""

VISUAL_PROMPT = """You are a storyboard artist for short vertical videos.
Below is a Thai narration script, already split into {n} numbered scenes. Do NOT change the narration.

Step 1 — read the WHOLE script and work out: the main topic, the setting/place, the era, and the main characters.
Step 2 — for EACH scene write:
- "headline": short on-screen text in THAI, 2-6 words, summarising that scene (may be empty "")
- "image": an English image-generation prompt, 15-35 words, that shows EXACTLY what that scene's narration talks about.
  Start with the main subject, then the action, then the place, lighting and camera shot (close-up / wide shot).
  Stay consistent with the topic and setting from Step 1 — every image must clearly belong to this same story.
  Recurring characters must be described with the SAME appearance every time (age, gender, hair, clothes).
  If the scene states a fact, number or idea, show a concrete visual of it (never an unrelated generic scene).
  No text or letters in the image. No real people's names, celebrities, brands or copyrighted characters — describe them generically.
- "search": 2-4 English words to search a stock-photo site for this scene (e.g. "shark swimming deep ocean")
{graphic_rules}

Reply with JSON only:
{{"topic": "one English sentence: what the story is about", "characters": "English description of main characters, or empty",
 "title": "catchy Thai title (1-2 emoji ok)", "summary": "Thai caption 1-2 sentences + 3-5 hashtags",
 "scenes": [{{"headline": "...", "image": "...", "search": "...", "graphic": null}}]}}
"scenes" must contain exactly {n} items, in order.

Script:
{scenes}"""

SCENE_PROMPT = """Write an English image-generation prompt for ONE scene of a Thai short video.
Story topic: {topic}
Previous scene: {prev}
THIS scene's Thai narration: {narr}
Next scene: {next}

The image must show exactly what THIS scene's narration is about, matching the story topic.
15-30 words: main subject first, then action, place, lighting, camera shot. No text in the image.
No real people's names, celebrities, brands or copyrighted characters.
Reply with JSON only: {{"image": "...", "search": "2-4 English words for a stock photo", "headline": "Thai 2-6 words"}}"""

GENERIC_IMAGES = [
    "soft glowing abstract background, bokeh lights, calm atmosphere",
    "a person thinking at a desk by the window, warm morning light",
    "wide landscape at golden hour, dramatic sky",
    "close-up of hands writing in a notebook, cozy light",
    "city street at night with neon reflections",
    "a cup of coffee on a wooden table, sunlight",
]


GRAPHICS_ON = True  # ปิดได้จากหน้าเว็บ (opts["graphics"])


def _graphic_rules() -> str:
    return G.GRAPHIC_RULES if GRAPHICS_ON else '- "graphic": always null'


def finish_graphics(scenes: list[dict]) -> None:
    """ไม่ให้กราฟิกรกเกินไป (ไม่เกินครึ่งหนึ่งของฉาก ไม่ซ้ำแบบติดกัน) + ฉากไม่มี AI → เดาจากตัวเลขในบท"""
    if not GRAPHICS_ON:
        for s in scenes:
            s["graphic"] = None
        return
    for s in scenes:
        if "graphic" not in s:
            s["graphic"] = G.guess(s.get("narration", ""))
    limit, used, prev = max(1, (len(scenes) + 1) // 2), 0, None
    for s in scenes:
        g = s.get("graphic")
        if g and (used >= limit or (prev and g["type"] == prev == "keyword")):
            s["graphic"] = None
            g = None
        if g:
            used += 1
        prev = g["type"] if g else None


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。])\s+|\n+|\s{2,}", text.strip())
    out = []
    for p in parts:
        p = p.strip()
        while len(p) > 140:  # ประโยคยาวมาก → ตัดที่ช่องว่าง หรือรอยต่อคำไทยใกล้ 110 ตัวอักษร
            cut = p.rfind(" ", 50, 120)
            if cut <= 0:
                cut = _thai_boundary(p, 110)
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        if p:
            out.append(p)
    return out


def _thai_boundary(p: str, n: int) -> int:
    try:
        from pythainlp.tokenize import word_tokenize
        pos, best = 0, 0
        for w in word_tokenize(p, engine="newmm"):
            if pos + len(w) > n:
                break
            pos += len(w)
            best = pos
        if best > 40:
            return best
    except Exception:
        pass
    return P._thai_cut(p, n)


def split_script(text: str, max_len: int = 110) -> list[str]:
    """แบ่งบทเป็นฉาก โดยเก็บทุกคำไว้ครบ (ฉากละ ~1-2 ประโยค / ไม่เกิน ~110 ตัวอักษร)"""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    scenes = []
    for para in paras:
        cur = ""
        for s in _split_sentences(para):
            if cur and len(cur) + 1 + len(s) > max_len:
                scenes.append(cur)
                cur = s
            else:
                cur = f"{cur} {s}".strip()
        if cur:
            scenes.append(cur)
    # ฉากสั้นมาก (เช่น "สวัสดีครับ") รวมกับฉากถัดไป
    merged = []
    for sc in scenes:
        if merged and len(merged[-1]) < 25 and len(merged[-1]) + 1 + len(sc) <= max_len + 30:
            merged[-1] = f"{merged[-1]} {sc}"
        else:
            merged.append(sc)
    return merged[:40]


def thai_ratio(text: str) -> float:
    letters = re.findall(r"[A-Za-zก-๙]", text or "")
    return sum(1 for c in letters if "ก" <= c <= "๙") / len(letters) if letters else 1.0


def make_story_plan(text: str, provider: str, target: float, mode: str = "verbatim",
                    graphics: bool = True, extra: str = "", strict: bool = False) -> dict:
    """mode="verbatim": อ่านตามบทที่ใส่ทุกคำ (AI แค่คิดภาพ+หัวข้อ) · "rewrite": ให้ AI เรียบเรียงใหม่
    strict=True (ลิงก์โพสต์/ข่าว): AI แปลไม่สำเร็จ = แจ้งผิดพลาด ไม่เอาต้นฉบับภาษาอื่นมาพากย์ตรงๆ"""
    global GRAPHICS_ON, LAST_AI_ERROR
    GRAPHICS_ON = graphics
    LAST_AI_ERROR = ""
    text = text.strip()
    if len(text) < 10:
        raise RuntimeError("ข้อความสั้นเกินไป ใส่ข้อมูลอย่างน้อย 1-2 ประโยค")
    foreign = thai_ratio(text) < 0.3
    if foreign and provider != "none":  # บทเป็นภาษาอื่น → ต้องแปลเป็นไทยก่อนพากย์
        mode, strict = "rewrite", True
    if mode == "rewrite":
        plan = _rewrite_plan(text, provider, target, extra)
        if plan:
            return plan
        if strict:
            raise RuntimeError("AI แปล/เรียบเรียงเป็นภาษาไทยไม่สำเร็จ"
                               + (f" ({LAST_AI_ERROR})" if LAST_AI_ERROR else "")
                               + " — ลองกดสร้างใหม่อีกครั้ง หรือเปลี่ยน AI (ถ้าโควตา Gemini หมด รอสักพักหรือพรุ่งนี้)")
    if foreign:
        raise RuntimeError("ข้อความเป็นภาษาอื่น ต้องเลือก AI (Gemini ฟรี) เพื่อแปลเป็นไทยก่อน")
    narrs = split_script(text)
    scenes = [{"narration": n_, "headline": "", "img": "", "image": "", "search": ""} for n_ in narrs]
    plan = {"title": narrs[0][:40] if narrs else "", "summary": "", "scenes": scenes}
    if provider != "none":
        fill_visuals(plan, provider)
    for i, s in enumerate(scenes):  # AI คิดภาพให้ไม่ได้จริงๆ → ใช้ภาพทั่วไป แต่ทำเครื่องหมายเตือนไว้
        if not s["image"]:
            s["image"], s["generic"] = GENERIC_IMAGES[i % len(GENERIC_IMAGES)], True
    finish_graphics(scenes)
    bad = sum(1 for s in scenes if s.get("generic"))
    if bad:
        why = "ยังไม่ได้เลือก AI" if provider == "none" else (plan.pop("ai_error", "") or "AI ตอบไม่ได้")
        plan["note"] = (f"AI คิดภาพให้ตรงเนื้อหาไม่ได้ {bad}/{len(scenes)} ฉาก ({why}) — ฉากเหล่านี้ใช้ภาพทั่วไปที่ไม่เกี่ยวกับเรื่อง "
                        "กด 📷 ภาพถ่ายจริง / 📁 รูปของฉัน ทีละฉาก หรือแก้ปัญหา AI แล้วเริ่มใหม่")
    plan.pop("ai_error", None)
    return plan


def _ask(provider: str, prompt: str) -> dict:
    raw = P.ask_ai(provider, prompt)
    return P._parse_json(raw)


def fill_visuals(plan: dict, provider: str) -> None:
    """คิดภาพประกอบทุกฉากจากบททั้งเรื่อง (รู้ว่าเรื่องเกี่ยวกับอะไร ตัวละครหน้าตายังไง)
    ฉากที่ได้ไม่ครบ → ถามทีละฉากซ้ำ (งานเล็กลง โมเดลเล็กทำได้แม่นขึ้น)"""
    scenes = plan["scenes"]
    topic = characters = ""
    try:
        data = _ask(provider, VISUAL_PROMPT.format(n=len(scenes), graphic_rules=_graphic_rules(), scenes="\n".join(
            f"Scene {i + 1}: {s['narration']}" for i, s in enumerate(scenes))))
        topic = str(data.get("topic") or "")[:300]
        characters = str(data.get("characters") or "")[:300]
        got = [v for v in data.get("scenes", []) if isinstance(v, dict)]
        if len(got) == len(scenes):  # จำนวนไม่ตรง = จับคู่ฉากผิดได้ → ไม่ใช้ แล้วถามทีละฉาก
            for s, v in zip(scenes, got):
                s["headline"] = P.clean_text(str(v.get("headline", "")))[:40]
                s["image"] = str(v.get("image", "")).strip()[:400]
                s["search"] = str(v.get("search", "")).strip()[:60]
                s["graphic"] = G.clean(v.get("graphic"), s["narration"])
        plan["title"] = str(data.get("title") or plan["title"])
        plan["summary"] = str(data.get("summary") or "")
    except Exception as e:
        print("AI คิดภาพทั้งเรื่องไม่สำเร็จ จะถามทีละฉาก:", e)
        plan["ai_error"] = P.error_text(e)
    if not topic:
        topic = " ".join(s["narration"] for s in scenes)[:300]
    for i, s in enumerate(scenes):
        if s["image"]:
            continue
        try:
            v = _ask(provider, SCENE_PROMPT.format(
                topic=topic, narr=s["narration"],
                prev=scenes[i - 1]["narration"] if i else "(start of video)",
                next=scenes[i + 1]["narration"] if i + 1 < len(scenes) else "(end of video)"))
            s["image"] = str(v.get("image", "")).strip()[:400]
            s["search"] = s["search"] or str(v.get("search", "")).strip()[:60]
            s["headline"] = s["headline"] or P.clean_text(str(v.get("headline", "")))[:40]
        except Exception as e:
            print(f"AI คิดภาพฉากที่ {i + 1} ไม่สำเร็จ:", e)
            plan["ai_error"] = P.error_text(e)
            if i == 0 and not any(x["image"] for x in scenes):
                break  # ฉากแรกก็ไม่ได้ + ทั้งเรื่องไม่ได้ = AI ใช้ไม่ได้เลย ไม่ต้องลองทุกฉาก
    if characters:  # ให้ตัวละครหน้าตาเหมือนกันทุกฉาก
        plan["characters"] = characters


LAST_AI_ERROR = ""
SPEECH_CPS = 11.5  # เสียงพากย์ไทยพูดได้ราว 11-12 ตัวอักษร/วินาที (ไม่นับช่องว่าง) ที่ความเร็ว +10%


def speech_budget(target: float) -> int:
    """จำนวนตัวอักษรบทพากย์ที่พอดีความยาวคลิป (หักเวลาเว้นระหว่างฉาก/ภาพปก ~10%)"""
    return int(target * 0.9 * SPEECH_CPS)


def _chars(t: str) -> int:
    return len(re.sub(r"\s", "", t or ""))


def fit_length(scenes: list[dict], budget: int) -> int:
    """AI เขียนยาวเกิน → ตัดฉากกลางเรื่องทีละฉาก (เก็บฉากเปิดและฉากปิดไว้) คืนจำนวนที่ตัด"""
    cut = 0
    while len(scenes) > 3 and sum(_chars(s["narration"]) for s in scenes) > budget * 1.15:
        mid = scenes[1:-1]
        drop = max(range(len(mid)), key=lambda k: (not mid[k].get("graphic"), _chars(mid[k]["narration"])))
        scenes.pop(drop + 1)
        cut += 1
    return cut


def _rewrite_plan(text: str, provider: str, target: float, extra: str = "") -> dict | None:
    """ลอง 2 รอบ (รอบสองตัดข้อมูลให้สั้นลง — กัน AI ตอบไม่จบ/JSON ขาด)"""
    global LAST_AI_ERROR
    if provider == "none":
        return None
    for limit in (8000, 3500):
        plan = _rewrite_once(text[:limit], provider, target, extra)
        if plan:
            if thai_ratio(" ".join(s["narration"] for s in plan["scenes"])) < 0.5:
                LAST_AI_ERROR = "AI ตอบกลับมาไม่ใช่ภาษาไทย"
                continue
            return plan
    return None


def _rewrite_once(text: str, provider: str, target: float, extra: str = "") -> dict | None:
    global LAST_AI_ERROR
    n = max(3, min(15, round(target / 7)))
    budget = speech_budget(target)
    try:
        prompt = STORY_PROMPT.format(target=int(target), n=n, text=text, graphic_rules=_graphic_rules(),
                                     extra=extra, budget=budget, per_scene=max(40, min(110, budget // n)))
        raw = P.ask_ai(provider, prompt)
        data = P._parse_json(raw)
        scenes = []
        for s in data.get("scenes", []):
            narr = P.clean_text(str(s.get("narration", "")))
            if narr:
                scenes.append({"narration": narr, "headline": P.clean_text(str(s.get("headline", "")))[:40],
                               "image": str(s.get("image", "")).strip()[:300] or GENERIC_IMAGES[0], "img": "",
                               "search": str(s.get("search", "")).strip()[:60],
                               "graphic": G.clean(s.get("graphic"), narr)})
        if scenes:
            cut = fit_length(scenes, budget)
            plan = {"title": str(data.get("title", "")), "summary": str(data.get("summary", "")), "scenes": scenes}
            if cut:
                plan["note"] = f"บทยาวเกิน {int(target)} วินาที จึงตัดฉากกลางเรื่องออก {cut} ฉาก (อยากได้ยาวกว่านี้ เลื่อนความยาวคลิปให้มากขึ้นแล้วสร้างใหม่)"
            for s in scenes:
                if s["image"] == GENERIC_IMAGES[0]:
                    s["image"] = ""
            if any(not s["image"] for s in scenes):
                fill_visuals(plan, provider)
            for i, s in enumerate(scenes):
                if not s["image"]:
                    s["image"], s["generic"] = GENERIC_IMAGES[i % len(GENERIC_IMAGES)], True
            finish_graphics(scenes)
            return plan
        LAST_AI_ERROR = "AI ไม่ได้ส่งฉากกลับมา"
    except Exception as e:
        print("AI เรียบเรียงบทไม่สำเร็จ:", e)
        LAST_AI_ERROR = P.error_text(e)[:160]
    return None


def size_for(layout: str) -> tuple[int, int]:
    return (1920, 1080) if layout == "original" else (1080, 1920)


STOP = set("a an the of in on at with and or to for by from into over under very is are this that his her their its".split())


def search_terms(s: dict) -> str:
    if s.get("search"):
        return s["search"]
    words = [w.strip(",.") for w in (s.get("image") or "").split()]
    return " ".join([w for w in words if w.lower() not in STOP][:4]) or "abstract background"


def next_names(scene_dir: Path, i: int, n: int, ext: str = ".png") -> list[Path]:
    """ชื่อไฟล์ภาพ/วิดีโอใหม่ของฉากที่ i (scene_03_v2.png, _v3.mp4 …) ไม่ทับของเดิม"""
    out, v = [], 2
    while len(out) < n:
        p = scene_dir / f"scene_{i + 1:02}_v{v}{ext}"
        if not p.with_suffix(".png").exists() and not p.with_suffix(".mp4").exists() and p not in out:
            out.append(p)
        v += 1
    return out


def is_video(name: str) -> bool:
    return str(name).lower().endswith(".mp4")


def poster(name: str) -> str:
    """ภาพตัวอย่างของวิดีโอ (ชื่อเดียวกัน .png) — ภาพนิ่งคืนชื่อเดิม"""
    return str(name)[:-4] + ".png" if is_video(name) else str(name)


def video_options(s: dict, i: int, scene_dir: Path, n: int = 4, query: str = "") -> list[str]:
    """วิดีโอฟรีให้เลือก (Pixabay/Pexels) ค้นแบบเดียวกับภาพถ่าย"""
    if query:
        lang = "th" if re.search(r"[ก-๙]", query) else "en"
        if lang == "th":
            query = imagegen.translate_th_en(query) or query
            lang = "th" if re.search(r"[ก-๙]", query) else "en"
    else:
        query, lang = scene_query(s)
    got = imagegen.search_videos(query, next_names(scene_dir, i, n, ".mp4"), lang)
    return [p.name for p in got]


def ai_variants(s: dict, i: int, scene_dir: Path, style: str, n: int, progress=None) -> tuple[list[str], bool]:
    """AI วาด n ภาพ (คนละแบบ) คืน (ชื่อไฟล์, วาดด้วย AI ได้ไหม)"""
    import random
    names, ai = [], True
    for k, p in enumerate(next_names(scene_dir, i, n)):
        if progress:
            progress(f"วาดภาพที่ {k + 1}/{n}")
        ai = imagegen.generate(s.get("image") or GENERIC_IMAGES[0], p, 1024, 1024, style,
                               seed=random.randint(1, 2**31 - 1), progress=progress) and ai
        names.append(p.name)
    return names, ai


TH_STOP = set("""และ หรือ แต่ ที่ ซึ่ง ของ ใน บน จาก กับ ให้ ได้ ไป มา เป็น อยู่ คือ มี ว่า จะ ก็ แล้ว ยัง นี้ นั้น
เรา เขา ผม ฉัน คุณ มัน พวก ทุก บาง หลาย มาก น้อย กว่า ที่สุด อย่าง เพราะ ถ้า เมื่อ โดย ตาม เพื่อ จึง ทั้ง
ครับ ค่ะ นะ จ้า เลย ด้วย อีก แค่ เคย ต้อง ควร อาจ สามารถ การ ความ ไม่ ใช่ ไหม อะไร ทำไม อย่างไร ยังไง""".split())


def thai_keywords(text: str, k: int = 3) -> str:
    """ดึงคำนามสำคัญจากบทภาษาไทย (ใช้ค้นภาพเมื่อ AI คิดภาพไม่ได้)"""
    words: list[str] = []
    try:
        from pythainlp.tokenize import word_tokenize
        toks = [t for t in word_tokenize(text, engine="newmm") if t.strip()]
        try:
            from pythainlp.tag import pos_tag
            tagged = pos_tag(toks, corpus="orchid_ud")
            words = [w for w, t in tagged if t in ("NOUN", "PROPN") and len(w) >= 2 and w not in TH_STOP]
        except Exception:
            words = []
        if not words:
            words = [w for w in toks if len(w) >= 3 and w not in TH_STOP and re.search(r"[ก-๙A-Za-z]", w)]
    except Exception:
        words = [w for w in re.split(r"\s+", text) if len(w) >= 3]
    seen: list[str] = []
    for w in sorted(words, key=lambda w: -len(w)):  # คำยาว = มักเป็นคำเฉพาะ (ทะเลทราย, ดาวอังคาร)
        if w not in seen and not any(w in x for x in seen):
            seen.append(w)
    order = [w for w in words if w in seen[:k]]
    return " ".join(dict.fromkeys(order))


def scene_query(s: dict) -> tuple[str, str]:
    """คำค้นภาพของฉาก → (คำค้น, ภาษา) — ถ้า AI คิดภาพไม่ได้ (generic) ใช้คำสำคัญจากบทแทน"""
    if not s.get("generic") and (s.get("search") or (s.get("image") and s["image"] not in GENERIC_IMAGES)):
        return search_terms(s), "en"
    th = thai_keywords(s.get("narration") or "")
    if not th:
        return search_terms(s), "en"
    en = imagegen.translate_th_en(th)
    return (en, "en") if en else (th, "th")


def photo_options(s: dict, i: int, scene_dir: Path, n: int = 4, query: str = "") -> list[str]:
    if query:
        lang = "th" if re.search(r"[ก-๙]", query) else "en"
        if lang == "th":
            query = imagegen.translate_th_en(query) or query
            lang = "th" if re.search(r"[ก-๙]", query) else "en"
    else:
        query, lang = scene_query(s)
    got = imagegen.search_photos(query, next_names(scene_dir, i, n), lang)
    if not got and lang == "en" and s.get("narration"):  # ภาษาอังกฤษไม่เจอ → ลองค้นภาษาไทยตรงๆ
        th = thai_keywords(s["narration"])
        if th:
            got = imagegen.search_photos(th, next_names(scene_dir, i, n), "th")
    return [p.name for p in got]


PICK_PROMPT = """You are a video editor choosing stock photos for a Thai short vertical video.
Story topic: {topic}
For each scene you get its Thai narration and several numbered candidate photos.
Pick the photo that best illustrates THAT scene's narration: the right subject, place and mood.
Prefer clear, relevant, good-looking photos. Avoid photos with big text/watermarks, or that contradict the narration.
order = photo numbers from best to worst. score 0-10 = how well your best pick matches (0 = nothing relevant).
Reply JSON only: {{"scenes": [{{"id": 1, "order": [2, 1, 3], "score": 7}}]}} with one item per scene."""


def vision_ready() -> bool:
    import os
    return bool((os.environ.get("GEMINI_API_KEY") or "").strip())


def _thumb_part(path: Path) -> dict | None:
    import base64
    import io
    from PIL import Image
    try:
        im = Image.open(path).convert("RGB")
        im.thumbnail((384, 384))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=70)
        return {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}}
    except Exception:
        return None


def rank_photos(scenes: list[dict], scene_dir: Path, topic: str = "", progress=None,
                per_call: int = 3) -> int:
    """ให้ Gemini ดูภาพตัวเลือกของแต่ละฉาก แล้วเรียงภาพที่ตรงบทที่สุดขึ้นก่อน (ส่งทีละ 3 ฉากต่อครั้ง ประหยัดโควตา)
    scenes: [{"narration", "options"}] — แก้ options/img ในตัว คืนจำนวนฉากที่เลือกให้สำเร็จ"""
    if not vision_ready():
        return 0
    todo = [s for s in scenes if len([o for o in s.get("options") or [] if (scene_dir / o).exists()]) > 1]
    topic = topic or " ".join(s.get("narration", "") for s in scenes)[:300]
    done = 0
    for g in range(0, len(todo), per_call):
        group = todo[g:g + per_call]
        if progress:
            progress(f"AI กำลังเลือกภาพที่ตรงบท ({g + 1}-{g + len(group)}/{len(todo)})")
        parts, cands = [], []
        for k, s in enumerate(group, 1):
            opts = [o for o in s["options"] if (scene_dir / o).exists()][:6]
            cands.append(opts)
            parts.append({"text": f"Scene {k} narration (Thai): {s.get('narration', '')}"})
            for m, o in enumerate(opts, 1):
                img = _thumb_part(scene_dir / poster(o))  # วิดีโอ → ดูจากภาพตัวอย่าง
                if img:
                    parts += [{"text": f"Scene {k} - photo {m}:"}, img]
        try:
            data = P._parse_json(P._ask_gemini(PICK_PROMPT.format(topic=topic), parts))
        except Exception as e:
            print("AI เลือกภาพไม่ได้ (ใช้ภาพแรกตามเดิม):", e)
            break  # โควตาเต็ม/ผิดพลาด → ไม่ต้องลองกลุ่มถัดไป
        for r in data.get("scenes") or []:
            try:
                k = int(r.get("id")) - 1
                order = [int(x) - 1 for x in r.get("order") or []]
                score = float(r.get("score") or 0)
            except (TypeError, ValueError):
                continue
            if not 0 <= k < len(group):
                continue
            s, opts = group[k], cands[k]
            best = [opts[x] for x in dict.fromkeys(order) if 0 <= x < len(opts)]
            new = best + [o for o in opts if o not in best]
            s["options"] = new + [o for o in s["options"] if o not in new]
            s["img"] = new[0]
            s["weak_photo"] = score < 4
            done += 1
    return done


def video_scenes(scenes: list[dict]) -> list[int]:
    """เลือกฉากที่จะแทรกวิดีโอ: ราว 1 ใน 3 กระจายทั้งเรื่อง (ฉากแรกด้วย = เปิดคลิปให้มีชีวิต)"""
    n = len(scenes)
    if n == 0:
        return []
    want = max(1, round(n / 3))
    step = n / want
    return sorted({min(n - 1, int(k * step)) for k in range(want)})


def add_videos(plan: dict, scene_dir: Path, progress, idxs: list[int] | None = None) -> int:
    """แทรกวิดีโอฟรีในบางฉาก (ภาพเดิมยังอยู่ในตัวเลือก) คืนจำนวนฉากที่ได้วิดีโอ"""
    scenes = plan["scenes"]
    idxs = video_scenes(scenes) if idxs is None else idxs
    done: list[dict] = []
    for k, i in enumerate(idxs):
        s = scenes[i]
        progress(k / max(1, len(idxs)) * 100, f"หาวิดีโอฟรีฉากที่ {i + 1} ({k + 1}/{len(idxs)})")
        try:
            vids = video_options(s, i, scene_dir, 4 if vision_ready() else 3)
        except Exception as e:
            plan["note"] = ((plan.get("note") or "") + f" · หาวิดีโอไม่ได้ ({P.error_text(e)})").strip(" ·")
            break  # คีย์ผิด/โควตา → ไม่ต้องลองฉากอื่น
        if not vids:
            continue
        tmp = {"narration": s.get("narration", ""), "options": vids}
        if len(vids) > 1 and vision_ready():
            rank_photos([tmp], scene_dir, plan.get("title") or "")
        s["options"] = tmp["options"] + [o for o in s.get("options") or [] if o not in tmp["options"]]
        s["img"] = tmp["options"][0]
        done.append(s)
    return len(done)


def draw_images(plan: dict, scene_dir: Path, layout: str, style: str, progress,
                only_missing: bool = True, source: str = "ai") -> int:
    """หาภาพทุกฉาก (AI วาด หรือภาพถ่ายจริง) คืนจำนวนฉากที่ได้ภาพจริง (ไม่ใช่ภาพไล่สี)"""
    scene_dir.mkdir(parents=True, exist_ok=True)
    n, ok = len(plan["scenes"]), 0
    photo_err = None
    if source == "ai" and not imagegen.available():  # ไม่มีการ์ดจอ → ใช้ภาพถ่ายจริงแทน
        source = "photo"
        plan["note"] = f"เครื่องนี้ไม่มีการ์ดจอ จึงใช้ภาพถ่ายจริงจาก {imagegen.photo_source()} แทนการวาดด้วย AI"
    photo_scenes: list[dict] = []
    for i, s in enumerate(plan["scenes"]):
        if only_missing and s.get("img") and (scene_dir / s["img"]).exists():
            continue
        # AI คิดภาพไม่ได้ (ภาพทั่วไปไม่เกี่ยวกับเรื่อง) → ใช้ภาพถ่ายฟรีจากคำสำคัญในบทแทนการวาด
        if (source == "photo" or s.get("generic")) and not photo_err:
            progress(i / n * 100, f"หาภาพถ่ายฉากที่ {i + 1}/{n}")
            try:
                names = photo_options(s, i, scene_dir, 6 if vision_ready() else 4)
                if names:
                    s["options"], s["img"] = names, names[0]
                    photo_scenes.append(s)
                    if s.pop("generic", False):
                        s["auto_photo"] = True
                    ok += 1
                    continue
            except Exception as e:  # คีย์ผิด/เน็ตมีปัญหา → ใช้ AI วาดแทนทั้งหมด
                photo_err = P.error_text(e)
                plan["note"] = f"หาภาพถ่ายไม่ได้ ({photo_err}) จึงให้ AI วาดแทน"
        progress(i / n * 100, f"วาดภาพฉากที่ {i + 1}/{n}")
        names, ai = ai_variants(s, i, scene_dir, style, 1, lambda m: progress(i / n * 100, f"ฉากที่ {i + 1}/{n}: {m}"))
        if not ai and not photo_err:  # วาดไม่ได้ (ได้แค่ภาพไล่สี) → ลองภาพถ่ายฟรีแทน
            try:
                got = photo_options(s, i, scene_dir, 6 if vision_ready() else 4)
                if got:
                    names, ai = got, True
                    photo_scenes.append(s)
            except Exception as e:
                photo_err = P.error_text(e)
        s["options"], s["img"] = names, names[0]
        ok += 1 if ai else 0
    if photo_scenes and vision_ready():
        rank_photos(photo_scenes, scene_dir, plan.get("title") or "", lambda m: progress(99, m))
    auto = sum(1 for s in plan["scenes"] if s.get("auto_photo"))
    if auto:
        plan["note"] = ((plan.get("note") or "") + f" · AI คิดภาพไม่ได้ {auto} ฉาก จึงใช้ภาพถ่ายฟรีที่ค้นจากคำสำคัญในบทแทน — "
                        "ภาพไหนไม่ตรง กด 📷 ภาพถ่ายจริง เพื่อดูภาพอื่น หรือพิมพ์คำค้นเอง").strip(" ·")
    weak = [str(k + 1) for k, s in enumerate(plan["scenes"]) if s.get("weak_photo")]
    if weak:
        plan["note"] = ((plan.get("note") or "") + f" · AI ดูแล้วว่าฉาก {', '.join(weak)} ยังไม่มีภาพที่ตรงบทนัก "
                        "ลองพิมพ์คำค้นเอง หรือใช้ 📁 รูปของฉัน").strip(" ·")
    return ok


# ───────────────────────── ตัดต่อ ─────────────────────────

LEAD, TAIL = 0.25, 0.45   # เว้นก่อน/หลังเสียงพากย์ในแต่ละฉาก
XF = 0.35                 # ความยาวทรานซิชัน
MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_up"]
TRANSITIONS = ["fade", "slideleft", "slideup", "circleopen", "smoothleft"]


def _motion(kind: str, W: int, H: int, D: float) -> str:
    """ภาพหลัก (สี่เหลี่ยมจัตุรัส) ค่อยๆ ซูม/เลื่อน วางบนพื้นหลังเบลอของภาพเดียวกัน → filter [0:v] → [mv]"""
    S = min(W, H)                        # ขนาดภาพหลัก: เต็มความกว้าง (แนวตั้ง) / เต็มความสูง (แนวนอน)
    y = (H - S) // 2 - (60 if H > W else 0)
    bg = (f"[b0]scale=270:270,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"boxblur=10:2,eq=brightness=-0.18:saturation=1.2,setsar=1[bg]")
    fit = f"scale={S}:{S}:force_original_aspect_ratio=increase,crop={S}:{S},setsar=1"
    if kind == "zoom_in":
        fg = f"{fit},scale=w='{S}*(1+0.10*t/{D:.3f})':h=-2:eval=frame,crop={S}:{S}:(iw-{S})/2:(ih-{S})/2"
    elif kind == "zoom_out":
        fg = f"{fit},scale=w='{S}*(1.10-0.10*t/{D:.3f})':h=-2:eval=frame,crop={S}:{S}:(iw-{S})/2:(ih-{S})/2"
    elif kind == "pan_right":
        big = int(S * 1.12) // 2 * 2
        fg = f"{fit},scale={big}:{big},crop={S}:{S}:x='(iw-{S})*t/{D:.3f}':y=(ih-{S})/2"
    else:
        big = int(S * 1.12) // 2 * 2
        fg = f"{fit},scale={big}:{big},crop={S}:{S}:x=(iw-{S})/2:y='(ih-{S})*(1-t/{D:.3f})'"
    return f"[0:v]split[b0][f0];{bg};[f0]{fg}[fg];[bg][fg]overlay=(W-w)/2:{y}[mv]"


def _video_layout(video: Path, W: int, H: int) -> str:
    """วิดีโอแทรก: แนวเดียวกับจอ → เต็มจอ · คนละแนว → วิดีโอสี่เหลี่ยมกลางจอบนพื้นหลังเบลอ (เหมือนฉากภาพนิ่ง)"""
    try:
        info = P.probe(video)
        vw, vh = int(info.get("width") or 0), int(info.get("height") or 0)
    except Exception:
        vw = vh = 0
    same = vw and vh and ((vh > vw) == (H > W)) and abs(vw / vh - W / H) < 0.35
    if same:
        return (f"[0:v]setpts=PTS-STARTPTS,scale={W}:{H}:force_original_aspect_ratio=increase,"
                f"crop={W}:{H},setsar=1[mv]")
    S = min(W, H)
    y = (H - S) // 2 - (60 if H > W else 0)
    return (f"[0:v]setpts=PTS-STARTPTS,split[b0][f0];"
            f"[b0]scale=270:-2,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
            f"boxblur=10:2,eq=brightness=-0.18:saturation=1.2,setsar=1[bg];"
            f"[f0]scale={S}:{S}:force_original_aspect_ratio=increase,crop={S}:{S},setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:{y}[mv]")


def render_scene(img: Path, scene: dict, i: int, narr: Path | None, out: Path, workdir: Path,
                 layout: str, subtitles: bool, extras: bool, brand: dict | None, sfx: bool = True) -> float:
    W, H = size_for(layout)
    vertical = H > W
    nd = P.probe(narr)["duration"] if narr else 0.0
    D = max(2.5, nd + LEAD + TAIL)
    video = is_video(img.name)
    anim = img.name.startswith("anim_")  # ฉากแอนิเมชันกราฟิก (ไม่มีภาพจริง): พื้นหลังเต็มจอลอยช้าๆ
    if anim:
        motion = (f"[0:v]crop={W}:{H}:x='(iw-{W})/2+(iw-{W})/2*sin(t*0.5)':"
                  f"y='(ih-{H})/2+(ih-{H})/2*cos(t*0.4)',setsar=1[mv]")
    else:
        motion = _video_layout(img, W, H) if video else _motion(MOTIONS[i % len(MOTIONS)], W, H, D)
    vf = ["fps=30"]

    # ข้อความไทยทั้งหมด (หัวข้อ, ชื่อช่อง, ซับ) วาดด้วย libass ให้สระ/วรรณยุกต์ถูกตำแหน่ง
    ass = P.Ass(W, H)
    head = (scene.get("headline") or "").strip() if extras else ""
    kin_cues = []
    pcard = img.parent / scene["product_img"] if anim and extras and scene.get("product_img") else None
    if pcard is not None and not pcard.exists():
        pcard = None
    has_g = bool(extras and scene.get("graphic") and not scene["graphic"].get("off"))
    studio = bool(pcard is not None and scene.get("studio"))
    if head and anim:  # ตัวหนังสือใหญ่เด้งกลางจอ + รูปทรงลอย (มีรูปสินค้า → ย้ายข้อความขึ้นบน)
        kin_cues = G.kinetic(ass, head, 0, D, i, cy=(0.15 if pcard is not None else None),
                             shapes=not studio)
    elif head:
        ass.headline(P._wrap(head, 16 if vertical else 30), 0, D, int(H * (0.105 if vertical else 0.07)))
    if studio and not has_g:  # ประกายวิ้งๆ รอบสินค้า
        G.sparkles(ass, 0.6, D, W / 2, H * 0.47, W * 0.3, i)
    if extras and scene.get("graphic") and not scene["graphic"].get("off"):  # โมชันกราฟิกช่วยให้เข้าใจ
        # ฉากสตูดิโอ: กรอบกราฟิกอยู่เหนือสินค้า (สินค้าวางบนแท่นด้านล่าง)
        cues = G.render(ass, scene["graphic"], min(0.4, D / 4) + (0.5 if kin_cues else 0), D - 0.2,
                        bottom=0.47 if studio and vertical else 0.69)
    else:
        cues = []
    cues = sorted(kin_cues + cues)
    brand = brand or {}
    text = (brand.get("text") or "").strip() if extras else ""
    logo = brand.get("logo") if extras else None
    if text:
        ass.brand(text, D, x=(40 + 96 + 18) if logo else 40)
    if extras and subtitles and narr and scene.get("narration"):
        ass.subs(scene["narration"], LEAD, nd, 22 if vertical else 40, pop=subtitles == "pop")
    if ass.write(workdir / f"text_{i}.ass"):
        vf.append(P.ass_filter(f"text_{i}.ass"))

    inputs = (["-stream_loop", "-1", "-t", f"{D:.3f}", "-i", str(img)] if video  # วิดีโอสั้นกว่าฉาก → วนซ้ำ
              else ["-loop", "1", "-framerate", "30", "-t", f"{D:.3f}", "-i", str(img)])
    parts, n_in = [], 1
    if narr:
        inputs += ["-i", str(narr)]; ia = n_in; n_in += 1
    else:
        inputs += ["-f", "lavfi", "-t", f"{D:.3f}", "-i", "anullsrc=r=44100:cl=stereo"]; ia = n_in; n_in += 1
    if logo:
        inputs += ["-loop", "1", "-i", str(logo)]; il = n_in; n_in += 1
        parts.append(motion)
        parts.append(f"[mv]{','.join(vf)}[pre]")
        parts.append(f"[{il}:v]scale=-2:{96 if vertical else 80},format=rgba[lg]")
        parts.append(f"[pre][lg]overlay=40:{'H*0.075-20' if vertical else '40'}:shortest=1,format=yuv420p[v]")
    else:
        parts.append(motion)
        parts.append(f"[mv]{','.join(vf)},format=yuv420p[v]")
    if pcard is not None and studio:  # ฉากสตูดิโอ: สินค้าวางบนแท่น + แถบแสงวิ่งผ่าน + กล้องค่อยๆ ซูมเข้า
        import product as PR
        bw, bh = (int(W * 0.36), int(H * 0.17)) if has_g else (int(W * 0.58), int(H * 0.36))
        band = workdir / "shine_band.png"
        if not band.exists():
            PR.shine_band(band)
        inputs += ["-loop", "1", "-t", f"{D:.3f}", "-i", str(pcard)]; ip = n_in; n_in += 1
        inputs += ["-loop", "1", "-t", f"{D:.3f}", "-i", str(band)]; ib = n_in; n_in += 1
        floor_y = H * PR.STUDIO_TOP + H * 0.012
        parts[parts.index(motion)] = motion.replace("[mv]", "[mv0]")
        parts.insert(parts.index(motion.replace("[mv]", "[mv0]")) + 1,
                     # แถบแสง: วางทับสินค้าแล้วใช้รูปร่างสินค้าเป็นหน้ากาก → แสงวิ่งผ่านเฉพาะตัวสินค้า (เร็วกว่า geq มาก)
                     f"[{ip}:v]scale={bw}:{bh}:force_original_aspect_ratio=decrease,format=rgba,split[pa][pb];"
                     f"[pb]alphaextract[pm];"
                     f"[{ib}:v]format=rgba,scale=-1:{bh * 2}[bd];"
                     f"[pa][bd]overlay=x='-overlay_w+mod(t+{i * 0.7:.1f},3.2)/1.3*(main_w+overlay_w)':y=-{bh // 2}:"
                     f"format=auto[ps];[ps][pm]alphamerge,fade=in:st=0:d=0.3:alpha=1[pc];"
                     f"[mv0][pc]overlay=x=(W-w)/2:y='{floor_y:.0f}-h+max(0,0.35-t)*260':format=auto,"
                     f"zoompan=z='min(1+0.0011*on,1.14)':x='iw/2-(iw/zoom/2)':y='ih*0.45-(ih/zoom*0.45)':"
                     f"d=1:s={W}x{H}:fps=30[mv]")
    elif pcard is not None:  # รูปสินค้าลอยขึ้นมา โยกเบาๆ อยู่ใต้ตัวหนังสือ (ก่อนวาดซับ/กราฟิก)
        inputs += ["-loop", "1", "-t", f"{D:.3f}", "-i", str(pcard)]; ip = n_in; n_in += 1
        cw = int(W * (0.34 if has_g else 0.62))
        cy = H * (0.40 if has_g else 0.52)
        parts[parts.index(motion)] = motion.replace("[mv]", "[mv0]")
        parts.insert(parts.index(motion.replace("[mv]", "[mv0]")) + 1,
                     f"[{ip}:v]scale={cw}:-1,format=rgba,"
                     f"rotate='{(-1) ** i * 0.05:.3f}+0.035*sin(t*1.7)':c=none:ow=rotw(0.09):oh=roth(0.09),"
                     f"fade=in:st=0.1:d=0.35:alpha=1[pc];"
                     f"[mv0][pc]overlay=x='(W-w)/2+{0 if has_g else ((i % 3) - 1) * W * 0.08:.0f}+10*cos(t*1.3)':"
                     f"y='{cy:.0f}-h/2+14*sin(t*2.1)+max(0,0.45-t)*500':"
                     f"eof_action=pass:format=auto[mv]")
    norm = "aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo"
    d = int(LEAD * 1000)
    delay = f",adelay={d}|{d}" if narr else ""
    sounds = {}
    if sfx and cues:
        try:
            sounds = G.make_sfx(workdir)
        except Exception as e:
            print("ทำเสียงเอฟเฟกต์กราฟิกไม่ได้:", str(e)[-200:])
    if sounds:
        # เสียงเอฟเฟกต์เบาๆ ตามจังหวะกราฟิก — ทุกเส้น apad ยาวไม่จำกัด ให้ amix หารเท่ากันตลอด แล้วคูณกลับ
        idx = {}
        for name in dict.fromkeys(n for _, n in cues):
            inputs += ["-i", str(sounds[name][0])]; idx[name] = n_in; n_in += 1
        labels = []
        for k, (t, name) in enumerate(cues):
            ms = int(t * 1000)
            parts.append(f"[{idx[name]}:a]{norm},volume={sounds[name][1]:.2f},adelay={ms}|{ms},apad[fx{k}]")
            labels.append(f"[fx{k}]")
        n = len(labels) + 1
        parts.append(f"[{ia}:a]{norm}{delay},apad[nar]")
        parts.append(f"[nar]{''.join(labels)}amix=inputs={n}:duration=first:dropout_transition=0,"
                     f"volume={n},atrim=0:{D:.3f}[a]")
    else:
        parts.append(f"[{ia}:a]{norm}{delay},apad,atrim=0:{D:.3f}[a]")
    P.run(["ffmpeg", "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(parts),
           "-map", "[v]", "-map", "[a]", "-t", f"{D:.3f}", "-c:v", "libx264", "-preset", "veryfast",
           "-crf", "21", "-r", "30", "-video_track_timescale", "90000",
           "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", out.name], cwd=workdir)
    return D


def join_xfade(files: list[Path], durs: list[float], out: Path, workdir: Path) -> None:
    """ต่อฉากด้วยทรานซิชัน (ถ้าไม่ได้ ใช้ต่อธรรมดา)"""
    if len(files) == 1:
        P.concat(files, out, workdir)
        return
    inputs, parts = [], []
    for f in files:
        inputs += ["-i", f.name]
    vlast, alast, off = "[0:v]", "[0:a]", 0.0
    for k in range(1, len(files)):
        off += durs[k - 1] - XF
        tr = TRANSITIONS[(k - 1) % len(TRANSITIONS)]
        parts.append(f"{vlast}[{k}:v]xfade=transition={tr}:duration={XF}:offset={off:.3f}[v{k}]")
        parts.append(f"{alast}[{k}:a]acrossfade=d={XF}[a{k}]")
        vlast, alast = f"[v{k}]", f"[a{k}]"
    try:
        P.run(["ffmpeg", "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(parts),
               "-map", vlast, "-map", alast, "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
               "-r", "30", "-video_track_timescale", "90000", "-c:a", "aac", "-b:a", "160k",
               "-ar", "44100", "-ac", "2", "-movflags", "+faststart", str(out.resolve())], cwd=workdir)
    except RuntimeError as e:
        print("ทรานซิชันไม่สำเร็จ ต่อแบบธรรมดาแทน:", str(e)[-200:])
        P.concat(files, out, workdir)


def render_story(plan: dict, scene_dir: Path, workdir: Path, out: Path, *, voice: str, rate: int,
                 layout: str, subtitles: bool, progress, brand: dict | None = None,
                 cover: Path | None = None, clean: bool = False, style: str = "cinematic",
                 tone: str = "story", sfx: bool = True) -> list[Path]:
    scene_dir, workdir, out = scene_dir.resolve(), workdir.resolve(), out.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    scenes = plan["scenes"]
    if not scenes:
        raise RuntimeError("ไม่มีฉากให้ตัดต่อ")
    missing = [s for s in scenes if not s.get("img") or not (scene_dir / s["img"]).exists()]
    if missing:  # ฉากที่เพิ่มใหม่/ภาพหาย → วาดก่อน
        draw_images(plan, scene_dir, layout, style, lambda p, m: progress(0, m))
    n, files, durs = len(scenes), [], []
    texts = [P.clean_text(s.get("narration", "")) for s in scenes]
    narrs = P.tts_all(texts, workdir, voice, rate, tone, progress, total=30)
    for i, s in enumerate(scenes):
        text, narr = texts[i], narrs[i]
        progress(30 + (i + 0.5) / n * 65, f"ทำแอนิเมชันฉากที่ {i + 1}/{n}")
        f = workdir / f"scene_{i:03}.mp4"
        sc = {**s, "narration": text}
        try:
            d = render_scene(scene_dir / s["img"], sc, i, narr, f, workdir, layout, subtitles,
                             not clean, None if clean else brand, sfx=sfx and not clean)
        except RuntimeError as e:  # ฟอนต์/ซับมีปัญหา → ทำแบบไม่มีตัวหนังสือ
            print("ทำฉากแบบเต็มไม่สำเร็จ ลองแบบไม่มีตัวหนังสือ:", str(e)[-300:])
            d = render_scene(scene_dir / s["img"], sc, i, narr, f, workdir, layout, False, False, None)
        files.append(f)
        durs.append(d)
    progress(97, "ต่อฉากพร้อมทรานซิชัน")
    joined = workdir / "joined.mp4"
    join_xfade(files, durs, joined, workdir)
    seq = [joined]
    if cover and not clean and Path(cover).exists():
        cv = workdir / "cover.mp4"
        try:
            P.make_cover_clip(Path(cover), joined, cv)
            seq.insert(0, cv)
        except RuntimeError as e:
            print("ใส่ภาพปกต้นคลิปไม่ได้:", e)
    P.concat(seq, out, workdir)  # เข้ารหัสใหม่เป็นสเปกมาตรฐาน (มือถือเล่นได้แน่นอน)
    return files
