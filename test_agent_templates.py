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
        self.assertNotIn("d.SDSA_China_PoC", cypher)
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

    def test_china_submission_teams_return_team_leads_only(self) -> None:
        cypher = agent.template_cypher(
            "which teams across China supported Litfulo vitiligo submission"
        )
        self.assertIsNotNone(cypher)
        self.assertIn("p.Team_Lead_Name", cypher)
        self.assertIn("AS Team_Lead", cypher)
        self.assertIn('CONTAINS "LITFULO"', cypher)
        self.assertIn('CONTAINS "VITILIGO"', cypher)
        self.assertNotIn("'Delivery contributor'", cypher)
        self.assertNotIn("AS Person", cypher)
        people = agent.template_cypher(
            "Who in China contributed to Litfulo vitiligo submission"
        )
        self.assertIn("'Delivery contributor'", people)
        self.assertNotIn("AS Team_Lead", people)

    def test_submission_delivered_datasets_and_tlfs(self) -> None:
        question = (
            "How many datasets and TLFs have been delivered for "
            "B798h – Submit NDA (R1, 50 & 100mg, IA) submission"
        )
        cypher = agent.template_cypher(question)
        self.assertIsNotNone(cypher)
        self.assertIn('CONTAINS "B798H"', cypher)
        self.assertIn('CONTAINS "NDA"', cypher)
        self.assertNotIn("100MG", cypher)
        self.assertNotIn("R1", cypher)
        self.assertNotIn("Project_Name", cypher)
        self.assertIn("d.Actual_Delivery_Date IS NOT NULL", cypher)
        self.assertIn("d.CSR_ADaM_Num_Total AS ADaM_Datasets", cypher)
        self.assertIn("d.CSR_SDTM_Num_Total AS SDTM_Datasets", cypher)
        self.assertIn("d.CSR_TLF_Num_Total AS TLFs", cypher)
        self.assertIn("[:HAS_DELIVERY]->(d:Delivery)-[:SUPPORT_SUBMISSION]", cypher)
        self.assertNotIn("HAS_TLF", cypher)
        self.assertNotIn("HAS_SDTM", cypher)
        self.assertNotIn("HAS_ADAM", cypher)
        self.assertEqual(agent._select_examples(question), ["submission.md"])

    def test_submission_delivered_artifacts_skip_llm(self) -> None:
        question = (
            "How many datasets and TLFs have been delivered for "
            "B798h – Submit NDA (R1, 50 & 100mg, IA) submission"
        )
        rows = [
            {
                "Submission": "B798h – Submit NDA (R1, 50 & 100mg, IA)",
                "Study": "B7981001",
                "Delivery": "B7981001_1",
                "Reporting_Event": "Interim Analysis",
                "Planned_Delivery_Date": "2024-01-01",
                "Actual_Delivery_Date": "2024-01-15",
                "ADaM_Datasets": 4,
                "SDTM_Datasets": 8,
                "TLFs": 30,
            }
        ]
        with (
            patch("agent.run_cypher", return_value=rows),
            patch("agent._chat") as mock_chat,
            patch("agent.get_schema") as mock_get_schema,
            patch("agent._build_domain_context") as mock_context,
        ):
            result = agent.ask(question)

            mock_chat.assert_not_called()
            mock_get_schema.assert_not_called()
            mock_context.assert_not_called()
        self.assertIn('CONTAINS "B798H"', result["cypher"])
        self.assertIn('CONTAINS "NDA"', result["cypher"])
        self.assertEqual(
            result["answer"],
            "Delivered **12** datasets (**8** SDTM, **4** ADaM) "
            "and **30** TLFs across **1** delivery. "
            "Counts for each delivery are in the table below.",
        )
        self.assertEqual(result["rows"], rows)

    def test_submission_hours_match_project_name_or_name(self) -> None:
        cypher = agent.template_cypher(
            "how many hours were spent on Litfulo vitiligo submission by each individual"
        )
        self.assertIsNotNone(cypher)
        self.assertIn("sub.Project_Name", cypher)
        self.assertIn("sub.Name", cypher)
        self.assertIn('CONTAINS "LITFULO"', cypher)
        self.assertIn('CONTAINS "VITILIGO"', cypher)
        self.assertNotIn("LITFULO VITILIGO", cypher)
        self.assertIn("[:TIME_ON]->", cypher)
        self.assertIn("DIDN_Month", cypher)
        self.assertIn("DID0_Month", cypher)
        self.assertNotIn("all(kw IN kws", cypher)
        self.assertNotIn("$", cypher)


if __name__ == "__main__":
    unittest.main()
