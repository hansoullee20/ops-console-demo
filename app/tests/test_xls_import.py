"""Fingerprint XLS import: parsing, preview, apply, rollback.

The fixtures are built at run time from fictional data by
`app/tests/fixtures/terminal_xls.py`, in the exact layout a real terminal
export uses. The real export contains employee names and is never committed.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from app import db
from app.rules import punch_review
from app.seed.demo_dataset import seed_demo_database
from app.services import xls_import, xls_pipeline
from app.services.xls_import import XlsImportError, dedupe_key, parse_workbook
from app.tests.fixtures.terminal_xls import SlotSpec, build_export, realistic_month


@pytest.fixture
def export(tmp_path: Path) -> Path:
    return build_export(tmp_path / "2026-07.XLS", slots=realistic_month())


@pytest.fixture
def seeded(migrated_db: Path) -> Path:
    seed_demo_database(migrated_db)
    return migrated_db


def _preview(export: Path, seeded: Path, tmp_path: Path, **kwargs):
    return xls_pipeline.preview_import(
        export, db_path=seeded, uploads_dir=tmp_path / "uploads", **kwargs
    )


def _apply(preview, seeded: Path, tmp_path: Path):
    return xls_pipeline.apply_import(
        preview.import_run_id, preview.confirmation_token,
        db_path=seeded, backups_dir=tmp_path / "backups",
    )


# ---------------------------------------------------------------------------
# parsing
# ---------------------------------------------------------------------------
def test_parses_period_slots_and_punches(export: Path):
    parsed = parse_workbook(export)
    assert parsed.period_start == "2026-07-01"
    assert parsed.period_end == "2026-07-31"
    assert len(parsed.slots) == 8
    assert len(parsed.active_slots) == 6
    assert parsed.warnings == []


def test_every_punch_count_from_zero_to_five_is_representable(export: Path):
    parsed = parse_workbook(export)
    per_day = Counter((p.slot_code, p.work_date) for p in parsed.punches)
    assert sorted(Counter(per_day.values())) == [1, 2, 3, 4, 5]
    assert any(s.punch_count == 0 for s in parsed.slots)


def test_exact_repeated_timestamps_are_all_preserved(export: Path):
    """§2.4: a punch is never dropped for looking like a duplicate. A real
    export contained the same timestamp three times in one day."""
    parsed = parse_workbook(export)
    day = [p for p in parsed.punches if p.slot_code == "004" and p.work_date == "2026-07-01"]
    assert [p.punch_time for p in day] == ["06:40", "06:40", "06:40", "16:11"]
    assert [p.occurrence_index for p in day] == [0, 1, 2, 3]


def test_dedupe_key_includes_the_sequence(export: Path):
    """Without the sequence, repeated timestamps collide on the unique index
    and raw events are silently refused. In one real month that would have
    lost 12 punches."""
    parsed = parse_workbook(export)
    keys = [dedupe_key("default", p) for p in parsed.punches]
    assert len(set(keys)) == len(keys)

    without_ordinal = {k.rsplit("|", 1)[0] for k in keys}
    assert len(without_ordinal) < len(keys), "fixture must contain repeated timestamps"


def test_terminal_emits_no_punch_type_markers(export: Path):
    """The real export has no 출/외/퇴/복 per punch, so imported events must not
    guess one."""
    parsed = parse_workbook(export)
    assert all(not any(c in p.raw_cell for c in "외복") for p in parsed.punches)


def test_unreadable_workbook_is_refused(tmp_path: Path):
    junk = tmp_path / "not.xls"
    junk.write_bytes(b"this is not a workbook")
    with pytest.raises(XlsImportError):
        parse_workbook(junk)


def test_workbook_without_the_raw_sheet_is_refused(tmp_path: Path):
    import xlwt

    book = xlwt.Workbook()
    book.add_sheet("something else").write(0, 0, "x")
    path = tmp_path / "wrong.xls"
    book.save(str(path))
    with pytest.raises(XlsImportError, match="근태기록"):
        parse_workbook(path)


# ---------------------------------------------------------------------------
# review rules
# ---------------------------------------------------------------------------
def test_repeated_punch_threshold_is_configurable():
    times = ["07:26", "07:36", "16:00"]
    assert punch_review.repeated_punch_indexes(times, 20) == {1}
    assert punch_review.repeated_punch_indexes(times, 5) == set()
    assert punch_review.repeated_punch_indexes(times, 600) == {1, 2}


def test_single_punch_day_is_incomplete_not_absent():
    review = punch_review.review_day(["07:30"])
    assert review["incomplete"] is True
    assert review["punch_count"] == 1


def test_whole_site_zero_punch_dates_are_listed():
    dates = ["2026-07-01", "2026-07-02", "2026-07-03"]
    assert punch_review.whole_site_zero_punch_dates(dates, {"2026-07-02"}) == [
        "2026-07-01", "2026-07-03",
    ]


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------
def test_preview_writes_no_punches_and_preserves_the_original(export, seeded, tmp_path):
    with db.connection(seeded) as conn:
        before = conn.execute("SELECT COUNT(*) FROM punch_events").fetchone()[0]

    preview = _preview(export, seeded, tmp_path)

    with db.connection(seeded) as conn:
        assert conn.execute("SELECT COUNT(*) FROM punch_events").fetchone()[0] == before
        run = conn.execute(
            "SELECT status, source_sha256, stored_source_path FROM import_runs WHERE id = ?",
            (preview.import_run_id,),
        ).fetchone()
    assert run["status"] == "previewed"
    assert run["source_sha256"] and Path(run["stored_source_path"]).exists()
    assert preview.new_punches == 29
    assert preview.as_dict()["canApply"] is True


def test_preview_reports_every_finding_class(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    codes = {f["code"] for f in preview.findings}
    assert {"unused_slot", "repeated_punch_candidate", "duplicate_timestamp",
            "incomplete_day", "whole_site_zero_punch"} <= codes
    assert preview.zero_punch_dates, "quiet days must be surfaced, not ignored"


def test_unmapped_slot_is_flagged_and_its_punches_still_kept(seeded, tmp_path):
    export = build_export(
        tmp_path / "unmapped.XLS",
        slots=[SlotSpec("099", "미등록", {1: ["07:20", "16:00"]})],
    )
    preview = _preview(export, seeded, tmp_path)
    assert any(f["code"] == "unmapped_slot" for f in preview.findings)
    assert preview.new_punches == 2

    _apply(preview, seeded, tmp_path)
    with db.connection(seeded) as conn:
        rows = conn.execute(
            "SELECT employee_id, review_flag FROM punch_events WHERE terminal_slot_code = '099'"
        ).fetchall()
    assert len(rows) == 2, "punches from an unmapped slot must still be preserved"
    assert all(r["employee_id"] is None and r["review_flag"] == "unmapped_slot" for r in rows)


def test_punch_before_hire_date_is_flagged(seeded, tmp_path):
    with db.transaction(seeded) as conn:
        conn.execute("UPDATE employees SET hire_date = '2026-08-01' WHERE employee_code = 'E001'")
    export = build_export(
        tmp_path / "early.XLS", slots=[SlotSpec("001", "가상", {1: ["07:20", "16:00"]})]
    )
    preview = _preview(export, seeded, tmp_path)
    assert any(f["code"] == "before_hire_date" for f in preview.findings)


def test_inactive_employee_is_flagged(seeded, tmp_path):
    with db.transaction(seeded) as conn:
        conn.execute("UPDATE employees SET status = 'suspended' WHERE employee_code = 'E001'")
    export = build_export(
        tmp_path / "inactive.XLS", slots=[SlotSpec("001", "가상", {1: ["07:20", "16:00"]})]
    )
    preview = _preview(export, seeded, tmp_path)
    assert any(f["code"] == "inactive_employee" for f in preview.findings)


def test_approved_leave_with_punches_is_flagged_and_neither_is_changed(seeded, tmp_path):
    with db.transaction(seeded) as conn:
        conn.execute(
            """
            INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date,
                                        leave_year, status)
            VALUES ((SELECT id FROM employees WHERE employee_code = 'E001'),
                    'annual', '2026-07-01', '2026-07-01', 2026, 'approved')
            """
        )
    export = build_export(
        tmp_path / "conflict.XLS", slots=[SlotSpec("001", "가상", {1: ["07:20", "16:00"]})]
    )
    preview = _preview(export, seeded, tmp_path)
    assert any(f["code"] == "leave_conflict" for f in preview.findings)

    _apply(preview, seeded, tmp_path)
    with db.connection(seeded) as conn:
        leave = conn.execute(
            "SELECT start_date, end_date, status FROM leave_requests "
            " WHERE start_date = '2026-07-01'"
        ).fetchone()
    assert (leave["start_date"], leave["end_date"], leave["status"]) == (
        "2026-07-01", "2026-07-01", "approved",
    ), "neither the leave nor the punches may be silently adjusted"


# ---------------------------------------------------------------------------
# apply
# ---------------------------------------------------------------------------
def test_apply_requires_the_confirmation_token(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    with pytest.raises(xls_pipeline.ImportError_, match="confirmation token"):
        xls_pipeline.apply_import(
            preview.import_run_id, "wrong-token",
            db_path=seeded, backups_dir=tmp_path / "backups",
        )
    with db.connection(seeded) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM punch_events WHERE import_run_id IS NOT NULL"
        ).fetchone()[0] == 0


def test_apply_snapshots_records_and_derives(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    result = _apply(preview, seeded, tmp_path)

    assert result["inserted"] == 29
    assert Path(result["snapshotPath"]).exists()
    assert result["attendanceRows"] > 0

    with db.connection(seeded) as conn:
        run = conn.execute(
            "SELECT status, punch_event_count, finished_at, snapshot_path FROM import_runs WHERE id = ?",
            (preview.import_run_id,),
        ).fetchone()
        assert run["status"] == "applied"
        assert run["punch_event_count"] == 29
        assert run["finished_at"] and run["snapshot_path"]

        audit = conn.execute(
            "SELECT action, confirmation_token FROM audit_log WHERE action = 'import.apply'"
        ).fetchone()
        assert audit["confirmation_token"] == preview.confirmation_token

        # every imported punch carries punch_type 'unknown': the terminal gives none
        types = {r[0] for r in conn.execute(
            "SELECT DISTINCT punch_type FROM punch_events WHERE import_run_id IS NOT NULL"
        )}
        assert types == {"unknown"}


def test_reimport_is_idempotent(export, seeded, tmp_path):
    first = _preview(export, seeded, tmp_path)
    _apply(first, seeded, tmp_path)
    with db.connection(seeded) as conn:
        after_first = conn.execute("SELECT COUNT(*) FROM punch_events").fetchone()[0]

    second = _preview(export, seeded, tmp_path)
    assert second.already_imported == 29 and second.new_punches == 0
    result = _apply(second, seeded, tmp_path)
    assert result["inserted"] == 0 and result["alreadyPresent"] == 29

    with db.connection(seeded) as conn:
        assert conn.execute("SELECT COUNT(*) FROM punch_events").fetchone()[0] == after_first


def test_repeated_punch_candidates_are_flagged_not_merged(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    _apply(preview, seeded, tmp_path)
    with db.connection(seeded) as conn:
        flagged = conn.execute(
            "SELECT COUNT(*) FROM punch_events "
            " WHERE import_run_id IS NOT NULL AND review_flag = 'repeated_punch_candidate'"
        ).fetchone()[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM punch_events WHERE import_run_id IS NOT NULL"
        ).fetchone()[0]
    assert flagged > 0
    assert total == 29, "flagging must not remove or merge any raw event"


def test_import_never_marks_a_day_absent(export, seeded, tmp_path):
    """The terminal's own card sheets call every unused slot 결근 on all 31
    days. None of that may reach the database."""
    preview = _preview(export, seeded, tmp_path)
    _apply(preview, seeded, tmp_path)
    with db.connection(seeded) as conn:
        absent = conn.execute(
            "SELECT COUNT(*) FROM attendance_days WHERE status = 'absent' AND source = 'fingerprint'"
        ).fetchone()[0]
    assert absent == 0


def test_single_punch_day_is_derived_as_unknown(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    _apply(preview, seeded, tmp_path)
    with db.connection(seeded) as conn:
        row = conn.execute(
            """
            SELECT a.status, a.review_flag FROM attendance_days a
              JOIN terminal_slots t ON t.employee_id = a.employee_id
             WHERE t.slot_code = '005' AND a.work_date = '2026-07-01'
            """
        ).fetchone()
    assert row["status"] == "unknown"
    assert row["review_flag"] == "incomplete_day"


def test_confirmed_attendance_is_never_overwritten_by_an_import(export, seeded, tmp_path):
    with db.transaction(seeded) as conn:
        employee_id = conn.execute(
            "SELECT employee_id FROM terminal_slots WHERE slot_code = '001'"
        ).fetchone()[0]
        conn.execute(
            """
            INSERT INTO attendance_days (employee_id, work_date, status, source,
                                         confirmed_at, confirmed_by, review_note)
            VALUES (?, '2026-07-01', 'leave', 'manual', '2026-07-02T00:00:00Z', 'admin', '수기 확정')
            """,
            (employee_id,),
        )
    preview = _preview(export, seeded, tmp_path)
    _apply(preview, seeded, tmp_path)

    with db.connection(seeded) as conn:
        row = conn.execute(
            "SELECT status, review_note FROM attendance_days "
            " WHERE employee_id = ? AND work_date = '2026-07-01'",
            (employee_id,),
        ).fetchone()
    assert row["status"] == "leave"
    assert row["review_note"] == "수기 확정"


# ---------------------------------------------------------------------------
# rollback
# ---------------------------------------------------------------------------
def test_rollback_marks_and_never_deletes_raw_punches(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    _apply(preview, seeded, tmp_path)

    result = xls_pipeline.rollback_import(preview.import_run_id, "잘못된 파일", db_path=seeded)

    assert result["punchesDeleted"] == 0
    assert result["punchesMarkedRolledBack"] == 29
    with db.connection(seeded) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM punch_events WHERE import_run_id = ?",
            (preview.import_run_id,),
        ).fetchone()[0]
        marked = conn.execute(
            "SELECT COUNT(*) FROM punch_events "
            " WHERE import_run_id = ? AND rolled_back_at IS NOT NULL",
            (preview.import_run_id,),
        ).fetchone()[0]
        run_status = conn.execute(
            "SELECT status FROM import_runs WHERE id = ?", (preview.import_run_id,)
        ).fetchone()[0]
    assert remaining == 29 and marked == 29
    assert run_status == "rolled_back"


def test_rollback_resets_derived_attendance_without_replacing_the_row(export, seeded, tmp_path):
    """Attendance backed only by rolled-back punches must stop claiming
    'normal' — while keeping its identity (finding N1)."""
    preview = _preview(export, seeded, tmp_path)
    _apply(preview, seeded, tmp_path)
    with db.connection(seeded) as conn:
        before = dict(conn.execute(
            "SELECT a.id, a.created_at, a.revision, a.status FROM attendance_days a "
            "  JOIN terminal_slots t ON t.employee_id = a.employee_id "
            " WHERE t.slot_code = '001' AND a.work_date = '2026-07-01'"
        ).fetchone())
    assert before["status"] == "normal"

    xls_pipeline.rollback_import(preview.import_run_id, "테스트", db_path=seeded)

    with db.connection(seeded) as conn:
        after = dict(conn.execute(
            "SELECT id, created_at, revision, status, review_flag FROM attendance_days WHERE id = ?",
            (before["id"],),
        ).fetchone())
    assert after["status"] == "unknown"
    assert after["review_flag"] == "import_rolled_back"
    assert after["id"] == before["id"]
    assert after["created_at"] == before["created_at"]
    assert after["revision"] == before["revision"] + 1


def test_rollback_requires_a_reason_and_an_applied_run(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    with pytest.raises(xls_pipeline.ImportError_, match="only an applied run"):
        xls_pipeline.rollback_import(preview.import_run_id, "아직 적용 안 됨", db_path=seeded)

    _apply(preview, seeded, tmp_path)
    with pytest.raises(xls_pipeline.ImportError_, match="reason"):
        xls_pipeline.rollback_import(preview.import_run_id, "   ", db_path=seeded)


def test_reapplying_after_rollback_restores_the_data(export, seeded, tmp_path):
    first = _preview(export, seeded, tmp_path)
    _apply(first, seeded, tmp_path)
    xls_pipeline.rollback_import(first.import_run_id, "재적용 테스트", db_path=seeded)

    second = _preview(export, seeded, tmp_path)
    result = _apply(second, seeded, tmp_path)

    # the rolled-back events already occupy their dedupe keys, so re-applying
    # reactivates them rather than inserting duplicates
    assert result["inserted"] == 0
    assert result["reactivated"] == 29

    with db.connection(seeded) as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM punch_events WHERE import_run_id IS NOT NULL"
        ).fetchone()[0]
        still_rolled_back = conn.execute(
            "SELECT COUNT(*) FROM punch_events "
            " WHERE import_run_id IS NOT NULL AND rolled_back_at IS NOT NULL"
        ).fetchone()[0]
        restored = conn.execute(
            "SELECT a.status FROM attendance_days a JOIN terminal_slots t "
            "    ON t.employee_id = a.employee_id "
            " WHERE t.slot_code = '001' AND a.work_date = '2026-07-01'"
        ).fetchone()[0]
    assert total == 29, "no raw event was duplicated or lost across the cycle"
    assert still_rolled_back == 0
    assert restored == "normal", "derived attendance must come back with the data"


def test_last_applied_import_is_reported(export, seeded, tmp_path):
    with db.connection(seeded) as conn:
        assert xls_pipeline.last_applied_import(conn) is None

    preview = _preview(export, seeded, tmp_path)
    _apply(preview, seeded, tmp_path)

    with db.connection(seeded) as conn:
        last = xls_pipeline.last_applied_import(conn)
    assert last and last["period_start"] == "2026-07-01"
    assert last["punch_event_count"] == 29


# ---------------------------------------------------------------------------
# provenance: a punch_event is one occurrence, traceable to its source cell
# ---------------------------------------------------------------------------
def test_punch_carries_provenance_separate_from_the_occurrence_ordinal(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    _apply(preview, seeded, tmp_path)

    with db.connection(seeded) as conn:
        rows = conn.execute(
            """
            SELECT punch_at, source_sheet, source_row_no, source_column, source_cell,
                   occurrence_index
              FROM punch_events
             WHERE terminal_slot_code = '004' AND work_date = '2026-07-01'
             ORDER BY occurrence_index
            """
        ).fetchall()

    assert len(rows) == 4
    assert [r["occurrence_index"] for r in rows] == [0, 1, 2, 3]
    # all four came out of one cell, so provenance is shared while the ordinal differs
    assert len({r["source_cell"] for r in rows}) == 1
    assert all(r["source_sheet"] == "근태기록" for r in rows)
    assert all(r["source_row_no"] is not None and r["source_column"] is not None for r in rows)
    assert rows[0]["source_cell"][0].isalpha() and rows[0]["source_cell"][1:].isdigit()


def test_provenance_columns_are_immutable_too(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    _apply(preview, seeded, tmp_path)
    with db.connection(seeded) as conn:
        punch_id = conn.execute(
            "SELECT id FROM punch_events WHERE import_run_id IS NOT NULL LIMIT 1"
        ).fetchone()[0]
        for column, value in (
            ("source_sheet", "다른시트"), ("source_column", 99),
            ("source_cell", "ZZ99"), ("occurrence_index", 7),
        ):
            with pytest.raises(Exception, match="immutable"):
                conn.execute(
                    f"UPDATE punch_events SET {column} = ? WHERE id = ?", (value, punch_id)
                )
            conn.rollback()


def test_dedupe_key_shape_is_the_agreed_one(export):
    parsed = parse_workbook(export)
    key = dedupe_key("default", parsed.punches[0])
    terminal, slot, work_date, time, punch_type, ordinal = key.split("|")
    assert terminal == "default"
    assert punch_type == "unknown"
    assert ordinal.isdigit()
    # the cell address is provenance, not identity: a re-exported file with
    # shifted rows must not look like new data
    assert parsed.punches[0].source_cell not in key


# ---------------------------------------------------------------------------
# import_run lifecycle and confirmation binding
# ---------------------------------------------------------------------------
def test_import_run_exists_from_upload_even_if_parsing_fails(seeded, tmp_path):
    junk = tmp_path / "broken.XLS"
    junk.write_bytes(b"not a workbook at all")

    with pytest.raises(XlsImportError):
        _preview(junk, seeded, tmp_path)

    with db.connection(seeded) as conn:
        run = conn.execute(
            "SELECT status, error_message, stored_source_path FROM import_runs "
            " ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert run["status"] == "failed"
    assert run["error_message"]
    assert Path(run["stored_source_path"]).exists(), "the original is preserved even on failure"


def test_confirmation_is_invalidated_when_the_mapping_changes(export, seeded, tmp_path):
    """The operator reviewed one mapping; applying must not commit another."""
    preview = _preview(export, seeded, tmp_path)

    with db.transaction(seeded) as conn:
        conn.execute("UPDATE terminal_slots SET employee_id = NULL WHERE slot_code = '001'")

    with pytest.raises(xls_pipeline.ImportError_, match="changed after this preview"):
        _apply(preview, seeded, tmp_path)

    with db.connection(seeded) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM punch_events WHERE import_run_id IS NOT NULL"
        ).fetchone()[0] == 0


def test_confirmation_is_invalidated_when_the_stored_file_changes(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    Path(preview.stored_source_path).write_bytes(b"tampered")

    with pytest.raises(xls_pipeline.ImportError_, match="changed after the preview"):
        _apply(preview, seeded, tmp_path)


def test_preview_fingerprint_is_recorded_on_the_run(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    with db.connection(seeded) as conn:
        run = conn.execute(
            "SELECT status, preview_fingerprint, confirmation_token FROM import_runs WHERE id = ?",
            (preview.import_run_id,),
        ).fetchone()
    assert run["status"] == "previewed"
    assert run["preview_fingerprint"] == preview.preview_fingerprint
    assert run["confirmation_token"] == preview.confirmation_token


# ---------------------------------------------------------------------------
# coverage: "the file said nothing happened" vs "never imported"
# ---------------------------------------------------------------------------
def test_coverage_distinguishes_reported_zero_from_never_imported(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    _apply(preview, seeded, tmp_path)

    with db.connection(seeded) as conn:
        rows = {
            r["work_date"]: (r["coverage_status"], r["raw_punch_count"])
            for r in conn.execute(
                "SELECT work_date, coverage_status, raw_punch_count FROM import_run_days "
                " WHERE import_run_id = ?",
                (preview.import_run_id,),
            )
        }

    # the fixture only has punches on 1 and 2 July; the file still covered the month
    assert len(rows) == 31
    assert rows["2026-07-01"][0] == "has_punches" and rows["2026-07-01"][1] > 0
    assert rows["2026-07-05"] == ("reported_zero", 0)

    # a month the file never mentioned has no coverage row at all
    assert "2026-08-01" not in rows


def test_reported_zero_is_never_turned_into_absence(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    _apply(preview, seeded, tmp_path)
    with db.connection(seeded) as conn:
        quiet_days = [
            r["work_date"] for r in conn.execute(
                "SELECT work_date FROM import_run_days WHERE coverage_status = 'reported_zero'"
            )
        ]
        assert quiet_days
        marks = conn.execute(
            "SELECT COUNT(*) FROM attendance_days "
            f" WHERE work_date IN ({','.join('?' * len(quiet_days))}) AND status = 'absent'",
            quiet_days,
        ).fetchone()[0]
    assert marks == 0


# ---------------------------------------------------------------------------
# rollback must not undo a human's work
# ---------------------------------------------------------------------------
def test_rollback_does_not_overwrite_a_manual_correction_made_after_the_import(
    export, seeded, tmp_path
):
    from app.services.attendance import correct_attendance

    preview = _preview(export, seeded, tmp_path)
    _apply(preview, seeded, tmp_path)

    with db.connection(seeded) as conn:
        employee_id = conn.execute(
            "SELECT employee_id FROM terminal_slots WHERE slot_code = '001'"
        ).fetchone()[0]

    conn = db.connect(seeded)
    try:
        correct_attendance(
            conn, employee_id=employee_id, work_date="2026-07-01",
            changes={"status": "leave", "review_note": "관리자 확인: 연차였음"},
            actor_id="admin", reason="수기 정정",
        )
        conn.commit()
    finally:
        conn.close()

    result = xls_pipeline.rollback_import(preview.import_run_id, "잘못된 파일", db_path=seeded)

    assert any(f["code"] == "rollback_conflict" for f in result["conflicts"])
    with db.connection(seeded) as conn:
        row = conn.execute(
            "SELECT status, review_note FROM attendance_days "
            " WHERE employee_id = ? AND work_date = '2026-07-01'",
            (employee_id,),
        ).fetchone()
    assert row["status"] == "leave", "the rollback undid a human's correction"
    assert row["review_note"] == "관리자 확인: 연차였음"


def test_rollback_skips_confirmed_rows_and_reports_them(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    _apply(preview, seeded, tmp_path)

    with db.transaction(seeded) as conn:
        employee_id = conn.execute(
            "SELECT employee_id FROM terminal_slots WHERE slot_code = '002'"
        ).fetchone()[0]
        conn.execute(
            "UPDATE attendance_days SET confirmed_at = ?, confirmed_by = 'admin' "
            " WHERE employee_id = ? AND work_date = '2026-07-01'",
            ("2026-07-05T00:00:00Z", employee_id),
        )

    result = xls_pipeline.rollback_import(preview.import_run_id, "테스트", db_path=seeded)
    assert any(f["code"] == "rollback_conflict" for f in result["conflicts"])

    with db.connection(seeded) as conn:
        status = conn.execute(
            "SELECT status FROM attendance_days WHERE employee_id = ? AND work_date = '2026-07-01'",
            (employee_id,),
        ).fetchone()[0]
    assert status == "normal", "a confirmed row must be left exactly as it was"


def test_attendance_records_which_import_derived_it(export, seeded, tmp_path):
    preview = _preview(export, seeded, tmp_path)
    _apply(preview, seeded, tmp_path)
    with db.connection(seeded) as conn:
        runs = {
            r[0] for r in conn.execute(
                "SELECT DISTINCT last_import_run_id FROM attendance_days "
                " WHERE source = 'fingerprint'"
            )
        }
    assert runs == {preview.import_run_id}
