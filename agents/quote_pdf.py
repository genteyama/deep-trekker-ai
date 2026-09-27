from pathlib import Path
from typing import Optional
import os
import struct

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from agents.formal_quote_document import format_document_amount, format_document_date
from models import FormalQuoteDocument

JAPANESE_FONT = "HeiseiKakuGo-W5"
EMBEDDED_FONT = "SpaceOneEmbeddedJP"
EMBEDDED_FONT_BOLD = "SpaceOneEmbeddedJP-Bold"
FONT_PATH_ENV = "SPACEONE_PDF_FONT_PATH"
FONT_BOLD_PATH_ENV = "SPACEONE_PDF_FONT_BOLD_PATH"
MIN_FONT_SIZE = 8
SPACEONE_LOGO = Path(__file__).resolve().parents[1] / "assets" / "branding" / "spaceone_logo.png"
SPACEONE_SEAL = Path(__file__).resolve().parents[1] / "assets" / "branding" / "spaceone_seal.png"


def resolve_pdf_fonts() -> tuple[str, str, str]:
    configured = (os.getenv(FONT_PATH_ENV) or "").strip()
    bold_configured = (os.getenv(FONT_BOLD_PATH_ENV) or "").strip()
    if configured:
        try:
            return _register_embedded_font(Path(configured), Path(bold_configured) if bold_configured else None)
        except (OSError, ValueError, KeyError, RuntimeError):
            pass
    return _register_cid_font()


def register_japanese_font() -> str:
    regular, _bold, _source = resolve_pdf_fonts()
    return regular


def render_formal_quote_pdf(
    document: FormalQuoteDocument,
    path: Path,
    *,
    logo_path: Optional[Path] = None,
    seal_path: Optional[Path] = None,
) -> Path:
    regular, bold, _source = resolve_pdf_fonts()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles(regular, bold)
    story = []
    story.append(_header_table(document, styles, logo_path if logo_path is not None else SPACEONE_LOGO))
    story.append(Spacer(1, 8))
    story.append(_parties_table(document, styles, seal_path if seal_path is not None else SPACEONE_SEAL))
    story.append(Spacer(1, 10))
    story.append(_meta_table(document, styles))
    story.append(Spacer(1, 10))
    story.append(Paragraph(f"御見積金額　¥{format_document_amount(document.total)}（税込）", styles["amount"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("明細", styles["section"]))
    story.append(Spacer(1, 4))
    story.append(_lines_table(document, styles))
    story.append(Spacer(1, 8))
    story.append(_totals_table(document, styles))
    if document.remarks:
        story.append(Spacer(1, 12))
        story.append(Paragraph("備考", styles["section"]))
        story.append(Spacer(1, 4))
        remark_blocks = []
        for remark in document.remarks:
            remark_blocks.append(Paragraph(escape_pdf_text(remark), styles["remark"]))
            remark_blocks.append(Spacer(1, 3))
        story.append(KeepTogether(remark_blocks))
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=document.quote_number or "SpaceOne Quote",
        author=document.issuer.company_name if document.issuer else "SpaceOne",
    )
    doc.build(story)
    return path


def extract_pdf_text(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def pdf_page_info(path: Path) -> dict:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        box = page.mediabox
        pages.append({"width": float(box.width), "height": float(box.height)})
    return {"page_count": len(reader.pages), "pages": pages}


def escape_pdf_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _styles(regular: str, bold: str) -> dict:
    return {
        "title": ParagraphStyle("title", fontName=bold, fontSize=18, leading=22, alignment=TA_CENTER, textColor=colors.HexColor("#123A56")),
        "label": ParagraphStyle("label", fontName=regular, fontSize=9, leading=12, textColor=colors.HexColor("#4A5B67")),
        "body": ParagraphStyle("body", fontName=regular, fontSize=10, leading=14, textColor=colors.HexColor("#1A2330")),
        "small": ParagraphStyle("small", fontName=regular, fontSize=9, leading=12, textColor=colors.HexColor("#1A2330")),
        "item": ParagraphStyle("item", fontName=regular, fontSize=9, leading=12, alignment=TA_LEFT, textColor=colors.HexColor("#1A2330")),
        "item_name": ParagraphStyle("item_name", fontName=bold, fontSize=9, leading=12, alignment=TA_LEFT, textColor=colors.HexColor("#123A56")),
        "qty": ParagraphStyle("qty", fontName=regular, fontSize=9, leading=12, alignment=TA_CENTER, textColor=colors.HexColor("#1A2330")),
        "money": ParagraphStyle("money", fontName=regular, fontSize=9, leading=12, alignment=TA_RIGHT, textColor=colors.HexColor("#1A2330")),
        "amount": ParagraphStyle("amount", fontName=bold, fontSize=13, leading=18, alignment=TA_LEFT, textColor=colors.HexColor("#123A56")),
        "section": ParagraphStyle("section", fontName=bold, fontSize=11, leading=14, textColor=colors.HexColor("#123A56")),
        "total_label": ParagraphStyle("total_label", fontName=bold, fontSize=11, leading=14, textColor=colors.HexColor("#123A56")),
        "total_money": ParagraphStyle("total_money", fontName=bold, fontSize=11, leading=14, alignment=TA_RIGHT, textColor=colors.HexColor("#123A56")),
        "remark": ParagraphStyle("remark", fontName=regular, fontSize=9, leading=13, alignment=TA_LEFT, textColor=colors.HexColor("#1A2330")),
        "right": ParagraphStyle("right", fontName=regular, fontSize=9, leading=12, alignment=TA_RIGHT, textColor=colors.HexColor("#1A2330")),
        "font_regular": regular,
        "font_bold": bold,
    }


def _header_table(document: FormalQuoteDocument, styles: dict, logo_path: Path) -> Table:
    logo = _optional_image(logo_path, max_height=28)
    header = Table(
        [[logo or "", Paragraph("御見積書", styles["title"]), ""]],
        colWidths=[90, 295, 90],
    )
    header.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (1, 0), (1, 0), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#123A56")),
            ]
        )
    )
    return header


