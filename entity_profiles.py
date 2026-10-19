"""Look up Study and Delivery profile fields for an answer."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from neo4j_client import run_cypher

log = logging.getLogger(__name__)

INLINE_LIMIT = 5
MAX_LOOKUPS = 200
DETAIL_TITLE = "Detailed Study/Delivery information"

_STUDY_COLUMNS = {"study", "study_name", "studyname", "specific_study_name"}
_DELIVERY_NAME_COLUMNS = {
    "delivery",
    "delivery_name",
    "deliveryname",
    "specific_did",
}
_DELIVERY_DID_COLUMNS = {"did", "delivery_id", "deliveryid", "delivery_did"}
_STUDY_PROFILE_KEYS = {"Study", "Plan_Phase", "TA", "Study_Priority", "SDSL"}
_DELIVERY_PROFILE_KEYS = {
    "Name",
    "Reporting_Event",
    "Reporting_Detail",
    "Planned_Delivery_Date",
    "SDSL",
}
_ALIAS_LABEL = re.compile(
    r"\((?P<alias>[A-Za-z_][\w]*)\s*:\s*`?(?P<label>Study|Delivery)`?\b",
    re.IGNORECASE,
)
_AS_ALIAS = re.compile(
    r"^(?P<expr>.*?)\s+AS\s+`?(?P<alias>[A-Za-z_][\w]*)`?$",
    re.IGNORECASE | re.DOTALL,
)
_PROP_EXPR = re.compile(r"^`?(?P<alias>[A-Za-z_][\w]*)`?\.`?(?P<prop>[A-Za-z_][\w]*)`?$")
_VAR_EXPR = re.compile(r"^`?(?P<alias>[A-Za-z_][\w]*)`?$")
_CUT_KEYWORDS = {"order", "skip", "limit", "union"}


@dataclass(frozen=True)
class EntityPresentation:
    inline: str = ""
    panel: dict[str, Any] | None = None
    looked_up: bool = False


def prepare_entity_presentation(
    rows: list[dict[str, Any]],
    cypher: str,
    graph: dict[str, Any] | None,
    *,
    chinese: bool,
    query=None,
) -> EntityPresentation:
    """Return inline text for small sets and a collapsible payload for larger ones."""
    study_names, delivery_keys = collect_entities(rows, cypher, graph or {})
    if not study_names and not delivery_keys:
        return EntityPresentation()

    truncated = len(study_names) > MAX_LOOKUPS or len(delivery_keys) > MAX_LOOKUPS
    study_names = study_names[:MAX_LOOKUPS]
    delivery_keys = delivery_keys[:MAX_LOOKUPS]
    runner = query or _default_query
    try:
        studies = _load_studies(study_names, runner)
        deliveries = _load_deliveries(delivery_keys, runner)
    except Exception as exc:  # noqa: BLE001
        log.warning("Study/Delivery profile lookup failed: %s", exc)
        return EntityPresentation(looked_up=True)

    inline, panel = render_entity_presentation(
        studies, deliveries, chinese=chinese, truncated=truncated
    )
    return EntityPresentation(inline=inline, panel=panel, looked_up=True)


def collect_entities(
    rows: list[dict[str, Any]],
    cypher: str,
    graph: dict[str, Any] | None,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Study names and (kind, value) delivery keys in first-seen order."""
    bindings = _return_bindings(cypher)
    study_columns = {
        key for key, label, prop in bindings if label == "Study" and prop.lower() == "name"
    }
    delivery_name_columns = {
        key for key, label, prop in bindings if label == "Delivery" and prop.lower() == "name"
    }
    delivery_did_columns = {
        key for key, label, prop in bindings if label == "Delivery" and prop.lower() == "did"
    }
    node_columns = {
        key: label for key, label, prop in bindings if prop == "" and label in {"Study", "Delivery"}
    }

    studies: list[str] = []
    deliveries: list[tuple[str, str]] = []
    seen_studies: set[str] = set()
    seen_deliveries: set[tuple[str, str]] = set()

    def add_study(value: Any) -> None:
        for text in _texts(value):
            if text not in seen_studies:
                seen_studies.add(text)
                studies.append(text)

    def add_delivery(kind: str, value: Any) -> None:
        for text in _texts(value):
            key = (kind, text)
            if key not in seen_deliveries:
                seen_deliveries.add(key)
                deliveries.append(key)

    for row in rows:
        if not isinstance(row, dict):
            continue
        for column, value in row.items():
            normalized = _field_key(str(column))
            if str(column) in study_columns or normalized in _STUDY_COLUMNS:
                add_study(value)
            elif str(column) in node_columns and node_columns[str(column)] == "Study":
                add_study(_node_name(value))
            if str(column) in delivery_name_columns or normalized in _DELIVERY_NAME_COLUMNS:
                add_delivery("name", value)
            elif str(column) in delivery_did_columns or normalized in _DELIVERY_DID_COLUMNS:
                add_delivery("did", value)
            elif str(column) in node_columns and node_columns[str(column)] == "Delivery":
                name, did = _node_delivery(value)
                if name:
                    add_delivery("name", name)
                elif did:
                    add_delivery("did", did)

    for name in _graph_studies(graph or {}):
        add_study(name)
    for kind, value in _graph_deliveries(graph or {}):
        add_delivery(kind, value)
    return studies, deliveries


