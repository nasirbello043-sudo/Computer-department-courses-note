"""Writes one [PDF] course as a black-and-white course book, in the style of the Chapter guides:
title page, chapter overview, learning outcomes, numbered sections, callout boxes, figures,
checklist, exercises, summary, terminology table and an educational note."""
import os, re
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Image, PageBreak,
                                Preformatted, Table, TableStyle, KeepTogether, NextPageTemplate)
from pdf_figures import render_figure

NOTE = "Educational note: this book is a study aid. Check important facts with your lecturer or textbook."
SYMBOLS = {"\u2192": "->", "\u2190": "<-", "\u2264": "<=", "\u2265": ">=", "\u2260": "!=", "\u221a": "sqrt",
           "\u03c0": "pi", "\u03b8": "theta", "\u03b1": "alpha", "\u03b2": "beta", "\u03bb": "lambda",
           "\u0394": "Delta", "\u03a3": "sum", "\u2212": "-", "\u00d7": "x", "\u00f7": "/", "\u00b0": " degrees",
           "\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'", "\u2013": "-", "\u2014": " - ", "\u2026": "...",
           "\u25a0": "", "\u25aa": "", "\u25fc": "", "\u25fe": "", "\u200b": ""}
NAVY, RED, GREEN, PALE = "#14243a", "#c64b4b", "#23845b", "#eef2f7"
CALLOUT_START = ("Note:", "Key test:", "Tip:", "Warning:", "Remember:", "Important:", "Educational note")

def _inline(text):
    t = str(text or "")
    for k, v in SYMBOLS.items():
        t = t.replace(k, v)
    t = escape(t)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    t = re.sub(r"`([^`]+)`", r"\1", t)
    t = t.replace("^2", "\u00b2").replace("^3", "\u00b3")
    t = t.replace("**", "").replace("__", "").replace("`", "")
    return t.strip()

def _blocks(text):
    out = []
    for raw in str(text or "").replace("\r", "").split("\n"):
        line = raw.strip()
        if not line or re.fullmatch(r"[-|:\s]+", line):
            continue
        if line.startswith("#"):
            out.append(("h", _inline(line.lstrip("#"))))
        elif line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|") if c.strip()]
            if cells:
                out.append(("li", " - ".join(_inline(c) for c in cells)))
        elif line.startswith(">"):
            out.append(("note", _inline(line.lstrip("> ").strip())))
        elif re.match(r"^[-*]\s+", line):
            out.append(("li", _inline(re.sub(r"^[-*]\s+", "", line))))
        elif re.match(r"^\d+[.)]\s", line):
            for p in re.split(r"\s(?=\d+[.)]\s)", line):
                out.append(("li", _inline(re.sub(r"^\d+[.)]\s*", "", p.strip()))))
        elif line.startswith(CALLOUT_START):
            out.append(("note", _inline(line)))
        else:
            out.append(("p", _inline(line)))
    return out

def styles():
    base = getSampleStyleSheet()
    k = dict(textColor=colors.black)
    return {
        "cover": ParagraphStyle("cover", parent=base["Title"], fontSize=30, leading=36, alignment=0, spaceAfter=10, **k),
        "kicker": ParagraphStyle("kicker", parent=base["BodyText"], fontSize=10, leading=14, textColor=colors.HexColor("#444444")),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontSize=21, leading=26, spaceBefore=4, spaceAfter=10, textColor=colors.HexColor(NAVY)),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=14, leading=19, spaceBefore=12, spaceAfter=5, textColor=colors.HexColor(NAVY)),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontSize=11.5, leading=15, spaceBefore=8, spaceAfter=3, textColor=colors.HexColor(NAVY)),
        "body": ParagraphStyle("body", parent=base["BodyText"], fontSize=10.5, leading=15, spaceAfter=7, alignment=4, **k),
        "li": ParagraphStyle("li", parent=base["BodyText"], fontSize=10.5, leading=14.5, leftIndent=16, bulletIndent=3, spaceAfter=3, **k),
        "callout": ParagraphStyle("callout", parent=base["BodyText"], fontSize=10, leading=14, **k),
        "cell": ParagraphStyle("cell", parent=base["BodyText"], fontSize=9.5, leading=12.5, **k),
        "cellhead": ParagraphStyle("cellhead", parent=base["BodyText"], fontSize=9.5, leading=12.5, fontName="Helvetica-Bold", **k),
        "caption": ParagraphStyle("caption", parent=base["BodyText"], fontSize=9, leading=12, alignment=1, spaceBefore=3, spaceAfter=8, **k),
        "code": ParagraphStyle("code", fontName="Courier", fontSize=9, leading=12, leftIndent=8),
    }

