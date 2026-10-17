#!/usr/bin/env python3
"""Learning Hub updates: makes announcement cards for the Updates page, drawn by code (no AI pictures).

Cards are made for new courses, new lessons (since the last run) and each [news] line in news.txt.
Every run redraws all current cards in the current style and deletes cards older than KEEP_DAYS.
Standard library only.
"""
import hashlib
import html
import json
import math
import os
import re
import textwrap
from datetime import datetime, timedelta, timezone

OUT = "courses/updates"
STATE = "courses/updates-state.json"
COURSES = "courses/index.json"
NEWS = "news.txt"
KEEP_DAYS = 15
ZONE = timezone(timedelta(hours=1))  # Nigeria time

STYLE = {
    "lesson": {"label": "NEW LESSON", "top": "#0f3a2a", "bottom": "#2a7457", "accent": "#e8c96a"},
    "course": {"label": "NEW COURSE", "top": "#0c2c4a", "bottom": "#2a6aa0", "accent": "#f2d27a"},
    "news": {"label": "NEWS", "top": "#4a1414", "bottom": "#9a3324", "accent": "#f0cf6e"},
}
NEWS_TITLE = "School news"
W, H = 1200, 675
TEXT_LEFT, TEXT_RIGHT = 110, 1090
BODY_BOTTOM = 530


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


def is_real(text):
    """A news line must contain at least one real word (3+ letters), so stray dots are ignored."""
    return re.search(r"[A-Za-z]{3,}", text or "") is not None


def read_news():
    try:
        with open(NEWS, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    found = []
    for line in lines:
        m = re.search(r"\[news\]\s*(.+)", line, re.I)
        if m and is_real(m.group(1)):
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
        current[cid] = {"title": c.get("title") or cid,
                        "ready": int(c.get("ready") or 0),
                        "total": int(c.get("total") or 0)}
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
            events.append({"kind": "news", "title": NEWS_TITLE, "text": text, "key": "news:" + h})
    state["news"] = sorted(seen)
    return events


def fit_title(text, max_w):
    """Biggest title size that fits in two lines."""
    for size in (66, 58, 50, 44):
        width = max(8, int(max_w / (size * 0.56)))
        lines = textwrap.wrap(text, width=width) or [""]
        if len(lines) <= 2:
            return size, lines
    size = 44
    lines = textwrap.wrap(text, width=max(8, int(max_w / (size * 0.56)))) or [""]
    if len(lines) > 2:
        lines = lines[:2]
        lines[-1] = lines[-1].rstrip(" ,.;:") + "..."
    return size, lines


def fit_body(text, max_w, top):
    """Biggest body size where the whole text fits above the footer. Truncates only as a last resort."""
    for size in (38, 34, 30, 27):
        line_h = size * 1.42
        max_lines = max(1, int((BODY_BOTTOM - top) / line_h) + 1)
        width = max(10, int(max_w / (size * 0.5)))
        lines = textwrap.wrap(text, width=width) or [""]
        if len(lines) <= max_lines:
            return size, lines, line_h
    size = 27
    line_h = size * 1.42
    max_lines = max(1, int((BODY_BOTTOM - top) / line_h) + 1)
    lines = textwrap.wrap(text, width=max(10, int(max_w / (size * 0.5)))) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(" ,.;:") + "..."
    return size, lines, line_h


def icon(kind, accent):
    """Simple drawn icons, so no emoji fonts are needed."""
    if kind == "lesson":
        return ('<g transform="translate(1000,130)" fill="none" stroke="%s" stroke-width="6" stroke-linejoin="round">'
                '<path d="M-42,-26 Q-18,-36 0,-22 Q18,-36 42,-26 L42,28 Q18,18 0,30 Q-18,18 -42,28 Z"/>'
                '<line x1="0" y1="-22" x2="0" y2="30"/></g>' % accent)
    if kind == "course":
        pts = []
        for i in range(10):
            r = 44 if i % 2 == 0 else 19
            a = -math.pi / 2 + i * math.pi / 5
            pts.append("%.1f,%.1f" % (r * math.cos(a), r * math.sin(a)))
        return '<g transform="translate(1000,130)"><polygon points="%s" fill="%s"/></g>' % (" ".join(pts), accent)
    return ('<g transform="translate(1000,130)" fill="%s">'
            '<path d="M-44,-12 L-18,-12 L24,-40 L24,40 L-18,12 L-44,12 Z"/>'
            '<path d="M36,-14 Q48,0 36,14" fill="none" stroke="%s" stroke-width="6" stroke-linecap="round"/></g>'
            % (accent, accent))


def card_svg(kind, title, text, date):
    st = STYLE.get(kind, STYLE["news"])
    acc = st["accent"]
    if kind == "news":
        title = NEWS_TITLE
    tsize, tlines = fit_title(title, TEXT_RIGHT - TEXT_LEFT - 140)
    title_y = 262
    last_title_y = title_y + (len(tlines) - 1) * tsize * 1.15
    body_top = last_title_y + 62
    bsize, blines, bline_h = fit_body(text, TEXT_RIGHT - TEXT_LEFT, body_top) if text else (0, [], 0)

    parts = ['<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
             '<stop offset="0" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient></defs>'
             % (st["top"], st["bottom"]),
             '<rect width="%d" height="%d" fill="url(#bg)"/>' % (W, H),
             '<circle cx="1110" cy="600" r="200" fill="#ffffff" opacity="0.06"/>',
             '<circle cx="90" cy="60" r="150" fill="#ffffff" opacity="0.05"/>',
             '<rect x="60" y="60" width="%d" height="555" rx="22" fill="none" stroke="%s" stroke-width="4"/>'
             % (W - 120, acc),
             '<rect x="60" y="60" width="%d" height="14" rx="7" fill="%s"/>' % (W - 120, acc),
             icon(kind, acc)]
    label = st["label"]
    badge_w = 60 + len(label) * 18
    parts.append('<rect x="%d" y="110" width="%d" height="48" rx="24" fill="%s"/>' % (TEXT_LEFT, badge_w, acc))
    parts.append('<text x="%d" y="144" font-family="Arial, sans-serif" font-size="24" font-weight="bold" '
                 'letter-spacing="3" fill="%s">%s</text>' % (TEXT_LEFT + 30, st["top"], esc(label)))
    for i, line in enumerate(tlines):
        parts.append('<text x="%d" y="%d" font-family="Georgia, serif" font-size="%d" font-weight="bold" '
                     'fill="#ffffff">%s</text>' % (TEXT_LEFT, title_y + i * tsize * 1.15, tsize, esc(line)))
    if blines:
        y = body_top
        for line in blines:
            parts.append('<text x="%d" y="%d" font-family="Arial, sans-serif" font-size="%d" fill="#f7f3e8">%s</text>'
                         % (TEXT_LEFT, y, bsize, esc(line)))
            y += bline_h
    parts.append('<line x1="%d" y1="555" x2="%d" y2="555" stroke="%s" stroke-opacity="0.6" stroke-width="2"/>'
                 % (TEXT_LEFT, TEXT_RIGHT, acc))
    parts.append('<text x="%d" y="592" font-family="Arial, sans-serif" font-size="24" fill="%s">'
                 'Learning Hub  |  FUE Kontagora</text>' % (TEXT_LEFT, acc))
    parts.append('<text x="%d" y="592" text-anchor="end" font-family="Arial, sans-serif" font-size="24" '
                 'fill="%s">%s</text>' % (TEXT_RIGHT, acc, esc(date)))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" width="%d" height="%d">%s</svg>'
            % (W, H, W, H, "".join(parts)))


