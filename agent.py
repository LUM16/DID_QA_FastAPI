"""Natural-language Neo4j Q&A agent (RSC edition)."""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from effort_prediction import person_name_candidates, predict_effort
from example_memory import format_positive_examples, get_memory
from neo4j_client import (
    expand_legacy_task_properties,
    get_schema,
    last_query_meta,
    load_env,
    run_cypher,
)
from result_presentation import select_result_presentation
from vox_client import add_usage, chat as _chat, empty_usage

log = logging.getLogger(__name__)

CYPHER_BLOCK = re.compile(r"```(?:cypher)?\s*([\s\S]*?)```", re.IGNORECASE)
APP_ROOT = Path(__file__).resolve().parent
DOCS_ROOT = APP_ROOT / "docs"
EXAMPLES_ROOT = DOCS_ROOT / "examples"

EXAMPLE_KEYWORDS = {
    "person_productivity.md": (
        "person",
        "productivity",
        "hands-on",
        "hour",
        "hours",
        "task",
        "tasks",
        "complete",
        "completed",
        "workload",
        "ntid",
        "员工",
        "工时",
        "任务",
    ),
    "workload_planning.md": ("capacity", "plan", "planned", "ongoing", "workload", "resource", "规划", "负载"),
    "study_delivery.md": ("study", "delivery", "did", "status", "里程碑", "交付"),
    "lot_tlf_sdtm_adam.md": ("lot", "tlf", "sdtm", "adam", "submission", "产出物"),
    "team_manager.md": (
        "manager",
        "group lead",
        "ta lead",
        "team",
        "reports to",
        "org",
        "org chart",
        "organization",
        "hierarchy",
        "经理",
        "团队",
        "组织",
    ),
    "reporting_dashboard.md": ("dashboard", "kpi", "trend", "monthly", "reporting", "看板", "报表"),
}
DEFAULT_EXAMPLES = (
    "query_index.md",
    "study_delivery.md",
    "workload_planning.md",
    "person_productivity.md",
    "lot_tlf_sdtm_adam.md",
    "team_manager.md",
    "reporting_dashboard.md",
    "uncategorized.md",
)
SAFE_EXAMPLE_FILES = tuple(
    name for name in DEFAULT_EXAMPLES if name != "sensitive_excluded.md"
)
SKILL_MAX_CHARS = 6000
SCHEMA_MAX_CHARS = 12000
EXAMPLE_MAX_CHARS = 5000
MAX_EXAMPLE_FILES = 3

LANGUAGE_RULE = (
    "Language policy: Match the user's question language. "
    "If the question is primarily Chinese, respond in Chinese. "
    "If the question is primarily English (or mixed with English as the main language), "
    "respond in English. Do not switch languages mid-answer unless quoting data labels."
)

EFFORT_PREDICTION_PATTERNS = (
    r"预测",
    r"预计",
    r"预估",
    r"估算.*(?:工时|时间|小时)",
    r"需要多久",
    r"还需要多少.*(?:工时|时间|小时)",
    r"\bforecast\b",
    r"\bpredict(?:ion)?\b",
    r"\bestimat(?:e|ed|ion)\b.*\b(?:effort|hours?|time)\b",
    r"\bhow long will\b",
    r"\bexpected (?:effort|hours?|time)\b",
)
DID_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_])[A-Za-z0-9][A-Za-z0-9-]*_\d+(?![A-Za-z0-9_])"
)
ISO_DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
PERSON_REFERENCE_PATTERN = re.compile(
    r"^(?:他|她|这个人|该人员|上述人员|上面的人|那个人|"
    r"this person|that person|the same person|him|her|them)$",
    re.IGNORECASE,
)
PERSON_REFERENCE_TEXT_PATTERN = re.compile(
    r"(?:他|她|这个人|该人员|上述人员|上面的人|那个人|"
    r"this\s+person|that\s+person|the same person|\bhim\b|\bher\b|\bthem\b)",
    re.IGNORECASE,
)
DID_REFERENCE_PATTERN = re.compile(
    r"(?:这个\s*did|该\s*did|上述\s*did|上一个\s*did|"
    r"this\s+did|that\s+did|the same did)",
    re.IGNORECASE,
)
DID_ONLY_PREFIX_PATTERN = re.compile(
    r"^(?:那|这个|该|上述|换成|改成|改为|使用|用|switch to|change to)$",
    re.IGNORECASE,
)
NON_NAME_WORD_PATTERN = re.compile(
    r"\b(?:hour|hours|working|work|effort|time|for|in|on|need|needed|"
    r"spend|cost|estimate|predict|forecast)\b",
    re.IGNORECASE,
)


