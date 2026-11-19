"""LaTeX route for PDF courses (writers 4-6).
Each lesson is written in LaTeX, checked by the compile gate, and kept only if it passes.
Accepted lessons are stored in courses/pdf/<course>.json; the book is assembled from them."""
import json, os, re, subprocess, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
BOOK = os.path.join(HERE, "book")
sys.path.insert(0, BOOK)
from write_lesson import write_lesson  # noqa: E402
from check_lesson import measure  # noqa: E402

def _read_outline_subtopics(cid):
    """Sub-topics from syllabi/<course>.txt lines like '1. Title | sub-topics', keyed by title."""
    path = os.path.join("syllabi", f"{cid}.txt")
    out = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            m = re.match(r"^\s*\d+\.\s*(.+?)\s*\|\s*(.+)$", line)
            if m:
                out[m.group(1).strip().lower()] = [s.strip() for s in m.group(2).split(",") if s.strip()]
    return out

def load_working(cid, title, theme):
    path = f"courses/pdf/{cid}.json"
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return {"title": title, "theme": theme, "lessons": []}

def save_working(cid, data):
    os.makedirs("courses/pdf", exist_ok=True)
    tmp = f"courses/pdf/{cid}.json.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, f"courses/pdf/{cid}.json")

MAX_EXAMPLES = 3  # worked examples for the whole book (non-maths)
MAX_EXAMPLES_MATHS = 10  # worked examples for the whole book (maths)
WORDS_PER_PAGE = 240  # used to size a lesson's word target
WORDS_PER_PAGE_EST = 420  # measured: about this many words fill one page of the book layout
DEFAULT_PAGES = (20, 40)
FIT_REWRITES = 24  # most lesson rewrites in one run, to stay within the daily allowance

def page_range(flags, default=DEFAULT_PAGES):
    """Page range from a course tag such as [30 to 40], [30-40] or [pages=30-40]."""
    for f in flags:
        m = re.fullmatch(r"(?:pages\s*=\s*)?(\d+)\s*(?:-|to)\s*(\d+)", str(f).strip().lower())
        if m:
            lo, hi = sorted((int(m.group(1)), int(m.group(2))))
            return max(1, lo), max(1, hi)
    return default

def lesson_words(rng, n_lessons):
    """Words per lesson that put the whole book in the middle of its page range."""
    lo, hi = rng
    return int(max(250, min(1800, ((lo + hi) / 2.0) / max(1, n_lessons) * WORDS_PER_PAGE)))

def _cap_examples_book(texts, cap):
    """Keeps the first `cap` worked examples across the whole book, in lesson order, and removes the rest."""
    count = {"n": 0}
    def keep(m):
        count["n"] += 1
        return m.group(0) if count["n"] <= cap else ""
    return [re.sub(r"\\begin\{example\}.*?\\end\{example\}", keep, tx, flags=re.S) for tx in texts]

def _strip_exercises(tex):
    """Non-maths courses have no exercise sections: remove them from the lesson text."""
    return re.sub(r"\\subsection\{Exercises\}.*?(?=\\subsection\{Key terms\})", "", tex, flags=re.S)

def _prepare(tex, maths):
    return tex if maths else _strip_exercises(tex)

