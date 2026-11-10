"""Team scope: "<Lead>'s team" -> everyone reporting (recursively) to Lead.

Runs after match_person, so lead names are already official Person.Name values.
A team includes the lead and every Active person reaching the lead through
REPORTS_TO*0.. (zero hops = the lead).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from neo4j_client import run_cypher
from vox_client import chat as _chat, empty_usage

ChatFn = Callable[..., tuple[str, dict[str, int]]]
TEAM_MAX_TOKENS = 120
MEMBER_ALIAS = "member"

DETECT_SYSTEM = """Decide which of the listed people are referred to as the LEAD of a team
in the question, i.e. the question restricts results to that person's team
(e.g. "Zhang Wei's team", "team of Zhang Wei", "Zhang Wei team", "Zhang Wei的团队",
"Zhang Wei组", "Zhang Wei下面的人", "Zhang Wei的下属").
A person who is only asked about individually is NOT a team lead.
Return exactly {"team_leads": [names copied exactly from the list]}; use [] when none."""


@dataclass(frozen=True)
class TeamScope:
    leads: tuple[str, ...]
    members: tuple[str, ...] = field(default=())
    # (name, reporting level) pairs; tuple keeps the dataclass hashable.
    levels: tuple[tuple[str, int], ...] = field(default=())

    @classmethod
    def with_levels(cls, leads: tuple[str, ...], levels: dict[str, int]) -> "TeamScope":
        return cls(tuple(leads), tuple(levels), tuple(levels.items()))

    def cypher_clause(self, alias: str = MEMBER_ALIAS) -> str:
        names = ", ".join(json.dumps(n, ensure_ascii=False) for n in self.leads)
        return (
            f"MATCH ({alias}:Person)-[:REPORTS_TO*0..]->(teamLead:Person)\n"
            f"WHERE teamLead.Name IN [{names}] AND {alias}.Status = 'Active'"
        )

    def prompt_hint(self) -> str:
        return (
            "TEAM SCOPE (mandatory): the question is restricted to the team of "
            f"{', '.join(self.leads)}. A team member is the lead or anyone reporting to "
            "the lead directly or indirectly, with Status 'Active'. The query MUST "
            "contain this pattern verbatim and use the member variable for every "
            "person in the result:\n"
            f"{self.cypher_clause()}\n"
            "Do not use Team_Lead_Name/Group_Lead_Name/TA_Lead_Name for this filter."
        )

    def validate(self, cypher: str) -> str | None:
        """Return an error message when the Cypher drops the team filter."""
        text = cypher or ""
        if not re.search(r"REPORTS_TO\s*\*\s*0\s*\.\.", text):
            return "Missing team filter (REPORTS_TO*0..)."
        missing = [n for n in self.leads if json.dumps(n, ensure_ascii=False) not in text
                   and f"'{n}'" not in text]
        if missing:
            return f"Team filter does not reference lead(s): {', '.join(missing)}."
        if not re.search(r"Status\s*=\s*['\"]Active['\"]", text):
            return "Team filter must require Status = 'Active'."
        return None


def detect_team_leads(
    question: str,
    persons: list[str],
    history_text: str = "",
    chat: ChatFn = _chat,
) -> tuple[list[str], dict[str, int]]:
    """LLM picks team leads among already-resolved persons. No persons -> no call."""
    persons = [p for p in dict.fromkeys(persons) if p]
    if not persons:
        return [], empty_usage()
    user = (
        f"People (official names): {json.dumps(persons, ensure_ascii=False)}\n\n"
        f"Recent conversation:\n{history_text or '(none)'}\n\nQuestion:\n{question}"
    )
    raw, usage = chat(DETECT_SYSTEM, user, temperature=0, max_tokens=TEAM_MAX_TOKENS)
    try:
        match = re.search(r"\{[\s\S]*\}", raw or "")
        leads = json.loads(match.group(0) if match else raw).get("team_leads") or []
    except (ValueError, AttributeError):
        return [], usage
    allowed = set(persons)
    return [str(n) for n in leads if str(n) in allowed], usage


def team_member_levels(
    leads: list[str] | tuple[str, ...], query: Callable = run_cypher
) -> dict[str, int]:
    """{member name: reporting level}; 0 = lead, 1 = direct report, 2+ = indirect.

    A member reachable through several paths (or under several leads) keeps the
    shortest distance. Ordered by level, then name.
    """
    names = ", ".join(json.dumps(n, ensure_ascii=False) for n in leads)
    cypher = (
        f"MATCH path = ({MEMBER_ALIAS}:Person)-[:REPORTS_TO*0..]->(teamLead:Person)\n"
        f"WHERE teamLead.Name IN [{names}] AND {MEMBER_ALIAS}.Status = 'Active'\n"
        f"RETURN {MEMBER_ALIAS}.Name AS name, min(length(path)) AS level\n"
        "ORDER BY level, name"
    )
    rows = query(cypher, limit_rows=100_000, record_meta=False)
    return {r["name"]: int(r["level"]) for r in rows if r.get("name")}


def team_members(leads: list[str] | tuple[str, ...], query: Callable = run_cypher) -> list[str]:
    """Active members (including leads) of the given leads' teams."""
    return list(team_member_levels(leads, query))


def resolve_team_scope(
    question: str,
    persons: list[str] | None,
    history_text: str = "",
    chat: ChatFn = _chat,
    with_members: bool = False,
    query: Callable = run_cypher,
) -> tuple[TeamScope | None, dict[str, int]]:
    leads, usage = detect_team_leads(question, persons or [], history_text, chat)
    if not leads:
        return None, usage
    if not with_members:
        return TeamScope(tuple(leads)), usage
    return TeamScope.with_levels(tuple(leads), team_member_levels(leads, query)), usage
