"""Preview, apply and roll back a fingerprint XLS import.

The flow is the one AI_BUILD_PLAN.md §7 Phase 3 requires:

     1. upload, preserve the original, open an import_run (pending)
     2. hash the source
     3. parse
     4. build the preview            (no business data written)
     5. slot mapping / findings
     6. preview fingerprint + snapshot
     7. explicit confirmation
     8. verify the token still matches this file AND this preview
     9. apply, in one transaction
    10. import_run -> applied, with per-date coverage recorded
    11. rollback available

The import_run exists from the upload, not from the apply: it represents the
whole lifecycle, which is what its pending/previewed/applied/failed/rolled_back
states were designed for.

The confirmation token is bound to import_run_id + source_sha256 + a fingerprint
of the preview itself. If the file or the slot mapping changed after the
operator reviewed it, the old confirmation no longer applies. This guards
against a work mistake, not an attacker.

Rollback never deletes a punch. Raw events are marked `rolled_back_at` and stay
in the table forever (§2.4). Derived attendance is recomputed from what remains,
but only for rows this import actually produced and that nobody has touched
since — anything else becomes a rollback_conflict finding instead of being
overwritten.
"""

from __future__ import annotations

import hashlib
import json
import re
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


class DemoContextRefused(ImportError_):
    """This database holds the fictional demo dataset; imports are refused."""


def ensure_import_allowed(db_path: Path | None = None) -> None:
    """Refuse to import real records into a database full of invented people.

    This lives in the service layer, not in the HTTP router, because it is a
    business rule rather than a transport concern. Every interface that can
    start an import — the API, the folder watcher, and any later tool layer —
    gets it by calling the same service functions, instead of each remembering
    to re-check. It used to be implemented separately in two places, which is
    how a third caller ends up without it.
    """
    if config.ALLOW_DEMO_IMPORT:
        return
    path = Path(db_path or config.DB_PATH)
    if not path.exists():
        return
    from app.services import ops  # noqa: PLC0415 - avoids an import cycle

    with db.connection(path, read_only=True) as conn:
        context = ops.data_context(conn)["data_context"]
    if context == "demo":
        raise DemoContextRefused(
            "이 데이터베이스는 데모 시드(data_context=demo)입니다. 실제 지문 기록을 "
            "가져오면 가상 직원 18명과 섞여 어느 쪽이 실제인지 구분할 수 없게 됩니다. "
            "운영용 데이터베이스에서 실행하십시오. 데모 시드로 흐름만 확인하려면 "
            "OPS_ALLOW_DEMO_IMPORT=1 로 백엔드를 실행하십시오."
        )


@dataclass
class ImportPreview:
    import_run_id: int
    source_filename: str
    stored_source_path: str
    source_sha256: str
    period_start: str
    period_end: str
    confirmation_token: str
    preview_fingerprint: str = ""
    slots: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    new_punches: int = 0
    already_imported: int = 0
    zero_punch_dates: list[str] = field(default_factory=list)
    covered_dates: list[str] = field(default_factory=list)

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
            "coveredDates": self.covered_dates,
            "previewFingerprint": self.preview_fingerprint,
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


