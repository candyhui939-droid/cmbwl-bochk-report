#!/usr/bin/env python3
"""Extract note metrics from annual report PDFs for CMBWL and BOCHK.

Pipeline steps:
1) Scan PDFs under data/raw/annual_reports/{BANK}/{YEAR}
2) Parse bank_name/year from filename
3) Extract per-page full text and table text
4) Filter candidate pages by note-category keywords
5) Extract normalized fields from candidate snippets
6) Write CSV with dedupe/conflict flags
7) Write run log with per-PDF stats
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

BANKS = ("CMBWL", "BOCHK")
ROOT = Path(__file__).resolve().parents[1]
RAW_BASE = ROOT / "data" / "raw" / "annual_reports"
OUTPUT_CSV = ROOT / "data" / "processed" / "fact_note_extract_sample.csv"
LOG_DIR = ROOT / "logs"

NOTE_KEYWORDS = {
    "NII": [r"\bnet\s+interest\s+income\b", r"\bnii\b", r"净利息收入"],
    "ECL": [r"\bexpected\s+credit\s+loss", r"\becl\b", r"减值", r"预期信用损失"],
    "DEPOSIT_BREAKDOWN": [
        r"deposit\s+by\s+", r"deposit\s+structure", r"存款结构", r"客户存款",
    ],
}

# broad metric regex to capture name/value/unit in note-related lines.
METRIC_PATTERN = re.compile(
    r"(?P<name>[A-Za-z\u4e00-\u9fff][A-Za-z0-9_\-\s\u4e00-\u9fff\(\)]{2,}?)"
    r"\s*[:：]?\s*"
    r"(?P<value>[\(\-]?\d[\d,\.]*\)?)"
    r"\s*(?P<unit>%|bps|bp|million|billion|thousand|HK\$|RMB|USD|元|百万元|千元)?",
    flags=re.IGNORECASE,
)

FILE_META_PATTERN = re.compile(r"^(?P<bank>CMBWL|BOCHK)_(?P<year>\d{4})_annual_report\.pdf$", re.IGNORECASE)


@dataclass
class PageContent:
    page_no: int
    text: str
    table_text: str


@dataclass
class ExtractionRecord:
    bank_name: str
    year: int
    note_category: str
    metric_name: str
    metric_value: str
    unit: str
    note_ref: str
    page_ref: str
    source_text_snippet: str
    dedupe_status: str = "unique"
    conflict_flag: str = ""


def build_logger(ts: str) -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"extract_notes_{ts}.log"
    logger = logging.getLogger("extract_notes_pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(log_file, encoding="utf-8")
    sh = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    fh.setFormatter(fmt)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


def discover_pdfs() -> List[Path]:
    pdfs: List[Path] = []
    for bank in BANKS:
        bank_dir = RAW_BASE / bank
        if not bank_dir.exists():
            continue
        pdfs.extend(sorted(bank_dir.glob("*/*.pdf")))
    return pdfs


def parse_file_meta(pdf_path: Path) -> Optional[Tuple[str, int]]:
    m = FILE_META_PATTERN.match(pdf_path.name)
    if m:
        return m.group("bank").upper(), int(m.group("year"))

    # fallback: infer from path segments
    bank = pdf_path.parent.parent.name.upper() if len(pdf_path.parents) >= 2 else ""
    year_s = pdf_path.parent.name
    if bank in BANKS and year_s.isdigit() and len(year_s) == 4:
        return bank, int(year_s)
    return None


def extract_pdf_pages(pdf_path: Path) -> List[PageContent]:
    pages: List[PageContent] = []
    try:
        import pdfplumber  # type: ignore
    except Exception:
        raise RuntimeError("Missing dependency: pdfplumber")

    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            tables = page.extract_tables() or []
            rows: List[str] = []
            for t in tables:
                for row in t:
                    row_text = " | ".join([c.strip() if c else "" for c in row])
                    if row_text.strip(" |"):
                        rows.append(row_text)
            pages.append(PageContent(page_no=i, text=text, table_text="\n".join(rows)))
    return pages


def find_candidate_pages(pages: Sequence[PageContent]) -> List[Tuple[str, PageContent]]:
    hits: List[Tuple[str, PageContent]] = []
    for p in pages:
        combined = f"{p.text}\n{p.table_text}".lower()
        for category, patterns in NOTE_KEYWORDS.items():
            if any(re.search(pat, combined, flags=re.IGNORECASE) for pat in patterns):
                hits.append((category, p))
    return hits


def to_snippet(text: str, max_len: int = 240) -> str:
    t = re.sub(r"\s+", " ", text).strip()
    return t[:max_len]


def extract_metrics(bank: str, year: int, category: str, page: PageContent) -> List[ExtractionRecord]:
    records: List[ExtractionRecord] = []
    source = f"{page.text}\n{page.table_text}"
    lines = [ln.strip() for ln in source.splitlines() if ln.strip()]
    for ln in lines:
        for m in METRIC_PATTERN.finditer(ln):
            metric = re.sub(r"\s+", " ", m.group("name")).strip(" -:_")
            if len(metric) < 3:
                continue
            records.append(
                ExtractionRecord(
                    bank_name=bank,
                    year=year,
                    note_category=category,
                    metric_name=metric,
                    metric_value=m.group("value"),
                    unit=(m.group("unit") or "").strip(),
                    note_ref=f"{category}_note",
                    page_ref=f"p.{page.page_no}",
                    source_text_snippet=to_snippet(ln),
                )
            )
    return records


def dedupe_and_mark(records: List[ExtractionRecord]) -> List[ExtractionRecord]:
    grouped: Dict[Tuple[str, int, str], List[ExtractionRecord]] = {}
    for r in records:
        grouped.setdefault((r.bank_name, r.year, r.metric_name.lower()), []).append(r)

    output: List[ExtractionRecord] = []
    for key, rows in grouped.items():
        if len(rows) == 1:
            output.append(rows[0])
            continue

        values = {f"{r.metric_value}|{r.unit}" for r in rows}
        if len(values) == 1:
            first = rows[0]
            first.dedupe_status = "deduped"
            output.append(first)
        else:
            for r in rows:
                r.conflict_flag = "value_conflict"
                r.dedupe_status = "kept_conflict"
                output.append(r)
    return output


def write_csv(records: Sequence[ExtractionRecord], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "bank_name", "year", "note_category", "metric_name", "metric_value", "unit",
        "note_ref", "page_ref", "source_text_snippet", "dedupe_status", "conflict_flag",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(r.__dict__)


def run() -> int:
    parser = argparse.ArgumentParser(description="Extract note metrics from annual report PDFs")
    parser.parse_args()

    ts = dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    logger = build_logger(ts)
    logger.info("Pipeline started.")

    pdfs = discover_pdfs()
    if not pdfs:
        logger.warning("No PDFs found under %s", RAW_BASE)

    all_records: List[ExtractionRecord] = []
    total_failures = 0

    for pdf in pdfs:
        meta = parse_file_meta(pdf)
        if not meta:
            logger.warning("Skip file with unparsable metadata: %s", pdf)
            continue
        bank, year = meta
        hits = 0
        extracted = 0
        failed = 0

        try:
            pages = extract_pdf_pages(pdf)
            candidates = find_candidate_pages(pages)
            hits = len({p.page_no for _, p in candidates})
            for cat, page in candidates:
                try:
                    recs = extract_metrics(bank, year, cat, page)
                    all_records.extend(recs)
                    extracted += len(recs)
                except Exception:
                    failed += 1
        except Exception as e:
            failed += 1
            logger.exception("Failed processing PDF %s: %s", pdf, e)

        total_failures += failed
        logger.info("PDF=%s | hit_pages=%s | extracted=%s | failed=%s", pdf.name, hits, extracted, failed)

    final_records = dedupe_and_mark(all_records)
    write_csv(final_records, OUTPUT_CSV)
    logger.info("Wrote CSV: %s (rows=%d)", OUTPUT_CSV, len(final_records))
    logger.info("Pipeline finished. total_failures=%d", total_failures)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
