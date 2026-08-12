"""Fingerprint XLS import over HTTP (AI_BUILD_PLAN.md §7 Phase 3).

These are the first mutation endpoints in the console, so the shape is
deliberately narrow:

    POST   /api/v1/imports                 upload -> preview      (no business
                                                                   data written)
    POST   /api/v1/imports/{id}/apply      confirm and commit
    POST   /api/v1/imports/{id}/rollback   undo, without deleting a punch
    GET    /api/v1/imports                 what has been imported
    GET    /api/v1/imports/pending         previews waiting on a human
    GET    /api/v1/imports/{id}            one run, with its coverage
    GET    /api/v1/imports/{id}/preview    the stored preview, re-openable later

Three rules the endpoints exist to enforce:

* Nothing is written to attendance without a second, explicit request carrying
  the token the preview issued. A single mis-click cannot import.
* An import is refused on a demo-seeded database. Attaching real punches to 18
  invented people produces a file nobody can trust afterwards.
* Every apply and rollback writes an audit_log row inside the same transaction
  as the change (done by the service, pinned by tests).

This module only translates HTTP to and from the service layer: it decides
status codes and parses multipart uploads, nothing else. Every rule — including
the refusal to import into a demo-seeded database — lives in
`app/services/xls_pipeline.py`, so a second interface onto the same functions
cannot end up with a different set of guarantees. The read shapes come from the
service too, for the same reason Phase 2 shares `app/services/ops.py` between
the API and the snapshot exporter.
"""

from __future__ import annotations

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
from app.services import xls_import, xls_pipeline

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])

ALLOWED_SUFFIXES = (".xls",)


def _connect(read_only: bool = True):
    if not config.DB_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="database not initialised; start the backend once to run migrations",
        )
    return db.connect(config.DB_PATH, read_only=read_only)


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
    source, filename, holder = _store_upload(file)
    try:
        preview = xls_pipeline.preview_import(source, original_filename=filename)
    except xls_pipeline.DemoContextRefused as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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


@router.get("/pending", summary="Imports waiting for a human to confirm")
def list_pending() -> dict:
    """The queue the folder watch fills.

    A watched file is previewed automatically, then stops here. Nothing in this
    list has changed any attendance data.
    """
    conn = _connect()
    try:
        runs = xls_pipeline.pending_imports(conn)
    finally:
        conn.close()
    return {
        "pending": runs,
        "watchDir": str(config.WATCH_DIR) if config.WATCH_DIR else None,
    }


@router.get("/{run_id}/preview", summary="The stored preview for a run")
def get_preview(run_id: int) -> dict:
    """Re-open a preview that was computed earlier, possibly by the watcher.

    This is the review snapshot. Applying does not trust it: `apply` re-reads
    the preserved file and recomputes the preview against the current slot
    mapping before it writes anything.
    """
    conn = _connect()
    try:
        run = xls_pipeline.import_run_detail(conn, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"no import run {run_id}")
        preview = xls_pipeline.stored_preview(conn, run_id)
        if preview is None:
            raise HTTPException(
                status_code=409,
                detail=f"import run {run_id} is '{run['status']}' and has no stored preview",
            )
        return preview
    finally:
        conn.close()


@router.get("", response_model=list[ImportRunSummary], summary="Import history")
def list_runs(limit: int = 50) -> list[ImportRunSummary]:
    conn = _connect()
    try:
        return [ImportRunSummary(**row) for row in xls_pipeline.import_history(conn, limit)]
    finally:
        conn.close()


@router.get("/{run_id}", response_model=ImportRunDetail, summary="One import run")
def get_run(run_id: int) -> ImportRunDetail:
    conn = _connect()
    try:
        detail = xls_pipeline.import_run_detail(conn, run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"no import run {run_id}")
        return ImportRunDetail(**detail)
    finally:
        conn.close()


# `원본기록` in the UI: where the preserved source files live, without ever
# serving one over HTTP. The files stay on the work PC's disk.
@router.get("/{run_id}/source", summary="Where the preserved original is stored")
def get_source_location(run_id: int) -> dict:
    conn = _connect()
    try:
        source = xls_pipeline.preserved_source(conn, run_id)
        if source is None:
            raise HTTPException(status_code=404, detail=f"no import run {run_id}")
        return source
    finally:
        conn.close()
