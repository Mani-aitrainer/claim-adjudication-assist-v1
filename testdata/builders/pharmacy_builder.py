"""Renders pharmacy invoice PDFs. Deliberately a different layout from claim_builder.py's
CMS-1500 form, so the parser (built in P2) is not accidentally coupled to one layout.
"""

from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

GST_RATE = 0.0  # kept at zero for these fixtures — not exercised by any scenario


def build_pharmacy_pdf(
    scenario: dict[str, Any],
    member: dict[str, Any],
    pharmacy: dict[str, Any],
    out_path: Path,
) -> Path:
    c = canvas.Canvas(str(out_path), pagesize=A4, invariant=1)
    width, height = A4
    x_margin = 2 * cm
    y = height - 2 * cm

    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(width / 2, y, pharmacy["name"])
    y -= 0.6 * cm
    c.setFont("Helvetica", 9)
    c.drawCentredString(width / 2, y, f"Pharmacy ID: {pharmacy['pharmacy_id']}")
    y -= 1 * cm

    c.setFont("Helvetica-Bold", 12)
    c.drawString(x_margin, y, f"Invoice — Claim Reference: {scenario['id']}")
    y -= 0.8 * cm

    def line(label: str, value: str, dy: float = 0.7 * cm) -> None:
        nonlocal y
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x_margin, y, label)
        c.setFont("Helvetica", 10)
        c.drawString(x_margin + 5 * cm, y, str(value))
        y -= dy

    line("Member ID:", member["member_id"])
    line("Member Name:", member["name"])
    line("Policy Number:", member["policy_no"])
    line("Invoice Date:", scenario["service_date"])
    y -= 0.3 * cm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(x_margin, y, "Drug Lines")
    y -= 0.7 * cm
    c.setFont("Helvetica-Bold", 9)
    headers = ["NDC Code", "Description", "Qty", "Unit Price", "Amount"]
    col_x = [
        x_margin,
        x_margin + 2.8 * cm,
        x_margin + 9.5 * cm,
        x_margin + 11 * cm,
        x_margin + 13.5 * cm,
    ]
    for header, col in zip(headers, col_x, strict=True):
        c.drawString(col, y, header)
    y -= 0.5 * cm
    c.setFont("Helvetica", 9)
    for item in scenario["line_items"]:
        c.drawString(col_x[0], y, item["code"])
        c.drawString(col_x[1], y, item["description"])
        c.drawString(col_x[2], y, str(item["units"]))
        c.drawString(col_x[3], y, f"{item['unit_price']:,.2f}")
        c.drawString(col_x[4], y, f"{item['amount']:,.2f}")
        y -= 0.5 * cm
    y -= 0.5 * cm

    total = sum(item["amount"] for item in scenario["line_items"])
    c.setFont("Helvetica-Bold", 11)
    c.drawString(x_margin, y, "Invoice Summary")
    y -= 0.8 * cm
    line("GST:", f"{total * GST_RATE:,.2f}")
    line("Invoice Total:", f"{total:,.2f} {scenario['currency']}")

    c.showPage()
    c.save()
    return out_path
