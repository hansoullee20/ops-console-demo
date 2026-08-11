"""Fingerprint XLS import over HTTP (AI_BUILD_PLAN.md §7 Phase 3).

These are the first mutation endpoints in the console, so the shape is
deliberately narrow:

    POST   /api/v1/imports                 upload -> preview      (no business
                                                                   data written)
    POST   /api/v1/imports/{id}/apply      confirm and commit
    POST   /api/v1/imports/{id}/rollback   undo, without deleting a punch
    GET    /api/v1/imports                 what has been imported
    GET    /api/v1/imports/{id}            one run, with its coverage

Three rules the endpoints exist to enforce:

* Nothing is written to attendance without a second, explicit request carrying
  the token the preview issued. A single mis-click cannot import.
* An import is refused on a demo-seeded database. Attaching real punches to 18
  invented people produces a file nobody can trust afterwards.
* Every apply and rollback writes an audit_log row inside the same transaction
  as the change (done by the service, pinned by tests).

The endpoints only orchestrate; every guarantee lives in
`app/services/xls_pipeline.py`, which is what the tests exercise directly.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app import config, db
from app.schemas.imports import (
    ApplyRequest,
    ApplyResult,
    ImportRunDetail,
    ImportRunSummary,
    RollbackRequest,
    RollbackResult,
)
from app.services import ops, xls_import, xls_pipeline

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])

ALLOWED_SUFFIXES = (".xls",)


def _connect(read_only: bool = True):
    if not config.DB_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="database not initialised; start the backend once to run migrations",
        )
    return db.connect(config.DB_PATH, read_only=read_only)


def _guard_context() -> None:
    """Refuse to import real records into a database full of invented people."""
    if config.ALLOW_DEMO_IMPORT:
        return
    conn = _connect()
    try:
        context = ops.data_context(conn)["data_context"]
    finally:
        conn.close()
    if context == "demo":
        raise HTTPException(
            status_code=409,
            detail=(
                "이 데이터베이스는 데모 시드(data_context=demo)입니다. 실제 지문 기록을 "
                "가져오면 가상 직원 18명과 섞여 어느 쪽이 실제인지 구분할 수 없게 됩니다. "
                "운영용 데이터베이스에서 실행하십시오. 데모 시드로 흐름만 확인하려면 "
                "OPS_ALLOW_DEMO_IMPORT=1 로 백엔드를 실행하십시오."
            ),
        )


def _store_upload(upload: UploadFile) -> tuple[Path, str, tempfile.TemporaryDirectory]:
    """Stream the upload to a temp file, enforcing the size cap as it arrives."""
    name = Path(upload.filename or "").name
    if not name.lower().endswith(ALLOWED_SUFFIXES):
        raise HTTPException(
            status_code=415,
            detail=(
                f"'{name or '파일'}' 은(는) .XLS 파일이 아닙니다. 지문 단말이 내보낸 "
                "월별 .XLS 파일을 선택하십시오. (.xlsx 는 단말 형식이 아닙니다)"
            ),
        )

    holder = tempfile.TemporaryDirectory(prefix="ops-import-")
    target = Path(holder.name) / "upload.xls"
    written = 0
    try:
        with target.open("wb") as handle:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > config.MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"파일이 너무 큽니다({config.MAX_UPLOAD_BYTES // (1024 * 1024)}MB 제한). "
                            "월별 지문 export 파일이 맞는지 확인하십시오."
                        ),
                    )
                handle.write(chunk)
    except Exception:
        holder.cleanup()
        raise
    if not written:
        holder.cleanup()
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    return target, name, holder


@router.post("", summary="Upload a terminal export and preview what it would do")
def create_preview(file: UploadFile = File(...)) -> dict:
    """Preserve the original, open an import run, and report the preview.

    Writes no punch, attendance, leave or replacement data. The import_run row
    it opens is a record of the attempt — including an attempt that fails to
    parse.
    """
    _guard_context()
    source, filename, holder = _store_upload(file)
    try:
        preview = xls_pipeline.preview_import(source, original_filename=filename)
    except xls_import.XlsDependencyMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except xls_import.XlsImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        holder.cleanup()
    return preview.as_dict()


@router.post("/{run_id}/apply", response_model=ApplyResult,
             summary="Commit a previewed import")
def apply_run(run_id: int, body: ApplyRequest) -> ApplyResult:
    _guard_context()
    try:
        result = xls_pipeline.apply_import(run_id, body.confirmationToken)
    except xls_pipeline.ImportError_ as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except xls_import.XlsImportError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ApplyResult(**result)


@router.post("/{run_id}/rollback", response_model=RollbackResult,
             summary="Undo an applied import without deleting raw punches")
def rollback_run(run_id: int, body: RollbackRequest) -> RollbackResult:
    try:
        result = xls_pipeline.rollback_import(run_id, body.reason)
    except xls_pipeline.ImportError_ as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return RollbackResult(**result)


@router.get("", response_model=list[ImportRunSummary], summary="Import history")
def list_runs(limit: int = 50) -> list[ImportRunSummary]:
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT r.id, r.source_filename, r.status, r.period_start, r.period_end,
                   r.punch_event_count, r.started_at, r.finished_at, r.rolled_back_at,
                   r.error_message,
                   (SELECT COUNT(*) FROM import_run_days d WHERE d.import_run_id = r.id)
                       AS covered_days
              FROM import_runs r
             WHERE r.source_kind = 'fingerprint_xls'
             ORDER BY r.id DESC LIMIT ?
            """,
            (max(1, min(limit, 200)),),
        ).fetchall()
        return [
            ImportRunSummary(
                id=row["id"],
                sourceFilename=row["source_filename"],
                status=row["status"],
                periodStart=row["period_start"],
                periodEnd=row["period_end"],
                punchEventCount=row["punch_event_count"],
                startedAt=row["started_at"],
                finishedAt=row["finished_at"],
                rolledBackAt=row["rolled_back_at"],
                errorMessage=row["error_message"],
                coveredDays=row["covered_days"],
            )
            for row in rows
        ]
    finally:
        conn.close()


