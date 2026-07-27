"""
PDF Briefing Generator — Printable intelligence reports for field operatives.

Generates professional PDF dossiers with:
  - Classification headers & watermarks
  - Multi-dimensional scoring visualization
  - Evidence chain & source attribution
  - Network cluster map
  - Temporal trend analysis
  - Actionable recommendations
  - Risk & opportunity matrices

Dependencies: reportlab (pre-installed in sandbox)
"""

import io
import logging
from datetime import datetime, timezone
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm, cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as canvas_lib

logger = logging.getLogger(__name__)

# ---- Font Registration (Hebrew + Latin support) ----
_LIBERATION_SANS = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
_LIBERATION_SANS_BOLD = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
_LIBERATION_SANS_ITALIC = "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf"
_LIBERATION_SANS_BI = "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf"

_FONTS_REGISTERED = False

def _register_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    candidates = [
        (
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Italic.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-BoldItalic.ttf",
        ),
        (
            "/Library/Fonts/Arial Unicode.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
            "/Library/Fonts/Arial Unicode.ttf",
        ),
        (
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        ),
        (
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ),
    ]
    for regular, bold, italic, bi in candidates:
        try:
            pdfmetrics.registerFont(TTFont("LiberationSans", regular))
            pdfmetrics.registerFont(TTFont("LiberationSans-Bold", bold))
            pdfmetrics.registerFont(TTFont("LiberationSans-Italic", italic))
            pdfmetrics.registerFont(TTFont("LiberationSans-BoldItalic", bi))
            pdfmetrics.registerFont(TTFont("LiberationSans-Oblique", italic))
            _FONTS_REGISTERED = True
            logger.info("PDF fonts registered from %s", regular)
            return
        except Exception:
            continue
    logger.warning("Could not register Hebrew-capable fonts. Hebrew text may render as blanks.")
    _FONTS_REGISTERED = True  # Don't retry


# ---- Styles ----

CLASSIFICATION_BANNER_COLORS = {
    "TOP SECRET": colors.Color(0.8, 0, 0),       # dark red
    "SECRET": colors.Color(0.9, 0.3, 0),           # orange-red
    "CONFIDENTIAL": colors.Color(0, 0.3, 0.7),     # blue
    "RESTRICTED": colors.Color(0.2, 0.5, 0.2),     # green
}

TIER_COLORS = {
    "critical": colors.Color(0.7, 0, 0),
    "high": colors.Color(0.9, 0.4, 0),
    "moderate": colors.Color(0.8, 0.7, 0),
    "low": colors.Color(0.2, 0.5, 0.8),
    "negligible": colors.Color(0.5, 0.5, 0.5),
}

BLACKOPPS_GREEN = colors.Color(0.05, 0.3, 0.15)
BLACKOPPS_GOLD = colors.Color(0.85, 0.65, 0.1)
PAGE_BG = colors.Color(0.98, 0.98, 0.96)  # warm paper


def _build_styles():
    """Build custom paragraph styles for the briefing."""
    _register_fonts()
    styles = getSampleStyleSheet()

    FONT = 'LiberationSans'
    FONT_BOLD = 'LiberationSans-Bold'
    FONT_ITALIC = 'LiberationSans-Italic'

    styles.add(ParagraphStyle(
        "Classification",
        parent=styles["Normal"],
        fontName=FONT_BOLD,
        fontSize=10,
        textColor=colors.white,
        alignment=TA_CENTER,
        spaceAfter=2 * mm,
    ))
    styles.add(ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName=FONT_BOLD,
        fontSize=20,
        textColor=BLACKOPPS_GREEN,
        alignment=TA_CENTER,
        spaceAfter=4 * mm,
    ))
    styles.add(ParagraphStyle(
        "SubjectName",
        parent=styles["Heading1"],
        fontName=FONT_BOLD,
        fontSize=24,
        textColor=colors.Color(0.1, 0.1, 0.1),
        alignment=TA_CENTER,
        spaceAfter=2 * mm,
    ))
    styles.add(ParagraphStyle(
        "SectionHeader",
        parent=styles["Heading2"],
        fontName=FONT_BOLD,
        fontSize=14,
        textColor=BLACKOPPS_GREEN,
        spaceBefore=8 * mm,
        spaceAfter=4 * mm,
        borderPadding=(0, 0, 2, 0),
    ))
    styles.add(ParagraphStyle(
        "ScoreLabel",
        parent=styles["Normal"],
        fontName=FONT,
        fontSize=9,
        textColor=colors.Color(0.3, 0.3, 0.3),
        alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        "ScoreValue",
        parent=styles["Normal"],
        fontName=FONT_BOLD,
        fontSize=18,
        alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        "Evidence",
        parent=styles["Normal"],
        fontName=FONT,
        fontSize=9,
        textColor=colors.Color(0.2, 0.2, 0.2),
        leftIndent=5 * mm,
        bulletIndent=2 * mm,
    ))
    styles.add(ParagraphStyle(
        "Recommendation",
        parent=styles["Normal"],
        fontName=FONT_ITALIC,
        fontSize=11,
        textColor=BLACKOPPS_GREEN,
        leftIndent=3 * mm,
        borderPadding=(3, 3, 3, 3),
    ))
    styles.add(ParagraphStyle(
        "RiskItem",
        parent=styles["Normal"],
        fontName=FONT,
        fontSize=10,
        textColor=colors.Color(0.7, 0, 0),
        leftIndent=5 * mm,
    ))
    styles.add(ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontName=FONT,
        fontSize=7,
        textColor=colors.Color(0.5, 0.5, 0.5),
        alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        "Watermark",
        parent=styles["Normal"],
        fontName=FONT_BOLD,
        fontSize=60,
        textColor=colors.Color(0.9, 0.9, 0.9),
        alignment=TA_CENTER,
    ))

    return styles


