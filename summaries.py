"""Exam cheat sheets for every course on the site: 7 to 10 pages each, no exercises.
Sources: courses.txt (courses the writers build) and manual-upload.txt (courses you upload).
Output: courses/summaries/<course>.pdf, plus courses/summaries/state.json.
Only courses/summaries is written. The writer jobs and the course files are never changed."""
import hashlib, html, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "book"))
from check_lesson import sanitize  # noqa: E402

OUT = os.path.join("courses", "summaries")
MIN_PAGES, MAX_PAGES = 7, 10
TRIES = 4
MODEL = os.environ.get("SUMMARY_MODEL", "openai/gpt-oss-120b")
KEY = os.environ.get("GROQ_API_KEY", "").strip()
MAX_MINUTES = int(os.environ.get("MAX_MINUTES", "60"))
START = time.time()
PDF_WRITERS = {"writer4", "writer5", "writer6"}
SOURCE_LIMIT = 90000  # characters of course text sent to the model

class Stop(Exception):
    pass

def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")

def ask(prompt):
    """One request to Groq. Returns the reply text; retries briefly on slow replies."""
    if not KEY:
        raise Stop("no GROQ_API_KEY set")
    body = json.dumps({"model": MODEL, "temperature": 0.3, "max_completion_tokens": 6000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    for attempt in range(3):
        if time.time() - START > MAX_MINUTES * 60:
            raise Stop("time is up for this run")
        req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", body,
                                     {"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
        try:
            with urllib.request.urlopen(req, timeout=150) as r:
                data = json.loads(r.read().decode())
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
            if text.strip():
                return text
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")
            if e.code == 429 and "per day" in detail.lower():
                raise Stop("the daily Groq limit is used up for this key")
            print("summary: model error", e.code, detail[:150])
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            print("summary: no answer in time:", str(e)[:120])
        time.sleep(20 * (attempt + 1))
    return ""

def latex_to_text(tex):
    tex = re.sub(r"\\(begin|end)\{[^}]*\}", " ", tex)
    tex = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", " ", tex)
    return re.sub(r"[{}$&%_^~]", " ", tex)

def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default

def writer_course_text(cid):
    c = load_json(os.path.join("courses", "html", cid, "course.json"), None)
    if c:
        parts = []
        for les in c.get("lessons", []):
            d = les.get("data") or {}
            if not d:
                continue
            parts.append(f"LESSON: {les.get('title', '')}\n{d.get('summary', '')}\n" + "\n".join(d.get("objectives", [])))
            for s in d.get("sections", []):
                parts.append(f"{s.get('heading', '')}\n{s.get('body', '')}")
            for k in d.get("key_terms", []):
                parts.append(f"{k.get('term', '')}: {k.get('meaning', '')}")
        return "\n".join(parts)
    c = load_json(os.path.join("courses", "pdf", cid + ".json"), None)
    if c:
        return "\n".join(f"LESSON: {l.get('title', '')}\n" + latex_to_text(l.get("tex", "")) for l in c.get("lessons", []) if l.get("tex"))
    return ""

def manual_text(path):
    if path.endswith(".pdf"):
        r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"], capture_output=True, encoding="utf-8", errors="replace")
        return r.stdout
    raw = open(path, encoding="utf-8", errors="replace").read()
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    return html.unescape(re.sub(r"<[^>]+>", " ", raw))

def sources():
    """Yields (course id, title, text, kind) for every course on the site."""
    if os.path.exists("courses.txt"):
        for line in open("courses.txt", encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            flags = {f.strip().lower() for f in re.findall(r"\[([^\]]+)\]", line)}
            title = re.sub(r"\[[^\]]+\]", "", line).strip()
            job = next((f[4:] for f in flags if f.startswith("job=")), "")
            kind = "pdf" if job in PDF_WRITERS else "html"
            yield slug(title), title, writer_course_text(slug(title)), kind
    if os.path.exists("manual-upload.txt"):
        for line in open("manual-upload.txt", encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            flags = {f.strip().lower() for f in re.findall(r"\[([^\]]+)\]", line)}
            title = re.sub(r"\[[^\]]+\]", "", line).strip()
            kind = "pdf" if "pdf" in flags else "html" if "html" in flags else None
            if not kind:
                continue
            cid = slug(title)
            path = os.path.join("manual", kind, cid + (".pdf" if kind == "pdf" else ".html"))
            if os.path.exists(path):
                yield cid, title, manual_text(path), kind

PROMPT = r"""Write an EXAM CHEAT SHEET for the course below, as LaTeX body text only.
The sheet must be {words} words long and help a student revise for an exam. It has NO exercises and NO worked examples
longer than two lines. It must contain, in this order:
\section{Cheat sheet: COURSE TITLE}
\subsection{Key terms} as a tabular with columns Term and Meaning (use \begin{tabular}{@{}p{3.6cm}p{10.4cm}@{}} \toprule ... \bottomrule),
covering every important term in the course.
\subsection{Definitions} one short paragraph per important definition, in bold term first.
\subsection{Rules, formulas and laws} each one stated precisely, with the conditions under which it applies.
\subsection{Methods step by step} the procedure for each method, as a numbered list.
\subsection{Lesson by lesson} for each lesson: a heading and 3 to 6 bullet points of what must be remembered.
\subsection{Common exam mistakes} a list of the errors students make, and how to avoid each one.
\subsection{Final checklist} a bulleted list of everything to be able to do before the exam.

Rules: plain English. Use \$, \% and \& for those characters. Maths only inside $...$. Use \item only inside lists.
Do not include a summary paragraph at the top, no motivational text, no exercises, no answers section. Cover every topic in the source.
Reply with the LaTeX only, no code fences.

COURSE SOURCE:
{source}
"""

def clean(reply):
    return re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", (reply or "").strip()).strip() + "\n"

def compile_cheatsheet(title, body):
    """Compiles one cheat sheet with the book template. Returns (pages, pdf bytes or None, errors)."""
    work = tempfile.mkdtemp()
    try:
        shutil.copy(os.path.join(HERE, "book", "template.tex"), work)
        head = "\\providecommand{\\coursetitle}{" + title.replace("&", "\\&") + " cheat sheet}\n\\input{template}\n\\begin{document}\n"
        with open(os.path.join(work, "sheet.tex"), "w", encoding="utf-8") as f:
            f.write(head + body + "\n\\end{document}\n")
        errs = []
        for _ in range(2):
            r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "sheet.tex"], cwd=work, capture_output=True, encoding="utf-8", errors="replace")
            errs = [l[1:].strip() for l in r.stdout.splitlines() if l.startswith("!")][:4]
        pdf = os.path.join(work, "sheet.pdf")
        if not os.path.exists(pdf) or errs:
            return 0, None, errs or ["LaTeX did not produce a PDF"]
        info = subprocess.run(["pdfinfo", pdf], capture_output=True, encoding="utf-8", errors="replace").stdout
        pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
        return pages, open(pdf, "rb").read(), []
    finally:
        shutil.rmtree(work, ignore_errors=True)

def make_summary(cid, title, text):
    """Writes a cheat sheet in the 7 to 10 page range. Returns (status, pages, pdf bytes or None)."""
    source = text[:SOURCE_LIMIT]
    words = 3600
    reply = ask(PROMPT.replace("{words}", str(words)).replace("{source}", source))
    best = None
    for attempt in range(1, TRIES + 1):
        body = sanitize(clean(reply))
        pages, pdf, errs = compile_cheatsheet(title, body)
        if pdf is not None and MIN_PAGES <= pages <= MAX_PAGES:
            return "ok", pages, pdf
        if pdf is not None and (best is None or abs(pages - 8.5) < abs(best[0] - 8.5)):
            best = (pages, pdf)
        if attempt == TRIES or budget_gone():
            break
        if errs:
            feedback = "LaTeX errors to fix: " + "; ".join(errs)
        elif pages < MIN_PAGES:
            feedback = f"The sheet is only {pages} pages. Add more definitions, rules, method steps and exam mistakes so it reaches 7 to 10 pages. Keep the same layout."
        else:
            feedback = f"The sheet is {pages} pages, over {MAX_PAGES}. Remove repetition and minor points so it fits 7 to 10 pages. Keep the same layout."
        reply = ask(PROMPT.replace("{words}", str(words)).replace("{source}", source) + "\n\nYOUR PREVIOUS SHEET WAS REJECTED: " + feedback + "\nSend the complete corrected sheet.\n\nPREVIOUS SHEET:\n" + body)
    if best:
        return "outside range", best[0], best[1]
    return "failed", 0, None

def budget_gone():
    return time.time() - START > MAX_MINUTES * 60

def main():
    os.makedirs(OUT, exist_ok=True)
    state_path = os.path.join(OUT, "state.json")
    state = load_json(state_path, {})
    done = 0
    for cid, title, text, kind in sources():
        if not text.strip():
            print("summary: no text yet for", title, "- skipped")
            continue
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        pdf_path = os.path.join(OUT, cid + ".pdf")
        if state.get(cid, {}).get("hash") == digest and os.path.exists(pdf_path) and state[cid].get("status") == "ok":
            print("summary: unchanged,", title)
            continue
        if budget_gone():
            print("summary: time is up, the rest waits for the next run")
            break
        try:
            status, pages, pdf = make_summary(cid, title, text)
        except Stop as e:
            print("summary: stopped -", e)
            break
        if pdf is not None:
            with open(pdf_path, "wb") as f:
                f.write(pdf)
        state[cid] = {"hash": digest, "status": status, "pages": pages, "title": title, "kind": kind}
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=1)
        print(f"summary: {title}: {status}, {pages} pages")
        done += 1
    print("summary: done,", done, "written this run")

if __name__ == "__main__":
    main()
