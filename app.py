"""
เว็บแอปสรุปคลิปวิดีโอ + ตัดต่อ + พากย์เสียงไทย
รัน:  python app.py   แล้วเปิด http://localhost:8000
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import shutil
import threading
import time
import traceback
import urllib.parse
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Route

BASE = Path(__file__).resolve().parent

# โหลดค่าจากไฟล์ .env (ถ้ามี) แบบง่ายๆ
env_file = BASE / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))

import pipeline as P  # noqa: E402 (ต้องโหลด .env ก่อน)
import game as G  # noqa: E402
import imagegen  # noqa: E402
import story as ST  # noqa: E402
import voice as V  # noqa: E402
import graphics as G2  # noqa: E402
import source as SRC  # noqa: E402
import product as PR  # noqa: E402

JOBS_DIR = Path(os.environ.get("JOBS_DIR", BASE / "jobs")).resolve()
JOBS_DIR.mkdir(parents=True, exist_ok=True)


APP_PIN = (os.environ.get("APP_PIN") or "").strip()
PIN_TOKEN = hashlib.sha256(f"sc-{APP_PIN}".encode()).hexdigest()[:40] if APP_PIN else ""

executor = ThreadPoolExecutor(max_workers=1)  # ทำทีละงาน ไม่ให้เครื่องอืด
jobs: dict[str, dict] = {}
lock = threading.Lock()


def job_dir(jid: str) -> Path:
    return JOBS_DIR / jid


class JobCancelled(Exception):
    pass


def save(jid: str, **changes) -> None:
    # ผู้ใช้กดยกเลิก → หยุดงานตรงจุดรายงานความคืบหน้าถัดไป
    if jobs.get(jid, {}).get("cancel") and not ({"status", "capcut", "preview_progress", "cancel"} & changes.keys()):
        raise JobCancelled()
    with lock:  # มีหลายเธรดเขียนพร้อมกัน (ถอดเสียง + วิดีโอตัวอย่าง)
        jobs[jid].update(changes, updated=time.time())
        f = job_dir(jid) / "job.json"
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(jobs[jid], ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(f)


def load_existing() -> None:
    for f in JOBS_DIR.glob("*/job.json"):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if j.get("status") in ("queued", "analyzing", "rendering"):
            j.update(status="error", message="งานถูกหยุดเพราะปิดโปรแกรมระหว่างทำ")
        if (j.get("capcut") or {}).get("status") == "working":
            j["capcut"] = {"status": "error", "message": "ถูกหยุดกลางทาง ลองส่งออกใหม่"}
        jobs[j["id"]] = j


def provider_available(p: str) -> bool:
    if p == "claude":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    if p == "gemini":
        return bool(os.environ.get("GEMINI_API_KEY"))
    if p == "ollama":
        try:
            import urllib.request
            urllib.request.urlopen(f"{P.OLLAMA_URL}/api/tags", timeout=1.5)
            return True
        except Exception:
            return False
    return True


# ───────────────────────── งานเบื้องหลัง ─────────────────────────

def fail_job(jid: str, e: Exception) -> None:
    if isinstance(e, JobCancelled):
        save(jid, status="cancelled", message="ยกเลิกแล้ว", cancel=False)
        return
    traceback.print_exc()
    save(jid, status="error", message=P.error_text(e), detail=traceback.format_exc()[-1500:])


def do_analyze(jid: str) -> None:
    d, j = job_dir(jid), jobs[jid]
    if j.get("status") == "cancelled":
        return
    try:
        if j["opts"].get("mode") == "story":
            plan = analyze_story(jid)
            finish_analyze(jid, plan)
            return
        if j.get("url") and not j.get("source"):
            save(jid, status="analyzing", step="download", progress=0, message="กำลังอ่านข้อมูลจากลิงก์")
            path, title = P.download_url(j["url"], d, lambda pct, msg: save(
                jid, step="download", progress=pct, message=msg))
            save(jid, source=path.name, name=title)
        src = d / j["source"]
        info = P.probe(src)
        if not info["has_video"]:
            raise RuntimeError("ไฟล์นี้ไม่มีภาพวิดีโอ")
        save(jid, status="analyzing", duration=info["duration"],
             step="extract", progress=2, message="แยกเสียงจากวิดีโอ")
        # วิดีโอตัวอย่างใช้แค่ในหน้าตรวจบท → โหมดอัตโนมัติไม่ต้องทำ
        # และทำคู่ขนานไปกับการถอดเสียง ไม่ต้องรอ
        if not j["opts"].get("auto") and P.needs_preview(info):
            threading.Thread(target=build_preview, args=(jid, src, info["duration"]),
                             daemon=True).start()
        if j["opts"].get("mode") == "game":
            plan = analyze_game(jid, src, info)
        else:
            plan = analyze_talk(jid, src, info)
        finish_analyze(jid, plan)
    except Exception as e:
        fail_job(jid, e)
    finally:
        if j.get("batch"):
            check_batch(j["batch"])


def finish_analyze(jid: str, plan: dict) -> None:
    j = jobs[jid]
    if j["opts"].get("auto"):
        save(jid, plan=plan, render_opts=j["opts"]["render"], status="rendering",
             step="render", progress=0, message="เริ่มตัดต่ออัตโนมัติ")
        do_render(jid)
        return
    save(jid, plan=plan, status="review", step="review", progress=100,
         message="วิเคราะห์เสร็จ รอรวมคลิป" if j["opts"].get("batch_hold") else "พร้อมให้ตรวจบทพากย์")


def analyze_product(jid: str) -> dict:
    d, j = job_dir(jid), jobs[jid]
    o = j["opts"]
    media, shots, pimg = PR.move_uploads(Path(o.get("upload_dir") or ""), d / "product_files")
    save(jid, status="analyzing", step="plan", progress=5,
         message="AI กำลังเขียนบทป้ายยา" + (" (อ่านภาพหน้าจอสินค้าด้วย)" if shots else ""))
    plan = PR.make_product_plan(o["product_info"], o["provider"], o["target_seconds"], shots,
                                graphics=o.get("graphics", True))
    save(jid, plan=plan, step="images", progress=30, message=f"ได้บท {len(plan['scenes'])} ฉาก — ใส่รูป/วิดีโอสินค้า")
    visual = o["product_info"].get("visual") or ("media" if media else "anim")
    if visual == "shots" and shots:  # ผู้ใช้เลือกใช้ภาพหน้าจอร้านในคลิปเอง (ภาพของร้านค้า)
        media = media + shots
    used = PR.add_media(plan, media, d / "scenes", lambda m: save(jid, step="images", progress=40, message=m)) \
        if visual != "anim" else 0
    if not used and visual in ("anim", "media", "shots"):  # ไม่มีสินค้าจริง → แอนิเมชันกราฟิกทั้งคลิป
        save(jid, step="images", progress=60, message="สร้างฉากแอนิเมชัน")
        (d / "scenes").mkdir(parents=True, exist_ok=True)
        card = d / "scenes" / "prodcard.png"
        pb = plan.get("product_box")
        if o["product_info"].get("use_img", "1") != "0":  # รูปสินค้าลอยในแอนิเมชัน (ไฟล์ที่ผู้ใช้ให้ หรือ AI ตัดจากภาพหน้าจอ)
            want = o["product_info"].get("img_style") or "studio"
            style = "sticker" if want == "studio" else want  # สตูดิโอ = ตัดพื้นหลังแล้ววางบนแท่น
            save(jid, step="images", progress=55,
                 message="AI กำลังจัดฉากถ่ายสินค้าใหม่" if style == "restage" else "กำลังตัดพื้นหลังรูปสินค้า")
            got = ""
            if pimg:
                got = PR.product_card(pimg, card, None, style)
            elif pb and shots and 1 <= pb["shot"] <= len(shots):
                got = PR.product_card(shots[pb["shot"] - 1], card, pb["box"], style)
            if got:
                msg = {"sticker": "ตัดพื้นหลังรูปสินค้าแล้ว — วางบนแท่นในฉากสตูดิโอ" if want == "studio"
                       else "ตัดพื้นหลังรูปสินค้าเป็นสติกเกอร์แล้ว",
                       "restage": "AI จัดฉากถ่ายสินค้าใหม่แล้ว — ตรวจดูว่าฉลาก/ตัวหนังสือบนสินค้ายังตรงของจริง ถ้าเพี้ยนให้เปลี่ยนเป็นแบบสติกเกอร์",
                       "card": "ใช้รูปสินค้าแบบกรอบ (ตัดพื้นหลังไม่ได้)"}[got]
                if style == "restage" and got != "restage":
                    msg = "AI จัดฉากใหม่ไม่ได้ (คีย์ฟรีอาจไม่มีรุ่นทำภาพ) จึง" + msg
                plan["note"] = ((plan.get("note") or "") + f" · {msg}").strip(" ·")
        PR.add_animation(plan, d / "scenes", o["render"].get("layout", "vertical_crop"),
                         studio=(o["product_info"].get("img_style") or "studio") == "studio")
        plan["note"] = ((plan.get("note") or "") + " · ทำเป็นแอนิเมชันกราฟิกทั้งคลิป — แก้ \"ข้อความบนจอ\" ได้ทุกฉาก "
                        "(ข้อความนี้จะเด้งตัวใหญ่กลางจอ) หรือกด 📷/📹 เปลี่ยนเป็นภาพฟรีเฉพาะบางฉาก").strip(" ·")
    elif not used:  # visual == "photo" → ภาพ/วิดีโอฟรีประกอบ (ไม่ใช่ตัวสินค้าจริง)
        ST.draw_images(plan, d / "scenes", o["render"].get("layout", "vertical_crop"), "cinematic",
                       lambda pct, msg: save(jid, step="images", progress=40 + pct * 0.58, message=msg), source="photo")
        plan["note"] = ((plan.get("note") or "") + " · ยังไม่มีรูป/วิดีโอสินค้าจริง จึงใช้ภาพฟรีประกอบไปก่อน — "
                        "แนะนำกด 📁 รูปของฉัน ใส่รูปสินค้าที่ถ่ายเองทีละฉาก คนดูจะเชื่อมากกว่า").strip(" ·")
    return plan


def analyze_story(jid: str) -> dict:
    d, j = job_dir(jid), jobs[jid]
    o = j["opts"]
    if o.get("product_info"):
        return analyze_product(jid)
    rewrite = o.get("script_mode") == "rewrite"
    text, extra, source = o.get("text", ""), "", None
    if o.get("source_url"):
        if o["provider"] == "none" or not provider_available(o["provider"]):
            raise RuntimeError("โหมดลิงก์โพสต์/ข่าวต้องใช้ AI ช่วยแปลและเรียบเรียง — เลือก Gemini (ฟรี) หรือ Claude แล้วลองใหม่")
        save(jid, status="analyzing", step="plan", progress=3, message="กำลังอ่านโพสต์/ข่าวจากลิงก์…")
        source = SRC.fetch_source(o["source_url"])
        text = source["text"]
        if o.get("source_note"):
            extra = f"- คำสั่งเพิ่มจากผู้ใช้ (ทำตามนี้): {o['source_note']}"
        save(jid, name=(source.get("title") or source["site"])[:60], source=source,
             message=f"อ่านจาก {source['site']} แล้ว — AI กำลังแปลและเรียบเรียงเป็นบทไทย")
    else:
        save(jid, status="analyzing", step="plan", progress=5,
             message="AI กำลังเรียบเรียงบทและแบ่งฉาก" if rewrite else "แบ่งฉากตามบท + คิดภาพประกอบ")
    plan = ST.make_story_plan(text, o["provider"], o["target_seconds"],
                              "rewrite" if rewrite else "verbatim", graphics=o.get("graphics", True), extra=extra,
                              strict=bool(source))
    if source:
        plan["source"] = {k: source[k] for k in ("site", "url", "title")}
    save(jid, plan=plan, step="images", progress=20, message=f"ได้บท {len(plan['scenes'])} ฉาก — เริ่มวาดภาพ")
    ok = ST.draw_images(plan, d / "scenes", o["render"].get("layout", "vertical_crop"), o.get("style", "cinematic"),
                        lambda pct, msg: save(jid, step="images", progress=20 + pct * 0.78, message=msg),
                        source=o.get("image_source", "ai"))
    if o.get("videos"):  # แทรกวิดีโอฟรีบางฉาก
        nv = ST.add_videos(plan, d / "scenes",
                           lambda pct, msg: save(jid, step="images", progress=97, message=msg))
        if nv:
            plan["note"] = ((plan.get("note") or "") + f" · แทรกวิดีโอฟรีแล้ว {nv} ฉาก (▶) — ภาพนิ่งเดิมยังเลือกกลับได้").strip(" ·")
    if ok == 0 and not plan.get("note"):
        plan["note"] = "วาดภาพด้วย AI ไม่ได้ (ไม่มีไลบรารี/การ์ดจอ) จึงใช้ภาพพื้นหลังไล่สีแทน"
    return plan


def build_preview(jid: str, src: Path, duration: float) -> None:
    d = job_dir(jid)
    part = d / "preview.part.mp4"
    try:
        P.make_preview(src, part, duration, lambda pct, _: save(jid, preview_progress=round(pct)))
        part.rename(d / "preview.mp4")
        save(jid, preview_progress=100)
    except Exception as e:
        print("สร้างวิดีโอตัวอย่างไม่ได้:", e)
        part.unlink(missing_ok=True)
        save(jid, preview_progress=-1)


def analyze_game(jid: str, src: Path, info: dict) -> dict:
    d, j = job_dir(jid), jobs[jid]
    if not info["has_audio"]:
        raise RuntimeError("คลิปนี้ไม่มีเสียง โหมดเกมต้องใช้เสียงเกมในการหาช็อตเด็ด "
                           "(ตอนอัดหน้าจอให้เปิดบันทึกเสียงภายในเครื่องด้วย)")
    wav = d / "audio.wav"
    P.extract_audio(src, wav)
    # เสียงประกาศในเกมเป็นภาษาอังกฤษชัดๆ ใช้โมเดล small ก็พอ และเร็วกว่ามาก
    events = G.detect_events(wav, "small", info["duration"], lambda pct, msg: save(
        jid, step="transcribe", progress=5 + pct * 0.75, message=msg))
    loud, hop = G.loudness(wav)
    wav.unlink(missing_ok=True)
    seen = []
    if j["opts"].get("vision", True) and provider_available("gemini"):
        try:
            seen = G.vision_moments(src, loud, hop, info["duration"], events, d / "vision",
                                    lambda m: save(jid, step="plan", progress=81, message=m))
        except Exception as e:
            print("AI ดูภาพเกมไม่ได้:", e)
        shutil.rmtree(d / "vision", ignore_errors=True)
    found = ", ".join(dict.fromkeys(e["label"] for e in events)) or "ไม่พบเสียงประกาศ"
    extra = [v for v in seen if v["score"] >= 6]
    if extra:
        found += f" + AI เห็นช็อตเด็ดจากภาพอีก {len(extra)} ช็อต"
    elif not events:
        found += " ใช้ช่วงไฟต์ที่เสียงดังแทน"
    narrate = j["opts"].get("narrate", True)
    save(jid, events=events, vision=seen, step="plan", progress=82,
         message=f"พบ: {found} — " + ("กำลังเขียนบทพากย์" if narrate else "ตัดไฮไลต์ (ไม่พากย์)"))
    clips = G.pick_clips(events, loud, hop, info["duration"], j["opts"]["target_seconds"], seen)
    if not narrate:  # ไม่พากย์: ใช้ชื่อคลิป/สรุปแบบพื้นฐาน ไม่เรียก AI เขียนบท
        plan = G.make_game_plan(clips, "none", j["opts"].get("note", ""))
        for c in plan["clips"]:
            c["narration"] = ""
        return plan
    return G.make_game_plan(clips, j["opts"]["provider"], j["opts"].get("note", ""))


def analyze_talk(jid: str, src: Path, info: dict) -> dict:
    d, j = job_dir(jid), jobs[jid]
    segs = []
    if info["has_audio"]:
        wav = d / "audio.wav"
        P.extract_audio(src, wav)
        segs = P.transcribe(
            wav, j["opts"]["whisper_model"], info["duration"],
            lambda pct, msg: save(jid, step="transcribe",
                                  progress=5 + pct * 0.75, message=msg))
        wav.unlink(missing_ok=True)
    save(jid, transcript=segs, step="plan", progress=82,
         message="AI กำลังสรุปเนื้อหาและเลือกไฮไลต์")
    return P.make_plan(segs, j["opts"]["provider"], j["opts"]["target_seconds"],
                       info["duration"])


def _brand(r: dict) -> dict:
    return {"text": r.get("channel") or "", "logo": asset_path("logo", r.get("logo") or "")}


def _best_clip(clips: list[dict]) -> dict:
    rank = G.LABEL_SCORE
    return max(clips, key=lambda c: (float(c.get("score") or 0), rank.get(c.get("label") or "", 0)))


def _resolve(rel: str) -> Path:
    """ช็อตจากต้นฉบับของงานอื่น (คลิปรวมหลายเกม): "<งาน>/source.mp4" """
    return JOBS_DIR / rel


def do_render(jid: str) -> None:
    P.TTS_NOTES.clear()
    V.reset()
    if jobs[jid]["opts"].get("mode") == "story":
        return do_render_story(jid)
    d, j = job_dir(jid), jobs[jid]
    try:
        r = j["render_opts"]
        work = d / "work"
        shutil.rmtree(work, ignore_errors=True)
        out = d / "output.mp4"
        clips = j["plan"]["clips"]
        brand = _brand(r)
        src = _resolve(j["source"]) if j.get("multi") else d / j["source"]
        # ภาพปก: เฟรมจังหวะเด็ดที่สุด + ชื่อคลิป
        thumb = d / "thumb.jpg"
        thumb.unlink(missing_ok=True)
        try:
            best = _best_clip(clips)
            bsrc = _resolve(best["src"]) if best.get("src") else src
            t_ = float(best.get("mark") or (float(best["start"]) + float(best["end"])) / 2)
            save(jid, message="ทำภาพปก")
            P.make_thumbnail(bsrc, t_, r.get("layout", "original"),
                             j["plan"].get("title") or Path(j.get("name", "")).stem,
                             best.get("label") or "", thumb, work, brand)
        except Exception as e:
            print("ทำภาพปกไม่ได้:", e)
        P.render(src, clips, work, out,
                 voice=r["voice"], tone=r.get("tone", "natural"), rate=r["rate"], orig_volume=r["orig_volume"],
                 subtitles=_subs(r), layout=r.get("layout", "original"),
                 fx=r.get("fx", False), brand=brand,
                 cover=thumb if r.get("cover") and thumb.exists() else None,
                 src_resolver=_resolve,
                 progress=lambda pct, msg: save(jid, progress=pct * 0.97, message=msg))
        music = asset_path("music", r.get("music") or "")
        if music:
            save(jid, progress=98, message="ใส่เพลงประกอบ")
            tmp = d / "output_music.mp4"
            P.add_music(out, music, r.get("music_volume", 0.25), tmp)
            tmp.replace(out)
        shutil.rmtree(work, ignore_errors=True)
        _make_post(jid)
        save(jid, status="done", step="done", progress=100, message="เสร็จแล้ว!",
             output_duration=P.probe(out)["duration"], warn=" • ".join(P.TTS_NOTES))
    except Exception as e:
        fail_job(jid, e)


def do_render_story(jid: str) -> None:
    d, j = job_dir(jid), jobs[jid]
    try:
        r, plan = j["render_opts"], j["plan"]
        if plan.get("product") and str(r.get("voice", "")).startswith("clone:"):
            # โมเดลโคลนเสียงห้ามใช้เชิงพาณิชย์ (CC BY-NC-SA) — งานขายของ/affiliate ใช้ไม่ได้
            r = {**r, "voice": "gemini:Leda" if V.gemini_ready() else P.THAI_VOICES[0]["id"]}
            P.TTS_NOTES.append("งานขายสินค้าใช้เสียงโคลนไม่ได้ (สัญญาอนุญาตห้ามใช้เชิงพาณิชย์) จึงใช้เสียงอื่นแทน")
        work = d / "work"
        shutil.rmtree(work, ignore_errors=True)
        out = d / "output.mp4"
        brand = _brand(r)
        layout = "original" if r.get("layout") == "original" else "vertical_crop"
        thumb = d / "thumb.jpg"
        thumb.unlink(missing_ok=True)
        first = (d / "scenes" / plan["scenes"][0]["img"]) if plan["scenes"] and plan["scenes"][0].get("img") else None
        if first and first.exists():
            try:
                save(jid, message="ทำภาพปก")
                P.make_thumbnail(first, 0, "original" if layout == "original" else "vertical_blur",
                                 plan.get("title") or j["name"], "", thumb, work, brand)
            except Exception as e:
                print("ทำภาพปกไม่ได้:", e)
        ST.render_story(plan, d / "scenes", work, out, voice=r["voice"], tone=r.get("tone", "natural"), rate=r["rate"], layout=layout,
                        sfx=r.get("gfx_sfx", True),
                        subtitles=_subs(r), brand=brand, style=j["opts"].get("style", "cinematic"),
                        cover=thumb if r.get("cover") and thumb.exists() else None,
                        progress=lambda pct, msg: save(jid, progress=pct * 0.97, message=msg))
        save(jid, plan=plan)  # ภาพที่วาดเพิ่มระหว่างตัดต่อ
        music = asset_path("music", r.get("music") or "")
        if music:
            save(jid, progress=98, message="ใส่เพลงประกอบ")
            tmp = d / "output_music.mp4"
            P.add_music(out, music, r.get("music_volume", 0.25), tmp)
            tmp.replace(out)
        shutil.rmtree(work, ignore_errors=True)
        _make_post(jid)
        save(jid, status="done", step="done", progress=100, message="เสร็จแล้ว!",
             output_duration=P.probe(out)["duration"], warn=" • ".join(P.TTS_NOTES))
    except Exception as e:
        fail_job(jid, e)


def do_capcut(jid: str) -> None:
    """ส่งออกสำหรับ CapCut: วิดีโอเต็มไม่มีซับ + ไฟล์แยกทีละช็อต"""
    d, j = job_dir(jid), jobs[jid]
    out_dir = d / "capcut"

    def prog(pct, msg):
        save(jid, capcut={"status": "working", "progress": pct, "message": msg})
    try:
        shutil.rmtree(out_dir, ignore_errors=True)
        work = d / "work_capcut"
        shutil.rmtree(work, ignore_errors=True)
        r = j["render_opts"]
        out_dir.mkdir(parents=True)
        full = out_dir / "00_ทั้งคลิป_ไม่มีซับ.mp4"
        if j["opts"].get("mode") == "story":
            parts = ST.render_story(j["plan"], d / "scenes", work, full, voice=r["voice"], tone=r.get("tone", "natural"), rate=r["rate"],
                                    layout="original" if r.get("layout") == "original" else "vertical_crop",
                                    subtitles=False, progress=prog, clean=True)
            prefix, labels = "ฉาก", ["" for _ in parts]
        else:
            src = _resolve(j["source"]) if j.get("multi") else d / j["source"]
            parts = P.render(src, j["plan"]["clips"], work, full,
                             voice=r["voice"], tone=r.get("tone", "natural"), rate=r["rate"], orig_volume=r["orig_volume"],
                             subtitles=False, layout=r.get("layout", "original"),
                             progress=prog, clean=True, src_resolver=_resolve)
            prefix, labels = "ช็อต", [c.get("label") or "" for c in j["plan"]["clips"]]
        names = [full.name]
        for i, (f, lb) in enumerate(zip(parts, labels), 1):
            tag = re.sub(r"[^A-Za-z0-9]+", "_", lb).strip("_")
            name = f"{i:02}_{prefix}{i}{'_' + tag if tag else ''}.mp4"
            shutil.move(str(f), out_dir / name)
            names.append(name)
        shutil.rmtree(work, ignore_errors=True)
        save(jid, capcut={"status": "done", "progress": 100, "message": "พร้อมแล้ว",
                          "files": names})
    except Exception as e:
        traceback.print_exc()
        save(jid, capcut={"status": "error", "progress": 0, "message": P.error_text(e)})


# ───────────────────────── API ─────────────────────────

def public(j: dict) -> dict:
    keep = ("id", "name", "url", "detail", "capcut", "preview_progress", "status", "step", "progress", "message", "duration",
            "plan", "opts", "render_opts", "output_duration", "created", "post", "warn")
    out = {k: j.get(k) for k in keep}
    out["segments"] = len(j.get("transcript") or [])
    out["thumb"] = (job_dir(j["id"]) / "thumb.jpg").exists()
    out["multi"] = bool(j.get("multi"))
    out["batch"] = j.get("batch") or ""
    return out


async def index(_: Request):
    return FileResponse(BASE / "static" / "index.html")


async def config(_: Request):
    return JSONResponse({
        "voices": P.voice_list(),
        "tones": {k: v[0] for k, v in V.TONES.items()},
        "gemini_tts": V.gemini_ready(),
        "clone_ok": P.has_gpu() or bool(os.environ.get("CLONE_CPU")),
        "ref_sentence": V.REF_SENTENCE,
        "layouts": P.LAYOUTS,
        "styles": {k: v[0] for k, v in imagegen.STYLES.items()},
        "imagegen": imagegen.available(),
        "pexels": True,  # ภาพถ่ายจริงใช้ได้เสมอ (Openverse ไม่ต้องมีคีย์)
        "photo_source": imagegen.photo_source(),
        "providers": {p: provider_available(p) for p in ("claude", "gemini", "ollama", "none")},
        "claude_model": P.DEFAULT_CLAUDE_MODEL,
        "ollama_model": P.DEFAULT_OLLAMA_MODEL,
        "gpu": P.has_gpu(),
        "vision": ST.vision_ready(),
        "videos": imagegen.videos_available(),
    })


UPLOADS = JOBS_DIR / "_uploads"


async def start_upload(_: Request):
    """อัปโหลดแบบแบ่งท่อน: ผ่านข้อจำกัดขนาดไฟล์ของลิงก์สาธารณะ และทนเน็ตมือถือหลุด"""
    UPLOADS.mkdir(parents=True, exist_ok=True)
    uid = uuid.uuid4().hex
    (UPLOADS / uid).write_bytes(b"")
    return JSONResponse({"upload_id": uid})


async def put_chunk(req: Request):
    uid = req.path_params["uid"]
    f = UPLOADS / uid
    if not uid.isalnum() or not f.exists():
        return JSONResponse({"error": "ไม่พบการอัปโหลดนี้"}, status_code=404)
    offset = int(req.query_params.get("offset", -1))
    size = f.stat().st_size
    if offset != size:  # ท่อนนี้เคยส่งสำเร็จแล้ว หรือส่งข้ามลำดับ → บอกตำแหน่งที่ถูกต้อง
        return JSONResponse({"size": size}, status_code=409)
    data = await req.body()
    with open(f, "ab") as out:
        out.write(data)
    return JSONResponse({"size": size + len(data)})


def job_opts(form) -> dict:
    opts = {
        "whisper_model": str(form.get("whisper_model") or "small"),
        "provider": str(form.get("provider") or "claude"),
        "target_seconds": max(15, min(600, int(_num(form.get("target_seconds"), 60)))),
        "auto": str(form.get("auto") or "") in ("1", "true", "on"),
        "mode": "game" if form.get("mode") == "game" else "talk",
        "note": str(form.get("note") or "")[:300],
    }
    if form.get("mode") == "product":  # 🛒 โหมดสินค้า = งานแบบข้อความ→คลิป ที่ใช้บทป้ายยา
        opts["mode"] = "story"
        opts["product_info"] = {k: str(form.get(f"p_{k}") or "")[:3000]
                                for k in ("name", "price", "full", "points", "cta", "visual", "use_img", "img_style")}
        opts["graphics"] = _bool(form.get("graphics"), True)
        opts["image_source"], opts["videos"], opts["script_mode"] = "photo", False, "rewrite"
        opts["text"] = opts["product_info"]["name"]
    if form.get("mode") == "story":
        opts["mode"] = "story"
        opts["text"] = str(form.get("text") or "")[:8000]
        src_url = SRC.find_url(opts["text"])
        if src_url:  # วางลิงก์โพสต์/ข่าว → อ่าน แปล เรียบเรียงเป็นคลิปไทย (ข้อความอื่นที่พิมพ์มา = คำสั่งเพิ่ม)
            opts["source_url"] = src_url
            opts["source_note"] = re.sub(r"https?://\S+", " ", opts["text"]).strip()[:500]
        opts["style"] = str(form.get("style") or "") if form.get("style") in imagegen.STYLES else "cinematic"
        opts["script_mode"] = "rewrite" if form.get("script_mode") == "rewrite" or opts.get("source_url") \
            else "verbatim"
        opts["image_source"] = "photo" if form.get("image_source") == "photo" else "ai"
        opts["graphics"] = _bool(form.get("graphics"), True)
        opts["videos"] = _bool(form.get("videos"), False) and imagegen.videos_available()
    opts["render"] = _render_opts(form, opts["mode"])
    if opts["mode"] == "game":
        opts["narrate"] = _bool(form.get("narrate"), True)
        if not opts["narrate"]:  # ไม่พากย์: เสียงเกมเต็ม + เอฟเฟกต์ ไม่มีซับบทพากย์
            opts["render"].update(orig_volume=1.0, subtitles=False, fx=True)
    if opts.get("product_info"):
        if not form.get("tone"):
            opts["render"]["tone"] = "bright"  # ป้ายยา = เสียงสดใส
        if str(opts["render"]["voice"]).startswith("clone:"):  # โคลนเสียงห้ามใช้เชิงพาณิชย์
            opts["render"]["voice"] = "gemini:Leda" if V.gemini_ready() else P.THAI_VOICES[0]["id"]
    return opts


def new_job(name: str, url: str, part: Path | None, opts: dict, batch: str = "") -> str:
    jid = uuid.uuid4().hex[:10]
    d = job_dir(jid)
    d.mkdir(parents=True)
    ext = Path(name).suffix.lower() or ".mp4"
    if part is not None:
        shutil.move(str(part), d / f"source{ext}")
    jobs[jid] = {"id": jid, "name": name, "source": "" if url else f"source{ext}",
                 "url": url, "opts": opts, "batch": batch, "created": time.time()}
    save(jid, status="queued", step="queued", progress=0, message="รอคิว")
    executor.submit(do_analyze, jid)
    return jid


def _upload_part(uid: str) -> Path | None:
    part = UPLOADS / uid
    if not uid.isalnum() or not part.exists() or part.stat().st_size == 0:
        return None
    return part


async def create_job(req: Request):
    form = await req.form(max_part_size=20 * 1024 ** 3)
    up = form.get("file")
    uid = str(form.get("upload_id") or "")
    url = str(form.get("url") or "").strip()
    part = None
    if form.get("mode") == "product":
        opts = job_opts(form)
        info = opts["product_info"]
        ids = [u for u in str(form.get("media_ids") or "").split(",") if u]
        sids = [u for u in str(form.get("shot_ids") or "").split(",") if u]
        names = str(form.get("media_names") or "").split("\n")
        if not info["name"].strip() and not info["points"].strip() and not sids:
            return JSONResponse({"error": "ใส่ชื่อสินค้า หรือรายละเอียด/ภาพหน้าจอสินค้าอย่างน้อย 1 อย่าง"}, status_code=400)
        up_dir = UPLOADS / f"prod_{uuid.uuid4().hex}"
        up_dir.mkdir(parents=True, exist_ok=True)
        for k, uid in enumerate(ids[:12]):
            part = _upload_part(uid)
            if part:
                ext = Path(names[k] if k < len(names) else "").suffix.lower()[:6] or ".jpg"
                shutil.move(str(part), up_dir / f"media_{k + 1:02}{ext}")
        pid = str(form.get("pimg_id") or "")
        if pid and _upload_part(pid):
            shutil.move(str(_upload_part(pid)), up_dir / "pimg_01.jpg")
        for k, uid in enumerate(sids[:4]):
            part = _upload_part(uid)
            if part:
                shutil.move(str(part), up_dir / f"shot_{k + 1:02}.jpg")
        opts["upload_dir"] = str(up_dir)
        return JSONResponse({"id": new_job("🛒 " + (info["name"].strip()[:40] or "สินค้า"), "", None, opts)})
    if form.get("mode") == "story":
        text = str(form.get("text") or "").strip()
        if len(text) < 10:
            return JSONResponse({"error": "ใส่ข้อความอย่างน้อย 1-2 ประโยค"}, status_code=400)
        name = re.sub(r"\s+", " ", text)[:40] + ("…" if len(text) > 40 else "")
        if SRC.find_url(text):
            name = "🔗 " + urllib.parse.urlparse(SRC.find_url(text)).netloc.replace("www.", "")
        return JSONResponse({"id": new_job(name, "", None, job_opts(form))})
    if url:
        m = re.search(r"https?://\S+", url)  # รองรับข้อความที่แชร์มาแล้วมีลิงก์ปนอยู่
        if not m:
            return JSONResponse({"error": "ลิงก์ไม่ถูกต้อง ต้องขึ้นต้นด้วย https://"}, status_code=400)
        url, name = m.group(0), "กำลังดาวน์โหลด…"
    elif uid:
        name = str(form.get("filename") or "video.mp4")
        part = _upload_part(uid)
        if part is None:
            return JSONResponse({"error": "อัปโหลดไม่ครบ ลองใหม่อีกครั้ง"}, status_code=400)
    elif up is not None and getattr(up, "filename", ""):
        name = up.filename
        UPLOADS.mkdir(parents=True, exist_ok=True)
        part = UPLOADS / uuid.uuid4().hex
        with open(part, "wb") as f:
            shutil.copyfileobj(up.file, f, 1024 * 1024)
    else:
        return JSONResponse({"error": "กรุณาเลือกไฟล์วิดีโอ"}, status_code=400)
    return JSONResponse({"id": new_job(name, url, part, job_opts(form))})


# ───────────────────────── หลายเกมรวดเดียว ─────────────────────────

BATCH_DIR = JOBS_DIR / "_batches"
batches: dict[str, dict] = {}


def save_batch(b: dict) -> None:
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    (BATCH_DIR / f"{b['id']}.json").write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")


async def create_batch(req: Request):
    form = await req.form()
    urls = re.findall(r"https?://\S+", str(form.get("urls") or ""))
    uids = [u for u in str(form.get("upload_ids") or "").split(",") if u]
    names = str(form.get("filenames") or "").split("\n")
    items = [(u, None, "กำลังดาวน์โหลด…") for u in urls]
    for i, uid in enumerate(uids):
        part = _upload_part(uid)
        if part is None:
            return JSONResponse({"error": "อัปโหลดไม่ครบ ลองใหม่อีกครั้ง"}, status_code=400)
        items.append(("", part, names[i] if i < len(names) and names[i] else f"เกม{i + 1}.mp4"))
    if not items:
        return JSONResponse({"error": "ไม่พบลิงก์หรือไฟล์"}, status_code=400)
    if len(items) > 20:
        return JSONResponse({"error": "ทำได้ครั้งละไม่เกิน 20 คลิป"}, status_code=400)
    opts = job_opts(form)
    compile_ = str(form.get("compile") or "") == "1" and opts["mode"] == "game"
    bid = "b" + uuid.uuid4().hex[:9]
    b = {"id": bid, "compile": compile_, "jobs": [], "compile_job": "", "created": time.time(),
         "opts": opts}
    batches[bid] = b
    save_batch(b)
    for url, part, name in items:
        o = json.loads(json.dumps(opts))
        if compile_:
            o["auto"] = False  # วิเคราะห์อย่างเดียว แล้วเอาช็อตเด็ดทุกเกมมารวมทีเดียว
            o["batch_hold"] = True
        b["jobs"].append(new_job(name, url, part, o, batch=bid))
    save_batch(b)
    return JSONResponse({"id": bid})


async def get_batch(req: Request):
    b = batches.get(req.path_params["bid"])
    if not b:
        return JSONResponse({"error": "ไม่พบชุดงานนี้"}, status_code=404)

    def row(jid):
        j = jobs.get(jid) or {}
        return {k: j.get(k) for k in ("id", "name", "status", "progress", "message", "step")}
    return JSONResponse({"id": b["id"], "compile": b["compile"], "jobs": [row(x) for x in b["jobs"]],
                         "compile_job": row(b["compile_job"]) if b.get("compile_job") else None})


def check_batch(bid: str) -> None:
    """ทุกเกมในชุดวิเคราะห์เสร็จแล้ว → สร้างคลิปรวมช็อตเด็ด"""
    b = batches.get(bid)
    if not b or not b["compile"] or b.get("compile_job"):
        return
    members = [jobs[x] for x in b["jobs"] if x in jobs]
    if len(members) < len(b["jobs"]) or \
            any(m.get("status") not in ("review", "done", "error", "cancelled") for m in members):
        return
    ok = [m for m in members if m.get("status") in ("review", "done") and (m.get("plan") or {}).get("clips")]
    opts = json.loads(json.dumps(b["opts"]))
    opts["auto"] = True
    cid = uuid.uuid4().hex[:10]
    job_dir(cid).mkdir(parents=True)
    jobs[cid] = {"id": cid, "name": f"รวมช็อตเด็ด {len(ok)} เกม", "opts": opts, "batch": bid,
                 "multi": True, "created": time.time(), "url": "", "source": ""}
    b["compile_job"] = cid
    save_batch(b)
    if not ok:
        save(cid, status="error", message="ไม่มีเกมไหนวิเคราะห์สำเร็จ ดูสาเหตุในแต่ละเกม")
        return
    cands = []
    for gi, m in enumerate(ok):
        for c in m["plan"]["clips"]:
            cands.append({**c, "src": f"{m['id']}/{m['source']}", "game": gi + 1,
                          "score": float(c.get("score") or 1)})
    chosen, total = [], 0.0
    for c in sorted(cands, key=lambda c: -c["score"]):
        if total >= opts["target_seconds"]:
            break
        chosen.append(c)
        total += c["end"] - c["start"]
    chosen.sort(key=lambda c: (c["game"], c["start"]))
    for c in chosen:
        c["events"] = c.get("events") or ([c["label"]] if c.get("label") else [])
        c["narration"] = ""
    note = (opts.get("note") or "") + f" (คลิปนี้รวมช็อตเด็ดจาก {len(ok)} เกม)"
    save(cid, status="analyzing", step="plan", progress=50,
         message=f"รวมช็อตเด็ดจาก {len(ok)} เกม — กำลังเขียนบทพากย์")
    try:
        plan = G.make_game_plan(chosen, opts["provider"] if opts.get("narrate", True) else "none", note)
        if not opts.get("narrate", True):
            for c in plan["clips"]:
                c["narration"] = ""
        if plan["title"].startswith(tuple(lb.title() for _, lb, _ in G.EVENTS)) or plan["title"].startswith("ไฮไลต์"):
            plan["title"] = f"รวมช็อตเด็ด {len(ok)} เกม 🔥"
    except Exception as e:
        fail_job(cid, e)
        return
    save(cid, plan=plan, source=chosen[0]["src"], render_opts=opts["render"],
         status="rendering", step="render", progress=0, message="เริ่มตัดต่อคลิปรวม")
    do_render(cid)


def _num(v, default: float) -> float:
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _render_opts(body, mode: str = "talk") -> dict:
    voice = str(body.get("voice") or "")
    tone = body.get("tone")
    layout = body.get("layout")
    game = mode == "game"
    return {
        "voice": voice if P.valid_voice(voice) else P.THAI_VOICES[0]["id"],
        "tone": tone if tone in V.TONES else ("caster" if game else "story" if mode == "story" else "natural"),
        "rate": max(-50, min(50, int(_num(body.get("rate"), 15 if game else 10)))),
        # โหมดเกม: เสียงเกมดังกว่า (ระบบลดลงให้เองตอนมีเสียงพากย์)
        "orig_volume": max(0.0, min(1.0, _num(body.get("orig_volume"), 0.7 if game else 0.15))),
        "layout": layout if layout in P.LAYOUTS else ("vertical_blur" if game else "vertical_crop" if mode == "story" else "original"),
        "subtitles": _bool(body.get("subtitles"), True),
        "sub_style": body.get("sub_style") if body.get("sub_style") in ("pop", "classic")
        else ("classic" if mode == "talk" and layout == "original" else "pop"),
        "fx": _bool(body.get("fx"), game),
        "gfx_sfx": _bool(body.get("gfx_sfx"), True),
        "cover": _bool(body.get("cover"), True),
        "music": str(body.get("music") or "") if asset_path("music", str(body.get("music") or "")) else "",
        "music_volume": max(0.0, min(1.0, _num(body.get("music_volume"), 0.25))),
        "channel": str(body.get("channel") or "").strip()[:40],
        "logo": str(body.get("logo") or "") if asset_path("logo", str(body.get("logo") or "")) else "",
    }


RENDER_KEYS = ("voice", "tone", "rate", "orig_volume", "layout", "subtitles", "sub_style", "gfx_sfx", "fx", "cover", "music",
               "music_volume", "channel", "logo")


def _subs(r: dict):
    """False = ไม่มีซับ · True = ซับปกติ · "pop" = ซับเด้งทีละคำ"""
    return ("pop" if r.get("sub_style") == "pop" else True) if r.get("subtitles") else False


def _make_post(jid: str, quiet: bool = False) -> None:
    j = jobs[jid]
    try:
        if not quiet:
            save(jid, progress=99, message="เขียนแคปชัน + แฮชแท็ก")
        save(jid, post=P.make_post(j.get("plan") or {}, j["opts"].get("mode", "talk"),
                                   j["opts"].get("provider", "none"), j["opts"].get("note", "")))
    except Exception as e:
        print("ทำแคปชันไม่ได้:", e)


async def regen_post(req: Request):
    j, err = _get(req.path_params["jid"])
    if err:
        return err
    await asyncio.to_thread(_make_post, j["id"], True)
    return JSONResponse({"post": jobs[j["id"]].get("post")})


def _bool(v, default: bool) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    return str(v).lower() not in ("", "0", "false", "off", "no")


def _get(jid: str):
    j = jobs.get(jid)
    if not j:
        return None, JSONResponse({"error": "ไม่พบงานนี้"}, status_code=404)
    return j, None


async def get_job(req: Request):
    j, err = _get(req.path_params["jid"])
    return err or JSONResponse(public(j))


async def list_jobs(_: Request):
    items = sorted(jobs.values(), key=lambda j: j.get("created", 0), reverse=True)
    return JSONResponse([{k: j.get(k) for k in ("id", "name", "status", "created")}
                         for j in items[:20]])


async def render_job(req: Request):
    jid = req.path_params["jid"]
    j, err = _get(jid)
    if err:
        return err
    if j["status"] in ("queued", "analyzing", "rendering"):
        return JSONResponse({"error": "งานนี้กำลังทำอยู่"}, status_code=409)
    body = await req.json()
    if j["opts"].get("mode") == "story":
        scenes = []
        for s in body.get("scenes", []):
            img = str(s.get("img") or "")
            if not re.fullmatch(r"scene_\d+(_v\d+)?\.(png|mp4)", img) or not (job_dir(jid) / "scenes" / img).exists():
                img = ""
            narr = str(s.get("narration") or "").strip()
            opts_ = [o for o in (s.get("options") or [])[:24]
                     if isinstance(o, str) and re.fullmatch(r"scene_\d+(_v\d+)?\.(png|mp4)", o)
                     and (job_dir(jid) / "scenes" / o).exists()]
            if narr or img:
                scenes.append({"narration": narr[:300], "headline": str(s.get("headline") or "")[:40],
                               "image": str(s.get("image") or "")[:300], "img": img,
                               "search": str(s.get("search") or "")[:60], "options": opts_,
                               "graphic": G2.clean(s.get("graphic"), "", strict=False) if isinstance(s.get("graphic"), dict)
                               and not s["graphic"].get("off") else None})
        if not scenes:
            return JSONResponse({"error": "ต้องมีอย่างน้อย 1 ฉาก"}, status_code=400)
        plan = {**(j.get("plan") or {}), "scenes": scenes,
                "title": body.get("title", ""), "summary": body.get("summary", "")}
        prev = j.get("render_opts") or j.get("opts", {}).get("render") or {}
        r = _render_opts({**prev, **{k: body[k] for k in RENDER_KEYS if k in body}}, "story")
        (job_dir(jid) / "output.mp4").unlink(missing_ok=True)
        shutil.rmtree(job_dir(jid) / "capcut", ignore_errors=True)
        (job_dir(jid) / "capcut.zip").unlink(missing_ok=True)
        j.pop("capcut", None)
        save(jid, plan=plan, render_opts=r, status="rendering", step="render", progress=0, message="เริ่มตัดต่อ",
             cancel=False)
        executor.submit(do_render, jid)
        return JSONResponse({"ok": True})
    clips = []
    dur = j.get("duration") or 0
    for c in body.get("clips", []):
        s, e = float(c.get("start", 0)), float(c.get("end", 0))
        src = str(c.get("src") or "")
        if src and not re.fullmatch(r"[0-9a-f]{10}/source\.\w+", src):
            src = ""
        if not src:
            s, e = max(0, min(s, dur)), max(0, min(e, dur))
        if e - s >= 0.5:
            clips.append({"start": s, "end": e, "narration": str(c.get("narration", "")),
                          "label": str(c.get("label") or "")[:20],
                          "mark": _num(c.get("mark"), s), "score": _num(c.get("score"), 0),
                          "desc": str(c.get("desc") or "")[:100],
                          **({"src": src} if src else {})})
    if not clips:
        return JSONResponse({"error": "ต้องมีอย่างน้อย 1 ช่วงที่ยาวกว่า 0.5 วินาที"},
                            status_code=400)
    if not j.get("multi"):
        clips.sort(key=lambda c: c["start"])
    plan = {**(j.get("plan") or {}), "clips": clips,
            "title": body.get("title", ""), "summary": body.get("summary", "")}
    prev = j.get("render_opts") or j.get("opts", {}).get("render") or {}
    r = _render_opts({**prev, **{k: body[k] for k in RENDER_KEYS if k in body}},
                     j.get("opts", {}).get("mode", "talk"))
    (job_dir(jid) / "output.mp4").unlink(missing_ok=True)
    shutil.rmtree(job_dir(jid) / "capcut", ignore_errors=True)
    (job_dir(jid) / "capcut.zip").unlink(missing_ok=True)
    j.pop("capcut", None)
    save(jid, plan=plan, render_opts=r, status="rendering", step="render",
         progress=0, message="เริ่มตัดต่อ", cancel=False)
    executor.submit(do_render, jid)
    return JSONResponse({"ok": True})


async def source_video(req: Request):
    j, err = _get(req.path_params["jid"])
    if err:
        return err
    prev = job_dir(j["id"]) / "preview.mp4"
    if j.get("multi") and j.get("source"):
        return FileResponse(_resolve(j["source"]))
    if not j.get("source"):
        return JSONResponse({"error": "ยังดาวน์โหลดไม่เสร็จ"}, status_code=404)
    return FileResponse(prev if prev.exists() else job_dir(j["id"]) / j["source"])


async def output_video(req: Request):
    j, err = _get(req.path_params["jid"])
    if err:
        return err
    f = job_dir(j["id"]) / "output.mp4"
    if not f.exists():
        return JSONResponse({"error": "ยังไม่มีวิดีโอผลลัพธ์"}, status_code=404)
    name = Path(j["name"]).stem + "_สรุป.mp4"
    dl = req.query_params.get("download")
    return FileResponse(f, filename=name if dl else None,
                        content_disposition_type="attachment" if dl else "inline")


async def capcut_export(req: Request):
    jid = req.path_params["jid"]
    j, err = _get(jid)
    if err:
        return err
    if j["status"] != "done":
        return JSONResponse({"error": "สร้างวิดีโอให้เสร็จก่อน"}, status_code=409)
    if (j.get("capcut") or {}).get("status") == "working":
        return JSONResponse({"ok": True})
    save(jid, capcut={"status": "working", "progress": 0, "message": "รอคิว"})
    executor.submit(do_capcut, jid)
    return JSONResponse({"ok": True})


async def capcut_file(req: Request):
    j, err = _get(req.path_params["jid"])
    if err:
        return err
    name = req.path_params["name"]
    if name not in ((j.get("capcut") or {}).get("files") or []):
        return JSONResponse({"error": "ไม่พบไฟล์"}, status_code=404)
    dl = req.query_params.get("download")
    return FileResponse(job_dir(j["id"]) / "capcut" / name, filename=name if dl else None,
                        content_disposition_type="attachment" if dl else "inline")


async def capcut_zip(req: Request):
    j, err = _get(req.path_params["jid"])
    if err:
        return err
    files = (j.get("capcut") or {}).get("files") or []
    if not files:
        return JSONResponse({"error": "ยังไม่ได้ส่งออก"}, status_code=404)
    z = job_dir(j["id"]) / "capcut.zip"
    if not z.exists():
        with zipfile.ZipFile(z, "w", zipfile.ZIP_STORED) as zf:
            for n in files:
                zf.write(job_dir(j["id"]) / "capcut" / n, n)
    return FileResponse(z, filename=Path(j["name"]).stem + "_CapCut.zip")


ASSETS = JOBS_DIR / "_assets"
P.VOICE_DIR = ASSETS / "voice"
ASSET_EXT = {"music": {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus"},
             "logo": {".png", ".jpg", ".jpeg", ".webp"}}


def asset_path(kind: str, name: str) -> Path | None:
    if kind not in ASSET_EXT or not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    f = ASSETS / kind / name
    return f if f.is_file() else None


async def list_assets(_: Request):
    return JSONResponse({k: sorted(p.name for p in (ASSETS / k).glob("*") if p.is_file())
                         if (ASSETS / k).exists() else [] for k in ASSET_EXT})


async def upload_asset(req: Request):
    form = await req.form(max_part_size=60 * 1024 ** 2)
    kind, up = str(form.get("kind") or ""), form.get("file")
    if kind not in ASSET_EXT or up is None or not getattr(up, "filename", ""):
        return JSONResponse({"error": "ไฟล์ไม่ถูกต้อง"}, status_code=400)
    ext = Path(up.filename).suffix.lower()
    if ext not in ASSET_EXT[kind]:
        return JSONResponse({"error": f"รองรับเฉพาะ {', '.join(sorted(ASSET_EXT[kind]))}"}, status_code=400)
    stem = re.sub(r"[^\w\-ก-๙ ]+", "", Path(up.filename).stem).strip()[:40] or kind
    (ASSETS / kind).mkdir(parents=True, exist_ok=True)
    name = f"{stem}{ext}"
    i = 2
    while (ASSETS / kind / name).exists() or (ASSETS / kind / f"{Path(name).stem}.png").exists():
        name = f"{stem}_{i}{ext}"
        i += 1
    with open(ASSETS / kind / name, "wb") as f:
        shutil.copyfileobj(up.file, f, 1024 * 1024)
    if kind == "logo" and ext != ".png":  # แปลงเป็น PNG ให้ ffmpeg ใช้ได้แน่นอน
        orig = ASSETS / kind / name
        png = orig.with_suffix(".png")
        try:
            P.run(["ffmpeg", "-y", "-hide_banner", "-i", str(orig), str(png)])
        except Exception as e:
            orig.unlink(missing_ok=True)
            return JSONResponse({"error": f"เปิดรูปไม่ได้: {e}"}, status_code=400)
        orig.unlink(missing_ok=True)
        name = png.name
    return JSONResponse({"name": name})


def _ref_text(wav24: Path) -> str:
    """ถอดข้อความจากเสียงตัวอย่าง (โมเดลโคลนต้องรู้ว่าในตัวอย่างพูดว่าอะไร)"""
    w16 = wav24.with_suffix(".16k.wav")
    try:
        P.extract_audio(wav24, w16)
        segs = P.transcribe(w16, "small", P.probe(wav24)["duration"], lambda *_: None)
        return " ".join(x.get("text", "").strip() for x in segs).strip()
    finally:
        w16.unlink(missing_ok=True)


async def upload_voice(req: Request):
    form = await req.form(max_part_size=30 * 1024 ** 2)
    up = form.get("file")
    if up is None or not getattr(up, "filename", ""):
        return JSONResponse({"error": "ไม่มีไฟล์เสียง"}, status_code=400)
    name = re.sub(r"[^\w\-ก-๙ ]+", "", str(form.get("name") or "")).strip()[:30] or "เสียงของฉัน"
    vd = ASSETS / "voice"
    vd.mkdir(parents=True, exist_ok=True)
    raw = vd / f"_{uuid.uuid4().hex}{Path(up.filename).suffix.lower()[:6] or '.webm'}"
    with open(raw, "wb") as f:
        shutil.copyfileobj(up.file, f, 1024 * 1024)
    wav = vd / f"{name}.wav"
    try:
        dur = await asyncio.to_thread(V.prepare_reference, raw, wav)
    except Exception as e:
        wav.unlink(missing_ok=True)
        return JSONResponse({"error": f"เปิดไฟล์เสียงไม่ได้: {P.error_text(e)}"}, status_code=400)
    finally:
        raw.unlink(missing_ok=True)
    if dur < 3:
        wav.unlink(missing_ok=True)
        return JSONResponse({"error": "เสียงสั้นเกินไป (ต้องพูดอย่างน้อย 5 วินาที)"}, status_code=400)
    text = str(form.get("ref_text") or "").strip()
    if not text:
        try:
            text = await asyncio.to_thread(_ref_text, wav)
        except Exception as e:
            print("ถอดข้อความเสียงตัวอย่างไม่ได้:", e)
    wav.with_suffix(".txt").write_text(text, "utf-8")
    return JSONResponse({"id": f"clone:{name}", "name": name, "duration": round(dur, 1), "text": text,
                         "voices": P.voice_list()})


async def delete_voice(req: Request):
    name = req.path_params["name"]
    if name not in P.clone_voices():
        return JSONResponse({"error": "ไม่พบเสียงนี้"}, status_code=404)
    for ext in (".wav", ".txt"):
        (ASSETS / "voice" / f"{name}{ext}").unlink(missing_ok=True)
    return JSONResponse({"voices": P.voice_list()})


async def voice_sample(req: Request):
    name = req.path_params["name"]
    f = ASSETS / "voice" / f"{name}.wav"
    return FileResponse(f) if name in P.clone_voices() else JSONResponse({"error": "ไม่พบเสียง"}, status_code=404)


async def preview_voice(req: Request):
    """ฟังตัวอย่างเสียงก่อนเลือก"""
    body = await req.json()
    voice, tone = str(body.get("voice") or ""), str(body.get("tone") or "natural")
    if not P.valid_voice(voice):
        return JSONResponse({"error": "ไม่รู้จักเสียงนี้"}, status_code=400)
    text = P.clean_text(str(body.get("text") or "")) or "สวัสดีครับ นี่คือตัวอย่างเสียงพากย์ของคลิปนี้"
    out = ASSETS / "_preview" / f"{uuid.uuid4().hex}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    for old in out.parent.glob("*.mp3"):
        if time.time() - old.stat().st_mtime > 600:
            old.unlink(missing_ok=True)
    P.TTS_NOTES.clear()
    try:
        await asyncio.to_thread(P.tts, text[:200], out, voice, int(_num(body.get("rate"), 0)), tone)
    except Exception as e:
        return JSONResponse({"error": P.error_text(e)}, status_code=500)
    return JSONResponse({"url": f"/api/voice-preview/{out.name}", "warn": " • ".join(P.TTS_NOTES)})


async def voice_preview_file(req: Request):
    name = req.path_params["name"]
    f = ASSETS / "_preview" / name
    return FileResponse(f) if re.fullmatch(r"[0-9a-f]{32}\.mp3", name) and f.exists() \
        else JSONResponse({"error": "หมดอายุ"}, status_code=404)


async def get_asset(req: Request):
    f = asset_path(req.path_params["kind"], req.path_params["name"])
    return FileResponse(f) if f else JSONResponse({"error": "ไม่พบไฟล์"}, status_code=404)


async def thumb_image(req: Request):
    j, err = _get(req.path_params["jid"])
    if err:
        return err
    f = job_dir(j["id"]) / "thumb.jpg"
    if not f.exists():
        return JSONResponse({"error": "ไม่มีภาพปก"}, status_code=404)
    dl = req.query_params.get("download")
    return FileResponse(f, filename=Path(j["name"]).stem + "_ปก.jpg" if dl else None,
                        content_disposition_type="attachment" if dl else "inline")


async def scene_image(req: Request):
    j, err = _get(req.path_params["jid"])
    if err:
        return err
    name = req.path_params["name"]
    f = job_dir(j["id"]) / "scenes" / name
    if not re.fullmatch(r"scene_\d+(_v\d+)?\.(png|mp4)", name) or not f.exists():
        return JSONResponse({"error": "ไม่พบภาพ"}, status_code=404)
    return FileResponse(f)


async def regen_scene(req: Request):
    """AI วาดภาพฉากใหม่ 3 แบบให้เลือก (ใช้คำบรรยายภาพที่แก้แล้วได้)"""
    from starlette.concurrency import run_in_threadpool
    j, err = _get(req.path_params["jid"])
    if err:
        return err
    body = await req.json()
    prompt = str(body.get("prompt") or "").strip()[:300] or ST.GENERIC_IMAGES[0]
    n = max(1, min(4, int(_num(body.get("n"), 3))))
    i = int(_num(req.path_params["i"], 0))
    d = job_dir(j["id"]) / "scenes"
    d.mkdir(parents=True, exist_ok=True)
    names, ai = await run_in_threadpool(ST.ai_variants, {"image": prompt}, i, d,
                                        j["opts"].get("style", "cinematic"), n)
    return JSONResponse({"imgs": names, "ai": ai})


async def photo_scene(req: Request):
    """ค้นภาพถ่ายจริงจากคลังภาพฟรี 4 ภาพให้เลือก"""
    from starlette.concurrency import run_in_threadpool
    j, err = _get(req.path_params["jid"])
    if err:
        return err
    body = await req.json()
    query = str(body.get("query") or "").strip()[:80]
    i = int(_num(req.path_params["i"], 0))
    d = job_dir(j["id"]) / "scenes"
    d.mkdir(parents=True, exist_ok=True)
    try:
        scenes = (j.get("plan") or {}).get("scenes") or []
        scene = dict(scenes[i]) if 0 <= i < len(scenes) else {}
        if body.get("narration"):
            scene["narration"] = str(body["narration"])
        if body.get("prompt") and not scene.get("generic"):
            scene["image"] = str(body["prompt"])
        rank = _bool(body.get("rank"), True) and ST.vision_ready()
        names = await run_in_threadpool(ST.photo_options, scene, i, d, 6 if rank else 4, query)
    except Exception as e:
        return JSONResponse({"error": P.error_text(e)}, status_code=400)
    if not names:
        return JSONResponse({"error": "ไม่เจอภาพที่ตรงคำค้น ลองพิมพ์คำค้นใหม่ (ไทยหรืออังกฤษก็ได้)"}, status_code=404)
    weak = False
    if rank and len(names) > 1:  # ให้ AI ดูแล้วเรียงภาพที่ตรงบทที่สุดขึ้นก่อน
        sc = {"narration": scene.get("narration", ""), "options": list(names)}
        if await run_in_threadpool(ST.rank_photos, [sc], d, (j.get("plan") or {}).get("title", "")):
            names, weak = sc["options"], sc.get("weak_photo", False)
    return JSONResponse({"imgs": names, "weak": weak})


async def video_scene(req: Request):
    """ค้นวิดีโอฟรีให้ฉากนี้ (Pixabay/Pexels) แล้วให้ AI เลือกตัวที่ตรงบทขึ้นก่อน"""
    from starlette.concurrency import run_in_threadpool
    j, err = _get(req.path_params["jid"])
    if err:
        return err
    body = await req.json()
    i = int(_num(req.path_params["i"], 0))
    d = job_dir(j["id"]) / "scenes"
    d.mkdir(parents=True, exist_ok=True)
    scenes = (j.get("plan") or {}).get("scenes") or []
    scene = dict(scenes[i]) if 0 <= i < len(scenes) else {}
    if body.get("narration"):
        scene["narration"] = str(body["narration"])
    if body.get("prompt") and not scene.get("generic"):
        scene["image"] = str(body["prompt"])
    try:
        names = await run_in_threadpool(ST.video_options, scene, i, d, 4, str(body.get("query") or "").strip()[:80])
    except Exception as e:
        return JSONResponse({"error": P.error_text(e)}, status_code=400)
    if not names:
        return JSONResponse({"error": "ไม่เจอวิดีโอที่ตรงคำค้น ลองพิมพ์คำค้นใหม่"}, status_code=404)
    if len(names) > 1 and ST.vision_ready():
        sc = {"narration": scene.get("narration", ""), "options": list(names)}
        if await run_in_threadpool(ST.rank_photos, [sc], d, (j.get("plan") or {}).get("title", "")):
            names = sc["options"]
    return JSONResponse({"imgs": names})


async def rank_scenes(req: Request):
    """ให้ AI เลือกภาพที่ตรงบทที่สุดของหลายฉากพร้อมกัน (ใช้หลังกดเปลี่ยนเป็นภาพถ่ายทุกฉาก)"""
    from starlette.concurrency import run_in_threadpool
    j, err = _get(req.path_params["jid"])
    if err:
        return err
    body = await req.json()
    d = job_dir(j["id"]) / "scenes"
    scenes = [{"narration": str(x.get("narration") or ""),
               "options": [str(o) for o in x.get("options") or [] if re.fullmatch(r"[\w.\-]+", str(o))]}
              for x in (body.get("scenes") or [])[:40]]
    if not ST.vision_ready():
        return JSONResponse({"error": "ต้องใส่คีย์ Gemini ก่อน AI ถึงจะช่วยเลือกภาพได้"}, status_code=400)
    n = await run_in_threadpool(ST.rank_photos, scenes, d, (j.get("plan") or {}).get("title", ""))
    return JSONResponse({"ranked": n, "scenes": [{"options": s["options"], "img": s.get("img"),
                                                  "weak": s.get("weak_photo", False)} for s in scenes]})


async def upload_scene(req: Request):
    """ใช้ภาพของตัวเองแทนภาพที่ AI วาด"""
    j, err = _get(req.path_params["jid"])
    if err:
        return err
    form = await req.form(max_part_size=300 * 1024 ** 2)
    up = form.get("file")
    if up is None or not getattr(up, "filename", ""):
        return JSONResponse({"error": "เลือกรูปก่อน"}, status_code=400)
    i = int(_num(req.path_params["i"], 0))
    d = job_dir(j["id"]) / "scenes"
    d.mkdir(parents=True, exist_ok=True)
    v = 2
    while (d / f"scene_{i + 1:02}_v{v}.png").exists() or (d / f"scene_{i + 1:02}_v{v}.mp4").exists():
        v += 1
    name = f"scene_{i + 1:02}_v{v}.png"
    ext = Path(up.filename).suffix.lower()[:6]
    raw = d / f"upload_{uuid.uuid4().hex}{ext}"
    with open(raw, "wb") as f:
        shutil.copyfileobj(up.file, f, 1024 * 1024)
    is_vid = ext in (".mp4", ".mov", ".webm", ".m4v", ".3gp", ".mkv") or \
        str(getattr(up, "content_type", "") or "").startswith("video/")
    if is_vid:  # วิดีโอของตัวเอง → แปลงเป็นคลิปแทรกฉาก (ไม่เกิน 20 วิแรก)
        from starlette.concurrency import run_in_threadpool
        vname = name[:-4] + ".mp4"
        try:
            await run_in_threadpool(imagegen.normalize_video, raw, d / vname)
        except Exception:
            return JSONResponse({"error": "เปิดวิดีโอนี้ไม่ได้ ลองไฟล์ MP4"}, status_code=400)
        finally:
            raw.unlink(missing_ok=True)
        return JSONResponse({"img": vname})
    try:  # ย่อให้ด้านยาวไม่เกิน 2048 + แปลงเป็น PNG
        P.run(["ffmpeg", "-y", "-hide_banner", "-i", str(raw), "-frames:v", "1",
               "-vf", "scale='min(2048,iw)':-2", str(d / name)])
    except Exception:
        return JSONResponse({"error": "เปิดรูปนี้ไม่ได้ ลองใช้ไฟล์ JPG หรือ PNG"}, status_code=400)
    finally:
        raw.unlink(missing_ok=True)
    return JSONResponse({"img": name})


async def delete_job(req: Request):
    jid = req.path_params["jid"]
    j, err = _get(jid)
    if err:
        return err
    if j["status"] in ("analyzing", "rendering"):
        return JSONResponse({"error": "งานนี้กำลังทำอยู่"}, status_code=409)
    jobs.pop(jid, None)
    shutil.rmtree(job_dir(jid), ignore_errors=True)
    return JSONResponse({"ok": True})


LOGIN_HTML = """<!doctype html><html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>สรุปคลิป</title>
<style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#f4f1ea;color:#1d1b17;
font:16px/1.6 system-ui,sans-serif}@media(prefers-color-scheme:dark){body{background:#161512;color:#efe9dd}}
form{width:min(340px,90vw);text-align:center}h1{font-size:28px;margin:0 0 4px}h1 span{color:#d9480f}
input{width:100%;box-sizing:border-box;font:600 28px monospace;letter-spacing:.4em;text-align:center;padding:14px;
border-radius:12px;border:1px solid #c9c1b1;margin:18px 0 12px;background:transparent;color:inherit}
button{width:100%;padding:14px;border:0;border-radius:12px;background:#d9480f;color:#fff;font:600 17px system-ui}
.e{color:#c92a2a;min-height:1.6em}</style></head><body><form method="post" action="login">
<h1>สรุป<span>คลิป</span></h1><div>ใส่รหัส PIN (ดูได้ในหน้า Colab)</div>
<input name="pin" inputmode="numeric" autocomplete="one-time-code" maxlength="12" autofocus required>
<div class="e">__ERR__</div><button>เข้าใช้งาน</button></form></body></html>"""


async def login(req: Request):
    if req.method == "GET":
        return HTMLResponse(LOGIN_HTML.replace("__ERR__", ""))
    form = await req.form()
    if APP_PIN and hmac.compare_digest(str(form.get("pin") or "").strip(), APP_PIN):
        r = RedirectResponse("./", status_code=303)
        r.set_cookie("sc_pin", PIN_TOKEN, max_age=30 * 86400, httponly=True, samesite="lax")
        return r
    await asyncio.sleep(1.5)  # กันการเดารหัสรัวๆ
    return HTMLResponse(LOGIN_HTML.replace("__ERR__", "รหัสไม่ถูกต้อง"), status_code=401)


LAST_ACTIVITY = [time.time()]  # ครั้งล่าสุดที่มีคนเปิดใช้โปรแกรม (ไว้ปิด Colab อัตโนมัติเมื่อไม่มีใครใช้)


async def idle_status(_: Request):
    busy = any(j.get("status") in ("queued", "analyzing", "rendering")
               or (j.get("capcut") or {}).get("status") == "working" for j in jobs.values())
    if busy:
        LAST_ACTIVITY[0] = time.time()  # งานที่กำลังทำอยู่ = ยังใช้งานอยู่
    return JSONResponse({"idle_seconds": int(time.time() - LAST_ACTIVITY[0]), "busy": busy})


async def alive(_: Request):
    """หน้าเว็บส่งมาเป็นระยะตอนผู้ใช้กำลังแก้บท/เลือกภาพ (ไม่มีคำขออื่น) → นับว่ายังใช้งานอยู่ ไม่ปิดเครื่อง"""
    return JSONResponse({"ok": True})


class PinGate:
    """ต้องใส่ PIN ก่อนใช้งาน (กันคนอื่นที่ได้ลิงก์ไป) + จดเวลาที่มีคนใช้งานล่าสุด"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/api/idle":
            return await self.app(scope, receive, send)  # ให้ตัวเฝ้าใน Colab ถามได้ (ไม่มีข้อมูลลับ)
        if scope["type"] == "http":
            LAST_ACTIVITY[0] = time.time()
        if scope["type"] != "http" or not APP_PIN or scope["path"] == "/login":
            return await self.app(scope, receive, send)
        cookie = ""
        for k, v in scope.get("headers", []):
            if k == b"cookie":
                for part in v.decode("latin-1").split(";"):
                    name, _, val = part.strip().partition("=")
                    if name == "sc_pin":
                        cookie = val
        if cookie and hmac.compare_digest(cookie, PIN_TOKEN):
            return await self.app(scope, receive, send)
        if scope["path"].startswith("/api/"):
            resp = JSONResponse({"error": "ต้องใส่รหัส PIN ก่อน — รีเฟรชหน้าเว็บ"}, status_code=401)
        else:
            resp = HTMLResponse(LOGIN_HTML.replace("__ERR__", ""))
        await resp(scope, receive, send)


async def cancel_job(req: Request):
    jid = req.path_params["jid"]
    j, err = _get(jid)
    if err:
        return err
    if j.get("status") == "queued":
        save(jid, status="cancelled", message="ยกเลิกแล้ว", cancel=False)
    elif j.get("status") in ("analyzing", "rendering"):
        save(jid, cancel=True, message="กำลังยกเลิก…")
    return JSONResponse({"ok": True})


load_existing()
for _f in BATCH_DIR.glob("*.json") if BATCH_DIR.exists() else []:
    try:
        _b = json.loads(_f.read_text(encoding="utf-8"))
        batches[_b["id"]] = _b
    except Exception:
        pass
app = Starlette(routes=[
    Route("/login", login, methods=["GET", "POST"]),
    Route("/api/idle", idle_status),
    Route("/api/alive", alive),
    Route("/api/jobs/{jid}/cancel", cancel_job, methods=["POST"]),
    Route("/", index),
    Route("/api/config", config),
    Route("/api/jobs", list_jobs, methods=["GET"]),
    Route("/api/jobs", create_job, methods=["POST"]),
    Route("/api/uploads", start_upload, methods=["POST"]),
    Route("/api/uploads/{uid}", put_chunk, methods=["PUT"]),
    Route("/api/jobs/{jid}", get_job, methods=["GET"]),
    Route("/api/jobs/{jid}", delete_job, methods=["DELETE"]),
    Route("/api/jobs/{jid}/render", render_job, methods=["POST"]),
    Route("/api/jobs/{jid}/post", regen_post, methods=["POST"]),
    Route("/api/jobs/{jid}/source", source_video),
    Route("/api/jobs/{jid}/output", output_video),
    Route("/api/jobs/{jid}/thumb.jpg", thumb_image),
    Route("/api/jobs/{jid}/scenes/{name}", scene_image),
    Route("/api/jobs/{jid}/scenes/{i}/regen", regen_scene, methods=["POST"]),
    Route("/api/jobs/{jid}/scenes/{i}/upload", upload_scene, methods=["POST"]),
    Route("/api/jobs/{jid}/scenes/{i}/photos", photo_scene, methods=["POST"]),
    Route("/api/jobs/{jid}/scenes-rank", rank_scenes, methods=["POST"]),
    Route("/api/jobs/{jid}/scenes/{i}/videos", video_scene, methods=["POST"]),
    Route("/api/assets", list_assets, methods=["GET"]),
    Route("/api/voices", upload_voice, methods=["POST"]),
    Route("/api/voices/{name}", delete_voice, methods=["DELETE"]),
    Route("/api/voices/{name}/sample", voice_sample),
    Route("/api/voice-preview", preview_voice, methods=["POST"]),
    Route("/api/voice-preview/{name}", voice_preview_file),
    Route("/api/assets", upload_asset, methods=["POST"]),
    Route("/api/assets/{kind}/{name}", get_asset),
    Route("/api/batches", create_batch, methods=["POST"]),
    Route("/api/batches/{bid}", get_batch),
    Route("/api/jobs/{jid}/capcut", capcut_export, methods=["POST"]),
    Route("/api/jobs/{jid}/capcut.zip", capcut_zip),
    Route("/api/jobs/{jid}/capcut/{name}", capcut_file),
])
app = PinGate(app)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT") or 8000)
    print(f"\n  เปิดเบราว์เซอร์ไปที่  http://localhost:{port}\n")
    uvicorn.run(app, host=os.environ.get("HOST") or "127.0.0.1", port=port, log_level="warning")