def drop_files(it):
    for fname in (it.get("file"), it.get("bg")):
        if fname:
            try:
                os.remove(os.path.join(OUT, fname))
            except OSError:
                pass


def cleanup(items):
    cutoff = (now() - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    keep = []
    for it in items:
        bad_news = it.get("kind") == "news" and not is_real(it.get("text", ""))
        if bad_news or it.get("date", "") < cutoff:
            drop_files(it)
            print("updates: removed card " + it.get("id", ""))
        else:
            keep.append(it)
    return keep


def main():
    state = load(STATE, {"initialized": False, "ready": {}, "news": []})
    courses = load(COURSES, [])
    items = load(OUT + "/index.json", [])
    events = lesson_events(state, courses) + news_events(state)
    os.makedirs(OUT, exist_ok=True)
    for ev in events:
        name = today() + "-" + hashlib.sha1(ev["key"].encode("utf-8")).hexdigest()[:8]
        items.insert(0, {"id": name, "date": today(), "kind": ev["kind"], "title": ev["title"],
                         "text": ev["text"], "file": name + ".svg"})
        print("updates: made " + name + " (" + ev["kind"] + ")")
    items = cleanup(items)
    for it in items:
        if it.get("bg"):  # old AI pictures are no longer used
            drop_files({"bg": it["bg"]})
            it["bg"] = None
        it["file"] = it.get("file") or it["id"] + ".svg"
        with open(os.path.join(OUT, it["file"]), "w", encoding="utf-8") as f:
            f.write(card_svg(it["kind"], it["title"], it.get("text", ""), it["date"]))
    save(OUT + "/index.json", items)
    state["initialized"] = True
    save(STATE, state)
    print("updates: " + str(len(events)) + " new, " + str(len(items)) + " cards on the page")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never stop the daily run
        print("updates: stopped: " + str(e))