def _safe(txt, style, **kw):
    try:
        return Paragraph(txt, style, **kw)
    except Exception:
        return Paragraph(escape(re.sub(r"<[^>]+>", "", txt)), style, **kw)

def _callout(txt, st):
    plain = re.sub(r"<[^>]+>", "", txt)
    bar = colors.HexColor(RED if plain.startswith(("Key test", "Warning", "Important")) else
                          GREEN if plain.startswith("Tip") else NAVY)
    box = Table([[_safe(txt, st["callout"])]], colWidths=[15.4 * cm])
    box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9d1dc")),
                             ("LINEBEFORE", (0, 0), (0, -1), 4, bar),
                             ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(PALE)),
                             ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                             ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return [box, Spacer(1, 8)]

def _prose(text, st):
    flow = []
    for kind, txt in _blocks(text):
        if not txt:
            continue
        if kind == "h":
            flow.append(_safe(txt, st["h3"]))
        elif kind == "li":
            flow.append(_safe(txt, st["li"], bulletText="\u2022"))
        elif kind == "note":
            flow.extend(_callout(txt, st))
        else:
            flow.append(_safe(txt, st["body"]))
    return flow

def _figures(les, st, cid, n):
    out = []
    for idx, g in enumerate(les.get("diagrams") or [], 1):
        cap = _inline(g.get("caption") or g.get("title") or "")
        label = f"Figure {n}.{idx}. {cap}" if cap else f"Figure {n}.{idx}."
        png = None
        if g.get("type") in ("graph", "conic", "parametric"):
            png = render_figure(dict(g, caption=""), os.path.join("courses", "images", f"pdf-{cid}-{n:02d}-{idx}.png"))
        elif g.get("type") == "image" and g.get("file"):
            p = os.path.join("courses", "images", g["file"])
            if os.path.exists(p) and p.lower().endswith((".png", ".jpg", ".jpeg")):
                png = p
        if png:
            img = Image(png)
            ratio = img.imageHeight / float(img.imageWidth or 1)
            w = 12 * cm
            img.drawWidth, img.drawHeight = w, w * ratio
            if img.drawHeight > 9 * cm:
                img.drawHeight, img.drawWidth = 9 * cm, 9 * cm / ratio
            out.append(KeepTogether([img, _safe(label, st["caption"])]))
        else:
            box = Table([[_safe(f"[Figure to be added: {cap or 'diagram'}]", st["callout"])]], colWidths=[15.4 * cm])
            box.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, colors.black, None, (2, 2)),
                                     ("TOPPADDING", (0, 0), (-1, -1), 26), ("BOTTOMPADDING", (0, 0), (-1, -1), 26)]))
            out.append(KeepTogether([box, _safe(label, st["caption"])]))
    return out