def _extract_cypher(text: str) -> str:
    match = CYPHER_BLOCK.search(text)
    if match:
        return match.group(1).strip().rstrip(";")
    for line in text.splitlines():
        s = line.strip()
        if s.upper().startswith(("MATCH", "CALL", "WITH", "RETURN", "OPTIONAL", "UNWIND")):
            return s.rstrip(";")
    raise ValueError(f"Could not parse Cypher from model output:\n{text}")


def _latest_prediction_context(
    history: list[dict[str, Any]] | None,
) -> dict[str, str | None] | None:
    for message in reversed(history or []):
        prediction = message.get("prediction")
        if not isinstance(prediction, dict):
            continue
        person = prediction.get("person")
        did = prediction.get("did")
        if isinstance(person, str) and person.strip() and isinstance(did, str) and did.strip():
            as_of_date = prediction.get("as_of_date")
            return {
                "person": person.strip(),
                "did": did.strip(),
                "as_of_date": (
                    as_of_date.strip()
                    if isinstance(as_of_date, str) and as_of_date.strip()
                    else None
                ),
            }
    return None


def _is_effort_prediction_question(
    question: str, history: list[dict[str, Any]] | None = None
) -> bool:
    if any(
        re.search(pattern, question, re.IGNORECASE)
        for pattern in EFFORT_PREDICTION_PATTERNS
    ):
        return True
    return bool(
        _latest_prediction_context(history)
        and DID_PATTERN.search(question)
        and DID_ONLY_PREFIX_PATTERN.search(
            question[: DID_PATTERN.search(question).start()].strip(" ,，:：")
        )
    )


def _prediction_intent_candidate(
    question: str, history: list[dict[str, Any]] | None
) -> bool:
    return bool(DID_PATTERN.search(question) or _latest_prediction_context(history))


def classify_effort_prediction_intent(
    question: str, history: list[dict[str, Any]] | None = None
) -> tuple[bool, dict[str, int]]:
    """Classify ambiguous DID questions before choosing prediction or Cypher."""
    if _is_effort_prediction_question(question, history):
        return True, empty_usage()
    if not _prediction_intent_candidate(question, history):
        return False, empty_usage()

    history_text = "\n".join(
        f"{message['role']}: {message['content']}" for message in (history or [])[-6:]
    )
    context = _latest_prediction_context(history)
    system = """Classify whether the user is asking for a future effort forecast.
Return exactly one JSON object: {"intent":"effort_prediction"} or
{"intent":"neo4j_query"}.

Choose effort_prediction only when the user asks to estimate, forecast, plan,
or determine the future total hands-on hours needed for a person and DID.
Choose neo4j_query for already recorded hours, delivery status, task details,
lists, counts, or any other graph-data question. Use the prediction context
only to resolve references such as "that DID" or "that person"; it does not
make every follow-up a forecast. Do not calculate hours or add explanation."""
    user = f"""Prediction context:
{json.dumps(context, ensure_ascii=False) if context else "(none)"}

Recent conversation:
{history_text or "(none)"}

Current request:
{question}"""
    raw, usage = _chat(system, user, temperature=0)
    payload = _extract_json_object(raw)
    intent = payload.get("intent")
    if intent not in {"effort_prediction", "neo4j_query"}:
        raise ValueError("Intent classifier returned an unsupported intent.")
    return intent == "effort_prediction", usage


def _extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", stripped, re.IGNORECASE)
    if fenced:
        stripped = fenced.group(1).strip()
    else:
        match = re.search(r"\{[\s\S]*\}", stripped)
        if match:
            stripped = match.group(0)
    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("Prediction parameter response must be a JSON object.")
    return payload


