"""Hermetic tests for team scoping (LLM and Neo4j mocked).

Run with:  python -m unittest test_team_scope -v
"""

from __future__ import annotations

import json
import unittest
from datetime import date
from unittest import mock

import agent
import hce_agent as ha
import team_scope as ts

USAGE = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}


def fake_chat(payload):
    return lambda system, user, **kwargs: (json.dumps(payload), USAGE)


def boom(*args, **kwargs):
    raise AssertionError("should not be called")


SCOPE = ts.TeamScope(("Wang, Wei",))
GOOD = (
    "MATCH (member:Person)-[:REPORTS_TO*0..]->(teamLead:Person)\n"
    "WHERE teamLead.Name IN [\"Wang, Wei\"] AND member.Status = 'Active'\n"
    "RETURN member.Name LIMIT 50"
)


class DetectTests(unittest.TestCase):
    def test_no_persons_skips_llm(self):
        self.assertEqual(ts.detect_team_leads("Wang Wei's team", [], chat=boom)[0], [])

    def test_only_resolved_names_kept(self):
        leads, _ = ts.detect_team_leads(
            "Wang, Wei's team", ["Wang, Wei"],
            chat=fake_chat({"team_leads": ["Wang, Wei", "Invented"]}),
        )
        self.assertEqual(leads, ["Wang, Wei"])

    def test_bad_json_means_no_scope(self):
        leads, _ = ts.detect_team_leads("x", ["A"], chat=lambda *a, **k: ("oops", USAGE))
        self.assertEqual(leads, [])


class ClauseTests(unittest.TestCase):
    def test_clause_includes_lead_and_active(self):
        clause = SCOPE.cypher_clause()
        self.assertIn("REPORTS_TO*0..", clause)
        self.assertIn("member.Status = 'Active'", clause)
        self.assertIn('"Wang, Wei"', clause)

    def test_validate(self):
        self.assertIsNone(SCOPE.validate(GOOD))
        self.assertIn("REPORTS_TO", SCOPE.validate("MATCH (p:Person) RETURN p"))
        self.assertIn("lead", SCOPE.validate(GOOD.replace("Wang, Wei", "Other")))
        self.assertIn("Active", SCOPE.validate(GOOD.replace("member.Status = 'Active'", "true")))

    def test_team_member_levels_query(self):
        seen = {}

        def query(cypher, **kwargs):
            seen["cypher"] = cypher
            return [{"name": "Wang, Wei", "level": 0}, {"name": "Li, Hua", "level": 1}]

        self.assertEqual(ts.team_member_levels(["Wang, Wei"], query), {"Wang, Wei": 0, "Li, Hua": 1})
        self.assertEqual(ts.team_members(["Wang, Wei"], query), ["Wang, Wei", "Li, Hua"])
        self.assertIn("Status = 'Active'", seen["cypher"])
        self.assertIn("min(length(path))", seen["cypher"])


class HceScopeTests(unittest.TestCase):
    def test_apply_team_scope(self):
        params = {"mode": "person", "persons": ["Wang, Wei"], "start": date(2026, 1, 1),
                  "end": date(2026, 6, 30), "feature_filter": {},
                  "group_filter": {"Team_Lead_Name": ["Wang, Wei"], "Site": ["China"]}}
        out = ha.apply_team_scope(params, ts.TeamScope(("Wang, Wei",), ("Li, Hua", "Wang, Wei")))
        self.assertEqual(out["mode"], "department")
        self.assertEqual(out["group_filter"], {"Site": ["China"], "Name": ["Li, Hua", "Wang, Wei"]})


def _person(name, fhce):
    import hce_caclulation as h
    return h.PersonHCE(name=name, ntid="", site="China", total_hce=1.0,
                       total_hours=10.0, feature_hours=5.0, feature_hce=fhce)


class HceSortTests(unittest.TestCase):
    PARAMS = {"mode": "department", "persons": [], "start": date(2026, 1, 1),
              "end": date(2026, 6, 30), "feature_filter": {}, "group_filter": {}}

    def _run(self, people, scope=None):
        with mock.patch.object(ha, "extract_hce_parameters", return_value=(dict(self.PARAMS), USAGE)), \
             mock.patch.object(ha.hce, "department_hce", return_value=(0.0, people)):
            return ha.answer_hce("q", team_scope=scope)

    def test_department_sorted_by_name(self):
        result = self._run([_person("Zed", 0.9), _person("amy", 0.1), _person("Bob", 0.5)])
        self.assertEqual([r["name"] for r in result["rows"]], ["amy", "Bob", "Zed"])
        self.assertNotIn("report_level", result["columns"])

    def test_team_sorted_by_level_then_name(self):
        scope = ts.TeamScope.with_levels(("Lead",), {"Lead": 0, "Bob": 1, "Amy": 2, "Cat": 1})
        people = [_person(n, 0.1) for n in ("Amy", "Cat", "Lead", "Bob")]
        result = self._run(people, scope)
        self.assertEqual([(r["report_level"], r["name"]) for r in result["rows"]],
                         [(0, "Lead"), (1, "Bob"), (1, "Cat"), (2, "Amy")])
        self.assertEqual(result["columns"][0], "report_level")
        self.assertIn("| Level | Name |", result["answer"])


