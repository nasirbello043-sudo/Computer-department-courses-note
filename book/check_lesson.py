"""Compile gate: checks one lesson against the fixed template before it is accepted.
Usage: python check_lesson.py lesson.tex
Exit 0 = accepted. Exit 1 = rejected, with the reasons printed for the writer to fix."""
import os, re, subprocess, sys, tempfile, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
MIN_PAGES = 1  # a lesson needs at least one full page; its length is otherwise set by its content
MAX_PAGES = None  # no per-lesson maximum: the 40-page cap applies to the whole course
# Anything that changes the size or layout of the text is refused.
FORBIDDEN = [r"\\small", r"\\large", r"\\Large", r"\\LARGE", r"\\huge", r"\\Huge", r"\\tiny", r"\\scriptsize",
             r"\\footnotesize", r"\\normalsize", r"\\fontsize", r"\\scalebox", r"\\resizebox", r"\\linespread",
             r"\\setlength", r"\\geometry", r"\\documentclass", r"\\begin\{document\}", r"\\usepackage", r"\\vspace"]
REQUIRED = {
    "learning outcomes box": r"\\begin\{note\}\s*\\textbf\{Learning outcomes",
    "at least one worked example": r"\\begin\{example\}",
    "at least one key test": r"\\begin\{keytest\}",
    "exercises": r"\\subsection\{Exercises\}",
    "key terms table": r"\\subsection\{Key terms\}",
}

def check_text(body):
    reasons = []
    for pat in FORBIDDEN:
        if re.search(pat, body):
            reasons.append("forbidden command for layout or font size: " + pat.replace("\\\\", "\\").replace("\\{", "{").replace("\\}", "}"))
    for name, pat in REQUIRED.items():
        if not re.search(pat, body):
            reasons.append("missing: " + name)
    return reasons

def compile_pages(body):
    work = tempfile.mkdtemp()
    try:
        shutil.copy(os.path.join(HERE, "template.tex"), work)
        with open(os.path.join(work, "lesson.tex"), "w", encoding="utf-8") as f:
            f.write(body)
        doc = "\\input{template}\n\\begin{document}\n\\input{lesson}\n\\end{document}\n"
        with open(os.path.join(work, "check.tex"), "w", encoding="utf-8") as f:
            f.write(doc)
        r = subprocess.run(["pdflatex", "-interaction=nonstopmode", "check.tex"], cwd=work, capture_output=True, encoding="utf-8", errors="replace")
        log = r.stdout
        errors = [l for l in log.splitlines() if l.startswith("!")]
        if r.returncode != 0 or errors or not os.path.exists(os.path.join(work, "check.pdf")):
            return None, errors[:5] or ["LaTeX did not produce a PDF"]
        info = subprocess.run(["pdfinfo", os.path.join(work, "check.pdf")], capture_output=True, encoding="utf-8", errors="replace").stdout
        pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
        return pages, []
    finally:
        shutil.rmtree(work, ignore_errors=True)

def check(path):
    body = open(path, encoding="utf-8").read()
    reasons = check_text(body)
    pages, errs = compile_pages(body)
    if errs:
        reasons += ["LaTeX error: " + e for e in errs]
    elif pages is not None:
        if pages < MIN_PAGES:
            reasons.append("too short: the lesson must fill at least one full page. Cover the outline fully. Do not change font or layout.")
    return pages, reasons

if __name__ == "__main__":
    pages, reasons = check(sys.argv[1])
    print(f"pages: {pages}")
    if reasons:
        print("REJECTED")
        for r in reasons:
            print(" -", r)
        sys.exit(1)
    print("ACCEPTED")