def _extract_effort_parameters_locally(
    question: str, history: list[dict[str, Any]] | None = None
) -> dict[str, str | None] | None:
    context = _latest_prediction_context(history)
    did_match = DID_PATTERN.search(question)
    date_match = ISO_DATE_PATTERN.search(question)
    as_of_date = date_match.group(0) if date_match else (
        context["as_of_date"] if context else None
    )
    if did_match:
        prefix = question[: did_match.start()].strip(" ,，:：")
        prefix = re.sub(
            r"^(?:请|请帮我|帮我)?\s*(?:预测|预计|预估|估算)\s*",
            "",
            prefix,
            flags=re.IGNORECASE,
        )
        prefix = re.sub(
            r"^(?:please\s+)?(?:predict|forecast|estimate)(?:\s+|$)",
            "",
            prefix,
            flags=re.IGNORECASE,
        )
        person = re.sub(
            r"(?:的)?\s*(?:完成|做|负责|对于|对)\s*$",
            "",
            prefix,
            flags=re.IGNORECASE,
        )
        person = re.sub(
            r"(?:'s|’s)?\s*(?:total\s+)?(?:effort|hours?|time)?\s*(?:for|on)\s*$",
            "",
            person,
            flags=re.IGNORECASE,
        ).strip(" ,，:：'\"")
        if (
            not person
            or PERSON_REFERENCE_PATTERN.fullmatch(person)
            or DID_ONLY_PREFIX_PATTERN.fullmatch(person)
            or (context and PERSON_REFERENCE_TEXT_PATTERN.search(question))
        ):
            person = context["person"] if context else ""
        if not person:
            return None
        return {
            "person": person,
            "did": did_match.group(0),
            "as_of_date": as_of_date,
        }

    if not context:
        return None
    if PERSON_REFERENCE_TEXT_PATTERN.search(question) or DID_REFERENCE_PATTERN.search(question):
        return {**context, "as_of_date": as_of_date}

    person = re.sub(
        r"^(?:请|请帮我|帮我)?\s*(?:预测|预计|预估|估算)\s*",
        "",
        question,
        flags=re.IGNORECASE,
    )
    person = re.sub(
        r"^(?:please\s+)?(?:predict|forecast|estimate)\s+",
        "",
        person,
        flags=re.IGNORECASE,
    )
    person = re.sub(
        r"(?:的)?\s*(?:工时|时间|小时|effort|hours?|time)?\s*[。！？?]*$",
        "",
        person,
        flags=re.IGNORECASE,
    ).strip(" ,，:：'\"")
    if not person or PERSON_REFERENCE_PATTERN.fullmatch(person):
        return None
    return {
        "person": person,
        "did": context["did"],
        "as_of_date": as_of_date,
    }


def extract_effort_prediction_parameters(
    question: str, history: list[dict[str, Any]] | None = None
) -> tuple[dict[str, str | None], dict[str, int]]:
    local_parameters = _extract_effort_parameters_locally(question, history)
    history_text = ""
    if history:
        history_text = "\n".join(
            f"{message['role']}: {message['content']}" for message in history[-6:]
        )
    candidates = person_name_candidates(question)
    system = """Extract parameters for a DID effort prediction request.
Return exactly one JSON object with these keys:
{"person": string|null, "did": string|null, "as_of_date": "YYYY-MM-DD"|null}
Rules:
1. If Neo4j person candidates are supplied, select exactly one matching official
   Person.Name from that list. Do not return surrounding wording such as
   "hours for", "working hours", "in", or the prediction verb.
2. If no candidate is a match, copy only the person name or nickname supplied.
3. Copy the DID exactly as supplied.
4. Do not invent missing values.
5. Use conversation history only to resolve an explicitly referenced prior person or DID.
6. Do not add markdown or explanation.
Examples:
- "predict C1071007_141 hours for Lumamman" ->
  {"person":"Lumanman","did":"C1071007_141","as_of_date":null}
- "C1071007_141 大概要投入多久？" with a prior prediction for Riven ->
  {"person":"Riven","did":"C1071007_141","as_of_date":null}
- "Riven 的工时" with a prior prediction for C1071007_141 ->
  {"person":"Riven","did":"C1071007_141","as_of_date":null}"""
    user = f"""Likely official Neo4j Person.Name candidates:
{json.dumps(candidates, ensure_ascii=False)}

Locally parsed parameters (use only as a hint; correct them when the full
question or prediction context indicates a different person or DID):
{json.dumps(local_parameters, ensure_ascii=False) if local_parameters else "(none)"}

Conversation history:
{history_text or '(none)'}

Current request:
{question}"""
    raw, usage = _chat(system, user, temperature=0)
    payload = _extract_json_object(raw)
    person = payload.get("person")
    did = payload.get("did")
    as_of_date = payload.get("as_of_date")
    if not isinstance(person, str) or not person.strip():
        raise ValueError("The prediction request is missing a person name.")
    if not isinstance(did, str) or not did.strip():
        raise ValueError("The prediction request is missing a DID.")
    if as_of_date is not None and not isinstance(as_of_date, str):
        raise ValueError("as_of_date must be YYYY-MM-DD or null.")
    return {
        "person": person.strip(),
        "did": did.strip(),
        "as_of_date": as_of_date,
    }, usage


