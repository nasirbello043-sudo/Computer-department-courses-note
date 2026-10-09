"""Generates course outlines and lessons with Groq and saves them as JSON in /courses.
courses.txt: one course per line, e.g.  Calculus I [maths] [long] | extra notes
  [maths] = formulas written in LaTeX      [long] = longer, multi-part lessons
Optional syllabus: save it as syllabi/<course-name-with-dashes>.txt and the lessons follow it.
Keys: the GROQ_API_KEY secret may hold several keys separated by commas.
Models: set MODELS (comma separated) to change the fallback order.
Safe to re-run: finished lessons are skipped and half-written long lessons are resumed."""
import base64, json, os, random, re, shutil, sys, time, urllib.request, urllib.error


def names(*envs, default=""):
    for n in envs:
        v = os.environ.get(n, "").strip()
        if v:
            return [x for x in re.split(r"[\s,]+", v) if x]
    return [x for x in re.split(r"[\s,]+", default) if x]


KEYS = names("GROQ_API_KEYS", "GROQ_API_KEY")
MODELS = names("MODELS", "MODEL", default="openai/gpt-oss-120b")
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
- graph (maths only, a function of x): {"type":"graph","title":str,"fn":"plain-text expression such as (x^2-4)/(x-2)","xmin":number,"xmax":number,"points":[{"x":number,"y":number,"label":"1 or 2 words","open":true or false}] (0 to 2 points),"caption":str}
Every diagram also has "after": the number of the section it belongs after. Use only facts that appear in the lesson, keep every text short, and write maths as plain text (x^2, sqrt(x)) with no backslashes.
Reply as JSON: {"diagrams": [ ... ]}"""
IMG_PLAN = """Lesson "@L@" of course "@T@". Numbered sections (starting at 0):
@D@
@K@
Suggest the pictures that would genuinely help students understand this lesson, and rate each one. Pictures are for things that are visual by nature: anatomy and body systems, structures, real objects and equipment, machines, apparatus, maps, life cycles, plants and animals, soil layers, circuits, processes that are easier to see than to read. Never request a picture for definitions, abstract ideas, code, calculations, graphs of functions or lists, because the site draws its own simple diagrams (step lists, comparisons, fact boxes, parts lists, graphs). Give at most 3 pictures, and return an empty list if none would really help. Only the best pictures of the whole course will be used, so be honest with the priority.
Reply as JSON: {"images": [{"priority": 1 to 10 (10 = students could hardly understand the topic without it, 7 = clearly helpful, 4 = nice to have), "picture_title": "short title shown on the picture, 2 to 6 words", "caption": "one sentence saying what the picture shows (students will read it)", "kind": "labelled diagram, photo, map, life cycle or illustration", "after": number of the section it belongs after, "subject": "precisely what is shown, 1 to 3 sentences", "layout": "how it is arranged, for example: the whole heart in the centre with labels on both sides and a line pointing to each part", "labels": ["short exact label texts, at most 8, each 1 to 3 plain words; empty for a photo"]}]}"""
IMG_DIR = "courses/images"
IMAGES_PER_COURSE = int(os.environ.get("IMAGES_PER_COURSE", "12"))  # most pictures asked for per course
EXTS = ("png", "jpg", "jpeg", "webp", "svg")
SAFE_IDS = {"x", "sin", "cos", "tan", "sqrt", "abs", "ln", "log", "exp", "pi", "e"}


def fill(tpl, **kw):
    for k, v in kw.items():
        tpl = tpl.replace("@" + k + "@", str(v))
    return tpl


PLAN2 = """Course: "@T@". Plan lesson @I@ of @K@: "@L@". It must cover: @F@
Other lessons: @O@
You are planning a complete textbook lesson that carries every student along without skipping steps.
Reply as JSON: {"summary": "2 sentences", "objectives": ["3 to 5 things the student can do by the end, each starting with a verb"], "prerequisites": "1 to 2 sentences on what the student should already know, or say that nothing is needed", "why": ["2 short paragraphs on why this matters in real life"], "calculation": true only if students must calculate or solve numerical problems in this lesson, otherwise false, "example_plan": ["only when calculation is true: 7 to 10 clearly different problem types or real scenarios, in order from Easy to Hard, each written like 'Easy: short description'; otherwise an empty list"], "sections": [{"heading": "clear heading", "points": "what this section teaches"}]} with 5 to 7 sections in teaching order, from the simplest idea to the hardest."""
SECTION2 = """Course: "@T@", lesson "@L@". Lesson plan: @P@
@M@Write ONLY the body of the section "@H@" (@X@).
Teach like a patient teacher: start with the idea in plain words, say why it is true or useful, give an everyday comparison, explain every new word the first time it appears, and build up in small steps without skipping any step. Use Markdown with no heading line and no horizontal lines. Put key points in callout lines that start with "> " followed by one of these bold labels exactly: **Definition:**, **Note:**, **In daily life:**, **Common mistake:**, **Remember:**. Use 2 to 4 callouts. Put important equations on their own line between $$ and $$ and keep formulas inside sentences between single $ signs. Never use \\[ \\] or \\( \\). Length: 450 to 650 words."""
WORKED = """Course: "@T@", lesson "@L@". Lesson plan: @P@
@M@Write one worked example for each of these problem types, in this order:
@X@
Every example must be a different type of problem or scenario. Use exactly this line format and nothing else:
EXAMPLE | Level | short title
GIVEN: the situation and what to find
STEP | short label | what we do in this step and why
(3 to 6 STEP lines; one small idea per step; never skip a step)
ANSWER: the final answer with units, or a clear conclusion"""
CLASSIFY = """Course: "@T@", lesson "@L@". Sections:
@D@
Decide whether students must calculate or solve numerical problems in this lesson. Reply as JSON: {"calculation": true or false, "example_plan": ["only when calculation is true: 7 to 10 clearly different problem types or real scenarios, in order from Easy to Hard, each written like 'Easy: short description'; otherwise an empty list"]}"""
PRACTICE = """Course: "@T@", lesson "@L@". Lesson plan: @P@
@M@If the lesson has no calculations, write short-answer questions that ask the student to explain, compare or apply the idea. Write 6 practice questions with full worked answers: 2 Easy, 2 Medium, 2 Hard. Use exactly this line format and nothing else:
PRACTICE | Easy
Q: the question
A: the full worked answer, step by step
(repeat; start each new level with a PRACTICE | Level line)"""
EXTRAS2 = ('Lesson "@L@" of course "@T@". Sections:\n@D@\n@M@Reply as JSON: {"recap": "3 to 4 sentences summing up the lesson", '
           + SHAPE.replace("{{", "{").replace("}}", "}") + '} with 6-8 key terms, 6 quiz questions based on the sections, 8 flashcards.')
STOP = {"introduction", "intro", "to", "of", "and", "the", "i", "ii", "iii", "iv", "for", "in", "basic", "basics", "fundamentals"}


class DailyLimit(Exception):
    pass


class Stop(Exception):
    pass


used = 0
REPORT = []
STATS = {"covers": 0, "pictures": 0, "label_retries": 0, "label_gave_up": 0, "glitches": 0}


def note(msg):
    print(msg)
    REPORT.append(msg)


def glitchy(t):
    """A short chunk repeated over and over (a model glitch such as a long run of \\; spacing commands)."""
    return bool(re.search(r"(.{2,12}?)\1{20,}", t or "", re.S))


def delete_course(cid):
    if os.path.isdir(f"courses/{cid}"):
        shutil.rmtree(f"courses/{cid}")
        note(f"Deleted course {cid} and its lessons")
    for f in (os.listdir(IMG_DIR) if os.path.isdir(IMG_DIR) else []):
        if re.match(re.escape(cid) + r"-l\d\d-", f) or f.startswith(f"cover-{cid}."):
            os.remove(f"{IMG_DIR}/{f}")
            note("Deleted picture " + f)


def clear_ai(cid, course):
    """Deletes pictures and covers the AI drew earlier so they go back on your list to be replaced by your own."""
    if course.get("cover"):
        for e in EXTS:
            f = f"{IMG_DIR}/cover-{cid}.{e}"
            if os.path.exists(f):
                os.remove(f)
        course.pop("cover", None)
        save(f"courses/{cid}/course.json", course)
        note("Removed the AI cover of " + cid)
    for les in course["lessons"]:
        lp = f"courses/{cid}/{les['file']}" if les["file"] else ""
        d = load(lp, None) if lp else None
        changed = False
        for g in (d or {}).get("diagrams", []):
            if g.get("type") == "image" and g.get("ai"):
                for e in EXTS:
                    f = f"{IMG_DIR}/{g['file']}.{e}"
                    if os.path.exists(f):
                        os.remove(f)
                g.pop("ai", None)
                changed = True
                note("Removed AI picture " + g["file"])
        if changed:
            save(lp, d)


def repair_lessons(title, cid, course, flags):
    """Rewrites only the sections that contain a repeated-symbol glitch."""
    mt = MATH_TEXT if flags & {"maths", "math"} else ""
    for les in course["lessons"]:
        lp = f"courses/{cid}/{les['file']}" if les["file"] else ""
        d = load(lp, None) if lp else None
        for sec in (d or {}).get("sections", []):
            if glitchy(sec.get("body", "")):
                if used > BUDGET or time.time() - START > MAX_MIN * 60:
                    return
                outline = "; ".join(x["heading"] for x in d["sections"])
                new = ask(fill(SECTION2, T=title, L=d["title"], P=outline, H=sec["heading"], X="", M=mt), as_json=False, max_tokens=2800)
                if new and not glitchy(new):
                    sec["body"] = new
                    save(lp, d)
                    note(f"Repaired a broken section in {lp}")
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


def parse_examples(t):
    out, cur = [], None
    for line in t.splitlines():
        x, u = line.strip(), line.strip().upper()
        if u.startswith("EXAMPLE"):
            p = [y.strip() for y in x.split("|")] + ["", ""]
            cur = {"level": p[1], "title": p[2] or "Example", "given": "", "steps": [], "answer": ""}
            out.append(cur)
        elif cur is None or not x:
            continue
        elif u.startswith("GIVEN:"):
            cur["given"] = x[6:].strip()
        elif u.startswith("STEP"):
            p = [y.strip() for y in x.split("|", 2)]
            if len(p) == 3:
                cur["steps"].append({"label": p[1], "text": p[2]})
        elif u.startswith("ANSWER:"):
            cur["answer"] = x[7:].strip()
        elif cur["answer"]:
            cur["answer"] += " " + x
        elif cur["steps"]:
            cur["steps"][-1]["text"] += " " + x
        else:
            cur["given"] += " " + x
    return [e for e in out if e["given"] and len(e["steps"]) >= 2 and e["answer"]]


def parse_practice(t):
    out, cur, lvl, mode = [], None, "", "q"
    for line in t.splitlines():
        x, u = line.strip(), line.strip().upper()
        if u.startswith("PRACTICE"):
            lvl = (x.split("|") + ["", ""])[1].strip()
        elif u.startswith("Q:"):
            cur, mode = {"level": lvl, "q": x[2:].strip(), "a": ""}, "q"
            out.append(cur)
        elif u.startswith("A:") and cur:
            cur["a"], mode = x[2:].strip(), "a"
        elif x and cur:
            cur[mode] += ("\n" if mode == "a" else " ") + x
    return [p for p in out if p["q"] and p["a"]]


def gen_examples(t, ltitle, outline, types, mt, dr, dpath=None):
    """Worked examples in batches of 4, one per problem type, saving progress. False if a batch failed."""
    batches = [types[i:i + 4] for i in range(0, len(types), 4)]
    for bi in range(dr.get("ex_batches", 0), len(batches)):
        x = "\n".join(f"{n}. {v}" for n, v in enumerate(batches[bi], 1))
        txt = ask(fill(WORKED, T=t, L=ltitle, P=outline, X=x, M=mt or MATH_TEXT), as_json=False, max_tokens=3500)
        items = parse_examples(txt) if txt and not glitchy(txt) else []
        if not items:
            if dpath:
                save(dpath, dr)
            return False
        dr["examples"] = dr.get("examples", []) + items
        dr["ex_batches"] = bi + 1
        if dpath:
            save(dpath, dr)
    return True


def fix_examples(title, cid, course, flags):
    """Lessons already in the textbook style: no worked examples unless the lesson has calculations, then 7 to 10."""
    for les in course["lessons"]:
        lp = f"courses/{cid}/{les['file']}" if les["file"] else ""
        d = load(lp, None) if lp else None
        if not d or "objectives" not in d or d.get("examples_version") == 2:
            continue
        if used > BUDGET or time.time() - START > MAX_MIN * 60:
            return
        digest = "\n".join(f"## {x['heading']}\n{x['body'][:500]}" for x in d["sections"])
        r = ask(fill(CLASSIFY, T=title, L=d["title"], D=digest), max_tokens=1200)
        if not isinstance(r, dict):
            continue
        plan = r.get("example_plan")
        if r.get("calculation") and isinstance(plan, list) and len(plan) >= 5:
            dr = {"examples": [], "ex_batches": 0}
            if not gen_examples(title, d["title"], "; ".join(x["heading"] for x in d["sections"]), plan[:10], "", dr):
                continue
            d["examples"] = dr["examples"]
        else:
            d["examples"] = []
        d["examples_version"] = 2
        save(lp, d)
        note(f"Worked examples fixed in {lp}: {len(d['examples'])}")


def clear_covers(cid, course):
    for e in EXTS:
        f = f"{IMG_DIR}/cover-{cid}.{e}"
        if os.path.exists(f):
            os.remove(f)
            note("Removed cover " + f)
    if course.pop("cover", None):
        save(f"courses/{cid}/course.json", course)


def replan_images(cid, course):
    """Throws away the pending picture requests of a course and plans them again (uploaded pictures stay)."""
    for les in course["lessons"]:
        lp = f"courses/{cid}/{les['file']}" if les["file"] else ""
        d = load(lp, None) if lp else None
        if d and d.pop("images_version", None) is not None:
            save(lp, d)


def write_lesson(t, i, k, les, titles, flags, dpath):
    maths = bool(flags & {"maths", "math"})
    c = dict(T=t, I=i, K=k, L=les["title"], O="; ".join(titles), F=les.get("focus") or "the usual content of this topic")
    if "short" in flags:
        for _ in range(2):
            d = ask(LESSON.format(t=t, i=i, k=k, l=les["title"], o=c["O"], f=c["F"], m=MATH_JSON if maths else ""))
            if d and len(d.get("sections", [])) >= 2 and good(d, maths):
                return d
        return None
    mt = MATH_TEXT if maths else ""
    dr = load(dpath, {})  # progress is saved after every step, so a stop never wastes work
    plan = dr.get("plan") or ask(fill(PLAN2, **c), max_tokens=3000)
    if not isinstance(plan, dict) or len(plan.get("sections", [])) < 4 or not plan.get("objectives"):
        return None
    dr["plan"] = plan
    secs = dr.setdefault("secs", [])
    outline = "; ".join(x["heading"] for x in plan["sections"])
    for x in plan["sections"][len(secs):]:
        body = ask(fill(SECTION2, T=t, L=les["title"], P=outline, H=x["heading"], X=x.get("points", ""), M=mt),
                   as_json=False, max_tokens=2800)
        if body and glitchy(body):
            STATS["glitches"] += 1
            note(f"Glitch in a section of lesson {i}: writing it again")
            body = ask(fill(SECTION2, T=t, L=les["title"], P=outline, H=x["heading"], X=x.get("points", ""), M=mt),
                       as_json=False, max_tokens=2800)
        if not body or glitchy(body):
            save(dpath, dr)
            return None
        secs.append({"heading": x["heading"], "body": body, "code": ""})
        save(dpath, dr)
    calc = bool(plan.get("calculation")) and isinstance(plan.get("example_plan"), list) and len(plan["example_plan"]) >= 5
    dr.setdefault("examples", [])
    if calc and not gen_examples(t, les["title"], outline, plan["example_plan"][:10], mt, dr, dpath):
        return None
    if "practice" not in dr:
        txt = ask(fill(PRACTICE, T=t, L=les["title"], P=outline, M=mt), as_json=False, max_tokens=3000)
        items = parse_practice(txt) if txt and not glitchy(txt) else []
        if not items:
            save(dpath, dr)
            return None
        dr["practice"] = items
        save(dpath, dr)
    digest = "\n".join(f"## {x['heading']}\n{x['body'][:900]}" for x in secs)
    ex = ask(fill(EXTRAS2, T=t, L=les["title"], D=digest, M=MATH_JSON if maths else ""))
    if not ex or not good(ex, maths) or not ex.get("recap"):
        return None
    why = plan.get("why")
    return {"title": les["title"], "summary": plan.get("summary", ""), "objectives": [str(o) for o in plan["objectives"]],
            "prerequisites": str(plan.get("prerequisites", "")), "why": why if isinstance(why, list) else [str(why or "")],
            "sections": secs, "examples": dr["examples"], "examples_version": 2, "practice": dr["practice"], "recap": ex["recap"],
            "key_terms": ex["key_terms"], "quiz": ex["quiz"], "flashcards": ex["flashcards"]}


def make_code(title, used):
    raw = re.findall(r"[A-Za-z0-9]+", title)
    last = raw[-1].lower() if len(raw) > 1 else ""
    num = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}.get(last) or (int(last) if last.isdigit() else None)
    ws = [w for w in re.findall(r"[A-Za-z]+", title) if w.lower() not in STOP] or re.findall(r"[A-Za-z]+", title) or ["X"]
    base = ws[0][:3].upper().ljust(3, "X")
    cands = ([base + str(num)] if num else []) + [base]
    if len(ws) > 1:
        cands.append("".join(w[0] for w in ws)[:3].upper().ljust(3, "X"))
    for c in cands:
        if c not in used:
            return c
    n = 2
    while base + str(n) in used:
        n += 1
    return base + str(n)


def theme_for(title, flags, taken):
    """A colour (hue) and a 3-letter code that no other course uses. Override the colour with [color=210]."""
    hues, n = [t["hue"] for t in taken], len(taken)
    forced = next((int(f[6:]) for f in flags if re.fullmatch(r"color=\d+", f)), None)
    gap = 20 if n < 15 else 10 if n < 30 else 4
    hue = forced % 360 if forced is not None else round(n * 137.508 + 20) % 360
    k = 0
    while forced is None and k < 400 and any(min(abs(hue - x), 360 - abs(hue - x)) < gap for x in hues):
        k += 1
        hue = round((n + k) * 137.508 + 20) % 360
    return {"hue": hue, "code": make_code(title, [t["code"] for t in taken])}


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
    parts = [f"Create a clear, accurate educational {kind} for secondary-school students.", f"Show: {subject}"]
    if g.get("layout"):
        parts.append(f"Layout: {g['layout']}")
    if g.get("labels"):
        parts.append("The only text allowed in the picture is these labels, each spelled exactly as written between the quotes, "
                     "in large, clear sans-serif letters, each joined by a thin straight line to the correct part:\n"
                     + "\n".join(f'- "{l}"' for l in g["labels"]) + "\nNo title, no caption, no numbers, no other words.")
    else:
        parts.append("Do not put any text in the picture.")
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


CF_ID = os.environ.get("CF_ACCOUNT_ID", "").strip()
CF_TOKEN = os.environ.get("CF_API_TOKEN", "").strip()
CF_ENABLED = os.environ.get("USE_CLOUDFLARE", "") == "1" and bool(CF_ID and CF_TOKEN)  # off by default
CF_MODEL = os.environ.get("CF_IMAGE_MODEL", "@cf/black-forest-labs/flux-1-schnell")
CF_MAX = int(os.environ.get("CF_MAX_IMAGES", "40"))  # pictures drawn per run
cf_off = False
cf_fail = 0


def cf_image(prompt, steps=6):
    """One picture from Cloudflare Workers AI as bytes, or None. Stops for the run when the free allowance is used up."""
    global cf_off, cf_fail
    if cf_off or not CF_ENABLED:
        return None
    req = urllib.request.Request(f"https://api.cloudflare.com/client/v4/accounts/{CF_ID}/ai/run/{CF_MODEL}",
                                 json.dumps({"prompt": prompt[:2000], "steps": steps}).encode(),
                                 {"Authorization": "Bearer " + CF_TOKEN, "Content-Type": "application/json",
                                  "User-Agent": "school-course-generator/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            img = base64.b64decode(json.load(r)["result"]["image"])
            cf_fail = 0
            return img
    except urllib.error.HTTPError as e:
        body = e.read()[:300]
        note(f"Cloudflare error {e.code}: " + body.decode("utf-8", "ignore")[:200])
        if e.code in (401, 403, 429) or b"4006" in body or b"daily" in body.lower():
            cf_off = True
    except (KeyError, TypeError, ValueError, urllib.error.URLError, OSError):
        note("Cloudflare gave no picture (unexpected reply or network problem)")
    cf_fail += 1
    if cf_fail >= 5 and not cf_off:
        cf_off = True
        note("Stopped drawing: 5 Cloudflare failures in a row (see the first error above)")
    return None


VISION_MODEL = os.environ.get("VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
VISION_TPM = int(os.environ.get("VISION_TOKENS_PER_MINUTE", "15000"))
VISION_LABELS = """This picture should be a labelled educational diagram. The ONLY text it should contain are these labels: @L@.
Read every word visible in the image carefully. Reply as JSON: {"text_found": [every word or phrase you can read], "all_present": true only if every label above appears and is spelled exactly right, "misspelled": [labels that are missing, misspelled or garbled], "extra_words": true if the image contains other words, titles or numbers that are not in the list, "reason": "one short sentence"}"""


def see(prompt, jpeg):
    """Asks the vision model about a picture. A dict, or None if it could not answer."""
    global used
    url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
    for key in KEYS:
        if (VISION_MODEL, key) in dead:
            continue
        body = json.dumps({"model": VISION_MODEL, "temperature": 0, "max_completion_tokens": 500,
                           "response_format": {"type": "json_object"},
                           "messages": [{"role": "user", "content": [{"type": "text", "text": prompt + "\nReply with valid JSON only."},
                                                                      {"type": "image_url", "image_url": {"url": url}}]}]}).encode()
        for _ in range(2):
            req = urllib.request.Request(URL, body, {"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                                     "User-Agent": "school-course-generator/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.load(r)
                tokens = data.get("usage", {}).get("total_tokens", 1800)
                used += tokens
                time.sleep(tokens * 60 / VISION_TPM)
                return json.loads(data["choices"][0]["message"]["content"])
            except urllib.error.HTTPError as e:
                txt = e.read()[:300].lower()
                if e.code == 429 and not (b"per day" in txt or b"tpd" in txt):
                    time.sleep(float(e.headers.get("retry-after") or 20) + 1)
                else:
                    print("Vision check unavailable:", e.code)
                    dead.add((VISION_MODEL, key))
                    break
            except (json.JSONDecodeError, KeyError, TypeError, urllib.error.URLError):
                time.sleep(3)
    return None


def labels_ok(jpeg, labels):
    """True if the labels in the picture are all present and spelled right, False if not, None if it could not be checked."""
    r = see(VISION_LABELS.replace("@L@", "; ".join(f'"{l}"' for l in labels)), jpeg)
    if not isinstance(r, dict):
        return None
    ok = bool(r.get("all_present")) and not r.get("misspelled") and not r.get("extra_words")
    print("  labels", "ok" if ok else "wrong: " + str(r.get("misspelled") or r.get("reason", ""))[:90])
    return ok


def hue_name(h):
    for lim, name in ((15, "red"), (45, "orange"), (70, "golden yellow"), (160, "green"), (200, "teal"), (255, "blue"), (290, "purple"), (335, "pink")):
        if h < lim:
            return name
    return "red"


def cover_prompt(title, hue, plan=None):
    """Prompt for a 3D hardcover textbook mockup. Put the school name on one line in school.txt to print it on the cover."""
    plan = plan or {}
    elements = ", ".join(plan.get("elements") or []) or "a few simple, recognisable symbols of the subject"
    school = open("school.txt", encoding="utf-8").read().strip().splitlines()[:1] if os.path.exists("school.txt") else []
    lines = ["Create a high-quality 3D mockup of a hardcover school textbook standing at a slight angle, showing the front cover and the spine, with a soft studio shadow on a plain light background (portrait orientation, 3:4).",
             f"The front cover is a rich, colourful, detailed digital illustration in a friendly educational style, with a {hue_name(hue)} colour palette, showing a lively scene built around: {elements}.",
             "Use exactly this text on the cover, spelled exactly as written, in large, bold, clear capital letters:",
             f'- Main title at the top: "{title.upper()}"']
    if plan.get("subtitle"):
        lines.append(f'- Subtitle under it, smaller: "{plan["subtitle"]}"')
    if school and school[0].strip():
        lines.append(f'- Small line at the bottom: "{school[0].strip()}"')
    lines.append(f'The spine shows "{title.upper()}" running vertically. Do not add any other text, author names, logos or watermarks.')
    return "\n".join(lines)


COVERQ = """School course: "@T@". Reply as JSON: {"subtitle": "a short catchy subtitle of 5 to 10 words, for example Exploring life from molecules to ecosystems", "elements": ["8 to 10 specific things that are typical of this subject and look good in a colourful illustration, for example a DNA double helix, a microscope, a frog"]}"""


def plan_covers(entries):
    """A subtitle and illustration ideas for each course cover, written once per course."""
    for title, _, flags in entries:
        cid = slug(title)
        c = load(f"courses/{cid}/course.json", None)
        if not c or "cover_plan" in c or "delete" in flags or have_cover(cid):
            continue
        r = ask(fill(COVERQ, T=c["title"]), max_tokens=600)
        if isinstance(r, dict) and r.get("elements"):
            c["cover_plan"] = {"subtitle": str(r.get("subtitle", ""))[:90], "elements": [str(x) for x in r["elements"]][:10]}
            save(f"courses/{cid}/course.json", c)


def have_cover(cid):
    return any(os.path.exists(f"{IMG_DIR}/cover-{cid}.{e}") for e in EXTS)


def make_cover(title, cid, course, cpath):
    """A cover picture for the course, drawn once in the course colour."""
    if "cover" in course or cf_off or not CF_ENABLED:
        return
    img = cf_image(cover_prompt(title, course["theme"]["hue"], course.get("cover_plan")))
    if img:
        os.makedirs(IMG_DIR, exist_ok=True)
        open(f"{IMG_DIR}/cover-{cid}.jpg", "wb").write(img)
        course["cover"] = f"cover-{cid}"
        save(cpath, course)
        STATS["covers"] += 1
        note(f"Drew cover for {cid}")


def have(name):
    return any(os.path.exists(f"{IMG_DIR}/{name}.{e}") for e in EXTS)


def enrich(title, cid, no, d, keep=()):
    """Adds the drawn diagrams and picture requests a lesson is missing. True if anything changed."""
    changed = False
    if "diagrams" not in d:
        dg = make_diagrams(title, d)
        if dg is not None:
            d["diagrams"], changed = dg, True
    if d.get("images_version") != 5:
        imgs = [g for g in d.get("diagrams", []) if g.get("type") == "image"]
        kept = [g for g in imgs if g.get("file") and have(g["file"])] + list(keep)  # pictures you already uploaded stay
        rest = [g for g in d.get("diagrams", []) if g.get("type") != "image"]
        d["diagrams"] = kept + rest
        changed = changed or len(imgs) != len(kept)
        new = plan_images(cid, no, d, kept)
        if new is not None:
            d["diagrams"] = kept + new + rest
            d["images_version"], changed = 5, True
    return changed


def collect(entries):
    """Pictures still missing, the best ones per course within its cap. Returns (todo, number already uploaded)."""
    todo, done = [], 0
    for title, _, flags in entries:
        cap = next((int(f.split("=")[1]) for f in flags if re.fullmatch(r"images=\d+", f)), IMAGES_PER_COURSE)
        c = load(f"courses/{slug(title)}/course.json", None)
        have_n, pending = 0, []
        for i, les in enumerate((c or {}).get("lessons", []), 1):
            lp = f"courses/{slug(title)}/{les['file']}" if les["file"] else ""
            d = load(lp, None) if lp else None
            for g in (d or {}).get("diagrams", []):
                if g.get("type") == "image" and g.get("file"):
                    if have(g["file"]):
                        have_n += 1
                    elif g.get("subject") and g.get("priority", 6) >= 5:
                        pending.append((i, c["title"], les["title"], g, lp, d))
        done += have_n
        best = sorted(pending, key=lambda t: (-t[3].get("priority", 6), t[0]))[:max(0, cap - have_n)]
        todo += [(ct, i, lt, g, lp, d) for i, ct, lt, g, lp, d in sorted(best, key=lambda t: t[0])]
    return todo, done


def make_pictures(entries):
    """Draws the pending pictures with Cloudflare Workers AI, best first. Any that fail stay on your list."""
    if not CF_ENABLED or cf_off:
        return
    os.makedirs(IMG_DIR, exist_ok=True)
    todo, _ = collect(entries)
    for ct, i, lt, g, lp, d in sorted(todo, key=lambda t: -t[3].get("priority", 6))[:CF_MAX]:
        if cf_off:
            break
        labelled = "label" in g.get("kind", "").lower() and bool(g.get("labels"))
        img, rejected = None, 0
        for attempt in range(3 if labelled else 1):
            pic = cf_image(build_prompt(g), steps=8 if labelled else 6)
            if not pic:
                break
            ok = labels_ok(pic, g["labels"]) if labelled else True
            if ok is False:
                rejected += 1
                STATS["label_retries"] += 1
            if ok is None:
                ok = True  # the vision model was not available, so keep the picture
            if ok:
                img = pic
                break
        if labelled and not img and rejected >= 3:
            STATS["label_gave_up"] += 1
            note(f"Labels never came out right for {g['file']}: left on your list")
        if img:
            open(f"{IMG_DIR}/{g['file']}.jpg", "wb").write(img)
            g["ai"] = True
            save(lp, d)
            STATS["pictures"] += 1
            note("Drew " + g["file"])
            time.sleep(1)


def write_requests(entries):
    """Writes courses/image-requests.md: only the pictures still waiting, each with its file name and prompt."""
    os.makedirs(IMG_DIR, exist_ok=True)
    readme = f"{IMG_DIR}/README.md"
    if not os.path.exists(readme):
        open(readme, "w", encoding="utf-8").write(
            "Upload lesson pictures here. File names must match courses/image-requests.md exactly "
            "(png, jpg, jpeg, webp or svg).\n")
    todo, done = collect(entries)
    covers = []
    for title, _, flags in entries:
        c = load(f"courses/{slug(title)}/course.json", None)
        if c and "delete" not in flags and not have_cover(slug(title)):
            covers.append((c["title"], slug(title), (c.get("theme") or {}).get("hue", 200), c.get("cover_plan")))
    lines = ["# Pictures to add", "", f"Waiting: **{len(todo)}** | Uploaded: **{done}** | Covers waiting: **{len(covers)}**", ""]
    if covers:
        lines += ["## Course covers", "", "Upload each cover into `courses/images` with the exact name. It shows as a book on the course card, the course page and the lesson banner on wide screens.", ""]
        for ct, cid, hue, plan in covers:
            lines += [f"### {ct}", "", "Save as:", "```", f"cover-{cid}.jpg", "```", "Prompt:", "```", cover_prompt(ct, hue, plan), "```", ""]
    last = (None, None)
    for ct, i, lt, g, _lp, _d in todo:
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
    flags = {f.lower() for f in re.findall(r"\[([\w=+-]+)\]", head)}
    return re.sub(r"\[[\w=+-]+\]", "", head).strip(), notes.strip(), flags


def load(p, default):
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default


def save(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(d, open(p, "w", encoding="utf-8"), indent=1, ensure_ascii=False)


def depts_of(flags):
    d = next((f[5:].split("+") for f in flags if f.startswith("dept=")), [])
    return sorted({slug(x) for x in d if slug(x)}) or ["general"]


def write_departments(entries):
    """courses/departments.json from departments.txt, plus any department a course tag mentions."""
    names = [l.strip() for l in open("departments.txt", encoding="utf-8")
             if l.strip() and not l.lstrip().startswith("#")] if os.path.exists("departments.txt") else []
    out = {slug(n): n for n in names if slug(n) and slug(n) != "general"}
    for _, _, flags in entries:
        for d in depts_of(flags):
            if d != "general" and d not in out:
                out[d] = d.replace("-", " ").title()
    save("courses/departments.json", [{"id": k, "name": v} for k, v in out.items()])


def write_report(entries):
    todo, done = collect(entries)
    lines = ["# Last run report", "", time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "",
             f"- Groq keys: {len(KEYS)} | model: {', '.join(MODELS)}",
             f"- Cloudflare account ID: {'set' if CF_ID else 'MISSING'} | Cloudflare token: {'set' if CF_TOKEN else 'MISSING'}",
             f"- Cloudflare drawing: {'ON' if CF_ENABLED else 'OFF (you upload the pictures yourself)'}" + (" (stopped for today: free allowance used up or access refused)" if cf_off else ""),
             f"- Covers drawn this run: {STATS['covers']} | pictures drawn: {STATS['pictures']} | label redraws: {STATS['label_retries']} | gave up on labels: {STATS['label_gave_up']}",
             f"- Glitches caught and rewritten: {STATS['glitches']} | tokens used: {used}",
             f"- Pictures waiting: {len(todo)} | already done: {done}", "", "## What happened", ""]
    lines += [f"- {m}" for m in REPORT[-60:]] or ["- Nothing to report."]
    os.makedirs("courses", exist_ok=True)
    open("courses/run-report.md", "w", encoding="utf-8").write("\n".join(lines) + "\n")


def main():
    lines_in = [l for l in open("courses.txt", encoding="utf-8") if l.strip() and not l.lstrip().startswith("#")]
    gflags = {f for l in lines_in if l.lstrip().startswith("@") for f in re.findall(r"[\w=-]+", l.lower())}  # "@clear-ai" applies to all courses
    entries = [(t, n, f | {g for g in gflags if not (g.startswith("images=") and any(x.startswith("images=") for x in f))})
               for t, n, f in (parse(l) for l in lines_in if not l.lstrip().startswith("@"))]
    made, index = 0, []
    try:
        note("Cloudflare drawing: " + ("ON" if CF_ENABLED else "OFF - pictures and covers come from your uploads"))
        for title, notes, flags in entries:
            if "delete" in flags:
                delete_course(slug(title))
                continue
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
            if "theme" not in course:
                taken = [t for t in (load(f"courses/{slug(x[0])}/course.json", {}).get("theme") for x in entries) if t]
                course["theme"] = theme_for(title, flags, taken)
                save(cpath, course)
            make_cover(title, cid, course, cpath)
            if "replan-images" in flags:
                replan_images(cid, course)
            if "clear-covers" in flags:
                clear_covers(cid, course)
            if "fix-examples" in flags:
                fix_examples(title, cid, course, flags)
            if "clear-ai" in flags:
                clear_ai(cid, course)
            if "repair" in flags:
                repair_lessons(title, cid, course, flags)
            for no, les in enumerate(course["lessons"], 1):  # add diagrams and picture requests to older lessons
                lp = f"courses/{cid}/{les['file']}" if les["file"] else ""
                ld = load(lp, None) if lp else None
                if ld and "sections" in ld and ("diagrams" not in ld or ld.get("images_version") != 5) and not ("rewrite" in flags and "objectives" not in ld):
                    if used > BUDGET or time.time() - START > MAX_MIN * 60:
                        raise Stop("Token or time budget for this run is used up")
                    if enrich(title, cid, no, ld):
                        save(lp, ld)
                        print("Updated diagrams and picture list for", lp)
            for i, les in enumerate(course["lessons"], 1):
                old = load(f"courses/{cid}/{les['file']}", None) if les["file"] else None
                if les["file"] and not ("rewrite" in flags and old and "objectives" not in old):
                    continue  # [rewrite] redoes old-style lessons in the textbook style
                if used > BUDGET or time.time() - START > MAX_MIN * 60:
                    raise Stop("Token or time budget for this run is used up")
                dpath = f"courses/{cid}/draft-{i:02d}.json"
                models_seen.clear()
                d = write_lesson(title, i, len(titles), les, titles, flags, dpath)
                if not d:
                    print("Skipped lesson", i, les["title"])
                    continue
                keep = [g for g in (old or {}).get("diagrams", []) if g.get("type") == "image" and g.get("file") and have(g["file"])]
                enrich(title, cid, i, d, keep)
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
        for title, _, flags in entries:
            c = load(f"courses/{slug(title)}/course.json", None)
            if c:
                index.append({"id": slug(title), "title": c["title"], "total": len(c["lessons"]),
                              "ready": sum(1 for l in c["lessons"] if l["file"]), "theme": c.get("theme"), "depts": depts_of(flags)})
        save("courses/index.json", index)
        write_departments(entries)
        try:
            make_pictures(entries)
        except Exception as e:
            print("Picture drawing stopped:", e)
        try:
            plan_covers(entries)
        except Exception as e:
            print("Cover ideas stopped:", e)
        write_requests(entries)
        write_report(entries)
    print("Done:", made, "new lessons")


if __name__ == "__main__":
    sys.exit(main())
