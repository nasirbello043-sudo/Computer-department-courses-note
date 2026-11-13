"""Writes one [PDF] course as a black-and-white PDF book from the lesson data in course.json."""
import os
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from pdf_figures import render_figure
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak, Preformatted, ListFlowable, ListItem, KeepTogether

NOTE = "We can make mistakes, and we'll be happy if you report any mistakes you find."
SYMBOLS = {"\u2192": "->", "\u2190": "<-", "\u2264": "<=", "\u2265": ">=", "\u2260": "!=", "\u221a": "sqrt",
           "\u00b2": "^2", "\u00b3": "^3", "\u03c0": "pi", "\u03b8": "theta", "\u03b1": "alpha", "\u03b2": "beta",
           "\u03bb": "lambda", "\u0394": "Delta", "\u03a3": "sum", "\u222b": "integral of ", "\u2212": "-",
           "\u00d7": "x", "\u00f7": "/", "\u00b0": " degrees", "\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'",
           "\u2013": "-", "\u2014": " - ", "\u2026": "..."}

def clean(text):
    t = str(text or "")
    for k, v in SYMBOLS.items():
        t = t.replace(k, v)
    return escape(t)


import re as _re

def _inline(text):
    """Turn a line of lesson text into safe PDF markup: bold/italics kept, markdown symbols removed."""
    t = str(text or "").replace("\u25a0", "-").replace("\u200b", "")
    t = escape(t)
    t = _re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = _re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    t = _re.sub(r"`([^`]+)`", r"\1", t)
    t = t.replace("^2", "\u00b2").replace("^3", "\u00b3")
    t = _re.sub(r"\^(\w+)", r"^\1", t)
    t = t.replace("**", "").replace("__", "").replace("`", "")
    for k, v in SYMBOLS.items():
        t = t.replace(k, v)
    return t.strip()

def _blocks(text):
    """Split lesson text into headings, bullet points, notes and paragraphs."""
    out = []
    for raw in str(text or "").replace("\r", "").split("\n"):
        line = raw.strip()
        if not line or _re.fullmatch(r"[-|:\s]+", line):
            continue
        if line.startswith("#"):
            out.append(("h", _inline(line.lstrip("#"))))
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|") if c.strip()]
            if cells:
                out.append(("li", " - ".join(_inline(c) for c in cells)))
        elif line.startswith(">"):
            out.append(("note", _inline(line.lstrip("> ").strip())))
        elif _re.match(r"^[-*]\s+", line):
            out.append(("li", _inline(_re.sub(r"^[-*]\s+", "", line))))
        elif _re.match(r"^\d+[.)]\s", line):
            parts = _re.split(r"\s(?=\d+[.)]\s)", line)
            for p in parts:
                out.append(("li", _inline(_re.sub(r"^\d+[.)]\s*", "", p.strip()))))
        else:
            out.append(("p", _inline(line)))
    return out

def _safe_para(txt, style, **kw):
    try:
        return Paragraph(txt, style, **kw)
    except Exception:
        plain = _re.sub(r"<[^>]+>", "", txt).replace("&amp;", "&")
        return Paragraph(escape(plain), style, **kw)

def _prose(text, st, width_style="body"):
    """Flowables for a block of lesson text, in a clean black-and-white layout."""
    flow = []
    for kind, txt in _blocks(text):
        if not txt:
            continue
        if kind == "h":
            flow.append(_safe_para(txt, st["h3"]))
        elif kind == "li":
            flow.append(_safe_para(txt, st["li"], bulletText="\u2022"))
        elif kind == "note":
            flow.append(_safe_para(txt, st["note"]))
        else:
            flow.append(_safe_para(txt, st["body"]))
    return flow

