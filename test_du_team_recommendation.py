"""Unit tests for rule-based DU team recommendation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from du_team_recommendation import (
    DEFAULT_SIMILARITY_CACHE_PATH,
    DEFAULT_DU_HISTORY_SNAPSHOT_PATH,
    _resolve_history_snapshot_path,
    _resolve_recommendation_cache_path,
    _scope_from_rows,
    group_lead_candidates,
    load_history_snapshot,
    recommend_teams,
    refresh_history_snapshot,
    resolve_group_lead_name,
)


class TeamRecommendationTests(unittest.TestCase):
    def test_default_history_snapshot_uses_artifact_resolver(self) -> None:
        resolved_path = Path("C:/temporary/du-history.joblib")
        with patch(
            "du_team_recommendation._resolve_prediction_artifact",
            return_value=resolved_path,
        ) as resolver:
            self.assertEqual(
                _resolve_history_snapshot_path(DEFAULT_DU_HISTORY_SNAPSHOT_PATH),
                resolved_path,
            )
        resolver.assert_called_once()

    def test_refresh_and_load_history_snapshot(self) -> None:
        history_rows = [{"du_team": "Team A", "did": "DID-A"}]
        workload_rows = [{"du_team": "Team A", "active_did_count": 2}]
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = Path(directory) / "du-history.joblib"
            with patch(
                "du_team_recommendation._read_query",
                side_effect=[history_rows, workload_rows],
            ):
                saved = refresh_history_snapshot(snapshot_path)
            loaded_history, loaded_workload, details = load_history_snapshot(snapshot_path)
        self.assertEqual(loaded_history, history_rows)
        self.assertEqual(loaded_workload, workload_rows)
        self.assertEqual(saved["history_row_count"], 1)
        self.assertEqual(details["workload_row_count"], 1)

    def test_loading_missing_history_snapshot_explains_refresh_command(self) -> None:
        missing_path = Path("C:/temporary/missing-du-history.joblib")
        with self.assertRaisesRegex(FileNotFoundError, "refresh-history"):
            load_history_snapshot(missing_path)

    def test_custom_history_snapshot_does_not_use_artifact_resolver(self) -> None:
        custom_path = Path("C:/temporary/custom-du-history.joblib")
        with patch("du_team_recommendation._resolve_prediction_artifact") as resolver:
            self.assertEqual(_resolve_history_snapshot_path(custom_path), custom_path)
        resolver.assert_not_called()

    def test_default_cache_uses_artifact_resolver(self) -> None:
        resolved_path = Path("C:/temporary/similarity.joblib")
        with patch(
            "du_team_recommendation._resolve_prediction_artifact",
            return_value=resolved_path,
        ) as resolver:
            self.assertEqual(
                _resolve_recommendation_cache_path(DEFAULT_SIMILARITY_CACHE_PATH),
                resolved_path,
            )
        resolver.assert_called_once()

    def test_custom_cache_does_not_use_artifact_resolver(self) -> None:
        custom_path = Path("C:/temporary/custom-similarity.joblib")
        with patch("du_team_recommendation._resolve_prediction_artifact") as resolver:
            self.assertEqual(_resolve_recommendation_cache_path(custom_path), custom_path)
        resolver.assert_not_called()

    def test_scope_rows_read_tlf_and_data_columns(self) -> None:
        scope = _scope_from_rows(
            [{"Title": "AE Summary", "Type": "T", "Source Datasets  ": "ADAE, ADSL"}],
            [
                {"SDTM/ADaM": "ADaM", "Domain/Dataset Name": "ADAE"},
                {"SDTM/ADaM": "SDTM", "Domain/Dataset Name": "AE"},
            ],
        )
        self.assertEqual(scope["tlfs"][0]["name"], "AE Summary")
        self.assertEqual({item["name"] for item in scope["adams"]}, {"ADAE", "ADSL"})
        self.assertEqual(scope["sdtms"][0]["name"], "AE")

    def test_group_lead_resolver_accepts_unique_name_token(self) -> None:
        candidates = group_lead_candidates(
            [{"group_leads": ["Zhang, Maggie", "Lee, Robin"]}]
        )
        self.assertEqual(resolve_group_lead_name("Maggie", candidates), "Zhang, Maggie")
        with self.assertRaisesRegex(ValueError, "uniquely match"):
            resolve_group_lead_name("Unknown", candidates)

    def test_recommendation_prefers_scope_coverage_and_reuses_cache(self) -> None:
        scope = {
            "tlfs": [{"name": "Adverse Events Summary", "type": "T", "source": "ADAE"}],
            "adams": [{"name": "ADAE"}],
            "sdtms": [{"name": "AE"}],
        }
        history = [
            {
                "du_team": "Team A", "did": "DID-A", "completion_date": "2026-09-01",
                "tlfs": [{"name": "Adverse Events Summary", "type": "T", "source": "ADAE"}],
                "adams": [{"name": "ADAE"}], "sdtms": [{"name": "AE"}],
            },
            {
                "du_team": "Team B", "did": "DID-B", "completion_date": "2026-09-01",
                "tlfs": [{"name": "Demographics Summary", "type": "T", "source": "ADSL"}],
                "adams": [{"name": "ADSL"}], "sdtms": [{"name": "DM"}],
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "similarity.joblib"
            first = recommend_teams(scope, history, [], cache_path)
            second = recommend_teams(scope, history, [], cache_path)
        self.assertEqual(first["recommendations"][0]["du_team"], "Team A")
        self.assertEqual(second["cache"]["hits"], 4)

    def test_tlf_coverage_combines_evidence_from_multiple_historical_dids(self) -> None:
        scope = {
            "tlfs": [
                {"name": "AE Summary", "type": "T", "source": "ADAE"},
                {"name": "Lab Summary", "type": "T", "source": "ADLB"},
            ],
            "adams": [],
            "sdtms": [],
        }
        history = [
            {
                "du_team": "Team A", "did": "DID-A", "completion_date": "2026-08-01",
                "tlfs": [{"name": "AE Summary", "type": "T", "source": "ADAE"}],
                "adams": [], "sdtms": [],
            },
            {
                "du_team": "Team A", "did": "DID-B", "completion_date": "2026-07-01",
                "tlfs": [{"name": "Lab Summary", "type": "T", "source": "ADLB"}],
                "adams": [], "sdtms": [],
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            result = recommend_teams(
                scope, history, [], Path(directory) / "similarity.joblib"
            )
        recommendation = result["recommendations"][0]
        self.assertEqual(recommendation["tlf_semantic_coverage"], 1.0)
        self.assertEqual(
            {
                item["target_tlf"]: item["evidence_did"]
                for item in recommendation["tlf_coverage_evidence"]
            },
            {"AE Summary": "DID-A", "Lab Summary": "DID-B"},
        )

    def test_recommendation_limits_results_to_selected_group_lead(self) -> None:
        scope = {"tlfs": [{"name": "AE Summary", "type": "T", "source": "ADAE"}]}
        history = [
            {
                "du_team": "Maggie Team", "group_leads": ["Zhang, Maggie"],
                "did": "DID-A", "completion_date": "2026-08-01",
                "tlfs": [{"name": "AE Summary", "type": "T", "source": "ADAE"}],
            },
            {
                "du_team": "Other Team", "group_leads": ["Lee, Robin"],
                "did": "DID-B", "completion_date": "2026-08-01",
                "tlfs": [{"name": "AE Summary", "type": "T", "source": "ADAE"}],
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            result = recommend_teams(
                scope,
                history,
                [],
                Path(directory) / "similarity.joblib",
                group_lead_name="Zhang, Maggie",
            )
        self.assertEqual(
            [row["du_team"] for row in result["recommendations"]], ["Maggie Team"]
        )


if __name__ == "__main__":
    unittest.main()
