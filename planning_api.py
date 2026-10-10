"""Snapshot-only team recommendation and person allocation endpoints."""

from __future__ import annotations

import io
import logging
import time
from contextlib import nullcontext
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4
from zipfile import BadZipFile

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from du_team_recommendation import (
    load_history_snapshot,
    recommendation_ta_lead_candidates,
    recommend_uploaded_scope,
)
from tlf_person_allocation import (
    allocate_uploaded_tlfs,
    allocation_excel_bytes,
    load_person_tlf_snapshot,
    team_lead_candidates,
)

router = APIRouter(prefix="/api/planning", tags=["Planning"])
PLANNING_LOCK = RLock()
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
EXAMPLE = Path(__file__).resolve().parent / "docs" / "C5001001_61.xlsx"
EXCEL_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
JOB_LOCK = RLock()
JOBS: dict[str, dict[str, Any]] = {}
LOG = logging.getLogger("uvicorn.error")
JOB_TTL_SECONDS = 3600
MAX_JOBS = 8


def _input(upload: UploadFile | None, *, data: bool = False) -> io.BytesIO | None:
    if upload is None:
        return None
    filename = Path(upload.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ({".csv"} if data else {".csv", ".xlsx"}):
        raise HTTPException(422, "Upload an .xlsx workbook or TLF CSV with Data CSV.")
    content = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Each uploaded file must be at most 20 MB.")
    if not content:
        raise HTTPException(422, "Uploaded files must not be empty.")
    stream = io.BytesIO(content)
    stream.name = filename
    return stream


def _run(function, *args, serialize: bool = True):
    try:
        # Business caches are shared mutable objects; planning runs are serialized.
        with PLANNING_LOCK if serialize else nullcontext():
            return jsonable_encoder(function(*args))
    except (ValueError, UnicodeError, BadZipFile) as exc:
        raise HTTPException(422, str(exc)) from exc
    except (OSError, RuntimeError) as exc:
        raise HTTPException(503, "Planning artifacts unavailable; check deployment files.") from exc


@router.get("/recommend/options")
def recommendation_options() -> dict[str, Any]:
    def options():
        history, _, snapshot = load_history_snapshot()
        return {"ta_leads": recommendation_ta_lead_candidates(history), "snapshot": snapshot}
    return _run(options, serialize=False)


@router.get("/allocate/options")
def allocation_options() -> dict[str, Any]:
    def options():
        history, _, snapshot = load_person_tlf_snapshot()
        return {"team_leads": team_lead_candidates(history), "snapshot": snapshot}
    return _run(options, serialize=False)


@router.get("/example")
def example() -> FileResponse:
    if not EXAMPLE.is_file():
        raise HTTPException(503, "The bundled example is unavailable.")
    return FileResponse(EXAMPLE, media_type=EXCEL_TYPE, filename=EXAMPLE.name)


@router.post("/recommend")
def recommend(
    ta_lead_name: str = Form(...),
    primary_file: UploadFile = File(...),
    data_csv_file: UploadFile | None = File(None),
) -> dict[str, Any]:
    return _run(recommend_uploaded_scope, ta_lead_name, _input(primary_file), _input(data_csv_file, data=True))


@router.post("/allocate")
def allocate(
    team_lead_name: str = Form(...),
    primary_file: UploadFile = File(...),
    data_csv_file: UploadFile | None = File(None),
) -> dict[str, Any]:
    return _run(allocate_uploaded_tlfs, team_lead_name, _input(primary_file), _input(data_csv_file, data=True))


def _prune_jobs() -> None:
    now = time.monotonic()
    for job_id, job in list(JOBS.items()):
        if job.get("finished_at") is not None and now - job["finished_at"] > JOB_TTL_SECONDS:
            del JOBS[job_id]


def _work_job(job_id: str, function, args: tuple) -> None:
    with PLANNING_LOCK:
        with JOB_LOCK:
            JOBS[job_id]["status"] = "running"
        try:
            result = _run(function, *args)
            outcome = {"status": "complete", "result": result}
        except HTTPException as exc:
            outcome = {"status": "error", "error": exc.detail, "error_status": exc.status_code}
        except Exception:
            LOG.exception("Planning job failed")
            outcome = {"status": "error", "error": "Planning failed; check server logs and artifacts.", "error_status": 500}
    with JOB_LOCK:
        JOBS[job_id].update(outcome, finished_at=time.monotonic())


def _new_job(background: BackgroundTasks, function, *args) -> dict[str, str]:
    with JOB_LOCK:
        _prune_jobs()
        if len(JOBS) >= MAX_JOBS:
            completed = [key for key, job in JOBS.items() if job.get("finished_at") is not None]
            if completed:
                del JOBS[completed[0]]
            else:
                raise HTTPException(429, "Planning is busy; retry when a current run completes.")
        job_id = uuid4().hex
        JOBS[job_id] = {"status": "queued", "created_at": time.monotonic()}
    background.add_task(_work_job, job_id, function, args)
    return {"job_id": job_id, "status": "queued"}


@router.post("/jobs/recommend", status_code=202)
def recommendation_job(
    background: BackgroundTasks,
    ta_lead_name: str = Form(...),
    primary_file: UploadFile = File(...),
    data_csv_file: UploadFile | None = File(None),
) -> dict[str, str]:
    return _new_job(background, recommend_uploaded_scope, ta_lead_name, _input(primary_file), _input(data_csv_file, data=True))


@router.post("/jobs/allocate", status_code=202)
def allocation_job(
    background: BackgroundTasks,
    team_lead_name: str = Form(...),
    primary_file: UploadFile = File(...),
    data_csv_file: UploadFile | None = File(None),
) -> dict[str, str]:
    return _new_job(background, allocate_uploaded_tlfs, team_lead_name, _input(primary_file), _input(data_csv_file, data=True))


@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    with JOB_LOCK:
        _prune_jobs()
        job = JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "Planning run expired or the server restarted; submit again.")
        return {
            "job_id": job_id,
            "status": job["status"],
            "elapsed_seconds": round(time.monotonic() - job["created_at"], 1),
            **{key: job[key] for key in ("result", "error", "error_status") if key in job},
        }


class AllocationExport(BaseModel):
    result: dict[str, Any] = Field(...)


@router.post("/allocate/excel")
def allocation_excel(body: AllocationExport) -> Response:
    allocations = body.result.get("allocations")
    if not isinstance(allocations, list) or not 1 <= len(allocations) <= 5000:
        raise HTTPException(422, "Supply an allocation result with 1–5000 TLFs.")
    try:
        content = allocation_excel_bytes(body.result)
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(422, "Invalid allocation result.") from exc
    return Response(
        content,
        media_type=EXCEL_TYPE,
        headers={"Content-Disposition": 'attachment; filename="tlf_person_allocation.xlsx"'},
    )
