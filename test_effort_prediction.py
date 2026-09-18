"""Unit tests for the DID effort prediction pipeline."""

from __future__ import annotations

import csv
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np

from effort_prediction import (
    TARGET_QUERY,
    TRAINING_QUERY,
    ONGOING_ASSIGNMENTS_QUERY,
    _apply_prediction_policy,
    _is_lfs_pointer,
    _load_similarity_cache,
    _save_similarity_cache,
    _select_prediction_policy,
    _select_person_name,
    _similarity_candidates,
    _tlf_semantic_similarity,
    _title_similarity,
    build_feature_row,
    build_training_features,
    clean_training_records,
    export_ongoing_predictions,
    person_name_candidates,
    predict_record,
    quality_report,
    train_model,
)


def make_record(index: int, person: str = "Person A") -> dict:
    completion = date(2024, 1, 1) + timedelta(days=index * 14)
    task_count = 5 + index % 5
    return {
        "person": person,
        "did": f"DID-{index:03d}",
        "study": f"STUDY-{index // 2}",
        "completion_date": completion.isoformat(),
        "actual_hours": 4.0 * task_count + (index % 3),
        "task_count": task_count,
        "task_generation_count": task_count,
        "task_qc_count": 0,
        "tlf_count": 2,
        "tlf_generation_count": 2,
        "tlf_qc_count": 0,
        "adam_count": 1,
        "adam_generation_count": 1,
        "adam_qc_count": 0,
        "sdtm_count": 1,
        "sdtm_generation_count": 1,
        "sdtm_qc_count": 0,
        "ta": "Oncology",
        "study_type": "Phase 3",
        "reporting_event": "Primary",
        "draft_or_final": "Final",
        "tlfs": [
            {
                "name": f"TLF-{index % 4}",
                "generation": person,
                "qc": None,
            }
        ],
        "adams": [{"name": "ADSL", "generation": person, "qc": None}],
        "sdtms": [{"name": "DM", "generation": person, "qc": None}],
        "work_on_rel_count": 1,
        "study_count": 1,
        "time_record_count": 1,
    }


