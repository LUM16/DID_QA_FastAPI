"""Validate a constrained, post-query presentation choice for Neo4j results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
import json
import math
import re
from numbers import Number
from typing import Any, Callable

import requests
from openai import OpenAIError

Usage = dict[str, int]
Chat = Callable[[str, str], tuple[str, Usage]]

DISPLAY_TYPES = {
    "table",
    "kpi_table",
    "bar",
    "horizontal_bar",
    "line",
    "stacked_bar",
    "grouped_bar",
    "pie",
}
CHART_TYPES = DISPLAY_TYPES - {"table", "kpi_table"}


def _field_names(rows: list[dict[str, Any]]) -> list[str]:
    return list(dict.fromkeys(key for row in rows for key in row if isinstance(key, str)))


def _extract_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)```", candidate, re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()
    value = json.loads(candidate)
    if not isinstance(value, dict):
        raise ValueError("Presentation selection must be a JSON object.")
    return value


def build_presentation_prompt(
    question: str, rows: list[dict[str, Any]]
) -> tuple[str, str]:
    """Build the constrained selection prompt from fields actually returned."""
    fields = _field_names(rows)
    system = """Choose a display for already-returned Neo4j rows.
Return exactly one JSON object and no markdown. You may select only exact field
names in the supplied field list. Never calculate, aggregate, rename, convert,
or transform values. Prefer table when the fields are not suitable for a chart.

Allowed responses:
- table or kpi_table:
  {"display_type":"table","table_fields":["exact_field_name"],"summary_required":false}
- pie:
  {"display_type":"pie","names_field":"exact_field_name",
   "values_field":"exact_numeric_field_name",
   "table_fields":["exact_field_name"],"summary_required":false}
- bar, horizontal_bar, line, stacked_bar, or grouped_bar:
  {"display_type":"bar","x_field":"exact_field_name",
   "y_fields":["exact_numeric_field_name"],"series_field":null,
   "table_fields":["exact_field_name"],"summary_required":false}

For a chart, x_field and each y_fields item must be a distinct supplied field.
series_field must be null or a distinct supplied field. table_fields must be a
non-empty list of supplied fields. Use pie only for a share of a whole across a
few categories. Use a chart only when returned values already support it; do
not derive a metric. Set summary_required to true only when a short textual
conclusion is necessary to answer a comparison or direct question.
Otherwise set it to false so the chart or table is the only result content."""
    user = f"""User question:
{question}

Actual return fields (the only permitted field names):
{json.dumps(fields, ensure_ascii=False)}