def _safe_name(filename: str) -> str:
    """A filename that can only ever land inside the uploads directory.

    The operator's file name is recorded verbatim in import_runs; this is only
    for the stored copy's path. Without it, a name like `../../index.html`
    would write outside uploads/.
    """
    name = Path(str(filename or "")).name
    name = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", name).strip("._") or "upload.xls"
    return name[:120]


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
def _preview_fingerprint(digest: str, slot_rows: list[dict], new_punches: int) -> str:
    """A digest of what the operator actually reviewed.

    Covers the file and the slot mapping the preview was computed against, so a
    mapping change between review and apply invalidates the confirmation.
    """
    payload = json.dumps(
        {
            "source": digest,
            "slots": [
                {k: row[k] for k in ("slot", "employee", "status", "punchCount")}
                for row in slot_rows
            ],
            "newPunches": new_punches,
        },
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _confirmation_token(run_id: int, digest: str, fingerprint: str, nonce: str) -> str:
    material = f"{run_id}|{digest}|{fingerprint}|{nonce}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def preview_import(
    source_path: Path | str,
    *,
    db_path: Path | None = None,
    uploads_dir: Path | None = None,
    original_filename: str | None = None,
    threshold_minutes: int = punch_review.DEFAULT_REPEATED_PUNCH_MINUTES,
    created_by: str = "operator",
    discovered_by: str = "upload",
) -> ImportPreview:
    """Preserve the original, open an import run, and report what apply would do.

    Writes no punch, attendance, leave or replacement data.
    """
    ensure_import_allowed(db_path)
    source_path = Path(source_path)
    uploads = Path(uploads_dir) if uploads_dir else config.UPLOADS_DIR
    uploads.mkdir(parents=True, exist_ok=True)

    filename = original_filename or source_path.name
    digest = _sha256(source_path)
    stored = uploads / (
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{digest[:12]}-{_safe_name(filename)}"
    )
    if source_path.resolve() != stored.resolve():
        shutil.copy2(source_path, stored)

    conn = db.connect(db_path or config.DB_PATH)
    try:
        # Step 1: the run exists from the upload, before anything is parsed, so
        # a file that fails to parse still leaves a record of the attempt.
        cursor = conn.execute(
            """
            INSERT INTO import_runs
                (source_filename, stored_source_path, source_sha256, source_kind,
                 status, created_by, started_at, discovered_by)
            VALUES (?, ?, ?, 'fingerprint_xls', 'pending', ?, ?, ?)
            """,
            (filename, str(stored), digest, created_by, _now(), discovered_by),
        )
        run_id = int(cursor.lastrowid)
        conn.commit()

        try:
            parsed = xls_import.parse_workbook(stored, source_filename=filename)
        except xls_import.XlsImportError as exc:
            conn.execute(
                "UPDATE import_runs SET status = 'failed', error_message = ? WHERE id = ?",
                (str(exc), run_id),
            )
            conn.commit()
            raise

        preview = _build_preview(conn, parsed, run_id, stored, digest, threshold_minutes)
        conn.execute(
            """
            UPDATE import_runs
               SET status = 'previewed', period_start = ?, period_end = ?,
                   source_row_count = ?, findings_json = ?,
                   preview_fingerprint = ?, confirmation_token = ?,
                   preview_json = ?
             WHERE id = ?
            """,
            (
                parsed.period_start, parsed.period_end, len(parsed.punches),
                json.dumps({"findings": preview.findings}, ensure_ascii=False),
                preview.preview_fingerprint, preview.confirmation_token,
                # Kept so a run previewed by the folder watcher can still be
                # reviewed hours later, by someone who never saw it happen.
                json.dumps(preview.as_dict(), ensure_ascii=False),
                run_id,
            ),
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

    # Only dates the source actually carried a column for can be reported as
    # quiet. A date the file never mentioned is simply not covered.
    zero_dates = punch_review.whole_site_zero_punch_dates(
        parsed.covered_dates, set(parsed.dates)
    )
    for date in zero_dates:
        findings.append(Finding(
            "whole_site_zero_punch", "review",
            "이 날짜에는 전 사업장 기록이 없습니다. 휴무·단말 장애·부분 export 중 무엇인지 "
            "확인이 필요하며, 전원 결근으로 처리하지 않습니다.",
            work_date=date,
        ))

    fingerprint = _preview_fingerprint(digest, slot_rows, new_punches)
    token = _confirmation_token(run_id, digest, fingerprint, secrets.token_urlsafe(16))

    return ImportPreview(
        import_run_id=run_id,
        source_filename=parsed.source_filename,
        stored_source_path=str(stored),
        source_sha256=digest,
        period_start=parsed.period_start,
        period_end=parsed.period_end,
        confirmation_token=token,
        preview_fingerprint=fingerprint,
        slots=slot_rows,
        findings=[f.as_dict() for f in findings],
        new_punches=new_punches,
        already_imported=already,
        zero_punch_dates=zero_dates,
        covered_dates=parsed.covered_dates,
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
    ensure_import_allowed(db_path)
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
        if not secrets.compare_digest(str(run["confirmation_token"] or ""), confirmation_token):
            raise ImportError_("confirmation token does not match this preview")

        source = Path(run["stored_source_path"])
        if not source.exists():
            raise ImportError_(f"preserved source file is missing: {source}")
        if _sha256(source) != run["source_sha256"]:
            raise ImportError_(
                "the preserved source file changed after the preview; review it again"
            )
        # Re-read from the preserved original rather than trusting anything
        # carried over from the preview request.
        parsed = xls_import.parse_workbook(source, source_filename=run["source_filename"])

        # Recompute the preview against the mapping as it stands *now*. If a
        # slot was mapped or unmapped since the operator reviewed it, they
        # confirmed something else.
        current = _build_preview(
            conn, parsed, import_run_id, source, run["source_sha256"], threshold_minutes
        )
        if current.preview_fingerprint != run["preview_fingerprint"]:
            raise ImportError_(
                "the slot mapping or file changed after this preview was reviewed; "
                "run the preview again before applying"
            )
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
                     raw_payload, source_filename, source_sheet, source_row_no,
                     source_column, source_cell, occurrence_index, source_hash,
                     dedupe_key, import_run_id, employee_id, review_flag)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dedupe_key) DO NOTHING
                """,
                (
                    TERMINAL_ID, punch.slot_code, punch.punch_at, punch.work_date,
                    punch.punch_type, punch.raw_cell, run["source_filename"],
                    punch.source_sheet, punch.source_row, punch.source_column,
                    punch.source_cell, punch.occurrence_index,
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
        _record_coverage(conn, import_run_id, parsed)
        derived = derive_attendance(conn, sorted(touched), import_run_id=import_run_id)

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


def _record_coverage(conn: sqlite3.Connection, import_run_id: int, parsed) -> None:
    """Record which dates this file covered, and how many punches each carried.

    This is what makes "the export said 2026-07-17 was empty" different from
    "August was never imported". Neither is an attendance verdict; the first is
    a fact about the source that a human still has to explain.
    """
    counts: dict[str, int] = {}
    for punch in parsed.punches:
        counts[punch.work_date] = counts.get(punch.work_date, 0) + 1

    for work_date in parsed.covered_dates:
        count = counts.get(work_date, 0)
        conn.execute(
            """
            INSERT INTO import_run_days
                (import_run_id, work_date, source_date_present, raw_punch_count, coverage_status)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT(import_run_id, work_date) DO UPDATE SET
                raw_punch_count = excluded.raw_punch_count,
                coverage_status = excluded.coverage_status
            """,
            (import_run_id, work_date, count,
             "has_punches" if count else "reported_zero"),
        )


def derive_attendance(
    conn: sqlite3.Connection,
    employee_days: list[tuple[int, str]],
    *,
    import_run_id: int | None = None,
) -> int:
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
                (employee_id, work_date, status, actual_in_at, actual_out_at, source,
                 review_flag, last_import_run_id)
            VALUES (?, ?, ?, ?, ?, 'fingerprint', ?, ?)
            ON CONFLICT(employee_id, work_date) DO UPDATE SET
                status = excluded.status,
                actual_in_at = excluded.actual_in_at,
                actual_out_at = excluded.actual_out_at,
                source = 'fingerprint',
                review_flag = COALESCE(attendance_days.review_flag, excluded.review_flag),
                last_import_run_id = COALESCE(excluded.last_import_run_id,
                                              attendance_days.last_import_run_id)
            """,
            (employee_id, work_date, status, times[0],
             times[-1] if len(times) > 1 else None, review_flag, import_run_id),
        )
        written += 1
    return written


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------
def _rollback_conflicts(
    conn: sqlite3.Connection, import_run_id: int, finished_at: str | None
) -> tuple[list[tuple[int, str]], list[Finding]]:
    """Split affected attendance rows into 'safe to revert' and 'touched since'.

    A row is only reverted when this import is the one that produced it and
    nobody has changed it since. Anything else is reported as a conflict rather
    than being silently overwritten — a rollback must not undo somebody's
    manual correction.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT a.id, a.employee_id, a.work_date, a.confirmed_at,
               a.last_import_run_id, a.source, e.name
          FROM punch_events p
          JOIN attendance_days a
            ON a.employee_id = p.employee_id AND a.work_date = p.work_date
          JOIN employees e ON e.id = a.employee_id
         WHERE p.import_run_id = ? AND p.employee_id IS NOT NULL
        """,
        (import_run_id,),
    ).fetchall()

    safe: list[tuple[int, str]] = []
    conflicts: list[Finding] = []
    for row in rows:
        if row["confirmed_at"]:
            conflicts.append(Finding(
                "rollback_conflict", "review",
                "관리자가 확정한 근태입니다. 롤백이 값을 되돌리지 않았습니다.",
                work_date=row["work_date"], employee=row["name"],
            ))
            continue
        if row["last_import_run_id"] != import_run_id:
            conflicts.append(Finding(
                "rollback_conflict", "review",
                "이 import 가 만든 행이 아닙니다(다른 import 또는 수기 입력). "
                "롤백이 값을 되돌리지 않았습니다.",
                work_date=row["work_date"], employee=row["name"],
            ))
            continue
        edited = conn.execute(
            """
            SELECT 1 FROM audit_log
             WHERE entity_type = 'attendance_days' AND entity_id = ?
               AND action = 'attendance.correct'
               AND (? IS NULL OR occurred_at > ?)
             LIMIT 1
            """,
            (row["id"], finished_at, finished_at),
        ).fetchone()
        if edited:
            conflicts.append(Finding(
                "rollback_conflict", "review",
                "import 이후 수동으로 수정된 근태입니다. 롤백이 값을 되돌리지 않았습니다.",
                work_date=row["work_date"], employee=row["name"],
            ))
            continue
        safe.append((row["employee_id"], row["work_date"]))
    return safe, conflicts


