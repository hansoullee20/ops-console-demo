"""Operational month reconciliation, close, reopen and snapshot export API."""
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, Field

from app import config, db
from app.services import month_close
from app.services.xls_pipeline import DemoContextRefused, ensure_import_allowed

router = APIRouter(prefix="/api/v1/month-close", tags=["month-close"])


class Action(BaseModel):
    actor: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=2, max_length=500)


def _allowed():
    try:
        ensure_import_allowed()
    except DemoContextRefused as exc:
        raise HTTPException(409, str(exc)) from exc


def _error(exc: month_close.MonthCloseError):
    detail = {"message": str(exc), "blockingItems": exc.blocking_items}
    return HTTPException(409, detail=detail)


@router.get("/{month}/reconciliation")
def reconciliation(month: str):
    _allowed(); conn = db.connect(config.DB_PATH)
    try:
        with conn:
            return month_close.reconcile(conn, month)
    except month_close.MonthCloseError as exc:
        raise _error(exc)
    finally:
        conn.close()


@router.post("/{month}/close")
def close(month: str, body: Action):
    _allowed(); conn = db.connect(config.DB_PATH)
    try:
        conn.execute("BEGIN IMMEDIATE")
        result = month_close.close_month(conn, month, body.actor, body.reason)
        conn.commit(); return result
    except (month_close.MonthCloseError, Exception) as exc:
        conn.rollback()
        if isinstance(exc, month_close.MonthCloseError): raise _error(exc)
        raise
    finally:
        conn.close()


@router.get("/{month}")
def get_close(month: str):
    _allowed(); conn = db.connect(config.DB_PATH, read_only=True)
    try:
        result = month_close.latest(conn, month)
        if not result: raise HTTPException(404, "month close not found")
        return result
    finally:
        conn.close()


@router.get("/{month}/snapshot")
def get_snapshot(month: str):
    _allowed(); conn = db.connect(config.DB_PATH, read_only=True)
    try: return month_close.snapshot(conn, month)
    except month_close.MonthCloseError as exc: raise HTTPException(404, str(exc))
    finally: conn.close()


@router.post("/{month}/reopen")
def reopen(month: str, body: Action):
    _allowed(); conn = db.connect(config.DB_PATH)
    try:
        conn.execute("BEGIN IMMEDIATE")
        result = month_close.reopen(conn, month, body.actor, body.reason)
        conn.commit(); return result
    except month_close.MonthCloseError as exc:
        conn.rollback(); raise _error(exc)
    finally: conn.close()


@router.get("/{month}/export.xlsx")
def export(month: str):
    _allowed(); conn = db.connect(config.DB_PATH, read_only=True)
    try: payload = month_close.export_xls(conn, month)
    except month_close.MonthCloseError as exc: raise HTTPException(409, str(exc))
    finally: conn.close()
    return Response(payload, media_type="application/vnd.ms-excel",
                    headers={"Content-Disposition": f'attachment; filename="attendance-{month}.xls"'})
