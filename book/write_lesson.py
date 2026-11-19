"""Writes one lesson in LaTeX, checks it with the compile gate, and retries with the reasons if it fails.
ask(prompt) is any function that returns the model's text (the Groq call in the workflow)."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from check_lesson import check, sanitize

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_TRIES = 3

RULES = r"""You write one lesson of a university course book in LaTeX.
Use ONLY these environments and commands:
  \lessonlabel{N}  then  \section{Title}  then  \subsection{...} for each part.
  \begin{note} \textbf{Learning outcomes.} ... \begin{itemize} ... \end{itemize} \end{note}   (first, after the section title)
  \begin{example} ... \end{example}   (a worked example for the most important rules or methods; one or two per lesson)
  \begin{keytest} \textbf{Key test.} ... \end{keytest}
  \subsection{Exercises} with an enumerate list (ONLY if this is a maths course; otherwise leave it out)
  \subsection{Key terms} with a tabular of Term and Meaning
Maths uses $...$ or \[ ... \]. Use \term{...} for new terms.
Write plainly and directly. No filler, no motivational talk, no summary section.
Cover every sub-topic listed for this lesson, each with its own subsection.
Do NOT use font-size, spacing, scaling or geometry commands.
Use \\item ONLY inside an itemize or enumerate list. Never write \\item in ordinary paragraphs. Never put words inside $...$; text is never maths. Do NOT use \documentclass, \usepackage or \begin{document}.
In ordinary text write \$ for a dollar sign, \% for percent and \& for an ampersand. Use a plain hyphen for minus in text. Maths symbols go inside $...$.
A page holds about 240 words, so use the length target you are given.
Reply with the LaTeX only. No explanation, no code fences."""

SAFE_RULES = """SAFE MODE (earlier attempts at this lesson failed to compile): write plain prose and simple lists only.
Do not use any table except the Key terms table. Do not use $, %, &, #, _ or any maths in the text: spell out 'percent', 'dollars' and 'and'.
Keep the required boxes and sections exactly as in the style example."""

def build_prompt(lesson_no, outline_line, subtopics, style_example, reasons=None, words=None, safe=False):
    p = RULES + "\n\nLESSON NUMBER: %d\nOUTLINE: %s\nSUB-TOPICS TO COVER: %s\n" % (lesson_no, outline_line, "; ".join(subtopics))
    if words:
        p += "LENGTH TARGET: about %d words in total for this lesson.\n" % words
    if safe:
        p += "\n" + SAFE_RULES + "\n"
    p += "\nSTYLE EXAMPLE (match this voice, notation and structure):\n" + style_example + "\n"
    if reasons:
        p += "\nYOUR PREVIOUS DRAFT WAS REJECTED FOR:\n- " + "\n- ".join(reasons) + "\nFix all of these and send the complete corrected lesson.\n"
    return p

def clean(text):
    t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text.strip())
    return t.strip() + "\n"

def write_lesson(lesson_no, outline_line, subtopics, style_example, out_path, ask, maths=False, words=None, safe=False):
    reasons = None
    for attempt in range(1, MAX_TRIES + 1):
        reply = ask(build_prompt(lesson_no, outline_line, subtopics, style_example, reasons, words, safe))
        if not reply or not str(reply).strip():
            reasons = ["the model gave no reply; trying again"]
            continue  # an empty reply is a failed try, not a crash
        body = sanitize(clean(str(reply)), maths)
        tmp = out_path + ".draft"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(body)
        pages, reasons = check(tmp, maths)
        if not reasons:
            os.replace(tmp, out_path)
            return True, attempt, []
    if os.path.exists(out_path + ".draft"):
        os.remove(out_path + ".draft")
    return False, MAX_TRIES, reasons