def rollback_import(
    import_run_id: int,
    reason: str,
    *,
    db_path: Path | None = None,
    actor_id: str = "operator",
) -> dict:
    """Undo an applied import without deleting a single raw punch.

    §2.4 is absolute: raw events are marked rolled_back_at and stay in the
    table. Derived attendance is recomputed only for rows this import produced
    and that nobody has touched since; the rest become rollback_conflict
    findings for a human to resolve.
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

        safe, conflicts = _rollback_conflicts(conn, import_run_id, run["finished_at"])

        conn.execute("BEGIN")
        marked = conn.execute(
            "UPDATE punch_events SET rolled_back_at = ?, rolled_back_reason = ? "
            " WHERE import_run_id = ? AND rolled_back_at IS NULL",
            (_now(), reason, import_run_id),
        ).rowcount
        redone = derive_attendance(conn, safe, import_run_id=import_run_id)

        conn.execute(
            "UPDATE import_runs SET status = 'rolled_back', rolled_back_at = ?, "
            "       findings_json = ? WHERE id = ?",
            (_now(),
             json.dumps({"rollbackConflicts": [c.as_dict() for c in conflicts]},
                        ensure_ascii=False),
             import_run_id),
        )
        conn.execute(
            """
            INSERT INTO audit_log (actor_type, actor_id, action, entity_type, entity_id,
                                   after_json, reason)
            VALUES ('import', ?, 'import.rollback', 'import_runs', ?, ?, ?)
            """,
            (actor_id, import_run_id,
             json.dumps({"punchesMarked": marked, "attendanceRedone": redone,
                         "conflicts": len(conflicts)}, ensure_ascii=False),
             reason),
        )
        conn.commit()
        return {
            "importRunId": import_run_id,
            "punchesMarkedRolledBack": marked,
            "attendanceRecomputed": redone,
            "punchesDeleted": 0,
            "conflicts": [c.as_dict() for c in conflicts],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# read models
#
# The API renders these; nothing re-queries import_runs on its own. Phase 2
# established the pattern with app/services/ops.py, where the API and the demo
# snapshot exporter share one set of read models so the two renderings cannot
# drift. The same reason applies to any later interface: a second caller that
# writes its own SQL is a second definition of what an import "is".
# ---------------------------------------------------------------------------
def import_history(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
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
        {
            "id": row["id"],
            "sourceFilename": row["source_filename"],
            "status": row["status"],
            "periodStart": row["period_start"],
            "periodEnd": row["period_end"],
            "punchEventCount": row["punch_event_count"],
            "startedAt": row["started_at"],
            "finishedAt": row["finished_at"],
            "rolledBackAt": row["rolled_back_at"],
            "errorMessage": row["error_message"],
            "coveredDays": row["covered_days"],
        }
        for row in rows
    ]


def import_run_detail(conn: sqlite3.Connection, run_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM import_runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    days = conn.execute(
        "SELECT work_date, coverage_status, raw_punch_count FROM import_run_days "
        " WHERE import_run_id = ? ORDER BY work_date",
        (run_id,),
    ).fetchall()
    findings: list[dict] = []
    if row["findings_json"]:
        try:
            findings = json.loads(row["findings_json"]).get("findings", [])
        except ValueError:  # pragma: no cover - defensive
            findings = []
    return {
        "id": row["id"],
        "sourceFilename": row["source_filename"],
        "status": row["status"],
        "periodStart": row["period_start"],
        "periodEnd": row["period_end"],
        "punchEventCount": row["punch_event_count"],
        "startedAt": row["started_at"],
        "finishedAt": row["finished_at"],
        "rolledBackAt": row["rolled_back_at"],
        "errorMessage": row["error_message"],
        "coveredDays": len(days),
        "sourceSha256": row["source_sha256"],
        "findings": findings,
        # Coverage facts, kept apart from any attendance verdict: a
        # reported_zero day is what the file said, not an absence.
        "days": [
            {
                "workDate": day["work_date"],
                "coverage": day["coverage_status"],
                "punches": day["raw_punch_count"],
            }
            for day in days
        ],
    }


def stored_preview(conn: sqlite3.Connection, run_id: int) -> dict | None:
    """The preview snapshot as the operator would have seen it.

    Returns None when the run has none — a run that failed to parse, or one
    already applied. Applying never trusts this: it re-reads the preserved file
    and recomputes against the current slot mapping.
    """
    row = conn.execute(
        "SELECT preview_json FROM import_runs WHERE id = ?", (run_id,)
    ).fetchone()
    if row is None or not row["preview_json"]:
        return None
    return json.loads(row["preview_json"])


def preserved_source(conn: sqlite3.Connection, run_id: int) -> dict | None:
    """Where the untouched original is kept.

    The path, not the bytes: the file stays on the work PC's disk and is never
    served to a caller.
    """
    row = conn.execute(
        "SELECT stored_source_path, source_filename, source_sha256 "
        "  FROM import_runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    stored = Path(row["stored_source_path"] or "")
    return {
        "sourceFilename": row["source_filename"],
        "storedPath": str(stored),
        "exists": stored.is_file(),
        "sha256": row["source_sha256"],
    }


def pending_imports(conn: sqlite3.Connection) -> list[dict]:
    """Previewed imports waiting for somebody to confirm or discard them."""
    rows = conn.execute(
        """
        SELECT id, source_filename, period_start, period_end, started_at,
               discovered_by, preview_json
          FROM import_runs
         WHERE status = 'previewed' AND source_kind = 'fingerprint_xls'
         ORDER BY id DESC
        """
    ).fetchall()
    out = []
    for row in rows:
        new_punches = None
        if row["preview_json"]:
            try:
                new_punches = json.loads(row["preview_json"]).get("newPunches")
            except ValueError:  # pragma: no cover - defensive
                new_punches = None
        out.append({
            "importRunId": row["id"],
            "sourceFilename": row["source_filename"],
            "periodStart": row["period_start"],
            "periodEnd": row["period_end"],
            "startedAt": row["started_at"],
            "discoveredBy": row["discovered_by"],
            "newPunches": new_punches,
        })
    return out


def last_applied_import(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT id, source_filename, period_start, period_end, finished_at, punch_event_count "
        "  FROM import_runs WHERE status = 'applied' AND source_kind = 'fingerprint_xls' "
        " ORDER BY COALESCE(finished_at, updated_at) DESC, id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None
