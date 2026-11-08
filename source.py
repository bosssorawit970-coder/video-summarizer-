"""
อ่านเนื้อหาจากลิงก์โพสต์/ข่าว (Reddit, เว็บข่าว, บล็อก …) เพื่อให้ AI แปลเป็นไทยแล้วทำเป็นคลิป
  • Reddit → ใช้ .json ของโพสต์ (หัวข้อ + เนื้อหา + คอมเมนต์ยอดนิยม)
  • เว็บทั่วไป → trafilatura (ถ้าติดตั้ง) → ดึงจาก <p> เอง → ตัวอ่านหน้าเว็บ r.jina.ai (สำรอง)
"""
from __future__ import annotations

import html as htmllib
import json
import re
import urllib.error
import urllib.parse
import urllib.request

BROWSER_UA = ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0 Mobile Safari/537.36")
REDDIT_UA = "sarupclip/1.0 (personal short-video maker; reads public posts)"
MAX_TEXT = 7000


def find_url(text: str) -> str:
    m = re.search(r"https?://[^\s<>\"']+", text or "")
    return m.group(0).rstrip(").,]") if m else ""


def _get(url: str, ua: str = BROWSER_UA, accept: str = "text/html,application/json;q=0.9,*/*;q=0.8",
         limit: int = 4 * 1024 * 1024) -> tuple[str, str]:
    """คืน (เนื้อหา, ลิงก์สุดท้ายหลัง redirect)"""
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": accept,
                                               "Accept-Language": "en-US,en;q=0.9,th;q=0.8"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read(limit)
        final = r.geturl()
        charset = r.headers.get_content_charset() or ""
    if not charset:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", raw[:4000], re.I)
        charset = m.group(1).decode() if m else "utf-8"
    return raw.decode(charset, "replace"), final


