from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .manual_content import MANUAL_SECTIONS, MANUAL_SUBTITLE, MANUAL_TITLE
from .runtime import APP_VERSION


ACCENT = colors.HexColor("#12355B")
LIGHT = colors.HexColor("#EAF2FB")
TEXT = colors.HexColor("#243247")
MUTED = colors.HexColor("#617187")
BORDER = colors.HexColor("#D8E1EC")


def _page_footer(canvas, doc):
    canvas.saveState()
    width, _height = A4
    canvas.setStrokeColor(BORDER)
    canvas.line(18 * mm, 14 * mm, width - 18 * mm, 14 * mm)
    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(18 * mm, 9 * mm, f"SICORPA {APP_VERSION} - Manuel utilisateur")
    canvas.drawRightString(width - 18 * mm, 9 * mm, f"Page {doc.page}")
    canvas.restoreState()


def generate_user_manual_pdf(target: str | Path) -> Path:
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")

    doc = SimpleDocTemplate(
        str(temporary), pagesize=A4,
        rightMargin=18 * mm, leftMargin=18 * mm,
        topMargin=18 * mm, bottomMargin=20 * mm,
        title=MANUAL_TITLE, author="SICORPA",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "ManualTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=23, leading=28, textColor=ACCENT, alignment=TA_CENTER, spaceAfter=10,
    )
    subtitle = ParagraphStyle(
        "ManualSubtitle", parent=styles["Normal"], fontSize=11, leading=15,
        textColor=MUTED, alignment=TA_CENTER, spaceAfter=18,
    )
    h1 = ParagraphStyle(
        "ManualH1", parent=styles["Heading1"], fontName="Helvetica-Bold",
        fontSize=14, leading=18, textColor=ACCENT, spaceBefore=8, spaceAfter=8,
    )
    body = ParagraphStyle(
        "ManualBody", parent=styles["BodyText"], fontName="Helvetica",
        fontSize=9.4, leading=13.5, textColor=TEXT, spaceAfter=7,
    )
    note = ParagraphStyle(
        "ManualNote", parent=body, fontSize=9, leading=13, textColor=ACCENT,
        leftIndent=7, rightIndent=7,
    )

    story = [Spacer(1, 18 * mm), Paragraph(MANUAL_TITLE, title), Paragraph(MANUAL_SUBTITLE, subtitle)]
    meta = Table([
        ["Version", APP_VERSION],
        ["Edition", datetime.now().strftime("%d/%m/%Y")],
        ["Objet", "Utilisation, controle, interpretation des rapports et annexes"],
    ], colWidths=[38 * mm, 115 * mm])
    meta.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), LIGHT),
        ("TEXTCOLOR", (0, 0), (-1, -1), TEXT),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    story.extend([meta, Spacer(1, 12 * mm)])
    callout = Table([[Paragraph(
        "Principe de lecture : toujours distinguer lignes physiques, occurrences, repetitions, agents uniques et regimes distincts. Une alerte SICORPA est un signal de controle, pas une conclusion administrative automatique.",
        note,
    )]], colWidths=[153 * mm])
    callout.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.8, ACCENT),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    story.extend([callout, PageBreak()])

    story.append(Paragraph("Sommaire", h1))
    for heading, _paragraphs in MANUAL_SECTIONS:
        story.append(Paragraph(heading, body))
    story.append(PageBreak())

    for heading, paragraphs in MANUAL_SECTIONS:
        story.append(Paragraph(heading, h1))
        for paragraph in paragraphs:
            story.append(Paragraph(paragraph.replace("&", "&amp;"), body))
        story.append(Spacer(1, 3 * mm))

    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    temporary.replace(target)
    return target
