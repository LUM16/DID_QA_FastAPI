"""Unit tests for rule-based DU team recommendation."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from du_team_recommendation import (
    DEFAULT_SIMILARITY_CACHE_PATH,
    DEFAULT_DU_HISTORY_SNAPSHOT_PATH,
    _resolve_history_snapshot_path,
    _resolve_recommendation_cache_path,
    _role_owned_tlfs,
    _scope_from_rows,
    group_lead_candidates,
    load_history_snapshot,
    recommend_teams,
    recommend_uploaded_scope,
    recommendation_ta_lead_candidates,
    refresh_history_snapshot,
    resolve_group_lead_name,
    ta_lead_candidates,
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
        history_rows = [{
            "du_team": "Team A", "did": "DID-A", "team_members": ["Owner"],
            "organization_mappings": [
                {"ta_lead": "TA One", "group_lead": "Group A"}
            ],
            "tlfs": [
                {"name": "Owned", "generation": "Owner", "qc": ""},
                {"name": "Observed", "generation": "Other", "qc": ""},
            ],
        }]
        workload_rows = [{"du_team": "Team A", "active_did_count": 2}]
        with tempfile.TemporaryDirectory() as directory:
            snapshot_path = Path(directory) / "du-history.joblib"
            with patch(
                "du_team_recommendation._read_query",
                side_effect=[history_rows, workload_rows],
            ):
                saved = refresh_history_snapshot(snapshot_path)
            loaded_history, loaded_workload, details = load_history_snapshot(snapshot_path)
        self.assertEqual(loaded_history[0]["tlfs"][0]["name"], "Owned")
        self.assertEqual(
            loaded_history[0]["organization_mappings"],
            [{"ta_lead": "TA One", "group_lead": "Group A"}],
        )
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

    def test_role_owned_tlfs_excludes_unowned_delivery_scope(self) -> None:
        owned = _role_owned_tlfs(
            [
                {"name": "Gen TLF", "generation": "Member A", "qc": ""},
                {"name": "QC TLF", "generation": "", "qc": ["Member B"]},
                {"name": "Unowned TLF", "generation": "Other", "qc": "Other"},
            ],
            ["Member A", "Member B"],
        )
        self.assertEqual([item["name"] for item in owned], ["Gen TLF", "QC TLF"])

    def test_group_lead_resolver_accepts_unique_name_token(self) -> None:
        candidates = group_lead_candidates(
            [{"group_leads": ["Zhang, Maggie", "Lee, Robin"]}]
        )
        self.assertEqual(resolve_group_lead_name("Maggie", candidates), "Zhang, Maggie")
        with self.assertRaisesRegex(ValueError, "uniquely match"):
            resolve_group_lead_name("Unknown", candidates)

    def test_ta_lead_filters_group_lead_candidates(self) -> None:
        history = [
            {
                "group_leads": ["Group A", "Group B"],
                "organization_mappings": [
                    {"ta_lead": "TA One", "group_lead": "Group A"},
                    {"ta_lead": "TA Two", "group_lead": "Group B"},
                ],
            }
        ]

        self.assertEqual(ta_lead_candidates(history), ["TA One", "TA Two"])
        self.assertEqual(group_lead_candidates(history, "TA One"), ["Group A"])
        self.assertEqual(group_lead_candidates(history, "TA Two"), ["Group B"])

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

    def test_recommendation_limits_results_to_selected_ta_group_path(self) -> None:
        scope = {"tlfs": [{"name": "AE Summary", "type": "T", "source": "ADAE"}]}
        history = [
            {
                "du_team": "TA One Team",
                "group_leads": ["Shared Group"],
                "organization_mappings": [
                    {"ta_lead": "TA One", "group_lead": "Shared Group"}
                ],
                "did": "DID-A",
                "completion_date": "2026-08-01",
                "tlfs": [{"name": "AE Summary", "type": "T", "source": "ADAE"}],
            },
            {
                "du_team": "TA Two Team",
                "group_leads": ["Shared Group"],
                "organization_mappings": [
                    {"ta_lead": "TA Two", "group_lead": "Shared Group"}
                ],
                "did": "DID-B",
                "completion_date": "2026-08-01",
                "tlfs": [{"name": "AE Summary", "type": "T", "source": "ADAE"}],
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            result = recommend_teams(
                scope,
                history,
                [],
                Path(directory) / "similarity.joblib",
                group_lead_name="Shared Group",
                ta_lead_name="TA One",
            )
        self.assertEqual(
                [row["du_team"] for row in result["recommendations"]],
            ["TA One Team"],
        )

    def test_recommendation_ta_choices_are_snapshot_backed_and_restricted(self) -> None:
        history = [
            {"organization_mappings": [{"ta_lead": name, "group_lead": "Group A"}]}
            for name in ["Other TA", "Iyer, Priya Venkatesan", "Shen, Henry"]
        ]
        self.assertEqual(
            recommendation_ta_lead_candidates(history),
            ["Shen, Henry", "Iyer, Priya Venkatesan"],
        )
        self.assertEqual(
            recommendation_ta_lead_candidates(history[:2]),
            ["Iyer, Priya Venkatesan"],
        )
        self.assertEqual(recommendation_ta_lead_candidates([]), [])

    def test_ta_only_ranking_compares_all_groups_and_scopes_workload(self) -> None:
        scope = {"tlfs": [{"name": "AE Summary", "type": "T", "source": "ADAE"}]}
        history = [
            {
                "du_team": team,
                "did": f"DID-{index}",
                "completion_date": date.today().isoformat(),
                "group_leads": [group],
                "organization_mappings": [{"ta_lead": ta, "group_lead": group}],
                "tlfs": scope["tlfs"],
            }
            for index, (team, ta, group) in enumerate([
                ("Henry A", "Shen, Henry", "Shared Group"),
                ("Henry B", "Shen, Henry", "Group B"),
                ("Henry C", "Shen, Henry", "Group C"),
                ("Henry D", "Shen, Henry", "Group D"),
                ("Priya A", "Iyer, Priya Venkatesan", "Shared Group"),
                ("Other A", "Other TA", "Group B"),
            ])
        ]
        workload = [
            {"du_team": row["du_team"], "active_did_count": index + 1}
            for index, row in enumerate(history[:4])
        ] + [
            {"du_team": "Priya A", "active_did_count": 1000},
            {"du_team": "Other A", "active_did_count": 2000},
        ]
        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "similarity.joblib"
            henry = recommend_teams(
                scope, history, workload, cache_path, top_n=10,
                ta_lead_name="Shen, Henry",
            )
            priya = recommend_teams(
                scope, history, workload, cache_path,
                ta_lead_name="Iyer, Priya Venkatesan",
            )
            without_other_tas = recommend_teams(
                scope, history[:4], workload[:4], cache_path, top_n=10,
                ta_lead_name="Shen, Henry",
            )
        self.assertEqual(henry["candidate_team_count"], 4)
        self.assertIsNone(henry["group_lead_name"])
        self.assertEqual(
            [row["du_team"] for row in henry["recommendations"]],
            ["Henry A", "Henry B", "Henry C", "Henry D"],
        )
        self.assertEqual(
            [row["group_leads"] for row in henry["recommendations"]],
            [["Shared Group"], ["Group B"], ["Group C"], ["Group D"]],
        )
        self.assertEqual(
            henry["recommendations"], without_other_tas["recommendations"]
        )
        self.assertAlmostEqual(henry["recommendations"][0]["score"], 85.5)
        self.assertAlmostEqual(henry["recommendations"][-1]["score"], 59.2)
        self.assertEqual(
            [row["du_team"] for row in priya["recommendations"]], ["Priya A"]
        )

    def test_uploaded_scope_no_longer_requires_a_group_lead(self) -> None:
        history = [{
            "organization_mappings": [
                {"ta_lead": "Shen, Henry", "group_lead": "Group A"}
            ]
        }]
        upload = object()
        scope = {"tlfs": [{"name": "AE Summary"}]}
        with (
            patch("du_team_recommendation.load_history_snapshot",
                  return_value=(history, [], {"generated_at": "test"})),
            patch("du_team_recommendation.load_uploaded_scope",
                  return_value=scope) as loader,
            patch("du_team_recommendation.recommend_teams",
                  return_value={}) as ranker,
        ):
            result = recommend_uploaded_scope("Shen, Henry", upload)
        loader.assert_called_once_with(upload, None, require_data=False)
        ranker.assert_called_once_with(
            scope, history, [], ta_lead_name="Shen, Henry"
        )
        self.assertEqual(result["history_snapshot"], {"generated_at": "test"})

    def test_uploaded_scope_rejects_unsupported_or_unavailable_ta(self) -> None:
        with (
            patch("du_team_recommendation.load_history_snapshot",
                  return_value=([], [], {})),
            patch("du_team_recommendation.load_uploaded_scope") as loader,
        ):
            for name in ["Other TA", "Shen, Henry", "Iyer, Priya Venkatesan"]:
                with self.subTest(name=name):
                    with self.assertRaisesRegex(ValueError, "Select Henry or Priya"):
                        recommend_uploaded_scope(name, object())
        loader.assert_not_called()

    def test_team_tab_has_one_ta_selector_and_ranks_across_groups(self) -> None:
        from fastapi.testclient import TestClient
        from app import app

        history = [
            {
                "du_team": team, "did": team,
                "completion_date": date.today().isoformat(),
                "group_leads": [group],
                "organization_mappings": [{"ta_lead": ta, "group_lead": group}],
                "tlfs": [{"name": "AE Summary", "type": "T", "source": "ADAE"}],
            }
            for team, ta, group in [
                ("Team A", "Shen, Henry", "Group A"),
                ("Team B", "Shen, Henry", "Group B"),
                ("Team C", "Iyer, Priya Venkatesan", "Group C"),
            ]
        ]
        snapshot = {"generated_at": "test", "history_row_count": 3}
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("du_team_recommendation.load_history_snapshot",
                  return_value=(history, [], snapshot)),
            patch("du_team_recommendation._resolve_recommendation_cache_path",
                  return_value=Path(directory) / "similarity.joblib"),
            patch("planning_api.load_history_snapshot",
                  return_value=(history, [], snapshot)),
        ):
            client = TestClient(app)
            self.assertEqual(
                client.get("/api/planning/recommend/options").json()["ta_leads"],
                ["Shen, Henry", "Iyer, Priya Venkatesan"],
            )
            for ta, expected in [
                ("Shen, Henry", {"Team A", "Team B"}),
                ("Iyer, Priya Venkatesan", {"Team C"}),
            ]:
                response = client.post(
                    "/api/planning/recommend",
                    data={"ta_lead_name": ta},
                    files={"primary_file": ("scope.csv", b"Title,Type,Source Datasets\nAE Summary,T,ADAE\n", "text/csv")},
                )
                self.assertEqual(response.status_code, 200)
                result = response.json()
                self.assertEqual(
                    {row["du_team"] for row in result["recommendations"]}, expected
                )
                self.assertIsNone(result["group_lead_name"])
            script = client.get("/static/planning.js").text
            self.assertIn("Select a TA Lead name…", script)
            self.assertIn("placeholder.value = ''; placeholder.disabled = true", script)
            self.assertIn("mode === 'recommend' ? 'TA Lead name'", script)
            self.assertNotIn("optional for recommendation", script)
            self.assertNotIn("Group Lead name", script)
            self.assertNotIn("DU", script)


if __name__ == "__main__":
    unittest.main()
