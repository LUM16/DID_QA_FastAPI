"""Train and run person-by-DID effort forecasts from read-only Neo4j data."""

from __future__ import annotations

import argparse
import csv
from difflib import SequenceMatcher
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import date, datetime
from functools import lru_cache
from itertools import groupby
from pathlib import Path
from statistics import median
from typing import Any, Iterable
from urllib.request import Request, urlopen

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import HashingVectorizer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from neo4j_client import get_driver, load_env

MODEL_VERSION = "did-effort-ridge-v3-robust"
DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parent / "artifacts" / "did_effort_model.joblib"
)
DEFAULT_SIMILARITY_CACHE_PATH = (
    Path(__file__).resolve().parent
    / "artifacts"
    / "did_effort_similarity_cache.joblib"
)
GITHUB_ARTIFACT_BASE_URL = (
    "https://media.githubusercontent.com/media/LUM16/DID_QA/main/artifacts"
)
DEFAULT_MODEL_URL = f"{GITHUB_ARTIFACT_BASE_URL}/did_effort_model.joblib"
DEFAULT_SIMILARITY_CACHE_URL = (
    f"{GITHUB_ARTIFACT_BASE_URL}/did_effort_similarity_cache.joblib"
)
LFS_POINTER_PREFIX = b"version https://git-lfs.github.com/spec/v1"
TLF_SEMANTIC_MATCH_THRESHOLD = 0.70
SIMILARITY_CACHE_VERSION = "tlf-char-wb-3-5-greedy-0.70-v1"
RECENT_CANDIDATE_LIMIT = 50
SAME_STUDY_CANDIDATE_LIMIT = 100
EXACT_OVERLAP_CANDIDATE_LIMIT = 100
SAME_TA_CANDIDATE_LIMIT = 25
PROGRESS_INTERVAL = 500
CACHE_CHECKPOINT_INTERVAL = 2000
TITLE_VECTORIZER = HashingVectorizer(
    analyzer="char_wb",
    ngram_range=(3, 5),
    n_features=2**16,
    alternate_sign=False,
    norm="l2",
)

TASK_FIELDS = (
    "task_count",
    "task_generation_count",
    "task_qc_count",
    "tlf_count",
    "tlf_generation_count",
    "tlf_qc_count",
    "adam_count",
    "adam_generation_count",
    "adam_qc_count",
    "sdtm_count",
    "sdtm_generation_count",
    "sdtm_qc_count",
)

NUMERIC_FEATURES = [
    *TASK_FIELDS,
    "person_completed_count",
    "person_median_hours",
    "person_recent_median_hours",
    "person_median_hours_per_task",
    "global_completed_count",
    "global_median_hours",
    "global_median_hours_per_task",
    "tlf_prior_overlap_count",
    "adam_prior_overlap_count",
    "sdtm_prior_overlap_count",
    "tlf_prior_coverage",
    "adam_prior_coverage",
    "sdtm_prior_coverage",
    "overall_prior_coverage",
    "tlf_unseen_count",
    "adam_unseen_count",
    "sdtm_unseen_count",
    "max_tlf_similarity",
    "max_tlf_semantic_similarity",
    "max_tlf_semantic_coverage",
    "max_adam_similarity",
    "max_sdtm_similarity",
    "max_overall_similarity",
    "max_combined_similarity",
    "top3_combined_similarity_mean",
    "top5_combined_similarity_mean",
    "similar_did_count_ge_70",
    "similar_did_count_ge_85",
    "weighted_similar_hours",
    "weighted_similar_hours_per_task",
    "latest_similar_hours",
    "similar_hours_trend",
    "days_since_similar_work",
]

CATEGORICAL_FEATURES = [
    "ta",
    "study_type",
    "reporting_event",
    "draft_or_final",
]

TRAINING_QUERY = """
MATCH (p:Person)-[wo:WORKS_ON]->(d:Delivery)
WHERE toLower(toString(d.DID_Status)) = 'completed'
  AND p.Name = $person
WITH p, d,
     count(wo) AS workOnRelCount,
     max(toFloat(coalesce(wo.Task_Num_Total, wo.CSR_Task_Num_Total))) AS taskCount,
     max(toFloat(coalesce(wo.Task_Num_Generation, wo.CSR_Task_Num_Generation))) AS taskGenerationCount,
     max(toFloat(coalesce(wo.Task_Num_QC, wo.CSR_Task_Num_QC))) AS taskQcCount,
     max(toFloat(coalesce(wo.TLF_Num_Total, wo.CSR_TLF_Num_Total))) AS tlfCount,
     max(toFloat(coalesce(wo.TLF_Num_Generation, wo.CSR_TLF_Num_Generation))) AS tlfGenerationCount,
     max(toFloat(coalesce(wo.TLF_Num_QC, wo.CSR_TLF_Num_QC))) AS tlfQcCount,
     max(toFloat(coalesce(wo.ADaM_Num_Total, wo.CSR_ADaM_Num_Total))) AS adamCount,
     max(toFloat(coalesce(wo.ADaM_Num_Generation, wo.CSR_ADaM_Num_Generation))) AS adamGenerationCount,
     max(toFloat(coalesce(wo.ADaM_Num_QC, wo.CSR_ADaM_Num_QC))) AS adamQcCount,
     max(toFloat(coalesce(wo.SDTM_Num_Total, wo.CSR_SDTM_Num_Total))) AS sdtmCount,
     max(toFloat(coalesce(wo.SDTM_Num_Generation, wo.CSR_SDTM_Num_Generation))) AS sdtmGenerationCount,
     max(toFloat(coalesce(wo.SDTM_Num_QC, wo.CSR_SDTM_Num_QC))) AS sdtmQcCount
OPTIONAL MATCH (s:Study)-[:HAS_DELIVERY]->(d)
WITH p, d, workOnRelCount, taskCount, taskGenerationCount, taskQcCount,
     tlfCount, tlfGenerationCount, tlfQcCount,
     adamCount, adamGenerationCount, adamQcCount,
     sdtmCount, sdtmGenerationCount, sdtmQcCount,
     collect(DISTINCT s) AS studies
WITH p, d, workOnRelCount, taskCount, taskGenerationCount, taskQcCount,
     tlfCount, tlfGenerationCount, tlfQcCount,
     adamCount, adamGenerationCount, adamQcCount,
     sdtmCount, sdtmGenerationCount, sdtmQcCount,
     head(studies) AS s, size(studies) AS studyCount
CALL {
  WITH p, d
  OPTIONAL MATCH (p)-[time:TIME_ON]->(dm:DIDN_Month)-[:BELONGS_TO]->(d)
  RETURN sum(toFloat(time.Hour)) AS actualHours,
         count(time) AS timeRecordCount
}
CALL {
  WITH s
  OPTIONAL MATCH (s)-[:HAS_DETAIL]->(si:Study_Info)
  RETURN head(collect(DISTINCT si.TA)) AS ta,
         head(collect(DISTINCT si.Study_Type)) AS studyType
}
CALL {
  WITH d
  OPTIONAL MATCH (d)-[rel:HAS_TLF]->(item:TLF)
  RETURN collect(DISTINCT {
    name: item.Name, category: item.Category, type: item.Type,
    source: item.Source, generation: rel.Generation, qc: rel.QC
  }) AS tlfs
}
CALL {
  WITH d
  OPTIONAL MATCH (d)-[rel:HAS_ADAM]->(item:ADaM)
  RETURN collect(DISTINCT {
    name: item.Name, category: item.Category, type: item.Type,
    generation: rel.Generation, qc: rel.QC
  }) AS adams
}
CALL {
  WITH d
  OPTIONAL MATCH (d)-[rel:HAS_SDTM]->(item:SDTM)
  RETURN collect(DISTINCT {
    name: item.Name, category: item.Category, type: item.Type,
    generation: rel.Generation, qc: rel.QC
  }) AS sdtms
}
RETURN p.Name AS person, d.DID AS did, s.Name AS study,
       substring(toString(d.Actual_Delivery_Date), 0, 10) AS completion_date,
       actualHours AS actual_hours,
       taskCount AS task_count,
       taskGenerationCount AS task_generation_count,
       taskQcCount AS task_qc_count,
       tlfCount AS tlf_count,
       tlfGenerationCount AS tlf_generation_count,
       tlfQcCount AS tlf_qc_count,
       adamCount AS adam_count,
       adamGenerationCount AS adam_generation_count,
       adamQcCount AS adam_qc_count,
       sdtmCount AS sdtm_count,
       sdtmGenerationCount AS sdtm_generation_count,
       sdtmQcCount AS sdtm_qc_count,
       ta, studyType AS study_type,
       d.Reporting_Event AS reporting_event,
       d.Draft_or_Final AS draft_or_final,
       tlfs, adams, sdtms,
       workOnRelCount AS work_on_rel_count,
       studyCount AS study_count,
       timeRecordCount AS time_record_count
ORDER BY completion_date, did, person
"""