class BriefingPDF:
    """
    Generates a professional intelligence briefing PDF.
    """

    def __init__(self, classification: str = "CONFIDENTIAL"):
        self.classification = classification.upper()
        self.styles = _build_styles()
        self.banner_color = CLASSIFICATION_BANNER_COLORS.get(
            self.classification, colors.Color(0, 0.3, 0.7)
        )

    def generate(self, name: str, briefing_data: dict, pipeline=None,
                  output_path: Optional[str] = None) -> bytes:
        """
        Generate the PDF and return as bytes.

        Args:
            name: Entity name
            briefing_data: Dict from pipeline.generate_briefing()
            pipeline: Optional pipeline reference for network data
            output_path: If provided, also save to file

        Returns:
            PDF as bytes
        """
        buffer = io.BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=20 * mm,
            bottomMargin=20 * mm,
            title=f"INTEL BRIEFING — {name}",
            author="BlackOpps OSINT",
            subject=f"Intelligence Briefing: {name}",
        )

        elements = []

        # ---- Header ----
        elements.append(self._classification_banner())
        elements.append(Spacer(1, 6 * mm))
        elements.append(Paragraph(f"BLACKOPPS INTELLIGENCE BRIEFING", self.styles["DocTitle"]))
        elements.append(Paragraph(name, self.styles["SubjectName"]))

        # Generation info
        gen_time = briefing_data.get("generated_at") or datetime.now(timezone.utc).isoformat()
        elements.append(Paragraph(
            f"Generated: {gen_time[:19]}Z | Classification: {self.classification} | "
            f"Handle via secure channels only",
            self.styles["Footer"],
        ))
        elements.append(HRFlowable(width="100%", thickness=1, color=BLACKOPPS_GREEN))
        elements.append(Spacer(1, 4 * mm))

        # ---- Influence Assessment ----
        influence = briefing_data.get("influence_assessment", {})
        elements.append(Paragraph("1. INFLUENCE ASSESSMENT", self.styles["SectionHeader"]))
        elements.append(self._score_table(influence))

        # Tier interpretation
        tier = influence.get("tier", "negligible").upper()
        tier_color = TIER_COLORS.get(influence.get("tier", "negligible"), colors.grey)
        elements.append(Spacer(1, 3 * mm))
        elements.append(Paragraph(
            f"<font color='{self._hex(tier_color)}'><b>TIER: {tier}</b></font> — "
            f"Composite {influence.get('composite_score', 0):.1f}/100 | "
            f"Confidence: {briefing_data.get('confidence', briefing_data.get('influence_assessment', {}).get('confidence', 0)):.0f}%",
            self.styles["Normal"],
        ))
        elements.append(Spacer(1, 2 * mm))

        # ---- Dimension Scores ----
        dimensions = influence.get("dimensions", {})
        elements.append(Paragraph("2. DIMENSIONAL BREAKDOWN", self.styles["SectionHeader"]))
        elements.append(self._dimension_table(dimensions))
        elements.append(Spacer(1, 3 * mm))

        # ---- Evidence ----
        evidence = briefing_data.get("evidence_summary", {})
        if evidence:
            elements.append(Paragraph("3. EVIDENCE CHAIN", self.styles["SectionHeader"]))
            for key, value in evidence.items():
                if value is not None and value != "" and value != []:
                    label = key.replace("_", " ").title()
                    elements.append(Paragraph(
                        f"• <b>{label}:</b> {value}",
                        self.styles["Evidence"],
                    ))
            elements.append(Spacer(1, 2 * mm))

        # ---- Sources ----
        sources = briefing_data.get("sources", [])
        if sources:
            elements.append(Paragraph("4. SOURCE ATTRIBUTION", self.styles["SectionHeader"]))
            for src in sources:
                elements.append(Paragraph(f"• {src}", self.styles["Evidence"]))
            elements.append(Spacer(1, 3 * mm))

        # ---- Recommendations ----
        recommendation = briefing_data.get("recommendation", "")
        strategy = briefing_data.get("engagement_strategy", "")
        if recommendation:
            elements.append(Paragraph("5. RECOMMENDED ACTION", self.styles["SectionHeader"]))
            elements.append(Paragraph(recommendation, self.styles["Recommendation"]))
            elements.append(Spacer(1, 2 * mm))
            if strategy:
                elements.append(Paragraph(
                    f"<b>Engagement Strategy:</b> {strategy}",
                    self.styles["Evidence"],
                ))
            elements.append(Spacer(1, 3 * mm))

        # ---- Risks & Opportunities ----
        risks = briefing_data.get("risks", [])
        opportunities = briefing_data.get("opportunities", [])
        if risks or opportunities:
            elements.append(Paragraph("6. RISK / OPPORTUNITY MATRIX", self.styles["SectionHeader"]))

            if risks:
                elements.append(Paragraph("<b>RISKS:</b>", self.styles["Normal"]))
                for r in risks:
                    elements.append(Paragraph(f"⚠ {r}", self.styles["RiskItem"]))
                elements.append(Spacer(1, 2 * mm))

            if opportunities:
                elements.append(Paragraph("<b>OPPORTUNITIES:</b>", self.styles["Normal"]))
                for o in opportunities:
                    elements.append(Paragraph(f"✓ {o}", self.styles["Evidence"]))
                elements.append(Spacer(1, 3 * mm))

        # ---- Network ----
        network = briefing_data.get("network", {})
        if network:
            elements.append(Paragraph("7. NETWORK ANALYSIS", self.styles["SectionHeader"]))
            elements.append(Paragraph(
                f"Cluster size: {network.get('cluster_size', 0)} | "
                f"Hubs in cluster: {network.get('hubs_in_cluster', 0)}",
                self.styles["Normal"],
            ))
            connections = network.get("connections", [])[:10]
            if connections:
                for conn in connections:
                    cname = conn.get("name", conn.get("entity", "?"))
                    rel = conn.get("relation_type", conn.get("via", "?"))
                    strength = conn.get("strength", 0)
                    elements.append(Paragraph(
                        f"• <b>{cname}</b> — {rel} (strength: {strength:.1f})",
                        self.styles["Evidence"],
                    ))
            elements.append(Spacer(1, 3 * mm))

        # ---- Temporal ----
        temporal = briefing_data.get("temporal", {})
        if temporal.get("snapshots", 0) > 0:
            elements.append(Paragraph("8. TEMPORAL TRACKING", self.styles["SectionHeader"]))
            elements.append(Paragraph(
                f"Snapshots recorded: {temporal['snapshots']}",
                self.styles["Normal"],
            ))
            latest = temporal.get("latest_change")
            if latest:
                elements.append(Paragraph(
                    f"Latest: {latest.get('timestamp', '?')[:19]}Z — "
                    f"Composite: {latest.get('composite', 0):.1f} ({latest.get('tier', '?')})",
                    self.styles["Evidence"],
                ))

        # ---- Footer ----
        elements.append(Spacer(1, 10 * mm))
        elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.Color(0.7, 0.7, 0.7)))
        elements.append(Paragraph(
            f"BLACKOPPS OSINT — {self.classification} — "
            f"Generated {gen_time[:19]}Z — "
            f"Do not distribute without authorization",
            self.styles["Footer"],
        ))

        # Build PDF
        doc.build(elements, onFirstPage=self._page_decorator, onLaterPages=self._page_decorator)

        pdf_bytes = buffer.getvalue()

        if output_path:
            with open(output_path, "wb") as f:
                f.write(pdf_bytes)

        return pdf_bytes

    def _classification_banner(self):
        """Generate classification banner."""
        banner_data = [[
            Paragraph(
                f"❖ {self.classification} ❖",
                self.styles["Classification"],
            )
        ]]
        banner = Table(banner_data, colWidths=[doc_width := A4[0] - 36 * mm])
        banner.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), self.banner_color),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        return banner

    def _score_table(self, influence: dict):
        """Create the big composite score display."""
        composite = influence.get("composite_score", 0)
        tier = influence.get("tier", "negligible").upper()
        tier_color = TIER_COLORS.get(influence.get("tier", "negligible"), colors.grey)

        data = [[
            Paragraph(
                f"<font color='{self._hex(tier_color)}' size='36'><b>{composite:.0f}</b></font>"
                f"<font size='16'>/100</font>",
                ParagraphStyle("BigScore", alignment=TA_CENTER, fontName="LiberationSans"),
            ),
            Paragraph(
                f"<font color='{self._hex(tier_color)}'><b>{tier}</b></font>",
                ParagraphStyle("TierLabel", alignment=TA_CENTER, fontName="LiberationSans-Bold", fontSize=14),
            ),
        ]]
        table = Table(data, colWidths=[70 * mm, 70 * mm])
        table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOX", (0, 0), (-1, -1), 1.5, tier_color),
            ("BACKGROUND", (0, 0), (-1, -1), colors.Color(0.97, 0.97, 0.95)),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        return table

    def _dimension_table(self, dimensions: dict):
        """Create the four-dimension score breakdown."""
        dims = [
            ("Political Capital", dimensions.get("political_capital", 0)),
            ("Community Influence", dimensions.get("community_influence", 0)),
            ("Voter Reliability", dimensions.get("voter_reliability", 0)),
            ("Financial Leverage", dimensions.get("financial_leverage", 0)),
        ]

        data = []
        row = []
        for label, score in dims:
            bar_width = int(score / 100 * 40)
            bar = "█" * (bar_width // 2) + "░" * (20 - bar_width // 2)
            color = self._score_color(score)
            cell = Paragraph(
                f"<b>{label}</b><br/>"
                f"<font color='{color}' size='16'><b>{score:.0f}</b></font>"
                f"<font size='7'><br/>{bar}</font>",
                ParagraphStyle(
                    "DimCell",
                    alignment=TA_CENTER,
                    fontName="LiberationSans",
                    fontSize=9,
                    leading=12,
                ),
            )
            row.append(cell)

        data.append(row)
        col_w = (A4[0] - 36 * mm) / 4
        table = Table(data, colWidths=[col_w] * 4)
        table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.Color(0.8, 0.8, 0.8)),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.Color(0.9, 0.9, 0.9)),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, -1), colors.white),
        ]))
        return table

    def _page_decorator(self, canvas: canvas_lib.Canvas, doc):
        """Add footer and watermarks to each page."""
        canvas.saveState()

        # Footer line
        canvas.setStrokeColor(colors.Color(0.7, 0.7, 0.7))
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)

        # Footer text
        canvas.setFont("LiberationSans", 7)
        canvas.setFillColor(colors.Color(0.4, 0.4, 0.4))
        canvas.drawString(18 * mm, 10 * mm, f"BLACKOPPS OSINT — {self.classification}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")

        # Diagonal watermark
        canvas.setFont("LiberationSans-Bold", 50)
        canvas.setFillColor(colors.Color(0.95, 0.95, 0.92))
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(45)
        canvas.drawCentredString(0, 0, self.classification)

        canvas.restoreState()

    @staticmethod
    def _score_color(score: float) -> str:
        if score >= 70:
            return "#B30000"
        elif score >= 50:
            return "#E67300"
        elif score >= 30:
            return "#3366CC"
        return "#666666"

    @staticmethod
    def _hex(color: colors.Color) -> str:
        return f"#{int(color.red * 255):02x}{int(color.green * 255):02x}{int(color.blue * 255):02x}"


def generate_briefing_pdf(name: str, briefing_data: dict,
                           pipeline=None, output_path: str = None,
                           classification: str = "CONFIDENTIAL") -> bytes:
    """
    Convenience function to generate a briefing PDF.

    Args:
        name: Entity name
        briefing_data: From pipeline.generate_briefing()
        pipeline: Optional pipeline reference
        output_path: Optional file path to save
        classification: Security classification level

    Returns:
        PDF as bytes
    """
    generator = BriefingPDF(classification=classification)
    return generator.generate(name, briefing_data, pipeline, output_path)
