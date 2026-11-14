"""LaTeX route for PDF courses (writers 4-6).
Each lesson is written in LaTeX, checked by the compile gate, and kept only if it passes.
Accepted lessons are stored in courses/pdf/<course>.json; the book is assembled from them."""
import json, os, re, subprocess, shutil, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
BOOK = os.path.join(HERE, "book")
sys.path.insert(0, BOOK)
from write_lesson import write_lesson  # noqa: E402
from check_lesson import check_text  # noqa: E402

MAX_BOOK_PAGES = 40

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
        body = "\\input{template}\n\\begin{document}\n" + "\n\\clearpage\n".join(tex_lessons) + "\n\\end{document}\n"
        with open(os.path.join(work, "book.tex"), "w", encoding="utf-8") as f:
            f.write(body)
        for _ in range(2):
            subprocess.run(["pdflatex", "-interaction=nonstopmode", "book.tex"], cwd=work, capture_output=True)
        built = os.path.join(work, "book.pdf")
        if not os.path.exists(built):
            return 0, ["the book did not compile"]
        info = subprocess.run(["pdfinfo", built], capture_output=True, text=True).stdout
        pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
        os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
        shutil.copy(built, out_pdf)
        problems = []
        if pages > MAX_BOOK_PAGES:
            problems.append(f"book is {pages} pages, over the {MAX_BOOK_PAGES}-page cap")
        return pages, problems
    finally:
        shutil.rmtree(work, ignore_errors=True)

def tex_course(cid, title, theme, lesson_titles, ask, budget_ok):
    """Writes every missing lesson of a PDF course. ask(prompt) returns text. budget_ok() returns False when time is up."""
    subs = _read_outline_subtopics(cid)
    data = load_working(cid, title, theme)
    if len(data["lessons"]) != len(lesson_titles):
        data["lessons"] = [{"title": t, "file": "", "tex": ""} for t in lesson_titles]
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
        pages, problems = assemble(cid, title, data, f"courses/pdf/{cid}.pdf")
        print(f"PDF book courses/pdf/{cid}.pdf: {pages} pages")
        for p in problems:
            print("  -", p)
    return made, data