PERSON_NAMES_QUERY = """
MATCH (p:Person)
WHERE p.Name IS NOT NULL
RETURN DISTINCT p.Name AS person
"""

TRAINING_PEOPLE_QUERY = """
MATCH (p:Person)-[:WORKS_ON]->(d:Delivery)
WHERE toLower(toString(d.DID_Status)) = 'completed'
  AND p.Name IS NOT NULL
RETURN DISTINCT p.Name AS person
ORDER BY person
"""

TARGET_QUERY = """
MATCH (p:Person)-[wo:WORKS_ON]->(d:Delivery)
WHERE p.Name = $person
WITH p, wo, d
WHERE toString(d.DID) = toString($did)
  AND toLower(toString(d.DID_Status)) IN ['planned', 'ongoing']
WITH p, d,
     count(wo) AS workOnRelCount,
     max(toFloat(coalesce(wo.Task_Num_Total, wo.CSR_Task_Num_Total))) AS taskCount,
     max(toFloat(coalesce(wo.Task_Num_Generation, wo.CSR_Task_Num_Generation))) AS taskGenerationCount,
     max(toFloat(coalesce(wo.Task_Num_QC, wo.CSR_Task_Num_QC))) AS taskQcCount,
     max(toFloat(coalesce(wo.TLF_Num_Total, wo.CSR_TLF_Num_Total))) AS tlfCount,
     max(toFloat(coalesce(wo.TLF_Num_Generation, wo.CSR_TLF_Num_Generation))) AS tlfGenerationCount,
     max(toFloat(coalesce(wo.TLF_Num_QC, wo.CSR_TLF_Num_QC))) AS tlfQcCount,
     max(toFloat(coalesce(wo.ADaM_Num_Total, wo.CSR_ADaM_Num_Total))) AS adamCount,
     max(toFloat(coalesce(wo.ADaM_Num_Generation, wo.CSR_ADaM_Num_Generation))) AS adamGenerationCount,
     max(toFloat(coalesce(wo.ADaM_Num_QC, wo.CSR_ADaM_Num_QC))) AS adamQcCount,
     max(toFloat(coalesce(wo.SDTM_Num_Total, wo.CSR_SDTM_Num_Total))) AS sdtmCount,
     max(toFloat(coalesce(wo.SDTM_Num_Generation, wo.CSR_SDTM_Num_Generation))) AS sdtmGenerationCount,
     max(toFloat(coalesce(wo.SDTM_Num_QC, wo.CSR_SDTM_Num_QC))) AS sdtmQcCount
OPTIONAL MATCH (s:Study)-[:HAS_DELIVERY]->(d)
WITH p, d, workOnRelCount, taskCount, taskGenerationCount, taskQcCount,
     tlfCount, tlfGenerationCount, tlfQcCount,
     adamCount, adamGenerationCount, adamQcCount,
     sdtmCount, sdtmGenerationCount, sdtmQcCount,
     head(collect(DISTINCT s)) AS s
CALL {
  WITH s
  OPTIONAL MATCH (s)-[:HAS_DETAIL]->(si:Study_Info)
  RETURN head(collect(DISTINCT si.TA)) AS ta,
         head(collect(DISTINCT si.Study_Type)) AS studyType
}
CALL {
  WITH d
  OPTIONAL MATCH (d)-[rel:HAS_TLF]->(item:TLF)
  RETURN collect(DISTINCT {
    name: item.Name, category: item.Category, type: item.Type,
    source: item.Source, generation: rel.Generation, qc: rel.QC
  }) AS tlfs
}
CALL {
  WITH d
  OPTIONAL MATCH (d)-[rel:HAS_ADAM]->(item:ADaM)
  RETURN collect(DISTINCT {
    name: item.Name, category: item.Category, type: item.Type,
    generation: rel.Generation, qc: rel.QC
  }) AS adams
}
CALL {
  WITH d
  OPTIONAL MATCH (d)-[rel:HAS_SDTM]->(item:SDTM)
  RETURN collect(DISTINCT {
    name: item.Name, category: item.Category, type: item.Type,
    generation: rel.Generation, qc: rel.QC
  }) AS sdtms
}
RETURN p.Name AS person, d.DID AS did, s.Name AS study,
       substring(toString(d.Planned_Delivery_Date), 0, 10) AS planned_date,
       taskCount AS task_count,
       taskGenerationCount AS task_generation_count,
       taskQcCount AS task_qc_count,
       tlfCount AS tlf_count,
       tlfGenerationCount AS tlf_generation_count,
       tlfQcCount AS tlf_qc_count,
       adamCount AS adam_count,
       adamGenerationCount AS adam_generation_count,
       adamQcCount AS adam_qc_count,
       sdtmCount AS sdtm_count,
       sdtmGenerationCount AS sdtm_generation_count,
       sdtmQcCount AS sdtm_qc_count,
       ta, studyType AS study_type,
       d.Reporting_Event AS reporting_event,
       d.Draft_or_Final AS draft_or_final,
       tlfs, adams, sdtms,
       workOnRelCount AS work_on_rel_count
"""

