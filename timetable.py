"""Reads the timetable files in timetable-uploads/ into timetables/<name>.json and timetables/index.json,
which the timetable page shows. A file whose name starts with "exam" is the exam timetable.
Word and PDF files are read from their text (exact). Pictures are read by a vision AI (Groq).
Runs from .github/workflows/timetable.yml. Never put keys in this file."""
import base64, datetime, glob, hashlib, io, json, os, re, time, urllib.error, urllib.request, zipfile

UP, OUT = "timetable-uploads", "timetables"
KEY = (os.environ.get("GROQ_TIMETABLE_KEY") or os.environ.get("GROQ_API_KEY") or "").strip()
TEXT_MODEL = os.environ.get("TT_TEXT_MODEL", "openai/gpt-oss-120b")
VISION_MODEL = os.environ.get("TT_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
URL = "https://api.groq.com/openai/v1/chat/completions"
NV_KEY = (os.environ.get("NVIDIA_API_KEY") or "").strip()
NV_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NV_VISION = os.environ.get("TT_NV_VISION", "meta/llama-3.2-11b-vision-instruct")
PICK = os.environ.get("TT_PICTURE_PROVIDER", "nvidia")  # "nvidia" or "groq" for pictures and scanned PDFs
TEXT_PROVIDER = os.environ.get("TT_TEXT_PROVIDER", "nvidia")  # "nvidia" or "groq" for Word and text PDFs
NV_TEXT = os.environ.get("TT_NV_TEXT", "meta/llama-3.1-70b-instruct")
EXTS = (".jpg", ".jpeg", ".png", ".webp", ".pdf", ".docx")
LOG = []
SCHEMA = """Reply as JSON: {"title": "short title", "kind": "exam or class", "note": "venue or other notes that apply to everything, or empty", "entries": [{"date": "YYYY-MM-DD for an exam timetable, otherwise empty", "day": "Monday", "start": "HH:MM 24-hour", "end": "HH:MM 24-hour", "code": "COURSE CODE such as GST 112", "title": "course title if shown, else empty", "venue": "venue if shown, else empty", "lecturer": "lecturer if shown, else empty"}], "holidays": [{"date": "YYYY-MM-DD", "label": "Public holiday"}]}
Write one entry for every course shown in the table. Do not invent anything that is not in the table. Use 24-hour times (3:15 pm is 15:15 and 12 noon is 12:00). Read the year from the heading. When a row gives a weekday and a date, copy both exactly as written."""


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


def chat(model, content, max_tokens=4000, nvidia=False):
    """One call to Groq or NVIDIA. Returns the parsed JSON reply, or None."""
    key, url = (NV_KEY, NV_URL) if nvidia else (KEY, URL)
    if not key:
        note(f"No {'NVIDIA_API_KEY' if nvidia else 'Groq key'} found, so {model} was not called")
        return None
    body = {"model": model, "temperature": 0, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}
    if not nvidia:
        body["max_completion_tokens"] = body.pop("max_tokens")
        body["response_format"] = {"type": "json_object"}
        if model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = "low"
    data = json.dumps(body).encode()
    for attempt in range(3):
        req = urllib.request.Request(url, data, {"Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": "timetable-reader/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                txt = json.load(r)["choices"][0]["message"]["content"] or ""
            m = re.search(r"\{[\s\S]*\}", txt)  # NVIDIA may wrap the JSON in words
            return json.loads(m.group(0) if m else txt)
        except urllib.error.HTTPError as e:
            body_txt = e.read()[:300].decode("utf8", "ignore")
            if e.code == 429 and attempt < 2:
                time.sleep(min(float(e.headers.get("retry-after") or 20), 60) + 1)
                continue
            note(f"{'NVIDIA' if nvidia else 'Groq'} error {e.code} with {model}: {body_txt[:160]}")
            return None
        except (json.JSONDecodeError, KeyError, TypeError, urllib.error.URLError, OSError):
            time.sleep(3)
    return None


def groq(model, content, max_tokens=4000):
    body = {"model": model, "temperature": 0, "max_completion_tokens": max_tokens, "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": content}]}
    if model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "low"
    data = json.dumps(body).encode()
    for attempt in range(3):
        req = urllib.request.Request(URL, data, {"Authorization": "Bearer " + KEY, "Content-Type": "application/json", "User-Agent": "timetable-reader/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(json.load(r)["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as e:
            txt = e.read()[:300].decode("utf8", "ignore")
            if e.code == 429 and attempt < 2:
                time.sleep(min(float(e.headers.get("retry-after") or 20), 60) + 1)
                continue
            note(f"Groq error {e.code} with {model}: {txt[:160]}")
            return None
        except (json.JSONDecodeError, KeyError, TypeError, urllib.error.URLError, OSError):
            time.sleep(3)
    return None


def file_text(path):
    """Exact text of a Word or PDF file; None for pictures."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        x = zipfile.ZipFile(path).read("word/document.xml").decode("utf8", "ignore")
        cell = lambda t: " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", t)).strip()
        rows = [" | ".join(cell(c) for c in re.findall(r"<w:tc>.*?</w:tc>", tr, re.S)) for tr in re.findall(r"<w:tr[ >].*?</w:tr>", x, re.S)]
        head = [cell(p) for p in re.findall(r"<w:p[ >].*?</w:p>", re.sub(r"<w:tbl>.*?</w:tbl>", "", x, flags=re.S), re.S)]
        return "\n".join([h for h in head if h] + rows)
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            note("PDF reading needs pypdf. Add the line 'pip install pypdf pillow' to the workflow.")
            return ""
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(path).pages)
    return None


def prep_image(raw):
    try:
        from PIL import Image, ImageOps
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
        if max(im.size) > 2200:
            im.thumbnail((2200, 2200))
        b = io.BytesIO()
        im.save(b, "JPEG", quality=88)
        return b.getvalue()
    except Exception:
        return raw if len(raw) < 3_500_000 else None


def pdf_page_image(raw):
    """First page of a PDF as a JPEG, using poppler's pdftoppm (installed by the workflow)."""
    import shutil, subprocess, tempfile
    if not shutil.which("pdftoppm"):
        return None
    with tempfile.TemporaryDirectory() as d:
        open(f"{d}/in.pdf", "wb").write(raw)
        subprocess.run(["pdftoppm", "-r", "200", "-f", "1", "-l", "1", "-jpeg", f"{d}/in.pdf", f"{d}/page"], capture_output=True, timeout=120)
        pages = sorted(glob.glob(f"{d}/page*.jpg"))
        return prep_image(open(pages[0], "rb").read()) if pages else None


def clean(d, stem):
    if not isinstance(d, dict) or not isinstance(d.get("entries"), list):
        return None
    out, warns = [], []
    for e in d["entries"]:
        m = re.search(r"([A-Za-z]{2,4})\s*-?\s*(\d{3})", str(e.get("code", ""))) if isinstance(e, dict) else None
        if not m:
            continue
        code, date, day = f"{m.group(1).upper()} {m.group(2)}", str(e.get("date") or ""), str(e.get("day") or "").strip().title()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            try:
                wd = datetime.date.fromisoformat(date).strftime("%A")
                if day and day != wd:
                    warns.append(f"{code}: the file says {day} but {date} is a {wd}. Check the date.")
                day = wd
            except ValueError:
                date = ""
        out.append({"date": date, "day": day, "start": str(e.get("start") or "")[:5], "end": str(e.get("end") or "")[:5], "code": code,
                    "title": str(e.get("title") or ""), "venue": str(e.get("venue") or ""), "lecturer": str(e.get("lecturer") or "")})
    hol = [{"date": str(h.get("date", "")), "label": str(h.get("label", "Holiday"))} for h in (d.get("holidays") or []) if isinstance(h, dict)]
    return {"kind": "exam" if stem.startswith("exam") or d.get("kind") == "exam" else "class", "title": str(d.get("title") or stem),
            "note": str(d.get("note") or ""), "entries": out, "holidays": hol, "warnings": warns}


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in glob.glob(f"{OUT}/*.json"):
        d = load(f, {}) if os.path.basename(f) != "index.json" else {}
        if isinstance(d, dict) and d.get("source") and not os.path.exists(f"{UP}/{d['source']}"):
            os.remove(f)
            note(f"Removed {os.path.basename(f)} because the file {d['source']} was deleted")
    for f in sorted(glob.glob(f"{UP}/*")):
        if os.path.splitext(f)[1].lower() not in EXTS:
            continue
        name, stem = os.path.basename(f), slug(os.path.splitext(os.path.basename(f))[0])
        raw = open(f, "rb").read()
        sha = hashlib.sha1(raw).hexdigest()
        jp = f"{OUT}/{stem}.json"
        if load(jp, {}).get("sha") == sha:
            continue
        if not (NV_KEY or KEY):
            note(f"{name}: no NVIDIA_API_KEY or Groq key found, so it was not read")
            continue
        hint = "This is an exam timetable. " if stem.startswith("exam") else ""
        text = file_text(f)
        ext = os.path.splitext(f)[1].lower()
        if text is None or (ext == ".pdf" and not text.strip()):
            # pictures, and PDFs with no text layer (scans): look at the page with a vision model
            if ext == ".pdf":
                img = pdf_page_image(raw)
                if img is None:
                    note(f"{name}: this PDF has no text and could not be turned into a picture. Upload a photo of it instead.")
                    continue
            else:
                img = prep_image(raw)
            if img is None:
                note(f"{name}: the picture is too large. Upload a smaller one.")
                continue
            content = [{"type": "text", "text": f'Timetable picture "{name}". {hint}{SCHEMA}\nReply with valid JSON only.'},
                       {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(img).decode()}}]
            if PICK == "nvidia":
                r = chat(NV_VISION, content, 4000, nvidia=True)
                how = f"read from the picture by NVIDIA ({NV_VISION})"
            else:
                r = chat(VISION_MODEL, content, 4000)
                how = f"read from the picture by Groq ({VISION_MODEL})"
        else:
            prompt = f'Timetable file "{name}". {hint}Its text (table rows on separate lines, cells separated by |):\n{text[:9000]}\n{SCHEMA}\nReply with valid JSON only.'
            if TEXT_PROVIDER == "nvidia":
                r = chat(NV_TEXT, prompt, 4000, nvidia=True)
                how = f"read from the text of the file by NVIDIA ({NV_TEXT})"
            else:
                r = chat(TEXT_MODEL, prompt)
                how = f"read from the text of the file by Groq ({TEXT_MODEL})"
        d = clean(r, stem)
        if not d or not d["entries"]:
            note(f"{name}: no courses could be read. It will be tried again on the next run.")
            continue
        d.update({"id": stem, "source": name, "sha": sha, "read": how, "updated": time.strftime("%Y-%m-%d", time.gmtime())})
        json.dump(d, open(jp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        note(f"{name}: {len(d['entries'])} courses {how}" + (f", {len(d['warnings'])} to check" if d["warnings"] else ""))
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
             f"- NVIDIA key found: {'yes' if NV_KEY else 'NO (add NVIDIA_API_KEY)'} | Groq key found: {'yes' if KEY else 'no'}",
             f"- Word and text PDFs: {NV_TEXT + ' (NVIDIA)' if TEXT_PROVIDER == 'nvidia' else TEXT_MODEL + ' (Groq)'} | pictures and scanned PDFs: {NV_VISION + ' (NVIDIA)' if PICK == 'nvidia' else VISION_MODEL + ' (Groq)'}",
             f"- Timetables on the site: {', '.join(i['id'] + ' (' + i['kind'] + ')' for i in items) or 'none'}", "", "## What happened", ""]
    open(f"{OUT}/read-report.md", "w", encoding="utf-8").write("\n".join(lines + [f"- {m}" for m in LOG] or lines) + "\n")


if __name__ == "__main__":
    main()