def _terms_table(terms, st):
    head = ParagraphStyle("head2", parent=st["cellhead"], textColor=colors.white)
    rows = [[_safe("Term", head), _safe("Meaning", head)]]
    rows += [[_safe(_inline(t.get("term")), st["cell"]), _safe(_inline(t.get("meaning")), st["cell"])] for t in terms]
    tbl = Table(rows, colWidths=[4.2 * cm, 11.2 * cm], repeatRows=1)
    tbl.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.black),
                             ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)),
                             ("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return [tbl, Spacer(1, 8)]

def build_pdf(cid, title, lessons, out_path):
    """lessons: list of lesson data dicts (None = not written yet). Writes the course book to out_path."""
    st = styles()
    cover_style = ParagraphStyle("cover2", parent=st["cover"], textColor=colors.white)
    kick_style = ParagraphStyle("kick2", parent=st["kicker"], textColor=colors.HexColor("#cfd8e3"))
    block = Table([[[Spacer(1, 1.6 * cm), _safe("COURSE BOOK", kick_style), Spacer(1, 6),
                     _safe(_inline(title), cover_style), Spacer(1, 6),
                     _safe("Study guide", kick_style), Spacer(1, 1.6 * cm)]]], colWidths=[15.4 * cm])
    block.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(NAVY)),
                               ("LEFTPADDING", (0, 0), (-1, -1), 22), ("RIGHTPADDING", (0, 0), (-1, -1), 22)]))
    story = [Spacer(1, 4 * cm), block, Spacer(1, 1.2 * cm)]
    story.extend(_callout(NOTE, st))
    written = [(n, les) for n, les in enumerate(lessons, 1) if les]
    for n, les in written:
        story.append(PageBreak())
        story.append(Paragraph(f"<font size=9>LESSON {n}</font>", st["kicker"]))
        story.append(_safe(_inline(f"{n}. {les.get('title') or ''}"), st["h1"]))
        if les.get("summary"):
            story.append(_safe("Lesson overview", st["h2"]))
            story.extend(_prose(les["summary"], st))
        if les.get("objectives"):
            story.append(_safe("Learning outcomes", st["h2"]))
            for o in les["objectives"]:
                story.append(_safe(_inline(o), st["li"], bulletText="\u2022"))
        for k, sec in enumerate(les.get("sections", []), 1):
            story.append(_safe(f"{n}.{k}  {_inline(sec.get('heading'))}", st["h2"]))
            story.extend(_prose(sec.get("body"), st))
            if sec.get("code"):
                story.append(Preformatted(str(sec["code"]), st["code"]))
                story.append(Spacer(1, 6))
            if k == 1:
                story.extend(_figures(les, st, cid, n))
        if les.get("key_terms"):
            story.append(_safe("Terminology at a glance", st["h2"]))
            story.extend(_terms_table(les["key_terms"], st))
        if les.get("practice"):
            story.append(_safe("Practical application", st["h2"]))
            for i, p in enumerate(les["practice"], 1):
                q = p.get("question") if isinstance(p, dict) else p
                story.append(_safe(f"Exercise {n}.{i}: {_inline(q)}", st["body"]))
        if les.get("objectives"):
            items = [_safe(f"[  ]  {_inline(o)}", st["li"]) for o in les["objectives"]]
            story.append(_safe("Checklist", st["h2"]))
            story.extend(items)
    story.append(PageBreak())
    story.extend(_callout(NOTE, st))

    def cover(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.black)
        canvas.rect(0, A4[1] - 0.6 * cm, A4[0], 0.6 * cm, stroke=0, fill=1)
        canvas.restoreState()

    def later(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.black)
        canvas.drawString(2.3 * cm, A4[1] - 1.5 * cm, _inline(title).replace("&amp;", "&").upper())
        canvas.drawRightString(A4[0] - 2.3 * cm, A4[1] - 1.5 * cm, f"Page {doc.page}")
        canvas.setStrokeColor(colors.black); canvas.setLineWidth(0.5)
        canvas.line(2.3 * cm, A4[1] - 1.7 * cm, A4[0] - 2.3 * cm, A4[1] - 1.7 * cm)
        canvas.restoreState()

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    doc = BaseDocTemplate(out_path, pagesize=A4, title=title, author="Learning Hub")
    frame = Frame(2.3 * cm, 2.2 * cm, A4[0] - 4.6 * cm, A4[1] - 4.4 * cm, id="body")
    doc.addPageTemplates([PageTemplate(id="cover", frames=[frame], onPage=cover),
                          PageTemplate(id="later", frames=[frame], onPage=later)])
    doc.build(story)
    return out_path
