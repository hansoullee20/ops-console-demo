"""Preview, apply and roll back a fingerprint XLS import.

The flow is the one AI_BUILD_PLAN.md §7 Phase 3 requires:

    upload -> preserve original -> parse -> preview -> findings
           -> snapshot -> explicit confirmation -> apply -> import_run -> rollback

Preview touches no data. Apply is a single transaction, guarded by a
confirmation token issued by the preview, and takes a database snapshot first.

Rollback never deletes a punch. Raw events are marked `rolled_back_at` and stay
in the table forever (§2.4); derived attendance for the affected dates is
recomputed afterwards.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app import config, db, migrate
from app.rules import punch_review
from app.rules.punch_review import Finding
from app.services import xls_import
from app.services.xls_import import ParsedWorkbook, dedupe_key

TERMINAL_ID = "default"


class ImportError_(RuntimeError):
    """The import could not proceed."""


@dataclass
class ImportPreview:
    import_run_id: int
    source_filename: str
    stored_source_path: str
    source_sha256: str
    period_start: str
    period_end: str
    confirmation_token: str
    slots: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    new_punches: int = 0
    already_imported: int = 0
    zero_punch_dates: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> list[dict]:
        return [f for f in self.findings if f["severity"] == "blocking"]

    def as_dict(self) -> dict:
        return {
            "importRunId": self.import_run_id,
            "sourceFilename": self.source_filename,
            "periodStart": self.period_start,
            "periodEnd": self.period_end,
            "confirmationToken": self.confirmation_token,
            "slots": self.slots,
            "findings": self.findings,
            "newPunches": self.new_punches,
            "alreadyImported": self.already_imported,
            "zeroPunchDates": self.zero_punch_dates,
            "canApply": not self.blocking and self.new_punches > 0,
        }


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dates_in(period_start: str, period_end: str) -> list[str]:
    from app.services.ops import _date_range

    start_day = int(period_start[8:10])
    end_day = int(period_end[8:10])
    return _date_range(period_start, end_day - start_day + 1)


def _slot_mapping(conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute(
        """
        SELECT t.slot_code, t.status AS slot_status, e.id AS employee_id, e.name,
               e.status AS employee_status, e.hire_date, e.end_date
          FROM terminal_slots t
          LEFT JOIN employees e ON e.id = t.employee_id
         WHERE t.terminal_id = ?
        """,
        (TERMINAL_ID,),
    ).fetchall()
    return {row["slot_code"]: dict(row) for row in rows}


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------
def preview_import(
    source_path: Path | str,
    *,
    db_path: Path | None = None,
    uploads_dir: Path | None = None,
    original_filename: str | None = None,
    threshold_minutes: int = punch_review.DEFAULT_REPEATED_PUNCH_MINUTES,
    created_by: str = "operator",
) -> ImportPreview:
    """Parse, preserve the original, and report what applying would do."""
    source_path = Path(source_path)
    uploads = Path(uploads_dir) if uploads_dir else config.UPLOADS_DIR
    uploads.mkdir(parents=True, exist_ok=True)

    filename = original_filename or source_path.name
    digest = _sha256(source_path)
    stored = uploads / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{digest[:12]}-{filename}"
    if source_path.resolve() != stored.resolve():
        shutil.copy2(source_path, stored)

    parsed = xls_import.parse_workbook(stored, source_filename=filename)

    conn = db.connect(db_path or config.DB_PATH)
    try:
        token = secrets.token_urlsafe(24)
        cursor = conn.execute(
            """
            INSERT INTO import_runs
                (source_filename, stored_source_path, source_sha256, source_kind,
                 period_start, period_end, status, source_row_count, created_by, started_at)
            VALUES (?, ?, ?, 'fingerprint_xls', ?, ?, 'previewed', ?, ?, ?)
            """,
            (
                filename, str(stored), digest,
                parsed.period_start, parsed.period_end,
                len(parsed.punches), created_by, _now(),
            ),
        )
        run_id = int(cursor.lastrowid)

        preview = _build_preview(conn, parsed, run_id, stored, digest, token, threshold_minutes)
        conn.execute(
            "UPDATE import_runs SET findings_json = ? WHERE id = ?",
            (json.dumps({"token": token, "findings": preview.findings}, ensure_ascii=False), run_id),
        )
        conn.commit()
        return preview
    finally:
        conn.close()


def _build_preview(
    conn: sqlite3.Connection,
    parsed: ParsedWorkbook,
    run_id: int,
    stored: Path,
    digest: str,
    token: str,
    threshold_minutes: int,
) -> ImportPreview:
    mapping = _slot_mapping(conn)
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT dedupe_key FROM punch_events WHERE dedupe_key IS NOT NULL"
        )
    }

    findings: list[Finding] = []
    slot_rows: list[dict] = []
    new_punches = already = 0

    by_slot_day: dict[tuple[str, str], list] = {}
    for punch in parsed.punches:
        by_slot_day.setdefault((punch.slot_code, punch.work_date), []).append(punch)

    for slot in parsed.slots:
        mapped = mapping.get(slot.slot_code)
        employee = mapped["name"] if mapped and mapped.get("employee_id") else None
        status = "mapped"
        if slot.punch_count == 0:
            status = "unused"
            findings.append(Finding(
                "unused_slot", "info",
                f"슬롯 {slot.slot_code}: 이 기간에 기록이 없습니다. 결근으로 처리하지 않습니다.",
                slot_code=slot.slot_code,
            ))
        elif not mapped or not mapped.get("employee_id"):
            status = "unmapped"
            findings.append(Finding(
                "unmapped_slot", "review",
                f"슬롯 {slot.slot_code}({slot.display_name or '이름없음'}): 직원 매핑이 없습니다. "
                "원본 기록은 보존되며 직원에 연결되지 않습니다.",
                slot_code=slot.slot_code,
            ))
        elif mapped["employee_status"] != "active":
            status = "inactive"
            findings.append(Finding(
                "inactive_employee", "review",
                f"슬롯 {slot.slot_code}: 재직 상태가 아닌 직원({mapped['employee_status']})의 기록입니다.",
                slot_code=slot.slot_code, employee=employee,
            ))

        slot_rows.append({
            "slot": slot.slot_code,
            "terminalName": slot.display_name,
            "employee": employee,
            "status": status,
            "punchCount": slot.punch_count,
            "dayCount": slot.day_count,
        })

    for (slot_code, work_date), punches in sorted(by_slot_day.items()):
        mapped = mapping.get(slot_code)
        employee = mapped["name"] if mapped and mapped.get("employee_id") else None
        times = [p.punch_time for p in punches]
        review = punch_review.review_day(times, threshold_minutes)

        for punch in punches:
            if dedupe_key(TERMINAL_ID, punch) in existing:
                already += 1
            else:
                new_punches += 1

        if review["has_repeated_candidate"]:
            findings.append(Finding(
                "repeated_punch_candidate", "review",
                f"{threshold_minutes}분 이내 재태그 후보: {' · '.join(times)} — 원본은 모두 보존됩니다.",
                slot_code=slot_code, work_date=work_date, employee=employee,
            ))
        if review["exact_repeat_count"]:
            findings.append(Finding(
                "duplicate_timestamp", "info",
                f"동일 시각 {review['exact_repeat_count']}건 반복: {' · '.join(times)} — 전부 별도 기록으로 보존됩니다.",
                slot_code=slot_code, work_date=work_date, employee=employee,
            ))
        if review["incomplete"]:
            findings.append(Finding(
                "incomplete_day", "review",
                f"펀치가 1건뿐입니다({times[0]}). 결근이나 정상근무로 단정하지 않습니다.",
                slot_code=slot_code, work_date=work_date, employee=employee,
            ))
        if mapped and mapped.get("employee_id"):
            if mapped["hire_date"] and work_date < mapped["hire_date"]:
                findings.append(Finding(
                    "before_hire_date", "review",
                    f"입사일({mapped['hire_date']}) 이전의 기록입니다.",
                    slot_code=slot_code, work_date=work_date, employee=employee,
                ))
            conflict = conn.execute(
                """
                SELECT 1 FROM leave_requests
                 WHERE employee_id = ? AND status = 'approved'
                   AND start_date <= ? AND end_date >= ?
                """,
                (mapped["employee_id"], work_date, work_date),
            ).fetchone()
            if conflict:
                findings.append(Finding(
                    "leave_conflict", "review",
                    "승인된 휴가 기간인데 지문 기록이 있습니다. 어느 쪽도 자동으로 수정하지 않습니다.",
                    slot_code=slot_code, work_date=work_date, employee=employee,
                ))

    period_dates = _dates_in(parsed.period_start, parsed.period_end)
    zero_dates = punch_review.whole_site_zero_punch_dates(period_dates, set(parsed.dates))
    for date in zero_dates:
        findings.append(Finding(
            "whole_site_zero_punch", "review",
            "이 날짜에는 전 사업장 기록이 없습니다. 휴무·단말 장애·부분 export 중 무엇인지 "
            "확인이 필요하며, 전원 결근으로 처리하지 않습니다.",
            work_date=date,
        ))

    return ImportPreview(
        import_run_id=run_id,
        source_filename=parsed.source_filename,
        stored_source_path=str(stored),
        source_sha256=digest,
        period_start=parsed.period_start,
        period_end=parsed.period_end,
        confirmation_token=token,
        slots=slot_rows,
        findings=[f.as_dict() for f in findings],
        new_punches=new_punches,
        already_imported=already,
        zero_punch_dates=zero_dates,
    )


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------
def _snapshot(db_path: Path, backups_dir: Path, label: str) -> Path:
    backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    target = backups_dir / f"{db_path.stem}-pre-import-{label}-{stamp}.db"
    source = db.connect(db_path)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()
    return target


def apply_import(
    import_run_id: int,
    confirmation_token: str,
    *,
    db_path: Path | None = None,
    backups_dir: Path | None = None,
    threshold_minutes: int = punch_review.DEFAULT_REPEATED_PUNCH_MINUTES,
    actor_id: str = "operator",
) -> dict:
    """Commit a previewed import. Requires the token the preview issued."""
    path = Path(db_path or config.DB_PATH)
    backups = Path(backups_dir or config.BACKUPS_DIR)

    conn = db.connect(path)
    try:
        run = conn.execute("SELECT * FROM import_runs WHERE id = ?", (import_run_id,)).fetchone()
        if run is None:
            raise ImportError_(f"no import run {import_run_id}")
        if run["status"] != "previewed":
            raise ImportError_(
                f"import run {import_run_id} is '{run['status']}'; only a previewed run can be applied"
            )
        stored = json.loads(run["findings_json"] or "{}")
        if not secrets.compare_digest(str(stored.get("token", "")), confirmation_token):
            raise ImportError_("confirmation token does not match this preview")

        source = Path(run["stored_source_path"])
        if not source.exists():
            raise ImportError_(f"preserved source file is missing: {source}")
        # Re-read from the preserved original rather than trusting anything
        # carried over from the preview request.
        parsed = xls_import.parse_workbook(source, source_filename=run["source_filename"])
    finally:
        conn.close()

    snapshot = _snapshot(path, backups, str(import_run_id))

    conn = db.connect(path)
    try:
        mapping = _slot_mapping(conn)
        inserted = skipped = reactivated = 0
        touched: set[tuple[int, str]] = set()

        conn.execute("BEGIN")
        for punch in parsed.punches:
            mapped = mapping.get(punch.slot_code) or {}
            employee_id = mapped.get("employee_id")
            key = dedupe_key(TERMINAL_ID, punch)
            cursor = conn.execute(
                """
                INSERT INTO punch_events
                    (terminal_id, terminal_slot_code, punch_at, work_date, punch_type,
                     raw_payload, source_filename, source_row_no, source_hash,
                     dedupe_key, import_run_id, employee_id, review_flag)
                VALUES (?, ?, ?, ?, 'unknown', ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO NOTHING
                """,
                (
                    TERMINAL_ID, punch.slot_code, punch.punch_at, punch.work_date,
                    punch.raw_cell, run["source_filename"], punch.sequence,
                    run["source_sha256"], key, import_run_id, employee_id,
                    None if employee_id else "unmapped_slot",
                ),
            )
            if cursor.rowcount:
                inserted += 1
            else:
                skipped += 1
                # Re-applying a source that was rolled back reactivates its
                # events rather than inserting duplicates. The raw columns are
                # untouched; only the rollback marker is cleared.
                reactivated += conn.execute(
                    "UPDATE punch_events "
                    "   SET rolled_back_at = NULL, rolled_back_reason = NULL "
                    " WHERE dedupe_key = ? AND rolled_back_at IS NOT NULL",
                    (key,),
                ).rowcount
            if employee_id:
                touched.add((employee_id, punch.work_date))

        _flag_repeated_punches(conn, import_run_id, threshold_minutes)
        derived = derive_attendance(conn, sorted(touched))

        conn.execute(
            """
            UPDATE import_runs
               SET status = 'applied', finished_at = ?, punch_event_count = ?,
                   snapshot_path = ?
             WHERE id = ?
            """,
            (_now(), inserted, str(snapshot), import_run_id),
        )
        conn.execute(
            """
            INSERT INTO audit_log (actor_type, actor_id, action, entity_type, entity_id,
                                   after_json, reason, confirmation_token)
            VALUES ('import', ?, 'import.apply', 'import_runs', ?, ?, ?, ?)
            """,
            (
                actor_id, import_run_id,
                json.dumps({"inserted": inserted, "skipped": skipped,
                            "reactivated": reactivated, "attendance": derived},
                           ensure_ascii=False),
                f"{run['source_filename']} 적용",
                confirmation_token,
            ),
        )
        conn.commit()
        return {
            "importRunId": import_run_id,
            "inserted": inserted,
            "alreadyPresent": skipped,
            "reactivated": reactivated,
            "attendanceRows": derived,
            "snapshotPath": str(snapshot),
        }
    except Exception:
        conn.rollback()
        conn.execute(
            "UPDATE import_runs SET status = 'failed', error_message = ? WHERE id = ?",
            ("apply failed and was rolled back", import_run_id),
        )
        conn.commit()
        raise
    finally:
        conn.close()


def _flag_repeated_punches(
    conn: sqlite3.Connection, import_run_id: int, threshold_minutes: int
) -> None:
    """Annotate re-tag candidates. Never merges or removes anything."""
    rows = conn.execute(
        """
        SELECT id, terminal_slot_code, work_date, punch_at
          FROM punch_events WHERE import_run_id = ? AND rolled_back_at IS NULL
         ORDER BY terminal_slot_code, work_date, punch_at, id
        """,
        (import_run_id,),
    ).fetchall()
    by_day: dict[tuple[str, str], list] = {}
    for row in rows:
        by_day.setdefault((row["terminal_slot_code"], row["work_date"]), []).append(row)

    for group in by_day.values():
        times = [row["punch_at"][11:16] for row in group]
        for index in punch_review.repeated_punch_indexes(times, threshold_minutes):
            conn.execute(
                "UPDATE punch_events SET review_flag = 'repeated_punch_candidate' "
                "WHERE id = ? AND review_flag IS NULL",
                (group[index]["id"],),
            )


def derive_attendance(conn: sqlite3.Connection, employee_days: list[tuple[int, str]]) -> int:
    """Derive attendance_days from punches for the given employee-days.

    Rules, all conservative:
      * two or more punches      -> normal
      * exactly one punch        -> unknown, flagged incomplete (never absent)
      * no punches left          -> a fingerprint-derived row is reset to
                                    unknown, because the evidence behind it is
                                    gone (this is what a rollback leaves). It is
                                    never turned into an absence, and rows from
                                    another source are left alone.
      * a row a human confirmed  -> never overwritten by an import

    Uses ON CONFLICT DO UPDATE. INSERT OR REPLACE would destroy the row's id,
    created_at, revision history and notes (finding N1).
    """
    written = 0
    for employee_id, work_date in employee_days:
        times = [
            row[0][11:16]
            for row in conn.execute(
                "SELECT punch_at FROM punch_events "
                " WHERE employee_id = ? AND work_date = ? AND rolled_back_at IS NULL "
                " ORDER BY punch_at",
                (employee_id, work_date),
            )
        ]
        existing = conn.execute(
            "SELECT id, confirmed_at, source FROM attendance_days "
            " WHERE employee_id = ? AND work_date = ?",
            (employee_id, work_date),
        ).fetchone()
        if existing and existing["confirmed_at"]:
            continue

        if not times:
            # Every punch behind this day was rolled back. Leaving it as
            # 'normal' would show attendance backed by nothing.
            if existing and existing["source"] == "fingerprint":
                conn.execute(
                    "UPDATE attendance_days "
                    "   SET status = 'unknown', actual_in_at = NULL, actual_out_at = NULL, "
                    "       review_flag = 'import_rolled_back' "
                    " WHERE id = ?",
                    (existing["id"],),
                )
                written += 1
            continue

        status = "normal" if len(times) >= 2 else "unknown"
        review_flag = None if len(times) >= 2 else "incomplete_day"
        conn.execute(
            """
            INSERT INTO attendance_days
                (employee_id, work_date, status, actual_in_at, actual_out_at, source, review_flag)
            VALUES (?, ?, ?, ?, ?, 'fingerprint', ?)
            ON CONFLICT(employee_id, work_date) DO UPDATE SET
                status = excluded.status,
                actual_in_at = excluded.actual_in_at,
                actual_out_at = excluded.actual_out_at,
                source = 'fingerprint',
                review_flag = COALESCE(attendance_days.review_flag, excluded.review_flag)
            """,
            (employee_id, work_date, status, times[0], times[-1] if len(times) > 1 else None, review_flag),
        )
        written += 1
    return written


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------
def rollback_import(
    import_run_id: int,
    reason: str,
    *,
    db_path: Path | None = None,
    actor_id: str = "operator",
) -> dict:
    """Undo an applied import without deleting a single raw punch.

    §2.4 is absolute: raw events are marked rolled_back_at and stay in the
    table. Derived attendance for the affected days is recomputed from whatever
    punches remain active.
    """
    if not reason or not reason.strip():
        raise ImportError_("a rollback must carry a reason for the audit log")

    conn = db.connect(Path(db_path or config.DB_PATH))
    try:
        run = conn.execute("SELECT * FROM import_runs WHERE id = ?", (import_run_id,)).fetchone()
        if run is None:
            raise ImportError_(f"no import run {import_run_id}")
        if run["status"] != "applied":
            raise ImportError_(
                f"import run {import_run_id} is '{run['status']}'; only an applied run can be rolled back"
            )

        affected = conn.execute(
            "SELECT DISTINCT employee_id, work_date FROM punch_events "
            " WHERE import_run_id = ? AND employee_id IS NOT NULL",
            (import_run_id,),
        ).fetchall()

        conn.execute("BEGIN")
        marked = conn.execute(
            "UPDATE punch_events SET rolled_back_at = ?, rolled_back_reason = ? "
            " WHERE import_run_id = ? AND rolled_back_at IS NULL",
            (_now(), reason, import_run_id),
        ).rowcount
        redone = derive_attendance(conn, [(r["employee_id"], r["work_date"]) for r in affected])

        conn.execute(
            "UPDATE import_runs SET status = 'rolled_back', rolled_back_at = ? WHERE id = ?",
            (_now(), import_run_id),
        )
        conn.execute(
            """
            INSERT INTO audit_log (actor_type, actor_id, action, entity_type, entity_id,
                                   after_json, reason)
            VALUES ('import', ?, 'import.rollback', 'import_runs', ?, ?, ?)
            """,
            (actor_id, import_run_id,
             json.dumps({"punchesMarked": marked, "attendanceRedone": redone}, ensure_ascii=False),
             reason),
        )
        conn.commit()
        return {"importRunId": import_run_id, "punchesMarkedRolledBack": marked,
                "attendanceRecomputed": redone, "punchesDeleted": 0}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def last_applied_import(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT id, source_filename, period_start, period_end, finished_at, punch_event_count "
        "  FROM import_runs WHERE status = 'applied' AND source_kind = 'fingerprint_xls' "
        " ORDER BY COALESCE(finished_at, updated_at) DESC, id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None
