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


if __name__ == "__main__":
    unittest.main()
