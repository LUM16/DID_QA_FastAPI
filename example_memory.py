"""Persistent thumbs-up example library for few-shot Cypher generation.

Successful answers become cases. Only 👍 cases are injected back into the
agent prompt as positive training examples. 👎 cases are excluded.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parent
MEMORY_DIR = APP_ROOT / "data" / "memory"
DB_PATH = MEMORY_DIR / "examples.sqlite3"

_WORD_RE = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_ts REAL,
    created_at TEXT,
    question TEXT,
    cypher TEXT,
    outcome TEXT,
    row_count INTEGER DEFAULT 0,
    feedback INTEGER DEFAULT 0,
    weight REAL DEFAULT 1.0
);
CREATE INDEX IF NOT EXISTS idx_cases_feedback ON cases(feedback);
"""


def tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    tokens = _WORD_RE.findall(text)
    cjk = "".join(_CJK_RE.findall(text))
    tokens += [cjk[i : i + 2] for i in range(max(0, len(cjk) - 1))]
    return tokens


def _now() -> tuple[float, str]:
    ts = time.time()
    iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
    return ts, iso


class ExampleMemory:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def add_case(
        self,
        question: str,
        cypher: str,
        *,
        outcome: str = "success",
        row_count: int = 0,
    ) -> int | None:
        if not (question or "").strip():
            return None
        ts, iso = _now()
        weight = 1.0 if outcome == "success" else 0.2
        cur = self._conn.execute(
            """
            INSERT INTO cases (created_ts, created_at, question, cypher, outcome,
                row_count, feedback, weight)
            VALUES (?,?,?,?,?,?,0,?)
            """,
            (ts, iso, question, cypher or "", outcome, row_count, weight),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def record_feedback(self, case_id: int, vote: int) -> bool:
        vote = 1 if vote > 0 else -1
        weight = 2.5 if vote > 0 else 0.0
        self._conn.execute(
            "UPDATE cases SET feedback=?, weight=? WHERE id=?",
            (vote, weight, case_id),
        )
        self._conn.commit()
        return self._conn.total_changes > 0

    def endorse(
        self, question: str, cypher: str, *, row_count: int = 0, case_id: int | None = None
    ) -> int | None:
        """Mark a Q+Cypher pair as a positive example, creating a case if needed."""
        if case_id:
            if self.record_feedback(case_id, 1):
                return case_id
        new_id = self.add_case(
            question, cypher, outcome="success", row_count=row_count
        )
        if new_id:
            self.record_feedback(new_id, 1)
        return new_id

    def reject(self, case_id: int | None, question: str = "", cypher: str = "") -> int | None:
        if case_id and self.record_feedback(case_id, -1):
            return case_id
        new_id = self.add_case(question, cypher, outcome="success")
        if new_id:
            self.record_feedback(new_id, -1)
        return new_id

    def positive_examples(self, question: str, limit: int = 3) -> list[dict[str, Any]]:
        """Thumbs-up cases ranked against the current question (BM25-style)."""
        rows = self._conn.execute(
            """
            SELECT * FROM cases
            WHERE feedback > 0 AND weight > 0
              AND cypher IS NOT NULL AND cypher <> ''
            ORDER BY weight DESC, created_ts DESC
            LIMIT 300
            """
        ).fetchall()
        cases = [dict(r) for r in rows]
        if not cases:
            return []
        q_tokens = tokenize(question)
        docs = [tokenize(f"{c.get('question','')}\n{c.get('cypher','')}") for c in cases]
        scores = _bm25_scores(q_tokens, docs)
        ranked = sorted(
            zip(scores, cases),
            key=lambda item: (item[0], float(item[1].get("weight") or 0), item[1]["id"]),
            reverse=True,
        )
        picked = [case for score, case in ranked if score > 0][:limit]
        if picked:
            return picked
        return cases[:limit]

    def stats(self) -> dict[str, Any]:
        def scalar(sql: str) -> int:
            return int(self._conn.execute(sql).fetchone()[0] or 0)

        return {
            "total": scalar("SELECT COUNT(*) FROM cases"),
            "thumbs_up": scalar("SELECT COUNT(*) FROM cases WHERE feedback>0"),
            "thumbs_down": scalar("SELECT COUNT(*) FROM cases WHERE feedback<0"),
        }

    def close(self) -> None:
        self._conn.close()


def _bm25_scores(query: list[str], docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(docs)
    if n == 0:
        return []
    doc_len = [len(d) for d in docs]
    avgdl = (sum(doc_len) / n) if n else 0.0
    df: dict[str, int] = {}
    tf_list: list[dict[str, int]] = []
    for doc in docs:
        freq: dict[str, int] = {}
        for tok in doc:
            freq[tok] = freq.get(tok, 0) + 1
        tf_list.append(freq)
        for term in freq:
            df[term] = df.get(term, 0) + 1
    idf = {term: math.log(1 + (n - count + 0.5) / (count + 0.5)) for term, count in df.items()}
    scores: list[float] = []
    for i, freq in enumerate(tf_list):
        total = 0.0
        dl = doc_len[i] or 1
        for term in query:
            if term not in freq or avgdl == 0:
                continue
            tf = freq[term]
            denom = tf + k1 * (1 - b + b * dl / avgdl)
            total += idf.get(term, 0.0) * (tf * (k1 + 1)) / denom
        scores.append(total)
    return scores


def format_positive_examples(examples: list[dict[str, Any]], max_chars: int = 4000) -> str:
    if not examples:
        return ""
    parts: list[str] = [
        "User-endorsed few-shot examples (thumbs-up). Prefer these patterns when they match:"
    ]
    used = len(parts[0])
    for ex in examples:
        block = (
            f"\nQ: {ex.get('question', '').strip()}\n```cypher\n{ex.get('cypher', '').strip()}\n```"
        )
        if used + len(block) > max_chars:
            break
        parts.append(block)
        used += len(block)
    return "\n".join(parts) if len(parts) > 1 else ""


_MEMORY: ExampleMemory | None = None


def get_memory() -> ExampleMemory:
    global _MEMORY
    if _MEMORY is None:
        _MEMORY = ExampleMemory()
    return _MEMORY


def dump_positive_json(path: Path | None = None) -> Path:
    """Optional backup of thumbs-up examples as JSON."""
    memory = get_memory()
    rows = memory._conn.execute(
        "SELECT question, cypher, created_at FROM cases WHERE feedback>0 ORDER BY created_ts DESC"
    ).fetchall()
    target = path or (MEMORY_DIR / "curated_examples.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target
