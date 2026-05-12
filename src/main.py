from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MetricRule:
    standard_name: str
    aliases: set[str]
    expected_unit: str
    extraction_priority: str


class MetricMapper:
    def __init__(self, mapping_file: Path) -> None:
        payload = self._load_mapping(mapping_file)
        self.needs_review_on_miss = bool(payload.get("fallback", {}).get("needs_review_on_miss", True))

        self.rules: dict[str, MetricRule] = {}
        self.alias_to_standard: dict[str, str] = {}

        for row in payload.get("metrics", []):
            standard_name = row["standard_name"]
            aliases = {standard_name, *row.get("aliases", [])}
            rule = MetricRule(
                standard_name=standard_name,
                aliases=aliases,
                expected_unit=row.get("expected_unit", ""),
                extraction_priority=row.get("extraction_priority", "table_first"),
            )
            self.rules[standard_name] = rule
            for alias in aliases:
                self.alias_to_standard[self._norm_key(alias)] = standard_name

    @staticmethod
    def _load_mapping(path: Path) -> dict[str, Any]:
        """Minimal YAML parser for the constrained mapping schema."""
        data: dict[str, Any] = {"fallback": {}, "metrics": []}
        current_metric: dict[str, Any] | None = None
        in_aliases = False

        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line == "fallback:":
                current_metric = None
                in_aliases = False
                continue
            if line.startswith("needs_review_on_miss:"):
                data["fallback"]["needs_review_on_miss"] = line.split(":", 1)[1].strip().lower() == "true"
                continue
            if line == "metrics:":
                current_metric = None
                in_aliases = False
                continue

            if line.startswith("- standard_name:"):
                current_metric = {
                    "standard_name": line.split(":", 1)[1].strip().strip('"'),
                    "aliases": [],
                }
                data["metrics"].append(current_metric)
                in_aliases = False
                continue

            if current_metric is None:
                continue

            if line == "aliases:":
                in_aliases = True
                continue

            if in_aliases and line.startswith("-"):
                current_metric["aliases"].append(line[1:].strip().strip('"'))
                continue

            in_aliases = False
            if line.startswith("expected_unit:"):
                current_metric["expected_unit"] = line.split(":", 1)[1].strip().strip('"')
            elif line.startswith("extraction_priority:"):
                current_metric["extraction_priority"] = line.split(":", 1)[1].strip().strip('"')

        return data

    @staticmethod
    def _norm_key(raw: str) -> str:
        return " ".join(raw.strip().lower().replace("_", " ").split())

    def normalize(self, extracted_item: dict[str, Any]) -> dict[str, Any]:
        raw_name = str(extracted_item.get("field_name", ""))
        matched_standard = self.alias_to_standard.get(self._norm_key(raw_name))

        out = dict(extracted_item)
        out["original_field_name"] = raw_name
        out["needs_review"] = False

        if matched_standard:
            rule = self.rules[matched_standard]
            out["field_name"] = matched_standard
            out["expected_unit"] = rule.expected_unit
            out["extraction_priority"] = rule.extraction_priority
        else:
            out["field_name"] = raw_name
            out["expected_unit"] = ""
            out["extraction_priority"] = ""
            out["needs_review"] = self.needs_review_on_miss

        return out


def write_csv(rows: list[dict[str, Any]], output_path: Path) -> None:
    if not rows:
        output_path.write_text("", encoding="utf-8")
        return

    all_fields = list(dict.fromkeys(k for r in rows for k in r.keys()))
    with output_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=all_fields)
        writer.writeheader()
        writer.writerows(rows)


def run_pipeline(extracted_rows: list[dict[str, Any]], mapping_path: Path, output_csv: Path) -> None:
    mapper = MetricMapper(mapping_path)
    normalized_rows = [mapper.normalize(row) for row in extracted_rows]
    write_csv(normalized_rows, output_csv)


if __name__ == "__main__":
    demo_rows = [
        {"field_name": "NII", "value": 280.1, "unit": "亿港元"},
        {"field_name": "CASA ratio", "value": 42.6, "unit": "%"},
        {"field_name": "未知字段", "value": "N/A", "unit": ""},
    ]
    run_pipeline(demo_rows, Path("config/metric_mapping.yaml"), Path("output.csv"))
