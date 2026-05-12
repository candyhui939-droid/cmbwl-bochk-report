"""Rule-based extraction using regex and table header heuristics.

Implementation target: cover at least ~60% fields with deterministic rules before
falling back to model extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional


AMOUNT_RE = re.compile(r"(?P<value>[\d,]+(?:\.\d+)?)\s*(?P<unit>HK\$|USD|RMB|人民幣|港元|百萬|億元)?", re.IGNORECASE)
PCT_RE = re.compile(r"(?P<value>-?\d+(?:\.\d+)?)\s*%")
BP_RE = re.compile(r"(?P<value>-?\d+(?:\.\d+)?)\s*bp", re.IGNORECASE)


@dataclass
class RuleExtraction:
    metric_name: str
    value: float
    unit: str
    source_text_snippet: str
    page_ref: str
    parser: str = "rule"


def parse_from_text(metric_name: str, text: str, page_ref: str) -> Optional[RuleExtraction]:
    """Parse a single metric from plain text via regex priority: % -> bp -> amount."""

    for regex, unit in ((PCT_RE, "%"), (BP_RE, "bp"), (AMOUNT_RE, "amount")):
        m = regex.search(text)
        if not m:
            continue
        raw_val = m.group("value").replace(",", "")
        value = float(raw_val)
        out_unit = unit if unit != "amount" else (m.groupdict().get("unit") or "")
        snippet = text[max(0, m.start() - 30) : m.end() + 30]
        return RuleExtraction(
            metric_name=metric_name,
            value=value,
            unit=out_unit,
            source_text_snippet=snippet.strip(),
            page_ref=page_ref,
        )
    return None


def parse_by_table_headers(
    rows: Iterable[Dict[str, str]],
    metric_name: str,
    header_aliases: Iterable[str],
    page_ref: str,
) -> List[RuleExtraction]:
    """Extract numeric cells when table headers match configured aliases."""

    aliases = [a.lower() for a in header_aliases]
    results: List[RuleExtraction] = []

    for row in rows:
        for header, cell in row.items():
            if header.lower() not in aliases:
                continue
            ext = parse_from_text(metric_name=metric_name, text=cell, page_ref=page_ref)
            if ext:
                results.append(ext)
    return results