def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], textColor=colors.black, fontSize=26, leading=32, spaceAfter=14),
        "lesson": ParagraphStyle("lesson", parent=base["Heading1"], textColor=colors.black, fontSize=19, leading=24, spaceBefore=6, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], textColor=colors.black, fontSize=13.5, leading=18, spaceBefore=10, spaceAfter=5),
        "body": ParagraphStyle("body", parent=base["BodyText"], textColor=colors.black, fontSize=10.5, leading=15, spaceAfter=7),
        "small": ParagraphStyle("small", parent=base["BodyText"], textColor=colors.black, fontSize=9, leading=12, spaceAfter=4),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], textColor=colors.black, fontSize=11.5, leading=15, spaceBefore=8, spaceAfter=4),
        "li": ParagraphStyle("li", parent=base["BodyText"], textColor=colors.black, fontSize=10.5, leading=14.5, leftIndent=16, bulletIndent=4, spaceAfter=3),
        "note": ParagraphStyle("note", parent=base["BodyText"], textColor=colors.black, fontSize=9, leading=12, borderColor=colors.black, borderWidth=0.6, borderPadding=6, spaceBefore=14),
    }

def _pictures(les, st, width, cid="course", lesson_no=0):
    out = []
    for idx, g in enumerate(les.get("diagrams") or [], 1):
        cap = clean(g.get("caption") or g.get("title") or "")
        if g.get("type") in ("graph", "conic", "parametric"):
            png = render_figure(g, os.path.join("courses", "images", f"pdf-{cid}-{lesson_no:02d}-{idx}.png"))
            if png:
                g = {"type": "image", "file": os.path.basename(png), "caption": g.get("caption") or g.get("title") or ""}
            else:
                out.append(Paragraph("Figure: " + cap, st["small"])); continue
        if g.get("type") != "image":
            continue
        path = g.get("file") or ""
        if path and os.path.exists(os.path.join("courses", "images", path)) and path.lower().endswith((".png", ".jpg", ".jpeg")):
            img = Image(os.path.join("courses", "images", path))
            ratio = img.imageHeight / float(img.imageWidth or 1)
            img.drawWidth, img.drawHeight = width, width * ratio
            if img.drawHeight > 9 * cm:
                img.drawHeight, img.drawWidth = 9 * cm, 9 * cm / ratio
            out.append(KeepTogether([img, Paragraph("Figure: " + cap, st["small"]), Spacer(1, 6)]))
        else:
            out.append(Paragraph("Figure (described): " + cap, st["small"]))
    return out

def build_pdf(cid, title, lessons, out_path):
    """lessons: list of lesson data dicts (the 'data' of each lesson in course.json; None = not written yet)."""
    st = styles()
    story = [Paragraph(clean(title), st["title"]), Spacer(1, 8)]
    for n, les in enumerate(lessons, 1):
        if not les:
            continue
        story.append(PageBreak())
        story.append(Paragraph(f"{n}. {clean(les.get('title') or '')}", st["lesson"]))
        if les.get("summary"):
            story.extend(_prose(les["summary"], st))
        if les.get("objectives"):
            story.append(Paragraph("What you will be able to do", st["h2"]))
            for o in les["objectives"]:
                story.extend(_prose("- " + str(o), st))
        width = 15 * cm
        for sec in les.get("sections", []):
            story.append(Paragraph(clean(sec.get("heading")), st["h2"]))
            story.extend(_prose(sec.get("body"), st))
            if sec.get("code"):
                story.append(Preformatted(str(sec["code"]), ParagraphStyle("code", fontName="Courier", fontSize=9, leading=12)))
                story.append(Spacer(1, 6))
        story.extend(_pictures(les, st, width, cid, n))
        if les.get("key_terms"):
            story.append(Paragraph("Key terms", st["h2"]))
            for kt in les["key_terms"]:
                story.append(Paragraph(f"<b>{_inline(kt.get('term'))}</b>: {_inline(kt.get('meaning'))}", st["li"], bulletText="\u2022"))
    story.append(Spacer(1, 16))
    story.append(Paragraph(clean(NOTE), st["note"]))

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.black)
        canvas.drawCentredString(A4[0] / 2, 1.2 * cm, f"{clean(title)}  |  page {doc.page}")
        canvas.restoreState()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    doc = SimpleDocTemplate(out_path, pagesize=A4, leftMargin=2.3 * cm, rightMargin=2.3 * cm,
                            topMargin=2.2 * cm, bottomMargin=2.2 * cm, title=title, author="Learning Hub")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out_path