def _parties_table(document: FormalQuoteDocument, styles: dict, seal_path: Path) -> Table:
    customer = f"{document.customer_name} 御中" if document.customer_name else ""
    issuer_lines = []
    if document.issuer:
        for value in (
            document.issuer.company_name,
            document.issuer.address,
            document.issuer.office_address,
            document.issuer.telephone,
        ):
            if value:
                issuer_lines.append(escape_pdf_text(value))
    left = [
        Paragraph("宛先", styles["label"]),
        Paragraph(escape_pdf_text(customer), styles["body"]),
        Spacer(1, 8),
        Paragraph("件名", styles["label"]),
        Paragraph(escape_pdf_text(document.subject or ""), styles["body"]),
    ]
    right_flow = [Paragraph(line, styles["right"]) for line in issuer_lines]
    seal = _optional_image(seal_path, max_height=42)
    if seal is not None:
        right_flow.append(Spacer(1, 4))
        right_flow.append(seal)
    table = Table([[left, right_flow]], colWidths=[300, 175])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return table


def _meta_table(document: FormalQuoteDocument, styles: dict) -> Table:
    rows = [
        [Paragraph("見積番号", styles["label"]), Paragraph(escape_pdf_text(document.quote_number or ""), styles["body"])],
        [Paragraph("発行日", styles["label"]), Paragraph(format_document_date(document.issue_date), styles["body"])],
        [Paragraph("有効期限", styles["label"]), Paragraph(format_document_date(document.valid_until), styles["body"])],
    ]
    table = Table(rows, colWidths=[70, 405])
    table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _lines_table(document: FormalQuoteDocument, styles: dict) -> Table:
    data = [[
        Paragraph("品名・内容", styles["label"]),
        Paragraph("数量", styles["label"]),
        Paragraph("単価", styles["label"]),
        Paragraph("金額", styles["label"]),
    ]]
    for line in document.customer_lines:
        data.append(
            [
                _item_name_cell(line, styles),
                Paragraph(str(line.quantity), styles["qty"]),
                Paragraph(format_document_amount(line.unit_price), styles["money"]),
                Paragraph(format_document_amount(line.amount), styles["money"]),
            ]
        )
    table = Table(data, colWidths=[275, 45, 75, 80], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), styles["font_regular"]),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F6F8")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#123A56")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D4DC")),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    return table


