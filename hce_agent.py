"""HCE branch of the Q&A agent.

Routing:   keyword "HCE" -> HCE directly; resource-related wording
           (Chinese/English staffing words, FTE, utilization...) -> LLM decides.
Parameters: LLM extracts mode/persons/time range/filters as JSON; keys are
           validated against whitelists before calling hce_caclulation.
Defaults:  no feature mentioned -> feature_filter = {} (total HCE);
           no group mentioned   -> group_filter = {} (all persons);
           no time range        -> ask the user instead of guessing.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict
from datetime import date
from typing import Any, Callable

import hce_caclulation as hce
from team_scope import TeamScope
from vox_client import add_usage, chat as _chat, empty_usage

HCE_KEYWORD_RE = re.compile(r"(?<![A-Za-z])HCE(?![A-Za-z])", re.IGNORECASE)
HCE_CANDIDATE_RE = re.compile(
    r"人力|资源(?:占用|利用|投入)?|投入|FTE|headcount|utili[sz]ation|head\s*count",
    re.IGNORECASE,
)

# user wording -> filter key (traversal path handled by hce_caclulation)
FEATURE_KEYS: dict[str, str] = {
    "Study_Info.Study_Type": "study type, e.g. INTERVENTIONAL / OBSERVATIONAL",
    "Study_Info.Derived_TA": "therapeutic area, e.g. Oncology, Vaccines, I&I, Internal Medicine, Other",
    "Study_Info.Name": "study number, e.g. C1071032",
    "DIDN_Month.DID": "DID, e.g. C5841001_16",
    "Study_Info.Plan_Phase": "study phase",
    "Study_Info.Study_Priority": "study priority",
}
GROUP_KEYS: dict[str, str] = {
    "Site": "site, e.g. China / US / India",
    "Team_Lead_Name": "team lead name",
    "Group_Lead_Name": "group lead name",
    "TA_Lead_Name": "TA lead name",
}
HCE_MAX_TOKENS = 400
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

ChatFn = Callable[..., tuple[str, dict[str, int]]]


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{[\s\S]*\}", text)
    payload = json.loads(match.group(0) if match else text)
    if not isinstance(payload, dict):
        raise ValueError("HCE response must be a JSON object.")
    return payload


def _history_text(history: list[dict[str, Any]] | None) -> str:
    return "\n".join(
        f"{m.get('role')}: {str(m.get('content'))[:500]}" for m in (history or [])[-4:]
    )


# ---------------------------------------------------------------------------
# Intent
# ---------------------------------------------------------------------------


def classify_hce_intent(
    question: str,
    history: list[dict[str, Any]] | None = None,
    chat: ChatFn = _chat,
) -> tuple[bool, dict[str, int]]:
    """Keyword HCE -> True; resource wording -> LLM decides; otherwise False."""
    if HCE_KEYWORD_RE.search(question):
        return True, empty_usage()
    if not HCE_CANDIDATE_RE.search(question):
        return False, empty_usage()
    system = """Decide whether the user asks for HCE (headcount equivalent /
resource utilization): how much staffing capacity (in person-months, FTE)
people or a department spent overall or on some studies/DIDs/TAs in a period.
Recorded raw hours, task lists or delivery status are NOT HCE.
Return exactly {"intent":"hce"} or {"intent":"other"}."""
    user = f"Recent conversation:\n{_history_text(history) or '(none)'}\n\nQuestion:\n{question}"
    raw, usage = chat(system, user, temperature=0, max_tokens=60)
    try:
        return _extract_json(raw).get("intent") == "hce", usage
    except ValueError:  # includes JSONDecodeError -> fall back to normal flow
        return False, usage


# ---------------------------------------------------------------------------
# Parameter extraction + validation
# ---------------------------------------------------------------------------


def _clean_filter(raw: Any, allowed: dict[str, str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in allowed:
            raise ValueError(f"Unsupported filter key: {key} (allowed: {', '.join(allowed)})")
        if value in (None, "", []):
            continue
        out[key] = [str(v) for v in value] if isinstance(value, list) else [str(value)]
    return out


def validate_hce_parameters(payload: dict[str, Any]) -> dict[str, Any]:
    mode = payload.get("mode")
    if mode not in {"person", "department"}:
        raise ValueError(f"Cannot tell whether this is person or department HCE: {mode!r}")
    persons = [str(p).strip() for p in payload.get("persons") or [] if str(p).strip()]
    if mode == "person" and not persons:
        raise ValueError("Person HCE requires a person name or NTID.")
    start, end = payload.get("start"), payload.get("end")
    missing_time = not (isinstance(start, str) and _ISO_DATE.match(start)
                        and isinstance(end, str) and _ISO_DATE.match(end))
    params: dict[str, Any] = {
        "mode": mode,
        "persons": persons,
        "start": None if missing_time else date.fromisoformat(start),
        "end": None if missing_time else date.fromisoformat(end),
        "feature_filter": _clean_filter(payload.get("feature_filter"), FEATURE_KEYS),
        "group_filter": _clean_filter(payload.get("group_filter"), GROUP_KEYS),
    }
    if params["start"] and params["end"] and params["end"] < params["start"]:
        raise ValueError("End date is earlier than start date.")
    return params


def extract_hce_parameters(
    question: str,
    history: list[dict[str, Any]] | None = None,
    today: date | None = None,
    chat: ChatFn = _chat,
) -> tuple[dict[str, Any], dict[str, int]]:
    today = today or date.today()
    feature_doc = "\n".join(f'  "{k}": {v}' for k, v in FEATURE_KEYS.items())
    group_doc = "\n".join(f'  "{k}": {v}' for k, v in GROUP_KEYS.items())
    system = f"""Extract HCE calculation parameters. Today is {today.isoformat()}.
