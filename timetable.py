"""Reads the timetables you type or upload in timetable-uploads/ and writes timetables/<name>.json plus timetables/index.json
for the timetable page. No AI is used anywhere in this file.

A .txt file starts with @exam or @school (the first line), then one line per course:
    MONDAY 28 SEPT 2026 | 15:15-18:15 | GST 112 | Science Hall          (exam: date, time, course, venue)
    TUESDAY | 08:00-10:00 | COS 101, MTH 102 | Hall A | Dr Musa          (school: weekday, time, courses, venue, lecturer)
    THURSDAY 1 OCT 2026 | PUBLIC HOLIDAY
Lines starting with # are notes. An optional line  @title Second Semester Examination  gives the timetable a title.
A Word (.docx) table is also read exactly, by its grid. Runs from .github/workflows/timetable.yml."""
import datetime, glob, hashlib, json, os, re, time, zipfile

UP, OUT = "timetable-uploads", "timetables"
LOG = []


def note(m):
    print(m)
    LOG.append(m)


def slug(t):
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def load(p, default):
    try:
        return json.load(open(p, encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


# ---- Word timetables are read by their grid (no AI) ----

CODE = re.compile(r"\b([A-Z]{2,4})\s?-?\s?(\d{3})\b")
HOLIDAY = re.compile(r"PUBLIC\s+HOLIDAY|HOLIDAY", re.I)
NOTE = re.compile(r"VENUE|HALL|BE WARNED|EXAMINATION", re.I)
MONTHS = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6, "JUL": 7, "AUG": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11, "DEC": 12}
WEEKDAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]


def _text(xml):
    return " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml)).strip()


def _grid(xml):
    """Rows of cells; each cell is (text, span). Merged cells keep their span."""
    rows = []
    for tr in re.findall(r"<w:tr[ >].*?</w:tr>", xml, re.S):
        cells = []
        for tc in re.findall(r"<w:tc>.*?</w:tc>", tr, re.S):
            m = re.search(r'<w:gridSpan w:val="(\d+)"', tc)
            span = int(m.group(1)) if m else 1
            paras = [_text(p) for p in re.findall(r"<w:p[ >].*?</w:p>|<w:p/>", tc, re.S)]
            cells.append(([p for p in paras if p], span))
        rows.append(cells)
    return rows


def _date(day_cell_lines):
    """'MONDAY 28TH SEPT, 2026' -> (weekday, date). Accepts the day and date on one or two lines."""
    txt = " ".join(day_cell_lines).upper()
    wd = next((w.title() for w in WEEKDAYS if w in txt), "")
    m = re.search(r"(\d{1,2})\s*(?:ST|ND|RD|TH)?\s+([A-Z]{3,4})\S*,?\s*(\d{4})", txt)
    if not m or m.group(2) not in MONTHS:
        return wd, None, "date not understood"
    try:
        d = datetime.date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
        return wd, d.isoformat(), ""
    except ValueError:
        return wd, None, "impossible date"


def read_docx(path):
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf8", "ignore")
    tables = re.findall(r"<w:tbl>.*?</w:tbl>", xml, re.S)
    out = {"entries": [], "holidays": [], "warnings": [], "notes": []}
    if not tables:
        out["warnings"].append("No table found in this file.")
        return out
    rows = _grid(tables[0])
    # time slots come from the header row: columns after the first
    head = rows[0]
    slots = []
    for cell, span in head[1:]:
        t = " ".join(cell)
        m = re.search(r"(\d{1,2}(?::\d{2})?)\s*(am|pm|a\.m\.|p\.m\.|noon)?\s*[-–]\s*(\d{1,2}(?::\d{2})?)\s*(am|pm|a\.m\.|p\.m\.|noon)?", t, re.I)
        slots.append(m.group(0) if m else t)
    # column x of each slot counts the span of every cell
    for cells in rows[1:]:
        if not cells:
            continue
        day_lines, _ = cells[0]
        if len(cells) == 1 and not any(w in " ".join(day_lines).upper() for w in WEEKDAYS):
            out["notes"].append(" ".join(day_lines))  # a full-width note row such as the venue line
            continue
        wd, iso, err = _date(day_lines)
        if err:
            out["warnings"].append(f"Row '{' '.join(day_lines)}': {err}. Check it.")
            continue
        col = 0
        for cell, span in cells[1:]:
            text = " ".join(cell).strip()
            if not text:
                col += span
                continue
            if span >= len(slots) or HOLIDAY.search(text):
                out["holidays"].append({"date": iso, "label": text.title()})
            elif NOTE.search(text) and not CODE.search(text):
                out["notes"].append(text)
            else:
                start_end = slots[col] if col < len(slots) else ""
                times = re.findall(r"\d{1,2}(?::\d{2})?", start_end)
                s = _hhmm(times[0], start_end) if times else ""
                e = _hhmm(times[1], start_end) if len(times) > 1 else ""
                codes = [f"{a} {b}" for a, b in CODE.findall(text.upper())]
                if not codes:
                    out["warnings"].append(f"{iso} {wd}: could not find a course code in '{text}'.")
                for code in codes:
                    entry = {"date": iso, "day": wd, "start": s, "end": e, "code": code, "title": "", "venue": "", "lecturer": ""}
                    out["entries"].append(entry)
            col += span
    # a weekday that disagrees with its date is a warning, not a silent fix
    for en in out["entries"]:
        actual = datetime.date.fromisoformat(en["date"]).strftime("%A") if en["date"] else ""
        if en["day"] and actual and en["day"].upper() != actual.upper():
            out["warnings"].append(f"{en['code']}: the file says {en['day']} but {en['date']} is a {actual}. Check the date.")
    return out


