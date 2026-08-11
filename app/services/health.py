"""Health / status information for the backend.

Phase 1 exposes only what the operator needs to trust the host: whether the
database is reachable, which schema version it is on, whether foreign keys are
being enforced, and when fingerprint data was last imported.

The fingerprint timestamp is deliberately part of health from day one: the real
terminal exports monthly XLS files, so attendance data is routinely stale and
the UI must never imply it is live (AI_BUILD_PLAN.md §3).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app import config, db

# Tables Phase 1 must provide (AI_BUILD_PLAN.md §7 Phase 1) plus the supporting
# tables the data rules require.
REQUIRED_TABLES = (
    "employees",
    "attendance_days",
    "punch_events",
    "leave_requests",
    "replacement_assignments",
    "notes",
    "documents",
    "site_calendar",
    "audit_log",
    "import_runs",
)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def fingerprint_status(conn) -> dict[str, Any]:
    """Last successfully applied fingerprint import, and whether it is stale."""
    row = conn.execute(
        """
        SELECT id, source_filename, period_start, period_end,
               COALESCE(finished_at, updated_at) AS synced_at
          FROM import_runs
         WHERE status = 'applied' AND source_kind = 'fingerprint_xls'
         ORDER BY COALESCE(finished_at, updated_at) DESC, id DESC
         LIMIT 1
        """
    ).fetchone()

    if row is None:
        return {
            "last_import_at": None,
            "last_import_id": None,
            "source_filename": None,
            "period_start": None,
            "period_end": None,
            "is_stale": True,
            "stale_after_hours": config.FINGERPRINT_STALE_AFTER_HOURS,
        }

    synced_at = _parse_timestamp(row["synced_at"])
    is_stale = True
    if synced_at is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=config.FINGERPRINT_STALE_AFTER_HOURS
        )
        is_stale = synced_at < cutoff

    return {
        "last_import_at": row["synced_at"],
        "last_import_id": row["id"],
        "source_filename": row["source_filename"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "is_stale": is_stale,
        "stale_after_hours": config.FINGERPRINT_STALE_AFTER_HOURS,
    }


def health_report(db_path: Path | str | None = None) -> dict[str, Any]:
    """Collect the full health payload. Never raises for a degraded database."""
    path = Path(db_path) if db_path is not None else config.DB_PATH
    report: dict[str, Any] = {
        "status": "ok",
        "database": {
            "path": str(path),
            "exists": path.exists(),
            "reachable": False,
            "foreign_keys_enforced": False,
            "schema_version": 0,
            "applied_migrations": [],
            "missing_tables": list(REQUIRED_TABLES),
        },
        "fingerprint": {
            "last_import_at": None,
            "last_import_id": None,
            "source_filename": None,
            "period_start": None,
            "period_end": None,
            "is_stale": True,
            "stale_after_hours": config.FINGERPRINT_STALE_AFTER_HOURS,
        },
        "detail": None,
    }

    if not path.exists():
        report["status"] = "degraded"
        report["detail"] = f"database file does not exist: {path}"
        return report

    try:
        # Read-only: a health check must never create or migrate anything.
        with db.connection(path, read_only=True) as conn:
            report["database"]["reachable"] = True
            report["database"]["foreign_keys_enforced"] = db.foreign_keys_enabled(conn)

            existing = set(db.table_names(conn))
            missing = [t for t in REQUIRED_TABLES if t not in existing]
            report["database"]["missing_tables"] = missing

            if "schema_migrations" in existing:
                applied = [
                    int(row[0])
                    for row in conn.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    )
                ]
                report["database"]["applied_migrations"] = applied
                report["database"]["schema_version"] = max(applied) if applied else 0

            if "import_runs" in existing:
                report["fingerprint"] = fingerprint_status(conn)

            if missing:
                report["status"] = "degraded"
                report["detail"] = f"missing tables: {', '.join(missing)}"
            elif not report["database"]["foreign_keys_enforced"]:
                report["status"] = "degraded"
                report["detail"] = "foreign key enforcement is off"
    except Exception as exc:  # database unreachable / corrupt — report, do not crash
        report["status"] = "error"
        report["detail"] = f"{type(exc).__name__}: {exc}"

    return report
