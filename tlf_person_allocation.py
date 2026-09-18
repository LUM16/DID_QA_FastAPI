"""Allocate Generation and QC people to uploaded TLFs from a local evidence snapshot."""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable

import joblib
from openpyxl import Workbook

from du_team_recommendation import (
    _date_or_minimum,
    _recency_score,
    _resolve_recommendation_cache_path,
    load_uploaded_scope,
)
from effort_prediction import (
    DEFAULT_SIMILARITY_CACHE_PATH,
    GITHUB_ARTIFACT_BASE_URL,
    TLF_SEMANTIC_MATCH_THRESHOLD,
    _assignment_matches,
    _cached_tlf_semantic_similarity,
    _load_similarity_cache,
    _metadata_equal,
    _normalized_name,
    _normalized_title,
    _resolve_prediction_artifact,
    _save_similarity_cache,
)
from neo4j_client import get_driver, load_env
from vox_client import chat

TLF_PERSON_SNAPSHOT_VERSION = "tlf-person-allocation-v1"
DEFAULT_TLF_PERSON_SNAPSHOT_PATH = (
    Path(__file__).resolve().parent / "artifacts" / "tlf_person_allocation_snapshot.joblib"
)
DEFAULT_TLF_PERSON_SNAPSHOT_URL = (
    f"{GITHUB_ARTIFACT_BASE_URL}/tlf_person_allocation_snapshot.joblib"
)

# Each prior primary assignment reduces the next score by 12 points.
PRIMARY_ALLOCATION_PENALTY = 12.0
PERSON_TLF_CANDIDATE_LIMIT = 25
MAX_GROUP_PRIMARY_PEOPLE_PER_ROLE = 2
_ROLE_HISTORY_CACHE: dict[
    tuple[int, str], tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]
] = {}

PERSON_TEAM_LEADS_QUERY = """
MATCH (p:Person)
WHERE p.Team_Lead_Name IS NOT NULL
  AND trim(toString(p.Team_Lead_Name)) <> ''
RETURN DISTINCT toString(p.Team_Lead_Name) AS team_lead_name
ORDER BY team_lead_name
"""

PERSON_TLF_HISTORY_BY_TEAM_QUERY = """
MATCH (p:Person)-[:WORKS_ON]->(d:Delivery)-[t:HAS_TLF]->(tlf:TLF)
WHERE p.Name IS NOT NULL
  AND trim(toString(p.Name)) <> ''
  AND toString(p.Team_Lead_Name) = $team_lead_name
  AND toLower(toString(d.DID_Status)) = 'completed'
  AND d.DID IS NOT NULL
  AND d.Actual_Delivery_Date IS NOT NULL
RETURN DISTINCT
       toString(p.Name) AS person,
       toString(p.Team_Lead_Name) AS team_lead_name,
       toString(d.DID) AS did,
       substring(toString(d.Actual_Delivery_Date), 0, 10) AS completion_date,
       tlf.Name AS tlf_name,
       tlf.Type AS tlf_type,
       tlf.Source AS tlf_source,
       t.Generation AS generation,
       t.QC AS qc
"""

PERSON_ACTIVE_WORKLOAD_BY_TEAM_QUERY = """
MATCH (p:Person)-[:WORKS_ON]->(d:Delivery)
WHERE p.Name IS NOT NULL
  AND trim(toString(p.Name)) <> ''
  AND toString(p.Team_Lead_Name) = $team_lead_name
  AND toLower(toString(d.DID_Status)) IN ['ongoing', 'planned']
RETURN toString(p.Name) AS person,
       toString(p.Team_Lead_Name) AS team_lead_name,
       count(DISTINCT d) AS active_did_count
"""


