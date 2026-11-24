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
- เล่าต่อเนื่อง ภาษาพูดเป็นกันเอง กระชับ
- ฉากสุดท้ายต้องจบด้วยคำถามสั้นๆ 1 ข้อที่เกี่ยวกับเรื่องนี้ ชวนคนดูตอบในคอมเมนต์ (เช่น "แล้วคุณล่ะ เคยเจอแบบนี้ไหม? คอมเมนต์บอกหน่อย")
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
{mood_rules}
{badge_rules}

ตอบเป็น JSON อย่างเดียว:
{{"title": "ชื่อคลิปดึงดูด (อีโมจิได้ 1-2 ตัว)", "summary": "แคปชัน 1-2 ประโยค + แฮชแท็ก 3-5 อัน",
 "scenes": [{{"narration": "...", "headline": "...", "image": "...", "search": "...", "graphic": null, "mood": "calm", "badge": "", "quote": "", "real": false}}]}}

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
  The SPECIFIC object the narration is about must be the main subject and clearly visible — if it is small or a detail
  (e.g. "the tiny hole in an airplane window"), use a macro / extreme close-up of exactly that detail and describe its
  shape and location, instead of a wide view of the whole thing (not just "airplane wing in the sky").
  No text or letters in the image. No real people's names, celebrities, brands or copyrighted characters — describe them generically.
- "search": 2-4 English words to search a stock-photo site for this scene (e.g. "shark swimming deep ocean")
{graphic_rules}
{mood_rules}
{badge_rules}
Also write "cta": ONE short, natural spoken Thai question (max 70 characters) about this topic that invites viewers to answer
in the comments, ending with something like "คอมเมนต์บอกหน่อย" (e.g. "แล้วคุณล่ะ มีเพื่อนเป็นแฝดไหม? คอมเมนต์บอกหน่อย"). No emoji.

Reply with JSON only:
{{"topic": "one English sentence: what the story is about", "characters": "English description of main characters, or empty", "cta": "...",
 "title": "catchy Thai title (1-2 emoji ok)", "summary": "Thai caption 1-2 sentences + 3-5 hashtags",
 "scenes": [{{"headline": "...", "image": "...", "search": "...", "graphic": null, "mood": "calm", "badge": "", "quote": "", "real": false}}]}}
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

MOOD_RULES = """- "mood": the feeling of this scene, so the animation can match it. One of:
  "hook" (attention-grabbing opener — usually scene 1), "calm", "info" (explaining facts/numbers),
  "exciting" (action, fast, competition), "shock" (surprise, twist, danger), "sad" (sad, serious, loss),
  "happy" (fun, good news, success, friendly ending). Vary it with the story — not the same mood everywhere."""

BADGE_RULES = """- "badge": ONLY for true stories (history, sports, news, real people/places): a short Thai date/place tag for this scene,
  like "1 พ.ค. 2019 · คัมป์นู" or "ปี 1969 · ดวงจันทร์". Use only facts you are sure of; otherwise "". Fiction/general topics: "".
- "quote": a short famous line really said in this moment (max 30 characters, Thai or original language), e.g. "Never Give Up".
  Only if it is a well-known real quote; otherwise "". Never invent quotes.
- "real": true if the scene shows real, specific people, teams, places or events (so real photos should be searched), else false.
- "amb": quiet background ambience that puts the viewer IN this scene's place/feeling, one of:
  "space", "signal" (radio static + beeps), "tension" (dark mysterious drone), "heart" (heartbeat, suspense),
  "clock" (ticking, time running out), "wind" (cold/wind/snow/desert), "rain", "waves" (sea/beach),
  "fire", "war" (distant explosions/battle), "night" (crickets, quiet night), "magic" (dream/fantasy/wonder), or "" for none.
  Keep the same ambience across consecutive scenes in the same place; use "" when nothing fits.
- "fx": ONE short sound effect at the start of the scene, or "": "boom" (big reveal/shock), "riser" (build-up just
  before a reveal), "beep", "heart", "shutter" (photo taken), "glitch" (error/strange signal), "ding" (good idea/answer).
  Use fx in at most a third of the scenes."""

MOODS = {"hook": "⚡ เปิดแรง", "calm": "🌿 สบายๆ", "info": "💡 ให้ข้อมูล", "exciting": "🔥 ตื่นเต้น",
         "shock": "😱 ช็อก/หักมุม", "sad": "🥀 เศร้า/จริงจัง", "happy": "😄 สนุก/ดีใจ"}

# อารมณ์ฉาก → กล้อง · ทรานซิชันเข้าฉาก · แฟลชตอนเปิด · เสียงเอฟเฟกต์ · โทนสี
MOOD_STYLE = {
    "hook": {"cam": ["punch"], "tr": "circleopen", "flash": True, "sfx": "whoosh"},
    "calm": {"cam": ["zoom_in", "pan_right", "pan_left"], "tr": "fade"},
    "info": {"cam": ["zoom_in", "pan_up", "pan_right"], "tr": "slideup"},
    "exciting": {"cam": ["pan_shake"], "tr": "slideleft", "sfx": "whoosh",
                 "color": "eq=contrast=1.08:saturation=1.15"},
    "shock": {"cam": ["punch_shake"], "tr": "fadewhite", "flash": True, "sfx": "hit",
              "color": "eq=contrast=1.12"},
    "sad": {"cam": ["zoom_out"], "tr": "fadeblack", "color": "eq=saturation=0.65:brightness=-0.03"},
    "happy": {"cam": ["pan_up", "zoom_in"], "tr": "smoothleft", "color": "eq=saturation=1.18:brightness=0.02"},
}


def _badges(v: dict) -> dict:
    """ป้ายวันที่/สถานที่ + คำพูดดัง จากคำตอบ AI (ตัดให้สั้น ไม่มีอีโมจิ)"""
    b = P.clean_text(str(v.get("badge") or ""))[:36]
    q = P.clean_text(str(v.get("quote") or "")).strip('"“”')[:40]
    amb = str(v.get("amb") or "").strip().lower()
    fx = str(v.get("fx") or "").strip().lower()
    return {"badge": b, "quote": q, "real": bool(v.get("real") or b),
            "amb": amb if amb in G.AMB else "", "fx": fx if fx in G.FX_NAMES else ""}


# AI ไม่ได้เลือกเสียงประกอบ → เดาจากคำในบท (ลำดับสำคัญ: ตัวแรกที่เจอชนะ)
AMB_RULES = [
    ("signal", r"สัญญาณ|วิทยุ|คลื่นวิทยุ|ดาวเทียม|เรดาร์|กล้องโทรทรรศน์|รหัสลับ|ข้อความจาก"),
    ("space", r"อวกาศ|ดวงดาว|ดาวเคราะห์|กาแล็กซี|จักรวาล|ดวงจันทร์|ดาวอังคาร|นักบินอวกาศ|มนุษย์ต่างดาว|เอเลี่ยน|ยูเอฟโอ|UFO"),
    ("war", r"สงคราม|สนามรบ|สนามเพลาะ|ทหาร|ระเบิด|ปืนใหญ่|กองทัพ|การรบ"),
    ("waves", r"ทะเล|มหาสมุทร|ชายหาด|คลื่น|เรือ|ใต้น้ำ|ฉลาม|วาฬ|เกาะ"),
    ("rain", r"ฝน|พายุ|ฟ้าผ่า|น้ำท่วม|มรสุม"),
    ("wind", r"หิมะ|หนาว|ขั้วโลก|ทะเลทราย|ภูเขาสูง|ยอดเขา|ลมแรง|น้ำแข็ง|คริสต์มาส"),
    ("fire", r"ไฟไหม้|เปลวไฟ|ภูเขาไฟ|กองไฟ|ลาวา|เผา"),
    ("clock", r"นาฬิกา|นับถอยหลัง|เวลาเหลือ|ทันเวลา|วินาทีสุดท้าย|หมดเวลา"),
    ("night", r"กลางคืน|เที่ยงคืน|ป่าลึก|ในป่า|ค่ำคืน"),
    ("magic", r"เวทมนตร์|ความฝัน|ฝันว่า|มหัศจรรย์|เทพนิยาย|ปาฏิหาริย์"),
    ("tension", r"ปริศนา|ลึกลับ|ไม่มีใครรู้|ไม่มีใครอธิบาย|หายตัว|ผี|สยอง|ฆาตกร|คดี|ความลับ|น่ากลัว"),
]