def assemble(cid, title, data, out_pdf, maths=False, rng=DEFAULT_PAGES):
    """Joins the accepted lessons into one book. Returns (pages, problems)."""
    lo, hi = rng
    tex_lessons = _cap_examples_book([_prepare(l["tex"], maths) for l in data.get("lessons", []) if l.get("tex")],
                                     MAX_EXAMPLES_MATHS if maths else MAX_EXAMPLES)
    work = tempfile.mkdtemp()
    try:
        shutil.copy(os.path.join(BOOK, "template.tex"), work)
        tpl_path = os.path.join(work, "template.tex")
        tpl = open(tpl_path, encoding="utf-8").read()
        # the course's own title always goes in the header, whatever template copy is in the repo
        tpl = re.sub(r"\\fancyhead\[L\]\{[^\n]*\}", lambda m: "\\fancyhead[L]{\\scriptsize\\textsc{\\coursetitle}}", tpl)
        open(tpl_path, "w", encoding="utf-8").write(tpl)
        body = "\\providecommand{\\coursetitle}{" + title.replace("&", "\\&") + "}\n\\input{template}\n\\begin{document}\n" + "\n\\clearpage\n".join(tex_lessons) + "\n\\end{document}\n"
        with open(os.path.join(work, "book.tex"), "w", encoding="utf-8") as f:
            f.write(body)
        for _ in range(2):
            subprocess.run(["pdflatex", "-interaction=nonstopmode", "book.tex"], cwd=work, capture_output=True)
        built = os.path.join(work, "book.pdf")
        if not os.path.exists(built):
            return 0, ["the book did not compile"]
        info = subprocess.run(["pdfinfo", built], capture_output=True, encoding="utf-8", errors="replace").stdout
        pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
        os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
        shutil.copy(built, out_pdf)
        problems = []
        if pages > hi:
            problems.append(f"book is {pages} pages, over the {hi}-page maximum")
        if pages < lo:
            problems.append(f"book is {pages} pages, below the {lo}-page minimum")
        return pages, problems
    finally:
        shutil.rmtree(work, ignore_errors=True)

def _words(tex):
    """Words of lesson text, ignoring LaTeX commands. Every real change moves this number."""
    body = re.sub(r"\\[a-zA-Z]+\*?", " ", tex)
    body = re.sub(r"[{}$&%_^~\\]", " ", body)
    return len(body.split())

def _fit_book(cid, title, data, ask, budget_ok, subs, maths, rng):
    """Brings the book inside its page range: under the minimum, the shortest lessons are rewritten with more depth;
    over the maximum, the longest are rewritten more tightly. A rewrite is kept only if it moves the length the right way."""
    lo, hi = rng
    words = lesson_words(rng, len(data["lessons"]))
    work = tempfile.mkdtemp()
    try:
        pages, problems = assemble(cid, title, data, f"courses/pdf/{cid}.pdf", maths, rng)
        lens, tried, swaps = {}, set(), 0
        while (pages < lo or pages > hi) and swaps < FIT_REWRITES and budget_ok():
            grow = pages < lo
            for idx, e in enumerate(data["lessons"]):
                if idx not in lens:
                    lens[idx] = _words(_prepare(e["tex"], maths))
            order = sorted((i for i in lens if (i, grow) not in tried), key=lambda i: lens[i], reverse=not grow)
            if not order:
                break
            idx = order[0]
            swaps += 1
            entry = data["lessons"][idx]
            old_pages = lens[idx]
            topics = subs.get(entry["title"].lower(), [entry["title"]])
            if grow:
                target = int(old_pages + WORDS_PER_PAGE_EST)  # one more page of words
                task = (entry["title"] + " (EXPAND: keep everything already in this lesson, and ADD one new subsection on a related "
                        "sub-topic from the outline that is not yet covered, with its own short explanation and one worked example. "
                        "Also explain the existing sub-topics more fully. Keep at most 3 worked examples in total and the same layout.)")
            else:
                target = max(200, int(old_pages - WORDS_PER_PAGE_EST))  # one page of words less
                task = (entry["title"] + " (TIGHTEN: rewrite this lesson more concisely. Remove repetition and side points, "
                        "keep every sub-topic, the same layout and at most 3 worked examples.)")
            out = os.path.join("courses", "pdf", f"{cid}-fit-{idx + 1:02d}.tex.tmp")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            ok, tries, reasons = write_lesson(idx + 1, task, topics, entry["tex"], out, ask, maths, words=target, safe=True)
            label = "Expanded" if grow else "Tightened"
            if ok:
                new = open(out, encoding="utf-8").read()
                n_new = _words(_prepare(new, maths))
                if n_new and ((n_new > old_pages * 1.1) if grow else (n_new < old_pages * 0.9)):
                    entry["tex"] = new
                    lens[idx] = n_new
                    print(f"{label} lesson {idx + 1} ({entry['title']}): {old_pages} -> {n_new} words")
                else:
                    tried.add((idx, grow))
                    print(f"{'Expansion' if grow else 'Tightening'} of lesson {idx + 1} ({entry['title']}) did not change length the right way ({old_pages} -> {n_new} pages), old version kept")
            else:
                tried.add((idx, grow))
                print(f"Rewrite of lesson {idx + 1} ({entry['title']}) not accepted:", "; ".join(reasons))
            if os.path.exists(out):
                os.remove(out)
            save_working(cid, data)
            pages, problems = assemble(cid, title, data, f"courses/pdf/{cid}.pdf", maths, rng)
        return pages, problems
    finally:
        shutil.rmtree(work, ignore_errors=True)