Return ONE JSON object:
{{"mode": "person" | "department",
  "persons": [official names or NTIDs exactly as written in the question],
  "start": "YYYY-MM-DD" | null, "end": "YYYY-MM-DD" | null,
  "feature_filter": {{key: [values]}},
  "group_filter": {{key: [values]}}}}

Rules:
- mode=person when specific people are named; otherwise department.
- Resolve relative periods (first half of this year, Q1, last month, last 3 months) using today.
  Use first day of start month and last day of end month.
  If the question and conversation give NO period, set start and end to null.
- feature_filter: only when the user restricts which work counts. Allowed keys:
{feature_doc}
  Study numbers like C1071032 -> Study_Info.Name; IDs with _<digits> -> DIDN_Month.DID.
  Study_Type values are uppercase (INTERVENTIONAL, OBSERVATIONAL).
  If no restriction, use {{}}.
- group_filter (department only): which people are included. Allowed keys:
{group_doc}
  If none, use {{}}.
- Never invent keys or values. No explanation."""
    user = f"Recent conversation:\n{_history_text(history) or '(none)'}\n\nQuestion:\n{question}"
    raw, usage = chat(system, user, temperature=0, max_tokens=HCE_MAX_TOKENS)
    return validate_hce_parameters(_extract_json(raw)), usage


# ---------------------------------------------------------------------------
# Answer
# ---------------------------------------------------------------------------


def _filter_text(filters: dict[str, Any]) -> str:
    if not filters:
        return "none (all hours)"
    return "; ".join(f"{k} ∈ {', '.join(v)}" for k, v in filters.items())


def _sort_people(
    params: dict[str, Any], people: list[hce.PersonHCE], levels: dict[str, int]
) -> list[hce.PersonHCE]:
    """Team: reporting level, then name. Department: name. Person: feature HCE desc."""
    if levels:
        return sorted(people, key=lambda p: (levels.get(p.name, 99), p.name.casefold()))
    if params["mode"] == "department":
        return sorted(people, key=lambda p: p.name.casefold())
    return sorted(people, key=lambda p: -p.feature_hce)


def _format_answer(
    params: dict[str, Any],
    people: list[hce.PersonHCE],
    total: float | None,
    levels: dict[str, int] | None = None,
) -> str:
    levels = levels or {}
    period = f"{params['start']:%Y-%m-%d} ~ {params['end']:%Y-%m-%d}"
    if params.get("requested_end"):
        period += f", capped at today (requested end {params['requested_end']:%Y-%m-%d})"
    lines = [f"**HCE result** ({period})", "", f"- Feature filter: {_filter_text(params['feature_filter'])}"]
    if params["mode"] == "department":
        if params.get("team_leads"):
            others = {k: v for k, v in params["group_filter"].items() if k != "Name"}
            group = f"team of {', '.join(params['team_leads'])} (Active members incl. lead)"
            if others:
                group += f"; {_filter_text(others)}"
        else:
            group = _filter_text(params["group_filter"]).replace("all hours", "all persons")
        lines += [f"- Person scope: {group}", f"- Department feature HCE total: **{total:.3f}** ({len(people)} persons)"]
    if not people:
        lines += ["", "No matching persons found."]
        return "\n".join(lines)
    level_head, level_sep = ("Level | ", "---|") if levels else ("", "")
    lines += ["", f"| {level_head}Name | NTID | Site | Total HCE | Feature hours / Total hours | Feature HCE |",
              f"|{level_sep}---|---|---|---|---|---|"]
    for p in people[:30]:
        level = f"{levels.get(p.name, '')} | " if levels else ""
        lines.append(
            f"| {level}{p.name} | {p.ntid} | {p.site} | {p.total_hce:.3f} | "
            f"{p.feature_hours:.1f} / {p.total_hours:.1f} | {p.feature_hce:.3f} |"
        )
    if len(people) > 30:
        lines.append("\n(Showing the first 30 persons; see the table or CSV/JSON download for full results.)")
    if levels:
        lines.append("\nLevel: 0 = team lead, 1 = direct report, 2+ = indirect report.")
    lines += ["", "Method: Total HCE = active workdays / workdays in the period (Mon-Fri, holidays ignored; "
              "1.0 = active for the whole period); department HCE = sum over persons; "
              "Feature HCE = Total HCE x feature hours / total hours."]
    return "\n".join(lines)


def _to_rows(people: list[hce.PersonHCE], levels: dict[str, int]) -> list[dict[str, Any]]:
    rows = []
    for p in people:
        row = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in asdict(p).items()}
        rows.append({"report_level": levels.get(p.name), **row} if levels else row)
    return rows


def _result(answer: str, rows: list[dict[str, Any]], usage, timings, error=None) -> dict[str, Any]:
    return {
        "answer": answer,
        "cypher": "",
        "rows": rows,
        "columns": list(rows[0].keys()) if rows else [],
        "schema": None,
        "error": error,
        "usage": usage,
        "timings_ms": timings,
        "case_id": None,
        "graph": {},
        "org_chart": False,  # rows carry names/levels, not a renderable reporting tree
    }


def clamp_to_today(params: dict[str, Any], today: date) -> dict[str, Any] | None:
    """Periods that are not over yet end today. Future-only periods -> None."""
    if params["start"] > today:
        return None
    if params["end"] > today:
        return {**params, "end": today, "requested_end": params["end"]}
    return params


_LEAD_KEYS = ("Team_Lead_Name", "Group_Lead_Name", "TA_Lead_Name")


def apply_team_scope(params: dict[str, Any], scope: TeamScope) -> dict[str, Any]:
    """Team questions are department HCE over the team's Active members."""
    group = {k: v for k, v in params["group_filter"].items() if k not in _LEAD_KEYS}
    group["Name"] = list(scope.members)
    return {**params, "mode": "department", "persons": [], "group_filter": group,
            "team_leads": list(scope.leads)}


