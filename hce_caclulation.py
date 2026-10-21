"""HCE (resource utilization) calculation.

Strategy: one parameterized Cypher query aggregates hours per person inside
Neo4j; calendar logic (working days, holidays, onboard/offboard proration)
is done in Python.

Definitions
- Step 1   total_hce   = sum over months of (active working days / month working days)
- Step 2.1 total_hours = sum of TIME_ON.Hour in the period
- Step 2.2 feature_hours = TIME_ON.Hour whose DIDN_Month links to a Study
           with Study_Info.Study_Type = study_type
- Step 2.3 feature_hce = total_hce * feature_hours / total_hours  (0 if no hours)
- Step 3   department feature HCE = sum of per-person feature_hce
"""

from __future__ import annotations

import calendar
import os
import re
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from typing import Any
from neo4j_client import get_driver
import holidays as _holidays


# ---------------------------------------------------------------------------
# Holiday configuration
# ---------------------------------------------------------------------------

# Person.Site -> ISO country code used by the `holidays` package.
SITE_TO_COUNTRY: dict[str, str] = {
    "China": "CN",
    "United States": "US",
    "India": "IN",
    # "Japan": "JP",
}

# Weekend days that are official working days (e.g. China make-up workdays).
EXTRA_WORKDAYS: dict[str, set[date]] = {
    "CN": {
        # 2026 (State Council holiday notice)
        date(2026, 1, 4),  # Sun, New Year
        date(2026, 2, 14),  # Sat, Spring Festival
        date(2026, 2, 28),  # Sat, Spring Festival
        date(2026, 5, 9),  # Sat, Labour Day
        date(2026, 9, 20),  # Sun, National Day
        date(2026, 10, 10),  # Sat, National Day
    },
}


@lru_cache(maxsize=None)
def _holiday_set(country: str | None, year: int) -> frozenset[date]:
    if country is None or _holidays is None:
        return frozenset()
    return frozenset(_holidays.country_holidays(country, years=year).keys())


def is_workday(d: date, country: str | None) -> bool:
    if country and d in EXTRA_WORKDAYS.get(country, set()):
        return True
    return d.weekday() < 5 and d not in _holiday_set(country, d.year)


def workdays(start: date, end: date, country: str | None) -> int:
    """Working days in [start, end], inclusive."""
    n, d = 0, start
    while d <= end:
        n += is_workday(d, country)
        d += timedelta(days=1)
    return n


# ---------------------------------------------------------------------------
# Step 1
# ---------------------------------------------------------------------------


def month_hce(
    year: int,
    month: int,
    onboard: date | None,
    offboard: date | None,
    country: str | None = None,
) -> float:
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    active_start = max(first, onboard) if onboard else first
    active_end = min(last, offboard) if offboard else last
    if active_end < active_start:
        return 0.0  # before onboard / after offboard
    total = workdays(first, last, country)
    return workdays(active_start, active_end, country) / total if total else 0.0


def _month_range(start: date, end: date) -> list[tuple[int, int]]:
    months, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months


def total_hce(
    start: date,
    end: date,
    onboard: date | None,
    offboard: date | None,
    country: str | None = None,
) -> float:
    return sum(
        month_hce(y, m, onboard, offboard, country) for y, m in _month_range(start, end)
    )


# ---------------------------------------------------------------------------
# Cypher (steps 2.1 / 2.2 aggregated in the database, one row per person)
# ---------------------------------------------------------------------------

_HOURS_QUERY = """
MATCH (p:Person)
WHERE ($names IS NULL OR p.Name IN $names OR p.NTID IN $names)
  AND {person_where}
OPTIONAL MATCH (p)-[t:TIME_ON]->(dm:DIDN_Month)
WHERE dm.Year * 100 + dm.Month >= $start_ym
  AND dm.Year * 100 + dm.Month <= $end_ym
WITH p, t, dm, {feature_expr} AS is_feature
RETURN p.Name AS name,
       p.NTID AS ntid,
       p.Site AS site,
       p.Onboard_Date AS onboard,
       p.Offboard_Date AS offboard,
       sum(coalesce(toFloat(t.Hour), 0.0)) AS total_hours,
       sum(CASE WHEN is_feature THEN coalesce(toFloat(t.Hour), 0.0) ELSE 0.0 END)
           AS feature_hours
"""
# is_feature is evaluated once per TIME_ON (via EXISTS{} when the condition is
# on a downstream node), so multiple Study paths never double count hours.