def render_entity_presentation(
    studies: list[dict[str, Any]],
    deliveries: list[dict[str, Any]],
    *,
    chinese: bool,
    truncated: bool = False,
) -> tuple[str, dict[str, Any] | None]:
    """Put five or fewer profiles in the answer; collapse anything larger."""
    inline_parts: list[str] = []
    panel_studies: list[dict[str, str]] = []
    panel_deliveries: list[dict[str, str]] = []
    if len(studies) <= INLINE_LIMIT:
        if studies:
            inline_parts.append(_format_studies(studies, chinese))
    else:
        panel_studies = [_public_study(row) for row in studies]
    if len(deliveries) <= INLINE_LIMIT:
        if deliveries:
            inline_parts.append(_format_deliveries(deliveries, chinese))
    else:
        panel_deliveries = [_public_delivery(row) for row in deliveries]

    panel = None
    if panel_studies or panel_deliveries:
        panel = {
            "title": DETAIL_TITLE,
            "studies": panel_studies,
            "deliveries": panel_deliveries,
            "truncated": truncated,
        }
    return "\n\n".join(inline_parts), panel


def study_lookup_cypher(names: list[str]) -> str:
    """Read Study_Info fields and SDSL from each study's most recent Delivery."""
    listed = json.dumps(names, ensure_ascii=False)
    return f"""UNWIND {listed} AS studyName
MATCH (s:Study {{Name: studyName}})
OPTIONAL MATCH (s)-[:HAS_DETAIL]->(si:Study_Info)
WITH s, head(collect(si)) AS si
OPTIONAL MATCH (s)-[:HAS_DELIVERY]->(d:Delivery)
WITH s, si, d,
  reduce(
    latest = '',
    dateValue IN [
      coalesce(toString(d.Actual_Delivery_Date), ''),
      coalesce(toString(d.Planned_Delivery_Date), '')
    ] |
    CASE WHEN dateValue > latest THEN dateValue ELSE latest END
  ) AS sortDate
ORDER BY s.Name, sortDate DESC, coalesce(d.Year, -1) DESC, coalesce(d.Month, -1) DESC, coalesce(d.Name, '') DESC
WITH s, si, head(collect(d)) AS latest
RETURN s.Name AS Study,
       si.Plan_Phase AS Plan_Phase,
       si.TA AS TA,
       si.Study_Priority AS Study_Priority,
       latest.SDSL AS SDSL,
       coalesce(latest.Name, latest.DID) AS SDSL_Delivery"""


def delivery_lookup_cypher(names: list[str], dids: list[str]) -> str:
    listed_names = json.dumps(names, ensure_ascii=False)
    listed_dids = json.dumps(dids, ensure_ascii=False)
    return f"""MATCH (d:Delivery)
WHERE d.Name IN {listed_names} OR d.DID IN {listed_dids}
RETURN d.Name AS Name,
       d.DID AS DID,
       d.Reporting_Event AS Reporting_Event,
       d.Reporting_Detail AS Reporting_Detail,
       d.Planned_Delivery_Date AS Planned_Delivery_Date,
       d.SDSL AS SDSL"""


def _default_query(cypher: str) -> list[dict[str, Any]]:
    return run_cypher(cypher, record_meta=False)


