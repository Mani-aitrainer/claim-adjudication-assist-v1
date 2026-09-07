"""Textract blocks -> {raw_text, key_values, tables}.

Resolves text either directly from a block's `Text` attribute (how the synthetic fixture
builder writes it) or, if absent, by walking CHILD relationships down to WORD blocks and
joining their text (how real AWS Textract responses are shaped) — so this parser works
unchanged once P15 swaps in captured real-Textract fixtures.
"""

from typing import Any, TypedDict

from app.core.exceptions import OCRServiceError


class ParsedField(TypedDict):
    value: str
    confidence: float


class ParsedDocument(TypedDict):
    raw_text: str
    key_values: dict[str, ParsedField]
    tables: list[list[dict[str, str]]]


def _block_map(blocks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {block["Id"]: block for block in blocks}


def _resolve_text(block: dict[str, Any], blocks_by_id: dict[str, dict[str, Any]]) -> str:
    if "Text" in block:
        return str(block["Text"])
    words = []
    for rel in block.get("Relationships", []):
        if rel["Type"] != "CHILD":
            continue
        for child_id in rel["Ids"]:
            child = blocks_by_id.get(child_id)
            if child and child["BlockType"] == "WORD":
                words.append(str(child.get("Text", "")))
    return " ".join(words)


def _value_block_for_key(
    key_block: dict[str, Any], blocks_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any] | None:
    for rel in key_block.get("Relationships", []):
        if rel["Type"] == "VALUE" and rel["Ids"]:
            return blocks_by_id.get(rel["Ids"][0])
    return None


def parse(doc: dict[str, Any]) -> ParsedDocument:
    if "error" in doc:
        raise OCRServiceError(doc["error"].get("message", "OCR service error"))

    blocks: list[dict[str, Any]] = doc.get("Blocks", [])
    blocks_by_id = _block_map(blocks)

    key_values: dict[str, ParsedField] = {}
    for block in blocks:
        if block["BlockType"] != "KEY_VALUE_SET" or "KEY" not in block.get("EntityTypes", []):
            continue
        value_block = _value_block_for_key(block, blocks_by_id)
        if value_block is None:
            continue
        label = _resolve_text(block, blocks_by_id)
        key_values[label] = {
            "value": _resolve_text(value_block, blocks_by_id),
            "confidence": float(value_block.get("Confidence", 0.0)),
        }

    tables: list[list[dict[str, str]]] = []
    for block in blocks:
        if block["BlockType"] != "TABLE":
            continue
        cells: list[dict[str, Any]] = []
        for rel in block.get("Relationships", []):
            if rel["Type"] != "CHILD":
                continue
            for cell_id in rel["Ids"]:
                cell = blocks_by_id.get(cell_id)
                if cell and cell["BlockType"] == "CELL":
                    cells.append(cell)

        rows_by_index: dict[int, dict[int, str]] = {}
        header_by_column: dict[int, str] = {}
        for cell in sorted(cells, key=lambda c: (c["RowIndex"], c["ColumnIndex"])):
            text = _resolve_text(cell, blocks_by_id)
            if cell["RowIndex"] == 0:
                header_by_column[cell["ColumnIndex"]] = text
            else:
                rows_by_index.setdefault(cell["RowIndex"], {})[cell["ColumnIndex"]] = text

        table_rows = [
            {header_by_column.get(col, str(col)): text for col, text in row.items()}
            for _, row in sorted(rows_by_index.items())
        ]
        tables.append(table_rows)

    raw_text = "\n".join(
        str(block["Text"]) for block in blocks if block["BlockType"] == "LINE"
    )

    return {"raw_text": raw_text, "key_values": key_values, "tables": tables}