# Feature-filter targets along the hours path, in path order.
# key -> (Cypher alias, pattern segment that reaches it from the previous one)
_PATH = {
    "TIME_ON": ("t", None),  # already bound in outer query
    "DIDN_Month": ("dm", None),  # already bound in outer query
    "PART_OF": ("r", "-[r:PART_OF]->"),
    "Study_Month": ("sm", "(sm:Study_Month)"),
    "BELONGS_TO": ("b", "-[b:BELONGS_TO]->"),
    "Study": ("s", "(s:Study)"),
    "HAS_DETAIL": ("h", "-[h:HAS_DETAIL]->"),
    "Study_Info": ("si", "(si:Study_Info)"),
}
_PATH_ORDER = list(_PATH)
_DEFAULT_TARGET = "Study_Info"


def _build_feature_expr(filters: Filter | None) -> tuple[str, dict]:
    """Feature filter whose keys are "Label.Property" (or "Property" -> Study_Info).

    Example: {"Study_Info.Study_Type": "INTERVENTIONAL", "Study.Phase": ["II", "III"],
              "DIDN_Month.Category": "CSR", "TIME_ON.Role": "QC"}
    Only the part of the path actually needed is matched.
    """
    if not filters:  # {} -> every hour counts as feature hours
        return "true", {}
    by_alias: dict[str, Filter] = {}
    deepest = 1  # index of DIDN_Month
    for key, value in filters.items():
        target, _, prop = key.rpartition(".")
        target = target or _DEFAULT_TARGET
        if target not in _PATH:
            raise ValueError(f"Unknown filter target {target!r}; use one of {_PATH_ORDER}")
        by_alias.setdefault(_PATH[target][0], {})[prop] = value
        deepest = max(deepest, _PATH_ORDER.index(target))

    clauses, params = [], {}
    for alias, props in by_alias.items():
        where, p = _build_where(alias, props, f"ff_{alias}_")
        clauses.append(where)
        params.update(p)
    where = " AND ".join(clauses)

    if deepest <= 1:  # only TIME_ON / DIDN_Month -> no traversal needed
        return f"coalesce({where}, false)", params

    # Nodes between DIDN_Month and the deepest target; ensure path ends on a node.
    if deepest % 2 == 0:  # ends on a relationship -> add following node
        deepest += 1
    segments = "".join(_PATH[k][1] for k in _PATH_ORDER[2 : deepest + 1])
    return f"EXISTS {{ MATCH (dm){segments} WHERE {where} }}", params


@dataclass
class PersonHCE:
    name: str | None
    ntid: str | None
    site: str | None
    total_hce: float        # step 1
    total_hours: float      # step 2.1
    feature_hours: float    # step 2.2
    feature_hce: float      # step 2.3


def _to_date(value: Any) -> date | None:
    """neo4j.time.Date -> datetime.date."""
    return value.to_native() if value is not None else None


_PROP_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

Filter = dict[str, Any]  # {property: value} ; list value -> IN ; None -> IS NULL


def _build_where(alias: str, filters: Filter | None, prefix: str) -> tuple[str, dict]:
    """Turn {"Site": "China", "Group": ["A", "B"]} into a parameterized WHERE.

    Property names are validated (they cannot be parameterized in Cypher);
    values are always passed as parameters.
    """
    if not filters:
        return "true", {}
    clauses, params = [], {}
    for i, (prop, value) in enumerate(filters.items()):
        if not _PROP_RE.match(prop):
            raise ValueError(f"Invalid property name: {prop!r}")
        key = f"{prefix}{i}"
        if value is None:
            clauses.append(f"{alias}.`{prop}` IS NULL")
            continue
        if isinstance(value, (list, tuple, set)):
            clauses.append(f"{alias}.`{prop}` IN ${key}")
            value = list(value)
        else:
            clauses.append(f"{alias}.`{prop}` = ${key}")
        params[key] = value
    return " AND ".join(clauses), params