def _clean(t: str) -> str:
    t = htmllib.unescape(t or "")
    t = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", t)  # ลิงก์ markdown → ข้อความ
    t = re.sub(r"[ \t ]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


# ───────────────────────── Reddit ─────────────────────────

def _is_reddit(url: str) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower()
    return host.endswith("reddit.com") or host.endswith("redd.it")


def _reddit(url: str) -> dict:
    if "/s/" in url or urllib.parse.urlparse(url).netloc.lower().endswith("redd.it"):
        try:  # ลิงก์แชร์แบบสั้น → หาลิงก์จริงก่อน
            _, url = _get(url)
        except Exception:
            pass
    p = urllib.parse.urlparse(url)
    path = p.path.rstrip("/")
    last = None
    for host in ("www.reddit.com", "old.reddit.com", "api.reddit.com"):
        try:
            raw, _ = _get(f"https://{host}{path}.json?raw_json=1&limit=12&sort=top", REDDIT_UA, "application/json")
            data = json.loads(raw)
            break
        except Exception as e:
            last = e
    else:
        raise RuntimeError(f"Reddit ไม่ยอมให้อ่าน ({last})")
    post = data[0]["data"]["children"][0]["data"]
    title = _clean(post.get("title", ""))
    body = _clean(post.get("selftext", ""))
    sub = post.get("subreddit_name_prefixed") or ("r/" + post.get("subreddit", ""))
    link = post.get("url_overridden_by_dest") or ""
    extra = ""
    if not body and link and not _is_reddit(link) and not re.search(r"\.(jpe?g|png|gif|gifv|mp4|webp)$|i\.redd\.it|v\.redd\.it|imgur",
                                                                     link, re.I):
        try:  # โพสต์ที่แชร์ลิงก์ข่าว → อ่านข่าวต้นทางด้วย
            extra = _web(link)["text"]
        except Exception:
            pass
    comments = []
    for c in (data[1]["data"]["children"] if len(data) > 1 else []):
        d = c.get("data") or {}
        txt = _clean(d.get("body", ""))
        if c.get("kind") == "t1" and txt and txt not in ("[deleted]", "[removed]") and not d.get("stickied"):
            comments.append((int(d.get("score") or 0), txt[:500]))
    comments.sort(key=lambda x: -x[0])
    parts = [f"หัวข้อโพสต์: {title}"]
    if body:
        parts.append(f"เนื้อหาโพสต์:\n{body}")
    if extra:
        parts.append(f"เนื้อหาข่าวที่โพสต์แชร์มา:\n{extra[:4000]}")
    if comments:
        parts.append("คอมเมนต์ยอดนิยม:\n" + "\n".join(f"- ({s} คะแนน) {t}" for s, t in comments[:5]))
    return {"title": title, "text": "\n\n".join(parts)[:MAX_TEXT], "site": f"Reddit {sub}".strip(),
            "url": f"https://www.reddit.com{path}"}


# ───────────────────────── เว็บทั่วไป ─────────────────────────

def _meta(page: str, *names: str) -> str:
    for n in names:
        m = re.search(rf"<meta[^>]+(?:property|name)=[\"']{re.escape(n)}[\"'][^>]*content=[\"']([^\"']+)", page, re.I) or \
            re.search(rf"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]*(?:property|name)=[\"']{re.escape(n)}[\"']", page, re.I)
        if m:
            return _clean(m.group(1))
    return ""


def _paragraphs(page: str) -> str:
    """ดึงย่อหน้าเนื้อหาเอง (ไม่มี trafilatura): ตัดเมนู/สคริปต์ แล้วเก็บ <h1-3> <p> <li> ที่ยาวพอ"""
    page = re.sub(r"(?is)<(script|style|noscript|nav|footer|header|aside|form|svg)[^>]*>.*?</\1>", " ", page)
    body = re.search(r"(?is)<article[^>]*>(.*?)</article>", page)
    page = body.group(1) if body and len(body.group(1)) > 1500 else page
    out = []
    for tag, inner in re.findall(r"(?is)<(h[1-3]|p|li)[^>]*>(.*?)</\1>", page):
        t = _clean(re.sub(r"(?s)<[^>]+>", " ", inner))
        if (tag == "p" and len(t) >= 40) or (tag != "p" and 15 <= len(t) <= 200 and tag != "li") or \
                (tag == "li" and len(t) >= 60):
            if t not in out:
                out.append(t)
    return "\n\n".join(out)


def _jina(url: str) -> str:
    """ตัวอ่านหน้าเว็บสำรอง (เว็บที่ต้องรัน JavaScript / กันบอท)"""
    raw, _ = _get("https://r.jina.ai/" + url, BROWSER_UA, "text/plain")
    raw = re.sub(r"(?m)^(Title|URL Source|Published Time|Markdown Content):.*$", "", raw)
    raw = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", raw)  # รูป
    return _clean(raw)


def _web(url: str) -> dict:
    page, final = _get(url)
    title = _meta(page, "og:title", "twitter:title") or _clean(
        re.sub(r"(?s)<[^>]+>", "", (re.search(r"(?is)<title[^>]*>(.*?)</title>", page) or [None, ""])[1]))
    site = _meta(page, "og:site_name") or urllib.parse.urlparse(final).netloc.replace("www.", "")
    text = ""
    try:
        import trafilatura
        text = trafilatura.extract(page, include_comments=False, include_tables=False, favor_precision=True) or ""
    except Exception:
        pass
    if len(text) < 300:
        text = _paragraphs(page) if len(_paragraphs(page)) > len(text) else text
    if len(text) < 300:
        try:
            text = _jina(url) or text
        except Exception:
            pass
    desc = _meta(page, "og:description", "description")
    if len(text) < 80 and desc:
        text = desc
    return {"title": title, "text": _clean(f"หัวข้อ: {title}\n\n{text}")[:MAX_TEXT], "site": site, "url": final}


def fetch_source(url: str) -> dict:
    """อ่านโพสต์/ข่าวจากลิงก์ คืน {"title", "text", "site", "url"}"""
    url = find_url(url) or url.strip()
    if not url.startswith("http"):
        raise RuntimeError("ลิงก์ไม่ถูกต้อง ต้องขึ้นต้นด้วย https://")
    try:
        src = _reddit(url) if _is_reddit(url) else _web(url)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 429):
            try:  # เว็บกันบอท → ลองตัวอ่านสำรอง
                text = _jina(url)
                if len(text) > 200:
                    return {"title": "", "text": text[:MAX_TEXT],
                            "site": urllib.parse.urlparse(url).netloc.replace("www.", ""), "url": url}
            except Exception:
                pass
            raise RuntimeError(f"เว็บนี้ไม่ยอมให้โปรแกรมอ่าน (HTTP {e.code}) — ลองคัดลอกเนื้อหามาวางเองแทน") from e
        raise RuntimeError(f"เปิดลิงก์ไม่ได้ (HTTP {e.code})") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"เปิดลิงก์ไม่ได้: {e.reason}") from e
    body = re.sub(r"^หัวข้อ(โพสต์)?: .*$", "", src["text"], flags=re.M).strip()
    if len(body) < 60:
        raise RuntimeError("อ่านเนื้อหาจากลิงก์นี้ไม่ได้ (อาจเป็นโพสต์รูป/วิดีโอล้วน หรือเว็บต้องล็อกอิน) — ลองคัดลอกข้อความมาวางเองแทน")
    return src