ONGOING_ASSIGNMENTS_QUERY = """
MATCH (p:Person)-[:WORKS_ON]->(d:Delivery)
WHERE toLower(toString(d.DID_Status)) = 'ongoing'
  AND p.Name IS NOT NULL
  AND d.DID IS NOT NULL
RETURN DISTINCT p.Name AS person, d.DID AS did
ORDER BY did, person
"""


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _read_query(query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    load_env()
    driver = get_driver()
    try:
        database = __import__("os").environ.get("NEO4J_DATABASE", "neo4j")
        with driver.session(database=database) as session:
            return session.execute_read(
                lambda tx: [record.data() for record in tx.run(query, parameters or {})]
            )
    finally:
        driver.close()


def load_training_records() -> list[dict[str, Any]]:
    """Load completed Person x DID records in small, independent transactions."""
    people = [
        row["person"]
        for row in _read_query(TRAINING_PEOPLE_QUERY)
        if row.get("person")
    ]
    records: list[dict[str, Any]] = []
    for person in people:
        records.extend(
            _normalize_record(row)
            for row in _read_query(TRAINING_QUERY, {"person": person})
        )
    return records


def _name_tokens(value: Any) -> frozenset[str]:
    return frozenset(re.findall(r"[A-Z0-9]+", str(value or "").upper()))


def _select_person_name(person: str, candidates: Iterable[str]) -> str:
    """Resolve harmless punctuation, ordering, and parenthesized-alias differences."""
    requested_normalized = _normalized_name(person)
    requested_tokens = _name_tokens(person)
    matches = [
        candidate
        for candidate in candidates
        if isinstance(candidate, str) and candidate.strip()
    ]
    exact = [
        candidate
        for candidate in matches
        if _normalized_name(candidate) == requested_normalized
    ]
    if len(exact) == 1:
        return exact[0]
    token_exact = [
        candidate for candidate in matches if _name_tokens(candidate) == requested_tokens
    ]
    if len(token_exact) == 1:
        return token_exact[0]
    alias_matches = [
        candidate
        for candidate in matches
        if requested_tokens and requested_tokens < _name_tokens(candidate)
    ]
    if len(alias_matches) == 1:
        return alias_matches[0]
    if len(alias_matches) > 1 or len(exact) > 1 or len(token_exact) > 1:
        options = sorted(set(alias_matches or token_exact or exact))
        raise ValueError(
            f"Person name {person!r} is ambiguous. Please use one of: "
            f"{', '.join(options[:10])}."
        )
    raise ValueError(f"No Person record matches {person!r}.")


@lru_cache(maxsize=1)
def _available_person_names() -> tuple[str, ...]:
    return tuple(
        str(row["person"])
        for row in _read_query(PERSON_NAMES_QUERY)
        if row.get("person")
    )


def resolve_person_name(person: str) -> str:
    """Return the unique Neo4j Person.Name matching a flexible user input."""
    return _select_person_name(person, _available_person_names())


def person_name_candidates(query: str, limit: int = 12) -> list[str]:
    """Return likely official Person.Name values for constrained LLM selection."""
    normalized_query = _normalized_name(query)
    if not normalized_query:
        return []

    def score(candidate: str) -> float:
        normalized_candidate = _normalized_name(candidate)
        sequence_score = SequenceMatcher(
            None, normalized_query, normalized_candidate
        ).ratio()
        if normalized_query in normalized_candidate:
            sequence_score += 1.0
        return sequence_score

    ranked = sorted(
        ((score(candidate), candidate) for candidate in _available_person_names()),
        key=lambda item: (-item[0], item[1]),
    )
    return [candidate for score, candidate in ranked[:limit] if score >= 0.35]


def load_target_record(person: str, did: str) -> dict[str, Any]:
    """Load one planned or ongoing Person x DID record."""
    resolved_person = resolve_person_name(person)
    return _load_target_record_for_exact_person(resolved_person, did)


def _load_target_record_for_exact_person(person: str, did: str) -> dict[str, Any]:
    """Load one target for an exact Person.Name value obtained from Neo4j."""
    rows = _read_query(TARGET_QUERY, {"person": person, "did": did})
    if not rows:
        raise ValueError(
            "No Planned/Ongoing WORKS_ON record found for "
            f"person={person!r}, DID={did!r}."
        )
    if len(rows) > 1:
        raise ValueError(f"Expected one target record, found {len(rows)}.")
    record = _normalize_record(rows[0])
    if record.get("work_on_rel_count") != 1:
        raise ValueError("Target has duplicate WORKS_ON relationships.")
    return record


def _number(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected a numeric value, got {value!r}.") from exc
    if not math.isfinite(result):
        raise ValueError(f"Expected a finite numeric value, got {value!r}.")
    return result


def _normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    for field in TASK_FIELDS:
        normalized[field] = _number(record.get(field))
    if "actual_hours" in record and record.get("actual_hours") is not None:
        normalized["actual_hours"] = _number(record["actual_hours"])
    for kind in ("tlfs", "adams", "sdtms"):
        normalized[kind] = [
            dict(item) for item in (record.get(kind) or []) if item and item.get("name")
        ]
    return normalized


def quality_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return blocking and warning-level data quality findings."""
    key_counts: dict[tuple[str, str], int] = {}
    for row in records:
        key = (str(row.get("person") or ""), str(row.get("did") or ""))
        key_counts[key] = key_counts.get(key, 0) + 1

    duplicate_keys = [
        {"person": person, "did": did, "count": count}
        for (person, did), count in key_counts.items()
        if count > 1
    ]
    return {
        "record_count": len(records),
        "unique_people": len({row.get("person") for row in records if row.get("person")}),
        "unique_dids": len({row.get("did") for row in records if row.get("did")}),
        "missing_completion_date": sum(not row.get("completion_date") for row in records),
        "missing_actual_hours": sum(row.get("actual_hours") is None for row in records),
        "non_positive_actual_hours": sum(
            row.get("actual_hours") is not None and row["actual_hours"] <= 0
            for row in records
        ),
        "duplicate_person_did": duplicate_keys,
        "duplicate_work_on_relationships": sum(
            _number(row.get("work_on_rel_count")) != 1 for row in records
        ),
        "multiple_studies": sum(_number(row.get("study_count")) > 1 for row in records),
        "no_time_records": sum(_number(row.get("time_record_count")) == 0 for row in records),
        "negative_task_counts": sum(
            any(_number(row.get(field)) < 0 for field in TASK_FIELDS) for row in records
        ),
    }


def clean_training_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apply explicit eligibility rules for model training."""
    cleaned = []
    for row in records:
        if not row.get("person") or not row.get("did") or not row.get("completion_date"):
            continue
        if row.get("actual_hours") is None or _number(row["actual_hours"]) <= 0:
            continue
        if _number(row.get("work_on_rel_count", 1)) != 1:
            continue
        if _number(row.get("study_count", 1)) > 1:
            continue
        try:
            datetime.fromisoformat(str(row["completion_date"])[:10])
        except ValueError:
            continue
        cleaned.append(_normalize_record(row))
    return cleaned


def _normalized_name(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def _assignment_matches(value: Any, person: str) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, (list, tuple, set)):
        return any(_assignment_matches(item, person) for item in value)
    return _normalized_name(value) == _normalized_name(person)


def _person_items(record: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    person = str(record.get("person") or "")
    items = [item for item in (record.get(kind) or []) if item.get("name")]
    assigned = [
        item
        for item in items
        if _assignment_matches(item.get("generation"), person)
        or _assignment_matches(item.get("qc"), person)
    ]
    return assigned or items


def _item_set(record: dict[str, Any], kind: str) -> set[str]:
    return {
        _normalized_name(item.get("name"))
        for item in _person_items(record, kind)
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def _normalized_title(value: Any) -> str:
    text = re.sub(r"[_/\\|]+", " ", str(value or "").lower())
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


@lru_cache(maxsize=50000)
def _title_vector(title: str) -> Any:
    return TITLE_VECTORIZER.transform([title])


def _title_similarity(left: Any, right: Any) -> float:
    left_title = _normalized_title(left)
    right_title = _normalized_title(right)
    if not left_title or not right_title:
        return 0.0
    if left_title == right_title:
        return 1.0
    return float(_title_vector(left_title).multiply(_title_vector(right_title)).sum())


def _metadata_equal(left: Any, right: Any) -> bool:
    return bool(left and right and _normalized_name(left) == _normalized_name(right))


def _tlf_item_similarity(
    left: dict[str, Any], right: dict[str, Any]
) -> float:
    weighted_score = 0.8 * _title_similarity(left.get("name"), right.get("name"))
    available_weight = 0.8
    for field in ("type", "source"):
        if left.get(field) and right.get(field):
            available_weight += 0.1
            if _metadata_equal(left.get(field), right.get(field)):
                weighted_score += 0.1
    return weighted_score / available_weight


def _tlf_semantic_similarity(
    left_items: list[dict[str, Any]],
    right_items: list[dict[str, Any]],
) -> tuple[float, float]:
    """Return one-to-one title similarity and target-title coverage."""
    if not left_items or not right_items:
        return 0.0, 0.0

    candidates = sorted(
        (
            (_tlf_item_similarity(left, right), left_index, right_index)
            for left_index, left in enumerate(left_items)
            for right_index, right in enumerate(right_items)
        ),
        reverse=True,
    )
    used_left: set[int] = set()
    used_right: set[int] = set()
    matched_scores = []
    for score, left_index, right_index in candidates:
        if score < TLF_SEMANTIC_MATCH_THRESHOLD:
            break
        if left_index in used_left or right_index in used_right:
            continue
        used_left.add(left_index)
        used_right.add(right_index)
        matched_scores.append(score)

    score = sum(matched_scores) / max(len(left_items), len(right_items))
    coverage = len(used_left) / len(left_items)
    return float(score), float(coverage)


def _tlf_items_hash(items: list[dict[str, Any]]) -> str:
    signature = sorted(
        (
            _normalized_title(item.get("name")),
            _normalized_name(item.get("type")),
            _normalized_name(item.get("source")),
        )
        for item in items
        if item.get("name")
    )
    serialized = json.dumps(signature, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _new_similarity_cache() -> dict[str, Any]:
    return {
        "version": SIMILARITY_CACHE_VERSION,
        "entries": {},
        "hits": 0,
        "misses": 0,
        "candidate_pairs": 0,
        "skipped_history_pairs": 0,
    }


def _load_similarity_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _new_similarity_cache()
    payload = joblib.load(path)
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), dict):
        raise ValueError(f"Invalid similarity cache format: {path.resolve()}")
    if payload.get("version") != SIMILARITY_CACHE_VERSION:
        return _new_similarity_cache()
    cache = _new_similarity_cache()
    cache["entries"] = payload["entries"]
    return cache


def _save_similarity_cache(cache: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    joblib.dump(
        {
            "version": SIMILARITY_CACHE_VERSION,
            "entries": cache["entries"],
        },
        temporary_path,
    )
    temporary_path.replace(path)


def _is_lfs_pointer(path: Path) -> bool:
    with path.open("rb") as artifact_file:
        return artifact_file.read(len(LFS_POINTER_PREFIX)) == LFS_POINTER_PREFIX


def _prediction_artifact_cache_dir() -> Path:
    configured = os.environ.get("DID_EFFORT_ARTIFACT_CACHE_DIR")
    cache_dir = (
        Path(configured)
        if configured
        else Path(tempfile.gettempdir()) / "did_qa_effort_artifacts"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _download_prediction_artifact(url: str, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.with_suffix(destination.suffix + ".download")
    headers = {"User-Agent": "did-qa-effort-prediction"}
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    try:
        with urlopen(Request(url, headers=headers), timeout=60) as response:
            with temporary_path.open("wb") as artifact_file:
                while chunk := response.read(1024 * 1024):
                    artifact_file.write(chunk)
        if _is_lfs_pointer(temporary_path):
            raise ValueError(
                f"GitHub returned an LFS pointer instead of artifact data from {url}."
            )
        temporary_path.replace(destination)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
    return destination


def _resolve_prediction_artifact(
    path: Path, default_path: Path, url_environment_variable: str, default_url: str
) -> Path:
    resolved_path = path.resolve()
    if resolved_path.exists() and not _is_lfs_pointer(resolved_path):
        return resolved_path
    if resolved_path != default_path.resolve():
        raise FileNotFoundError(f"Effort prediction artifact not found: {resolved_path}.")
    cached_path = _prediction_artifact_cache_dir() / default_path.name
    if cached_path.exists() and not _is_lfs_pointer(cached_path):
        return cached_path
    return _download_prediction_artifact(
        os.environ.get(url_environment_variable, default_url), cached_path
    )


@lru_cache(maxsize=2)
def _load_prediction_similarity_cache(
    path_string: str, modified_at_ns: int
) -> dict[str, Any]:
    return _load_similarity_cache(Path(path_string))


def _cached_tlf_semantic_similarity(
    left_items: list[dict[str, Any]],
    right_items: list[dict[str, Any]],
    cache: dict[str, Any] | None,
) -> tuple[float, float]:
    if cache is None:
        return _tlf_semantic_similarity(left_items, right_items)
    key = f"{_tlf_items_hash(left_items)}:{_tlf_items_hash(right_items)}"
    cached = cache["entries"].get(key)
    if cached is not None:
        cache["hits"] += 1
        return float(cached[0]), float(cached[1])
    result = _tlf_semantic_similarity(left_items, right_items)
    cache["entries"][key] = result
    cache["misses"] += 1
    return result


def _as_date(value: Any) -> date:
    return datetime.fromisoformat(str(value)[:10]).date()


def _safe_median(values: Iterable[float]) -> float:
    values = list(values)
    return float(median(values)) if values else 0.0


def _safe_mean(values: Iterable[float]) -> float:
    values = list(values)
    return float(sum(values) / len(values)) if values else 0.0


def _record_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("person") or ""),
        str(record.get("did") or ""),
        str(record.get("completion_date") or ""),
    )


def _similarity_candidates(
    target: dict[str, Any], person_history: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Keep high-value and recent history before expensive TLF title matching."""
    newest_first = sorted(
        person_history,
        key=lambda row: (_as_date(row["completion_date"]), str(row.get("did") or "")),
        reverse=True,
    )
    selected: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add(rows: Iterable[dict[str, Any]], limit: int) -> None:
        for row in list(rows)[:limit]:
            selected[_record_key(row)] = row

    add(newest_first, RECENT_CANDIDATE_LIMIT)

    target_study = _normalized_name(target.get("study"))
    if target_study:
        add(
            (
                row
                for row in newest_first
                if _normalized_name(row.get("study")) == target_study
            ),
            SAME_STUDY_CANDIDATE_LIMIT,
        )

    target_ta = _normalized_name(target.get("ta"))
    if target_ta:
        add(
            (
                row
                for row in newest_first
                if _normalized_name(row.get("ta")) == target_ta
            ),
            SAME_TA_CANDIDATE_LIMIT,
        )

    target_sets = {
        kind: _item_set(target, kind) for kind in ("tlfs", "adams", "sdtms")
    }
    add(
        (
            row
            for row in newest_first
            if any(
                target_sets[kind] & _item_set(row, kind)
                for kind in ("tlfs", "adams", "sdtms")
            )
        ),
        EXACT_OVERLAP_CANDIDATE_LIMIT,
    )
    return sorted(
        selected.values(),
        key=lambda row: (_as_date(row["completion_date"]), str(row.get("did") or "")),
    )


def _weighted_mean(
    similarities: list[dict[str, Any]], value_getter: Any
) -> float:
    weighted = [
        (item["combined_similarity"], value_getter(item))
        for item in similarities
        if item["combined_similarity"] >= TLF_SEMANTIC_MATCH_THRESHOLD
    ]
    valid = [(weight, value) for weight, value in weighted if value is not None]
    total_weight = sum(weight for weight, _ in valid)
    return (
        float(sum(weight * float(value) for weight, value in valid) / total_weight)
        if total_weight
        else 0.0
    )


def _similar_hours_trend(similarities: list[dict[str, Any]]) -> float:
    repeated = sorted(
        (
            item
            for item in similarities
            if item["combined_similarity"] >= TLF_SEMANTIC_MATCH_THRESHOLD
        ),
        key=lambda item: (_as_date(item["completion_date"]), str(item.get("did") or "")),
    )
    if len(repeated) < 2:
        return 0.0
    hours = [_number(item["actual_hours"]) for item in repeated]
    x_mean = (len(hours) - 1) / 2
    y_mean = sum(hours) / len(hours)
    denominator = sum((index - x_mean) ** 2 for index in range(len(hours)))
    return float(
        sum(
            (index - x_mean) * (value - y_mean)
            for index, value in enumerate(hours)
        )
        / denominator
    )


def build_feature_row(
    target: dict[str, Any],
    history: list[dict[str, Any]],
    similarity_cache: dict[str, Any] | None = None,
    *,
    eligible_history: list[dict[str, Any]] | None = None,
    person_history_override: list[dict[str, Any]] | None = None,
    global_statistics: dict[str, float] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build time-safe features and return the most similar personal history."""
    target_date_value = target.get("completion_date") or target.get("as_of_date")
    target_date = _as_date(target_date_value) if target_date_value else date.today()
    eligible = (
        eligible_history
        if eligible_history is not None
        else [
            row
            for row in history
            if row.get("completion_date")
            and _as_date(row["completion_date"]) < target_date
        ]
    )
    person_history = (
        person_history_override
        if person_history_override is not None
        else [
            row
            for row in eligible
            if _normalized_name(row.get("person"))
            == _normalized_name(target.get("person"))
        ]
    )
    candidate_history = _similarity_candidates(target, person_history)
    if similarity_cache is not None:
        similarity_cache["candidate_pairs"] += len(candidate_history)
        similarity_cache["skipped_history_pairs"] += (
            len(person_history) - len(candidate_history)
        )

    if global_statistics is None:
        global_hours = [_number(row["actual_hours"]) for row in eligible]
        global_rates = [
            _number(row["actual_hours"]) / _number(row["task_count"])
            for row in eligible
            if _number(row.get("task_count")) > 0
        ]
        global_statistics = {
            "completed_count": float(len(eligible)),
            "median_hours": _safe_median(global_hours),
            "median_hours_per_task": _safe_median(global_rates),
        }
    person_hours = [_number(row["actual_hours"]) for row in person_history]
    person_rates = [
        _number(row["actual_hours"]) / _number(row["task_count"])
        for row in person_history
        if _number(row.get("task_count")) > 0
    ]

    target_sets = {kind: _item_set(target, kind) for kind in ("tlfs", "adams", "sdtms")}
    target_tlf_items = _person_items(target, "tlfs")
    historical_union = {
        kind: set().union(*(_item_set(row, kind) for row in person_history))
        if person_history
        else set()
        for kind in ("tlfs", "adams", "sdtms")
    }

    similarities = []
    for row in candidate_history:
        semantic_tlf_similarity, semantic_tlf_coverage = _cached_tlf_semantic_similarity(
            target_tlf_items,
            _person_items(row, "tlfs"),
            similarity_cache,
        )
        scores = {
            kind: _jaccard(target_sets[kind], _item_set(row, kind))
            for kind in ("tlfs", "adams", "sdtms")
        }
        non_empty_scores = [
            score
            for kind, score in scores.items()
            if target_sets[kind] or _item_set(row, kind)
        ]
        similarities.append(
            {
                "did": row.get("did"),
                "study": row.get("study"),
                "completion_date": row.get("completion_date"),
                "actual_hours": row.get("actual_hours"),
                "task_count": row.get("task_count"),
                "tlf_similarity": scores["tlfs"],
                "tlf_semantic_similarity": semantic_tlf_similarity,
                "tlf_semantic_coverage": semantic_tlf_coverage,
                "adam_similarity": scores["adams"],
                "sdtm_similarity": scores["sdtms"],
                "overall_similarity": (
                    sum(non_empty_scores) / len(non_empty_scores)
                    if non_empty_scores
                    else 0.0
                ),
            }
        )
        similarities[-1]["combined_similarity"] = (
            similarities[-1]["overall_similarity"]
            + similarities[-1]["tlf_semantic_similarity"]
        ) / 2
    similarities.sort(key=lambda item: item["combined_similarity"], reverse=True)
    best = similarities[0] if similarities else None
    repeated_similarities = [
        item
        for item in similarities
        if item["combined_similarity"] >= TLF_SEMANTIC_MATCH_THRESHOLD
    ]
    latest_similar = max(
        repeated_similarities,
        key=lambda item: (_as_date(item["completion_date"]), str(item.get("did") or "")),
        default=None,
    )

    feature = {field: _number(target.get(field)) for field in TASK_FIELDS}
    prior_overlap_counts = {
        kind: len(target_sets[kind] & historical_union[kind])
        for kind in ("tlfs", "adams", "sdtms")
    }
    prior_coverages = {
        kind: (
            prior_overlap_counts[kind] / len(target_sets[kind])
            if target_sets[kind]
            else 0.0
        )
        for kind in ("tlfs", "adams", "sdtms")
    }
    available_prior_coverages = [
        prior_coverages[kind]
        for kind in ("tlfs", "adams", "sdtms")
        if target_sets[kind]
    ]
    feature.update(
        {
            "person_completed_count": float(len(person_history)),
            "person_median_hours": _safe_median(person_hours),
            "person_recent_median_hours": _safe_median(person_hours[-5:]),
            "person_median_hours_per_task": _safe_median(person_rates),
            "global_completed_count": global_statistics["completed_count"],
            "global_median_hours": global_statistics["median_hours"],
            "global_median_hours_per_task": global_statistics[
                "median_hours_per_task"
            ],
            "tlf_prior_overlap_count": float(prior_overlap_counts["tlfs"]),
            "adam_prior_overlap_count": float(prior_overlap_counts["adams"]),
            "sdtm_prior_overlap_count": float(prior_overlap_counts["sdtms"]),
            "tlf_prior_coverage": prior_coverages["tlfs"],
            "adam_prior_coverage": prior_coverages["adams"],
            "sdtm_prior_coverage": prior_coverages["sdtms"],
            "overall_prior_coverage": _safe_mean(available_prior_coverages),
            "tlf_unseen_count": float(
                len(target_sets["tlfs"]) - prior_overlap_counts["tlfs"]
            ),
            "adam_unseen_count": float(
                len(target_sets["adams"]) - prior_overlap_counts["adams"]
            ),
            "sdtm_unseen_count": float(
                len(target_sets["sdtms"]) - prior_overlap_counts["sdtms"]
            ),
            "max_tlf_similarity": max(
                (item["tlf_similarity"] for item in similarities), default=0.0
            ),
            "max_tlf_semantic_similarity": max(
                (item["tlf_semantic_similarity"] for item in similarities),
                default=0.0,
            ),
            "max_tlf_semantic_coverage": max(
                (item["tlf_semantic_coverage"] for item in similarities),
                default=0.0,
            ),
            "max_adam_similarity": max(
                (item["adam_similarity"] for item in similarities), default=0.0
            ),
            "max_sdtm_similarity": max(
                (item["sdtm_similarity"] for item in similarities), default=0.0
            ),
            "max_overall_similarity": max(
                (item["overall_similarity"] for item in similarities),
                default=0.0,
            ),
            "max_combined_similarity": (
                best["combined_similarity"] if best else 0.0
            ),
            "top3_combined_similarity_mean": _safe_mean(
                item["combined_similarity"] for item in similarities[:3]
            ),
            "top5_combined_similarity_mean": _safe_mean(
                item["combined_similarity"] for item in similarities[:5]
            ),
            "similar_did_count_ge_70": float(len(repeated_similarities)),
            "similar_did_count_ge_85": float(
                sum(
                    item["combined_similarity"] >= 0.85
                    for item in similarities
                )
            ),
            "weighted_similar_hours": _weighted_mean(
                similarities, lambda item: _number(item["actual_hours"])
            ),
            "weighted_similar_hours_per_task": _weighted_mean(
                similarities,
                lambda item: (
                    _number(item["actual_hours"]) / _number(item["task_count"])
                    if _number(item.get("task_count")) > 0
                    else None
                ),
            ),
            "latest_similar_hours": (
                _number(latest_similar["actual_hours"]) if latest_similar else 0.0
            ),
            "similar_hours_trend": _similar_hours_trend(similarities),
            "days_since_similar_work": float(
                (target_date - _as_date(best["completion_date"])).days
                if best and best["combined_similarity"] > 0
                else 3650
            ),
            "ta": str(target.get("ta") or "UNKNOWN"),
            "study_type": str(target.get("study_type") or "UNKNOWN"),
            "reporting_event": str(target.get("reporting_event") or "UNKNOWN"),
            "draft_or_final": str(target.get("draft_or_final") or "UNKNOWN"),
        }
    )
    return feature, similarities[:5]


def build_training_features(
    records: list[dict[str, Any]],
    similarity_cache: dict[str, Any] | None = None,
    similarity_cache_path: Path | None = None,
    show_progress: bool = False,
) -> tuple[list[dict[str, Any]], np.ndarray]:
    ordered = sorted(records, key=lambda row: (row["completion_date"], str(row["did"])))
    features = []
    labels = []
    total = len(ordered)
    eligible_history: list[dict[str, Any]] = []
    person_histories: dict[str, list[dict[str, Any]]] = {}
    processed = 0
    for _, same_day_rows in groupby(
        ordered, key=lambda row: str(row["completion_date"])[:10]
    ):
        day_rows = list(same_day_rows)
        global_hours = [_number(row["actual_hours"]) for row in eligible_history]
        global_rates = [
            _number(row["actual_hours"]) / _number(row["task_count"])
            for row in eligible_history
            if _number(row.get("task_count")) > 0
        ]
        global_statistics = {
            "completed_count": float(len(eligible_history)),
            "median_hours": _safe_median(global_hours),
            "median_hours_per_task": _safe_median(global_rates),
        }
        for row in day_rows:
            person_key = _normalized_name(row.get("person"))
            feature, _ = build_feature_row(
                row,
                [],
                similarity_cache,
                eligible_history=eligible_history,
                person_history_override=person_histories.get(person_key, []),
                global_statistics=global_statistics,
            )
            features.append(feature)
            labels.append(_number(row["actual_hours"]))
            processed += 1
            if show_progress and (
                processed % PROGRESS_INTERVAL == 0 or processed == total
            ):
                stats = similarity_cache or _new_similarity_cache()
                print(
                    "Feature progress: "
                    f"{processed}/{total} records; "
                    f"cache hits={stats['hits']}, misses={stats['misses']}; "
                    f"candidate pairs={stats['candidate_pairs']}, "
                    f"skipped={stats['skipped_history_pairs']}",
                    file=sys.stderr,
                    flush=True,
                )
            if (
                similarity_cache is not None
                and similarity_cache_path is not None
                and processed % CACHE_CHECKPOINT_INTERVAL == 0
            ):
                _save_similarity_cache(similarity_cache, similarity_cache_path)
        eligible_history.extend(day_rows)
        for row in day_rows:
            person_key = _normalized_name(row.get("person"))
            person_histories.setdefault(person_key, []).append(row)
    return features, np.asarray(labels, dtype=float)


def _matrix(features: list[dict[str, Any]]) -> list[list[Any]]:
    columns = NUMERIC_FEATURES + CATEGORICAL_FEATURES
    return [[feature.get(column) for column in columns] for feature in features]


def _pipeline() -> Pipeline:
    numeric_indices = list(range(len(NUMERIC_FEATURES)))
    categorical_indices = list(
        range(len(NUMERIC_FEATURES), len(NUMERIC_FEATURES) + len(CATEGORICAL_FEATURES))
    )
    preprocessing = ColumnTransformer(
        [
            (
                "numeric",
                Pipeline(
                    [
                        ("imputer", SimpleImputer(strategy="median")),
                        ("scale", StandardScaler()),
                    ]
                ),
                numeric_indices,
            ),
            (
                "categorical",
                OneHotEncoder(handle_unknown="ignore"),
                categorical_indices,
            ),
        ]
    )
    return Pipeline([("preprocess", preprocessing), ("regressor", Ridge(alpha=1.0))])


def _grouped_time_split(
    records: list[dict[str, Any]],
) -> tuple[set[str], set[str], set[str]]:
    did_dates: dict[str, date] = {}
    for row in records:
        did = str(row["did"])
        completion = _as_date(row["completion_date"])
        did_dates[did] = max(did_dates.get(did, completion), completion)
    ordered = sorted(did_dates, key=lambda did: (did_dates[did], did))
    if len(ordered) < 6:
        raise ValueError("At least 6 completed DIDs are required for a grouped time split.")
    train_end = max(1, int(len(ordered) * 0.70))
    calibration_end = max(train_end + 1, int(len(ordered) * 0.85))
    calibration_end = min(calibration_end, len(ordered) - 1)
    return (
        set(ordered[:train_end]),
        set(ordered[train_end:calibration_end]),
        set(ordered[calibration_end:]),
    )


def _predict_hours(model: Pipeline, features: list[dict[str, Any]]) -> np.ndarray:
    return np.maximum(0.0, np.expm1(model.predict(_matrix(features))))


def _history_baseline_predictions(
    features: list[dict[str, Any]],
) -> np.ndarray:
    return np.asarray(
        [
            (
                _number(feature.get("person_median_hours"))
                if _number(feature.get("person_completed_count")) > 0
                and _number(feature.get("person_median_hours")) > 0
                else _number(feature.get("global_median_hours"))
            )
            for feature in features
        ],
        dtype=float,
    )


def _apply_prediction_policy(
    ridge_predictions: np.ndarray,
    features: list[dict[str, Any]],
    policy: dict[str, Any],
) -> np.ndarray:
    baseline_predictions = _history_baseline_predictions(features)
    ridge_weight = float(policy["ridge_weight"])
    predictions = (
        ridge_weight * ridge_predictions
        + (1.0 - ridge_weight) * baseline_predictions
        + float(policy["offset_hours"])
    )
    cap_hours = policy.get("cap_hours")
    if cap_hours is not None:
        predictions = np.minimum(predictions, float(cap_hours))
    return np.maximum(0.0, predictions)


def _select_prediction_policy(
    training_labels: np.ndarray,
    calibration_features: list[dict[str, Any]],
    calibration_labels: np.ndarray,
    ridge_predictions: np.ndarray,
) -> dict[str, Any]:
    """Choose a robust blend and cap on calibration data only."""
    baseline_predictions = _history_baseline_predictions(calibration_features)
    cap_candidates: list[tuple[float | None, float | None]] = [
        (quantile, float(np.quantile(training_labels, quantile)))
        for quantile in (0.99, 0.995, 0.999, 1.0)
    ]
    cap_candidates.append((None, None))
    candidates = []
    for ridge_weight in np.linspace(0.0, 1.0, 21):
        blended = (
            ridge_weight * ridge_predictions
            + (1.0 - ridge_weight) * baseline_predictions
        )
        for offset_hours in (
            0.0,
            float(np.median(calibration_labels - blended)),
        ):
            for cap_quantile, cap_hours in cap_candidates:
                policy = {
                    "ridge_weight": float(ridge_weight),
                    "baseline_weight": float(1.0 - ridge_weight),
                    "offset_hours": offset_hours,
                    "cap_quantile": cap_quantile,
                    "cap_hours": cap_hours,
                }
                predicted = _apply_prediction_policy(
                    ridge_predictions, calibration_features, policy
                )
                metrics = _metrics(calibration_labels, predicted)
                candidates.append((metrics["wape"], metrics["mae"], policy, metrics))
    _, _, selected, selected_metrics = min(
        candidates, key=lambda candidate: (candidate[0], candidate[1])
    )
    selected["calibration_metrics"] = selected_metrics
    return selected


def _policy_for_final_model(
    policy: dict[str, Any], all_labels: np.ndarray
) -> dict[str, Any]:
    final_policy = dict(policy)
    cap_quantile = final_policy.get("cap_quantile")
    final_policy["calibration_cap_hours"] = final_policy.get("cap_hours")
    final_policy["cap_hours"] = (
        float(np.quantile(all_labels, cap_quantile))
        if cap_quantile is not None
        else None
    )
    return final_policy


@lru_cache(maxsize=4)
def _load_model_artifact(path: str, modified_time_ns: int) -> dict[str, Any]:
    """Cache a model until its on-disk modification time changes."""
    del modified_time_ns
    return joblib.load(path)


def _metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    errors = predicted - actual
    return {
        "mae": float(mean_absolute_error(actual, predicted)),
        "median_ae": float(np.median(np.abs(errors))),
        "rmse": float(math.sqrt(mean_squared_error(actual, predicted))),
        "wape": float(np.abs(errors).sum() / actual.sum()) if actual.sum() else 0.0,
        "bias": float(errors.mean()),
    }


def train_model(
    records: list[dict[str, Any]],
    model_path: Path,
    minimum_records: int = 20,
    similarity_cache_path: Path | None = None,
    show_progress: bool = False,
) -> dict[str, Any]:
    """Train, time-test, calibrate upper prediction bounds, and persist the model."""
    cleaned = sorted(
        clean_training_records(records),
        key=lambda row: (row["completion_date"], str(row["did"]), str(row["person"])),
    )
    if len(cleaned) < minimum_records:
        raise ValueError(
            f"Only {len(cleaned)} eligible records; at least {minimum_records} are required."
        )
    similarity_cache = (
        _load_similarity_cache(similarity_cache_path)
        if similarity_cache_path is not None
        else None
    )
    features, labels = build_training_features(
        cleaned,
        similarity_cache=similarity_cache,
        similarity_cache_path=similarity_cache_path,
        show_progress=show_progress,
    )
    if similarity_cache is not None and similarity_cache_path is not None:
        _save_similarity_cache(similarity_cache, similarity_cache_path)
    train_dids, calibration_dids, test_dids = _grouped_time_split(cleaned)
    train_idx = [i for i, row in enumerate(cleaned) if str(row["did"]) in train_dids]
    calibration_idx = [
        i for i, row in enumerate(cleaned) if str(row["did"]) in calibration_dids
    ]
    test_idx = [i for i, row in enumerate(cleaned) if str(row["did"]) in test_dids]

    evaluation_model = _pipeline()
    evaluation_model.fit(
        _matrix([features[i] for i in train_idx]), np.log1p(labels[train_idx])
    )
    calibration_features = [features[i] for i in calibration_idx]
    raw_calibration_predictions = _predict_hours(
        evaluation_model, calibration_features
    )
    prediction_policy = _select_prediction_policy(
        labels[train_idx],
        calibration_features,
        labels[calibration_idx],
        raw_calibration_predictions,
    )
    calibration_predictions = _apply_prediction_policy(
        raw_calibration_predictions,
        calibration_features,
        prediction_policy,
    )
    calibration_residuals = labels[calibration_idx] - calibration_predictions
    upper_adjustments = {
        "p80": max(0.0, float(np.quantile(calibration_residuals, 0.80))),
        "p90": max(0.0, float(np.quantile(calibration_residuals, 0.90))),
    }
    test_features = [features[i] for i in test_idx]
    raw_test_predictions = _predict_hours(evaluation_model, test_features)
    test_predictions = _apply_prediction_policy(
        raw_test_predictions, test_features, prediction_policy
    )
    metrics = _metrics(labels[test_idx], test_predictions)
    metrics["p80_coverage"] = float(
        np.mean(labels[test_idx] <= test_predictions + upper_adjustments["p80"])
    )
    metrics["p90_coverage"] = float(
        np.mean(labels[test_idx] <= test_predictions + upper_adjustments["p90"])
    )
    benchmark_metrics = {
        "raw_ridge": _metrics(labels[test_idx], raw_test_predictions),
        "person_history_baseline": _metrics(
            labels[test_idx], _history_baseline_predictions(test_features)
        ),
        "robust_blend": dict(metrics),
    }

    final_model = _pipeline()
    final_model.fit(_matrix(features), np.log1p(labels))
    final_prediction_policy = _policy_for_final_model(prediction_policy, labels)
    artifact = {
        "model_version": MODEL_VERSION,
        "trained_at": datetime.now().astimezone().isoformat(),
        "model": final_model,
        "history": cleaned,
        "numeric_features": NUMERIC_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "upper_adjustments": upper_adjustments,
        "prediction_policy": final_prediction_policy,
        "metrics": metrics,
        "benchmark_metrics": benchmark_metrics,
        "split": {
            "train_records": len(train_idx),
            "calibration_records": len(calibration_idx),
            "test_records": len(test_idx),
            "train_dids": len(train_dids),
            "calibration_dids": len(calibration_dids),
            "test_dids": len(test_dids),
        },
    }
    model_path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, model_path)
    return {
        "model_path": str(model_path.resolve()),
        "model_version": MODEL_VERSION,
        "eligible_records": len(cleaned),
        "metrics": metrics,
        "upper_adjustments": upper_adjustments,
        "prediction_policy": final_prediction_policy,
        "benchmark_metrics": benchmark_metrics,
        "split": artifact["split"],
        "similarity_cache": (
            {
                "path": str(similarity_cache_path.resolve()),
                "entries": len(similarity_cache["entries"]),
                "hits": similarity_cache["hits"],
                "misses": similarity_cache["misses"],
                "candidate_pairs": similarity_cache["candidate_pairs"],
                "skipped_history_pairs": similarity_cache["skipped_history_pairs"],
            }
            if similarity_cache is not None and similarity_cache_path is not None
            else None
        ),
    }


def predict_record(
    target: dict[str, Any],
    model_path: Path,
    as_of_date: str | None = None,
    similarity_cache_path: Path | None = None,
) -> dict[str, Any]:
    """Predict total effort for one normalized target record."""
    resolved_model_path = model_path.resolve()
    if not resolved_model_path.exists():
        raise FileNotFoundError(
            f"Effort model not found: {resolved_model_path}. Train the model before predicting."
        )
    artifact = _load_model_artifact(
        str(resolved_model_path), resolved_model_path.stat().st_mtime_ns
    )
    if (
        artifact.get("model_version") != MODEL_VERSION
        or artifact.get("numeric_features") != NUMERIC_FEATURES
        or artifact.get("categorical_features") != CATEGORICAL_FEATURES
        or not isinstance(artifact.get("prediction_policy"), dict)
    ):
        raise ValueError(
            "The saved effort model uses an older feature schema. "
            "Retrain it with the current effort_prediction.py."
        )
    target = _normalize_record(target)
    target["as_of_date"] = as_of_date or date.today().isoformat()
    history = [
        row
        for row in artifact["history"]
        if _as_date(row["completion_date"]) < _as_date(target["as_of_date"])
    ]
    similarity_cache = (
        _load_prediction_similarity_cache(
            str(similarity_cache_path.resolve()),
            similarity_cache_path.stat().st_mtime_ns,
        )
        if similarity_cache_path is not None
        else None
    )
    feature, similar = build_feature_row(target, history, similarity_cache)
    raw_prediction = _predict_hours(artifact["model"], [feature])
    p50 = float(
        _apply_prediction_policy(
            raw_prediction, [feature], artifact["prediction_policy"]
        )[0]
    )
    adjustments = artifact["upper_adjustments"]
    warnings = []
    if feature["person_completed_count"] < 5:
        warnings.append("This person has fewer than 5 eligible completed DID records.")
    if feature["global_completed_count"] < 20:
        warnings.append("Fewer than 20 historical records precede the prediction date.")
    if not any(target.get(kind) for kind in ("tlfs", "adams", "sdtms")):
        warnings.append("No TLF/ADaM/SDTM details were available for similarity features.")
    return {
        "person": target.get("person"),
        "did": target.get("did"),
        "study": target.get("study"),
        "prediction_type": "total_hours",
        "as_of_date": target["as_of_date"],
        "p50_hours": round(p50, 1),
        "p80_hours": round(p50 + adjustments["p80"], 1),
        "p90_hours": round(p50 + adjustments["p90"], 1),
        "model_version": artifact["model_version"],
        "person_completed_did_count": int(feature["person_completed_count"]),
        "similarity_features": {
            name: feature[name]
            for name in (
                "top3_combined_similarity_mean",
                "top5_combined_similarity_mean",
                "similar_did_count_ge_70",
                "similar_did_count_ge_85",
                "weighted_similar_hours",
                "weighted_similar_hours_per_task",
                "latest_similar_hours",
                "similar_hours_trend",
                "tlf_prior_coverage",
                "adam_prior_coverage",
                "sdtm_prior_coverage",
                "overall_prior_coverage",
                "tlf_unseen_count",
                "adam_unseen_count",
                "sdtm_unseen_count",
            )
        },
        "prediction_policy": {
            "ridge_weight": artifact["prediction_policy"]["ridge_weight"],
            "baseline_weight": artifact["prediction_policy"]["baseline_weight"],
            "cap_hours": artifact["prediction_policy"]["cap_hours"],
        },
        "similar_historical_dids": similar,
        "warnings": warnings,
    }


def predict_effort(
    person: str,
    did: str,
    model_path: Path = DEFAULT_MODEL_PATH,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Load a target from Neo4j and forecast it; intended for Agent tool wiring."""
    resolved_model_path = _resolve_prediction_artifact(
        model_path,
        DEFAULT_MODEL_PATH,
        "DID_EFFORT_MODEL_URL",
        DEFAULT_MODEL_URL,
    )
    resolved_similarity_cache_path = _resolve_prediction_artifact(
        DEFAULT_SIMILARITY_CACHE_PATH,
        DEFAULT_SIMILARITY_CACHE_PATH,
        "DID_EFFORT_SIMILARITY_CACHE_URL",
        DEFAULT_SIMILARITY_CACHE_URL,
    )
    return predict_record(
        load_target_record(person, did),
        model_path=resolved_model_path,
        as_of_date=as_of_date,
        similarity_cache_path=resolved_similarity_cache_path,
    )


def load_ongoing_assignments() -> list[dict[str, str]]:
    """Return the assigned Person x DID pairs that are currently ongoing."""
    return [
        {"person": str(row["person"]), "did": str(row["did"])}
        for row in _read_query(ONGOING_ASSIGNMENTS_QUERY)
        if row.get("person") and row.get("did")
    ]


def export_ongoing_predictions(
    output_path: Path,
    model_path: Path = DEFAULT_MODEL_PATH,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Write a point-in-time CSV forecast for every assigned ongoing DID."""
    prediction_date = as_of_date or date.today().isoformat()
    generated_at = datetime.now().astimezone().isoformat()
    resolved_model_path = _resolve_prediction_artifact(
        model_path,
        DEFAULT_MODEL_PATH,
        "DID_EFFORT_MODEL_URL",
        DEFAULT_MODEL_URL,
    )
    resolved_similarity_cache_path = _resolve_prediction_artifact(
        DEFAULT_SIMILARITY_CACHE_PATH,
        DEFAULT_SIMILARITY_CACHE_PATH,
        "DID_EFFORT_SIMILARITY_CACHE_URL",
        DEFAULT_SIMILARITY_CACHE_URL,
    )
    cache_modified_at_ns = resolved_similarity_cache_path.stat().st_mtime_ns
    similarity_cache = _load_prediction_similarity_cache(
        str(resolved_similarity_cache_path), cache_modified_at_ns
    )
    fieldnames = [
        "predicted_at",
        "as_of_date",
        "model_version",
        "person",
        "did",
        "study",
        "planned_date",
        "p50_hours",
        "p80_hours",
        "p90_hours",
        "person_completed_did_count",
        "similar_did_count_ge_70",
        "similar_did_count_ge_85",
        "overall_prior_coverage",
        "warnings",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    assignments = load_ongoing_assignments()
    with output_path.open("w", encoding="utf-8-sig", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fieldnames)
        writer.writeheader()
        for assignment in assignments:
            target = _load_target_record_for_exact_person(
                assignment["person"], assignment["did"]
            )
            prediction = predict_record(
                target,
                model_path=resolved_model_path,
                as_of_date=prediction_date,
                similarity_cache_path=resolved_similarity_cache_path,
            )
            similarity = prediction["similarity_features"]
            writer.writerow(
                {
                    "predicted_at": generated_at,
                    "as_of_date": prediction["as_of_date"],
                    "model_version": prediction["model_version"],
                    "person": prediction["person"],
                    "did": prediction["did"],
                    "study": prediction["study"],
                    "planned_date": target.get("planned_date"),
                    "p50_hours": prediction["p50_hours"],
                    "p80_hours": prediction["p80_hours"],
                    "p90_hours": prediction["p90_hours"],
                    "person_completed_did_count": prediction[
                        "person_completed_did_count"
                    ],
                    "similar_did_count_ge_70": similarity[
                        "similar_did_count_ge_70"
                    ],
                    "similar_did_count_ge_85": similarity[
                        "similar_did_count_ge_85"
                    ],
                    "overall_prior_coverage": similarity[
                        "overall_prior_coverage"
                    ],
                    "warnings": " | ".join(prediction["warnings"]),
                }
            )
    _save_similarity_cache(similarity_cache, resolved_similarity_cache_path)
    _load_prediction_similarity_cache.cache_clear()
    return {
        "output": str(output_path.resolve()),
        "model_version": MODEL_VERSION,
        "as_of_date": prediction_date,
        "generated_at": generated_at,
        "ongoing_assignments": len(assignments),
        "similarity_cache": {
            "path": str(resolved_similarity_cache_path),
            "entries": len(similarity_cache["entries"]),
            "hits": similarity_cache["hits"],
            "misses": similarity_cache["misses"],
        },
    }


def _load_json_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("Input JSON must be a list or an object containing a records list.")
    return [_normalize_record(record) for record in records]


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    extract_parser = subparsers.add_parser("extract", help="Export completed DID records.")
    extract_parser.add_argument("--output", type=Path, required=True)

    train_parser = subparsers.add_parser("train", help="Train and save the effort model.")
    train_parser.add_argument("--input", type=Path, help="Extract JSON; omit to query Neo4j.")
    train_parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    train_parser.add_argument(
        "--cache", type=Path, default=DEFAULT_SIMILARITY_CACHE_PATH
    )
    train_parser.add_argument("--minimum-records", type=int, default=20)

    predict_parser = subparsers.add_parser(
        "predict", help="Predict a planned or ongoing Person x DID."
    )
    predict_parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    predict_parser.add_argument("--person", required=True)
    predict_parser.add_argument("--did", required=True)
    predict_parser.add_argument("--as-of-date")

    export_ongoing_parser = subparsers.add_parser(
        "export-ongoing",
        help="Export V3 forecasts for every assigned ongoing Person x DID.",
    )
    export_ongoing_parser.add_argument("--output", type=Path, required=True)
    export_ongoing_parser.add_argument("--model", type=Path, default=DEFAULT_MODEL_PATH)
    export_ongoing_parser.add_argument("--as-of-date")

    args = parser.parse_args()
    if args.command == "extract":
        records = load_training_records()
        payload = {
            "extracted_at": datetime.now().astimezone().isoformat(),
            "quality": quality_report(records),
            "records": records,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
            encoding="utf-8",
        )
        _print_json({"output": str(args.output.resolve()), "quality": payload["quality"]})
    elif args.command == "train":
        records = _load_json_records(args.input) if args.input else load_training_records()
        _print_json(
            train_model(
                records,
                args.model,
                args.minimum_records,
                similarity_cache_path=args.cache,
                show_progress=True,
            )
        )
    elif args.command == "predict":
        _print_json(
            predict_effort(args.person, args.did, args.model, args.as_of_date)
        )
    else:
        _print_json(
            export_ongoing_predictions(args.output, args.model, args.as_of_date)
        )


if __name__ == "__main__":
    main()