def _hhmm(t, context):
    h, _, mi = t.partition(":")
    h = int(h)
    mi = int(mi or 0)
    pm = bool(re.search(r"p\.?m\.?|noon", context, re.I))
    if pm and h < 12:
        h += 12
    if not pm and h == 12:
        h = 12
    return f"{h:02d}:{mi:02d}"


# ---- Typed text timetables ----
T_CODE = re.compile(r"\b([A-Z]{2,4})\s?-?\s?(\d{3}[A-Z]?)\b")
T_DAYS = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
T_MONTHS = {"JANUARY": 1, "JAN": 1, "FEBRUARY": 2, "FEB": 2, "MARCH": 3, "MAR": 3, "APRIL": 4, "APR": 4, "MAY": 5, "JUNE": 6, "JUN": 6,
            "JULY": 7, "JUL": 7, "AUGUST": 8, "AUG": 8, "SEPTEMBER": 9, "SEPT": 9, "SEP": 9, "OCTOBER": 10, "OCT": 10,
            "NOVEMBER": 11, "NOV": 11, "DECEMBER": 12, "DEC": 12}


def t_when(s):
    """(weekday, ISO date or None) from text such as 'MONDAY 28TH SEPT, 2026', '28/09/2026' or '2026-09-28'."""
    u = s.upper()
    wd = next((d.title() for d in T_DAYS if d in u), "") or next((d.title() for d in T_DAYS if re.search(r"\b" + d[:3] + r"\b", u)), "")
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", u)
    parts = (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    if not parts:
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", u)
        parts = (int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None
    if not parts:
        m = re.search(r"(\d{1,2})\s*(?:ST|ND|RD|TH)?\s+([A-Z]{3,9})\.?,?\s*(\d{4})", u)
        if m and m.group(2) in T_MONTHS:
            parts = (int(m.group(3)), T_MONTHS[m.group(2)], int(m.group(1)))
    try:
        return wd, datetime.date(*parts).isoformat() if parts else None
    except ValueError:
        return wd, None


def t_hm(h, mi, ap):
    h, mi, ap = int(h), int(mi or 0), (ap or "").lower().replace(".", "")
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return h * 60 + mi


def t_time(s):
    """('HH:MM', 'HH:MM') from '15:15-18:15', '3:15pm-6:15pm', '8-11am' or '12 noon-3pm'. None if not understood."""
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.|noon)?\s*(?:-|\u2013|to)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?", s, re.I)
    if not m:
        return None
    h1, m1, a1, h2, m2, a2 = m.groups()
    if a1 and a1.lower() == "noon":
        a1 = "pm"
    if not a1 and a2:
        a1 = a2
        if t_hm(h1, m1, a1) >= t_hm(h2, m2, a2) and a2.lower().startswith("p"):
            a1 = "am"
    start, end = t_hm(h1, m1, a1), t_hm(h2, m2, a2)
    if not a1 and not a2 and end <= start and int(h2) <= 12:
        end += 12 * 60
    if end <= start or end > 24 * 60:
        return None
    return f"{start // 60:02d}:{start % 60:02d}", f"{end // 60:02d}:{end % 60:02d}"


def parse_text(text, stem):
    kind, title, entries, holidays, warns, seen = None, "", [], [], [], set()
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            word = line[1:].strip()
            low = word.lower()
            if low.startswith("title"):
                title = word[5:].strip(" :-")
            elif low.startswith("exam"):
                kind = "exam"
            elif low.startswith(("school", "class", "normal", "lecture")):
                kind = "class"
            else:
                warns.append(f"Line {n}: unknown marker '{line}'. Use @exam or @school.")
            continue
        if kind is None:
            kind = "exam" if stem.startswith("exam") else "class"
            warns.append(f"No @exam or @school line at the top, so this was treated as {'an exam' if kind == 'exam' else 'a school'} timetable.")
        p = [x.strip() for x in line.split("|")]
        wd, date = t_when(p[0])
        if any(re.search(r"holiday", x, re.I) for x in p[1:]) or (len(p) == 1 and re.search(r"holiday", p[0], re.I)):
            label = next((x for x in p[1:] if re.search(r"holiday", x, re.I)), p[0])
            if date:
                holidays.append({"date": date, "label": label.title()})
            else:
                warns.append(f"Line {n}: a holiday needs a date. '{line}'")
            continue
        if len(p) < 3:
            warns.append(f"Line {n}: needs at least day or date | time | course. '{line}'")
            continue
        if kind == "exam" and not date:
            warns.append(f"Line {n}: an exam line needs a date I can read, such as 28 SEPT 2026. '{p[0]}'")
            continue
        if kind == "class" and not wd:
            warns.append(f"Line {n}: a school line needs a weekday, such as MONDAY. '{p[0]}'")
            continue
        tm = t_time(p[1])
        if not tm:
            warns.append(f"Line {n}: could not read the time '{p[1]}'. Write it like 08:00-11:00 or 3:15pm-6:15pm.")
            continue
        pieces = [x.strip() for x in re.split(r"[,/;]", p[2]) if x.strip()]
        codes = []
        for piece in pieces:
            m = T_CODE.search(piece.upper())
            if m:
                codes.append(f"{m.group(1)} {m.group(2)}")
            else:
                warns.append(f"Line {n}: '{piece}' does not look like a course code (such as CSC 201).")
        if date and wd and datetime.date.fromisoformat(date).strftime("%A") != wd:
            warns.append(f"Line {n}: {wd} does not match {date}, which is a {datetime.date.fromisoformat(date).strftime('%A')}. Check the date.")
        if date:
            wd = datetime.date.fromisoformat(date).strftime("%A")
        for code in codes:
            key = (date or wd, tm[0], code)
            if key in seen:
                warns.append(f"Line {n}: {code} is listed twice for {date or wd} at {tm[0]}.")
                continue
            seen.add(key)
            entries.append({"date": date or "", "day": wd, "start": tm[0], "end": tm[1], "code": code, "title": "",
                            "venue": p[3] if len(p) > 3 else "", "lecturer": p[4] if len(p) > 4 else ""})
    return {"kind": kind or "class", "title": title or stem.replace("-", " ").title(), "note": "", "entries": entries,
            "holidays": holidays, "warnings": warns}


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in glob.glob(f"{OUT}/*.json"):
        d = load(f, {}) if os.path.basename(f) != "index.json" else {}
        if isinstance(d, dict) and d.get("source") and not os.path.exists(f"{UP}/{d['source']}"):
            os.remove(f)
            note(f"Removed {os.path.basename(f)} because the file {d['source']} was deleted")
    for f in sorted(glob.glob(f"{UP}/*")):
        name = os.path.basename(f)
        ext = os.path.splitext(f)[1].lower()
        if name.lower().startswith("readme") or ext in (".md", ".json"):
            continue
        stem = slug(os.path.splitext(name)[0])
        raw = open(f, "rb").read()
        sha = hashlib.sha1(raw).hexdigest()
        jp = f"{OUT}/{stem}.json"
        if load(jp, {}).get("sha") == sha:
            continue
        if ext == ".txt":
            d = parse_text(raw.decode("utf-8", "ignore"), stem)
            how = "typed text file"
        elif ext == ".docx":
            try:
                g = read_docx(f)
            except Exception as e:
                note(f"{name}: the Word file could not be read ({str(e)[:80]}).")
                continue
            d = {"kind": "exam" if stem.startswith("exam") else "class", "title": stem.replace("-", " ").title(), "note": "",
                 "entries": g["entries"], "holidays": g["holidays"], "warnings": g["warnings"]}
            how = "Word table"
        else:
            note(f"{name}: skipped. Type the timetable in a .txt file instead (see the example files).")
            continue
        if not d["entries"]:
            note(f"{name}: no courses were read from it.")
            for w in d["warnings"]:
                note("  Check: " + w)
            continue
        d.update({"id": stem, "source": name, "sha": sha, "read": how + " (no AI)", "updated": time.strftime("%Y-%m-%d", time.gmtime())})
        json.dump(d, open(jp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        note(f"{name}: {len(d['entries'])} course slots, {len(d['holidays'])} holidays ({d['kind']})" + (f", {len(d['warnings'])} to check" if d["warnings"] else ""))
        for w in d["warnings"]:
            note("  Check: " + w)
    items = []
    for f in sorted(glob.glob(f"{OUT}/*.json")):
        if os.path.basename(f) == "index.json":
            continue
        d = load(f, {})
        items.append({"id": os.path.splitext(os.path.basename(f))[0], "kind": d.get("kind", "class"), "title": d.get("title", ""),
                      "entries": len(d.get("entries", [])), "updated": d.get("updated", ""), "source": d.get("source", ""), "warnings": d.get("warnings", [])})
    json.dump(items, open(f"{OUT}/index.json", "w", encoding="utf-8"), indent=1)
    lines = ["# Timetable reader report", "", time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "",
             f"- Timetables on the site: {', '.join(i['id'] + ' (' + i['kind'] + ')' for i in items) or 'none'}", "", "## What happened", ""]
    open(f"{OUT}/read-report.md", "w", encoding="utf-8").write("\n".join(lines + ([f"- {m}" for m in LOG] or ["- Nothing new to read."])) + "\n")


if __name__ == "__main__":
    main()
