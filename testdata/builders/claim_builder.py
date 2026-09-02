"""Renders CMS-1500-flavoured claim form PDFs from a scenario's ground truth dict.

Every PDF is rendered from the same ground_truth dict that is written to
tests/fixtures/expected/<ID>.expected.json — ground truth is never transcribed by hand.
"""

from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

PLAN_NAME = "HealthSecure Gold 2024"


def _line_items_total(line_items: list[dict[str, Any]]) -> float:
    return sum(item["amount"] for item in line_items)


def build_claim_pdf(
    scenario: dict[str, Any],
    member: dict[str, Any],
    provider: dict[str, Any],
    out_path: Path,
) -> Path:
    c = canvas.Canvas(str(out_path), pagesize=A4, invariant=1)
    width, height = A4
    x_margin = 2 * cm
    y = height - 2 * cm

    def line(label: str, value: str, dy: float = 0.7 * cm) -> None:
        nonlocal y
        c.setFont("Helvetica-Bold", 9)
        c.drawString(x_margin, y, label)
        c.setFont("Helvetica", 10)
        c.drawString(x_margin + 5 * cm, y, str(value))
        y -= dy

    c.setFont("Helvetica-Bold", 14)
    c.drawString(x_margin, y, "HEALTH INSURANCE CLAIM FORM (CMS-1500 style)")
    y -= 1 * cm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(x_margin, y, "Member / Policy Details")
    y -= 0.8 * cm
    line("Member ID:", member["member_id"])
    line("Member Name:", member["name"])
    line("Date Of Birth:", member["dob"])
    line("Member Age:", member["age"])
    line("Policy Number:", member["policy_no"])
    line("Plan Name:", PLAN_NAME)
    y -= 0.3 * cm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(x_margin, y, "Provider Details")
    y -= 0.8 * cm
    line("Provider ID:", provider["provider_id"])
    line("Provider Name:", provider["name"])
    line("Network Status:", provider["network_status"])
    y -= 0.3 * cm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(x_margin, y, "Service Details")
    y -= 0.8 * cm
    line("Service Start Date:", scenario["service_start_date"])
    line("Service End Date:", scenario["service_end_date"])
    same_day = scenario["service_start_date"] == scenario["service_end_date"]
    line("Place Of Service:", "Outpatient" if same_day else "Inpatient")
    line("Diagnosis Codes:", ", ".join(scenario["diagnosis_codes"]))
    y -= 0.5 * cm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(x_margin, y, "Line Items")
    y -= 0.7 * cm
    c.setFont("Helvetica-Bold", 9)
    headers = ["Code", "Description", "Units", "Charge"]
    col_x = [x_margin, x_margin + 2.5 * cm, x_margin + 10 * cm, x_margin + 12.5 * cm]
    for header, col in zip(headers, col_x, strict=True):
        c.drawString(col, y, header)
    y -= 0.5 * cm
    c.setFont("Helvetica", 9)
    for item in scenario["line_items"]:
        c.drawString(col_x[0], y, item["code"])
        c.drawString(col_x[1], y, item["description"])
        c.drawString(col_x[2], y, str(item["units"]))
        c.drawString(col_x[3], y, f"{item['amount']:,.2f}")
        y -= 0.5 * cm
    y -= 0.5 * cm

    c.setFont("Helvetica-Bold", 11)
    c.drawString(x_margin, y, "Claim Summary")
    y -= 0.8 * cm
    line("Total Charged:", f"{_line_items_total(scenario['line_items']):,.2f}")
    line("Currency:", scenario["currency"])
    line("Claim Reference:", scenario["id"])
    y -= 1 * cm
    c.setFont("Helvetica", 9)
    c.drawString(x_margin, y, "Signature: ____________________________")

    c.showPage()
    c.save()
    return out_path
