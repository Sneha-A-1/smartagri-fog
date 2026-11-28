"""PDF report with reportlab: summary, caveats, tables (wide ones on landscape pages), figures and parameters."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from smartagri_core.reports.model import CI, Report, fmt_ci, fmt_num

_FONTS_READY = False


def _fonts() -> tuple[str, str]:
    """DejaVu Sans (bundled with matplotlib) covers ±, µ, ▼ and ▲, which the PDF base fonts do not."""
    global _FONTS_READY
    import matplotlib
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if not _FONTS_READY:
        base = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        pdfmetrics.registerFont(TTFont("DejaVu", str(base / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(base / "DejaVuSans-Bold.ttf")))
        pdfmetrics.registerFontFamily(
            "DejaVu", normal="DejaVu", bold="DejaVu-Bold", italic="DejaVu", boldItalic="DejaVu-Bold"
        )
        _FONTS_READY = True
    return "DejaVu", "DejaVu-Bold"


def _cell(v: Any, decimals: int | None) -> str:
    if isinstance(v, CI):
        return fmt_ci(v, decimals) + {"better": " ▼", "worse": " ▲"}.get(v.mark, "")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return fmt_num(v, decimals)
    return "" if v is None else str(v)


def pdf_bytes(report: Report, figure_pngs: dict[str, bytes]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (
        BaseDocTemplate,
        Frame,
        Image,
        KeepTogether,
        NextPageTemplate,
        PageBreak,
        PageTemplate,
        Paragraph,
        Spacer,
        Table,
        TableStyle,
    )

    regular, bold = _fonts()
    body = ParagraphStyle("body", fontName=regular, fontSize=9.5, leading=13.5, spaceAfter=6)
    small = ParagraphStyle("small", parent=body, fontSize=7.5, leading=10, textColor=colors.HexColor("#4b5563"))
    cell = ParagraphStyle("cell", fontName=regular, fontSize=7, leading=8.6)
    cell_b = ParagraphStyle("cellb", parent=cell, fontName=bold)
    h1 = ParagraphStyle("h1", fontName=bold, fontSize=17, leading=21, spaceAfter=4)
    h2 = ParagraphStyle("h2", fontName=bold, fontSize=11.5, leading=15, spaceBefore=10, spaceAfter=5)

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title=report.title,
        author="SmartAgri-Fog",
        creator="SmartAgri-Fog",
    )

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont(regular, 7)
        canvas.setFillColor(colors.HexColor("#6b7280"))
        canvas.drawString(d.leftMargin, 1 * cm, f"SmartAgri-Fog · {report.title} · {report.data_origin} data")
        canvas.drawRightString(d.pagesize[0] - d.rightMargin, 1 * cm, f"Page {d.page}")
        canvas.restoreState()

    pw, ph = A4
    lw, lh = landscape(A4)
    doc.addPageTemplates(
        [
            PageTemplate("portrait", [Frame(2 * cm, 1.8 * cm, pw - 4 * cm, ph - 3.6 * cm)], onPage=footer, pagesize=A4),
            PageTemplate(
                "landscape",
                [Frame(1.5 * cm, 1.8 * cm, lw - 3 * cm, lh - 3.6 * cm)],
                onPage=footer,
                pagesize=landscape(A4),
            ),
        ]
    )

    story: list[Any] = [Paragraph(report.title, h1)]
    if report.subtitle:
        story.append(Paragraph(report.subtitle, small))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Summary", h2))
    story += [Paragraph(_x(p), body) for p in report.summary if p]
    if report.caveats:
        story.append(Paragraph("Caveats", h2))
        story += [Paragraph("• " + _x(c), body) for c in report.caveats]

    orientation = "portrait"
    for t in report.tables:
        wide = len(t.columns) > 6
        want = "landscape" if wide else "portrait"
        if want != orientation:
            story += [NextPageTemplate(want), PageBreak()]
            orientation = want
        width = (lw - 3 * cm) if wide else (pw - 4 * cm)
        data = [[Paragraph(_x(c.header), cell_b) for c in t.columns]]
        for i, row in enumerate(t.rows):
            style = cell_b if t.highlight_row == i else cell
            data.append([Paragraph(_x(_cell(v, c.decimals)), style) for v, c in zip(row, t.columns, strict=True)])
        first = 0.24 if len(t.columns) > 2 else 0.5
        widths = [width * first] + [width * (1 - first) / max(len(t.columns) - 1, 1)] * (len(t.columns) - 1)
        if len(t.columns) == 3 and t.columns[1].kind == "text":  # e.g. hypothesis, statement, verdict
            widths = [width * 0.15, width * 0.65, width * 0.2]
        tbl = Table(data, colWidths=widths, repeatRows=1)
        tbl.setStyle(
            TableStyle(
                [
                    ("LINEABOVE", (0, 0), (-1, 0), 0.8, colors.black),
                    ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.black),
                    ("LINEBELOW", (0, -1), (-1, -1), 0.8, colors.black),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        block = [Paragraph(_x(t.caption), h2), tbl]
        if t.notes:
            block.append(Paragraph(_x(t.notes), small))
        story += block

    if orientation != "portrait":
        story += [NextPageTemplate("portrait"), PageBreak()]
    if report.figures:
        story.append(Paragraph("Figures", h2))
    for f in report.figures:
        png = figure_pngs.get(f.key)
        if not png:
            continue
        img = Image(io.BytesIO(png))
        scale = min((pw - 4 * cm) / img.imageWidth, 9 * cm / img.imageHeight, 1.0) if img.imageWidth else 1
        img.drawWidth, img.drawHeight = img.imageWidth * scale, img.imageHeight * scale
        story.append(KeepTogether([img, Paragraph(_x(f"Figure ({f.key}). {f.caption}"), small), Spacer(1, 8)]))

    story.append(Paragraph("Parameters and provenance", h2))
    story.append(
        Paragraph(
            _x(json.dumps({"params": report.params, "provenance": report.provenance}, indent=1, default=str))
            .replace("\n", "<br/>")
            .replace(" ", "&nbsp;"),
            small,
        )
    )
    doc.build(story)
    return buf.getvalue()


def _x(text: str) -> str:
    """Escape for reportlab's mini-markup."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