@router.get("/{run_id}", response_model=ImportRunDetail, summary="One import run")
def get_run(run_id: int) -> ImportRunDetail:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM import_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"no import run {run_id}")
        days = conn.execute(
            "SELECT work_date, coverage_status, raw_punch_count FROM import_run_days "
            " WHERE import_run_id = ? ORDER BY work_date",
            (run_id,),
        ).fetchall()
        findings = []
        if row["findings_json"]:
            try:
                findings = json.loads(row["findings_json"]).get("findings", [])
            except ValueError:  # pragma: no cover - defensive
                findings = []
        return ImportRunDetail(
            id=row["id"],
            sourceFilename=row["source_filename"],
            status=row["status"],
            periodStart=row["period_start"],
            periodEnd=row["period_end"],
            punchEventCount=row["punch_event_count"],
            startedAt=row["started_at"],
            finishedAt=row["finished_at"],
            rolledBackAt=row["rolled_back_at"],
            errorMessage=row["error_message"],
            coveredDays=len(days),
            sourceSha256=row["source_sha256"],
            findings=findings,
            # The coverage facts, kept apart from any attendance verdict: a
            # reported_zero day is what the file said, not an absence.
            days=[
                {
                    "workDate": day["work_date"],
                    "coverage": day["coverage_status"],
                    "punches": day["raw_punch_count"],
                }
                for day in days
            ],
        )
    finally:
        conn.close()


# `원본기록` in the UI: where the preserved source files live, without ever
# serving one over HTTP. The files stay on the work PC's disk.
@router.get("/{run_id}/source", summary="Where the preserved original is stored")
def get_source_location(run_id: int) -> dict:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT stored_source_path, source_filename, source_sha256 "
            "  FROM import_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"no import run {run_id}")
        stored = Path(row["stored_source_path"] or "")
        return {
            "sourceFilename": row["source_filename"],
            "storedPath": str(stored),
            "exists": stored.is_file(),
            "sha256": row["source_sha256"],
        }
    finally:
        conn.close()