class AgentScopeTests(unittest.TestCase):
    def test_template_skipped_and_validation_blocks_unfiltered_query(self):
        state = {"question": "hours on B798H NDA submission for each person in Wang, Wei's team",
                 "team_scope": SCOPE, "schema": {"labels": []}}
        with mock.patch.object(agent, "_build_domain_context", return_value=""):
            prepared = agent._prepare(state)
        self.assertNotIn("cypher", prepared)
        with mock.patch.object(agent, "generate_cypher", return_value=("MATCH (p:Person) RETURN p", USAGE)):
            generated = agent._generate({**state, **prepared})
        self.assertIsNotNone(generated["error"])
        with mock.patch.object(agent, "run_cypher", side_effect=boom):
            executed = agent._execute({**state, **prepared, **generated})
        self.assertEqual(executed["rows"], [])

    def test_valid_generation_passes(self):
        state = {"question": "q", "team_scope": SCOPE, "schema": {}, "domain_context": ""}
        with mock.patch.object(agent, "generate_cypher", return_value=(GOOD, USAGE)):
            self.assertIsNone(agent._generate(state)["error"])

    def test_prompt_contains_hint(self):
        captured = {}

        def chat(system, user, **kwargs):
            captured["user"] = user
            return f"```cypher\n{GOOD}\n```", USAGE

        with mock.patch.object(agent, "_chat", chat):
            agent.generate_cypher("q", {}, "ctx", None, team_scope=SCOPE)
        self.assertIn("TEAM SCOPE", captured["user"])


class ClampTodayTests(unittest.TestCase):
    TODAY = date(2026, 11, 3)

    def _params(self, start, end):
        return {"mode": "department", "start": start, "end": end}

    def test_future_end_capped(self):
        out = ha.clamp_to_today(self._params(date(2026, 1, 1), date(2026, 12, 31)), self.TODAY)
        self.assertEqual(out["end"], self.TODAY)
        self.assertEqual(out["requested_end"], date(2026, 12, 31))

    def test_past_period_unchanged(self):
        params = self._params(date(2025, 1, 1), date(2025, 12, 31))
        self.assertIs(ha.clamp_to_today(params, self.TODAY), params)

    def test_future_start_rejected(self):
        self.assertIsNone(ha.clamp_to_today(self._params(date(2027, 1, 1), date(2027, 3, 31)), self.TODAY))

    def test_partial_month_counts_elapsed_workdays(self):
        import hce_caclulation as h
        # Nov 2026: 21 workdays; Nov 2-3 (Mon, Tue) elapsed -> 2/21.
        self.assertAlmostEqual(h.total_hce(date(2026, 11, 1), self.TODAY, None, None), 2 / 21)
        self.assertAlmostEqual(h.total_hce(date(2026, 1, 1), date(2026, 12, 31), None, None), 12.0)

    def test_hce_result_disables_org_chart(self):
        self.assertFalse(ha._result("", [], USAGE, {})["org_chart"])


class ExportRowsTests(unittest.TestCase):
    def test_export_without_cypher_uses_rows(self):
        import app
        body = app.ExportBody(cypher="", format="csv",
                              rows=[{"report_level": 0, "name": "Lead"}],
                              columns=["report_level", "name"])
        with mock.patch.object(app, "run_cypher_with_meta", side_effect=boom):
            response = app.export_result(body)
        import asyncio

        async def read():
            return b"".join([c async for c in response.body_iterator])

        data = asyncio.run(read()).decode("utf-8-sig")
        self.assertEqual(data.splitlines(), ["report_level,name", "0,Lead"])

    def test_export_with_nothing_is_rejected(self):
        import app
        from fastapi import HTTPException
        with self.assertRaises(HTTPException):
            app.export_result(app.ExportBody(cypher="", format="csv"))


if __name__ == "__main__":
    unittest.main()
