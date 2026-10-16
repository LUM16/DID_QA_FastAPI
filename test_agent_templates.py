"""Tests for deterministic Cypher templates and local answers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import agent


ZERO_USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


class AgentTemplateTests(unittest.TestCase):
    def test_did_status_template_skips_generation_and_answer_llms(self) -> None:
        with (
            patch("agent.classify_effort_prediction_intent") as mock_intent,
            patch("agent.run_cypher", return_value=[{"DID": "C1071007_142", "Status": "Completed"}]),
            patch("agent._chat") as mock_chat,
            patch("agent.get_schema") as mock_get_schema,
            patch("agent._build_domain_context") as mock_context,
        ):
            result = agent.ask("Show DID C1071007_142 status")

            mock_intent.assert_not_called()
            mock_chat.assert_not_called()
            mock_get_schema.assert_not_called()
            mock_context.assert_not_called()
        self.assertEqual(result["answer"], "C1071007_142 status is **Completed**.")
        self.assertNotIn("cypher_generation", result["timings_ms"])
        self.assertNotIn("answer_generation", result["timings_ms"])
        self.assertEqual(result["usage"], ZERO_USAGE)

    def test_completed_delivery_template_returns_local_table_summary(self) -> None:
        rows = [
            {
                "Delivery": "C1071007_1",
                "DID": "C1071007_1",
                "Status": "Completed",
            },
            {
                "Delivery": "C1071007_2",
                "DID": "C1071007_2",
                "Status": "Completed",
            },
        ]
        with (
            patch("agent.classify_effort_prediction_intent") as mock_intent,
            patch("agent.run_cypher", return_value=rows),
            patch("agent._chat") as mock_chat,
            patch("agent.get_schema") as mock_get_schema,
            patch("agent._build_domain_context") as mock_context,
        ):
            result = agent.ask("List completed deliveries for study C1071007")

            mock_intent.assert_not_called()
            mock_chat.assert_not_called()
            mock_get_schema.assert_not_called()
            mock_context.assert_not_called()
        self.assertEqual(
            result["answer"],
            "Found **2** matching deliveries. See the table below for details.",
        )
        self.assertNotIn("cypher_generation", result["timings_ms"])
        self.assertNotIn("answer_generation", result["timings_ms"])
        self.assertIsNotNone(result["visualization"])

    def test_submission_study_template_splits_keywords_and_uses_real_paths(self) -> None:
        cypher = agent.template_cypher(
            "Please list the studies that contribute to Litfulo vitiligo submission and show study DSP category"
        )
        self.assertIsNotNone(cypher)
        self.assertIn('CONTAINS "LITFULO"', cypher)
        self.assertIn('CONTAINS "VITILIGO"', cypher)
        self.assertNotIn("LITFULO VITILIGO", cypher)
        self.assertIn("sub.Project_Name", cypher)
        self.assertIn("sub.Name", cypher)
        self.assertIn("[:HAS_DELIVERY]->(d:Delivery)-[:SUPPORT_SUBMISSION]", cypher)
        self.assertIn("[:HAS_DID0]->(did0:DID0)-[:SUPPORT_SUBMISSION]", cypher)
        self.assertIn("si.DSP_Flag AS DSP_Category", cypher)
        self.assertNotIn("HAS_SDTM", cypher)
        self.assertNotIn("HAS_ADAM", cypher)
        self.assertNotIn("HAS_TLF", cypher)

    def test_submission_study_question_skips_llm(self) -> None:
        rows = [{"Study": "C3441021", "DSP_Category": "DSP"}]
        with (
            patch("agent.run_cypher", return_value=rows),
            patch("agent._chat") as mock_chat,
            patch("agent.get_schema") as mock_get_schema,
            patch("agent._build_domain_context") as mock_context,
        ):
            result = agent.ask(
                "Please list the studies that contribute to Litfulo vitiligo submission and show study DSP category"
            )

            mock_chat.assert_not_called()
            mock_get_schema.assert_not_called()
            mock_context.assert_not_called()
        self.assertIn('CONTAINS "LITFULO"', result["cypher"])
        self.assertIn('CONTAINS "VITILIGO"', result["cypher"])
        self.assertNotIn("HAS_SDTM", result["cypher"])
        self.assertEqual(
            result["answer"],
            "Found **1** study. DSP category is in the table below.",
        )
        self.assertEqual(result["rows"], rows)

    def test_china_submission_contributors_use_site_sdsl_and_poc(self) -> None:
        cypher = agent.template_cypher(
            "Who in China contributed to Litfulo vitiligo submission"
        )
        self.assertIsNotNone(cypher)
        self.assertIn('CONTAINS "LITFULO"', cypher)
        self.assertIn('CONTAINS "VITILIGO"', cypher)
        self.assertNotIn("LITFULO VITILIGO", cypher)
        self.assertIn("[:WORKS_ON]->(d:Delivery)-[:SUPPORT_SUBMISSION]", cypher)
        self.assertIn("[:FROM_SITE]->(site:Site)", cypher)
        self.assertIn("toUpper(trim(site.Name)) = 'CHINA'", cypher)
        self.assertIn("s.SDSL", cypher)
        self.assertIn("d.SDSA_China_PoC", cypher)
        self.assertIn("s.SDSA_China_PoC", cypher)
        self.assertIn("'Delivery contributor'", cypher)
        self.assertIn("'Study SDSL'", cypher)
        self.assertIn("'China PoC'", cypher)
        self.assertNotIn("OPTIONAL MATCH (p)-[:FROM_SITE]", cypher)
        study_cypher = agent.template_cypher(
            "Please list the studies that contribute to Litfulo vitiligo submission and show study DSP category"
        )
        self.assertIn("si.DSP_Flag AS DSP_Category", study_cypher)
        self.assertNotIn("SDSA_China_PoC", study_cypher)


if __name__ == "__main__":
    unittest.main()
