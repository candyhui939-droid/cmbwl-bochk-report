#!/usr/bin/env python3
"""Generate QC outputs for fact note extraction CSV.

Inputs:
  - fact_note_extract_sample.csv (default, configurable)
Outputs:
  1) data/processed/fact_note_extract_qc.csv
  2) data/processed/fact_note_extract_review_todo.csv
  3) Summary printed to stdout and optionally written as JSON

Rules include:
  - metric_value missing
  - unit conflict within bank/year/metric_name
  - missing page number
  - missing source snippet
  - direct report usability ratio threshold gate (default: 85%)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

import pandas as pd

DEFAULT_INPUT = "fact_note_extract_sample.csv"
DEFAULT_QC_OUT = "data/processed/fact_note_extract_qc.csv"
DEFAULT_TODO_OUT = "data/processed/fact_note_extract_review_todo.csv"


def _norm_text(v) -> str:
    if pd.isna(v):
        return ""
    return str(v).strip()


def _is_missing(v) -> bool:
    return _norm_text(v) == ""


def _calc_status_flags(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    # Rule 1: metric_value missing
    out["metric_value_missing"] = out.get("metric_value", "").apply(_is_missing)

    # Rule 2: missing page number
    page_col = "page_number" if "page_number" in out.columns else "page"
    out["page_missing"] = out.get(page_col, "").apply(_is_missing)

    # Rule 3: missing source snippet
    snippet_col = "source_snippet" if "source_snippet" in out.columns else "original_snippet"
    out["snippet_missing"] = out.get(snippet_col, "").apply(_is_missing)

    # Rule 4: unit conflict within (bank, year, metric_name)
    required_for_unit = [c for c in ["bank", "year", "metric_name", "unit"] if c in out.columns]
    if set(["bank", "year", "metric_name", "unit"]).issubset(out.columns):
        unit_set_size = (
            out.assign(unit_norm=out["unit"].apply(_norm_text))
            .groupby(["bank", "year", "metric_name"], dropna=False)["unit_norm"]
            .transform(lambda x: len({u for u in x if u != ""}))
        )
        out["unit_conflict"] = unit_set_size > 1
    else:
        out["unit_conflict"] = False

    # model/rule hit flags (best effort by column names)
    if "rule_hit" in out.columns:
        out["rule_hit_bool"] = out["rule_hit"].astype(str).str.lower().isin(["1", "true", "yes", "y", "pass"])
    else:
        out["rule_hit_bool"] = False

    if "model_hit" in out.columns:
        out["model_hit_bool"] = out["model_hit"].astype(str).str.lower().isin(["1", "true", "yes", "y", "pass"])
    else:
        out["model_hit_bool"] = False

    # field-level statuses
    out["qc_metric_value_status"] = out["metric_value_missing"].map({True: "fail", False: "pass"})
    out["qc_unit_status"] = out["unit_conflict"].map({True: "warn", False: "pass"})
    out["qc_page_status"] = out["page_missing"].map({True: "warn", False: "pass"})
    out["qc_snippet_status"] = out["snippet_missing"].map({True: "warn", False: "pass"})

    # overall status
    fail_any = out[["metric_value_missing"]].any(axis=1)
    warn_any = out[["unit_conflict", "page_missing", "snippet_missing"]].any(axis=1)
    out["qc_overall_status"] = "pass"
    out.loc[warn_any, "qc_overall_status"] = "warn"
    out.loc[fail_any, "qc_overall_status"] = "fail"

    # direct-report usable: pass only if no fail/warn blockers
    out["report_ready"] = ~fail_any & ~warn_any

    return out


def _build_review_todo(qc_df: pd.DataFrame) -> pd.DataFrame:
    issue_mask = (
        qc_df["metric_value_missing"]
        | qc_df["unit_conflict"]
        | qc_df["page_missing"]
        | qc_df["snippet_missing"]
    )
    todo = qc_df.loc[issue_mask].copy()

    def collect_issues(row) -> str:
        issues: List[str] = []
        if row["metric_value_missing"]:
            issues.append("metric_value_missing")
        if row["unit_conflict"]:
            issues.append("unit_conflict")
        if row["page_missing"]:
            issues.append("page_missing")
        if row["snippet_missing"]:
            issues.append("snippet_missing")
        return ";".join(issues)

    todo["review_issue_tags"] = todo.apply(collect_issues, axis=1)

    cols_first = [c for c in ["bank", "year", "metric_name", "metric_value", "unit", "review_issue_tags"] if c in todo.columns]
    other_cols = [c for c in todo.columns if c not in cols_first]
    return todo[cols_first + other_cols]


def _build_summary(qc_df: pd.DataFrame, threshold: float) -> Dict[str, object]:
    group_cols = [c for c in ["bank", "year"] if c in qc_df.columns]
    if not group_cols:
        qc_df = qc_df.copy()
        qc_df["bank"] = "ALL"
        qc_df["year"] = "ALL"
        group_cols = ["bank", "year"]

    grp = qc_df.groupby(group_cols, dropna=False)

    summary_df = grp.apply(
        lambda g: pd.Series(
            {
                "records": len(g),
                "hit_rate": float((g["qc_overall_status"] == "pass").mean()),
                "missing_rate": float(g["metric_value_missing"].mean()),
                "rule_hit_rate": float(g["rule_hit_bool"].mean()),
                "model_hit_rate": float(g["model_hit_bool"].mean()),
                "report_ready_rate": float(g["report_ready"].mean()),
            }
        )
    ).reset_index()

    blocked = summary_df[summary_df["report_ready_rate"] < threshold]

    return {
        "threshold": threshold,
        "groups": summary_df.to_dict(orient="records"),
        "blocked_groups": blocked[group_cols + ["report_ready_rate"]].to_dict(orient="records"),
        "can_enter_report_stage": blocked.empty,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--qc-output", default=DEFAULT_QC_OUT)
    parser.add_argument("--todo-output", default=DEFAULT_TODO_OUT)
    parser.add_argument("--summary-json", default="")
    parser.add_argument("--report-ready-threshold", type=float, default=0.85)
    args = parser.parse_args()

    input_path = Path(args.input)
    qc_output = Path(args.qc_output)
    todo_output = Path(args.todo_output)

    df = pd.read_csv(input_path)
    qc_df = _calc_status_flags(df)

    qc_output.parent.mkdir(parents=True, exist_ok=True)
    todo_output.parent.mkdir(parents=True, exist_ok=True)

    qc_df.to_csv(qc_output, index=False)

    todo_df = _build_review_todo(qc_df)
    todo_df.to_csv(todo_output, index=False)

    summary = _build_summary(qc_df, threshold=args.report_ready_threshold)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.summary_json:
        out_json = Path(args.summary_json)
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    if not summary["can_enter_report_stage"]:
        raise SystemExit(
            "Blocked: report_ready_rate below threshold for one or more bank/year groups. "
            f"threshold={args.report_ready_threshold}"
        )


if __name__ == "__main__":
    main()
