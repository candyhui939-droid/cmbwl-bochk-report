"""Validation for extracted metric records."""

from __future__ import annotations

from typing import Dict, Iterable, List, Set, Tuple


REQUIRED_FIELDS = ("metric_name", "value", "unit", "source_text_snippet", "page_ref")


def validate_records(records: Iterable[Dict], min_value: float = -1e15, max_value: float = 1e15) -> List[str]:
    errors: List[str] = []
    seen: Set[Tuple[str, str]] = set()

    for idx, rec in enumerate(records):
        for field in REQUIRED_FIELDS:
            if rec.get(field) in (None, ""):
                errors.append(f"row {idx}: missing required field `{field}`")

        value = rec.get("value")
        if isinstance(value, (int, float)):
            if value < min_value or value > max_value:
                errors.append(f"row {idx}: abnormal value {value}")

        key = (str(rec.get("metric_name")), str(rec.get("page_ref")))
        if key in seen:
            errors.append(f"row {idx}: duplicate metric/page pair {key}")
        seen.add(key)

    return errors
