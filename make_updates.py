#!/usr/bin/env python3
"""Learning Hub updates: makes announcement cards for the Updates page.

Cards are made for new courses, new lessons (since the last run) and every [news] line in news.txt.
If CARD_AI=1, Cloudflare Workers AI paints a background picture. The words are always added by code,
so spelling stays exact. Cards older than KEEP_DAYS are deleted. Standard library only.
"""
import base64
import hashlib
import html
import json
import os
import re
import textwrap
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

OUT = "courses/updates"
STATE = "courses/updates-state.json"
COURSES = "courses/index.json"
NEWS = "news.txt"
KEEP_DAYS = 15
MAX_AI_PER_RUN = 6
MODEL = "@cf/stabilityai/stable-diffusion-xl-base-1.0"
ZONE = timezone(timedelta(hours=1))  # Nigeria time

USE_AI = os.environ.get("CARD_AI", "") == "1"
ACCOUNT = os.environ.get("CF_ACCOUNT_ID", "").strip()
TOKEN = os.environ.get("CF_API_TOKEN", "").strip()

PROMPTS = {
    "lesson": "soft abstract background for a school announcement, deep green and gold colours, gentle light, bokeh, empty centre, no text, no letters, no numbers, no logos, no people",
    "course": "soft abstract background for a new school course announcement, deep green and gold, floating light particles, empty centre, no text, no letters, no numbers, no logos, no people",
    "news": "soft abstract background for a school news bulletin, navy blue and gold, subtle paper texture, empty centre, no text, no letters, no numbers, no logos, no people",
}
LABEL = {"lesson": "NEW LESSON", "course": "NEW COURSE", "news": "NEWS"}


def now():
    return datetime.now(ZONE)


def today():
    return now().strftime("%Y-%m-%d")


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def esc(text):
    return html.escape(str(text), quote=True)


def read_news():
    try:
        with open(NEWS, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        m = re.search(r"\[news\]\s*(.+)", line, re.I)
        if m and m.group(1).strip():
            found.append(m.group(1).strip())
    return found


def lesson_events(state, courses):
    """Compares ready-lesson counts with the last run. The first run only records the counts (no cards)."""
    events = []
    current = {}
    for c in courses:
        cid = c.get("id")
        if not cid:
            continue
        current[cid] = {
            "title": c.get("title") or cid,
            "ready": int(c.get("ready") or 0),
            "total": int(c.get("total") or 0),
        }
    if state.get("initialized"):
        for cid, c in current.items():
            before = state.get("ready", {}).get(cid)
            if before is None:
                events.append({"kind": "course", "title": "New course: " + c["title"],
                               "text": str(c["total"]) + " lessons. Open the course to start learning.",
                               "key": "course:" + cid})
            elif c["ready"] > before:
                n = c["ready"] - before
                s = "s" if n > 1 else ""
                events.append({"kind": "lesson", "title": "New lesson" + s + " in " + c["title"],
                               "text": str(n) + " new lesson" + s + " ready. Open the course to read "
                                       + ("them." if n > 1 else "it."),
                               "key": "lesson:" + cid + ":" + str(c["ready"])})
    state["ready"] = {cid: c["ready"] for cid, c in current.items()}
    return events


def news_events(state):
    events = []
    seen = set(state.get("news", []))
    for text in read_news():
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]
        if h not in seen:
            seen.add(h)
            events.append({"kind": "news", "title": "Announcement", "text": text, "key": "news:" + h})
    state["news"] = sorted(seen)
    return events


def make_background(kind, name):
    """Asks Cloudflare Workers AI for a plain background picture. Returns the file name, or None."""
    if not (ACCOUNT and TOKEN):
        print("updates: no Cloudflare account or token, using plain background")
        return None
    url = "https://api.cloudflare.com/client/v4/accounts/" + ACCOUNT + "/ai/run/" + MODEL
    body = json.dumps({"prompt": PROMPTS.get(kind, PROMPTS["news"]), "num_steps": 20}).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            ctype = r.headers.get("Content-Type", "")
            data = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read()[:200].decode("utf-8", "replace")
        print("updates: picture AI refused (" + str(e.code) + "): " + detail + " - using plain background")
        return None
    except Exception as e:
        print("updates: picture AI failed: " + str(e) + " - using plain background")
        return None
    if "json" in ctype:
        try:
            data = base64.b64decode(json.loads(data)["result"]["image"])
        except (ValueError, KeyError, TypeError) as e:
            print("updates: picture AI sent an unexpected answer: " + str(e) + " - using plain background")
            return None
    if len(data) < 5000:
        print("updates: picture AI sent a too-small image - using plain background")
        return None
    fname = name + "-bg.png"
    with open(os.path.join(OUT, fname), "wb") as f:
        f.write(data)
    return fname


