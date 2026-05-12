"""LLM fallback parser for fields missed by rule parser.

The model output must map field names to standardized `metric_name` values.
"""

from __future__ import annotations

import json
from typing import Dict, Iterable, List


ALLOWED_METRIC_NAMES = {
    "net_interest_income",
    "credit_risk",
    "deposits_from_customers",
}


def build_prompt(unmatched_fields: Iterable[str], context_text: str) -> str:
    fields = ", ".join(unmatched_fields)
    return (
        "You are extracting banking report metrics. "
        "Return strict JSON array only. Each item must include: "
        "metric_name, value, unit, source_text_snippet, page_ref. "
        "metric_name must be one of: "
        f"{sorted(ALLOWED_METRIC_NAMES)}. "
        f"Focus only on remaining fields: {fields}. "
        f"Context: {context_text[:6000]}"
    )


def parse_llm_json(raw_output: str) -> List[Dict]:
    """Validate and normalize LLM JSON payload."""

    data = json.loads(raw_output)
    if not isinstance(data, list):
        raise ValueError("LLM output must be a JSON list")

    cleaned: List[Dict] = []
    for item in data:
        metric_name = item.get("metric_name")
        if metric_name not in ALLOWED_METRIC_NAMES:
            raise ValueError(f"Unknown metric_name: {metric_name}")
        cleaned.append(
            {
                "metric_name": metric_name,
                "value": item.get("value"),
                "unit": item.get("unit"),
                "source_text_snippet": item.get("source_text_snippet", ""),
                "page_ref": item.get("page_ref", ""),
                "parser": "llm",
            }
        )
    return cleaned