class EffortPredictionTests(unittest.TestCase):
    def test_person_name_resolution_accepts_ordering_and_unique_aliases(self) -> None:
        candidates = (
            "Lu, Manman",
            "Chen, Zhenchao (Riven)",
            "Zhou, Feifeng",
        )

        self.assertEqual(
            _select_person_name("Manman Lu", candidates), "Lu, Manman"
        )
        self.assertEqual(
            _select_person_name("Riven", candidates), "Chen, Zhenchao (Riven)"
        )
        self.assertEqual(
            _select_person_name("feifeng zhou", candidates), "Zhou, Feifeng"
        )

    def test_person_name_resolution_rejects_ambiguous_aliases(self) -> None:
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            _select_person_name(
                "Manman", ("Lu, Manman (Manman)", "Wang, Manman (Manman)")
            )

    def test_person_name_candidates_rank_close_database_names(self) -> None:
        with patch("effort_prediction._available_person_names", return_value=(
            "Lu, Manman",
            "Chen, Zhenchao (Riven)",
            "Zhou, Feifeng",
        )):
            candidates = person_name_candidates("LUMANMAN")

        self.assertEqual(candidates[0], "Lu, Manman")

    def test_lfs_pointer_is_not_treated_as_a_model(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            pointer_path = Path(directory) / "model.joblib"
            pointer_path.write_bytes(
                b"version https://git-lfs.github.com/spec/v1\n"
                b"oid sha256:example\nsize 123\n"
            )

            self.assertTrue(_is_lfs_pointer(pointer_path))

    def test_title_similarity_matches_reworded_tlf_titles(self) -> None:
        similar = _title_similarity(
            "Summary of Treatment-Emergent Adverse Events",
            "Treatment Emergent Adverse Event Summary",
        )
        unrelated = _title_similarity(
            "Summary of Treatment-Emergent Adverse Events",
            "Participant Disposition by Country",
        )

        self.assertGreater(similar, 0.70)
        self.assertLess(unrelated, 0.30)

    def test_tlf_semantic_matching_is_one_to_one(self) -> None:
        target = [
            {"name": "Adverse Event Summary", "type": "Table", "source": "ADAE"},
            {"name": "Adverse Events Summary", "type": "Table", "source": "ADAE"},
        ]
        history = [
            {"name": "Summary of Adverse Events", "type": "Table", "source": "ADAE"}
        ]

        score, coverage = _tlf_semantic_similarity(target, history)

        self.assertLessEqual(score, 0.5)
        self.assertEqual(coverage, 0.5)

    def test_queries_support_csr_work_on_property_names(self) -> None:
        for query in (TRAINING_QUERY, TARGET_QUERY):
            self.assertIn("wo.CSR_TLF_Num_Total", query)
            self.assertIn("wo.CSR_ADaM_Num_Total", query)
            self.assertIn("wo.CSR_SDTM_Num_Total", query)
            self.assertIn("(item:ADaM)", query)
            self.assertNotIn("(item:ADAM)", query)
        self.assertIn("WHERE p.Name = $person", TARGET_QUERY)

    def test_ongoing_assignments_query_excludes_planned_deliveries(self) -> None:
        self.assertIn("DID_Status)) = 'ongoing'", ONGOING_ASSIGNMENTS_QUERY)
        self.assertNotIn("'planned'", ONGOING_ASSIGNMENTS_QUERY)

    def test_features_only_use_strictly_earlier_history(self) -> None:
        previous = make_record(0)
        same_day = make_record(1)
        same_day["completion_date"] = previous["completion_date"]
        target = make_record(2)
        target["completion_date"] = "2024-01-10"

        features, similar = build_feature_row(target, [previous, same_day])

        self.assertEqual(features["person_completed_count"], 2.0)
        self.assertEqual(len(similar), 2)
        self.assertIn("max_tlf_semantic_similarity", features)
        self.assertIn("tlf_semantic_similarity", similar[0])

        target["completion_date"] = previous["completion_date"]
        features, _ = build_feature_row(target, [previous, same_day])
        self.assertEqual(features["person_completed_count"], 0.0)

    def test_incremental_training_features_match_direct_construction(self) -> None:
        records = [make_record(index) for index in range(8)]
        records[3]["completion_date"] = records[2]["completion_date"]
        ordered = sorted(
            records, key=lambda row: (row["completion_date"], str(row["did"]))
        )
        expected = [build_feature_row(row, ordered)[0] for row in ordered]

        actual, labels = build_training_features(records)

        self.assertEqual(actual, expected)
        self.assertEqual(labels.tolist(), [row["actual_hours"] for row in ordered])

    def test_repeated_similarity_features_summarize_history(self) -> None:
        history = [make_record(index) for index in range(4)]
        hours = [10.0, 20.0, 30.0, 40.0]
        task_counts = [2.0, 4.0, 5.0, 8.0]
        for row, actual_hours, task_count in zip(history, hours, task_counts):
            row["actual_hours"] = actual_hours
            row["task_count"] = task_count
            row["tlfs"][0]["name"] = "Adverse Event Summary"

        target = make_record(10)
        target["tlfs"][0]["name"] = "Adverse Event Summary"
        features, similar = build_feature_row(target, history)

        self.assertEqual(len(similar), 4)
        self.assertEqual(features["top3_combined_similarity_mean"], 1.0)
        self.assertEqual(features["top5_combined_similarity_mean"], 1.0)
        self.assertEqual(features["similar_did_count_ge_70"], 4.0)
        self.assertEqual(features["similar_did_count_ge_85"], 4.0)
        self.assertAlmostEqual(features["weighted_similar_hours"], 25.0)
        self.assertAlmostEqual(features["weighted_similar_hours_per_task"], 5.25)
        self.assertEqual(features["latest_similar_hours"], 40.0)
        self.assertAlmostEqual(features["similar_hours_trend"], 10.0)

    def test_prior_union_coverage_combines_multiple_historical_dids(self) -> None:
        first = make_record(0)
        first["tlfs"] = [
            {"name": "TLF-A", "generation": first["person"], "qc": None}
        ]
        second = make_record(1)
        second["tlfs"] = [
            {"name": "TLF-B", "generation": second["person"], "qc": None}
        ]
        target = make_record(3)
        target["tlfs"] = [
            {"name": "TLF-A", "generation": target["person"], "qc": None},
            {"name": "TLF-B", "generation": target["person"], "qc": None},
        ]

        features, _ = build_feature_row(target, [first, second])

        self.assertEqual(features["tlf_prior_overlap_count"], 2.0)
        self.assertEqual(features["tlf_prior_coverage"], 1.0)
        self.assertEqual(features["tlf_unseen_count"], 0.0)
        self.assertLess(features["max_tlf_similarity"], 1.0)

    def test_prediction_policy_can_prefer_baseline_and_cap_outliers(self) -> None:
        features = [
            {
                "person_completed_count": 10,
                "person_median_hours": value,
                "global_median_hours": 20,
            }
            for value in (10, 12, 14, 16)
        ]
        actual = np.asarray([11.0, 13.0, 15.0, 17.0])
        ridge = np.asarray([1000.0, 900.0, 800.0, 700.0])
        policy = _select_prediction_policy(
            np.asarray([5.0, 10.0, 20.0, 40.0, 80.0]),
            features,
            actual,
            ridge,
        )
        predictions = _apply_prediction_policy(ridge, features, policy)

        self.assertLess(policy["ridge_weight"], 0.5)
        self.assertLess(float(predictions.max()), 100.0)
        self.assertLess(
            np.abs(predictions - actual).sum(),
            np.abs(ridge - actual).sum(),
        )

    def test_candidate_filter_keeps_only_recent_unrelated_history(self) -> None:
        history = [make_record(index) for index in range(80)]
        for index, row in enumerate(history):
            row["study"] = f"HISTORY-{index}"
            row["ta"] = f"TA-{index}"
            row["tlfs"][0]["name"] = f"TLF-{index}"
            row["adams"][0]["name"] = f"ADAM-{index}"
            row["sdtms"][0]["name"] = f"SDTM-{index}"
        target = make_record(100)
        target["study"] = "TARGET-STUDY"
        target["ta"] = "TARGET-TA"
        target["tlfs"][0]["name"] = "TARGET-TLF"
        target["adams"][0]["name"] = "TARGET-ADAM"
        target["sdtms"][0]["name"] = "TARGET-SDTM"

        candidates = _similarity_candidates(target, history)

        self.assertEqual(len(candidates), 50)
        self.assertEqual(candidates[-1]["did"], history[-1]["did"])

    def test_similarity_cache_persists_pair_results(self) -> None:
        target = make_record(5)
        history = make_record(1)

        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "similarity.joblib"
            cache = _load_similarity_cache(cache_path)
            build_feature_row(target, [history], cache)
            self.assertEqual(cache["misses"], 1)
            _save_similarity_cache(cache, cache_path)

            reloaded = _load_similarity_cache(cache_path)
            build_feature_row(target, [history], reloaded)

        self.assertEqual(reloaded["hits"], 1)
        self.assertEqual(reloaded["misses"], 0)

    def test_quality_and_cleaning_reject_invalid_rows(self) -> None:
        valid = make_record(0)
        invalid = make_record(1)
        invalid["actual_hours"] = 0

        report = quality_report([valid, invalid])
        cleaned = clean_training_records([valid, invalid])

        self.assertEqual(report["non_positive_actual_hours"], 1)
        self.assertEqual(len(cleaned), 1)

    def test_train_save_and_predict(self) -> None:
        records = [
            make_record(index, "Person A" if index % 2 == 0 else "Person B")
            for index in range(30)
        ]
        target = make_record(31, "Person A")
        target.pop("completion_date")
        target.pop("actual_hours")

        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "model.joblib"
            training = train_model(records, model_path, minimum_records=20)
            result = predict_record(target, model_path, as_of_date="2026-01-01")
            self.assertTrue(model_path.exists())

        self.assertEqual(training["eligible_records"], 30)
        self.assertIn("person_history_baseline", training["benchmark_metrics"])
        self.assertIn("ridge_weight", training["prediction_policy"])
        self.assertGreaterEqual(result["p80_hours"], result["p50_hours"])
        self.assertGreaterEqual(result["p90_hours"], result["p80_hours"])
        self.assertEqual(result["prediction_type"], "total_hours")
        self.assertIn("similar_hours_trend", result["similarity_features"])
        self.assertIn("overall_prior_coverage", result["similarity_features"])
        self.assertIn("ridge_weight", result["prediction_policy"])

    def test_export_ongoing_predictions_writes_one_snapshot_per_assignment(self) -> None:
        target = make_record(31, "Person A")
        target.pop("completion_date")
        target["planned_date"] = "2026-02-01"
        prediction = {
            "person": "Person A",
            "did": "DID-031",
            "study": "STUDY-15",
            "as_of_date": "2026-01-15",
            "model_version": "did-effort-ridge-v3-robust",
            "p50_hours": 10.0,
            "p80_hours": 15.0,
            "p90_hours": 20.0,
            "person_completed_did_count": 8,
            "similarity_features": {
                "similar_did_count_ge_70": 3,
                "similar_did_count_ge_85": 1,
                "overall_prior_coverage": 0.75,
            },
            "warnings": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "ongoing.csv"
            with patch(
                "effort_prediction._resolve_prediction_artifact",
                side_effect=lambda path, *_: path,
            ), patch(
                "effort_prediction.load_ongoing_assignments",
                return_value=[{"person": "Person A", "did": "DID-031"}],
            ), patch(
                "effort_prediction._load_target_record_for_exact_person",
                return_value=target,
            ), patch(
                "effort_prediction.predict_record", return_value=prediction
            ), patch(
                "effort_prediction._load_prediction_similarity_cache",
                return_value={
                    "entries": {},
                    "hits": 0,
                    "misses": 0,
                },
            ) as load_cache, patch(
                "effort_prediction._save_similarity_cache"
            ):
                result = export_ongoing_predictions(
                    output_path, Path(directory) / "model.joblib", "2026-01-15"
                )
            with output_path.open(encoding="utf-8-sig", newline="") as output_file:
                rows = list(csv.DictReader(output_file))

        self.assertEqual(result["ongoing_assignments"], 1)
        self.assertEqual(rows[0]["person"], "Person A")
        self.assertEqual(rows[0]["p90_hours"], "20.0")
        self.assertEqual(rows[0]["planned_date"], "2026-02-01")
        self.assertEqual(load_cache.call_count, 1)

if __name__ == "__main__":
    unittest.main()
