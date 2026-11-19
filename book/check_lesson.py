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

# Environments where & is a column separator and must stay as it is.
_COLUMN_ENVS = "tabular|tabular\\*|tabularx|array|align|align\\*|aligned|alignat|matrix|pmatrix|bmatrix|vmatrix|cases|split|gather"
_SYMBOLS = {"\u2212": "-", "\u2013": "--", "\u2014": "---", "\u2264": "$\\leq$", "\u2265": "$\\geq$", "\u2248": "$\\approx$",
            "\u2260": "$\\neq$", "\u00b1": "$\\pm$", "\u00f7": "$\\div$", "\u2192": "$\\rightarrow$", "\u2190": "$\\leftarrow$",
            "\u21d2": "$\\Rightarrow$", "\u2211": "$\\sum$", "\u221e": "$\\infty$", "\u00bd": "1/2", "\u00bc": "1/4", "\u00be": "3/4",
            "\u2022": "-", "\u2026": "...", "\u00a0": " ", "\u200b": "", "\u2713": "", "\u2714": "", "\u2716": "",
            "\u201c": "``", "\u201d": "''", "\u2018": "`", "\u2019": "'"}

def _fix_stray_items(body):
    """\\item is only valid inside itemize or enumerate. Outside a list it becomes a plain line."""
    out, depth = [], 0
    for line in body.split("\n"):
        depth += len(re.findall(r"\\begin\{(?:itemize|enumerate)\}", line))
        if depth == 0 and re.match(r"^\s*\\item\b", line):
            line = re.sub(r"^\s*\\item\s*", "", line)
        depth = max(0, depth - len(re.findall(r"\\end\{(?:itemize|enumerate)\}", line)))
        out.append(line)
    return "\n".join(out)

def sanitize(body, maths=False):
    """Fixes characters that break LaTeX: bare & % and currency $, plus symbols the font cannot print."""
    for k, v in _SYMBOLS.items():
        body = body.replace(k, v)
    body = _fix_stray_items(body)
    out, depth = [], 0
    for line in body.split("\n"):
        opens = len(re.findall(r"\\begin\{(?:%s)\}" % _COLUMN_ENVS, line))
        closes = len(re.findall(r"\\end\{(?:%s)\}" % _COLUMN_ENVS, line))
        inside = depth > 0 or opens > 0
        depth = max(0, depth + opens - closes)
        if not inside:
            line = re.sub(r"(?<!\\)&", r"\\&", line)
        line = re.sub(r"(?<!\\)%", r"\\%", line)
        if not maths:
            line = re.sub(r"(?<![\\$])\$(?=\d)", r"\\$", line)
        out.append(line)
    return "\n".join(out)

def check_text(body, maths=False):
    reasons = []
    for pat in FORBIDDEN:
        if re.search(pat, body):
            reasons.append("forbidden command for layout or font size: " + pat.replace("\\\\", "\\").replace("\\{", "{").replace("\\}", "}"))
    for name, pat in REQUIRED.items():
        if name == "exercises" and not maths:
            continue  # exercises are only for maths courses
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
        lines = log.splitlines()
        errors = []
        for i, l in enumerate(lines):
            if l.startswith("!"):
                where = next((x for x in lines[i + 1:i + 8] if re.match(r"^l\.\d+", x)), "")
                errors.append(l[1:].strip() + ((" | at " + where.strip()) if where else ""))
        if r.returncode != 0 or errors or not os.path.exists(os.path.join(work, "check.pdf")):
            return None, errors[:4] or ["LaTeX did not produce a PDF"]
        info = subprocess.run(["pdfinfo", os.path.join(work, "check.pdf")], capture_output=True, encoding="utf-8", errors="replace").stdout
        pages = int(re.search(r"Pages:\s+(\d+)", info).group(1))
        return pages, []
    finally:
        shutil.rmtree(work, ignore_errors=True)

def measure(body):
    """Pages a lesson takes when compiled alone, or None if it does not compile."""
    pages, errs = compile_pages(body)
    return None if errs else pages

def check(path, maths=False):
    body = open(path, encoding="utf-8").read()
    reasons = check_text(body, maths)
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
