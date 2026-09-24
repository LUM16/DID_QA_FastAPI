"""Tests for the FastAPI response payload."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app import FeedbackBody, feedback, insight_payload, log_query_timings


class InsightPayloadTests(unittest.TestCase):
    def test_includes_stage_and_total_timings(self) -> None:
        payload = insight_payload(
            {
                "answer": "Done",
                "rows": [],
                "timings_ms": {
                    "intent": 3.9,
                    "cypher_generation": 120,
                    "invalid": "slow",
                },
            },
            elapsed_ms=150,
        )

        self.assertEqual(
            payload["timings_ms"],
            {"intent": 3, "cypher_generation": 120, "total": 150},
        )
        self.assertEqual(payload["elapsed_ms"], 150)

    @patch("app.TIMING_LOG.info")
    def test_logs_stage_timings_to_server_console(self, mock_info) -> None:
        log_query_timings(
            {
                "timings_ms": {
                    "intent": 3,
                    "neo4j": 40,
                    "answer_generation": 70,
                    "total": 120,
                },
                "row_count": 2,
                "error": None,
            }
        )

        mock_info.assert_called_once_with(
            "DID query timings | %s | rows=%s | status=%s",
            "intent=3ms | neo4j=40ms | answer_generation=70ms | total=120ms",
            2,
            "ok",
        )

    @patch("app.get_memory")
    def test_positive_feedback_uses_helpful_reason(self, mock_get_memory) -> None:
        memory = Mock()
        memory.record_feedback.return_value = True
        mock_get_memory.return_value = memory

        result = feedback(FeedbackBody(case_id=42, vote=1))

        self.assertEqual(result, {"ok": True, "case_id": 42, "vote": 1, "reason": "helpful"})
        memory.record_feedback.assert_called_once_with(42, 1, reason="helpful", note="")

    def test_positive_feedback_rejects_negative_reason(self) -> None:
        with self.assertRaisesRegex(HTTPException, "Positive feedback"):
            feedback(FeedbackBody(case_id=42, vote=1, reason="wrong_data"))


if __name__ == "__main__":
    unittest.main()
