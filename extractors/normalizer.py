"""Normalize extracted values and units.

- monetary amounts -> 亿港元
- ratios -> %
"""

from __future__ import annotations

from typing import Dict


def normalize_record(record: Dict) -> Dict:
    out = dict(record)
    val = out.get("value")
    unit = str(out.get("unit", "")).strip().lower()

    if val is None:
        return out

    # Monetary normalization to 亿港元.
    if unit in {"hk$", "港元", "hkd"}:
        out["value"] = float(val) / 100_000_000
        out["unit"] = "亿港元"
    elif unit in {"百萬", "百万", "million"}:
        out["value"] = float(val) / 100
        out["unit"] = "亿港元"
    elif unit in {"億元", "亿元", "亿港元"}:
        out["value"] = float(val)
        out["unit"] = "亿港元"
    elif unit in {"%", "pct", "percent", "percentage"}:
        out["value"] = float(val)
        out["unit"] = "%"
    return out
