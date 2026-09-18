"""Unit tests for prediction-snapshot validation."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from validate_effort_predictions import comparison_metrics, validate_prediction_snapshot


class PredictionValidationTests(unittest.TestCase):
    def test_metrics_measure_errors_and_interval_coverage(self) -> None:
        metrics = comparison_metrics(
            [
                {"actual_hours": 12, "p50_hours": 10, "p80_hours": 13, "p90_hours": 15},
                {"actual_hours": 20, "p50_hours": 25, "p80_hours": 28, "p90_hours": 30},
            ]
        )

        self.assertEqual(metrics["mae_hours"], 3.5)
        self.assertEqual(metrics["mean_error_hours"], -1.5)
        self.assertEqual(metrics["p80_coverage"], 1.0)
        self.assertEqual(metrics["p90_coverage"], 1.0)

    def test_validation_writes_completed_rows_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path = root / "predictions.csv"
            comparison_path = root / "comparison.csv"
            report_path = root / "report.md"
            with snapshot_path.open("w", encoding="utf-8", newline="") as snapshot_file:
                writer = csv.DictWriter(
                    snapshot_file,
                    fieldnames=[
                        "person", "did", "predicted_at", "as_of_date",
                        "model_version", "p50_hours", "p80_hours", "p90_hours",
                    ],
                )
                writer.writeheader()
                writer.writerows(
                    [
                        {
                            "person": "Person A", "did": "DID-1",
                            "predicted_at": "2026-01-01T00:00:00+00:00",
                            "as_of_date": "2026-01-01",
                            "model_version": "v3", "p50_hours": 10,
                            "p80_hours": 15, "p90_hours": 20,
                        },
                        {
                            "person": "Person B", "did": "DID-2",
                            "predicted_at": "2026-01-01T00:00:00+00:00",
                            "as_of_date": "2026-01-01",
                            "model_version": "v3", "p50_hours": 10,
                            "p80_hours": 15, "p90_hours": 20,
                        },
                    ]
                )
            with patch(
                "validate_effort_predictions.load_completed_actuals",
                return_value={
                    ("Person A", "DID-1"): {
                        "completed_date": "2026-02-01",
                        "actual_hours": 12,
                        "actual_time_record_count": 2,
                    }
                },
            ):
                result = validate_prediction_snapshot(
                    snapshot_path, comparison_path, report_path
                )
            with comparison_path.open(encoding="utf-8-sig", newline="") as comparison_file:
                rows = list(csv.DictReader(comparison_file))
            report = report_path.read_text(encoding="utf-8")

        self.assertEqual(result["snapshot_rows"], 2)
        self.assertEqual(result["completed_rows"], 1)
        self.assertEqual(rows[0]["actual_hours"], "12.0")
        self.assertEqual(rows[0]["p80_covered"], "True")
        self.assertIn("Now completed and compared: **1**", report)


if __name__ == "__main__":
    unittest.main()