def _prediction_confidence(
    prediction: dict[str, Any], chinese: bool
) -> tuple[str, str]:
    features = prediction.get("similarity_features") or {}
    completed_count = int(prediction.get("person_completed_did_count") or 0)
    high_similarity_count = float(features.get("similar_did_count_ge_85") or 0)
    coverage = float(features.get("overall_prior_coverage") or 0)
    unseen_count = sum(
        float(features.get(name) or 0)
        for name in ("tlf_unseen_count", "adam_unseen_count", "sdtm_unseen_count")
    )
    reasons = (
        [f"{completed_count} 个历史 DID"]
        if chinese
        else [f"{completed_count} historical DIDs"]
    )
    if high_similarity_count:
        reasons.append(
            (
                f"{int(high_similarity_count)} 个高相似历史案例"
                if chinese
                else f"{int(high_similarity_count)} highly similar historical cases"
            )
        )
    if coverage >= 0.99 and unseen_count == 0:
        reasons.append("无未见任务" if chinese else "no unseen tasks")
    if (
        completed_count >= 20
        and high_similarity_count >= 3
        and coverage >= 0.99
        and unseen_count == 0
    ):
        return ("高" if chinese else "High"), ("；" if chinese else "; ").join(reasons)
    if completed_count >= 5 and high_similarity_count >= 1:
        return ("中" if chinese else "Medium"), ("；" if chinese else "; ").join(reasons)
    return ("低" if chinese else "Low"), ("；" if chinese else "; ").join(reasons)


def _same_study_label(item: dict[str, Any], prediction: dict[str, Any]) -> str:
    item_study = item.get("study")
    target_study = prediction.get("study")
    if item_study and target_study:
        return "同 Study" if item_study == target_study else "跨 Study"
    return "Study 未知"


def _format_effort_prediction(
    prediction: dict[str, Any], question: str, requested_person: str | None = None
) -> str:
    chinese = bool(re.search(r"[\u4e00-\u9fff]", question))
    similar = prediction.get("similar_historical_dids") or []
    warnings = prediction.get("warnings") or []
    confidence, confidence_reason = _prediction_confidence(prediction, chinese)
    if chinese:
        lines = [
            f"**{prediction['person']}** 完成 **{prediction['did']}** 的预计总工时：",
            f"- 最可能工时（P50）：**{prediction['p50_hours']} 小时**",
            f"- 建议排期（P80）：**{prediction['p80_hours']} 小时**",
            f"- 保守预留（P90）：**{prediction['p90_hours']} 小时**",
            "",
            f"预测可信度：**{confidence}**（{confidence_reason}）。",
        ]
        if requested_person and requested_person.casefold() != str(
            prediction["person"]
        ).casefold():
            lines.append(
                f"人员匹配：输入 `{requested_person}` → `{prediction['person']}`。"
            )
        if similar:
            lines.extend(["", "最相似的历史案例："])
            lines.extend(
                (
                    f"- {item['did']}（{_same_study_label(item, prediction)}，"
                    f"{item.get('completion_date') or '完成日期未知'}）："
                    f"实际 {item['actual_hours']} 小时；"
                    f"TLF 标题近似度 {item['tlf_semantic_similarity']:.0%}，"
                    f"ADaM 相似度 {item['adam_similarity']:.0%}，"
                    f"SDTM 相似度 {item['sdtm_similarity']:.0%}"
                )
                for item in similar[:3]
            )
        if warnings:
            lines.extend(["", "注意：", *[f"- {warning}" for warning in warnings]])
        lines.extend(["", f"模型版本：`{prediction['model_version']}`"])
        return "\n".join(lines)

    lines = [
        f"Estimated total effort for **{prediction['person']}** on **{prediction['did']}**:",
        f"- Most likely effort (P50): **{prediction['p50_hours']} hours**",
        f"- Planning estimate (P80): **{prediction['p80_hours']} hours**",
        f"- Conservative reserve (P90): **{prediction['p90_hours']} hours**",
        "",
        f"Prediction confidence: **{confidence}** ({confidence_reason}).",
    ]
    if requested_person and requested_person.casefold() != str(
        prediction["person"]
    ).casefold():
        lines.append(
            f"Person match: `{requested_person}` → `{prediction['person']}`."
        )
    if similar:
        lines.extend(["", "Most similar historical cases:"])
        lines.extend(
            (
                f"- {item['did']} ({_same_study_label(item, prediction)}, "
                f"{item.get('completion_date') or 'completion date unavailable'}): "
                f"{item['actual_hours']} actual hours; "
                f"TLF title similarity {item['tlf_semantic_similarity']:.0%}, "
                f"ADaM similarity {item['adam_similarity']:.0%}, "
                f"SDTM similarity {item['sdtm_similarity']:.0%}"
            )
            for item in similar[:3]
        )
    if warnings:
        lines.extend(["", "Warnings:", *[f"- {warning}" for warning in warnings]])
    lines.extend(["", f"Model version: `{prediction['model_version']}`"])
    return "\n".join(lines)