def answer_hce(
    question: str,
    history: list[dict[str, Any]] | None = None,
    initial_usage: dict[str, int] | None = None,
    initial_timings: dict[str, int] | None = None,
    chat: ChatFn = _chat,
    today: date | None = None,
    team_scope: TeamScope | None = None,
) -> dict[str, Any]:
    timings = dict(initial_timings or {})
    usage = initial_usage or empty_usage()
    started = time.perf_counter()
    try:
        params, p_usage = extract_hce_parameters(question, history, today=today, chat=chat)
        usage = add_usage(usage, p_usage)
    except Exception as exc:  # noqa: BLE001
        return _result(f"Failed to parse HCE parameters: {exc}", [], usage, timings, error=str(exc))
    timings["hce_parameters"] = int((time.perf_counter() - started) * 1000)
    if team_scope is not None:
        params = apply_team_scope(params, team_scope)

    if params["start"] is None:
        return _result(
            "Please specify the HCE time period (e.g. \"January to June 2026\" or \"first half of this year\").",
            [], usage, timings,
        )
    params = clamp_to_today(params, today or date.today())
    if params is None:
        return _result("The requested HCE period starts in the future; no data yet.", [], usage, timings)

    started = time.perf_counter()
    if params["mode"] == "person":
        people = hce.person_hce(params["persons"], params["start"], params["end"],
                                feature_filter=params["feature_filter"])
        total = None
    else:
        total, people = hce.department_hce(params["start"], params["end"],
                                           group_filter=params["group_filter"],
                                           feature_filter=params["feature_filter"])
    timings["hce_calculation"] = int((time.perf_counter() - started) * 1000)

    levels = dict(team_scope.levels) if team_scope is not None else {}
    people = _sort_people(params, people, levels)
    rows = _to_rows(people, levels)
    return _result(_format_answer(params, people, total, levels), rows, usage, timings)
