"""Tests for thumbs-up example memory, export, and org-chart helpers."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import export
from example_memory import (
    ExampleMemory,
    format_negative_examples,
    format_positive_examples,
)
from result_presentation import validate_presentation_selection
from ui_results import chart_payload, org_from_rows


class ExampleMemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.memory = ExampleMemory(Path(self.tmp.name) / "examples.sqlite3")

    def tearDown(self) -> None:
        self.memory.close()
        self.tmp.cleanup()

    def test_thumbs_up_examples_are_retrieved_for_similar_questions(self) -> None:
        case_id = self.memory.add_case(
            "Show Priya's org chart",
            "MATCH (p:Person) RETURN p.Name AS person LIMIT 10",
            outcome="success",
            row_count=10,
        )
        self.memory.record_feedback(case_id, 1)
        self.memory.add_case(
            "Count ongoing deliveries",
            "MATCH (d:Delivery) RETURN count(d) AS n",
            outcome="success",
            row_count=1,
        )

        found = self.memory.positive_examples("organization chart for Priya", limit=3)
        self.assertTrue(found)
        self.assertIn("org chart", found[0]["question"].lower())
        text = format_positive_examples(found)
        self.assertIn("User-endorsed", text)
        self.assertIn("```cypher", text)

    def test_thumbs_down_excludes_a_case(self) -> None:
        case_id = self.memory.add_case(
            "List studies",
            "MATCH (s:Study) RETURN s.Name LIMIT 5",
            outcome="success",
        )
        self.memory.record_feedback(
            case_id,
            -1,
            reason="wrong_query",
            note="Uses the wrong node label",
        )
        self.assertEqual(self.memory.positive_examples("list studies"), [])
        found = self.memory.negative_examples("list studies")
        self.assertEqual(found[0]["feedback_reason"], "wrong_query")
        self.assertEqual(found[0]["feedback_note"], "Uses the wrong node label")
        self.assertIn("Do not copy", format_negative_examples(found))
        self.assertEqual(self.memory.stats()["thumbs_down"], 1)

    def test_unknown_case_does_not_report_success(self) -> None:
        self.assertFalse(self.memory.record_feedback(99999, -1))

    def test_stats_groups_feedback_reasons_by_vote(self) -> None:
        positive_id = self.memory.add_case("List studies", "MATCH (s:Study) RETURN s")
        negative_id = self.memory.add_case("List deliveries", "MATCH (d:Delivery) RETURN d")
        self.memory.record_feedback(positive_id, 1, reason="helpful")
        self.memory.record_feedback(negative_id, -1, reason="missing_data")

        summary = self.memory.stats()

        self.assertEqual(summary["feedback_reasons"]["positive"], {"helpful": 1})
        self.assertEqual(summary["feedback_reasons"]["negative"], {"missing_data": 1})


class ExportAndOrgTests(unittest.TestCase):
    def test_csv_and_json_export_flatten_nested_cells(self) -> None:
        rows = [{"person": "Riven", "reports_to": ["Maggie"]}]
        csv_text = export.to_csv(rows, ["person", "reports_to"])
        self.assertIn("person,reports_to", csv_text)
        self.assertIn("Riven", csv_text)
        payload = json.loads(export.to_json(rows, ["person", "reports_to"]))
        self.assertEqual(payload[0]["person"], "Riven")

    def test_org_from_rows_builds_reporting_edges(self) -> None:
        rows = [
            {"person": "Priya", "reporting_level": 0, "reports_to": [], "status": "Active"},
            {"person": "Alex", "reporting_level": 1, "reports_to": ["Priya"], "status": "Active"},
        ]
        graph = org_from_rows(rows, ["person", "reporting_level", "reports_to", "status"])
        self.assertIsNotNone(graph)
        self.assertEqual(graph["node_count"], 2)
        self.assertEqual(graph["edges"][0]["type"], "REPORTS_TO")
        self.assertEqual(graph["edges"][0]["source"], "Alex")
        self.assertEqual(graph["edges"][0]["target"], "Priya")

    def test_pie_selection_is_validated(self) -> None:
        result = validate_presentation_selection(
            {
                "display_type": "pie",
                "names_field": "site",
                "values_field": "hours",
                "table_fields": ["site", "hours"],
                "summary_required": False,
            },
            [{"site": "China", "hours": 10.0}, {"site": "US", "hours": 5.0}],
        )
        self.assertEqual(result["chart_type"], "pie")
        payload = chart_payload(result)
        self.assertEqual(payload[0], "pie")
        self.assertEqual(payload[1], ["China", "US"])


if __name__ == "__main__":
    unittest.main()
