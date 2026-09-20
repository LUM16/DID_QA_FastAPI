"""Tests for safe post-query result presentation."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import agent
from result_presentation import select_result_presentation, validate_presentation_selection


class ResultPresentationTests(unittest.TestCase):
    def test_chart_selection_uses_only_returned_fields_and_keeps_table_fallback(self) -> None:
        rows = [{"month": "2026-08", "hours": 10.5}, {"month": "2026-09", "hours": 12.0}]

        result, usage, warning = select_result_presentation(
            "Show the monthly trend",
            rows,
            lambda *_: (
                json.dumps(
                    {
                        "display_type": "line",
                        "x_field": "month",
                        "y_fields": ["hours"],
                        "series_field": None,
                        "table_fields": ["month", "hours"],
                        "summary_required": False,
                    }
                ),
                {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            ),
        )

        self.assertEqual(result["chart_type"], "line")
        self.assertEqual(result["table"]["rows"], rows)
        self.assertEqual(result["data_note"], "Recorded TIME_ON hours.")
        self.assertEqual(usage["total_tokens"], 5)
        self.assertIsNone(warning)

    def test_invalid_fields_or_nonfinite_chart_values_are_rejected(self) -> None:
        self.assertIsNone(
            validate_presentation_selection(
                {
                    "display_type": "bar",
                    "x_field": "person",
                    "y_fields": ["invented_hours"],
                    "series_field": None,
                    "table_fields": ["person"],
                },
                [{"person": "A", "hours": 1.0}],
            )
        )
        self.assertIsNone(
            validate_presentation_selection(
                {
                    "display_type": "bar",
                    "x_field": "person",
                    "y_fields": ["hours"],
                    "series_field": None,
                    "table_fields": ["person", "hours"],
                },
                [{"person": "A", "hours": float("nan")}],
            )
        )

    def test_table_selection_uses_deterministic_task_count_note(self) -> None:
        rows = [{"person": "A", "task_count": 4}]
        result, _, warning = select_result_presentation(
            "Show assignments",
            rows,
            lambda *_: (
                '{"display_type":"kpi_table","table_fields":["person","task_count"],'
                '"summary_required":false}',
                {},
            ),
        )
        self.assertEqual(result["display_type"], "kpi_table")
        self.assertEqual(result["data_note"], "Assigned task count.")
        self.assertIn("table", result)
        self.assertIsNone(warning)

    def test_table_formats_nested_values_as_readable_scalar_cells(self) -> None:
        result = validate_presentation_selection(
            {
                "display_type": "table",
                "table_fields": ["person", "assignment_examples"],
                "summary_required": False,
            },
            [
                {
                    "person": "Riven",
                    "assignment_examples": [
                        {"domain": "AE", "role": "QC"},
                        {"domain": "DM", "role": "QC"},
                    ],
                }
            ],
        )

        self.assertEqual(
            result["table"]["rows"][0]["assignment_examples"],
            "domain: AE; role: QC | domain: DM; role: QC",
        )

    def test_chart_rejects_nested_category_values(self) -> None:
        self.assertIsNone(
            validate_presentation_selection(
                {
                    "display_type": "bar",
                    "x_field": "assignment",
                    "y_fields": ["task_count"],
                    "series_field": None,
                    "table_fields": ["assignment", "task_count"],
                    "summary_required": False,
                },
                [{"assignment": {"domain": "AE"}, "task_count": 1}],
            )
        )

    def test_line_chart_requires_a_month_or_date_x_field(self) -> None:
        self.assertIsNone(
            validate_presentation_selection(
                {
                    "display_type": "line",
                    "x_field": "person",
                    "y_fields": ["hours"],
                    "series_field": None,
                    "table_fields": ["person", "hours"],
                    "summary_required": False,
                },
                [{"person": "A", "hours": 2.0}],
            )
        )

    @patch("agent.run_cypher", return_value=[{"month": "2026-09", "hours": 5.0}])
    @patch("agent._chat")
    def test_visual_only_presentation_skips_text_answer(
        self, mock_chat, _mock_run_cypher
    ) -> None:
        mock_chat.side_effect = [
            ("```cypher\nMATCH (n) RETURN '2026-09' AS month, 5.0 AS hours\n```", {}),
            (
                '{"display_type":"line","x_field":"month","y_fields":["hours"],'
                '"series_field":null,"table_fields":["month","hours"],'
                '"summary_required":false}',
                {},
            ),
        ]
        with patch(
            "agent.classify_effort_prediction_intent",
            return_value=(False, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
        ):
            result = agent.ask("Show monthly hours", schema={"labels": []})

        self.assertEqual(mock_chat.call_count, 2)
        self.assertEqual(result["answer"], "")
        self.assertIsNotNone(result["visualization"])
        self.assertEqual(
            set(result["timings_ms"]),
            {"intent", "prepare", "cypher_generation", "neo4j", "presentation"},
        )
        self.assertTrue(all(value >= 0 for value in result["timings_ms"].values()))

    @patch("agent.run_cypher", return_value=[{"month": "2026-09", "hours": 5.0}])
    @patch("agent._chat")
    def test_requested_summary_is_concise_without_duplicate_rows(
        self, mock_chat, _mock_run_cypher
    ) -> None:
        mock_chat.side_effect = [
            ("```cypher\nMATCH (n) RETURN '2026-09' AS month, 5.0 AS hours\n```", {}),
            (
                '{"display_type":"line","x_field":"month","y_fields":["hours"],'
                '"series_field":null,"table_fields":["month","hours"],'
                '"summary_required":true}',
                {},
            ),
            ("September recorded hours were 5.0.", {"total_tokens": 4}),
        ]
        with patch(
            "agent.classify_effort_prediction_intent",
            return_value=(False, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
        ):
            result = agent.ask("Compare monthly hours", schema={"labels": []})

        answer_prompt = mock_chat.call_args_list[2].args[0]
        self.assertIn("do not output a markdown table", answer_prompt)
        self.assertEqual(result["answer"], "September recorded hours were 5.0.")

    @patch("agent.run_cypher", return_value=[{"study": "C100", "delivery_count": 2}])
    @patch("agent._chat")
    def test_failed_presentation_selection_does_not_fail_generic_qa(
        self, mock_chat, mock_run_cypher
    ) -> None:
        mock_chat.side_effect = [
            ("```cypher\nMATCH (s:Study) RETURN s.Name AS study, 2 AS delivery_count\n```", {}),
            RuntimeError("presentation service unavailable"),
            ("C100 has two deliveries.", {"total_tokens": 4}),
        ]
        with patch(
            "agent.classify_effort_prediction_intent",
            return_value=(False, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
        ):
            result = agent.ask("Show monthly hours by study", schema={"labels": []})

        self.assertIsNone(result["error"])
        self.assertEqual(result["answer"], "C100 has two deliveries.")
        self.assertEqual(result["rows"], [{"study": "C100", "delivery_count": 2}])
        self.assertIsNone(result["visualization"])
        self.assertEqual(
            result["presentation_warning"],
            "Presentation is unavailable; showing the text answer only.",
        )
        mock_run_cypher.assert_called_once()


if __name__ == "__main__":
    unittest.main()
