"""Generates course outlines and lessons with Groq and saves them as JSON in /courses.
courses.txt: one course per line, e.g.  Calculus I [maths] [long] | extra notes
  [maths] = formulas written in LaTeX      [long] = longer, multi-part lessons
Optional syllabus: save it as syllabi/<course-name-with-dashes>.txt and the lessons follow it.
Keys: the GROQ_API_KEY secret may hold several keys separated by commas.
Models: set MODELS (comma separated) to change the fallback order.
Safe to re-run: finished lessons are skipped and half-written long lessons are resumed."""
import html, json, os, re, sys, time, urllib.parse, urllib.request, urllib.error


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
Create 2 or 3 simple teaching diagrams that make this lesson easier to understand. Pick the best type for each:
- steps (an ordered process): {"type":"steps","title":str,"steps":[{"label":str,"text":"one short sentence"}] (3 to 6),"loop":true if the process repeats}
- compare (two things side by side): {"type":"compare","title":str,"left":{"name":str,"points":[str]},"right":{"name":str,"points":[str]}} (2 to 5 points each)
- facts (key numbers): {"type":"facts","title":str,"items":[{"value":str,"label":str}]} (3 to 4 items)
- parts (parts of one thing and what each does): {"type":"parts","title":str,"items":[{"name":str,"role":str}]} (4 to 6 items)
- graph (maths only, a function of x): {"type":"graph","title":str,"fn":"plain-text expression such as (x^2-4)/(x-2)","xmin":number,"xmax":number,"points":[{"x":number,"y":number,"label":str,"open":true or false}] (optional),"caption":str}
Every diagram also has "after": the number of the section it belongs after. Use only facts that appear in the lesson, keep every text short, and write maths as plain text (x^2, sqrt(x)) with no backslashes.
Reply as JSON: {"diagrams": [ ... ]}"""
IMG_Q = """Lesson "@L@" of course "@T@". Numbered sections (starting at 0):
@D@
Decide whether 1 or 2 real pictures from Wikimedia Commons (labelled anatomy diagrams, maps, life cycles, machine parts, circuit or network diagrams, charts) would genuinely help students understand this lesson. Return an empty list if no picture would help.
Reply as JSON: {"images": [{"query": "2 to 4 plain English search words, e.g. human lung anatomy diagram", "after": number of the section it belongs after, "caption": "one short sentence saying what the picture shows"}]}"""
IMG_PICK = """For each picture need, choose the best Wikimedia Commons file. Prefer clear diagrams labelled in English that match the need exactly. Reject files that are unrelated, in another language, photos of people, or too specialised for students. Use null if none is good enough.
@N@
Reply as JSON: {"choices": [{"need": 0, "pick": "a"}]}"""
COMMONS = "https://commons.wikimedia.org/w/api.php"
UA = "SchoolLearningHub/1.0 (" + (("https://github.com/" + os.environ["GITHUB_REPOSITORY"])
                                  if os.environ.get("GITHUB_REPOSITORY") else "educational project") + ")"
OK_LICENSE = re.compile(r"^(public domain|pd\b|cc0|cc[ -]by(?!-n)(?:[ -]sa)?\b)", re.I)  # free licences only (no NC / ND)
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
    return [g for g in (out.get("diagrams") or []) if isinstance(g, dict) and check(g)][:3]


def commons(q):
    """Free-licensed picture candidates from Wikimedia Commons, or None if the search failed."""
    qs = urllib.parse.urlencode({"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                                 "gsrsearch": q, "gsrlimit": 12, "prop": "imageinfo",
                                 "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 800,
                                 "iiextmetadatafilter": "LicenseShortName|Artist|ImageDescription|Restrictions"})
    try:
        with urllib.request.urlopen(urllib.request.Request(COMMONS + "?" + qs, headers={"User-Agent": UA}), timeout=30) as r:
            pages = json.load(r).get("query", {}).get("pages", {})
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        print("Commons search failed:", e)
        return None
    clean = lambda v: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html.unescape(v))).strip()
    out = []
    for pg in sorted(pages.values(), key=lambda p: p.get("index", 99)):
        try:
            ii = pg["imageinfo"][0]
            md = ii.get("extmetadata", {})
            lic = md.get("LicenseShortName", {}).get("value", "")
            if (not OK_LICENSE.match(lic) or md.get("Restrictions", {}).get("value")
                    or ii["mime"] not in ("image/svg+xml", "image/png", "image/jpeg") or ii["width"] < 500):
                continue
            out.append({"title": pg["title"].replace("File:", ""), "url": ii["thumburl"], "page": ii["descriptionurl"],
                        "credit": clean(md.get("Artist", {}).get("value", "")) or "Wikimedia Commons contributor",
                        "license": lic, "desc": clean(md.get("ImageDescription", {}).get("value", ""))[:120]})
        except (KeyError, IndexError, TypeError):
            continue
    return out[:6]


def find_images(t, d):
    """Picks real, free-licensed pictures from Wikimedia Commons. Returns a list (maybe empty) or None on failure."""
    digest = "\n".join(f"{i}. {s['heading']}: {s['body'][:500]}" for i, s in enumerate(d["sections"]))
    q = ask(IMG_Q.replace("@T@", t).replace("@L@", d["title"]).replace("@D@", digest), max_tokens=800)
    if not isinstance(q, dict):
        return None
    needs = [x for x in (q.get("images") or []) if isinstance(x, dict) and x.get("query")][:2]
    found = []
    for n in needs:
        time.sleep(1)
        c = commons(str(n["query"]))
        if c is None:
            return None
        found.append(c)
    if not any(found):
        return []
    lines = []
    for i, (n, cands) in enumerate(zip(needs, found)):
        lines.append(f'Need {i}: {n.get("caption") or n["query"]}')
        lines += [f"  {'abcdef'[j]}) {c['title']} - {c['desc']}" for j, c in enumerate(cands)]
    out = ask(IMG_PICK.replace("@N@", "\n".join(lines)), max_tokens=600)
    if not isinstance(out, dict):
        return None
    imgs = []
    for ch in out.get("choices") or []:
        try:
            i = int(ch["need"])
            c = found[i]["abcdef".index(str(ch["pick"]).lower()[0])]
        except (KeyError, IndexError, ValueError, TypeError):
            continue
        after = needs[i].get("after")
        imgs.append({"type": "image", "title": str(needs[i].get("caption") or c["title"]), "alt": c["title"],
                     "url": c["url"], "page": c["page"], "credit": c["credit"], "license": c["license"],
                     "after": after if isinstance(after, int) else None})
    return imgs


def enrich(title, d):
    """Adds the drawn diagrams and Commons pictures a lesson is missing. True if anything changed."""
    changed = False
    if "diagrams" not in d:
        dg = make_diagrams(title, d)
        if dg is not None:
            d["diagrams"], changed = dg, True
    if "images_checked" not in d:
        im = find_images(title, d)
        if im is not None:
            d["diagrams"] = im + d.get("diagrams", [])
            d["images_checked"], changed = True, True
    return changed


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
    flags = {f.lower() for f in re.findall(r"\[(\w+)\]", head)}
    return re.sub(r"\[\w+\]", "", head).strip(), notes.strip(), flags


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
            for les in course["lessons"]:  # add diagrams to lessons written before diagrams existed
                lp = f"courses/{cid}/{les['file']}" if les["file"] else ""
                ld = load(lp, None) if lp else None
                if ld and "sections" in ld and ("diagrams" not in ld or "images_checked" not in ld):
                    if used > BUDGET or time.time() - START > MAX_MIN * 60:
                        raise Stop("Token or time budget for this run is used up")
                    if enrich(title, ld):
                        save(lp, ld)
                        print("Added diagrams and pictures to", lp)
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
                enrich(title, d)
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
    print("Done:", made, "new lessons")


if __name__ == "__main__":
    sys.exit(main())