def wrap(text, width, max_lines):
    lines = textwrap.wrap(text, width=width) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,.;:") + "..."
    return lines


def card_svg(ev, bg, date):
    W, H = 1200, 675
    title_lines = wrap(ev["title"], 26, 2)
    body_lines = wrap(ev["text"], 50, 5) if ev["text"] else []
    parts = ['<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
             '<stop offset="0" stop-color="#1b4332"/><stop offset="1" stop-color="#2d6a4f"/>'
             '</linearGradient></defs>']
    if bg:
        parts.append('<image href="%s" x="0" y="0" width="%d" height="%d" preserveAspectRatio="xMidYMid slice"/>'
                     % (esc(bg), W, H))
        parts.append('<rect width="%d" height="%d" fill="#0b2418" opacity="0.45"/>' % (W, H))
    else:
        parts.append('<rect width="%d" height="%d" fill="url(#g)"/>' % (W, H))
    parts.append('<rect x="60" y="60" width="%d" height="%d" rx="18" fill="none" stroke="#c9a84c" stroke-width="4"/>'
                 % (W - 120, H - 120))
    parts.append('<text x="110" y="150" font-family="Arial, sans-serif" font-size="30" font-weight="bold" '
                 'letter-spacing="4" fill="#e8c96a">%s</text>' % esc(LABEL[ev["kind"]]))
    y = 215
    for line in title_lines:
        parts.append('<text x="110" y="%d" font-family="Georgia, serif" font-size="60" font-weight="bold" '
                     'fill="#ffffff">%s</text>' % (y, esc(line)))
        y += 74
    y = y - 74 + 70
    for line in body_lines:
        parts.append('<text x="110" y="%d" font-family="Arial, sans-serif" font-size="36" fill="#f5f1e6">%s</text>'
                     % (y, esc(line)))
        y += 46
    parts.append('<text x="110" y="%d" font-family="Arial, sans-serif" font-size="26" fill="#e8c96a">'
                 'Learning Hub  |  %s</text>' % (H - 90, esc(date)))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">%s</svg>'
            % (W, H, W, H, "".join(parts)))


def cleanup(items):
    cutoff = (now() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    keep = []
    for it in items:
        if it.get("date", "") < cutoff:
            for fname in (it.get("file"), it.get("bg")):
                if fname:
                    try:
                        os.remove(os.path.join(OUT, fname))
                    except OSError:
                        pass
            print("updates: deleted old card " + it.get("id", ""))
        else:
            keep.append(it)
    return keep


def main():
    state = load(STATE, {"initialized": False, "ready": {}, "news": []})
    courses = load(COURSES, [])
    items = load(OUT + "/index.json", [])
    events = lesson_events(state, courses) + news_events(state)
    os.makedirs(OUT, exist_ok=True)
    ai_left = MAX_AI_PER_RUN
    for ev in events:
        name = today() + "-" + hashlib.sha1(ev["key"].encode("utf-8")).hexdigest()[:8]
        bg = None
        if USE_AI and ai_left > 0:
            ai_left -= 1
            bg = make_background(ev["kind"], name)
        with open(os.path.join(OUT, name + ".svg"), "w", encoding="utf-8") as f:
            f.write(card_svg(ev, bg, today()))
        items.insert(0, {"id": name, "date": today(), "kind": ev["kind"], "title": ev["title"],
                         "text": ev["text"], "file": name + ".svg", "bg": bg})
        print("updates: made " + name + " (" + ev["kind"] + ")")
    items = cleanup(items)
    save(OUT + "/index.json", items)
    state["initialized"] = True
    save(STATE, state)
    print("updates: " + str(len(events)) + " new, " + str(len(items)) + " cards on the page")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never stop the daily run
        print("updates: stopped: " + str(e))