def _item_name_cell(line, styles: dict) -> Paragraph:
    name = escape_pdf_text(line.item_name or "")
    detail = escape_pdf_text(line.customer_description or "")
    bold = styles["font_bold"]
    if name and detail:
        return Paragraph(f'<font name="{bold}"><b>{name}</b></font><br/>{detail}', styles["item"])
    if name:
        return Paragraph(f'<font name="{bold}"><b>{name}</b></font>', styles["item"])
    return Paragraph(detail, styles["item"])


def _register_cid_font() -> tuple[str, str, str]:
    names = set(pdfmetrics.getRegisteredFontNames())
    if JAPANESE_FONT not in names:
        pdfmetrics.registerFont(UnicodeCIDFont(JAPANESE_FONT))
    pdfmetrics.registerFontFamily(
        JAPANESE_FONT,
        normal=JAPANESE_FONT,
        bold=JAPANESE_FONT,
        italic=JAPANESE_FONT,
        boldItalic=JAPANESE_FONT,
    )
    return JAPANESE_FONT, JAPANESE_FONT, "cid"


def _register_embedded_font(path: Path, bold_path: Optional[Path]) -> tuple[str, str, str]:
    if not path.is_file():
        raise ValueError("configured PDF font path does not exist")
    names = set(pdfmetrics.getRegisteredFontNames())
    if EMBEDDED_FONT not in names:
        pdfmetrics.registerFont(TTFont(EMBEDDED_FONT, str(path), subfontIndex=0))
    bold_name = EMBEDDED_FONT
    if bold_path is not None and bold_path.is_file():
        if EMBEDDED_FONT_BOLD not in names:
            pdfmetrics.registerFont(TTFont(EMBEDDED_FONT_BOLD, str(bold_path), subfontIndex=0))
        bold_name = EMBEDDED_FONT_BOLD
    pdfmetrics.registerFontFamily(
        EMBEDDED_FONT,
        normal=EMBEDDED_FONT,
        bold=bold_name,
        italic=EMBEDDED_FONT,
        boldItalic=bold_name,
    )
    return EMBEDDED_FONT, bold_name, "embedded"


def _totals_table(document: FormalQuoteDocument, styles: dict) -> Table:
    rows = [
        [Paragraph("小計", styles["label"]), Paragraph(format_document_amount(document.subtotal), styles["money"])],
        [Paragraph("消費税", styles["label"]), Paragraph(format_document_amount(document.tax_amount), styles["money"])],
        [Paragraph("合計", styles["total_label"]), Paragraph(format_document_amount(document.total), styles["total_money"])],
    ]
    table = Table(rows, colWidths=[395, 80])
    table.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEABOVE", (0, 0), (-1, 0), 1.25, colors.HexColor("#123A56")),
                ("LINEABOVE", (0, 2), (-1, 2), 0.7, colors.HexColor("#123A56")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def _optional_image(path: Optional[Path], *, max_height: float):
    if path is None:
        return None
    path = Path(path)
    if not path.exists():
        return None
    width, height = _png_size(path)
    if not width or not height:
        return Image(str(path), height=max_height)
    scaled_width = max_height * (width / height)
    return Image(str(path), width=scaled_width, height=max_height)


def _png_size(path: Path) -> tuple[int, int]:
    try:
        with path.open("rb") as handle:
            signature = handle.read(8)
            if signature != b"\x89PNG\r\n\x1a\n":
                return (0, 0)
            handle.read(8)
            return struct.unpack(">II", handle.read(8))
    except OSError:
        return (0, 0)