def answer_effort_prediction(
    question: str,
    history: list[dict[str, Any]] | None = None,
    initial_usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    parameters, usage = extract_effort_prediction_parameters(question, history)
    prediction = predict_effort(
        person=str(parameters["person"]),
        did=str(parameters["did"]),
        as_of_date=parameters["as_of_date"],
    )
    return {
        "answer": _format_effort_prediction(
            prediction, question, requested_person=str(parameters["person"])
        ),
        "cypher": "",
        "rows": [prediction],
        "schema": None,
        "error": None,
        "usage": add_usage(initial_usage or empty_usage(), usage),
        "prediction": prediction,
        "case_id": None,
        "graph": {},
        "columns": list(prediction.keys()),
    }


@lru_cache(maxsize=64)
def _read_doc(relative_path: str) -> str:
    p = DOCS_ROOT / relative_path
    if not p.exists():
        raise FileNotFoundError(f"Missing prompt doc: {p}")
    return p.read_text(encoding="utf-8")


def _select_examples(question: str, limit: int = MAX_EXAMPLE_FILES) -> list[str]:
    q = question.lower()
    scored: list[tuple[int, str]] = []
    for filename, keywords in EXAMPLE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in q)
        if score > 0:
            scored.append((score, filename))
    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [name for _, name in scored[:limit]]
    if len(selected) < limit:
        for fallback in DEFAULT_EXAMPLES:
            if fallback not in selected:
                selected.append(fallback)
            if len(selected) >= limit:
                break
    return selected[:limit]


def _build_domain_context(question: str) -> str:
    skill_text = _read_doc("skill.md")[:SKILL_MAX_CHARS]
    schema_text = _read_doc("schema.md")[:SCHEMA_MAX_CHARS]
    parts = [
        "Domain guidance from docs/skill.md:",
        skill_text,
        "",
        "Domain schema reference from docs/schema.md:",
        schema_text,
    ]

    selected = _select_examples(question)
    try:
        endorsed = format_positive_examples(get_memory().positive_examples(question, limit=3))
    except Exception:  # noqa: BLE001 - example memory must not break Cypher generation
        endorsed = ""
    if endorsed:
        parts.extend(["", endorsed])

    for filename in selected:
        example_path = EXAMPLES_ROOT / filename
        if not example_path.exists():
            continue
        example_text = _read_doc(f"examples/{filename}")[:EXAMPLE_MAX_CHARS]
        parts.extend(
            [
                "",
                f"Few-shot reference from {example_path.as_posix()}:",
                example_text,
            ]
        )
    return "\n".join(parts)


def _compact_live_schema(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "labels": schema.get("labels") or [],
        "relationshipTypes": schema.get("relationshipTypes") or [],
        "propertyKeys": schema.get("propertyKeys") or [],
    }


