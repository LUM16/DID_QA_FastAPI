"""Tests for Study and Delivery profile enrichment."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import agent
from entity_profiles import (
    DETAIL_TITLE,
    collect_entities,
    delivery_lookup_cypher,
    prepare_entity_presentation,
    render_entity_presentation,
    study_lookup_cypher,
)
from neo4j_client import ensure_read_only


def _study(name: str, priority: str = "High") -> dict[str, str]:
    return {
        "Study": name,
        "Plan_Phase": "Phase 3",
        "TA": "Oncology",
        "Study_Priority": priority,
        "SDSL": "Jane Doe",
        "SDSL_Delivery": f"{name}_9",
    }


def _delivery(name: str) -> dict[str, str]:
    return {
        "Name": name,
        "DID": name,
        "Reporting_Event": "Clinical Study Report",
        "Reporting_Detail": "Final",
        "Planned_Delivery_Date": "2026-03-01",
        "SDSL": "Jane Doe",
    }


class EntityProfileTests(unittest.TestCase):
    def test_schema_documents_study_priority_and_delivery_sdsl(self) -> None:
        schema = agent._read_doc("schema.md")
        self.assertIn("- `Study_Priority`", schema)
        self.assertIn("`SDSL` is not a `Study_Info` property.", schema)
        self.assertIn("Study_Priority", schema[:6000])
        skill = agent._read_doc("skill.md")
        self.assertIn("Study_Priority", skill[:3000])
        self.assertIn("SDSL` is not a `Study_Info` property.", skill[:3000])

    def test_study_lookup_uses_latest_delivery_sdsl(self) -> None:
        cypher = study_lookup_cypher(["C3441021"])
        ensure_read_only(cypher)
        self.assertIn("Study_Priority", cypher)
        self.assertIn("[:HAS_DETAIL]->(si:Study_Info)", cypher)
        self.assertIn("[:HAS_DELIVERY]->(d:Delivery)", cypher)
        self.assertIn("latest.SDSL AS SDSL", cypher)
        self.assertIn("Actual_Delivery_Date", cypher)
        self.assertIn("Planned_Delivery_Date", cypher)
        self.assertNotIn("si.SDSL", cypher)
        self.assertIn('"C3441021"', cypher)

    def test_collects_returned_study_and_delivery_identifiers(self) -> None:
        cypher = """MATCH (s:Study)-[:HAS_DELIVERY]->(d:Delivery)
