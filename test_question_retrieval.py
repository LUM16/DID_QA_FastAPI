"""Question-level retrieval, review validation and comparison metrics."""

from __future__ import annotations

import json
import math
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import agent
from benchmark_question_retrieval import (
    load_evaluation, markdown_report, quality_metrics, run_benchmark,
)
from question_retrieval import (
    Question, QuestionIndex, apply_reviews, format_matches, get_index, load_questions,
    select_example_files,
)


def fixture_questions() -> tuple[Question, ...]:
    return tuple(
        Question(
            id=f"q{index:03}", question=title,
            text=f"## q{index:03}: {title}\n\n```cypher\nRETURN {index} AS value\n```",
            source=source, source_sha256=f"hash{index}", retrieval_text=text,
        )
        for index, (title, source, text) in enumerate((
            ("Person hours", "person_productivity.md", "person hours effort 工时 工作时间"),
            ("Study delivery status", "study_delivery.md", "study delivery status 交付 状态"),
            ("Manager hierarchy", "team_manager.md", "manager reporting hierarchy 经理 组织"),
            ("Task assignments", "person_productivity.md", "task assignments ownership 任务 分配"),
        ))
    )


class QuestionRetrievalTests(unittest.TestCase):
    def test_flat_search_returns_three_unique_ranked_questions(self) -> None:
        index = QuestionIndex(fixture_questions())
        matches = index.search("经理组织")
        self.assertEqual(len(matches), 3)
        self.assertEqual(matches[0].question.id, "q002")
        self.assertEqual(len({match.question.id for match in matches}), 3)
        self.assertEqual([match.score for match in matches], sorted(
            (match.score for match in matches), reverse=True,
        ))

    def test_flat_search_is_not_restricted_by_keyword_file(self) -> None:
        index = QuestionIndex(fixture_questions())
        query = "person hours manager hierarchy"
        self.assertEqual(select_example_files(query), ["person_productivity.md"])
        self.assertIn("q002", [match.question.id for match in index.search(query)])
        restricted = index.search(query, candidates={"q000", "q003"})
        self.assertNotIn("q002", [match.question.id for match in restricted])

    def test_blank_input_rejected_and_no_overlap_is_visible(self) -> None:
        index = QuestionIndex(fixture_questions())
        with self.assertRaisesRegex(ValueError, "blank"):
            index.search(" ")
        with self.assertLogs("question_retrieval", level="WARNING") as captured:
            matches = index.search("zzzzunknown")
        self.assertIn("no lexical overlap", captured.output[0])
        self.assertEqual([match.question.id for match in matches], ["q000", "q001", "q002"])
        self.assertTrue(all(match.score == 0 for match in matches))

    def test_complete_examples_and_review_cautions_are_preserved(self) -> None:
        questions = fixture_questions()
        questions = (replace(questions[0], issues=("Check the live field.",)), *questions[1:])
        context = format_matches(QuestionIndex(questions).search("person hours"))
        self.assertIn(questions[0].text, context)
        self.assertIn("Check the live field.", context)
        self.assertEqual(context.count("```cypher"), 3)

    def test_parser_excludes_sensitive_file_and_preserves_full_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            questions = fixture_questions()
            (root / "bank.md").write_text(
                "# Flat bank\n\n" + "\n\n".join(item.text for item in questions),
                encoding="utf-8",
            )
            (root / "sensitive_excluded.md").write_text(
                "## q999: Forbidden\n```cypher\nRETURN 999\n```", encoding="utf-8",
            )
            parsed = load_questions(root)
            self.assertEqual(len(parsed), 4)
            self.assertEqual(parsed[0].text, questions[0].text)
            self.assertNotIn("q999", {item.id for item in parsed})
            self.assertTrue(all(len(item.source_sha256) == 64 for item in parsed))
            (root / "duplicate.md").write_text(questions[0].text, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Duplicate question ID"):
                load_questions(root)

    def test_parser_includes_dashboard_and_suffixed_question_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            identifiers = ("q140_1", "q140_2", "dashboard_q001", "sub001")
            (root / "bank.md").write_text("\n\n".join(
                f"## {identifier}: Question {identifier}\n\n```cypher\nRETURN 1\n```"
                for identifier in identifiers
            ), encoding="utf-8")
            self.assertEqual(
                {item.id for item in load_questions(root)}, set(identifiers),
            )

    def test_reviews_require_complete_unique_current_coverage(self) -> None:
        questions = fixture_questions()
        reviews = [
            {"id": item.id, "question": item.question,
             "source_sha256": item.source_sha256,
             "retrieval_text": item.retrieval_text, "issues": []}
            for item in questions
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "reviews.json"

            def write(items: list[dict]) -> None:
                path.write_text(json.dumps({"version": 1, "reviews": items}), encoding="utf-8")

            write(reviews)
            self.assertEqual(len(apply_reviews(questions, path)), 4)
            write(reviews[:-1])
            with self.assertRaisesRegex(ValueError, "coverage mismatch"):
                apply_reviews(questions, path)
            write(reviews + [reviews[0]])
            with self.assertRaisesRegex(ValueError, "Duplicate review"):
                apply_reviews(questions, path)
            write([{**reviews[0], "source_sha256": "stale"}, *reviews[1:]])
            with self.assertRaisesRegex(ValueError, "Stale review"):
                apply_reviews(questions, path)
            write([{**reviews[0], "retrieval_text": ""}, *reviews[1:]])
            with self.assertRaisesRegex(ValueError, "Missing reviewed retrieval text"):
                apply_reviews(questions, path)
            write([{**reviews[0], "issues": "not a list"}, *reviews[1:]])
            with self.assertRaisesRegex(ValueError, "Invalid review issues"):
                apply_reviews(questions, path)

    def test_changed_source_metadata_changes_cache_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, review = root / "bank.md", root / "review.json"
            source.write_text("first", encoding="utf-8")
            review.write_text("{}", encoding="utf-8")
            with (
                patch("question_retrieval.source_paths", return_value=(source,)),
                patch("question_retrieval.REVIEW_PATH", review),
                patch("question_retrieval._cached_index") as cached,
            ):
                get_index()
                first_fingerprint = cached.call_args.args[0]
                source.write_text("updated source", encoding="utf-8")
                get_index()
                self.assertNotEqual(first_fingerprint, cached.call_args.args[0])

    def test_metrics_use_true_top_three_and_fixed_precision_denominator(self) -> None:
        metrics = quality_metrics(["q001", "q002", "q003"], {"q002", "q004"})
        self.assertEqual(metrics["hit_at_3"], 1)
        self.assertAlmostEqual(metrics["precision_at_3"], 1 / 3)
        self.assertEqual(metrics["recall_at_3"], 0.5)
        self.assertEqual(metrics["mrr_at_3"], 0.5)
        self.assertAlmostEqual(
            metrics["ndcg_at_3"], (1 / math.log2(3)) / (1 + 1 / math.log2(3)),
        )
        self.assertEqual(quality_metrics([], {"q001"})["precision_at_3"], 0)
        with self.assertRaises(ValueError):
            quality_metrics(["q001", "q001"], {"q001"})

    def test_evaluation_rejects_unknown_labels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "eval.json"
            path.write_text(json.dumps({
                "version": 1,
                "queries": [{"id": "e01", "question": "hours", "relevant_ids": ["q999"]}],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Invalid relevance"):
                load_evaluation(path, {"q000"})

    def test_benchmark_reports_all_methods_quality_and_timing(self) -> None:
        questions = fixture_questions()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source in {item.source for item in questions}:
                (root / source).write_text(
                    "\n\n".join(item.text for item in questions if item.source == source),
                    encoding="utf-8",
                )
            (root / "query_index.md").write_text("# Index only", encoding="utf-8")
            review_path = root / "review.json"
            review_path.write_text("{}", encoding="utf-8")
            eval_path = root / "eval.json"
            eval_path.write_text(json.dumps({
                "version": 1, "queries": [
                    {"id": "e01", "question": "person hours", "relevant_ids": ["q000"]},
                    {"id": "e02", "question": "manager hierarchy", "relevant_ids": ["q002"]},
                ],
            }), encoding="utf-8")
            with (
                patch("benchmark_question_retrieval.load_questions", return_value=questions),
                patch("benchmark_question_retrieval.apply_reviews", return_value=questions),
                patch("benchmark_question_retrieval.EXAMPLES_ROOT", root),
                patch("benchmark_question_retrieval.REVIEW_PATH", review_path),
            ):
                result = run_benchmark(eval_path, repeats=2)
        self.assertEqual(result["question_count"], 4)
        self.assertEqual(result["eval_query_count"], 2)
        self.assertEqual(result["summary"]["flat_tfidf"]["hit_at_3"], 1)
        self.assertEqual(len(result["summary"]), 4)
        for row in result["queries"]:
            self.assertEqual(len(row["methods"]["flat_tfidf"]["ids"]), 3)
            for metrics in row["methods"].values():
                self.assertEqual(len(metrics["latency_samples_ms"]), 2)
        self.assertIn("not semantic embeddings", markdown_report(result))
        self.assertIn("legacy_prefix", markdown_report(result))

    def test_agent_defaults_to_flat_retrieval_and_retains_other_guidance(self) -> None:
        with (
            patch.dict(os.environ, {"QUESTION_RETRIEVAL_MODE": "flat_tfidf"}),
            patch("agent.load_env"),
            patch("agent.retrieve_context", return_value="FULL TOP THREE") as retrieve,
            patch("agent._select_examples") as old_selection,
            patch("agent.get_memory") as memory,
        ):
            memory.return_value.positive_examples.return_value = []
            memory.return_value.negative_examples.return_value = []
            context = agent._build_domain_context("compare study hours")
        retrieve.assert_called_once_with("compare study hours")
        old_selection.assert_not_called()
        self.assertIn("FULL TOP THREE", context)
        self.assertIn("Domain guidance", context)
        self.assertIn("Domain schema reference", context)

    def test_agent_rejects_invalid_mode(self) -> None:
        with (
            patch.dict(os.environ, {"QUESTION_RETRIEVAL_MODE": "typo"}),
            patch("agent.load_env"),
            self.assertRaisesRegex(ValueError, "Unsupported QUESTION_RETRIEVAL_MODE"),
        ):
            agent._build_domain_context("hours")

    def test_unset_mode_defaults_to_flat_retrieval(self) -> None:
        with (
            patch.dict(os.environ),
            patch("agent.load_env"),
            patch("agent.retrieve_context", return_value="REVIEWED TOP THREE") as retrieve,
            patch("agent._select_examples", side_effect=AssertionError("Unexpected category filter")),
            patch("agent.get_memory") as memory,
        ):
            os.environ.pop("QUESTION_RETRIEVAL_MODE", None)
            memory.return_value.positive_examples.return_value = []
            memory.return_value.negative_examples.return_value = []
            context = agent._build_domain_context("study contribution percentage")
        retrieve.assert_called_once_with("study contribution percentage")
        self.assertIn("REVIEWED TOP THREE", context)

    def test_agent_injects_real_reviewed_top_three_without_category_filter(self) -> None:
        question = "study contribution percentage"
        index = get_index()
        matches = index.search(question)
        with (
            patch.dict(os.environ, {"QUESTION_RETRIEVAL_MODE": "flat_tfidf"}),
            patch("agent.load_env"),
            patch("agent._select_examples", side_effect=AssertionError("Unexpected category filter")),
            patch("agent.get_memory") as memory,
        ):
            memory.return_value.positive_examples.return_value = []
            memory.return_value.negative_examples.return_value = []
            context = agent._build_domain_context(question)
        self.assertEqual(len(matches), 3)
        self.assertIn(format_matches(matches), context)
        for match in matches:
            self.assertIn(match.question.text, context)
            for issue in match.question.issues:
                self.assertIn(issue, context)

    def test_legacy_mode_does_not_invoke_flat_retrieval(self) -> None:
        with (
            patch.dict(os.environ, {"QUESTION_RETRIEVAL_MODE": "legacy_prefix"}),
            patch("agent.load_env"),
            patch("agent.retrieve_context") as retrieve,
            patch("agent._select_examples", return_value=[]) as legacy,
            patch("agent.get_memory") as memory,
        ):
            memory.return_value.positive_examples.return_value = []
            memory.return_value.negative_examples.return_value = []
            agent._build_domain_context("hours")
        retrieve.assert_not_called()
        legacy.assert_called_once_with("hours")

    def test_both_modes_preserve_submission_relationship_guidance(self) -> None:
        for mode in ("flat_tfidf", "legacy_prefix"):
            with (
                self.subTest(mode=mode),
                patch.dict(os.environ, {"QUESTION_RETRIEVAL_MODE": mode}),
                patch("agent.load_env"),
                patch("agent.retrieve_context", return_value="TOP THREE"),
                patch("agent.get_memory") as memory,
            ):
                memory.return_value.positive_examples.return_value = []
                memory.return_value.negative_examples.return_value = []
                context = agent._build_domain_context("submission studies and DSP")
            self.assertIn(
                "(Study)-[:HAS_DELIVERY]->(Delivery)-[:SUPPORT_SUBMISSION]->(Submission)",
                context,
            )
            self.assertIn("Study_Info.DSP_Flag", context)
            self.assertIn("(Person)-[:LEADS_SUBMISSION]->(Submission)", context)

    def test_submission_examples_are_reviewed_and_retrievable(self) -> None:
        index = get_index()
        expected = {"sub001", "sub002", "sub003", "sub004"}
        self.assertEqual(
            {item.id for item in index.questions if item.source == "submission.md"},
            expected,
        )
        matches = index.search("China submission teams team lead names")
        self.assertIn("sub003", {match.question.id for match in matches})
        question = (
            "How many datasets and TLFs have been delivered for "
            "B798h NDA submission"
        )
        self.assertEqual(select_example_files(question), agent._select_examples(question))
        self.assertEqual(select_example_files(question), ["submission.md"])

    def test_published_bank_is_fully_reviewed_and_index_is_cached(self) -> None:
        index = get_index()
        self.assertIs(index, get_index())
        self.assertEqual(len(index.questions), len(load_questions()))
        self.assertEqual(len(index.search("study delivery status")), 3)
        self.assertTrue(all(item.source != "sensitive_excluded.md" for item in index.questions))


if __name__ == "__main__":
    unittest.main()
