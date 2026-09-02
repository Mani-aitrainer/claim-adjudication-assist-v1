"""Renders the synthetic policy corpus (wording, member handbook, procedure annexure) to PDF."""

from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

STYLES = getSampleStyleSheet()


def _doc(path: Path) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        invariant=1,  # deterministic CreationDate/ID so regeneration is byte-identical
    )


def build_policy_wording(
    product: dict[str, Any], clauses: list[dict[str, Any]], out_dir: Path
) -> Path:
    out_path = out_dir / "policy_wording.pdf"
    period = product["product_period"]
    story = [
        Paragraph(f"{product['name']}", STYLES["Title"]),
        Paragraph(f"Product Code: {product['code']}", STYLES["Normal"]),
        Paragraph(
            f"Sum Insured: {product['currency']} {product['sum_insured']:,} | "
            f"Policy Period: {period['start']} to {period['end']}",
            STYLES["Normal"],
        ),
        Spacer(1, 0.5 * cm),
    ]
    for clause in clauses:
        story.append(Paragraph(f"{clause['clause_id']} — {clause['title']}", STYLES["Heading3"]))
        story.append(Paragraph(clause["text"].strip(), STYLES["BodyText"]))
        story.append(Spacer(1, 0.3 * cm))
    _doc(out_path).build(story)
    return out_path


def build_member_handbook(
    product: dict[str, Any], paragraphs: list[dict[str, Any]], out_dir: Path
) -> Path:
    out_path = out_dir / "member_handbook.pdf"
    story = [
        Paragraph(f"{product['name']} — Member Handbook", STYLES["Title"]),
        Paragraph(
            "A plain-language guide to your cover. Wording differs from the policy document "
            "on purpose, so retrieval has to work on meaning, not string matching.",
            STYLES["Italic"],
        ),
        Spacer(1, 0.5 * cm),
    ]
    for para in paragraphs:
        story.append(Paragraph(f"Related to clause {para['clause_ref']}", STYLES["Heading4"]))
        story.append(Paragraph(para["text"].strip(), STYLES["BodyText"]))
        story.append(Spacer(1, 0.3 * cm))
    _doc(out_path).build(story)
    return out_path


def build_procedure_code_annexure(rows: list[dict[str, Any]], out_dir: Path) -> Path:
    out_path = out_dir / "procedure_code_annexure.pdf"
    story = [
        Paragraph("Procedure Code Annexure", STYLES["Title"]),
        Spacer(1, 0.5 * cm),
    ]
    table_data = [["Code", "Benefit Category", "Clause"]]
    for row in rows:
        table_data.append([row["code"], row["benefit_category"], row["clause_id"]])
    table = Table(table_data, colWidths=[3 * cm, 8 * cm, 3 * cm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.append(table)
    _doc(out_path).build(story)
    return out_path


def build_all(policy_wordings: dict[str, Any], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    product = policy_wordings["product"]
    return [
        build_policy_wording(product, policy_wordings["clauses"], out_dir),
        build_member_handbook(product, policy_wordings["member_handbook_paragraphs"], out_dir),
        build_procedure_code_annexure(policy_wordings["procedure_code_annexure"], out_dir),
    ]