def guess_amb(text: str) -> str:
    for name, pat in AMB_RULES:
        if re.search(pat, text or "", re.I):
            return name
    return ""


def finish_sound(scenes: list[dict]) -> None:
    """ทุกฉากมีเสียงบรรยากาศ (ถ้าเข้ากัน) — ฉากที่ยังไม่ได้เลือก เดาจากบท / ใช้ของฉากก่อนหน้าถ้าเป็นเรื่องเดียวกัน"""
    prev = ""
    for s in scenes:
        if "amb" not in s or s.get("amb") is None:
            s["amb"] = guess_amb(s.get("narration", "")) or (prev if prev in ("space", "war", "waves", "wind", "night") else "")
        if not s.get("fx"):
            s["fx"] = ""
        prev = s.get("amb") or ""


def guess_mood(text: str, i: int, n: int) -> str:
    """AI ไม่ได้บอกอารมณ์ฉาก → เดาจากคำในบท"""
    t = text or ""
    if i == 0:
        return "hook"
    if re.search(r"ตกใจ|ช็อก|ไม่น่าเชื่อ|อันตราย|หักมุม|แต่แล้ว|ทันใดนั้น|ระเบิด|สยอง|น่ากลัว|เตือน", t):
        return "shock"
    if re.search(r"เศร้า|เสียใจ|สูญเสีย|เสียชีวิต|ร้องไห้|น่าเสียดาย|โศก|ล้มเหลว|เจ็บปวด", t):
        return "sad"
    if re.search(r"เร็ว|แข่ง|บุก|วิ่ง|สู้|มันส์|ระทึก|พุ่ง|ไล่ล่า|ทะยาน", t):
        return "exciting"
    if re.search(r"ดีใจ|สนุก|สำเร็จ|ชนะ|ยินดี|ตลก|ฮา|มีความสุข|ว้าว", t) or i == n - 1:
        return "happy"
    if re.search(r"\d", t):
        return "info"
    return "calm" if i % 2 else "info"


def clean_mood(v, text: str, i: int, n: int) -> str:
    v = str(v or "").strip().lower()
    return v if v in MOODS else guess_mood(text, i, n)


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


def finish_moods(scenes: list[dict]) -> None:
    for i, sc in enumerate(scenes):
        sc["mood"] = clean_mood(sc.get("mood"), sc.get("narration", ""), i, len(scenes))


def finish_graphics(scenes: list[dict]) -> None:
    finish_moods(scenes)
    finish_sound(scenes)
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
                    graphics: bool = True, extra: str = "", strict: bool = False, longform: bool = False) -> dict:
    """mode="verbatim": อ่านตามบทที่ใส่ทุกคำ (AI แค่คิดภาพ+หัวข้อ) · "rewrite": ให้ AI เรียบเรียงใหม่
    strict=True (ลิงก์โพสต์/ข่าว): AI แปลไม่สำเร็จ = แจ้งผิดพลาด ไม่เอาต้นฉบับภาษาอื่นมาพากย์ตรงๆ"""
    global GRAPHICS_ON, LAST_AI_ERROR
    GRAPHICS_ON = graphics
    LAST_AI_ERROR = ""
    text = text.strip()
    if len(text) < 10:
        raise RuntimeError("ข้อความสั้นเกินไป ใส่ข้อมูลอย่างน้อย 1-2 ประโยค")
    if longform:
        if provider == "none":
            raise RuntimeError("คลิปยาวต้องใช้ AI เขียนบท — เลือก Gemini (ฟรี) หรือ Claude")
        return make_long_plan(text, provider, target, extra)
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
    cta = plan.pop("cta", "")
    if cta and scenes and not re.search(r"คอมเมน|คอมเม้น|ติดตาม|กดไลก์|กดไลค์|กดแชร์", scenes[-1]["narration"]):
        # บทของผู้ใช้ไม่มีคำชวนคอมเมนต์ → เพิ่มฉากปิดท้ายสั้นๆ (ลบ/แก้ได้ในหน้าตรวจบท)
        last = scenes[-1]
        scenes.append({"narration": cta, "headline": "", "img": "", "image": last.get("image", ""),
                       "search": last.get("search", ""), "graphic": None, "mood": "happy", "cta": True})
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


LONG_PROMPT = """คุณเป็นนักเล่าเรื่องช่อง YouTube สารคดีภาษาไทยมืออาชีพ เขียนบทคลิปยาว (แนวนอน) ความยาวประมาณ {minutes} นาที จากข้อมูลด้านล่าง

ข้อกำหนด:
- บทพากย์รวมประมาณ {budget} ตัวอักษร (ไม่นับช่องว่าง) ขาด/เกินได้ไม่เกิน 10% — สำคัญ คลิปต้องยาวตามนี้
- แบ่งเป็น {chapters} บท (chapter) แต่ละบทมีชื่อสั้นๆ ไม่เกิน 20 ตัวอักษร เรียงเรื่องให้ลื่นไหล
- บทแรก "เปิดเรื่อง" ยาว 20-40 วินาที: ดึงความสนใจทันที (คำถาม/ข้อเท็จจริงที่น่าทึ่ง) แล้วบอกว่าคลิปนี้จะพาไปรู้อะไร โดยยังไม่เฉลย
- ทุก 1-2 นาที ใส่ประโยคดึงให้ดูต่อ เช่น "แต่เรื่องที่แปลกที่สุดยังไม่มา…" "และนี่คือจุดที่ทุกอย่างเปลี่ยนไป"
- เล่าแบบสารคดีที่สนุก ภาษาพูดเป็นธรรมชาติ มีจังหวะ ไม่ใช่อ่านรายงาน อธิบายบริบทให้คนที่ไม่รู้เรื่องเข้าใจ
- บทสุดท้าย: สรุปข้อคิด/คำถามที่ยังค้างคา แล้วชวนกดติดตามช่อง และคอมเมนต์ตอบคำถาม 1 ข้อ
- ยึดข้อเท็จจริงจากข้อมูลเท่านั้น ห้ามแต่งตัวเลข ชื่อ วันที่ หรือเหตุการณ์ ถ้าข้อมูลไม่พอ ให้ขยายด้วยการอธิบายบริบท/ความหมาย ไม่ใช่แต่งเพิ่ม
- ชื่อคน/สถานที่ภาษาอื่นให้ทับศัพท์ไทย ห้ามใส่อีโมจิหรือสัญลักษณ์ในบทพากย์
{extra}
ตอบ JSON อย่างเดียว:
{{"title": "ชื่อคลิป YouTube น่าคลิก ไม่เกิน 70 ตัวอักษร", "summary": "สรุปเรื่อง 1-2 ประโยค",
  "chapters": [{{"title": "ชื่อบท", "text": "บทพากย์ทั้งบท แบ่งย่อหน้าด้วยบรรทัดว่าง"}}]}}

ข้อมูล:
{text}"""


