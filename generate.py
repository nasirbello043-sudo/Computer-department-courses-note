"""Generates course outlines and lessons with Groq and saves them as JSON in /courses.
courses.txt: one course per line, e.g.  Calculus I [maths] [long] | extra notes
  [maths] = formulas written in LaTeX      [long] = longer, multi-part lessons
Optional syllabus: save it as syllabi/<course-name-with-dashes>.txt and the lessons follow it.
Keys: the GROQ_API_KEY secret may hold several keys separated by commas.
Models: set MODELS (comma separated) to change the fallback order.
Safe to re-run: finished lessons are skipped and half-written long lessons are resumed."""
import json, os, re, sys, time, urllib.request, urllib.error


def names(*envs, default=""):
    for n in envs:
        v = os.environ.get(n, "").strip()
        if v:
            return [x for x in re.split(r"[\s,]+", v) if x]
    return [x for x in re.split(r"[\s,]+", default) if x]


KEYS = names("GROQ_API_KEYS", "GROQ_API_KEY")
MODELS = names("MODELS", "MODEL", default="openai/gpt-oss-120b,openai/gpt-oss-20b,llama-3.3-70b-versatile")
if not KEYS:
    sys.exit("No Groq key found. Add the GROQ_API_KEY secret.")
SLOTS = [(m, k) for m in MODELS for k in KEYS]  # tried in order; a slot is dropped when its daily limit is hit
dead = set()
BUDGET = int(os.environ.get("TOKEN_BUDGET", "1000000"))
TPM = int(os.environ.get("TOKENS_PER_MINUTE", "7000"))  # pacing under the per-minute limit
PER_COURSE = int(os.environ.get("LESSONS_PER_COURSE", "10"))
MAX_MIN = int(os.environ.get("MAX_MINUTES", "45"))  # stop early so the results always get saved
URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM = ("You write clear, accurate course material for secondary-school and early-university students. "
          "Use simple English, concrete examples and short paragraphs. Never invent facts.")
MATH_TEXT = "Write all maths in LaTeX inside $...$ (inline) or $$...$$ (display). "
MATH_JSON = ("In this JSON reply write maths in plain text only (x^2, sqrt(x), a/b, pi, integral of f(x) dx) "
             "and do not use LaTeX or backslashes. ")

OUTLINE = ('Course: "{t}". Notes: {n}\nGive an ordered outline of exactly {k} lessons that teach this course '
           'from basics to confident use. Reply as {{"lessons": [{{"title": str, "focus": "what it covers"}}]}}')
OUTLINE_SYL = ('Course: "{t}". Below is the official syllabus. Turn it into an ordered list of lessons that covers EVERY '
               'topic in it, in its order. Split big topics into several lessons and merge tiny ones.\nSYLLABUS:\n{s}\n'
               'Reply as {{"lessons": [{{"title": str, "focus": "the syllabus points this lesson must cover"}}]}}')
SHAPE = ('"key_terms": [{{"term": str, "meaning": str}}], "quiz": [{{"q": str, "options": [4 strings], '
         '"answer": index 0-3, "why": "one sentence"}}], "flashcards": [{{"front": str, "back": str}}]')
LESSON = ('Course: "{t}". Write lesson {i} of {k}: "{l}". It must cover: {f}\nOther lessons: {o}\n{m}'
          'Reply as JSON with exactly these keys: {{"title": str, "summary": "2 sentences", '
          '"sections": [{{"heading": str, "body": "2-3 short paragraphs separated by \\n\\n", "code": "optional example or empty string"}}] '
          '(3 to 4 sections), ' + SHAPE + '}} with 4-6 key terms, 4 quiz questions, 5 flashcards.')
PLAN = ('Course: "{t}". Plan a long, thorough lesson {i} of {k}: "{l}". It must cover: {f}\nOther lessons: {o}\n'
        'Reply as JSON: {{"summary": "2 sentences", "sections": [{{"heading": str, "points": "what this section teaches"}}]}} '
        'with 6 to 8 sections. If the subject involves calculation, end with a "Practice problems" section.')
