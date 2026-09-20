"""Tests for the FastAPI response payload."""

from __future__ import annotations

import unittest

from app import insight_payload


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


if __name__ == "__main__":
    unittest.main()
