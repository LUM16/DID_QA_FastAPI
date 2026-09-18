"""Result export helpers (CSV / JSON) and cell flattening."""

from __future__ import annotations

import csv
import io
import json
from typing import Any


def flatten_cell(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def normalize_rows(
    rows: list[dict[str, Any]], columns: list[str] | None = None
) -> list[dict[str, Any]]:
    cols = columns or (list(rows[0].keys()) if rows else [])
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append({c: flatten_cell(row.get(c)) for c in cols})
    return out


def to_csv(rows: list[dict[str, Any]], columns: list[str] | None = None) -> str:
    cols = columns or (list(rows[0].keys()) if rows else [])
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for row in normalize_rows(rows, cols):
        writer.writerow(row)
    return buf.getvalue()


def to_json(rows: list[dict[str, Any]], columns: list[str] | None = None) -> str:
    return json.dumps(
        normalize_rows(rows, columns), ensure_ascii=False, indent=2, default=str
    )