def _fetch_rows(
    names: list[str] | None,
    person_filter: Filter | None,
    feature_filter: Filter | None,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    person_where, p_params = _build_where("p", person_filter, "pf")
    feature_expr, f_params = _build_feature_expr(feature_filter)
    query = _HOURS_QUERY.format(person_where=person_where, feature_expr=feature_expr)
    params = {
        "names": names,
        "start_ym": start.year * 100 + start.month,
        "end_ym": end.year * 100 + end.month,
        **p_params,
        **f_params,
    }
    driver = get_driver()
    try:
        with driver.session(database=os.environ.get("NEO4J_DATABASE", "neo4j")) as s:
            return [r.data() for r in s.run(query, **params)]
    finally:
        driver.close()


def _compute(rows: list[dict[str, Any]], start: date, end: date) -> list[PersonHCE]:
    results = []
    for r in rows:
        country = SITE_TO_COUNTRY.get(r["site"])
        hce = total_hce(start, end, _to_date(r["onboard"]), _to_date(r["offboard"]), country)
        tot, feat = r["total_hours"], r["feature_hours"]
        results.append(
            PersonHCE(
                name=r["name"],
                ntid=r["ntid"],
                site=r["site"],
                total_hce=hce,
                total_hours=tot,
                feature_hours=feat,
                feature_hce=hce * feat / tot if tot > 0 else 0.0,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

DEFAULT_FEATURE: Filter = {"Study_Info.Study_Type": "INTERVENTIONAL"}
DEFAULT_GROUP: Filter = {"Site": "China"}                   # on Person

# group_filter:   Person节点属性
# feature_filter: 
# (Person)-[t:TIME_ON]->(dm:DIDN_Month)-[r:PART_OF]->(sm:Study_Month)-[b:BELONGS_TO]->(s:Study)-[h:HAS_DETAIL]->(si:Study_Info)

def person_hce(
    name_or_ntid: str | list[str],
    start: date,
    end: date,
    feature_filter: Filter | None = None,
) -> list[PersonHCE]:
    """Steps 1-2 for one or more persons (matched by Name or NTID)."""
    names = [name_or_ntid] if isinstance(name_or_ntid, str) else list(name_or_ntid)
    feature = DEFAULT_FEATURE if feature_filter is None else feature_filter
    return _compute(_fetch_rows(names, None, feature, start, end), start, end)


def department_hce(
    start: date,
    end: date,
    group_filter: Filter | None = None,
    feature_filter: Filter | None = None,
) -> tuple[float, list[PersonHCE]]:
    """Step 3: sum of per-person feature HCE for persons matching group_filter."""
    group = DEFAULT_GROUP if group_filter is None else group_filter
    feature = DEFAULT_FEATURE if feature_filter is None else feature_filter
    people = _compute(_fetch_rows(None, group, feature, start, end), start, end)
    return sum(p.feature_hce for p in people), people


if __name__ == "__main__":
    total, people = department_hce(
        date(2026, 1, 1), 
        date(2026, 6, 30),
        group_filter={"Site": ["China"]},
        feature_filter={"Study_Info.TA": ["Oncology"]},
    )
    print(f"Department feature HCE: {total:.3f} ({len(people)} persons)")

    people = person_hce(
        "Chen, Sizhen", 
        date(2026, 1, 1), 
        date(2026, 6, 30),
        feature_filter={"Study_Info.Name": ["C1071032"]},
    )
    for p in people:
        print(
            f"{p.name} ({p.ntid}): total HCE={p.total_hce:.3f}, "
            f"hours={p.feature_hours:.1f}/{p.total_hours:.1f}, "
            f"feature HCE={p.feature_hce:.3f}"
        )


    people = person_hce(
        "Chen, Sizhen", 
        date(2026, 1, 1), 
        date(2026, 6, 30),
        feature_filter={"DIDN_Month.DID": ["C5841001_16"]},
    )
    for p in people:
        print(
            f"{p.name} ({p.ntid}): total HCE={p.total_hce:.3f}, "
            f"hours={p.feature_hours:.1f}/{p.total_hours:.1f}, "
            f"feature HCE={p.feature_hce:.3f}"
        )