def make_long_plan(text: str, provider: str, target: float, extra: str = "") -> dict:
    """📺 คลิปยาว: AI เขียนบทเป็นบทๆ (chapter) → แบ่งฉากละ ~10-14 วิ → คิดภาพทีละชุด → ชื่อบทขึ้นจอตอนเปลี่ยนบท"""
    global LAST_AI_ERROR
    budget = speech_budget(target)
    chapters = max(4, min(9, round(target / 90)))
    data = None
    for limit in (30000, 14000):
        try:
            data = P._parse_json(P.ask_ai(provider, LONG_PROMPT.format(
                minutes=round(target / 60), budget=budget, chapters=chapters, extra=extra, text=text[:limit])))
            if data.get("chapters"):
                break
        except Exception as e:
            LAST_AI_ERROR = str(e)[:200]
            print("เขียนบทคลิปยาวไม่ได้:", e)
    chs = [c for c in (data or {}).get("chapters") or [] if isinstance(c, dict) and str(c.get("text") or "").strip()]
    if not chs:
        raise RuntimeError("AI เขียนบทคลิปยาวไม่สำเร็จ" + (f" ({LAST_AI_ERROR})" if LAST_AI_ERROR else "")
                           + " — ลองใหม่อีกครั้ง (ถ้าโควตา Gemini หมด รอหลังบ่าย 3 โมง)")
    scenes = []
    for ci, ch in enumerate(chs):
        body = P.clean_text(str(ch.get("text") or ""))
        body = re.sub(r"\n{3,}", "\n\n", str(ch.get("text") or "")).strip()
        parts = [P.clean_text(x) for x in split_script(body, max_len=150)]
        title = P.clean_text(str(ch.get("title") or ""))[:24]
        for k, narr in enumerate(x for x in parts if x):
            sc = {"narration": narr, "headline": "", "img": "", "image": "", "search": "", "chapter_no": ci}
            if k == 0:
                sc["chapter"] = title or f"บทที่ {ci + 1}"
            scenes.append(sc)
    plan = {"title": str(data.get("title") or "")[:90], "summary": str(data.get("summary") or ""),
            "scenes": scenes, "longform": True}
    for a in range(0, len(scenes), 18):  # คิดภาพทีละ 18 ฉาก (ทั้งเรื่องทีเดียว AI ตอบไม่ครบ)
        sub = {"title": plan["title"], "scenes": scenes[a:a + 18]}
        fill_visuals(sub, provider)
        if not plan["summary"]:
            plan["summary"] = sub.get("summary", "")
    for i, sc in enumerate(scenes):
        if not sc.get("image"):
            sc["image"], sc["generic"] = GENERIC_IMAGES[i % len(GENERIC_IMAGES)], True
        if sc.get("chapter") and sc["chapter_no"] > 0:  # ชื่อบทขึ้นจอ
            sc["graphic"] = {"type": "keyword", "text": f"{sc['chapter_no']}. {sc['chapter']}"[:30]}
    finish_graphics(scenes)
    got = sum(len(re.sub(r"\s", "", s["narration"])) for s in scenes)
    if got < budget * 0.6:
        plan["note"] = (f"บทที่ได้สั้นกว่าที่ตั้งไว้ (ราว {got / SPEECH_CPS / 60:.1f} นาที) เพราะข้อมูลมีไม่พอเล่ายาว — "
                        "ใส่ข้อมูลเพิ่ม/ลิงก์บทความ หรือเลือกหัวข้อที่มีเรื่องเล่าเยอะกว่า")
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
        data = _ask(provider, VISUAL_PROMPT.format(n=len(scenes), graphic_rules=_graphic_rules(), mood_rules=MOOD_RULES, badge_rules=BADGE_RULES, scenes="\n".join(
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
                s["mood"] = str(v.get("mood") or "")
                s.update(_badges(v))
        plan["title"] = str(data.get("title") or plan["title"])
        plan["summary"] = str(data.get("summary") or "")
        cta = P.clean_text(str(data.get("cta") or ""))[:90]
        if cta and thai_ratio(cta) > 0.5:
            plan["cta"] = cta
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
        prompt = STORY_PROMPT.format(target=int(target), n=n, text=text, graphic_rules=_graphic_rules(), mood_rules=MOOD_RULES, badge_rules=BADGE_RULES,
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
                               "graphic": G.clean(s.get("graphic"), narr), "mood": str(s.get("mood") or ""),
                               **_badges(s)})
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


def ai_variants(s: dict, i: int, scene_dir: Path, style: str, n: int, progress=None,
                tall: bool = False) -> tuple[list[str], bool]:
    """AI วาด n ภาพ (คนละแบบ) คืน (ชื่อไฟล์, วาดด้วย AI ได้ไหม)"""
    import random
    names, ai = [], True
    for k, p in enumerate(next_names(scene_dir, i, n)):
        if progress:
            progress(f"วาดภาพที่ {k + 1}/{n}")
        ai = imagegen.generate(s.get("image") or GENERIC_IMAGES[0], p, 1024, 1792 if tall else 1024, style,
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
    names = next_names(scene_dir, i, n + 3)
    real = bool(s.get("badge") or s.get("real"))  # ฉากเหตุการณ์/บุคคล/สถานที่จริง
    commons = []
    if lang == "en":  # ภาพจริงจาก Wikimedia Commons (ฉากเหตุการณ์จริงเอามาก่อน)
        commons = imagegen.commons_photos(query, names[n:n + (3 if real else 2)])
    try:
        got = imagegen.search_photos(query, names[:n], lang)
    except RuntimeError:
        if not commons:
            raise
        got = []
    if not got and not commons and lang == "en" and s.get("narration"):  # ภาษาอังกฤษไม่เจอ → ลองค้นภาษาไทยตรงๆ
        th = thai_keywords(s["narration"])
        if th:
            got = imagegen.search_photos(th, names[:n], "th")
    return [p.name for p in (commons + got if real else got[:1] + commons + got[1:])]


PICK_PROMPT = """You are a video editor choosing stock photos for a Thai short vertical video.
Story topic: {topic}
For each scene you get its Thai narration and several numbered candidate photos.
Pick the photo that best illustrates THAT scene's narration: the right subject, place and mood.
Prefer clear, relevant, good-looking photos. Avoid photos with big text/watermarks, or that contradict the narration.
order = photo numbers from best to worst. score 0-10 = how well your best pick matches (0 = nothing relevant).
Reply JSON only: {{"scenes": [{{"id": 1, "order": [2, 1, 3], "score": 7}}]}} with one item per scene."""


FIX_PROMPT = """An image was made for one scene of a Thai short video, but it does not show what the narration is about.
Narration (Thai): {narration}
Story topic: {topic}
Old image prompt: {old}
Write a NEW English image prompt (15-35 words) that makes the exact subject of the narration unmistakable:
name the specific object/creature/action as the main subject first, use a close-up or macro shot if it is small,
describe its shape, colour and where it is. Photo-realistic, no text. Also give 2-4 English stock-photo search words.
Reply JSON only: {{"image": "...", "search": "..."}}"""

REF_PROMPT = """The user uploaded a REFERENCE image showing roughly what they want for one scene of a Thai short video.
Scene narration (Thai): {narration}
Story topic: {topic}
Look at the reference and reply JSON only:
{{"desc": "one English sentence: what the reference shows (subject, framing, mood, style)",
 "image": "English image prompt, 15-35 words: the narration's subject shown the way the reference looks (framing, lighting, style). No text, no logos.",
 "search": "2-4 English words to find similar stock photos/videos"}}"""

FIT_OK = 6  # คะแนนความตรงขั้นต่ำ (0-10) ที่ยอมรับภาพ


def verify_images(plan: dict, scene_dir: Path, layout: str, style: str, progress,
                  only: list[int] | None = None, force: bool = False) -> int:
    """🧠 ตรวจภาพทุกฉากด้วย Gemini ว่าตรงบทไหม — ไม่ตรง (< 6/10) → หาภาพถ่ายจริง + เขียนคำสั่งวาดใหม่ให้ชัดขึ้น
    (Gemini วาด ถ้าคีย์ทำได้ ไม่งั้นวาดในเครื่อง) แล้วให้ AI เลือกภาพที่ตรงที่สุด  คืนจำนวนฉากที่เปลี่ยนภาพ"""
    if not vision_ready():
        return 0
    topic = plan.get("title") or ""
    scenes = plan["scenes"]
    changed = 0
    for i, s in enumerate(scenes):
        img = s.get("img") or ""
        if only is not None and i not in only:
            continue
        if not img or is_video(img) or img.startswith("anim_") or (s.get("img_locked") and not force):
            continue
        progress(i / len(scenes) * 100, f"🧠 ตรวจว่าภาพตรงบท ฉากที่ {i + 1}/{len(scenes)}")
        tmp = {"narration": s.get("narration", ""), "options": [img]}
        score = _rank_one(tmp, scene_dir, topic)
        if score is None:
            return changed  # AI ดูภาพไม่ได้ (โควตา/เน็ต) → หยุดตรวจ ใช้ภาพเดิม
        s["fit"] = score
        if score >= FIT_OK and not force:
            continue
        cands = [img] + [o for o in s.get("options") or [] if o != img]
        progress(i / len(scenes) * 100, f"🧠 ภาพฉากที่ {i + 1} ไม่ตรงบท ({score:g}/10) — กำลังหาภาพใหม่")
        try:  # 1) ภาพถ่ายจริง (มักตรงกว่าสำหรับของเฉพาะเจาะจง)
            cands += [o for o in photo_options(s, i, scene_dir, 4) if o not in cands]
        except Exception as e:
            print("หาภาพถ่ายไม่ได้:", e)
        try:  # 2) เขียนคำสั่งวาดใหม่ให้ชัดขึ้น แล้ววาดใหม่
            fix = P._parse_json(P._ask_gemini(FIX_PROMPT.format(narration=s.get("narration", ""), topic=topic,
                                                                old=s.get("image", ""))))
            if fix.get("image"):
                s["image"] = str(fix["image"])[:300]
                if fix.get("search"):
                    s["search"] = str(fix["search"])[:60]
                out = next_names(scene_dir, i, 1)[0]
                if imagegen.gemini_image(s["image"], out, tall=layout != "original"):
                    cands.insert(1, out.name)
                else:
                    names, ai = ai_variants(s, i, scene_dir, style, 1, tall=layout != "original")
                    if ai:
                        cands.insert(1, names[0])
        except Exception as e:
            print("วาดภาพใหม่ไม่ได้:", e)
        tmp = {"narration": s.get("narration", ""), "options": cands[:6]}
        best_score = _rank_one(tmp, scene_dir, topic)
        if best_score is not None and tmp["options"][0] != img:
            s["img"] = tmp["options"][0]
            s["fit"] = best_score
            changed += 1
        s["options"] = list(dict.fromkeys(tmp["options"] + cands))
    dedupe_images(plan, scene_dir)
    return changed


def from_reference(s: dict, i: int, scene_dir: Path, ref: Path, layout: str, style: str, topic: str = "",
                   want_video: bool = True, progress=None) -> list[str]:
    """🎯 รูปตัวอย่าง → หาภาพ/วิดีโอ "ประมาณนี้" ให้ฉาก: AI ดูรูปตัวอย่าง → คำสั่งวาด + คำค้น
    → Gemini วาดตามรูปตัวอย่าง + AI ในเครื่องวาด + ภาพถ่าย + วิดีโอฟรี → AI เลือกตัวที่ใกล้ที่สุด
    คืนรายชื่อไฟล์เรียงจากดีสุด (รูปตัวอย่างเองอยู่ท้ายสุด เผื่อจะใช้ตรงๆ)"""
    tall = layout != "original"
    say = progress or (lambda m: None)
    part = _thumb_part(ref)
    data = P._parse_json(P._ask_gemini(REF_PROMPT.format(narration=s.get("narration", ""), topic=topic),
                                       [part] if part else None))
    desc = str(data.get("desc") or "")[:200]
    if data.get("image"):
        s["image"] = str(data["image"])[:300]
    if data.get("search"):
        s["search"] = str(data["search"])[:60]
    cands: list[str] = []
    say("Gemini กำลังทำภาพตามรูปตัวอย่าง")
    try:
        out = next_names(scene_dir, i, 1)[0]
        if imagegen.gemini_image(s["image"], out, tall=tall, ref=ref):
            cands.append(out.name)
    except Exception as e:
        print("Gemini ทำภาพตามรูปตัวอย่างไม่ได้:", e)
    if imagegen.available():
        say("AI ในเครื่องกำลังวาด")
        try:
            names, ai = ai_variants(s, i, scene_dir, style, 1, tall=tall)
            if ai:
                cands += names
        except Exception as e:
            print("วาดในเครื่องไม่ได้:", e)
    say("ค้นภาพถ่ายที่คล้ายกัน")
    try:
        cands += [o for o in photo_options(s, i, scene_dir, 4) if o not in cands]
    except Exception as e:
        print("ค้นภาพถ่ายไม่ได้:", e)
    if want_video and imagegen.videos_available():
        say("ค้นวิดีโอที่คล้ายกัน")
        try:
            cands += [o for o in video_options(s, i, scene_dir, 3, s.get("search", "")) if o not in cands]
        except Exception as e:
            print("ค้นวิดีโอไม่ได้:", e)
    if len(cands) > 1:
        say("AI กำลังเลือกตัวที่ใกล้รูปตัวอย่างที่สุด")
        tmp = {"narration": f"{s.get('narration', '')}\n(The user wants it to look like: {desc})", "options": cands[:6]}
        fit = _rank_one(tmp, scene_dir, topic)
        cands = list(dict.fromkeys(tmp["options"] + cands))
        if fit is not None:
            s["fit"] = fit
    return cands


MATCH_PROMPT = """The user wrote a Thai short-video script and uploaded {n} REFERENCE images ("I want pictures like these").
Match the references to the scenes. For each scene give the number of the reference whose subject best fits
what that scene's narration talks about, or 0 if no reference fits. One reference may fit several scenes.
Try to use every reference at least once (put it on the scene it fits best), and one reference on at most 2 scenes.
Do not give a reference to a scene
about something clearly different.
Scenes:
{scenes}
Reply JSON only: {{"scenes": [{{"id": 1, "ref": 2}}]}} with one item per scene."""


def match_refs(scenes: list[dict], refs: list[Path], topic: str = "") -> dict[int, int]:
    """จับคู่รูปตัวอย่างกับฉาก → {ฉาก: ลำดับรูป}  (ไม่มีคีย์ Gemini → กระจายรูปตามลำดับเรื่อง)"""
    n = len(scenes)
    if not refs or not n:
        return {}
    spread = {min(n - 1, round(k * n / len(refs))): k for k in range(len(refs))}
    if not vision_ready():
        return spread
    parts = []
    for k, r in enumerate(refs, 1):
        img = _thumb_part(r)
        if img:
            parts += [{"text": f"Reference {k}:"}, img]
    lines = "\n".join(f"{i + 1}. {s.get('narration', '')[:200]}" for i, s in enumerate(scenes))
    try:
        data = P._parse_json(P._ask_gemini(MATCH_PROMPT.format(n=len(refs), scenes=lines), parts))
        out = {}
        for r in data.get("scenes") or []:
            i, k = int(r.get("id") or 0) - 1, int(r.get("ref") or 0) - 1
            if 0 <= i < n and 0 <= k < len(refs):
                out[i] = k
        for k in range(len(refs)):  # รูปที่ AI ไม่ได้ใช้ → ใส่ฉากที่ยังว่างใกล้ตำแหน่งตามลำดับ
            if k not in out.values():
                want = min(n - 1, round(k * n / len(refs)))
                free = sorted((i for i in range(n) if i not in out), key=lambda i: abs(i - want))
                if free:
                    out[free[0]] = k
        per: dict[int, int] = {}
        for i in sorted(out):  # รูปเดียวใช้ได้ไม่เกิน 2 ฉาก (ภาพเดิมยาวๆ น่าเบื่อ)
            per[out[i]] = per.get(out[i], 0) + 1
            if per[out[i]] > 2:
                del out[i]
        return out or spread
    except Exception as e:
        print("AI จับคู่รูปตัวอย่างไม่ได้:", e)
        return spread


def apply_refs(plan: dict, refs: list[Path], scene_dir: Path, layout: str, style: str, use: str,
               progress, want_video: bool = True) -> int:
    """🎯 รูปตัวอย่างที่ส่งมาพร้อมบท: จับคู่กับฉาก แล้ว
    use="direct" → ใช้รูปนั้นเป็นภาพฉากเลย / "similar" → ทำ/หาภาพใหม่ให้คล้ายรูป (รูปเดิมอยู่ในตัวเลือก)
    ฉากที่ได้รูปจะล็อกไว้ (AI ตรวจภาพ/แทรกวิดีโอไม่เปลี่ยนทับ) คืนจำนวนฉากที่ใช้รูปตัวอย่าง"""
    from PIL import Image
    scenes = plan["scenes"]
    scene_dir.mkdir(parents=True, exist_ok=True)
    progress(0, "🎯 AI กำลังจับคู่รูปตัวอย่างกับฉาก")
    pairs = match_refs(scenes, refs, plan.get("title") or "")
    topic = plan.get("title") or ""
    for m, (i, k) in enumerate(sorted(pairs.items())):
        s = scenes[i]
        copy = next_names(scene_dir, i, 1)[0]
        try:
            Image.open(refs[k]).convert("RGB").save(copy)
        except Exception as e:
            print("เปิดรูปตัวอย่างไม่ได้:", e)
            continue
        old = [o for o in s.get("options") or ([s["img"]] if s.get("img") else [])]
        names = [copy.name]
        if use != "direct" and vision_ready():
            progress(m / max(1, len(pairs)) * 100, f"🎯 ทำภาพฉากที่ {i + 1} ให้คล้ายรูปตัวอย่าง {k + 1} ({m + 1}/{len(pairs)})")
            try:
                got = from_reference(s, i, scene_dir, copy, layout, style, topic, want_video)
                names = [n for n in got if n != copy.name] + [copy.name]
            except Exception as e:
                print("ทำภาพตามรูปตัวอย่างไม่ได้:", e)
        s["img"] = names[0]
        s["options"] = list(dict.fromkeys(names + old))
        s["img_locked"] = True
        s["ref"] = k + 1
        s["ref_direct"] = names[0] == copy.name
    return len(pairs)


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
            data = P._parse_json(P._ask_gemini(PICK_PROMPT.format(topic=topic), parts, lite_first=True))
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


def _rank_one(tmp: dict, scene_dir: Path, topic: str) -> float | None:
    """เรียงตัวเลือกของฉากเดียว คืนคะแนนความตรงของตัวที่ดีที่สุด (None = AI ดูไม่ได้)"""
    opts = [o for o in tmp["options"] if (scene_dir / poster(o)).exists()][:6]
    parts = [{"text": f"Scene 1 narration (Thai): {tmp.get('narration', '')}"}]
    for m, o in enumerate(opts, 1):
        img = _thumb_part(scene_dir / poster(o))
        if img:
            parts += [{"text": f"Scene 1 - photo {m}:"}, img]
    try:
        data = P._parse_json(P._ask_gemini(PICK_PROMPT.format(topic=topic or tmp.get("narration", "")), parts, lite_first=True))
        r = (data.get("scenes") or [{}])[0]
        order = [int(x) - 1 for x in r.get("order") or []]
        best = [opts[x] for x in dict.fromkeys(order) if 0 <= x < len(opts)]
        tmp["options"] = best + [o for o in tmp["options"] if o not in best]
        return float(r.get("score") or 0)
    except Exception as e:
        print("AI ดูวิดีโอไม่ได้:", e)
        return None


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
        cur = s.get("img") if s.get("img") and (scene_dir / s["img"]).exists() else ""
        if vision_ready():
            # ให้ AI ดูวิดีโอเทียบกับภาพเดิมของฉาก: ใส่วิดีโอเฉพาะเมื่อตรงบทกว่าภาพเดิม และตรงจริง (คะแนน ≥ 6/10)
            tmp = {"narration": s.get("narration", ""), "options": vids + ([cur] if cur else [])}
            score = _rank_one(tmp, scene_dir, plan.get("title") or "")
            best = tmp["options"][0]
            others = [o for o in s.get("options") or [] if o not in tmp["options"]]
            s["options"] = tmp["options"] + others
            if score is None or not is_video(best) or score < 6:
                s["img"] = cur or best  # วิดีโอไม่ตรงพอ → คงภาพเดิม (วิดีโอยังอยู่ในตัวเลือก กดเลือกเองได้)
                continue
            s["img"] = best
        else:  # ไม่มีคีย์ Gemini ดูภาพไม่ได้ → แทรกเฉพาะฉากที่ไม่ใช่ฉากเปิด (กันภาพแรกไม่ตรงเรื่อง)
            s["options"] = vids + [o for o in s.get("options") or [] if o not in vids]
            if i == 0 and cur:
                continue
            s["img"] = vids[0]
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
        # ฉากเหตุการณ์/บุคคล/สถานที่จริง → ภาพจริง (Wikimedia Commons ก่อน) ดีกว่าให้ AI วาดหน้าคนจริง
        if (source == "photo" or s.get("generic") or s.get("real")) and not photo_err:
            progress(i / n * 100, f"หาภาพ{'จริง' if s.get('real') else 'ถ่าย'}ฉากที่ {i + 1}/{n}")
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
        names, ai = ai_variants(s, i, scene_dir, style, 1, lambda m: progress(i / n * 100, f"ฉากที่ {i + 1}/{n}: {m}"),
                                tall=layout != "original")
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
    dedupe_images(plan, scene_dir)
    auto = sum(1 for s in plan["scenes"] if s.get("auto_photo"))
    if auto:
        plan["note"] = ((plan.get("note") or "") + f" · AI คิดภาพไม่ได้ {auto} ฉาก จึงใช้ภาพถ่ายฟรีที่ค้นจากคำสำคัญในบทแทน — "
                        "ภาพไหนไม่ตรง กด 📷 ภาพถ่ายจริง เพื่อดูภาพอื่น หรือพิมพ์คำค้นเอง").strip(" ·")
    weak = [str(k + 1) for k, s in enumerate(plan["scenes"]) if s.get("weak_photo")]
    if weak:
        plan["note"] = ((plan.get("note") or "") + f" · AI ดูแล้วว่าฉาก {', '.join(weak)} ยังไม่มีภาพที่ตรงบทนัก "
                        "ลองพิมพ์คำค้นเอง หรือใช้ 📁 รูปของฉัน").strip(" ·")
    return ok


def _ahash(f: Path) -> int | None:
    """ลายนิ้วมือภาพ (8x8) — ไฟล์คนละชื่อแต่ภาพเดียวกันก็จับได้"""
    if f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp") or not f.exists():
        return None
    try:
        from PIL import Image
        px = list(Image.open(f).convert("L").resize((8, 8)).getdata())
        avg = sum(px) / 64
        return sum(1 << k for k, v in enumerate(px) if v > avg)
    except Exception:
        return None


def _same(a: int | None, b: int | None) -> bool:
    return a is not None and b is not None and bin(a ^ b).count("1") <= 6


def dedupe_images(plan: dict, scene_dir: Path, max_repeat: int = 1) -> int:
    """ฉากหลายฉากได้ภาพเดียวกัน (ค้นเจอภาพยอดนิยมซ้ำ / รูปตัวอย่างใช้หลายฉาก) → ภาพซ้ำยาวๆ น่าเบื่อ
    ฉากที่ซ้ำ: เปลี่ยนเป็นตัวเลือกถัดไปที่ยังไม่ซ้ำ  (ฉากที่ผู้ใช้ส่งรูปตัวอย่างแบบใช้ตรงๆ ซ้ำได้ max_repeat+1 ครั้ง)"""
    seen: list[int] = []
    count: dict[int, int] = {}
    changed = 0
    for s in plan["scenes"]:
        h = _ahash(scene_dir / s["img"]) if s.get("img") else None
        hit = next((x for x in seen if _same(x, h)), None)
        allow = max_repeat if s.get("ref_direct") else 0
        if hit is None or count.get(hit, 0) <= allow:
            if hit is None and h is not None:
                seen.append(h)
                hit = h
            if hit is not None:
                count[hit] = count.get(hit, 0) + 1
            continue
        for o in s.get("options") or []:
            ho = _ahash(scene_dir / o)
            if (scene_dir / o).exists() and (ho is None or not any(_same(x, ho) for x in seen)):
                s["img"] = o
                if ho is not None:
                    seen.append(ho)
                    count[ho] = 1
                changed += 1
                break
    return changed


# ───────────────────────── ตัดต่อ ─────────────────────────

LEAD, TAIL = 0.25, 0.45   # เว้นก่อน/หลังเสียงพากย์ในแต่ละฉาก
XF = 0.35                 # ความยาวทรานซิชัน
MOTIONS = ["zoom_in", "pan_right", "zoom_out", "pan_up"]
TRANSITIONS = ["fade", "slideleft", "slideup", "circleopen", "smoothleft"]


SECOND_SHOT = 4.5  # ฉากยาวกว่านี้ (วินาที) → ครึ่งหลังตัดเป็นมุมใกล้ (เปลี่ยนภาพทุก 2-4 วิ ตามจังหวะ Shorts)


def _motion(kind: str, W: int, H: int, D: float, color: str = "", full: bool = False,
            card: tuple[int, int] | None = None) -> str:
    """ภาพนิ่ง → กล้องเคลื่อนตามอารมณ์ฉาก → filter [0:v] → [mv]
    full=True: ภาพเต็มจอ · False: ภาพจัตุรัสกลางจอบนพื้นหลังเบลอของภาพเดียวกัน
    kind: zoom_in · zoom_out · pan_right/left/up/down · punch (กระชากซูมเข้า) · punch_shake (กระชาก+สั่น) · pan_shake (เลื่อน+สั่นเบาๆ)
    ฉากยาว > SECOND_SHOT วิ: ครึ่งหลังตัดไปมุมใกล้ (ซูม 1.35 เท่า) ให้ภาพเปลี่ยนระหว่างฉาก"""
    S = min(W, H)
    OW, OH = card or ((W, H) if full else (S, S))
    D3 = f"{D:.3f}"
    u = f"(t/{D3})"
    # z = ซูม (≥1) · cx, cy = ตำแหน่งกล้อง 0..1 ของพื้นที่ที่เหลือ · sx, sy = สั่น (พิกเซล)
    sx = sy = "0"
    if kind == "zoom_out":
        z, cx, cy = f"(1.12-0.12*{u})", "0.5", "0.5"
    elif kind in ("pan_right", "pan_left"):
        z, cy = "1.14", "0.5"
        cx = u if kind == "pan_right" else f"(1-{u})"
    elif kind in ("pan_up", "pan_down"):
        z, cx = "1.14", "0.5"
        cy = f"(1-{u})" if kind == "pan_up" else u
    elif kind in ("punch", "punch_shake"):
        z, cx, cy = f"(1.06+0.12*min(t/0.3,1)+0.04*{u})", "0.5", "0.5"
        if kind == "punch_shake":
            sx, sy = "22*sin(t*47)*max(0,1-t/0.8)", "22*cos(t*41)*max(0,1-t/0.8)"
    elif kind == "pan_shake":
        z, cx, cy = "1.18", f"(0.15+0.7*{u})", "0.5"
        sx, sy = "5*sin(t*23)", "5*sin(t*17)"
    else:  # zoom_in
        z, cx, cy = f"(1+0.10*{u})", "0.5", "0.5"
    if D > SECOND_SHOT:  # มุมที่ 2: ตัดไปภาพใกล้ช่วงครึ่งหลัง แล้วซูมช้าๆ ต่อ
        M = f"{D * 0.5:.3f}"
        z = f"if(lt(t,{M}),{z},1.35+0.05*(t-{M})/{D - D * 0.5:.3f})"
        cx = f"if(lt(t,{M}),{cx},0.5)"
        cy = f"if(lt(t,{M}),{cy},0.40)"  # ค่อนขึ้นบน (หน้าคน/ตัวเด่นมักอยู่ช่วงบน)
    fg = (f"scale={OW}:{OH}:force_original_aspect_ratio=increase,crop={OW}:{OH},setsar=1,"
          f"scale=w='{OW}*{z}':h=-2:eval=frame,"
          f"crop={OW}:{OH}:x='clip((iw-{OW})*{cx}+{sx},0,iw-{OW})':y='clip((ih-{OH})*{cy}+{sy},0,ih-{OH})'")
    if color:
        fg += "," + color
    if card:
        return fg
    if full:
        return f"[0:v]{fg},setsar=1[mv]"
    y = (H - S) // 2 - (60 if H > W else 0)
    bg = (f"[b0]scale=270:270,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
          f"boxblur=10:2,eq=brightness=-0.18:saturation=1.2,setsar=1[bg]")
    return f"[0:v]split[b0][f0];{bg};[f0]{fg}[fg];[bg][fg]overlay=(W-w)/2:{y}[mv]"


PAPER, GRID = "0xF4F0E6", "0xE4DED1"
CARD_PAD = 16


def card_geom(img: Path, W: int, H: int, left: bool = False) -> tuple[int, int, int, int]:
    """สไตล์การ์ดสารคดี: ขนาด/ตำแหน่งภาพในการ์ด (cw, ch, x, y) ตามสัดส่วนภาพจริง"""
    r = 16 / 9
    try:
        if is_video(img.name):
            info = P.probe(img)
            r = float(info["width"]) / float(info["height"])
        else:
            from PIL import Image
            with Image.open(img) as im:
                r = im.width / im.height
    except Exception:
        pass
    if H > W:  # แนวตั้ง: การ์ดกว้างเกือบเต็มจอ ช่วงบน (ซับอยู่ล่าง) · ภาพแนวตั้งครอปเป็นจัตุรัส
        r = max(r, 1.0)
        cw = int(W * 0.86)
        ch = int(min(max(cw / r, cw * 9 / 16), H * 0.38))
        cw = int(min(cw, ch * r)) if ch >= H * 0.38 else cw
        y = int(H * 0.33 - ch / 2)
    else:
        ch = int(H * 0.68)
        cw = int(min(ch * r, W * 0.62))
        ch = int(min(ch, cw / r))
        y = int(H * 0.44 - ch / 2)
    cw, ch = cw // 2 * 2, ch // 2 * 2
    if left and W > H:  # แนวนอน + มีกราฟิกมุมขวา → การ์ดชิดซ้าย ไม่ทับกัน
        return cw, ch, int(W * 0.05), y
    return cw, ch, (W - cw) // 2, y


def _card_layout(img: Path, kind: str, W: int, H: int, D: float, color: str, video: bool, left: bool = False) -> str:
    """พื้นกระดาษตาราง + ภาพ/วิดีโอในการ์ดขาวมีเงา เลื่อนขึ้นมาตอนเปิดฉาก แล้วลอยเบาๆ → [mv]"""
    cw, ch, x, y = card_geom(img, W, H, left)
    b = CARD_PAD
    if video:
        media = f"setpts=PTS-STARTPTS,scale={cw}:{ch}:force_original_aspect_ratio=increase,crop={cw}:{ch},setsar=1"
    else:
        media = _motion(kind, W, H, D, color, card=(cw, ch))
    fy = f"{y - b}+max(0,0.35-t)*700+5*sin(t*1.4)"
    return (f"color=c={PAPER}:s={W}x{H}:r=30:d={D:.3f},drawgrid=w=48:h=48:t=2:c={GRID},format=rgba[pp];"
            f"[0:v]{media},pad={cw + 2 * b}:{ch + 2 * b}:{b}:{b}:color=white,format=rgba,split[c1][c2];"
            f"[c2]colorchannelmixer=rr=0:rg=0:rb=0:gr=0:gg=0:gb=0:br=0:bg=0:bb=0:aa=0.32,"
            f"pad=iw+60:ih+60:30:30:color=black@0,boxblur=14:2[sh];"
            f"[pp][sh]overlay=x={x - b - 30 + 10}:y='{fy}-30+16':format=auto[p1];"
            f"[p1][c1]overlay=x={x - b}:y='{fy}':format=auto,format=yuv420p[mv]")


def full_frame_ok(img: Path, W: int, H: int) -> bool:
    """ใช้ภาพเต็มจอได้ไหม: จอแนวตั้ง + ภาพแนวตั้งหรือจัตุรัส (ภาพแนวนอนกว้างๆ ครอปแล้วเสียเนื้อหามาก → ใช้แบบมีขอบเบลอ)"""
    if W >= H:
        return True
    try:
        from PIL import Image
        with Image.open(img) as im:
            w, h = im.size
        return w / max(1, h) <= 1.1
    except Exception:
        return False


def scene_style(scene: dict, i: int) -> dict:
    mood = scene.get("mood") if scene.get("mood") in MOOD_STYLE else "calm"
    st = MOOD_STYLE[mood]
    return {**st, "mood": mood, "cam": st["cam"][i % len(st["cam"])]}


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
                 layout: str, subtitles: bool, extras: bool, brand: dict | None, sfx: bool = True,
                 frame: str = "full", less_text: bool = True, ambience: bool = True,
                 sound_dir: Path | None = None) -> float:
    W, H = size_for(layout)
    vertical = H > W
    nd = P.probe(narr)["duration"] if narr else 0.0
    D = max(2.5, nd + LEAD + TAIL)
    video = is_video(img.name)
    sty = scene_style(scene, i)
    anim = img.name.startswith("anim_")  # ฉากแอนิเมชันกราฟิก (ไม่มีภาพจริง): พื้นหลังเต็มจอลอยช้าๆ
    if anim:
        motion = (f"[0:v]crop={W}:{H}:x='(iw-{W})/2+(iw-{W})/2*sin(t*0.5)':"
                  f"y='(ih-{H})/2+(ih-{H})/2*cos(t*0.4)',setsar=1[mv]")
    elif frame == "card":
        g_on = bool(extras and scene.get("graphic") and not scene["graphic"].get("off"))
        motion = _card_layout(img, sty["cam"], W, H, D, sty.get("color", ""), video, g_on)
    else:
        full = frame == "full" and full_frame_ok(img, W, H)
        motion = _video_layout(img, W, H) if video else _motion(sty["cam"], W, H, D, sty.get("color", ""), full)
    vf = ["fps=30"]
    if sty.get("flash") and extras:  # เปิดฉากด้วยแฟลชขาว (ฉากเปิด/ช็อก)
        vf.append("fade=t=in:st=0:d=0.22:color=white")

    # ข้อความไทยทั้งหมด (หัวข้อ, ชื่อช่อง, ซับ) วาดด้วย libass ให้สระ/วรรณยุกต์ถูกตำแหน่ง
    ass = P.Ass(W, H)
    head = (scene.get("headline") or "").strip() if extras else ""
    # ตัวหนังสือน้อย: มีซับแล้ว → ไม่ใส่ป้ายหัวข้อ/ป้ายคำเด่นซ้ำ (เหลือซับ + กราฟิกตัวเลข/รายการที่ให้ข้อมูลเพิ่ม)
    sub_on = bool(subtitles and narr and scene.get("narration"))
    if less_text and sub_on and not anim:
        head = ""
    kin_cues = []
    pcard = img.parent / scene["product_img"] if anim and extras and scene.get("product_img") else None
    if pcard is not None and not pcard.exists():
        pcard = None
    gfx = scene.get("graphic")
    if less_text and sub_on and gfx and gfx.get("type") == "keyword":
        gfx = None
    has_g = bool(extras and gfx and not gfx.get("off"))
    studio = bool(pcard is not None and scene.get("studio"))
    if head and anim:  # ตัวหนังสือใหญ่เด้งกลางจอ + รูปทรงลอย (มีรูปสินค้า → ย้ายข้อความขึ้นบน)
        kin_cues = G.kinetic(ass, head, 0, D, i, cy=(0.15 if pcard is not None else None),
                             shapes=not studio)
    elif head:
        ass.headline(P._wrap(head, 16 if vertical else 30), 0, D, int(H * (0.105 if vertical else 0.07)))
    if extras and not anim and (scene.get("badge") or scene.get("quote")):
        # ป้ายวันที่·สถานที่ (เหลือง มุมล่างซ้ายของภาพ) + คำพูดดัง (ส้ม บนภาพ) — แบบคลิปสารคดี
        if frame == "card":
            cw, ch, cx0, cy0 = card_geom(img, W, H, bool(gfx and not gfx.get("off")))
        else:
            cw, ch, cx0, cy0 = W - 80, int(H * (0.5 if vertical else 0.8)), 40, int(H * (0.16 if vertical else 0.08))
        u = min(W, H) / 1080 * (1.0 if vertical else 1.25)
        if scene.get("badge"):
            ass.events.append(f"Dialogue: 2,{P._ass_time(0.45)},{P._ass_time(D)},GBox,,0,0,0,,"
                              f"{{\\an4\\pos({cx0 + int(28 * u)},{cy0 + ch - int(20 * u)})\\fs{int(34 * u)}\\bord{int(12 * u)}"
                              f"\\fscx60\\fscy60\\t(0,160,\\fscx100\\fscy100)\\fad(150,200)}}{P.ass_text(scene['badge'])}")
        if scene.get("quote"):
            ass.events.append(f"Dialogue: 2,{P._ass_time(0.8)},{P._ass_time(D)},Head,,0,0,0,,"
                              f"{{\\an5\\pos({W // 2},{cy0 + int(20 * u)})\\fs{int(44 * u)}\\frz2"
                              f"\\fscx50\\fscy50\\t(0,180,\\fscx108\\fscy108)\\t(180,300,\\fscx100\\fscy100)\\fad(150,200)}}"
                              f"“{P.ass_text(scene['quote'])}”")
    if studio and not has_g:  # ประกายวิ้งๆ รอบสินค้า
        G.sparkles(ass, 0.6, D, W / 2, H * 0.47, W * 0.3, i)
    if has_g:  # โมชันกราฟิกช่วยให้เข้าใจ
        # ฉากสตูดิโอ: กรอบกราฟิกอยู่เหนือสินค้า (สินค้าวางบนแท่นด้านล่าง)
        cues = G.render(ass, gfx, min(0.4, D / 4) + (0.5 if kin_cues else 0), D - 0.2,
                        bottom=0.47 if studio and vertical else 0.70 if frame == "card" else 0.69)
    else:
        cues = []
    if sty.get("sfx") and extras:  # เสียงเอฟเฟกต์ตามอารมณ์ฉาก (ฟิ้ว/ตึง) ตอนเปิดฉาก
        cues = [(0.02, sty["sfx"])] + cues
    fx = scene.get("fx") or ""
    if ambience and fx in G.FX_NAMES:  # เสียงประกอบที่ AI เลือกตามเนื้อหา
        if fx == "boom":
            cues = [c for c in cues if c[1] != "hit"]  # ไม่ซ้อนกับเสียงตึงของอารมณ์ช็อก
        cues.append((0.12 if fx != "riser" else max(0.1, D - 1.7), fx))
    elif frame == "card" and extras and not anim:  # การ์ดเลื่อนขึ้นมา = เสียงฟิ้วเบาๆ
        cues = [(0.02, "whoosh")] + cues
    if extras and not anim and scene.get("quote") and D > 1.5:
        cues = cues + [(0.8, "pop")]
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
    msc = None
    if extras and brand.get("mascot_pack") and "*" not in brand["mascot_pack"]:  # ชุดมาสคอต: ท่าตามอารมณ์ฉาก โผล่ที่มุมจอทุกฉาก
        import mascot as MS
        msc = MS.pick(brand["mascot_pack"], sty["mood"], i)
    if msc is not None:
        mf, mxy = MS.scene_overlay(msc, W, H, brand.get("mascot_pos", "top_right"), i)
        inputs += ["-loop", "1", "-t", f"{D:.3f}", "-i", str(msc)]; im_ = n_in; n_in += 1
        last = parts[-1]
        parts[-1] = last[:last.rindex("[v]")] + "[v0]"
        parts.append(f"[{im_}:v]{mf}[msc];[v0][msc]overlay={mxy}:shortest=1:format=auto,format=yuv420p[v]")
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
    bed = None
    amb = scene.get("amb") or ""
    if ambience and amb:  # เสียงบรรยากาศเบาๆ คลอทั้งฉาก
        try:
            if amb.startswith("file:") and sound_dir:
                f = sound_dir / amb[5:]
                bed = (f, 0.5) if f.is_file() else None
            else:
                f = G.make_amb(workdir, amb)
                bed = (f, 0.75) if f else None
        except Exception as e:
            print("ทำเสียงบรรยากาศไม่ได้:", str(e)[-200:])
    sounds = {}
    if (sfx or ambience) and cues:
        try:
            sounds = G.make_sfx(workdir)
        except Exception as e:
            print("ทำเสียงเอฟเฟกต์กราฟิกไม่ได้:", str(e)[-200:])
    if not sfx:  # ปิดเสียงเอฟเฟกต์กราฟิก → เหลือเฉพาะเสียงประกอบที่ AI เลือก
        cues = [c for c in cues if c[1] == fx]
    if sounds or bed:
        # เสียงเอฟเฟกต์เบาๆ ตามจังหวะกราฟิก — ทุกเส้น apad ยาวไม่จำกัด ให้ amix หารเท่ากันตลอด แล้วคูณกลับ
        idx = {}
        labels = []
        if sounds:
            for name in dict.fromkeys(n for _, n in cues):
                inputs += ["-i", str(sounds[name][0])]; idx[name] = n_in; n_in += 1
            for k, (t, name) in enumerate(cues):
                ms = int(t * 1000)
                parts.append(f"[{idx[name]}:a]{norm},volume={sounds[name][1]:.2f},adelay={ms}|{ms},apad[fx{k}]")
                labels.append(f"[fx{k}]")
        if bed:
            inputs += ["-stream_loop", "-1", "-i", str(bed[0])]
            parts.append(f"[{n_in}:a]{norm},atrim=0:{D:.3f},volume={bed[1]:.2f},"
                         f"afade=t=in:st=0:d=0.5,afade=t=out:st={max(0, D - 0.5):.3f}:d=0.5,apad[bed]")
            n_in += 1
            labels.append("[bed]")
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


def join_xfade(files: list[Path], durs: list[float], out: Path, workdir: Path,
               trans: list[str] | None = None) -> None:
    """ต่อฉากด้วยทรานซิชัน (ถ้าไม่ได้ ใช้ต่อธรรมดา) — คลิปยาวหลายสิบฉาก: ต่อทีละชุด 20 ฉาก แล้วต่อชุดเข้าด้วยกัน
    (เปิดทุกฉากพร้อมกันใน ffmpeg ตัวเดียว หน่วยความจำไม่พอ)"""
    if len(files) > 24:
        groups = []
        for g, a in enumerate(range(0, len(files), 20)):
            gf = workdir / f"group_{g:02}.mp4"
            _join_xfade(files[a:a + 20], durs[a:a + 20], gf, workdir, (trans or [])[a:a + 20] or None)
            groups.append(gf)
        P.concat(groups, out, workdir)
        return
    _join_xfade(files, durs, out, workdir, trans)


def _join_xfade(files: list[Path], durs: list[float], out: Path, workdir: Path,
                trans: list[str] | None = None) -> None:
    if len(files) == 1:
        P.concat(files, out, workdir)
        return
    inputs, parts = [], []
    for f in files:
        inputs += ["-i", f.name]
    vlast, alast, off = "[0:v]", "[0:a]", 0.0
    for k in range(1, len(files)):
        off += durs[k - 1] - XF
        tr = (trans[k] if trans and k < len(trans) and trans[k] else TRANSITIONS[(k - 1) % len(TRANSITIONS)])
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


def ai_animate(scenes: list[dict], scene_dir: Path, progress) -> dict:
    """🤖 ให้ AI (การ์ดจอ) ขยับภาพนิ่งทุกฉากให้เป็นวิดีโอสั้น วนลูปได้ — เก็บไว้ใช้ซ้ำตอนตัดต่อใหม่
    คืน {ลำดับฉาก: ไฟล์วิดีโอ}  ทำไม่ได้ → ฉากนั้นใช้ภาพนิ่ง + กล้องตามอารมณ์แทน"""
    import motion as MO
    if not MO.ai_available():
        P.TTS_NOTES.append("ไม่พบการ์ดจอ NVIDIA — ข้าม AI ขยับภาพ ใช้กล้องเคลื่อนตามอารมณ์ฉากแทน")
        return {}
    todo = [(i, s) for i, s in enumerate(scenes)
            if s.get("img") and not is_video(s["img"]) and not s["img"].startswith("anim_")]
    out, fails = {}, 0
    strength = {"calm": "soft", "sad": "soft", "info": "soft", "exciting": "strong", "shock": "strong"}
    try:
        for k, (i, s) in enumerate(todo):
            src = scene_dir / s["img"]
            mv = scene_dir / f"{src.stem}_aimove_{s.get('mood', 'calm')}.mp4"
            if not mv.exists():
                def prog(m, k=k, i=i):
                    progress(30, f"🤖 AI ขยับภาพฉากที่ {i + 1} ({k + 1}/{len(todo)}): {m}")
                try:
                    img, (w, h) = MO.load(src, "original")
                    MO.ai_video(img, mv, w, h, 3.0, strength.get(s.get("mood"), "normal"), True, prog)
                except Exception as e:
                    fails += 1
                    mv.unlink(missing_ok=True)
                    print(f"AI ขยับภาพฉาก {i + 1} ไม่สำเร็จ:", str(e)[-300:])
                    if fails >= 2 and not out:  # พังติดกัน (การ์ดจอ/หน่วยความจำ) → เลิกลอง
                        break
                    continue
            out[i] = mv
    finally:
        MO.release_ai()  # คืนการ์ดจอให้ขั้นตัดต่อ
    if fails:
        P.TTS_NOTES.append(f"AI ขยับภาพไม่สำเร็จ {fails} ฉาก — ฉากเหล่านั้นใช้กล้องเคลื่อนตามอารมณ์แทน")
    return out


def render_story(plan: dict, scene_dir: Path, workdir: Path, out: Path, *, voice: str, rate: int,
                 layout: str, subtitles: bool, progress, brand: dict | None = None,
                 cover: Path | None = None, clean: bool = False, style: str = "cinematic",
                 tone: str = "story", sfx: bool = True, ai_motion: bool = False,
                 frame: str = "full", less_text: bool = True, ambience: bool = True,
                 sound_dir: Path | None = None) -> list[Path]:
    scene_dir, workdir, out = scene_dir.resolve(), workdir.resolve(), out.resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    scenes = plan["scenes"]
    if not scenes:
        raise RuntimeError("ไม่มีฉากให้ตัดต่อ")
    missing = [s for s in scenes if not s.get("img") or not (scene_dir / s["img"]).exists()]
    if missing:  # ฉากที่เพิ่มใหม่/ภาพหาย → วาดก่อน
        draw_images(plan, scene_dir, layout, style, lambda p, m: progress(0, m))
    n, files, durs = len(scenes), [], []
    finish_moods(scenes)  # ทุกฉากต้องมีอารมณ์ (กำหนดกล้อง/ทรานซิชัน/เสียงให้เข้ากับเนื้อหา)
    finish_sound(scenes)
    texts = [P.clean_text(s.get("narration", "")) for s in scenes]
    narrs = P.tts_all(texts, workdir, voice, rate, tone, progress, total=30)
    moving = ai_animate(scenes, scene_dir, progress) if ai_motion else {}
    for i, s in enumerate(scenes):
        text, narr = texts[i], narrs[i]
        progress(30 + (i + 0.5) / n * 65, f"ทำแอนิเมชันฉากที่ {i + 1}/{n} ({MOODS.get(s.get('mood'), '')})")
        f = workdir / f"scene_{i:03}.mp4"
        sc = {**s, "narration": text}
        src = moving.get(i) or scene_dir / s["img"]
        try:
            d = render_scene(src, sc, i, narr, f, workdir, layout, subtitles,
                             not clean, None if clean else brand, sfx=sfx and not clean,
                             frame=frame, less_text=less_text, ambience=ambience and not clean,
                             sound_dir=sound_dir)
        except RuntimeError as e:  # ฟอนต์/ซับมีปัญหา → ทำแบบไม่มีตัวหนังสือ
            print("ทำฉากแบบเต็มไม่สำเร็จ ลองแบบไม่มีตัวหนังสือ:", str(e)[-300:])
            d = render_scene(src, sc, i, narr, f, workdir, layout, False, False, None, frame=frame)
        files.append(f)
        durs.append(d)
    progress(97, "ต่อฉากพร้อมทรานซิชัน")
    t = 0.0
    for k, s in enumerate(scenes):  # เวลาเริ่มของแต่ละฉาก (ไทม์สแตมป์บทในคำอธิบาย YouTube)
        s["t"] = round(t, 1)
        t += durs[k] - (XF if k < len(scenes) - 1 else 0)
    joined = workdir / "joined.mp4"
    join_xfade(files, durs, joined, workdir, [scene_style(s, i)["tr"] for i, s in enumerate(scenes)])
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
