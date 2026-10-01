"""Generates course outlines and lessons with Groq and saves them as JSON in /courses.
courses.txt: one course per line, e.g.  Calculus I [maths] [long] | extra notes
  [maths] = formulas written in LaTeX      [long] = longer, multi-part lessons
Optional syllabus: save it as syllabi/<course-name-with-dashes>.txt and the lessons follow it.
Safe to re-run: finished lessons are skipped. Stops cleanly at the daily limit."""
import json, os, re, sys, time, urllib.request, urllib.error

KEY = os.environ["GROQ_API_KEY"]
MODEL = os.environ.get("MODEL", "openai/gpt-oss-120b")
BUDGET = int(os.environ.get("TOKEN_BUDGET", "170000"))  # tokens per run (free tier is about 200K a day)
TPM = int(os.environ.get("TOKENS_PER_MINUTE", "7000"))  # we pace ourselves under the per-minute limit
PER_COURSE = int(os.environ.get("LESSONS_PER_COURSE", "10"))
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
SECTION = ('Course: "{t}", lesson "{l}". Lesson plan: {plan}\n{m}Write the section "{h}" ({pts}). '
           'Use Markdown without a heading line, 350 to 500 words, short paragraphs, **bold** for key terms. '
           'Include at least one fully worked example that shows every step. For a "Practice problems" section give '
           '4 problems, each followed by a full worked solution. Output only the section text.')
EXTRAS = ('Lesson "{l}" of course "{t}". Sections:\n{d}\n{m}Reply as JSON: {{' + SHAPE + '}} with 6-8 key terms, '
          '6 quiz questions based on the sections, 8 flashcards.')


class DailyLimit(Exception):
    pass


class Stop(Exception):
    pass


used = 0
START = time.time()
MAX_MIN = int(os.environ.get("MAX_MINUTES", "45"))  # stop early so the results always get saved


def ask(prompt, as_json=True, max_tokens=4500, tries=4):
    global used
    payload = {"model": MODEL, "temperature": 0.4, "max_completion_tokens": max_tokens,
               "messages": [{"role": "system", "content": SYSTEM},
                            {"role": "user", "content": prompt + ("\nReply with valid JSON only." if as_json else "")}]}
    if as_json:
        payload["response_format"] = {"type": "json_object"}
    if MODEL.startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"
    body = json.dumps(payload).encode()
    for _ in range(tries):
        req = urllib.request.Request(URL, body, {"Authorization": "Bearer " + KEY,
                                                 "Content-Type": "application/json",
                                                 "User-Agent": "school-course-generator/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
            tokens = data.get("usage", {}).get("total_tokens", 3000)
            used += tokens
            time.sleep(tokens * 60 / TPM)  # stay under the per-minute token limit
            text = (data["choices"][0]["message"]["content"] or "").strip()
            if not text:
                continue
            return json.loads(text) if as_json else text
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = float(e.headers.get("retry-after") or 30)
                if wait > 180:
                    raise DailyLimit("Daily limit reached")
                time.sleep(wait + 1)
            elif e.code >= 500:
                time.sleep(10)
            else:
                print("HTTP", e.code, e.read()[:400])
                if e.code in (401, 403, 404):
                    raise Stop("Groq refused the request - check the GROQ_API_KEY secret")
                time.sleep(3)  # other 400s (e.g. invalid JSON from the model) are retried, then skipped
        except (json.JSONDecodeError, KeyError, TypeError, urllib.error.URLError):
            print("Unreadable reply, retrying")
            time.sleep(5)
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


def write_lesson(t, i, k, les, titles, flags):
    maths = bool(flags & {"maths", "math"})
    ctx = dict(t=t, i=i, k=k, l=les["title"], o="; ".join(titles),
               f=les.get("focus") or "the usual content of this topic")
    if "long" not in flags:
        for _ in range(2):
            d = ask(LESSON.format(m=MATH_JSON if maths else "", **ctx))
            if d and len(d.get("sections", [])) >= 2 and good(d, maths):
                return d
        return None
    plan = ask(PLAN.format(**ctx))
    if not plan or len(plan.get("sections", [])) < 4:
        return None
    outline = "; ".join(s["heading"] for s in plan["sections"])
    secs = []
    for s in plan["sections"]:
        body = ask(SECTION.format(t=t, l=les["title"], plan=outline, h=s["heading"], pts=s.get("points", ""),
                                  m=MATH_TEXT if maths else ""), as_json=False, max_tokens=2500)
        if not body:
            return None
        secs.append({"heading": s["heading"], "body": body, "code": ""})
    digest = "\n".join(f"## {s['heading']}\n{s['body'][:900]}" for s in secs)
    ex = ask(EXTRAS.format(t=t, l=les["title"], d=digest, m=MATH_JSON if maths else ""))
    if not ex or not good(ex, maths):
        return None
    return {"title": les["title"], "summary": plan.get("summary", ""), "sections": secs,
            "key_terms": ex["key_terms"], "quiz": ex["quiz"], "flashcards": ex["flashcards"]}


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
            for i, les in enumerate(course["lessons"], 1):
                if les["file"]:
                    continue
                if used > BUDGET or time.time() - START > MAX_MIN * 60:
                    raise Stop("Token or time budget for this run is used up")
                d = write_lesson(title, i, len(titles), les, titles, flags)
                if not d:
                    print("Skipped lesson", i, les["title"])
                    continue
                d["reviewed"] = False
                les["file"] = f"lesson-{i:02d}.json"
                save(f"courses/{cid}/{les['file']}", d)
                save(cpath, course)
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
