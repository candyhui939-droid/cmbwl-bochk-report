"""Locate candidate report pages using bilingual keywords and synonyms.

This module provides a lightweight, explainable first-pass locator for note pages
that likely contain target metrics.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class CandidateHit:
    """A matched candidate page.

    Attributes:
        page_ref: Human-readable page reference, e.g. "p.123".
        score: Weighted match score.
        matched_terms: Terms that appeared in the page text.
    """

    page_ref: str
    score: float
    matched_terms: Tuple[str, ...]


DEFAULT_METRIC_SYNONYMS: Dict[str, Sequence[str]] = {
    "net_interest_income": (
        "net interest income",
        "interest income net of interest expense",
        "净利息收入",
        "净利息收益",
    ),
    "credit_risk": (
        "credit risk",
        "risk management",
        "credit quality",
        "信贷风险",
        "信用风险",
    ),
    "deposits_from_customers": (
        "deposits from customers",
        "customer deposits",
        "due to customers",
        "客户存款",
        "吸收存款",
    ),
}


def locate_candidates(
    pages: Iterable[Tuple[str, str]],
    metric_name: str,
    synonyms_map: Dict[str, Sequence[str]] | None = None,
    min_score: float = 1.0,
) -> List[CandidateHit]:
    """Find candidate pages by matching metric bilingual keywords and synonyms.

    Args:
        pages: Iterable of (page_ref, page_text).
        metric_name: Standardized metric name.
        synonyms_map: Optional synonym dictionary keyed by metric_name.
        min_score: Minimal score threshold for returning candidates.

    Returns:
        Ranked candidate pages in descending score order.
    """

    synonyms = (synonyms_map or DEFAULT_METRIC_SYNONYMS).get(metric_name, ())
    if not synonyms:
        return []

    hits: List[CandidateHit] = []
    lowered = [term.lower() for term in synonyms]

    for page_ref, page_text in pages:
        text = page_text.lower()
        matched = tuple(term for term in lowered if term in text)
        if not matched:
            continue

        score = float(len(matched))
        if score >= min_score:
            hits.append(CandidateHit(page_ref=page_ref, score=score, matched_terms=matched))

    hits.sort(key=lambda x: x.score, reverse=True)
    return hits
