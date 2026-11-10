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

def styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title", parent=base["Title"], textColor=colors.black, fontSize=26, leading=32, spaceAfter=14),
        "lesson": ParagraphStyle("lesson", parent=base["Heading1"], textColor=colors.black, fontSize=19, leading=24, spaceBefore=6, spaceAfter=10),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], textColor=colors.black, fontSize=13.5, leading=18, spaceBefore=10, spaceAfter=5),
        "body": ParagraphStyle("body", parent=base["BodyText"], textColor=colors.black, fontSize=10.5, leading=15, spaceAfter=7),
        "small": ParagraphStyle("small", parent=base["BodyText"], textColor=colors.black, fontSize=9, leading=12, spaceAfter=4),
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
            story.append(Paragraph(clean(les["summary"]), st["body"]))
        if les.get("objectives"):
            story.append(Paragraph("What you will be able to do", st["h2"]))
            story.append(ListFlowable([ListItem(Paragraph(clean(o), st["body"]), leftIndent=14) for o in les["objectives"]],
                                      bulletType="bullet", start="-", leftIndent=14))
        width = 15 * cm
        for sec in les.get("sections", []):
            story.append(Paragraph(clean(sec.get("heading")), st["h2"]))
            for para in str(sec.get("body") or "").split("\n\n"):
                if para.strip():
                    story.append(Paragraph(clean(para.strip()), st["body"]))
            if sec.get("code"):
                story.append(Preformatted(str(sec["code"]), ParagraphStyle("code", fontName="Courier", fontSize=9, leading=12)))
                story.append(Spacer(1, 6))
        story.extend(_pictures(les, st, width, cid, n))
        if les.get("key_terms"):
            story.append(Paragraph("Key terms", st["h2"]))
            for kt in les["key_terms"]:
                story.append(Paragraph(f"<b>{clean(kt.get('term'))}</b>: {clean(kt.get('meaning'))}", st["body"]))
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