def tex_course(cid, title, theme, lesson_titles, ask, budget_ok, rewrite=False, maths=False, pages=DEFAULT_PAGES):
    """Writes every missing lesson of a PDF course, then fits the book to its page range.
    ask(prompt) returns text. budget_ok() returns False when time is up.
    rewrite=True clears the saved lessons once, so the whole course is written again.
    A lesson that failed in an earlier run is written in plain 'safe mode' so the course cannot stay stuck on it."""
    subs = _read_outline_subtopics(cid)
    data = load_working(cid, title, theme)
    if len(data["lessons"]) != len(lesson_titles):
        data["lessons"] = [{"title": t, "file": "", "tex": ""} for t in lesson_titles]
    if rewrite and not data.get("rewrite_started"):
        for entry in data["lessons"]:
            entry["tex"] = ""
            entry["file"] = ""
            entry.pop("fails", None)
        data["rewrite_started"] = True
        save_working(cid, data)
        print(f"Rewriting {cid} from the start")
    style = open(os.path.join(BOOK, "style_example.tex"), encoding="utf-8").read()
    words = lesson_words(pages, len(lesson_titles))
    made = 0
    for i, t in enumerate(lesson_titles, 1):
        entry = data["lessons"][i - 1]
        if entry.get("tex"):
            continue
        if not budget_ok():
            break
        topics = subs.get(t.lower(), [t])
        out = os.path.join("courses", "pdf", f"{cid}-{i:02d}.tex.tmp")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        safe = entry.get("fails", 0) >= 1
        ok, tries, reasons = write_lesson(i, t, topics, style, out, ask, maths, words=words, safe=safe)
        if ok:
            entry["tex"] = open(out, encoding="utf-8").read()
            entry["file"] = f"tex-{i:02d}"
            entry.pop("fails", None)
            made += 1
            print(f"Accepted LaTeX lesson {i} ({t}) after {tries} tries" + (" in safe mode" if safe else ""))
        else:
            entry["fails"] = entry.get("fails", 0) + 1
            print(f"Lesson {i} ({t}) not accepted after {tries} tries" + (" in safe mode" if safe else "") + ":", "; ".join(reasons))
        if os.path.exists(out):
            os.remove(out)
        save_working(cid, data)
    done = sum(1 for l in data["lessons"] if l.get("tex"))
    missing = [f"{i} ({l['title']}, failed {l.get('fails', 0)}x)" for i, l in enumerate(data["lessons"], 1) if not l.get("tex")]
    print(f"Course status {cid}: {done}/{len(data['lessons'])} lessons accepted" + (f"; missing: {', '.join(missing)}" if missing else ""))
    if done == len(data["lessons"]):
        pages_now, problems = _fit_book(cid, title, data, ask, budget_ok, subs, maths, pages)
        print(f"PDF book courses/pdf/{cid}.pdf: {pages_now} pages (target {pages[0]}-{pages[1]})")
        for p in problems:
            print("  -", p)
    return made, data

def fit_saved(cid, title, data, ask, budget_ok, maths, rng):
    """Fits an already finished book to its page range. Used by the setup and combine rebuild, which previously only assembled it."""
    subs = _read_outline_subtopics(cid)
    return _fit_book(cid, title, data, ask, budget_ok, subs, maths, rng)