SECTION = ('Course: "{t}", lesson "{l}". Lesson plan: {plan}\n{m}Write ONLY the body of the section "{h}" ({pts}).\n'
           'Format rules: plain Markdown. No headings, no horizontal lines, do not repeat the section title. '
           'No tables unless it is a small table of values (at most 5 rows). Short paragraphs, **bold** for key terms, '
           '"- " for bullet lists. Put every important equation on its own line between $$ and $$; keep formulas inside '
           'sentences between single $ signs. Never use \\[ \\] or \\( \\).\n'
           'For worked examples number the steps (1., 2., 3.), say in words what you do in each step, and show one '
           'displayed equation per step. For a "Practice problems" section give 4 problems, each followed by a full '
           'worked solution. Length: 350 to 500 words.')
EXTRAS = ('Lesson "{l}" of course "{t}". Sections:\n{d}\n{m}Reply as JSON: {{' + SHAPE + '}} with 6-8 key terms, '
          '6 quiz questions based on the sections, 8 flashcards.')

DIAGRAMS = """Lesson "@L@" of course "@T@". Numbered sections (starting at 0):
@D@
Create the simple teaching diagrams this lesson needs: as many as genuinely help (usually 2 to 5) and none that are filler. Pick the best type for each:
- steps (an ordered process): {"type":"steps","title":str,"steps":[{"label":"a short meaningful name such as Plant legumes, never just Step 1","text":"one short sentence"}] (3 to 6),"loop":true if the process repeats}
- compare (two things side by side): {"type":"compare","title":str,"left":{"name":str,"points":[str]},"right":{"name":str,"points":[str]}} (2 to 5 points each)
- facts (key numbers): {"type":"facts","title":str,"items":[{"value":str,"label":str}]} (3 to 4 items)
- parts (parts of one thing and what each does): {"type":"parts","title":str,"items":[{"name":str,"role":str}]} (4 to 6 items)
- graph (maths only, a function of x): {"type":"graph","title":str,"fn":"plain-text expression such as (x^2-4)/(x-2)","xmin":number,"xmax":number,"points":[{"x":number,"y":number,"label":str,"open":true or false}] (optional),"caption":str}
Every diagram also has "after": the number of the section it belongs after. Use only facts that appear in the lesson, keep every text short, and write maths as plain text (x^2, sqrt(x)) with no backslashes.
Reply as JSON: {"diagrams": [ ... ]}"""
IMG_PLAN = """Lesson "@L@" of course "@T@". Numbered sections (starting at 0):
@D@
@K@
Suggest the pictures that would genuinely help students understand this lesson, and rate each one. Pictures are for things that are visual by nature: anatomy and body systems, structures, real objects and equipment, machines, apparatus, maps, life cycles, plants and animals, soil layers, circuits, processes that are easier to see than to read. Never request a picture for definitions, abstract ideas, code, calculations, graphs of functions or lists, because the site draws its own simple diagrams (step lists, comparisons, fact boxes, parts lists, graphs). Give at most 3 pictures, and return an empty list if none would really help. Only the best pictures of the whole course will be used, so be honest with the priority.
Reply as JSON: {"images": [{"priority": 1 to 10 (10 = students could hardly understand the topic without it, 7 = clearly helpful, 4 = nice to have), "picture_title": "short title shown on the picture, 2 to 6 words", "caption": "one sentence saying what the picture shows (students will read it)", "kind": "labelled diagram, photo, map, life cycle or illustration", "after": number of the section it belongs after, "subject": "precisely what is shown, 1 to 3 sentences", "layout": "how it is arranged, for example: the whole heart in the centre with labels on both sides and a line pointing to each part", "labels": ["short exact label texts, at most 12; empty for a photo"]}]}"""
IMG_DIR = "courses/images"
IMAGES_PER_COURSE = int(os.environ.get("IMAGES_PER_COURSE", "12"))  # most pictures asked for per course
EXTS = ("png", "jpg", "jpeg", "webp", "svg")
SAFE_IDS = {"x", "sin", "cos", "tan", "sqrt", "abs", "ln", "log", "exp", "pi", "e"}


