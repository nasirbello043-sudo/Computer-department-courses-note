"""LaTeX route for PDF courses (writers 4-6).
Each lesson is written in LaTeX, checked by the compile gate, and kept only if it passes.
Accepted lessons are stored in courses/pdf/<course>.json; the book is assembled from them."""
import json, os, re, subprocess, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
BOOK = os.path.join(HERE, "book")
sys.path.insert(0, BOOK)
from write_lesson import write_lesson  # noqa: E402
from check_lesson import check_text  # noqa: E402

MIN_BOOK_PAGES = 20
MAX_BOOK_PAGES = 40
EXPAND_ROUNDS = 2  # per run, to keep within the daily allowance

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

def assemble(cid, title, data, out_pdf):
    """Joins the accepted lessons into one book. Returns (pages, problems)."""
    tex_lessons = [l["tex"] for l in data.get("lessons", []) if l.get("tex")]
    work = tempfile.mkdtemp()
    try:
        shutil.copy(os.path.join(BOOK, "template.tex"), work)
        head = open(os.path.join(BOOK, "template.tex"), encoding="utf-8").read()
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
        if pages > MAX_BOOK_PAGES:
            problems.append(f"book is {pages} pages, over the {MAX_BOOK_PAGES}-page cap")
        if pages < MIN_BOOK_PAGES:
            problems.append(f"book is {pages} pages, below the {MIN_BOOK_PAGES}-page minimum")
        return pages, problems
    finally:
        shutil.rmtree(work, ignore_errors=True)

def _lesson_pages(tex, work_dir):
    from check_lesson import check
    tmp = os.path.join(work_dir, "measure.tex")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(tex)
    pages, reasons = check(tmp)
    return pages if not reasons else None

def _expand_book(cid, title, data, ask, budget_ok, subs):
    """If the book is under the minimum, rewrite the shortest lessons with more depth.
    A rewrite is kept only if the lesson gets longer. Returns the final (pages, problems)."""
    work = tempfile.mkdtemp()
    try:
        pages, problems = assemble(cid, title, data, f"courses/pdf/{cid}.pdf")
        rounds = 0
        while pages < MIN_BOOK_PAGES and rounds < EXPAND_ROUNDS and budget_ok():
            rounds += 1
            lengths = []
            for idx, entry in enumerate(data["lessons"]):
                n = _lesson_pages(entry["tex"], work) or 1
                lengths.append((n, idx))
            lengths.sort()
            for n_old, idx in lengths[:3]:
                if not budget_ok():
                    break
                entry = data["lessons"][idx]
                topics = subs.get(entry["title"].lower(), [entry["title"]])
                out = os.path.join("courses", "pdf", f"{cid}-expand-{idx + 1:02d}.tex.tmp")
                os.makedirs(os.path.dirname(out), exist_ok=True)
                task = (entry["title"] + " (EXPAND: rewrite this lesson with more depth: "
                        "more worked examples and fuller explanation for each sub-topic; keep the same layout and structure)")
                ok, tries, reasons = write_lesson(idx + 1, task, topics, entry["tex"], out, ask)
                if ok:
                    new = open(out, encoding="utf-8").read()
                    n_new = _lesson_pages(new, work) or 0
                    if n_new > n_old:
                        entry["tex"] = new
                        print(f"Expanded lesson {idx + 1} ({entry['title']}): {n_old} -> {n_new} pages")
                    else:
                        print(f"Expansion of lesson {idx + 1} ({entry['title']}) was not longer ({n_new} vs {n_old} pages), old version kept")
                else:
                    print(f"Expansion of lesson {idx + 1} ({entry['title']}) not accepted:", "; ".join(reasons))
                if os.path.exists(out):
                    os.remove(out)
            save_working(cid, data)
            pages, problems = assemble(cid, title, data, f"courses/pdf/{cid}.pdf")
        return pages, problems
    finally:
        shutil.rmtree(work, ignore_errors=True)

def tex_course(cid, title, theme, lesson_titles, ask, budget_ok, rewrite=False):
    """Writes every missing lesson of a PDF course. ask(prompt) returns text. budget_ok() returns False when time is up.
    rewrite=True clears the saved lessons once, so the whole course is written again (used for courses that are too short)."""
    subs = _read_outline_subtopics(cid)
    data = load_working(cid, title, theme)
    if len(data["lessons"]) != len(lesson_titles):
        data["lessons"] = [{"title": t, "file": "", "tex": ""} for t in lesson_titles]
    if rewrite and not data.get("rewrite_started"):
        for entry in data["lessons"]:
            entry["tex"] = ""
            entry["file"] = ""
        data["rewrite_started"] = True
        save_working(cid, data)
        print(f"Rewriting {cid} from the start")
    style = open(os.path.join(BOOK, "style_example.tex"), encoding="utf-8").read()
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
        ok, tries, reasons = write_lesson(i, t, topics, style, out, ask)
        if ok:
            entry["tex"] = open(out, encoding="utf-8").read()
            entry["file"] = f"tex-{i:02d}"
            made += 1
            print(f"Accepted LaTeX lesson {i} ({t}) after {tries} tries")
        else:
            print(f"Lesson {i} ({t}) not accepted after {tries} tries:", "; ".join(reasons))
        if os.path.exists(out):
            os.remove(out)
        save_working(cid, data)
    if all(l.get("tex") for l in data["lessons"]):
        pages, problems = _expand_book(cid, title, data, ask, budget_ok, subs)
        print(f"PDF book courses/pdf/{cid}.pdf: {pages} pages")
        for p in problems:
            print("  -", p)
    return made, data
