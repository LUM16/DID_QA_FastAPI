"""Tests for the FastAPI response payload."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app import (
    CopilotTokenBody,
    FeedbackBody,
    copilot_token_status,
    feedback,
    insight_payload,
    log_query_timings,
    save_token,
)


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

    @patch("app.retrieve_copilot_token", return_value="secret-token")
    @patch("app.current_ntid", return_value="user.name")
    def test_copilot_status_does_not_return_saved_token(
        self, mock_ntid, mock_retrieve
    ) -> None:
        result = copilot_token_status(Mock(headers={}))

        self.assertEqual(result, {"saved": True, "ntid": "user.name"})
        mock_ntid.assert_called_once()
        mock_retrieve.assert_called_once_with("user.name")

    @patch("app.save_copilot_token")
    @patch("app.current_ntid", return_value="user.name")
    def test_save_copilot_token_uses_current_posit_ntid(
        self, mock_ntid, mock_save
    ) -> None:
        result = save_token(
            CopilotTokenBody(github_token="secret-token"), Mock(headers={})
        )

        self.assertEqual(result, {"saved": True, "ntid": "user.name"})
        mock_ntid.assert_called_once()
        mock_save.assert_called_once_with("user.name", "secret-token")

    @patch("app.retrieve_copilot_token", return_value="secret-token")
    @patch("app.current_ntid", return_value="")
    def test_copilot_status_uses_browser_ntid_when_cookie_is_not_forwarded(
        self, mock_ntid, mock_retrieve
    ) -> None:
        result = copilot_token_status(
            Mock(headers={}), posit_connect_ntid="user.name"
        )

        self.assertEqual(result, {"saved": True, "ntid": "user.name"})
        mock_ntid.assert_called_once()
        mock_retrieve.assert_called_once_with("user.name")

    def test_page_uses_browser_posit_connect_identity_lookup(self) -> None:
        with open("web/static/index.html", encoding="utf-8") as source_file:
            source = source_file.read()

        self.assertIn("fetch('/__api__/me'", source)
        self.assertIn("credentials:'same-origin'", source)
        self.assertIn("posit_connect_ntid", source)


if __name__ == "__main__":
    unittest.main()