def generate_cypher(question: str, schema: dict[str, Any], history: list[dict[str, str]] | None = None) -> tuple[str, dict[str, int]]:
    schema_text = json.dumps(_compact_live_schema(schema), ensure_ascii=False, indent=2)
    domain_context = _build_domain_context(question)
    history_text = ""
    if history:
        recent = history[-6:]
        history_text = "\n".join(f"{m['role']}: {m['content']}" for m in recent)

    system = """You are a DID Neo4j Cypher expert. Rewrite the user's question into one read-only Cypher query based on the given schema and domain examples.
Rules:
1. Output exactly one Cypher statement inside a ```cypher code block.
2. Never use CREATE/MERGE/DELETE/SET/REMOVE/DROP or other write operations.
3. Add LIMIT for result sets (default 50) unless the user asks for a count only.
4. Study identifiers often use IPort_Study or Name (e.g. C1071007). Do not invent property names.
5. Common pattern: (:Study)-[:HAS_DELIVERY]->(:Delivery).
6. Use only property keys that appear in schema.propertyKeys or docs/schema.md.
7. Cypher keywords stay in English; do not translate labels/properties.
8. Follow rules and safe patterns from docs/skill.md, docs/schema.md, and docs/examples/*.md (ignore sensitive_excluded.md).
9. Prefer business query patterns from person_productivity.md, workload_planning.md, study_delivery.md, lot_tlf_sdtm_adam.md, team_manager.md, reporting_dashboard.md, and query_index.md.
10. Do not generate employee ranking/performance-scoring queries.
11. When user-endorsed thumbs-up examples are provided, prefer those Cypher patterns if they match the question.
12. For org-chart / reporting-tree questions, prefer the scalar template columns person, reporting_level, reports_to, status so the UI can render both a table and an organization chart.
13. WORKS_ON has no Task_Num_Total. Person task totals must be coalesce(toFloat(w.CSR_Task_Num_Total),0)+coalesce(toFloat(w.SDA_Task_Num_Total),0)+coalesce(toFloat(w.STD_Task_Num_Total),0)+coalesce(toFloat(w.esub_Data_Num_Total),0)."""

    user = f"""Schema:
{schema_text}

Domain context:
{domain_context}

Conversation history:
{history_text or '(none)'}

User question: {question}

Generate a read-only Cypher query."""

    raw, usage = _chat(system, user)
    return expand_legacy_task_properties(_extract_cypher(raw)), usage


def repair_cypher(question: str, schema: dict[str, Any], previous_cypher: str, previous_rows: list[dict[str, Any]], history: list[dict[str, str]] | None = None) -> tuple[str, dict[str, int]]:
    schema_text = json.dumps(_compact_live_schema(schema), ensure_ascii=False, indent=2)
    history_text = ""
    if history:
        recent = history[-6:]
        history_text = "\n".join(f"{m['role']}: {m['content']}" for m in recent)

    system = """You are a Neo4j query repair assistant. The previous Cypher query returned no data, but the user likely expects business results. Fix the query by keeping it read-only and using only valid property names from the schema.
Rules:
1. Output exactly one Cypher statement inside a ```cypher code block.
2. Do not invent property names; follow schema.propertyKeys exactly.
3. Correct common date bugs: use `Planned_Delivery_Date` / `Actual_Delivery_Date` and filter on the actual date field instead of a transformed or missing property.
4. Keep the business date filter in the WHERE clause or MATCH path, and do not hide it inside an OPTIONAL MATCH without a real predicate.
5. When the question mentions a month or year, apply the filter to the date field and keep it aligned with the user’s requested period.
6. Preserve the original business intent and return the relevant rows.
7. Prefer the safe patterns from docs/skill.md and docs/examples/*.md (skip sensitive_excluded.md).
8. Never use CREATE/MERGE/DELETE/SET/REMOVE/DROP or other write operations.
9. Never use Task_Num_Total; expand person tasks into CSR_Task_Num_Total + SDA_Task_Num_Total + STD_Task_Num_Total + esub_Data_Num_Total."""

    user = f"""Schema:
{schema_text}

Conversation history:
{history_text or '(none)'}

User question: {question}

Previous Cypher:
{previous_cypher}

Previous query returned zero rows.

Use the schema and business intent to repair the query so it returns the expected data for the asked period.

Generate a corrected read-only Cypher query."""

    raw, usage = _chat(system, user)
    return expand_legacy_task_properties(_extract_cypher(raw)), usage


