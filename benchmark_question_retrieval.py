"""Reproducible local retrieval evaluation; never calls Vox or Neo4j."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sklearn

from question_retrieval import (
    EXAMPLES_ROOT, EXAMPLE_MAX_CHARS, REVIEW_PATH, ROOT, QuestionIndex, apply_reviews,
    format_matches, load_questions, select_example_files,
)

EVAL_PATH = ROOT / "docs" / "question_retrieval_eval.json"
METHODS = ("flat_tfidf", "categorized_tfidf", "flat_original", "legacy_prefix")


def quality_metrics(retrieved: list[str], relevant: set[str]) -> dict[str, float]:
    if not relevant:
        raise ValueError("Quality metrics require at least one relevant ID.")
    if len(retrieved) != len(set(retrieved)):
        raise ValueError("Retrieved IDs must be unique.")
    hits = [int(identifier in relevant) for identifier in retrieved[:3]]
    dcg = sum(hit / math.log2(rank + 2) for rank, hit in enumerate(hits))
    ideal = sum(1 / math.log2(rank + 2) for rank in range(min(3, len(relevant))))
    return {
        "hit_at_3": float(any(hits)),
        "precision_at_3": sum(hits) / 3,
        "recall_at_3": sum(hits) / len(relevant),
        "mrr_at_3": next((1 / (rank + 1) for rank, hit in enumerate(hits) if hit), 0.0),
        "ndcg_at_3": dcg / ideal,
    }


def load_evaluation(path: Path, known_ids: set[str]) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    queries = payload.get("queries")
    if payload.get("version") != 1 or not isinstance(queries, list) or not queries:
        raise ValueError("Expected a nonempty version-1 evaluation set.")
    seen: set[str] = set()
    for query in queries:
        if not isinstance(query, dict):
            raise ValueError("Each evaluation query must be an object.")
        identifier, question, relevant = (
            query.get("id"), query.get("question"), query.get("relevant_ids")
        )
        if not isinstance(identifier, str) or not identifier.strip() or identifier in seen:
            raise ValueError("Evaluation IDs must be unique nonempty strings.")
        seen.add(identifier)
        if not isinstance(question, str) or not question.strip():
            raise ValueError(f"Blank evaluation query: {identifier}")
        if (
            not isinstance(relevant, list) or not relevant
            or any(not isinstance(item, str) or item not in known_ids for item in relevant)
            or len(relevant) != len(set(relevant))
        ):
            raise ValueError(f"Invalid relevance labels for {identifier}.")
    return queries


def run_benchmark(eval_path: Path = EVAL_PATH, repeats: int = 30) -> dict[str, Any]:
    if repeats < 1:
        raise ValueError("Benchmark repeats must be positive.")
    started = time.perf_counter()
    raw = load_questions()
    reviewed = apply_reviews(raw)
    index = QuestionIndex(reviewed)
    cold_ms = (time.perf_counter() - started) * 1000
    original_index = QuestionIndex(raw)
    queries = load_evaluation(eval_path, {item.id for item in raw})
    file_texts = {
        name: (EXAMPLES_ROOT / name).read_text(encoding="utf-8")
        for name in {item.source for item in raw} | {"query_index.md"}
    }
    legacy_prefixes = {
        name: text[:EXAMPLE_MAX_CHARS] for name, text in file_texts.items()
    }
    visible_legacy_ids = {
        name: [
            item.id for item in raw
            if item.source == name and item.text in context
        ][:3]
        for name, context in legacy_prefixes.items()
    }

    def retrieve(
        method: str, question: str, *, warn_on_no_overlap: bool = True,
    ) -> tuple[list[str], str]:
        if method == "legacy_prefix":
            # Score only complete examples actually visible in the original prompt.
            filename = select_example_files(question)[0]
            return visible_legacy_ids[filename], legacy_prefixes[filename]
        candidates = None
        selected_index = index
        if method == "categorized_tfidf":
            selected_files = select_example_files(question)
            candidates = {item.id for item in raw if item.source in selected_files}
        elif method == "flat_original":
            selected_index = original_index
        matches = selected_index.search(
            question, candidates=candidates, warn_on_no_overlap=warn_on_no_overlap,
        )
        return [match.question.id for match in matches], format_matches(matches)

    rows = []
    for query in queries:
        methods: dict[str, Any] = {}
        for method in METHODS:
            identifiers, context = retrieve(method, query["question"])
            durations = []
            for _ in range(repeats):
                started = time.perf_counter_ns()
                retrieve(method, query["question"], warn_on_no_overlap=False)
                durations.append((time.perf_counter_ns() - started) / 1_000_000)
            methods[method] = {
                "ids": identifiers,
                **quality_metrics(identifiers, set(query["relevant_ids"])),
                "prompt_chars": len(context),
                "latency_samples_ms": durations,
            }
        rows.append({**query, "methods": methods})
    summary = {}
    for method in METHODS:
        values = [row["methods"][method] for row in rows]
        durations = sorted(sample for value in values for sample in value["latency_samples_ms"])
        summary[method] = {
            metric: statistics.mean(value[metric] for value in values)
            for metric in (
                "hit_at_3", "precision_at_3", "recall_at_3", "mrr_at_3", "ndcg_at_3",
                "prompt_chars",
            )
        }
        summary[method].update({
            "latency_p50_ms": statistics.median(durations),
            "latency_p95_ms": durations[math.ceil(0.95 * len(durations)) - 1],
        })
    return {
        "version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime": {"python": platform.python_version(), "scikit_learn": sklearn.__version__},
        "question_count": len(raw), "eval_query_count": len(queries), "repeats": repeats,
        "reviewed_questions_with_cautions": sum(bool(item.issues) for item in reviewed),
        "review_caution_count": sum(len(item.issues) for item in reviewed),
        "cold_reviewed_index_ms": cold_ms,
        "vector_shape": list(index.matrix.shape), "vector_nnz": index.matrix.nnz,
        "sparse_matrix_bytes": sum(
            buffer.nbytes for buffer in (index.matrix.data, index.matrix.indices, index.matrix.indptr)
        ),
        "fingerprints": {
            "reviews_sha256": hashlib.sha256(REVIEW_PATH.read_bytes()).hexdigest(),
            "evaluation_sha256": hashlib.sha256(eval_path.read_bytes()).hexdigest(),
            "sources_sha256": hashlib.sha256(
                "".join(item.source_sha256 for item in raw).encode("ascii")
            ).hexdigest(),
        },
        "limitations": [
            "Agent-authored paraphrase relevance labels, not independent human gold judgments.",
            "Recall uses the annotated relevant IDs only; labels may be incomplete.",
            "Local lexical TF-IDF, not semantic embeddings or downstream answer accuracy.",
            "Warm timings include selection, transform, scoring and prompt assembly; "
            "exclude imports, source I/O, fingerprint checks, warning log I/O, Vox and Neo4j.",
            "Legacy baseline scores only fully visible examples; partial examples are not executable references.",
            "Review augmentation is controlled by categorized_tfidf using the same reviewed vectors "
            "and flat_original using original titles only.",
            "Categorized baseline preserves this repository's one-file keyword routing, "
            "not an optimized or learned classifier; results do not generalize to all category-based retrieval.",
            "Prompt character counts are not token counts or measured LLM latency/cost.",
            "Offline review effort is not included in cold index construction time.",
        ],
        "summary": summary, "queries": rows,
    }


def markdown_report(result: dict[str, Any]) -> str:
    lines = [
        "# Question retrieval comparison", "",
        f"Safe questions: **{result['question_count']}**. "
        f"Agent-authored evaluation queries: **{result['eval_query_count']}**. "
        f"Timing repeats per query/method: **{result['repeats']}**.", "",
        "Every safe question has a matching offline review and source hash. "
        f"**{result['reviewed_questions_with_cautions']}** questions have "
        f"**{result['review_caution_count']}** review cautions. "
        "The source Cypher is unchanged; cautions travel with retrieved examples.", "",
        f"Runtime: Python **{result['runtime']['python']}**, "
        f"scikit-learn **{result['runtime']['scikit_learn']}**.", "",
        "All methods return at most three question-level references. "
        "The legacy file-prefix baseline can expose fewer than three complete questions.", "",
        "| Method | Hit@3 | Precision@3 | Recall@3 | MRR@3 | nDCG@3 | p50 ms | p95 ms | Mean prompt chars |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method, values in result["summary"].items():
        lines.append(
            f"| {method} | {values['hit_at_3']:.3f} | {values['precision_at_3']:.3f} "
            f"| {values['recall_at_3']:.3f} | {values['mrr_at_3']:.3f} "
            f"| {values['ndcg_at_3']:.3f} | {values['latency_p50_ms']:.3f} "
            f"| {values['latency_p95_ms']:.3f} | {values['prompt_chars']:.0f} |"
        )
    flat = result["summary"]["flat_tfidf"]
    categorized = result["summary"]["categorized_tfidf"]
    legacy = result["summary"]["legacy_prefix"]
    lines.extend([
        "", "## Observed trade-off", "",
        "Against category-filtered retrieval with identical reviewed vectors, "
        f"flat retrieval changes Hit@3 by **{100 * (flat['hit_at_3'] - categorized['hit_at_3']):+.1f} "
        f"percentage points**, MRR@3 by **{flat['mrr_at_3'] - categorized['mrr_at_3']:+.3f}**, "
        f"and p50 local latency by **{flat['latency_p50_ms'] - categorized['latency_p50_ms']:+.3f} ms**.",
        "",
        "Against the actual legacy prompt, mean retrieved-context size changes by "
        f"**{flat['prompt_chars'] - legacy['prompt_chars']:+.0f} characters**. "
        "A larger complete-example prompt can increase generation cost/latency even when local "
        "retrieval is fast; this experiment does not measure that downstream trade-off.",
        "", "## Interpretation", "",
        "- `flat_tfidf`: all safe reviewed questions, without category filtering (production default).",
        "- `categorized_tfidf`: the identical reviewed index, restricted to the original keyword-selected file.",
        "- `flat_original`: all safe original titles, without review paraphrase augmentation.",
        "- `legacy_prefix`: actual original selection of one topic file and its first 2200 characters.",
        "", f"Cold reviewed corpus loading/index construction: **{result['cold_reviewed_index_ms']:.3f} ms** "
        "(imports excluded). "
        f"Sparse vector matrix: **{result['sparse_matrix_bytes']} bytes**, "
        f"shape **{result['vector_shape']}**, nonzeros **{result['vector_nnz']}**.",
        "", "## Limits", "",
        *[f"- {limit}" for limit in result["limitations"]],
        "", "## Per-query retrieval", "",
        "| Query | Relevant | Flat Top 3 | Categorized Top 3 | Original-title Top 3 | Legacy complete IDs |",
        "|---|---|---|---|---|---|",
    ])
    for row in result["queries"]:
        cells = [row["id"] + ": " + row["question"], ", ".join(row["relevant_ids"])]
        cells.extend(", ".join(row["methods"][method]["ids"]) or "(none)" for method in METHODS)
        lines.append("| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--eval", type=Path, default=EVAL_PATH)
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "question_retrieval_results.json")
    parser.add_argument("--report", type=Path, default=ROOT / "docs" / "question_retrieval_comparison.md")
    parser.add_argument("--repeats", type=int, default=30)
    args = parser.parse_args()
    result = run_benchmark(args.eval, args.repeats)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(markdown_report(result), encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
