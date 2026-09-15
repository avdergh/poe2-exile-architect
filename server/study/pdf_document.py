"""Paginated learning handbook with vector mechanism diagrams and navigable sections."""

from __future__ import annotations

from io import BytesIO
import hashlib
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfdoc import PDFString
from reportlab.platypus import (
    BaseDocTemplate,
    Flowable,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .guide import LearningGuide
from .pdf_inline import Paragraph

INK = colors.HexColor("#172F36")
ACCENT = colors.HexColor("#286A72")
PALE = colors.HexColor("#EFF5F5")
GREY = colors.HexColor("#D9D9D9")
WIDTH, HEIGHT = 595.28, 841.89
MARGIN = 50


class MechanismDiagram(Flowable):
    """Text wraps within real vector nodes; geometry never implies measured numbers."""

    def __init__(self, steps, style):
        Flowable.__init__(self)
        self.steps = steps
        self.style = style

    def wrap(self, available_width, available_height):
        self.width = available_width
        self.cards = []
        horizontal = len(self.steps) <= 3
        card_width = (
            (available_width - 18 * (len(self.steps) - 1)) / len(self.steps)
            if horizontal
            else available_width
        )
        for i, (label, explanation) in enumerate(self.steps, 1):
            label_p = Paragraph(f"{i:02d}  {label}", self.style["flowTitle"])
            body_p = Paragraph(explanation, self.style["small"])
            lh = label_p.wrap(card_width - 24, 1000)[1]
            bh = body_p.wrap(card_width - 24, 1000)[1]
            self.cards.append((label_p, body_p, lh, bh, max(74, lh + bh + 30)))
        self.height = (
            max(c[-1] for c in self.cards)
            if horizontal
            else sum(c[-1] for c in self.cards) + 13 * (len(self.cards) - 1)
        )
        self.horizontal, self.card_width = horizontal, card_width
        return self.width, self.height

    def draw(self):
        canvas = self.canv
        y = self.height
        for i, (label, body, lh, bh, height) in enumerate(self.cards):
            x = i * (self.card_width + 18) if self.horizontal else 0
            h = self.height if self.horizontal else height
            bottom = 0 if self.horizontal else y - h
            canvas.setFillColor(PALE)
            canvas.setStrokeColor(GREY)
            canvas.roundRect(x, bottom, self.card_width, h, 6, stroke=1, fill=1)
            label.drawOn(canvas, x + 12, bottom + h - 12 - lh)
            body.drawOn(canvas, x + 12, bottom + h - 18 - lh - bh)
            if i + 1 < len(self.cards):
                canvas.setStrokeColor(ACCENT)
                canvas.setFillColor(ACCENT)
                p = canvas.beginPath()
                if self.horizontal:
                    ax, ay = x + self.card_width + 13, self.height / 2
                    canvas.line(x + self.card_width + 3, ay, ax, ay)
                    p.moveTo(ax, ay)
                    p.lineTo(ax - 4, ay + 3)
                    p.lineTo(ax - 4, ay - 3)
                else:
                    ax, ay = self.width / 2, bottom - 10
                    canvas.line(ax, bottom - 2, ax, ay)
                    p.moveTo(ax, ay)
                    p.lineTo(ax - 3, ay + 4)
                    p.lineTo(ax + 3, ay + 4)
                p.close()
                canvas.drawPath(p, stroke=0, fill=1)
            y = bottom - 13


def build_pdf(
    guide: LearningGuide, *, title: str, language: str, components: dict, inline
) -> bytes:
    # Embed an OFL font subset so CJK text survives offline viewers on every host.
    font = "StudySans"
    if font not in pdfmetrics.getRegisteredFontNames():
        font_path = Path(__file__).with_name("data") / "fonts" / "StudySans-Regular.ttf"
        source = json.loads(font_path.with_name("source.json").read_text("utf-8"))
        if hashlib.sha256(font_path.read_bytes()).hexdigest() != source["fontSha256"]:
            raise ValueError("study_font_integrity_failed")
        pdfmetrics.registerFont(TTFont(font, str(font_path)))

    def text(value, size=22):
        return inline.pdf(value, size=size)

    styles = {
        "body": ParagraphStyle(
            "Body",
            fontName=font,
            fontSize=11,
            leading=18,
            autoLeading="max",
            textColor=INK,
            spaceAfter=7,
            # The CJK-only splitter treats image fragments as empty characters. The regular
            # splitter supports inline images/nobr and can wrap long unspaced CJK text.
            wordWrap=None,
            splitLongWords=True,
            allowWidows=0,
            allowOrphans=0,
        ),
    }
    for name, overrides in {
        "title": dict(fontSize=27, leading=44, textColor=colors.black, spaceAfter=18),
        "unit": dict(
            fontSize=19,
            leading=34,
            textColor=colors.black,
            spaceBefore=18,
            spaceAfter=12,
            keepWithNext=True,
        ),
        "heading": dict(
            fontSize=13,
            leading=26,
            textColor=colors.black,
            spaceBefore=12,
            spaceAfter=6,
            keepWithNext=True,
        ),
        "intro": dict(fontSize=11.5, leading=20, spaceAfter=16, keepWithNext=True),
        "small": dict(fontSize=9.5, leading=15, spaceAfter=0),
        "flowTitle": dict(fontSize=11, leading=17, spaceAfter=0, textColor=ACCENT),
        "tableHead": dict(fontSize=10, leading=15, textColor=colors.white, spaceAfter=0),
        "bullet": dict(leftIndent=12, firstLineIndent=-10, spaceAfter=6),
    }.items():
        styles[name] = ParagraphStyle(name, parent=styles["body"], **overrides)

    class Handbook(BaseDocTemplate):
        def afterFlowable(self, flowable):
            anchor = getattr(flowable, "guide_anchor", None)
            if anchor is not None:
                self.canv.bookmarkPage(anchor)
                self.canv.addOutlineEntry(flowable.getPlainText(), anchor, 0, False)

    output = BytesIO()
    doc = Handbook(
        output,
        pagesize=(WIDTH, HEIGHT),
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=46,
        bottomMargin=48,
        title=inline.plain(title),
        author="Exile Architect",
        pageCompression=1,
    )

    def page(canvas, document):
        canvas.saveState()
        catalog = canvas._doc.Catalog
        if "Lang" not in catalog.__NoDefault__:
            catalog.__NoDefault__ = [*catalog.__NoDefault__, "Lang"]
        catalog.Lang = PDFString(language)
        if document.page > 1:
            header_style = ParagraphStyle(
                "RunningTitle",
                fontName=font,
                fontSize=8,
                leading=18,
                textColor=colors.HexColor("#51616B"),
            )
            header = Paragraph(text(title, 14), header_style)
            _, header_height = header.wrap(WIDTH - MARGIN * 2, 24)
            header.drawOn(canvas, MARGIN, HEIGHT - 16 - header_height)
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.HexColor("#51616B"))
        canvas.drawRightString(WIDTH - MARGIN, 26, str(document.page))
        canvas.restoreState()

    doc.addPageTemplates(
        PageTemplate(
            id="handbook",
            frames=[
                Frame(
                    MARGIN,
                    48,
                    WIDTH - MARGIN * 2,
                    HEIGHT - 94,
                    leftPadding=0,
                    rightPadding=0,
                    topPadding=0,
                    bottomPadding=0,
                )
            ],
            onPage=page,
        )
    )
    story = [
        Spacer(1, 30),
        Paragraph(text(title, 36), styles["title"]),
        Paragraph(text(guide.subtitle), styles["intro"]),
        Paragraph(text(guide.introduction), styles["intro"]),
        Spacer(1, 18),
        Paragraph(text(guide.navigationTitle), styles["heading"]),
    ]
    for i, unit in enumerate(guide.units):
        story.append(
            Paragraph(
                f'<link href="#unit-{i}" color="#286A72">{i + 1:02d}  {text(unit.title)}</link>',
                styles["body"],
            )
        )
    story.append(PageBreak())
    width = WIDTH - MARGIN * 2
    for i, unit in enumerate(guide.units):
        if i and unit.startNewPage:
            story.append(PageBreak())
        heading = Paragraph(f"{i + 1:02d}  {text(unit.title, 28)}", styles["unit"])
        heading.guide_anchor = f"unit-{i}"
        story.extend([heading, Paragraph(text(unit.introduction), styles["intro"])])
        for block in unit.blocks:
            if block.type in {"paragraph", "heading"}:
                story.append(
                    Paragraph(
                        text(block.text), styles["body" if block.type == "paragraph" else "heading"]
                    )
                )
            elif block.type == "bullets":
                story.extend(Paragraph("- " + text(item), styles["bullet"]) for item in block.items)
            elif block.type == "table":
                data = [[Paragraph(text(value), styles["tableHead"]) for value in block.columns]]
                data.extend(
                    [Paragraph(text(value), styles["small"]) for value in row] for row in block.rows
                )
                ratios = {2: [0.30, 0.70], 3: [0.26, 0.37, 0.37], 4: [0.22, 0.26, 0.26, 0.26]}[
                    len(block.columns)
                ]
                table = Table(
                    data, colWidths=[width * ratio for ratio in ratios], repeatRows=1, hAlign="LEFT"
                )
                table.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), INK),
                            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
                            ("GRID", (0, 0), (-1, -1), 0.5, GREY),
                            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                            ("LEFTPADDING", (0, 0), (-1, -1), 9),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                            ("TOPPADDING", (0, 0), (-1, -1), 7),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                        ]
                    )
                )
                table.spaceAfter = 12
                if len(data) <= 8:
                    story.append(KeepTogether([table]))
                else:
                    table._rowSplitRange = (3, -2)
                    story.append(table)
            elif block.type == "flow":
                diagram = MechanismDiagram(
                    [(text(s.label), text(s.explanation)) for s in block.steps], styles
                )
                diagram.spaceAfter = 12
                story.extend(
                    [
                        KeepTogether([Paragraph(text(block.title), styles["heading"]), diagram]),
                    ]
                )
            elif block.type == "note":
                note = Table(
                    [
                        [Paragraph(text(block.title), styles["flowTitle"])],
                        [Paragraph(text(block.text), styles["body"])],
                    ],
                    colWidths=[width],
                )
                note.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, -1), PALE),
                            ("LINEBEFORE", (0, 0), (0, -1), 3, ACCENT),
                            ("LEFTPADDING", (0, 0), (-1, -1), 13),
                            ("RIGHTPADDING", (0, 0), (-1, -1), 13),
                            ("TOPPADDING", (0, 0), (-1, -1), 8),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ]
                    )
                )
                note.spaceAfter = 12
                story.append(KeepTogether([note]))
    doc.build(story)
    return output.getvalue()