def _load_studies(names: list[str], query) -> list[dict[str, Any]]:
    if not names:
        return []
    rows = query(study_lookup_cypher(names))
    if not _has_keys(rows, _STUDY_PROFILE_KEYS):
        return []
    by_name = {str(row.get("Study")): row for row in rows if row.get("Study")}
    return [by_name[name] for name in names if name in by_name]


def _load_deliveries(keys: list[tuple[str, str]], query) -> list[dict[str, Any]]:
    if not keys:
        return []
    names = [value for kind, value in keys if kind == "name"]
    dids = [value for kind, value in keys if kind == "did"]
    rows = query(delivery_lookup_cypher(names, dids))
    if not _has_keys(rows, _DELIVERY_PROFILE_KEYS):
        return []
    ordered: list[dict[str, Any]] = []
    used: set[int] = set()
    for kind, value in keys:
        for index, row in enumerate(rows):
            if index in used:
                continue
            matched = row.get("Name") if kind == "name" else row.get("DID")
            if matched == value or (kind == "name" and row.get("DID") == value):
                used.add(index)
                ordered.append(row)
                break
    return ordered


def _has_keys(rows: list[dict[str, Any]], required: set[str]) -> bool:
    return bool(rows) and isinstance(rows[0], dict) and required.issubset(rows[0])


def _format_studies(studies: list[dict[str, Any]], chinese: bool) -> str:
    title = "**Study 基本信息**" if chinese else "**Study**"
    lines = [_study_line(_public_study(row), chinese) for row in studies]
    return title + "\n\n" + "\n".join(lines)


def _format_deliveries(deliveries: list[dict[str, Any]], chinese: bool) -> str:
    title = "**Delivery 基本信息**" if chinese else "**Delivery**"
    lines = [_delivery_line(_public_delivery(row), chinese) for row in deliveries]
    return title + "\n\n" + "\n".join(lines)


def _study_line(row: dict[str, str], chinese: bool) -> str:
    sep = "；" if chinese else "; "
    colon = "：" if chinese else ": "
    parts = [
        f"Plan_Phase{colon}{_show(row.get('Plan_Phase'))}",
        f"TA{colon}{_show(row.get('TA'))}",
        f"Study_Priority{colon}{_show(row.get('Study_Priority'))}",
        f"SDSL{colon}{_show(row.get('SDSL'))}",
    ]
    return f"- **{_show(row.get('Study'))}** — {sep.join(parts)}"


def _delivery_line(row: dict[str, str], chinese: bool) -> str:
    sep = "；" if chinese else "; "
    colon = "：" if chinese else ": "
    parts = [
        f"Reporting_Event{colon}{_show(row.get('Reporting_Event'))}",
        f"Reporting_Detail{colon}{_show(row.get('Reporting_Detail'))}",
        f"Planned_Delivery_Date{colon}{_show(row.get('Planned_Delivery_Date'))}",
        f"SDSL{colon}{_show(row.get('SDSL'))}",
    ]
    return f"- **{_show(row.get('Name'))}** — {sep.join(parts)}"


def _public_study(row: dict[str, Any]) -> dict[str, str]:
    sdsl = _clean(row.get("SDSL"))
    source = _clean(row.get("SDSL_Delivery"))
    if sdsl and source:
        sdsl = f"{sdsl} ({source})"
    return {
        "Study": _clean(row.get("Study")),
        "Plan_Phase": _clean(row.get("Plan_Phase")),
        "TA": _clean(row.get("TA")),
        "Study_Priority": _clean(row.get("Study_Priority")),
        "SDSL": sdsl,
    }


def _public_delivery(row: dict[str, Any]) -> dict[str, str]:
    return {
        "Name": _clean(row.get("Name") or row.get("DID")),
        "Reporting_Event": _clean(row.get("Reporting_Event")),
        "Reporting_Detail": _clean(row.get("Reporting_Detail")),
        "Planned_Delivery_Date": _clean(row.get("Planned_Delivery_Date")),
        "SDSL": _clean(row.get("SDSL")),
    }


