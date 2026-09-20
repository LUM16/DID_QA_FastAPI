"""DID Insight web app for Posit Connect: Insight2 UI + FastAPI API."""

from __future__ import annotations

import io
import logging
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent import ask as agent_ask
from agent import _read_doc
from example_memory import get_memory
from export import to_csv, to_json
from neo4j_client import (
    connection_summary,
    ensure_read_only,
    get_driver,
    get_schema,
    clear_schema_cache,
    load_env,
    raise_limit,
    run_cypher_with_meta,
)
from vox_client import vox_health

STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"
MAX_EXPORT_ROWS = 20000
TIMING_LOG = logging.getLogger("uvicorn.error")
TIMING_STAGE_ORDER = (
    "intent",
    "prepare",
    "cypher_generation",
    "neo4j",
    "cypher_repair",
    "prediction_parameters",
    "prediction_model",
    "presentation",
    "answer_generation",
    "total",
)

app = FastAPI(title="DID Insight", version="2.0.0")
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class QueryBody(BaseModel):
    question: str
    history: list[dict[str, Any]] = Field(default_factory=list)
    provider: str | None = None
    refresh_schema: bool = False


class FeedbackBody(BaseModel):
    case_id: int
    vote: int
    note: str = ""


class ImproveBody(BaseModel):
    provider: str | None = None
    force: bool = False


class ExportBody(BaseModel):
    cypher: str
    format: str = "csv"


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return jsonable(item())
        except Exception:  # noqa: BLE001
            return str(value)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:  # noqa: BLE001
            return str(value)
    return str(value)


def _viz_payload(visualization: dict[str, Any] | None) -> dict[str, Any] | None:
    if not visualization:
        return None
    kind = str(visualization.get("chart_type") or visualization.get("display_type") or "")
    if kind in {"table", "kpi_table", ""}:
        return None
    if kind in {"horizontal_bar", "stacked_bar", "grouped_bar"}:
        kind = "bar"
    if kind not in {"bar", "line", "pie"}:
        return None
    if kind == "pie":
        chart = {
            "names": visualization.get("names"),
            "values": visualization.get("values"),
        }
    else:
        y_fields = visualization.get("y")
        y_field = y_fields[0] if isinstance(y_fields, list) and y_fields else y_fields
        chart = {"x": visualization.get("x"), "y": y_field}
    return {"kind": kind, "chart": chart}


def insight_payload(result: dict[str, Any], elapsed_ms: int) -> dict[str, Any]:
    load_env()
    rows = jsonable(result.get("rows") or [])
    columns = result.get("columns") or (
        list(dict.fromkeys(key for row in rows if isinstance(row, dict) for key in row))
    )
    cypher = result.get("cypher") or ""
    error = result.get("error")
    row_count = len(rows)
    if error:
        confidence = "low"
    elif row_count:
        confidence = "high"
    else:
        confidence = "medium"
    attempts = []
    if cypher or error:
        attempts.append(
            {
                "cypher": cypher,
                "row_count": row_count,
                "error": error,
            }
        )
    answer = result.get("answer") or ""
    if error and not answer:
        answer = str(error)
    usage = result.get("usage") or {}
    timings_ms = {
        str(stage): max(0, int(duration))
        for stage, duration in (result.get("timings_ms") or {}).items()
        if isinstance(duration, (int, float)) and not isinstance(duration, bool)
    }
    timings_ms["total"] = elapsed_ms
    return {
        "answer": answer,
        "cypher": cypher,
        "rows": rows,
        "columns": columns,
        "row_count": row_count,
        "graph": jsonable(result.get("graph") or {}),
        "viz": _viz_payload(result.get("visualization")),
        "case_id": result.get("case_id"),
        "confidence": confidence,
        "provider": "vox",
        "model": os.environ.get("VOX_MODEL", "gpt-4o"),
        "fallback_used": False,
        "attempts": attempts,
        "elapsed_ms": elapsed_ms,
        "timings_ms": timings_ms,
        "error": error,
        "usage": jsonable(usage),
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
        "prediction": jsonable(result.get("prediction")) if result.get("prediction") else None,
    }


def log_query_timings(payload: dict[str, Any]) -> None:
    timings = payload.get("timings_ms")
    if not isinstance(timings, dict):
        return
    details = [
        f"{stage}={timings[stage]}ms"
        for stage in TIMING_STAGE_ORDER
        if stage in timings
    ]
    TIMING_LOG.info(
        "DID query timings | %s | rows=%s | status=%s",
        " | ".join(details),
        payload.get("row_count", 0),
        "error" if payload.get("error") else "ok",
    )


def neo4j_health() -> dict[str, Any]:
    load_env()
    uri = os.environ.get("NEO4J_URI", connection_summary())
    try:
        driver = get_driver()
        try:
            driver.verify_connectivity()
        finally:
            driver.close()
        return {"ok": True, "uri": uri, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "uri": uri, "error": str(exc)}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    page = STATIC_DIR / "index.html"
    if not page.exists():
        raise HTTPException(status_code=500, detail="Missing web/static/index.html")
    return FileResponse(str(page))


@app.get("/health")
def health() -> dict[str, Any]:
    load_env()
    return {
        "neo4j": neo4j_health(),
        "llm": vox_health(),
    }


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    try:
        return get_memory().stats()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/schema/refresh")
def refresh_schema() -> dict[str, Any]:
    try:
        _read_doc.cache_clear()
        clear_schema_cache()
        return get_schema(force=True, include_counts=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/query")
def query(body: QueryBody) -> dict[str, Any]:
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    started = time.perf_counter()
    try:
        schema = get_schema() if body.refresh_schema else None
        result = agent_ask(body.question.strip(), history=body.history, schema=schema)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    payload = insight_payload(result, elapsed_ms)
    log_query_timings(payload)
    return payload


@app.post("/api/feedback")
def feedback(body: FeedbackBody) -> dict[str, Any]:
    memory = get_memory()
    ok = memory.record_feedback(body.case_id, body.vote)
    if not ok:
        raise HTTPException(status_code=404, detail="Unknown case_id")
    return {"ok": True, "case_id": body.case_id, "vote": 1 if body.vote > 0 else -1}


@app.post("/api/improve")
def improve(_body: ImproveBody) -> dict[str, Any]:
    stats_payload = get_memory().stats()
    return {
        "status": "skipped",
        "reason": (
            "This RSC edition learns from 👍 / 👎 on answers. "
            "Thumbs-up Cypher pairs are reused as few-shot examples."
        ),
        "rules_added": 0,
        "cases_reviewed": stats_payload.get("total", 0),
        "stats": stats_payload,
    }


@app.post("/api/export")
def export_result(body: ExportBody) -> StreamingResponse:
    try:
        safe = ensure_read_only(body.cypher)
        expanded = raise_limit(safe, MAX_EXPORT_ROWS)
        meta = run_cypher_with_meta(expanded, max_rows=MAX_EXPORT_ROWS)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Export refused: {exc}") from exc
    rows, columns = meta["rows"], meta["columns"]
    fmt = (body.format or "csv").lower()
    if fmt == "json":
        data = to_json(rows, columns)
        return StreamingResponse(
            io.BytesIO(data.encode("utf-8")),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=did_result.json"},
        )
    data = to_csv(rows, columns)
    return StreamingResponse(
        io.BytesIO(data.encode("utf-8-sig")),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=did_result.csv"},
    )


def main() -> None:
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=8010, reload=False)


if __name__ == "__main__":
    main()
