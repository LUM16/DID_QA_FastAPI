"""Neo4j read-only helpers for the RSC Streamlit app."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

APP_ROOT = Path(__file__).resolve().parent
ENV_FILE = APP_ROOT / ".env"

try:  # pragma: no cover
    from neo4j.graph import Node as _GNode
    from neo4j.graph import Path as _GPath
    from neo4j.graph import Relationship as _GRel
except Exception:  # pragma: no cover
    _GNode = _GRel = _GPath = None  # type: ignore

try:  # pragma: no cover
    from neo4j.time import Date as _NDate
    from neo4j.time import DateTime as _NDateTime
    from neo4j.time import Duration as _NDuration
    from neo4j.time import Time as _NTime
except Exception:  # pragma: no cover
    _NDate = _NDateTime = _NDuration = _NTime = None  # type: ignore

FORBIDDEN = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD\s+CSV|FOREACH|CALL\s+\{)\b",
    re.IGNORECASE,
)
_LIMIT_RE = re.compile(r"\bLIMIT\s+\d+\b", re.IGNORECASE)
_LEGACY_TASK_PROP = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z_][A-Za-z0-9_]*)\.(Task_Num_Total|Task_Num_Generation|Task_Num_QC)\b"
)
_LEGACY_TASK_MAP = {
    "Task_Num_Total": (
        "CSR_Task_Num_Total",
        "SDA_Task_Num_Total",
        "STD_Task_Num_Total",
        "esub_Data_Num_Total",
    ),
    "Task_Num_Generation": (
        "CSR_Task_Num_Generation",
        "SDA_Task_Num_Generation",
        "STD_Task_Num_Generation",
        "esub_Data_Num_Generation",
    ),
    "Task_Num_QC": (
        "CSR_Task_Num_QC",
        "SDA_Task_Num_QC",
        "STD_Task_Num_QC",
        "esub_Data_Num_QC",
    ),
}
_TITLE_KEYS = ("Name", "name", "DID", "Title", "Email", "NTID", "Milestone", "Category", "id")
MAX_EXPORT_ROWS = 20000
_LAST_META: dict[str, Any] = {}
_SCHEMA_CACHE: dict[str, Any] | None = None
_DRIVER_CACHE: dict[str, Any] = {
    "driver": None,
    "uri": None,
    "user": None,
    "password": None,
}


def load_env() -> None:
    """
    Load APP_ROOT/.env into os.environ.

    When .env exists (local RSC folder testing), its values win.
    On Posit Connect, prefer not bundling .env — set Vars instead; if no
    .env file is present, existing Connect Vars are used as-is.
    """
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ[key.strip()] = value.strip().strip('"').strip("'")


def get_driver():
    load_env()
    uri = os.environ.get("NEO4J_URI", "bolt://10.109.2.157:7687")
    user = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        raise ValueError("NEO4J_PASSWORD is not set (use Connect Vars or .env).")
    cached = _DRIVER_CACHE.get("driver")
    if (
        cached is not None
        and _DRIVER_CACHE.get("uri") == uri
        and _DRIVER_CACHE.get("user") == user
        and _DRIVER_CACHE.get("password") == password
    ):
        return cached

    close_driver()
    driver = GraphDatabase.driver(uri, auth=(user, password))
    _DRIVER_CACHE.update(
        {"driver": driver, "uri": uri, "user": user, "password": password}
    )
    return driver


def close_driver() -> None:
    driver = _DRIVER_CACHE.get("driver")
    if driver is not None:
        driver.close()
    _DRIVER_CACHE.update({"driver": None, "uri": None, "user": None, "password": None})


def expand_legacy_task_properties(query: str) -> str:
    """Rewrite obsolete WORKS_ON task fields into the current CSR/SDA/STD/esub split."""

    def repl(match: re.Match[str]) -> str:
        alias, field = match.group(1), match.group(2)
        parts = [
            f"coalesce(toFloat({alias}.{name}), 0.0)"
            for name in _LEGACY_TASK_MAP[field]
        ]
        return "(" + " + ".join(parts) + ")"

    return _LEGACY_TASK_PROP.sub(repl, query)


def ensure_read_only(query: str) -> str:
    stripped = query.strip().rstrip(";")
    if FORBIDDEN.search(stripped):
        raise ValueError("Only read-only Cypher queries are allowed.")
    return stripped


def raise_limit(cypher: str, cap: int) -> str:
    text = ensure_read_only(cypher)
    matches = list(_LIMIT_RE.finditer(text))
    if matches:
        last = matches[-1]
        return text[: last.start()] + f"LIMIT {int(cap)}" + text[last.end() :]
    return f"{text}\nLIMIT {int(cap)}"


class _GraphBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _node_id(node: Any) -> str:
        try:
            return str(node.element_id)
        except Exception:
            try:
                return f"n{node.id}"
            except Exception:
                return f"n{id(node)}"

    @staticmethod
    def _labels(node: Any) -> list[str]:
        try:
            return [str(label) for label in node.labels]
        except Exception:
            return []

    def _title(self, node: Any, labels: list[str]) -> str:
        props = dict(node)
        for key in _TITLE_KEYS:
            value = props.get(key)
            if value not in (None, ""):
                return str(value)
        return labels[0] if labels else "Node"

    def add_node(self, node: Any) -> str:
        node_id = self._node_id(node)
        if node_id not in self.nodes:
            labels = self._labels(node)
            self.nodes[node_id] = {
                "id": node_id,
                "label": labels[0] if labels else "Node",
                "labels": labels,
                "title": self._title(node, labels),
                "properties": self.serialize(dict(node)),
            }
        return node_id

    def add_edge(self, rel: Any) -> None:
        try:
            rel_id = str(rel.element_id)
        except Exception:
            rel_id = f"r{id(rel)}"
        if rel_id in self.edges:
            return
        source = self.add_node(rel.start_node)
        target = self.add_node(rel.end_node)
        self.edges[rel_id] = {
            "id": rel_id,
            "source": source,
            "target": target,
            "type": str(getattr(rel, "type", "RELATES_TO")),
            "properties": self.serialize(dict(rel)),
        }

    def to_dict(self, node_cap: int = 600, edge_cap: int = 1500) -> dict[str, Any]:
        nodes = list(self.nodes.values())
        edges = list(self.edges.values())
        node_count, edge_count = len(nodes), len(edges)
        if node_count > node_cap:
            kept = {n["id"] for n in nodes[:node_cap]}
            nodes = nodes[:node_cap]
            edges = [e for e in edges if e["source"] in kept and e["target"] in kept]
        if len(edges) > edge_cap:
            edges = edges[:edge_cap]
        return {
            "nodes": nodes,
            "edges": edges,
            "node_count": node_count,
            "edge_count": edge_count,
            "truncated_graph": node_count > node_cap or edge_count > edge_cap,
        }

    def serialize(self, value: Any) -> Any:
        if _GNode is not None and isinstance(value, _GNode):
            self.add_node(value)
            return self.serialize(dict(value))
        if _GRel is not None and isinstance(value, _GRel):
            self.add_edge(value)
            props = self.serialize(dict(value))
            return props if props else {"_relationship": str(getattr(value, "type", "REL"))}
        if _GPath is not None and isinstance(value, _GPath):
            for rel in value.relationships:
                self.add_edge(rel)
            return [self.serialize(node) for node in value.nodes]
        if _NDateTime is not None and isinstance(value, _NDateTime):
            return value.isoformat()
        if _NDate is not None and isinstance(value, _NDate):
            return value.isoformat()
        if _NTime is not None and isinstance(value, _NTime):
            return value.isoformat()
        if _NDuration is not None and isinstance(value, _NDuration):
            return str(value)
        if isinstance(value, dict):
            return {str(k): self.serialize(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self.serialize(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if hasattr(value, "isoformat"):
            try:
                return value.isoformat()
            except Exception:
                return str(value)
        return str(value)


def run_cypher_with_meta(query: str, max_rows: int = 200) -> dict[str, Any]:
    """Run read-only Cypher and return rows plus a reconstructed relationship graph."""
    global _LAST_META
    safe = ensure_read_only(query)
    load_env()
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    driver = get_driver()
    with driver.session(database=database) as session:
        result = session.run(safe)
        keys = list(result.keys())
        builder = _GraphBuilder()
        rows: list[dict[str, Any]] = []
        for i, record in enumerate(result):
            if i >= max_rows:
                break
            rows.append({key: builder.serialize(record[key]) for key in keys})
        meta = {
            "rows": rows,
            "columns": keys,
            "graph": builder.to_dict(),
            "row_count": len(rows),
            "cypher": safe,
        }
        _LAST_META = meta
        return meta


def last_query_meta() -> dict[str, Any]:
    return _LAST_META


def run_cypher(query: str, limit_rows: int = 200) -> list[dict[str, Any]]:
    return run_cypher_with_meta(query, max_rows=limit_rows)["rows"]


def get_schema(*, force: bool = False, include_counts: bool = False) -> dict[str, Any]:
    global _SCHEMA_CACHE
    if not force and not include_counts and _SCHEMA_CACHE is not None:
        return _SCHEMA_CACHE
    load_env()
    database = os.environ.get("NEO4J_DATABASE", "neo4j")
    driver = get_driver()
    with driver.session(database=database) as session:
        labels = [
            row["label"]
            for row in session.run("CALL db.labels() YIELD label RETURN label ORDER BY label")
        ]
        rel_types = [
            row["relationshipType"]
            for row in session.run(
                "CALL db.relationshipTypes() YIELD relationshipType "
                "RETURN relationshipType ORDER BY relationshipType"
            )
        ]
        props = [
            row["propertyKey"]
            for row in session.run(
                "CALL db.propertyKeys() YIELD propertyKey "
                "RETURN propertyKey ORDER BY propertyKey"
            )
        ]
        counts: dict[str, Any] = {}
        if include_counts:
            for label in labels[:20]:
                counts[label] = session.run(
                    f"MATCH (n:`{label}`) RETURN count(n) AS c"
                ).single()["c"]

        payload = {
            "labels": labels,
            "relationshipTypes": rel_types,
            "propertyKeys": props[:100],
            "nodeCountsByLabel": counts,
        }
        if not include_counts:
            _SCHEMA_CACHE = payload
        return payload


def clear_schema_cache() -> None:
    global _SCHEMA_CACHE
    _SCHEMA_CACHE = None


def connection_summary() -> str:
    load_env()
    return os.environ.get("NEO4J_URI", "bolt://10.109.2.157:7687")
