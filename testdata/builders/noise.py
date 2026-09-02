"""OCR corruption functions.

Each function is a pure, deterministic transform (no shared random state) so that
regenerating fixtures with the same inputs always produces byte-identical output.
Each is aimed at one of the four few-shot examples the FieldRepairAgent is trained on.
"""

from collections.abc import Callable
from typing import Any

_DIGIT_TO_LETTER = {"0": "O", "1": "I", "5": "S", "8": "B"}


def char_confusion(text: str) -> str:
    """Digit/letter confusion, e.g. member IDs and procedure codes: 0<->O, 1<->I, 5<->S, 8<->B."""
    return "".join(_DIGIT_TO_LETTER.get(ch, ch) for ch in text)


def date_reformat(iso_date: str) -> str:
    """ISO date -> a non-ISO variant, e.g. 2024-03-05 -> 05-Mar-2024."""
    year, month, day = iso_date.split("-")
    months = [
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]
    month_name = months[int(month) - 1]
    return f"{day}-{month_name}-{year}"


def currency_noise(amount: float) -> str:
    """Adds currency symbol, thousands commas and a trailing '/-' the way a form would print it."""
    whole = int(amount)
    formatted = f"{whole:,}"
    return f"Rs. {formatted}/-"


def whitespace_wrap(text: str) -> str:
    """Injects a line-wrap hyphen and a doubled space, as a scanned form's line wrap would."""
    if len(text) < 4:
        return text + "  "
    midpoint = len(text) // 2
    return f"{text[:midpoint]}-\n{text[midpoint:]}  "


def dropout(text: str, ratio: float = 0.5) -> str:
    """Replaces a deterministic fraction of characters with '#' to simulate a smudge."""
    if not text:
        return text
    step = max(1, round(1 / ratio))
    chars = list(text)
    for i in range(0, len(chars), step):
        chars[i] = "#"
    return "".join(chars)


def table_shift(rows: list[dict]) -> list[dict]:
    """Shifts the first row's 'units' and 'amount' values into the wrong columns."""
    if not rows:
        return rows
    shifted = [dict(row) for row in rows]
    shifted[0]["units"], shifted[0]["amount"] = shifted[0]["amount"], shifted[0]["units"]
    return shifted


NOISE_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "char_confusion": char_confusion,
    "date_reformat": date_reformat,
    "currency_noise": currency_noise,
    "whitespace_wrap": whitespace_wrap,
    "dropout": dropout,
    "table_shift": table_shift,
}
