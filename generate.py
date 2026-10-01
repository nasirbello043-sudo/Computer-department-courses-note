"""Generates course outlines and lessons with Groq and saves them as JSON in /courses.
Reads course titles from courses.txt (one per line, optional "Title | notes").
Safe to re-run: existing lessons are skipped. Stops cleanly at the daily limit."""
import json, os, re, sys, time, urllib.request, urllib.error

KEY = os.environ["GROQ_API_KEY"]
MODEL = os.environ.get("MODEL", "openai/gpt-oss-120b")
MAX = int(os.environ.get("MAX_LESSONS", "40"))    # lessons per run
PER_COURSE = int(os.environ.get("LESSONS_PER_COURSE", "10"))
PAUSE = int(os.environ.get("PAUSE_SECONDS", "20"))  # keeps us under the per-minute token limit
URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM = ("You write clear, accurate course material for secondary-school and early-university students. "
          "Use simple English, concrete examples and short paragraphs. Reply with valid JSON only.")

OUTLINE = ('Course: "{t}". Notes: {n}\nGive an ordered outline of exactly {k} lessons that teach this course '
           'from basics to confident use. Reply as {{"lessons": ["Lesson title", ...]}}')

LESSON = ('Course: "{t}". Write lesson {i} of {k}: "{l}".\nOther lessons: {o}\n'
          'Reply as JSON with exactly these keys:\n'
          '{{"title": str, "summary": "2 sentences", '
          '"sections": [{{"heading": str, "body": "2-3 short paragraphs separated by \\n\\n", "code": "optional example or empty string"}}] (3 to 4 sections), '
          '"key_terms": [{{"term": str, "meaning": str}}] (4 to 6), '
          '"quiz": [{{"q": str, "options": [4 strings], "answer": index 0-3, "why": "one sentence"}}] (4 questions), '
          '"flashcards": [{{"front": str, "back": str}}] (5 cards)}}')


class DailyLimit(Exception):
    pass


def chat(prompt, tries=4):
    payload = {"model": MODEL, "temperature": 0.4, "max_completion_tokens": 4500,
               "response_format": {"type": "json_object"},
               "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]}
    if MODEL.startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"
    body = json.dumps(payload).encode()
    for _ in range(tries):
        req = urllib.request.Request(URL, body, {"Authorization": "Bearer " + KEY,
                                                 "Content-Type": "application/json",
                                                 "User-Agent": "school-course-generator/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(json.load(r)["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = float(e.headers.get("retry-after") or 30)
                if wait > 180:
                    raise DailyLimit("Daily limit reached")
                time.sleep(wait + 1)
            elif e.code >= 500:
                time.sleep(10)
            else:
                print("HTTP", e.code, e.read()[:300])
                raise
        except (json.JSONDecodeError, KeyError, TypeError):
            print("Unreadable reply, retrying")
            time.sleep(5)
    return None


def valid(d):
    try:
        return (len(d["sections"]) >= 2 and len(d["quiz"]) >= 3 and len(d["flashcards"]) >= 3
                and all(len(q["options"]) == 4 and q["answer"] in range(4) for q in d["quiz"]))
    except (KeyError, TypeError):
        return False


def slug(t):
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def load(p, default):
    return json.load(open(p)) if os.path.exists(p) else default


def save(p, d):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(d, open(p, "w"), indent=1, ensure_ascii=False)


def main():
    lines = [l.strip() for l in open("courses.txt") if l.strip() and not l.startswith("#")]
    made, index = 0, []
    try:
        for line in lines:
            title, _, notes = [x.strip() for x in line.partition("|")]
            cid = slug(title)
            cpath = f"courses/{cid}/course.json"
            course = load(cpath, None)
            if not course:
                out = chat(OUTLINE.format(t=title, n=notes or "none", k=PER_COURSE))
                if not out or not out.get("lessons"):
                    continue
                course = {"title": title, "lessons": [{"title": t, "file": None} for t in out["lessons"]]}
                save(cpath, course)
            titles = [l["title"] for l in course["lessons"]]
            for i, les in enumerate(course["lessons"], 1):
                if les["file"] or made >= MAX:
                    continue
                d = chat(LESSON.format(t=title, i=i, k=len(titles), l=les["title"], o="; ".join(titles)))
                if not d or not valid(d):
                    print("Skipped lesson", i, les["title"])
                    continue
                d["reviewed"] = False
                fname = f"lesson-{i:02d}.json"
                save(f"courses/{cid}/{fname}", d)
                les["file"] = fname
                save(cpath, course)
                made += 1
                print("Wrote", cid, fname)
                time.sleep(PAUSE)
    except DailyLimit as e:
        print(e, "- run again tomorrow.")
    finally:
        for line in lines:
            title = line.partition("|")[0].strip()
            c = load(f"courses/{slug(title)}/course.json", None)
            if c:
                index.append({"id": slug(title), "title": c["title"], "total": len(c["lessons"]),
                              "ready": sum(1 for l in c["lessons"] if l["file"])})
        save("courses/index.json", index)
    print("Done:", made, "new lessons")


if __name__ == "__main__":
    sys.exit(main())
