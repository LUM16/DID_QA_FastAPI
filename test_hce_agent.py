"""Hermetic tests for hce_agent (LLM and Neo4j are mocked).

Run with:  python -m unittest test_hce_agent -v
"""

from __future__ import annotations

import json
import unittest
from datetime import date
from unittest import mock

import hce_agent as ha
import hce_caclulation as h

TODAY = date(2026, 10, 30)
USAGE = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}


def fake_chat(payload):
    def _chat(system, user, **kwargs):
        return json.dumps(payload), USAGE
    return _chat


def boom(*args, **kwargs):
    raise AssertionError("LLM should not be called")


class IntentTests(unittest.TestCase):
    def test_keyword_skips_llm(self):
        self.assertTrue(ha.classify_hce_intent("Chen 今年的 HCE 是多少", chat=boom)[0])

    def test_unrelated_skips_llm(self):
        self.assertFalse(ha.classify_hce_intent("C5841001_16 的状态", chat=boom)[0])

    def test_candidate_uses_llm(self):
        self.assertTrue(ha.classify_hce_intent("中国组的人力投入", chat=fake_chat({"intent": "hce"}))[0])
        self.assertFalse(ha.classify_hce_intent("资源列表", chat=fake_chat({"intent": "other"}))[0])

    def test_bad_llm_output_falls_back(self):
        self.assertFalse(ha.classify_hce_intent("人力", chat=lambda *a, **k: ("oops", USAGE))[0])


class ValidateTests(unittest.TestCase):
    def test_rejects_unknown_feature_key(self):
        with self.assertRaises(ValueError):
            ha.validate_hce_parameters({"mode": "department", "start": "2026-01-01",
                                        "end": "2026-06-30", "feature_filter": {"Study.SDSL": "x"}})

    def test_scalar_becomes_list_and_missing_time(self):
        p = ha.validate_hce_parameters({"mode": "department",
                                        "feature_filter": {"Study_Info.Derived_TA": "Oncology"}})
        self.assertEqual(p["feature_filter"], {"Study_Info.Derived_TA": ["Oncology"]})
        self.assertIsNone(p["start"])

    def test_person_requires_name(self):
        with self.assertRaises(ValueError):
            ha.validate_hce_parameters({"mode": "person", "start": "2026-01-01", "end": "2026-01-31"})


class FeatureValueTests(unittest.TestCase):
    def _ff(self, ff):
        return ha.validate_hce_parameters({"mode": "department", "feature_filter": ff})["feature_filter"]

    def test_whole_phase_includes_subphases_and_cross_phase(self):
        self.assertEqual(self._ff({"Study_Info.Plan_Phase": "Phase 3"})["Study_Info.Plan_Phase"],
                         ["PH III", "PH IIIA", "PH IIIB", "PH II PH III"])
        self.assertEqual(self._ff({"Study_Info.Plan_Phase": ["一期"]})["Study_Info.Plan_Phase"],
                         ["PH I", "PH IB PHII"])

    def test_specific_subphase_stays(self):
        self.assertEqual(self._ff({"Study_Info.Plan_Phase": "PH IIIA"})["Study_Info.Plan_Phase"], ["PH IIIA"])

    def test_enum_case_and_aliases(self):
        out = self._ff({"Study_Info.Study_Type": "observational", "Study_Info.Derived_TA": "oncology"})
        self.assertEqual(out["Study_Info.Study_Type"], ["NON INTERVENTIONAL"])
        self.assertEqual(out["Study_Info.Derived_TA"], ["Oncology"])

    def test_unknown_enum_value_rejected_with_choices(self):
        with self.assertRaisesRegex(ValueError, "choose from: I&I"):
            self._ff({"Study_Info.Derived_TA": "Cardiology"})

    def test_old_ta_key_rejected(self):
        with self.assertRaises(ValueError):
            self._ff({"Study_Info.TA": "Oncology"})

    def test_date_range(self):
        out = self._ff({"Study_Info.FSFV": {"from": "2025-01-01", "to": None}})
        self.assertEqual(out["Study_Info.FSFV"], {"from": date(2025, 1, 1), "to": None})
        with self.assertRaises(ValueError):
            self._ff({"Study_Info.DBR": {"from": "2026-05-01", "to": "2026-01-01"}})
        with self.assertRaises(ValueError):
            self._ff({"Study_Info.DBR": "2026"})

    def test_range_where_clause(self):
        where, params = h._build_where("si", {"FSFV": {"from": date(2025, 1, 1), "to": None}}, "x")
        self.assertEqual(where, "si.`FSFV` >= $x0_from")
        self.assertEqual(params, {"x0_from": date(2025, 1, 1)})


class AnswerTests(unittest.TestCase):
    def test_missing_time_asks_user(self):
        res = ha.answer_hce("中国组 HCE", chat=fake_chat({"mode": "department"}), today=TODAY)
        self.assertIn("time period", res["answer"])
        self.assertEqual(res["rows"], [])

    def test_department_defaults_are_empty_filters(self):
        person = h.PersonHCE("A", "a1", "China", 6.0, 100.0, 50.0, 3.0)
        with mock.patch.object(h, "department_hce", return_value=(3.0, [person])) as m:
            res = ha.answer_hce(
                "今年上半年部门 HCE",
                chat=fake_chat({"mode": "department", "start": "2026-01-01", "end": "2026-06-30"}),
                today=TODAY,
            )
        m.assert_called_once_with(date(2026, 1, 1), date(2026, 6, 30), group_filter={}, feature_filter={})
        self.assertIn("3.000", res["answer"])
        self.assertEqual(res["rows"][0]["feature_hce"], 3.0)

    def test_person_with_feature(self):
        with mock.patch.object(h, "person_hce", return_value=[]) as m:
            ha.answer_hce(
                "Chen, Sizhen 在 C1071032 上的 HCE",
                chat=fake_chat({"mode": "person", "persons": ["Chen, Sizhen"],
                                "start": "2026-01-01", "end": "2026-06-30",
                                "feature_filter": {"Study_Info.Name": "C1071032"}}),
                today=TODAY,
            )
        m.assert_called_once_with(["Chen, Sizhen"], date(2026, 1, 1), date(2026, 6, 30),
                                  feature_filter={"Study_Info.Name": ["C1071032"]})


if __name__ == "__main__":
    unittest.main()