def answer_from_rows(
    question: str,
    cypher: str,
    rows: list[dict[str, Any]],
    *,
    structured_presentation: bool = False,
) -> tuple[str, dict[str, int]]:
    payload = json.dumps(rows[:80], ensure_ascii=False, default=str)
    detail_rule = (
        "A validated chart or table will render the row details separately. Give only "
        "a direct, concise conclusion in at most two sentences; do not output a "
        "markdown table, list, or repeat individual rows."
        if structured_presentation
        else "For multiple rows, use a concise list or table-style markdown."
    )
    system = f"""You are a Neo4j graph Q&A assistant. Answer from the query results in clear natural language.
Rules:
1. {LANGUAGE_RULE}
2. Lead with the direct answer, then add brief supporting detail if useful.
3. Never invent data that is not in the results.
4. If results are empty, explain likely reasons (wrong ID, property name, or no matching data).
5. {detail_rule}
6. Keep property/field names from the database as-is when citing them."""

    user = f"""User question: {question}

Cypher executed:
{cypher}

Query results (JSON):
{payload}

Write the answer now."""
    return _chat(system, user)


def _needs_repair(question: str, rows: list[dict[str, Any]], cypher: str) -> bool:
    if rows:
        return False
    q = question.lower()
    date_keywords = (
        "august",
        "september",
        "january",
        "february",
        "march",
        "april",
        "may",
        "june",
        "july",
        "month",
        "year",
        "planned delivery",
        "actual delivery",
        "delivery date",
        "delivered",
        "delivery",
    )
    if any(keyword in q for keyword in date_keywords):
        return True
    return "optional match" in cypher.lower() and "where" in cypher.lower()


def _remember_case(question: str, cypher: str, rows: list[dict[str, Any]], error: str | None) -> int | None:
    try:
        outcome = "error" if error else ("success" if rows else "empty")
        return get_memory().add_case(
            question, cypher, outcome=outcome, row_count=len(rows or [])
        )
    except Exception:  # noqa: BLE001
        return None


def _graph_for_cypher(cypher: str) -> dict[str, Any]:
    meta = last_query_meta() or {}
    expected = (cypher or "").strip().rstrip(";")
    actual = str(meta.get("cypher") or "").strip().rstrip(";")
    if expected and actual == expected:
        return meta.get("graph") or {}
    return {}


def ask(
    question: str,
    history: list[dict[str, Any]] | None = None,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    load_env()
    is_prediction, intent_usage = classify_effort_prediction_intent(question, history)
    if is_prediction:
        try:
            result = answer_effort_prediction(
                question, history, initial_usage=intent_usage
            )
            result["schema"] = schema
            return result
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            return {
                "answer": f"Effort prediction failed: {error}",
                "cypher": "",
                "rows": [],
                "schema": schema,
                "error": error,
                "usage": empty_usage(),
            }
    schema = schema or get_schema()
    last_error = None
    cypher = ""
    usage = intent_usage

    for _attempt in range(3):
        try:
            hint = f"\nPrevious Cypher failed: {last_error}" if last_error else ""
            cypher, u1 = generate_cypher(question + hint, schema, history)
            usage = add_usage(usage, u1)
            rows = run_cypher(cypher)

            if not rows and _needs_repair(question, rows, cypher):
                repaired, u_repair = repair_cypher(question, schema, cypher, rows, history)
                usage = add_usage(usage, u_repair)
                rows = run_cypher(repaired)
                cypher = repaired

            visualization, presentation_usage, presentation_warning = select_result_presentation(
                question,
                rows,
                chat=lambda system, user: _chat(system, user, temperature=0),
            )
            usage = add_usage(usage, presentation_usage)
            if visualization is not None and not visualization["summary_required"]:
                answer = ""
            else:
                answer, u2 = answer_from_rows(
                    question,
                    cypher,
                    rows,
                    structured_presentation=visualization is not None,
                )
                usage = add_usage(usage, u2)
            case_id = _remember_case(question, cypher, rows, None)
            columns = list(dict.fromkeys(key for row in rows for key in row))
            return {
                "answer": answer,
                "cypher": cypher,
                "rows": rows,
                "columns": columns,
                "schema": schema,
                "error": None,
                "usage": usage,
                "visualization": visualization,
                "table": visualization.get("table") if visualization else None,
                "presentation_warning": presentation_warning,
                "case_id": case_id,
                "graph": _graph_for_cypher(cypher),
            }
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            log.exception("Query attempt %s failed: %s", _attempt + 1, last_error)

    return {
        "answer": f"Query failed after 3 attempts: {last_error}",
        "cypher": cypher,
        "rows": [],
        "columns": [],
        "schema": schema,
        "error": last_error,
        "usage": usage,
        "case_id": _remember_case(question, cypher, [], last_error),
        "graph": {},
    }