RETURN s.Name AS Study, d.DID AS DID
ORDER BY d.DID"""
        studies, deliveries = collect_entities(
            [{"Study": "C3441021", "DID": "C3441021_9"}],
            cypher,
            {},
        )
        self.assertEqual(studies, ["C3441021"])
        self.assertEqual(deliveries, [("did", "C3441021_9")])

    def test_collects_graph_nodes_and_raw_return_keys(self) -> None:
        studies, deliveries = collect_entities(
            [{"s.Name": "C1071007"}],
            "MATCH (s:Study) RETURN s.Name",
            {
                "nodes": [
                    {
                        "label": "Delivery",
                        "labels": ["Delivery"],
                        "properties": {"Name": "C1071007_3", "DID": "C1071007_3"},
                    }
                ]
            },
        )
        self.assertEqual(studies, ["C1071007"])
        self.assertEqual(deliveries, [("name", "C1071007_3")])

    def test_five_profiles_stay_in_the_answer(self) -> None:
        inline, panel = render_entity_presentation(
            [_study(f"C{i}") for i in range(5)],
            [_delivery("C0_1")],
            chinese=False,
        )
        self.assertIsNone(panel)
        self.assertIn("**Study**", inline)
        self.assertIn("Plan_Phase: Phase 3", inline)
        self.assertIn("Study_Priority: High", inline)
        self.assertIn("SDSL: Jane Doe (C0_9)", inline)
        self.assertIn("Reporting_Event: Clinical Study Report", inline)
        self.assertNotIn(DETAIL_TITLE, inline)

    def test_more_than_five_profiles_are_collapsed(self) -> None:
        inline, panel = render_entity_presentation(
            [_study(f"C{i}") for i in range(6)],
            [_delivery("C0_1")],
            chinese=True,
        )
        self.assertIn("**Delivery 基本信息**", inline)
        self.assertNotIn("**Study 基本信息**", inline)
        self.assertIsNotNone(panel)
        assert panel is not None
        self.assertEqual(panel["title"], DETAIL_TITLE)
        self.assertEqual(len(panel["studies"]), 6)
        self.assertEqual(panel["deliveries"], [])
        self.assertEqual(panel["studies"][0]["SDSL"], "Jane Doe (C0_9)")

    def test_lookup_ignores_rows_that_are_not_profiles(self) -> None:
        presentation = prepare_entity_presentation(
            [{"Study": "C3441021", "DSP_Category": "DSP"}],
            "MATCH (s:Study) RETURN s.Name AS Study",
            {},
            chinese=False,
            query=lambda _cypher: [{"Study": "C3441021", "DSP_Category": "DSP"}],
        )
        self.assertEqual(presentation.inline, "")
        self.assertIsNone(presentation.panel)
        self.assertTrue(presentation.looked_up)

    def test_ask_appends_study_profile_and_keeps_conclusion_short(self) -> None:
        def fake(query: str, limit_rows: int = 200, record_meta: bool = True):
            if "Study_Priority" in query:
                self.assertFalse(record_meta)
                self.assertNotIn("si.SDSL", query)
                return [_study("C3441021")]
            return [{"Study": "C3441021", "DSP_Category": "DSP"}]

        with (
            patch("agent.run_cypher", side_effect=fake),
            patch("agent._chat") as mock_chat,
            patch("agent.get_schema"),
            patch("agent._build_domain_context"),
        ):
            result = agent.ask(
                "Please list the studies that contribute to Litfulo vitiligo submission and show study DSP category"
            )

        mock_chat.assert_not_called()
        self.assertTrue(result["answer"].startswith("Found **1** study."))
        self.assertIn("Plan_Phase: Phase 3", result["answer"])
        self.assertIn("TA: Oncology", result["answer"])
        self.assertIn("Study_Priority: High", result["answer"])
        self.assertIn("SDSL: Jane Doe (C3441021_9)", result["answer"])
        self.assertIsNone(result["entity_details"])

    def test_ask_collapses_more_than_five_deliveries(self) -> None:
        main_rows = [
            {"Delivery": f"C1071007_{i}", "DID": f"C1071007_{i}", "Status": "Completed"}
            for i in range(6)
        ]

        def fake(query: str, limit_rows: int = 200, record_meta: bool = True):
            if "Reporting_Event" in query:
                self.assertFalse(record_meta)
                return [_delivery(f"C1071007_{i}") for i in range(6)]
            return main_rows

        with (
            patch("agent.run_cypher", side_effect=fake),
            patch("agent._chat") as mock_chat,
            patch("agent.get_schema"),
            patch("agent._build_domain_context"),
        ):
            result = agent.ask("List completed deliveries for study C1071007")

        mock_chat.assert_not_called()
        self.assertEqual(
            result["answer"],
            "Found **6** matching deliveries. See the table below for details.",
        )
        details = result["entity_details"]
        self.assertEqual(details["title"], DETAIL_TITLE)
        self.assertEqual(len(details["deliveries"]), 6)
        self.assertEqual(details["deliveries"][0]["Name"], "C1071007_0")
        self.assertEqual(details["deliveries"][0]["Reporting_Detail"], "Final")
        self.assertEqual(details["deliveries"][0]["SDSL"], "Jane Doe")
        self.assertEqual(details["studies"], [])
        ensure_read_only(delivery_lookup_cypher(["C1071007_0"], ["C1071007_0"]))


if __name__ == "__main__":
    unittest.main()