class DailyLimit(Exception):
    pass


class Stop(Exception):
    pass


used = 0
START = time.time()
models_seen = set()


def ask(prompt, as_json=True, max_tokens=4500, tries=4):
    global used
    attempts = 0
    user = prompt + ("\nReply with valid JSON only." if as_json else "")
    while attempts < tries:
        slot = next((s for s in SLOTS if s not in dead), None)
        if not slot:
            raise DailyLimit("Every key and model has reached its limit")
        model, key = slot
        payload = {"model": model, "temperature": 0.4, "max_completion_tokens": max_tokens,
                   "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]}
        if as_json:
            payload["response_format"] = {"type": "json_object"}
        if model.startswith("openai/gpt-oss"):
            payload["reasoning_effort"] = "low"
        req = urllib.request.Request(URL, json.dumps(payload).encode(),
                                     {"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                      "User-Agent": "school-course-generator/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
            tokens = data.get("usage", {}).get("total_tokens", 3000)
            used += tokens
            models_seen.add(model)
            time.sleep(tokens * 60 / TPM)  # stay under the per-minute token limit
            text = (data["choices"][0]["message"]["content"] or "").strip()
            if not text:
                attempts += 1
                continue
            return json.loads(text) if as_json else text
        except urllib.error.HTTPError as e:
            body = e.read()[:400]
            low = body.lower()
            if e.code == 429:
                wait = float(e.headers.get("retry-after") or 30)
                if wait > 180 or b"per day" in low or b"tpd" in low or b"rpd" in low:
                    print("Daily limit reached for", model, "- switching to the next key or model")
                    dead.add(slot)
                else:
                    time.sleep(wait + 1)
                    attempts += 1
            elif e.code in (401, 403):
                print("A key was rejected - skipping it")
                dead.update(s for s in SLOTS if s[1] == key)
            elif e.code == 404 or b"model_not_found" in low or b"decommissioned" in low:
                print("Model not available:", model)
                dead.update(s for s in SLOTS if s[0] == model)
            elif e.code >= 500:
                time.sleep(10)
                attempts += 1
            else:
                print("HTTP", e.code, body)  # e.g. invalid JSON from the model: retry, then skip
                time.sleep(3)
                attempts += 1
        except (json.JSONDecodeError, KeyError, TypeError, urllib.error.URLError):
            print("Unreadable reply, retrying")
            time.sleep(5)
            attempts += 1
    return None


def corrupt(d):
    """LaTeX like \\frac or \\times written with single backslashes turns into control characters in JSON."""
    s = json.dumps(d, ensure_ascii=False)
    return bool(re.search(r"(?<!\\)(?:\\\\)*\\(?:[fbrt]|n(?:eq\b|abla))", s))


def good(d, maths):
    try:
        ok = (len(d["quiz"]) >= 3 and len(d["flashcards"]) >= 3 and len(d["key_terms"]) >= 3
              and all(len(q["options"]) == 4 and q["answer"] in range(4) for q in d["quiz"]))
    except (KeyError, TypeError):
        return False
    return ok and not (maths and corrupt(d))


def write_lesson(t, i, k, les, titles, flags, dpath):
    maths = bool(flags & {"maths", "math"})
    ctx = dict(t=t, i=i, k=k, l=les["title"], o="; ".join(titles),
               f=les.get("focus") or "the usual content of this topic")
    if "long" not in flags:
        for _ in range(2):
            d = ask(LESSON.format(m=MATH_JSON if maths else "", **ctx))
            if d and len(d.get("sections", [])) >= 2 and good(d, maths):
                return d
        return None
    draft = load(dpath, {})  # progress is saved after every section, so a stop never wastes work
    plan = draft.get("plan") or ask(PLAN.format(**ctx))
    if not plan or len(plan.get("sections", [])) < 4:
        return None
    draft["plan"] = plan
    secs = draft.setdefault("secs", [])
    outline = "; ".join(s["heading"] for s in plan["sections"])
    for s in plan["sections"][len(secs):]:
        body = ask(SECTION.format(t=t, l=les["title"], plan=outline, h=s["heading"], pts=s.get("points", ""),
                                  m=MATH_TEXT if maths else ""), as_json=False, max_tokens=2500)
        if not body:
            save(dpath, draft)
            return None
        secs.append({"heading": s["heading"], "body": body, "code": ""})
        save(dpath, draft)
    digest = "\n".join(f"## {s['heading']}\n{s['body'][:900]}" for s in secs)
    ex = ask(EXTRAS.format(t=t, l=les["title"], d=digest, m=MATH_JSON if maths else ""))
    if not ex or not good(ex, maths):
        return None
    return {"title": les["title"], "summary": plan.get("summary", ""), "sections": secs,
            "key_terms": ex["key_terms"], "quiz": ex["quiz"], "flashcards": ex["flashcards"]}


def ok_expr(e):
    e = str(e).lower()
    return bool(re.fullmatch(r"[0-9a-z+\-*/^().,\s]+", e)) and all(i in SAFE_IDS for i in re.findall(r"[a-z]+", e))


def check(g):
    try:
        t = g.get("type")
        if t == "steps":
            return 3 <= len(g["steps"]) <= 8 and all(x.get("label") for x in g["steps"])
        if t == "compare":
            return all(g[k].get("name") and len(g[k]["points"]) >= 2 for k in ("left", "right"))
        if t == "facts":
            return len(g["items"]) >= 2 and all(x.get("value") and x.get("label") for x in g["items"])
        if t == "parts":
            return len(g["items"]) >= 3 and all(x.get("name") for x in g["items"])
        if t == "graph":
            return ok_expr(g["fn"]) and float(g["xmin"]) < float(g["xmax"])
    except (KeyError, TypeError, AttributeError, ValueError):
        return False
    return False


def make_diagrams(t, d):
    """Returns a list of valid diagrams (maybe empty), or None if the model call failed."""
    digest = "\n".join(f"{i}. {s['heading']}: {s['body'][:700]}" for i, s in enumerate(d["sections"]))
    out = ask(DIAGRAMS.replace("@T@", t).replace("@L@", d["title"]).replace("@D@", digest), max_tokens=3000)
    if not isinstance(out, dict):
        return None
    return [g for g in (out.get("diagrams") or []) if isinstance(g, dict) and check(g)][:5]


STYLE = ("Style: clean modern textbook illustration on a plain white background, soft natural colours with strong "
         "contrast, large easy-to-read sans-serif text, uncluttered, landscape orientation (4:3), high resolution. "
         "No watermark, no decorative border, no extra words.")
PHOTO_STYLE = "Style: realistic, well-lit, sharp photograph with natural colours, landscape orientation (4:3). No text, no watermark, no logos."


def build_prompt(g):
    """The ready-to-paste prompt for an AI image maker. Edit image-style.txt in the repo to change the style."""
    kind, subject = g.get("kind", "labelled diagram"), g.get("subject") or g.get("title", "")
    if "photo" in kind.lower():
        return f"Create a realistic photograph for a school lesson: {subject}\n\n{PHOTO_STYLE}"
    style = STYLE
    if os.path.exists("image-style.txt"):
        style = open("image-style.txt", encoding="utf-8").read().strip() or STYLE
    parts = [f'Create a clear, accurate educational {kind} for secondary-school students, titled "{g.get("picture_title") or g.get("title", "")}".',
             f"Show: {subject}"]
    if g.get("layout"):
        parts.append(f"Layout: {g['layout']}")
    if g.get("labels"):
        parts.append("Use exactly these text labels, each spelled exactly as written and joined by a thin line to the "
                     "correct part. Do not add any other words except the title:\n" + "\n".join(f"- {l}" for l in g["labels"]))
    else:
        parts.append("Do not add any text except the title.")
    parts.append(style)
    return "\n\n".join(parts)


def plan_images(cid, no, d, kept):
    """Pictures this lesson really needs (often none). A list (maybe empty), or None if the model call failed."""
    digest = "\n".join(f"{i}. {x['heading']}: {x['body'][:500]}" for i, x in enumerate(d["sections"]))
    known = ("Pictures already added to this lesson: " + "; ".join(g.get("title", "") for g in kept) +
             ". Do not suggest these again.") if kept else ""
    q = ask(IMG_PLAN.replace("@T@", cid).replace("@L@", d["title"]).replace("@D@", digest).replace("@K@", known),
            max_tokens=2000)
    if not isinstance(q, dict):
        return None
    out, names = [], {g["file"] for g in kept if g.get("file")}
    for x in q.get("images") or []:
        if not isinstance(x, dict) or not x.get("caption") or not x.get("subject"):
            continue
        base = f"{cid}-l{no:02d}-" + (slug(str(x.get("picture_title") or x["caption"]))[:40].strip("-") or "picture")
        name, n = base, 2
        while name in names:
            name, n = f"{base}-{n}", n + 1
        names.add(name)
        labels, after = x.get("labels"), x.get("after")
        try:
            priority = max(1, min(10, int(float(x.get("priority", 6)))))
        except (TypeError, ValueError):
            priority = 6
        out.append({"type": "image", "file": name, "title": str(x["caption"]), "alt": str(x["caption"]),
                    "priority": priority,
                    "picture_title": str(x.get("picture_title", "")), "kind": str(x.get("kind", "labelled diagram")),
                    "subject": str(x["subject"]), "layout": str(x.get("layout", "")),
                    "labels": [str(l) for l in labels][:12] if isinstance(labels, list) else [],
                    "after": after if isinstance(after, int) else None})
    return out[:3]


def have(name):
    return any(os.path.exists(f"{IMG_DIR}/{name}.{e}") for e in EXTS)


def enrich(title, cid, no, d):
    """Adds the drawn diagrams and picture requests a lesson is missing. True if anything changed."""
    changed = False
    if "diagrams" not in d:
        dg = make_diagrams(title, d)
        if dg is not None:
            d["diagrams"], changed = dg, True
    if d.get("images_version") != 5:
        imgs = [g for g in d.get("diagrams", []) if g.get("type") == "image"]
        kept = [g for g in imgs if g.get("file") and have(g["file"])]  # pictures you already uploaded stay
        rest = [g for g in d.get("diagrams", []) if g.get("type") != "image"]
        d["diagrams"] = kept + rest
        changed = changed or len(imgs) != len(kept)
        new = plan_images(cid, no, d, kept)
        if new is not None:
            d["diagrams"] = kept + new + rest
            d["images_version"], changed = 5, True
    return changed


def write_requests(entries):
    """Writes courses/image-requests.md: only the pictures still waiting, each with its file name and prompt."""
    os.makedirs(IMG_DIR, exist_ok=True)
    readme = f"{IMG_DIR}/README.md"
    if not os.path.exists(readme):
        open(readme, "w", encoding="utf-8").write(
            "Upload lesson pictures here. File names must match courses/image-requests.md exactly "
            "(png, jpg, jpeg, webp or svg).\n")
    todo, done = [], 0
    for title, _, flags in entries:
        cap = next((int(f.split("=")[1]) for f in flags if re.fullmatch(r"images=\d+", f)), IMAGES_PER_COURSE)
        c = load(f"courses/{slug(title)}/course.json", None)
        have_n, pending = 0, []
        for i, les in enumerate((c or {}).get("lessons", []), 1):
            d = load(f"courses/{slug(title)}/{les['file']}", None) if les["file"] else None
            for g in (d or {}).get("diagrams", []):
                if g.get("type") == "image" and g.get("file"):
                    if have(g["file"]):
                        have_n += 1
                    elif g.get("subject") and g.get("priority", 6) >= 5:
                        pending.append((i, c["title"], les["title"], g))
        done += have_n
        best = sorted(pending, key=lambda t: (-t[3].get("priority", 6), t[0]))[:max(0, cap - have_n)]  # best ones fill the cap
        todo += [(ct, i, lt, g) for i, ct, lt, g in sorted(best, key=lambda t: t[0])]
    lines = ["# Pictures to add", "", f"Waiting: **{len(todo)}** | Uploaded: **{done}**", ""]
    last = (None, None)
    for ct, i, lt, g in todo:
        if last[0] != ct:
            lines += [f"## {ct}", ""]
        if last != (ct, i):
            lines += [f"### Lesson {i}: {lt}", ""]
        last = (ct, i)
        lines += ["Save as:", "```", g["file"] + ".png", "```", "Prompt:", "```", build_prompt(g), "```", ""]
    open("courses/image-requests.md", "w", encoding="utf-8").write("\n".join(lines))


def make_outline(title, notes, syllabus):
    prompt = (OUTLINE_SYL.format(t=title, s=syllabus[:7000]) if syllabus
              else OUTLINE.format(t=title, n=notes or "none", k=PER_COURSE))
    out = ask(prompt, max_tokens=6000)
    lessons = []
    for x in (out or {}).get("lessons", []):
        if isinstance(x, str):
            x = {"title": x}
        if isinstance(x, dict) and x.get("title"):
            lessons.append({"title": x["title"], "focus": x.get("focus", ""), "file": None})
    return lessons


def slug(t):
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def parse(line):
    head, _, notes = line.partition("|")
    flags = {f.lower() for f in re.findall(r"\[([\w=]+)\]", head)}
    return re.sub(r"\[[\w=]+\]", "", head).strip(), notes.strip(), flags


def load(p, default):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def save(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(d, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


def main():
    entries = [parse(l) for l in open("courses.txt", encoding="utf-8") if l.strip() and not l.lstrip().startswith("#")]
    made, index = 0, []
    try:
        for title, notes, flags in entries:
            cid = slug(title)
            cpath = f"courses/{cid}/course.json"
            course = load(cpath, None)
            if not course:
                sp = f"syllabi/{cid}.txt"
                syllabus = open(sp, encoding="utf-8").read() if os.path.exists(sp) else ""
                lessons = make_outline(title, notes, syllabus)
                if not lessons:
                    continue
                course = {"title": title, "lessons": lessons}
                save(cpath, course)
            titles = [l["title"] for l in course["lessons"]]
            for no, les in enumerate(course["lessons"], 1):  # add diagrams and picture requests to older lessons
                lp = f"courses/{cid}/{les['file']}" if les["file"] else ""
                ld = load(lp, None) if lp else None
                if ld and "sections" in ld and ("diagrams" not in ld or ld.get("images_version") != 5):
                    if used > BUDGET or time.time() - START > MAX_MIN * 60:
                        raise Stop("Token or time budget for this run is used up")
                    if enrich(title, cid, no, ld):
                        save(lp, ld)
                        print("Updated diagrams and picture list for", lp)
            for i, les in enumerate(course["lessons"], 1):
                if les["file"]:
                    continue
                if used > BUDGET or time.time() - START > MAX_MIN * 60:
                    raise Stop("Token or time budget for this run is used up")
                dpath = f"courses/{cid}/draft-{i:02d}.json"
                models_seen.clear()
                d = write_lesson(title, i, len(titles), les, titles, flags, dpath)
                if not d:
                    print("Skipped lesson", i, les["title"])
                    continue
                enrich(title, cid, i, d)
                d["reviewed"] = False
                d["models"] = sorted(models_seen)
                les["file"] = f"lesson-{i:02d}.json"
                save(f"courses/{cid}/{les['file']}", d)
                save(cpath, course)
                if os.path.exists(dpath):
                    os.remove(dpath)
                made += 1
                print("Wrote", cid, les["file"], "- tokens used so far:", used)
    except (DailyLimit, Stop) as e:
        print(e, "- it will continue on the next run.")
    finally:
        for title, _, _ in entries:
            c = load(f"courses/{slug(title)}/course.json", None)
            if c:
                index.append({"id": slug(title), "title": c["title"], "total": len(c["lessons"]),
                              "ready": sum(1 for l in c["lessons"] if l["file"])})
        save("courses/index.json", index)
        write_requests(entries)
    print("Done:", made, "new lessons")


if __name__ == "__main__":
    sys.exit(main())