def _read_query(
    query: str, parameters: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    load_env()
    driver = get_driver()
    try:
        database = os.environ.get("NEO4J_DATABASE", "neo4j")
        with driver.session(database=database) as session:
            return session.execute_read(lambda tx: tx.run(query, **(parameters or {})).data())
    finally:
        driver.close()


def _snapshot_path() -> Path:
    configured = os.environ.get("TLF_PERSON_ALLOCATION_SNAPSHOT_PATH")
    return Path(configured) if configured else DEFAULT_TLF_PERSON_SNAPSHOT_PATH


def _resolve_snapshot_path(snapshot_path: Path) -> Path:
    """Resolve the default snapshot if a Git-backed deployment has an LFS pointer."""
    # A new deployment has no snapshot until its operator runs refresh-snapshot.
    # Do not turn that clear action into an attempted remote artifact download.
    if not snapshot_path.exists():
        return snapshot_path
    if snapshot_path.resolve() != DEFAULT_TLF_PERSON_SNAPSHOT_PATH.resolve():
        return snapshot_path
    return _resolve_prediction_artifact(
        snapshot_path,
        DEFAULT_TLF_PERSON_SNAPSHOT_PATH,
        "TLF_PERSON_ALLOCATION_SNAPSHOT_URL",
        DEFAULT_TLF_PERSON_SNAPSHOT_URL,
    )


def refresh_person_tlf_snapshot(
    output_path: Path = DEFAULT_TLF_PERSON_SNAPSHOT_PATH,
) -> dict[str, Any]:
    """Run the only Neo4j reads used by this workflow and atomically save their result."""
    team_leads = [
        str(row.get("team_lead_name") or "").strip()
        for row in _read_query(PERSON_TEAM_LEADS_QUERY)
        if str(row.get("team_lead_name") or "").strip()
    ]
    history_rows = [
        row
        for team_lead_name in team_leads
        for row in _read_query(
            PERSON_TLF_HISTORY_BY_TEAM_QUERY, {"team_lead_name": team_lead_name}
        )
    ]
    if not history_rows:
        raise ValueError("Neo4j returned no completed Person × DID × TLF role evidence.")
    workload_rows = [
        row
        for team_lead_name in team_leads
        for row in _read_query(
            PERSON_ACTIVE_WORKLOAD_BY_TEAM_QUERY, {"team_lead_name": team_lead_name}
        )
    ]
    snapshot = {
        "version": TLF_PERSON_SNAPSHOT_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(),
        "history_rows": history_rows,
        "workload_rows": workload_rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    joblib.dump(snapshot, temporary_path)
    temporary_path.replace(output_path)
    return {
        "path": str(output_path.resolve()),
        "generated_at": snapshot["generated_at"],
        "history_row_count": len(history_rows),
        "workload_row_count": len(workload_rows),
    }


@lru_cache(maxsize=2)
def _load_person_tlf_snapshot_cached(
    path_string: str, modified_at_ns: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    path = Path(path_string)
    snapshot = joblib.load(path)
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("version") != TLF_PERSON_SNAPSHOT_VERSION
        or not isinstance(snapshot.get("history_rows"), list)
        or not isinstance(snapshot.get("workload_rows"), list)
        or not isinstance(snapshot.get("generated_at"), str)
    ):
        raise ValueError(f"Invalid TLF person-allocation snapshot: {path.resolve()}")
    return snapshot["history_rows"], snapshot["workload_rows"], {
        "path": str(path.resolve()),
        "generated_at": snapshot["generated_at"],
        "history_row_count": len(snapshot["history_rows"]),
        "workload_row_count": len(snapshot["workload_rows"]),
    }


def load_person_tlf_snapshot(
    snapshot_path: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Load local evidence only; deliberately never queries Neo4j."""
    path = _resolve_snapshot_path(snapshot_path or _snapshot_path())
    if not path.exists():
        raise FileNotFoundError(
            f"TLF person-allocation snapshot is unavailable: {path.resolve()}. "
            "Run `python tlf_person_allocation.py refresh-snapshot` after Neo4j updates."
        )
    return _load_person_tlf_snapshot_cached(
        str(path.resolve()), path.stat().st_mtime_ns
    )


def team_lead_candidates(history_rows: Iterable[dict[str, Any]]) -> list[str]:
    """Return only stored, display-ready Team_Lead_Name values."""
    return sorted(
        {
            str(row.get("team_lead_name") or "").strip()
            for row in history_rows
            if str(row.get("team_lead_name") or "").strip()
        },
        key=str.casefold,
    )


def _json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", stripped, flags=re.I)
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("The Team Lead matcher did not return a JSON object.")
    return payload


def resolve_team_lead_name(
    entered_name: str,
    candidates: Iterable[str],
    chat_fn: Callable[..., tuple[str, dict[str, int]]] = chat,
) -> dict[str, Any]:
    """Use Vox for extraction, then accept only the literal stored candidate it returns."""
    allowed = list(dict.fromkeys(str(item).strip() for item in candidates if str(item).strip()))
    if not allowed:
        raise ValueError("The snapshot has no Team_Lead_Name candidates.")
    system = (
        "Return JSON only: {\"team_lead_name\":\"<exact candidate or empty string>\"}. "
        "Match the user's Team Lead text only to one item in the supplied candidates. "
        "Never create, correct, abbreviate, or return any other name."
    )
    user = json.dumps(
        {"entered_name": entered_name, "candidates": allowed},
        ensure_ascii=False,
    )
    raw, usage = chat_fn(system, user, temperature=0)
    selected = str(_json_object(raw).get("team_lead_name") or "").strip()
    if selected not in allowed:
        raise ValueError(
            "The LLM match is not an exact Team_Lead_Name candidate in this snapshot. "
            "Choose or enter a stored Team Lead name."
        )
    return {"team_lead_name": selected, "usage": usage, "raw_match": selected}


def _single_tlf(row: dict[str, Any]) -> dict[str, str]:
    return {
        "name": str(row.get("tlf_name") or "").strip(),
        "type": str(row.get("tlf_type") or "").strip(),
        "source": str(row.get("tlf_source") or "").strip(),
    }


def _metadata_score(target: dict[str, str], historical: dict[str, str]) -> float:
    scores = [
        _metadata_equal(target.get(field), historical.get(field))
        for field in ("type", "source")
    ]
    return sum(scores) / 2


def _workload_scores(workload_rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for row in workload_rows:
        person = str(row.get("person") or "").strip()
        if person:
            counts[person] += int(row.get("active_did_count") or 0)
    return dict(counts)


def _semantic_candidates(
    target: dict[str, str], rows: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Retain a bounded set of relevant evidence rows before semantic matching."""
    target_title_words = {
        word for word in _normalized_title(target["name"]).split() if len(word) >= 3
    }

    def relevance(row: dict[str, Any]) -> tuple[int, int, int, datetime]:
        historical = _single_tlf(row)
        exact_title = _normalized_title(target["name"]) == _normalized_title(historical["name"])
        metadata_matches = sum(
            _metadata_equal(target.get(field), historical.get(field))
            for field in ("type", "source")
        )
        historical_words = {
            word for word in _normalized_title(historical["name"]).split() if len(word) >= 3
        }
        shared_words = len(target_title_words & historical_words)
        return (
            int(exact_title),
            metadata_matches,
            shared_words,
            _date_or_minimum(row.get("completion_date")),
        )

    relevant = [
        row
        for row in rows
        if relevance(row)[0] or relevance(row)[1] or relevance(row)[2]
    ]
    return sorted(relevant, key=relevance, reverse=True)[:PERSON_TLF_CANDIDATE_LIMIT]


def _role_candidates(
    target: dict[str, str],
    role_rows_by_person: dict[str, list[dict[str, Any]]],
    workloads: dict[str, int],
    maximum_workload: int,
    cache: dict[str, Any],
) -> list[dict[str, Any]]:
    """Keep each person's best completed, role-specific TLF evidence row."""
    best: dict[str, dict[str, Any]] = {}
    for person, person_rows in role_rows_by_person.items():
        for row in _semantic_candidates(target, person_rows):
            historical = _single_tlf(row)
            if not historical["name"]:
                continue
            # Cache only the title-semantic comparison. Type and Source receive their
            # explicitly allocated five points below rather than being double-counted.
            semantic, _ = _cached_tlf_semantic_similarity(
                [{"name": target["name"], "type": "", "source": ""}],
                [{"name": historical["name"], "type": "", "source": ""}],
                cache,
            )
            exact_title = _normalized_title(target["name"]) == _normalized_title(historical["name"])
            workload = workloads.get(person, 0)
            workload_score = 1.0 - workload / maximum_workload if maximum_workload else 1.0
            components = {
                "semantic_tlf_match": 40 * semantic,
                "exact_title": 15.0 if exact_title else 0.0,
                "type_source": 5 * _metadata_score(target, historical),
                "recent_relevant": (
                    5 * _recency_score(row.get("completion_date"))
                    if semantic >= TLF_SEMANTIC_MATCH_THRESHOLD
                    else 0.0
                ),
                "workload": 35 * workload_score,
            }
            candidate = {
                "person": person,
                "base_score": round(sum(components.values()), 2),
                "components": {key: round(value, 2) for key, value in components.items()},
                "active_did_count": workload,
                "evidence_did": str(row.get("did") or ""),
                "evidence_completion_date": row.get("completion_date"),
                "evidence_tlf": historical["name"],
            }
            existing = best.get(person)
            if existing is None or (
                candidate["base_score"],
                _date_or_minimum(candidate["evidence_completion_date"]),
            ) > (
                existing["base_score"],
                _date_or_minimum(existing["evidence_completion_date"]),
            ):
                best[person] = candidate
    return list(best.values())


def _team_role_history(
    team_lead_name: str, history_rows: Iterable[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Index a selected team's completed TLF evidence once per allocation run."""
    indexed: dict[str, dict[str, Any]] = {
        "generation": {
            "by_person": defaultdict(list), "by_title": defaultdict(list),
            "by_type": defaultdict(list), "by_source": defaultdict(list),
            "by_word": defaultdict(list),
        },
        "qc": {
            "by_person": defaultdict(list), "by_title": defaultdict(list),
            "by_type": defaultdict(list), "by_source": defaultdict(list),
            "by_word": defaultdict(list),
        },
    }
    for row in history_rows:
        if str(row.get("team_lead_name") or "").strip() != team_lead_name:
            continue
        person = str(row.get("person") or "").strip()
        if not person:
            continue
        for role in indexed:
            if _assignment_matches(row.get(role), person):
                historical = _single_tlf(row)
                if not historical["name"]:
                    continue
                role_index = indexed[role]
                role_index["by_person"][person].append(row)
                role_index["by_title"][_normalized_title(historical["name"])].append(row)
                if historical["type"]:
                    role_index["by_type"][_normalized_name(historical["type"])].append(row)
                if historical["source"]:
                    role_index["by_source"][_normalized_name(historical["source"])].append(row)
                for word in _normalized_title(historical["name"]).split():
                    if len(word) >= 3:
                        role_index["by_word"][word].append(row)
    return indexed


def _indexed_role_candidates(
    target: dict[str, str], role_index: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    """Retrieve only evidence connected to a target's title or metadata."""
    rows_by_person: dict[str, dict[tuple[str, str, str], dict[str, Any]]] = defaultdict(dict)

    def add(rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            person = str(row.get("person") or "").strip()
            if person:
                key = (
                    str(row.get("did") or ""),
                    str(row.get("tlf_name") or ""),
                    str(row.get("completion_date") or ""),
                )
                rows_by_person[person][key] = row

    add(role_index["by_title"].get(_normalized_title(target["name"]), []))
    if target.get("type"):
        add(role_index["by_type"].get(_normalized_name(target["type"]), []))
    if target.get("source"):
        add(role_index["by_source"].get(_normalized_name(target["source"]), []))
    for word in _normalized_title(target["name"]).split():
        if len(word) >= 3:
            add(role_index["by_word"].get(word, []))
    return {person: list(rows.values()) for person, rows in rows_by_person.items()}


def _rank_primary(
    candidates: Iterable[dict[str, Any]],
    allocations: dict[str, int],
    excluded_people: set[str] | None = None,
) -> list[dict[str, Any]]:
    excluded_people = excluded_people or set()
    ranked = []
    for candidate in candidates:
        person = candidate["person"]
        if person in excluded_people:
            continue
        penalty = PRIMARY_ALLOCATION_PENALTY * allocations[person]
        ranked.append(
            {
                **candidate,
                "prior_primary_allocations": allocations[person],
                "balancing_penalty": round(penalty, 2),
                "adjusted_score": round(candidate["base_score"] - penalty, 2),
            }
        )
    return sorted(ranked, key=lambda item: (-item["adjusted_score"], item["person"].casefold()))


def _backups(
    candidates: Iterable[dict[str, Any]], primary: dict[str, Any] | None,
    allocations: dict[str, int],
) -> list[dict[str, Any]]:
    primary_person = primary.get("person") if primary else None
    ranked = _rank_primary(candidates, allocations, {primary_person} if primary_person else set())
    return ranked[:2]


def _split_source_names(source: str) -> set[str]:
    return {
        _normalized_name(value)
        for value in re.split(r"[,;|]+", source)
        if _normalized_name(value)
    }


def _grouped_targets(
    scope: dict[str, list[dict[str, str]]]
) -> list[tuple[dict[str, str], str]]:
    """Prefer direct SDTM source matches, then source sets, then an individual TLF."""
    sdtm_names = {_normalized_name(item.get("name")) for item in scope["sdtms"]}
    grouped = []
    for index, target in enumerate(scope["tlfs"], start=1):
        source_names = _split_source_names(target.get("source", ""))
        mapped_sdtms = sorted(source_names & sdtm_names)
        if mapped_sdtms:
            group_key = f"SDTM: {', '.join(mapped_sdtms)}"
        elif source_names:
            group_key = f"Source: {', '.join(sorted(source_names))}"
        else:
            group_key = f"Individual: TLF {index}"
        grouped.append((target, group_key))
    return grouped


def _rank_group_primary(
    candidates: Iterable[dict[str, Any]],
    allocations: dict[str, int],
    role_owners: set[str],
    other_role_owners: set[str],
) -> list[dict[str, Any]]:
    eligible = _rank_primary(candidates, allocations, other_role_owners)
    preferred = [candidate for candidate in eligible if candidate["person"] in role_owners]
    if preferred:
        return preferred
    if len(role_owners) >= MAX_GROUP_PRIMARY_PEOPLE_PER_ROLE:
        return []
    return eligible


def allocation_export_rows(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten allocation results into one spreadsheet row per uploaded TLF."""
    rows = []
    for allocation in result["allocations"]:
        tlf = allocation["tlf"]
        group_type, _, group_key = allocation["group"].partition(": ")
        row = {
            "Group Type": group_type,
            "Group Key": group_key or allocation["group"],
            "TLF Title": tlf["name"],
            "TLF Type": tlf.get("type", ""),
            "Source Datasets": tlf.get("source", ""),
            "Lead Review Required": "Yes" if allocation["lead_review_required"] else "No",
            "Review Reason": allocation["fallback_reason"] or "",
            "Snapshot Generated At": result.get("snapshot", {}).get("generated_at", ""),
            "Matched Team Lead": result.get(
                "team_lead_name",
                result.get("team_match", {}).get("team_lead_name", ""),
            ),
        }
        for role, label in (("generation", "Generation"), ("qc", "QC")):
            recommendation = allocation[role]
            primary = recommendation["primary"]
            row[f"{label} Primary"] = primary["person"] if primary else ""
            row[f"{label} Primary Score"] = primary["adjusted_score"] if primary else None
            row[f"{label} Primary Active DIDs"] = (
                primary["active_did_count"] if primary else None
            )
            row[f"{label} Evidence DID"] = primary["evidence_did"] if primary else ""
            for index, backup in enumerate(recommendation["backups"], start=1):
                row[f"{label} Backup {index}"] = backup["person"]
                row[f"{label} Backup {index} Score"] = backup["adjusted_score"]
                row[f"{label} Backup {index} Active DIDs"] = backup["active_did_count"]
                row[f"{label} Backup {index} Evidence DID"] = backup["evidence_did"]
            for index in range(len(recommendation["backups"]) + 1, 3):
                row[f"{label} Backup {index}"] = ""
                row[f"{label} Backup {index} Score"] = None
                row[f"{label} Backup {index} Active DIDs"] = None
                row[f"{label} Backup {index} Evidence DID"] = ""
        rows.append(row)
    return rows


def allocation_excel_bytes(result: dict[str, Any]) -> bytes:
    """Create a downloadable one-row-per-TLF allocation workbook."""
    rows = allocation_export_rows(result)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "TLF Allocation"
    if rows:
        headers = list(rows[0])
        worksheet.append(headers)
        for row in rows:
            worksheet.append([row[header] for header in headers])
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = worksheet.dimensions
        for column in worksheet.columns:
            letter = column[0].column_letter
            worksheet.column_dimensions[letter].width = min(
                45, max(12, max(len(str(cell.value or "")) for cell in column) + 2)
            )
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def allocate_tlf_people(
    tlfs: Iterable[dict[str, str]],
    team_lead_name: str,
    history_rows: Iterable[dict[str, Any]],
    workload_rows: Iterable[dict[str, Any]],
    cache_path: Path = DEFAULT_SIMILARITY_CACHE_PATH,
    group_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return primary and two backups per role, applying run-local primary balancing."""
    targets = [item for item in tlfs if str(item.get("name") or "").strip()]
    if not targets:
        raise ValueError("No TLF rows were found in the uploaded input.")
    groups = list(group_keys) if group_keys is not None else [
        f"Individual: TLF {index}" for index in range(1, len(targets) + 1)
    ]
    if len(groups) != len(targets):
        raise ValueError("Each uploaded TLF must have exactly one allocation group.")
    rows = history_rows if isinstance(history_rows, list) else list(history_rows)
    workloads = _workload_scores(workload_rows)
    maximum_workload = max(workloads.values(), default=0)
    cache = _load_similarity_cache(_resolve_recommendation_cache_path(cache_path))
    role_history_key = (id(rows), team_lead_name)
    cached_role_history = _ROLE_HISTORY_CACHE.get(role_history_key)
    role_history = (
        cached_role_history[1]
        if cached_role_history and cached_role_history[0] is rows
        else None
    )
    if role_history is None:
        role_history = _team_role_history(team_lead_name, rows)
        _ROLE_HISTORY_CACHE[role_history_key] = (rows, role_history)
    allocations: dict[str, int] = defaultdict(int)
    group_owners: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"generation": set(), "qc": set()}
    )
    allocations_result = []
    for target, group_key in zip(targets, groups):
        generation = _role_candidates(
            target,
            _indexed_role_candidates(target, role_history["generation"]),
            workloads,
            maximum_workload,
            cache,
        )
        qc = _role_candidates(
            target,
            _indexed_role_candidates(target, role_history["qc"]),
            workloads,
            maximum_workload,
            cache,
        )
        owners = group_owners[group_key]
        generation_primary = next(
            iter(
                _rank_group_primary(
                    generation, allocations, owners["generation"], owners["qc"]
                )
            ),
            None,
        )
        if generation_primary:
            allocations[generation_primary["person"]] += 1
            owners["generation"].add(generation_primary["person"])
        qc_ranked = _rank_group_primary(
            qc,
            allocations,
            owners["qc"],
            owners["generation"]
            | ({generation_primary["person"]} if generation_primary else set()),
        )
        qc_primary = next(iter(qc_ranked), None)
        lead_review_required = False
        fallback_reason = None
        has_different_qc_evidence = generation_primary and any(
            item["person"] != generation_primary["person"] for item in qc
        )
        if generation_primary and qc_primary is None and not has_different_qc_evidence:
            same_person_qc = next(
                (item for item in qc if item["person"] == generation_primary["person"]), None
            )
            lead_review_required = True
            if same_person_qc:
                # Deliberately bypass the distinct/cap filters only after proving no
                # other QC evidence candidate exists.
                qc_primary = {
                    **same_person_qc,
                    "prior_primary_allocations": allocations[same_person_qc["person"]],
                    "balancing_penalty": 0.0,
                    "adjusted_score": same_person_qc["base_score"],
                    "same_person_fallback": True,
                }
                fallback_reason = (
                    "LEAD REVIEW REQUIRED: no different person has QC role evidence; "
                    "the Generation primary is the QC fallback."
                )
            else:
                fallback_reason = (
                    "LEAD REVIEW REQUIRED: no different person has QC role evidence "
                    "and the Generation primary has no QC evidence either."
                )
        if qc_primary and qc_primary["person"] != (generation_primary or {}).get("person"):
            allocations[qc_primary["person"]] += 1
            owners["qc"].add(qc_primary["person"])
        generation_backups = _backups(generation, generation_primary, allocations)
        qc_backups = _backups(qc, qc_primary, allocations)
        allocations_result.append(
            {
                "tlf": target,
                "group": group_key,
                "generation": {"primary": generation_primary, "backups": generation_backups},
                "qc": {"primary": qc_primary, "backups": qc_backups},
                "lead_review_required": lead_review_required,
                "fallback_reason": fallback_reason,
            }
        )
    if cache["misses"]:
        _save_similarity_cache(cache, _resolve_recommendation_cache_path(cache_path))
    return {
        "team_lead_name": team_lead_name,
        "allocations": allocations_result,
        "primary_balancing": {
            "penalty_per_prior_primary": PRIMARY_ALLOCATION_PENALTY,
        },
        "cache": {
            "hits": cache["hits"],
            "misses": cache["misses"],
            "candidate_pairs": cache["hits"] + cache["misses"],
        },
    }


def allocate_uploaded_tlfs(
    team_lead_input: str,
    primary_file: Any,
    data_csv_file: Any | None = None,
    chat_fn: Callable[..., tuple[str, dict[str, int]]] = chat,
) -> dict[str, Any]:
    """Load the upload and local snapshot, resolve the team, and allocate TLFs."""
    history_rows, workload_rows, snapshot = load_person_tlf_snapshot()
    match = resolve_team_lead_name(team_lead_input, team_lead_candidates(history_rows), chat_fn)
    scope = load_uploaded_scope(primary_file, data_csv_file)
    grouped_targets = _grouped_targets(scope)
    result = allocate_tlf_people(
        [target for target, _ in grouped_targets],
        match["team_lead_name"],
        history_rows,
        workload_rows,
        group_keys=[group_key for _, group_key in grouped_targets],
    )
    result["snapshot"] = snapshot
    result["team_match"] = match
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh the local Person × completed DID × TLF allocation snapshot."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    refresh = commands.add_parser(
        "refresh-snapshot",
        help="Query Neo4j once and write the snapshot used by the TLF allocation UI.",
    )
    refresh.add_argument(
        "--output", type=Path, default=_snapshot_path(),
        help="Snapshot output path (default: artifacts/tlf_person_allocation_snapshot.joblib).",
    )
    arguments = parser.parse_args()
    if arguments.command == "refresh-snapshot":
        details = refresh_person_tlf_snapshot(arguments.output)
        print(
            "TLF person-allocation snapshot refreshed: "
            f"{details['history_row_count']:,} evidence rows, "
            f"{details['workload_row_count']:,} workload rows."
        )
        print(f"Generated at: {details['generated_at']}")
        print(f"Path: {details['path']}")


if __name__ == "__main__":
    main()