def _show(value: Any) -> str:
    text = _clean(value)
    return text or "—"


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _texts(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        found: list[str] = []
        for item in value:
            found.extend(_texts(item))
        return found
    if isinstance(value, dict):
        for key in ("Name", "title", "DID"):
            text = _clean(value.get(key))
            if text:
                return [text]
        return []
    text = _clean(value)
    if not text or len(text) > 200:
        return []
    return [text]


def _node_name(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("Name") or value.get("title")
    return value


def _node_delivery(value: Any) -> tuple[str, str]:
    if isinstance(value, dict):
        return _clean(value.get("Name")), _clean(value.get("DID"))
    text = _clean(value)
    return text, ""


def _field_key(column: str) -> str:
    text = column.strip()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _graph_studies(graph: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for node in graph.get("nodes") or []:
        if "Study" not in _node_labels(node):
            continue
        name = _clean((node.get("properties") or {}).get("Name"))
        if name:
            names.append(name)
    return names


def _graph_deliveries(graph: dict[str, Any]) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for node in graph.get("nodes") or []:
        if "Delivery" not in _node_labels(node):
            continue
        props = node.get("properties") or {}
        name = _clean(props.get("Name"))
        did = _clean(props.get("DID"))
        if name:
            keys.append(("name", name))
        elif did:
            keys.append(("did", did))
    return keys


def _node_labels(node: dict[str, Any]) -> set[str]:
    labels = {str(node.get("label") or "")}
    labels.update(str(label) for label in (node.get("labels") or []))
    labels.discard("")
    return labels


def _return_bindings(cypher: str) -> list[tuple[str, str, str]]:
    """Map each returned alias.property to (result key, label, property)."""
    labels = {
        match.group("alias"): "Study" if match.group("label").lower() == "study" else "Delivery"
        for match in _ALIAS_LABEL.finditer(cypher or "")
    }
    clause = _return_clause(cypher or "")
    if not clause or not labels:
        return []
    bindings: list[tuple[str, str, str]] = []
    for item in _split_top_level(clause):
        match = _AS_ALIAS.match(item.strip())
        if match:
            expr = match.group("expr").strip()
            key = match.group("alias")
        else:
            expr = item.strip()
            key = expr
        prop_match = _PROP_EXPR.match(expr)
        if prop_match:
            alias = prop_match.group("alias")
            label = labels.get(alias)
            if label:
                bindings.append((key, label, prop_match.group("prop")))
            continue
        var_match = _VAR_EXPR.match(expr)
        if var_match:
            alias = var_match.group("alias")
            label = labels.get(alias)
            if label:
                bindings.append((key, label, ""))
    return bindings


def _return_clause(cypher: str) -> str:
    start = _last_keyword(cypher, "return")
    if start is None:
        return ""
    rest = cypher[start:]
    end = _next_keyword(rest, _CUT_KEYWORDS)
    return rest if end is None else rest[:end]


def _last_keyword(text: str, keyword: str) -> int | None:
    found = None
    for index in _keyword_indexes(text, {keyword}):
        found = index + len(keyword)
    return found


def _next_keyword(text: str, keywords: set[str]) -> int | None:
    indexes = _keyword_indexes(text, keywords)
    return indexes[0] if indexes else None


def _keyword_indexes(text: str, keywords: set[str]) -> list[int]:
    indexes: list[int] = []
    depth = 0
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"':
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            i += 1
            continue
        if ch == "`":
            end = text.find("`", i + 1)
            i = len(text) if end < 0 else end + 1
            continue
        if ch in "([{":
            depth += 1
            i += 1
            continue
        if ch in ")]}":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and ch.isalpha():
            end = i + 1
            while end < len(text) and text[end].isalpha():
                end += 1
            word = text[i:end].lower()
            if word in keywords and _word_boundary(text, i, end):
                if word == "order" and text[end : end + 3].lower() == " by":
                    indexes.append(i)
                elif word != "order":
                    indexes.append(i)
            i = end
            continue
        i += 1
    return indexes


def _word_boundary(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start else " "
    after = text[end] if end < len(text) else " "
    return not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_")


def _split_top_level(text: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"':
                if i + 1 < len(text):
                    buf.append(text[i + 1])
                i += 2
                continue
            if ch == quote:
                quote = ""
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            buf.append(ch)
        elif ch == "`":
            end = text.find("`", i + 1)
            chunk = text[i:] if end < 0 else text[i : end + 1]
            buf.append(chunk)
            i += len(chunk)
            continue
        elif ch in "([{":
            depth += 1
            buf.append(ch)
        elif ch in ")]}":
            depth = max(0, depth - 1)
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
        i += 1
    if buf:
        parts.append("".join(buf).strip())
    return [part for part in parts if part]