Returned rows (already final; do not alter them):
{json.dumps(rows[:80], ensure_ascii=False, default=str)}"""
    return system, user


def _valid_field_list(value: Any, fields: set[str]) -> list[str] | None:
    if not isinstance(value, list) or not value:
        return None
    if any(not isinstance(item, str) or item not in fields for item in value):
        return None
    return value if len(set(value)) == len(value) else None


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, Number) and not isinstance(value, bool) and math.isfinite(float(value))


def _is_chart_category(value: Any) -> bool:
    return isinstance(value, (str, Number, date, datetime)) and not isinstance(value, bool)


def _chart_fields_are_usable(
    rows: list[dict[str, Any]],
    x_field: str,
    y_fields: list[str],
    series_field: str | None,
) -> bool:
    if not rows:
        return False
    for row in rows:
        if not _is_chart_category(row.get(x_field)):
            return False
        if series_field is not None and not _is_chart_category(row.get(series_field)):
            return False
        if any(not _is_finite_number(row.get(field)) for field in y_fields):
            return False
    return True


def _is_temporal_field(rows: list[dict[str, Any]], field: str) -> bool:
    return bool(rows) and all(
        re.fullmatch(r"\d{4}(?:-\d{2}){0,2}", str(row.get(field) or ""))
        for row in rows
    )


def _format_table_value(value: Any, depth: int = 0) -> Any:
    """Convert nested Neo4j values into scalar cells for Streamlit dataframes."""
    if value is None or isinstance(value, (str, Number, bool, date, datetime)):
        return value
    if depth >= 3:
        return str(value)
    if isinstance(value, Mapping):
        return "; ".join(
            f"{key}: {_format_table_value(item, depth + 1)}"
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return " | ".join(str(_format_table_value(item, depth + 1)) for item in value)
    return str(value)


def _table_payload(rows: list[dict[str, Any]], fields: list[str]) -> dict[str, Any]:
    return {
        "columns": fields,
        "rows": [
            {field: _format_table_value(row.get(field)) for field in fields}
            for row in rows
        ],
    }


def _data_note(fields: list[str]) -> str | None:
    notes: list[str] = []
    normalized = {field.casefold() for field in fields}
    if normalized & {"hours", "recorded_hours", "time_on_hours"}:
        notes.append("Recorded TIME_ON hours.")
    if "task_count" in normalized:
        notes.append("Assigned task count.")
    return " ".join(notes) or None


def table_from_rows(rows: list[dict[str, Any]], fields: list[str] | None = None) -> dict[str, Any]:
    """Always-safe table payload from Neo4j rows."""
    table_fields = fields or _field_names(rows)
    return _table_payload(rows, table_fields)


def validate_presentation_selection(
    selection: dict[str, Any], rows: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Return a render-safe payload, or None when the LLM response is invalid."""
    fields = _field_names(rows)
    field_set = set(fields)
    display_type = selection.get("display_type")
    if display_type not in DISPLAY_TYPES:
        return None

    if display_type in {"table", "kpi_table"}:
        if set(selection) != {"display_type", "table_fields", "summary_required"}:
            return None
        table_fields = _valid_field_list(selection.get("table_fields"), field_set)
        summary_required = selection.get("summary_required")
        if table_fields is None or not isinstance(summary_required, bool):
            return None
        return {
            "display_type": display_type,
            "table": _table_payload(rows, table_fields),
            "data_note": _data_note(table_fields),
            "summary_required": summary_required,
        }

    if display_type == "pie":
        if set(selection) != {
            "display_type",
            "names_field",
            "values_field",
            "table_fields",
            "summary_required",
        }:
            return None
        names_field = selection.get("names_field")
        values_field = selection.get("values_field")
        table_fields = _valid_field_list(selection.get("table_fields"), field_set)
        summary_required = selection.get("summary_required")
        if (
            not isinstance(names_field, str)
            or names_field not in field_set
            or not isinstance(values_field, str)
            or values_field not in field_set
            or names_field == values_field
            or table_fields is None
            or not isinstance(summary_required, bool)
            or not _chart_fields_are_usable(rows, names_field, [values_field], None)
        ):
            return None
        return {
            "display_type": "pie",
            "chart_type": "pie",
            "data": rows,
            "x": names_field,
            "y": [values_field],
            "names": names_field,
            "values": values_field,
            "series": None,
            "horizontal": False,
            "stack": None,
            "table": _table_payload(rows, table_fields),
            "data_note": _data_note([values_field]),
            "summary_required": summary_required,
        }

    if set(selection) != {
        "display_type",
        "x_field",
        "y_fields",
        "series_field",
        "table_fields",
        "summary_required",
    }:
        return None
    x_field = selection.get("x_field")
    y_fields = _valid_field_list(selection.get("y_fields"), field_set)
    series_field = selection.get("series_field")
    table_fields = _valid_field_list(selection.get("table_fields"), field_set)
    summary_required = selection.get("summary_required")
    if (
        not isinstance(x_field, str)
        or x_field not in field_set
        or y_fields is None
        or table_fields is None
        or not isinstance(summary_required, bool)
        or (series_field is not None and (not isinstance(series_field, str) or series_field not in field_set))
        or x_field in y_fields
        or (series_field is not None and (series_field == x_field or series_field in y_fields))
        or not _chart_fields_are_usable(rows, x_field, y_fields, series_field)
        or (display_type == "line" and not _is_temporal_field(rows, x_field))
    ):
        return None

    chart_type = "line" if display_type == "line" else "bar"
    return {
        "display_type": display_type,
        "chart_type": chart_type,
        "data": rows,
        "x": x_field,
        "y": y_fields,
        "series": series_field,
        "horizontal": display_type == "horizontal_bar",
        "stack": True if display_type == "stacked_bar" else (
            False if display_type == "grouped_bar" else None
        ),
        "table": _table_payload(rows, table_fields),
        "data_note": _data_note(y_fields),
        "summary_required": summary_required,
    }


def select_result_presentation(
    question: str, rows: list[dict[str, Any]], chat: Chat
) -> tuple[dict[str, Any] | None, Usage, str | None]:
    """Select presentation without allowing its failure to invalidate query results."""
    fields = _field_names(rows)
    empty_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    if not rows or not fields:
        return None, empty_usage, None
    if len(rows) == 1 and len(fields) == 1 and _is_finite_number(rows[0].get(fields[0])):
        return (
            {
                "display_type": "table",
                "table": _table_payload(rows, fields),
                "data_note": _data_note(fields),
                "summary_required": True,
            },
            empty_usage,
            None,
        )
    try:
        system, user = build_presentation_prompt(question, rows)
        raw, usage = chat(system, user)
        presentation = validate_presentation_selection(_extract_json_object(raw), rows)
        warning = (
            None
            if presentation is not None
            else "Presentation selection was invalid; showing the text answer only."
        )
        return presentation, usage, warning
    except (
        json.JSONDecodeError,
        KeyError,
        OpenAIError,
        requests.RequestException,
        RuntimeError,
        TypeError,
        ValueError,
    ):
        return (
            None,
            empty_usage,
            "Presentation is unavailable; showing the text answer only.",
        )
