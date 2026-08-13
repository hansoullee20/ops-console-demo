from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db, migrate
from app.main import create_app
from app.services import attendance, month_close, operational_safety


def _operational(migrated_db):
    conn = db.connect(migrated_db)
    conn.execute("UPDATE app_meta SET value='operational' WHERE key='data_context'")
    conn.commit()
    return conn


def _employee(conn, code="CLOSE1"):
    return conn.execute(
        "INSERT INTO employees(employee_code,name,hire_date) VALUES(?,?,?)",
        (code, f"Fictional {code}", "2025-01-01"),
    ).lastrowid


def _exception(conn, *, code="manual_attendance_review", work_date="2026-08-10",
               scope="employee", employee_id=None, evidence=()):
    return operational_safety.ensure_exception(
        conn, code=code, severity="review", scope=scope, employee_id=employee_id,
        work_date=work_date, summary="Fictional review", evidence=evidence,
    )


def test_closed_month_guards_attendance_and_all_exception_transitions(migrated_db):
    conn = _operational(migrated_db)
    month_close.close_month(conn, "2026-08", "operator", "Fictional close")
    employee_id = _employee(conn)
    conn.execute(
        "INSERT INTO attendance_days(employee_id,work_date,status,source) VALUES(?,?,'unknown','manual')",
        (employee_id, "2026-08-10"),
    )
    exceptions = [_exception(conn, employee_id=employee_id, code=f"closed_guard_{state}")
                  for state in ("ack", "resolve", "waive")]
    with pytest.raises(attendance.AttendanceCorrectionError):
        attendance.correct_attendance(
            conn, employee_id=employee_id, work_date="2026-08-10",
            changes={"review_note": "blocked"}, actor_id="operator", reason="test",
        )
    for item, transition in zip(exceptions, ("acknowledged", "resolved", "waived")):
        with pytest.raises(operational_safety.SafetyError):
            operational_safety.transition_exception(conn, item["id"], transition, "blocked")
    month_close.reopen(conn, "2026-08", "operator", "Fictional correction")
    attendance.correct_attendance(
        conn, employee_id=employee_id, work_date="2026-08-10",
        changes={"review_note": "allowed"}, actor_id="operator", reason="test",
    )
    for item, transition in zip(exceptions, ("acknowledged", "resolved", "waived")):
        assert operational_safety.transition_exception(conn, item["id"], transition, "allowed")["status"] == transition
    conn.close()


def test_close_metadata_trigger_and_hash_integrity_gate(migrated_db):
    conn = _operational(migrated_db)
    close = month_close.close_month(conn, "2026-08", "operator", "Fictional close")
    conn.commit()
    with pytest.raises(Exception):
        conn.execute("UPDATE month_closes SET close_note='tampered' WHERE id=?", (close["id"],))
    conn.rollback()
    reopened = month_close.reopen(conn, "2026-08", "operator", "Fictional reopen")
    assert reopened["status"] == "reopened"
    conn.execute(
        "INSERT INTO month_closes(month_key,revision,status,reconciliation_version,policy_version,"
        "closed_at,closed_by,close_note,snapshot_hash) VALUES('2026-09',1,'closed','2','2',"
        "'2026-10-01T00:00:00Z','operator','bad hash',?)",
        ("0" * 64,),
    )
    conn.commit()
    with pytest.raises(month_close.MonthCloseIntegrityError):
        month_close.snapshot(conn, "2026-09")
    with pytest.raises(month_close.MonthCloseIntegrityError):
        month_close.export_xls(conn, "2026-09")
    conn.close()


def test_null_date_source_mapping_replacement_attribution_and_frozen_links(migrated_db):
    conn = _operational(migrated_db)
    employee_id = _employee(conn)
    operational_safety.create_schedule(
        conn, employee_id=employee_id, effective_from="2026-08-01",
        effective_to="2026-08-31", weekday_mask="",
    )
    import_id = conn.execute(
        "INSERT INTO import_runs(source_filename,status,period_start,period_end) "
        "VALUES('fictional.xls','applied','2026-08-01','2026-08-31')"
    ).lastrowid
    mapping_id = conn.execute(
        "INSERT INTO terminal_slots(slot_code,employee_id,effective_from,status) VALUES('901',?,'2026-08-01','mapped')",
        (employee_id,),
    ).lastrowid
    replacement_id = conn.execute(
        "INSERT INTO replacement_assignments(work_date,start_date,end_date,substitute_employee_id,status) "
        "VALUES('2026-08-12','2026-08-12','2026-08-13',?,'assigned')",
        (employee_id,),
    ).lastrowid
    specs = [
        ("source_null", "source", [{"evidence_type": "fingerprint_xls", "entity_type": "import_run", "import_run_id": import_id}]),
        ("mapping_null", "mapping", [{"evidence_type": "mapping", "entity_type": "terminal_slot", "entity_id": mapping_id}]),
        ("replacement_null", "replacement", [{"evidence_type": "replacement", "entity_type": "replacement_assignment", "entity_id": replacement_id}]),
    ]
    ids = []
    for code, scope, evidence in specs:
        item = _exception(conn, code=code, scope=scope, employee_id=None, work_date=None, evidence=evidence)
        ids.append(item["id"])
    reconciliation = month_close.reconcile(conn, "2026-08")
    assert {item["exceptionIds"][0] for item in reconciliation["blockingItems"]} >= set(ids)
    active_ids = [row[0] for row in conn.execute(
        "SELECT id FROM operational_exceptions WHERE status IN ('open','acknowledged')"
    )]
    for exception_id in active_ids:
        operational_safety.transition_exception(conn, exception_id, "waived", "Fictional waiver")
    close = month_close.close_month(conn, "2026-08", "operator", "Fictional close")
    frozen = month_close.snapshot(conn, "2026-08")
    assert {item["exception_id"] for item in frozen["exceptions"]} >= set(ids)
    original_events = list(frozen["exceptionEventIds"])
    original_evidence = list(frozen["exceptionEvidenceLinkIds"])
    conn.execute(
        "INSERT INTO exception_events(exception_id,event_type,note,actor) VALUES(?,'later_note','later','operator')",
        (ids[0],),
    )
    conn.execute(
        "INSERT INTO exception_evidence_links(exception_id,evidence_type,entity_type,reference_text,evidence_key,created_by) "
        "VALUES(?,'manual_statement','note','later','later-evidence','operator')",
        (ids[0],),
    )
    frozen_again = month_close.snapshot(conn, "2026-08", close_id=close["id"])
    assert frozen_again["exceptionEventIds"] == original_events
    assert frozen_again["exceptionEvidenceLinkIds"] == original_evidence
    conn.close()


def test_revision_lookup_lineage_and_export_modes_http(migrated_db, monkeypatch):
    conn = _operational(migrated_db)
    first = month_close.close_month(conn, "2026-08", "operator", "Revision one")
    month_close.reopen(conn, "2026-08", "operator", "Fictional reopen")
    conn.commit(); conn.close()
    monkeypatch.setattr(config, "DB_PATH", migrated_db)
    client = TestClient(create_app())
    assert client.get("/api/v1/month-close/2026-08/export.xlsx").status_code == 409
    assert client.get("/api/v1/month-close/2026-08/export.xlsx?revision=1").status_code == 200
    second_response = client.post(
        "/api/v1/month-close/2026-08/close",
        json={"actor": "operator", "reason": "Revision two"},
    )
    assert second_response.status_code == 200
    second = second_response.json()
    assert second["revision"] == 2 and second["supersedes_close_id"] == first["id"]
    revisions = client.get("/api/v1/month-close/2026-08/revisions").json()["revisions"]
    assert [row["revision"] for row in revisions] == [1, 2]
    assert client.get("/api/v1/month-close/2026-08/snapshot?revision=1").json()["close"]["id"] == first["id"]
    assert client.get("/api/v1/month-close/2026-08/snapshot?revision=2").json()["close"]["id"] == second["id"]
    assert client.get("/api/v1/month-close/2026-08/export.xlsx?revision=1").status_code == 200
    assert client.get("/api/v1/month-close/2026-08/export.xlsx?revision=2").status_code == 200
    assert client.get("/api/v1/month-close/2026-08/export.xlsx").status_code == 200


def test_snapshot_source_link_validation(migrated_db):
    conn = _operational(migrated_db)
    canonical = month_close._canonical("2026-08", 1, [], [], [{"type": "unknown", "id": 999}], [], [], None)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    close_id = conn.execute(
        "INSERT INTO month_closes(month_key,revision,status,reconciliation_version,policy_version,"
        "closed_at,closed_by,close_note,snapshot_hash) VALUES('2026-08',1,'closed','2','2',"
        "'2026-09-01T00:00:00Z','operator','invalid source',?)", (digest,)
    ).lastrowid
    conn.execute(
        "INSERT INTO month_close_source_links(close_id,source_type,source_id) VALUES(?, 'unknown', 999)",
        (close_id,),
    )
    with pytest.raises(month_close.MonthCloseIntegrityError):
        month_close.snapshot(conn, "2026-08")
    conn.close()


def test_0008_to_0009_to_0010_to_0011_upgrade_backfills_lineage_and_is_idempotent(tmp_path):
    old = tmp_path / "through-v9"; old.mkdir()
    for source in config.MIGRATIONS_DIR.glob("*.sql"):
        if source.name.startswith(("0010_", "0011_")):
            continue
        (old / source.name).write_bytes(source.read_bytes())
    database = tmp_path / "phase45-v9.db"; backups = tmp_path / "backups"
    assert migrate.run_migrations(database, migrations_dir=old, backups_dir=backups).schema_version == 9
    conn = db.connect(database)
    empty_v1 = lambda revision: hashlib.sha256(
        month_close._canonical("2026-08", revision, [], [], [], version="1").encode()
    ).hexdigest()
    first = conn.execute(
        "INSERT INTO month_closes(month_key,revision,status,reconciliation_version,policy_version,"
        "closed_at,closed_by,close_note,snapshot_hash,reopened_at,reopened_by,reopen_reason) "
        "VALUES('2026-08',1,'reopened','1','1','2026-09-01T00:00:00Z','operator','v1',?,"
        "'2026-09-02T00:00:00Z','operator','correction')", (empty_v1(1),)
    ).lastrowid
    second = conn.execute(
        "INSERT INTO month_closes(month_key,revision,status,reconciliation_version,policy_version,"
        "closed_at,closed_by,close_note,snapshot_hash) "
        "VALUES('2026-08',2,'closed','1','1','2026-09-03T00:00:00Z','operator','v2',?)",
        (empty_v1(2),),
    ).lastrowid
    conn.commit(); conn.close()
    result = migrate.run_migrations(database, backups_dir=backups)
    assert result.applied == [10, 11] and result.backup_path and result.backup_path.exists()
    conn = db.connect(database)
    assert conn.execute("SELECT supersedes_close_id FROM month_closes WHERE id=?", (second,)).fetchone()[0] == first
    assert month_close.snapshot(conn, "2026-08", close_id=first)["close"]["revision"] == 1
    assert month_close.snapshot(conn, "2026-08", close_id=second)["close"]["revision"] == 2
    conn.close()
    assert migrate.run_migrations(database, backups_dir=backups).applied == []


def test_closed_reconciliation_get_is_read_only_and_reopen_allows_reconciliation(migrated_db, monkeypatch):
    conn = _operational(migrated_db)
    employee_id = _employee(conn, "READONLY1")
    operational_safety.create_schedule(
        conn, employee_id=employee_id, effective_from="2026-08-01",
        effective_to="2026-08-31", weekday_mask="",
    )
    stable = _exception(conn, code="informational_history", work_date="2026-08-10",
                        scope="employee", employee_id=employee_id)
    conn.execute("UPDATE operational_exceptions SET severity='info' WHERE id=?", (stable["id"],))
    closed = month_close.close_month(conn, "2026-08", "operator", "Read-only close")
    # Simulate newly visible live facts without using a guarded production mutation.
    conn.execute(
        "INSERT INTO employee_schedule_dates(employee_id,work_date,is_scheduled,label,created_by) "
        "VALUES(?,'2026-08-11',1,'Newly visible test fact','test-fixture')", (employee_id,)
    )
    conn.commit()
    before = {
        "exceptions": conn.execute("SELECT COUNT(*) FROM operational_exceptions").fetchone()[0],
        "events": conn.execute("SELECT COUNT(*) FROM exception_events").fetchone()[0],
        "evidence": conn.execute("SELECT COUNT(*) FROM exception_evidence_links").fetchone()[0],
        "fingerprints": [tuple(row) for row in conn.execute(
            "SELECT id,observation_fingerprint FROM operational_exceptions ORDER BY id")],
    }
    conn.close()
    monkeypatch.setattr(config, "DB_PATH", migrated_db)
    client = TestClient(create_app())
    for _ in range(3):
        response = client.get("/api/v1/month-close/2026-08/reconciliation")
        assert response.status_code == 200 and response.json()["reconciliationStatus"] == "closed"
    conn = db.connect(migrated_db)
    after = {
        "exceptions": conn.execute("SELECT COUNT(*) FROM operational_exceptions").fetchone()[0],
        "events": conn.execute("SELECT COUNT(*) FROM exception_events").fetchone()[0],
        "evidence": conn.execute("SELECT COUNT(*) FROM exception_evidence_links").fetchone()[0],
        "fingerprints": [tuple(row) for row in conn.execute(
            "SELECT id,observation_fingerprint FROM operational_exceptions ORDER BY id")],
    }
    assert after == before
    month_close.reopen(conn, "2026-08", "operator", "Explicit re-evaluation")
    conn.commit(); conn.close()
    response = client.get("/api/v1/month-close/2026-08/reconciliation")
    assert response.status_code == 200
    conn = db.connect(migrated_db)
    assert conn.execute(
        "SELECT 1 FROM operational_exceptions WHERE employee_id=? AND work_date='2026-08-11' "
        "AND exception_code='scheduled_no_punch'", (employee_id,)
    ).fetchone()
    conn.close()


def test_schedule_completeness_blocks_without_adverse_employee_record(migrated_db, monkeypatch):
    conn = _operational(migrated_db)
    employee_id = conn.execute(
        "INSERT INTO employees(employee_code,name,hire_date,end_date,status) "
        "VALUES('COVERAGE1','Fictional Coverage','2026-08-01','2026-08-31','active')"
    ).lastrowid
    conn.execute(
        "INSERT INTO site_calendar(calendar_date,day_type,is_working,label) "
        "VALUES('2026-08-03','working',1,'Fictional working day')"
    )
    conn.commit(); conn.close()
    monkeypatch.setattr(config, "DB_PATH", migrated_db)
    client = TestClient(create_app())
    result = client.get("/api/v1/month-close/2026-08/reconciliation").json()
    missing = [item for item in result["blockingItems"] if item["code"] == "schedule_coverage_incomplete"]
    assert result["reconciliationStatus"] == "blocked"
    assert [(item["workDate"], item["periodEnd"]) for item in missing] == [("2026-08-01", "2026-08-31")]
    conn = db.connect(migrated_db)
    assert not conn.execute(
        "SELECT 1 FROM operational_exceptions WHERE exception_code='scheduled_no_punch' AND employee_id=?",
        (employee_id,),
    ).fetchone()
    assert not conn.execute(
        "SELECT 1 FROM attendance_days WHERE employee_id=? AND status IN ('absent','late','misconduct','unauthorized_absence')",
        (employee_id,),
    ).fetchone()
    conn.close()
    blocked = client.post(
        "/api/v1/month-close/2026-08/close",
        json={"actor": "operator", "reason": "Must remain blocked"},
    )
    assert blocked.status_code == 409
    conn = db.connect(migrated_db)
    assert conn.execute("SELECT COUNT(*) FROM month_closes").fetchone()[0] == 0
    operational_safety.create_schedule(
        conn, employee_id=employee_id, effective_from="2026-08-01",
        effective_to="2026-08-15", weekday_mask="",
    )
    conn.commit(); conn.close()
    partial = client.get("/api/v1/month-close/2026-08/reconciliation").json()
    partial_missing = [item for item in partial["blockingItems"] if item["code"] == "schedule_coverage_incomplete"]
    assert [(item["workDate"], item["periodEnd"]) for item in partial_missing] == [("2026-08-16", "2026-08-31")]
    conn = db.connect(migrated_db)
    operational_safety.create_schedule(
        conn, employee_id=employee_id, effective_from="2026-08-16",
        effective_to="2026-08-31", weekday_mask="",
    )
    conn.commit(); conn.close()
    complete = client.get("/api/v1/month-close/2026-08/reconciliation").json()
    assert not [item for item in complete["blockingItems"] if item["code"] == "schedule_coverage_incomplete"]
    assert complete["reconciliationStatus"] == "ready"
    assert client.post(
        "/api/v1/month-close/2026-08/close",
        json={"actor": "operator", "reason": "Schedule evidence complete"},
    ).status_code == 200


def test_single_date_override_does_not_cover_rest_of_employment_period(migrated_db):
    conn = _operational(migrated_db)
    employee_id = conn.execute(
        "INSERT INTO employees(employee_code,name,hire_date,end_date,status) "
        "VALUES('COVERAGE2','Fictional Override','2026-08-10','2026-08-12','active')"
    ).lastrowid
    operational_safety.set_schedule_date(
        conn, employee_id=employee_id, work_date="2026-08-11", is_scheduled=False,
    )
    result = month_close.reconcile(conn, "2026-08")
    missing = [item for item in result["blockingItems"]
               if item["code"] == "schedule_coverage_incomplete" and item["employeeId"] == employee_id]
    assert [(item["workDate"], item["periodEnd"]) for item in missing] == [
        ("2026-08-10", "2026-08-10"), ("2026-08-12", "2026-08-12")]
    assert not conn.execute(
        "SELECT 1 FROM operational_exceptions WHERE employee_id=? AND exception_code='scheduled_no_punch'",
        (employee_id,),
    ).fetchone()
    conn.close()


def test_retired_schedule_remains_authoritative_when_historical_month_reopens(migrated_db):
    conn = _operational(migrated_db)
    employee_id = conn.execute(
        "INSERT INTO employees(employee_code,name,hire_date,end_date,status) "
        "VALUES('HISTORY1','Fictional History','2026-08-01',NULL,'active')"
    ).lastrowid
    schedule = operational_safety.create_schedule(
        conn, employee_id=employee_id, effective_from='2026-08-01',
        effective_to=None, weekday_mask='',
    )
    assert not [item for item in month_close.reconcile(conn,'2026-08')['blockingItems']
                if item['code']=='schedule_coverage_incomplete']
    month_close.close_month(conn,'2026-08','operator','historical schedule close')
    # A September retirement changes September onward, not August history.
    operational_safety.retire_schedule(
        conn, schedule['id'], 'future retirement',
        retirement_effective_from='2026-09-01',
    )
    month_close.reopen(conn,'2026-08','operator','historical verification')
    reopened = month_close.reconcile(conn,'2026-08')
    assert not [item for item in reopened['blockingItems']
                if item['code']=='schedule_coverage_incomplete']
    assert operational_safety.resolve_schedule(conn,employee_id,'2026-08-31')['isAuthoritative']
    assert not operational_safety.resolve_schedule(conn,employee_id,'2026-09-01')['isAuthoritative']
    conn.close()


def test_open_ended_retirement_checks_every_affected_closed_month(migrated_db,monkeypatch):
    conn=_operational(migrated_db)
    employee_id=conn.execute(
        "INSERT INTO employees(employee_code,name,hire_date,status) "
        "VALUES('RETIRE-GUARD','Fictional Guard','2026-08-01','active')"
    ).lastrowid
    schedule=operational_safety.create_schedule(
        conn,employee_id=employee_id,effective_from='2026-08-01',
        effective_to=None,weekday_mask='',
    )
    august=month_close.close_month(conn,'2026-08','operator','August close')
    september=month_close.close_month(conn,'2026-09','operator','September close')
    september_before=month_close.snapshot(conn,'2026-09',close_id=september['id'])
    month_close.reopen(conn,'2026-08','operator','August correction')
    conn.commit();conn.close()

    monkeypatch.setattr(config,'DB_PATH',migrated_db)
    client=TestClient(create_app())
    blocked=client.post(
        f'/api/v1/employees/{employee_id}/schedules/{schedule["id"]}/retire',
        json={'actor':'operator','reason':'historical correction',
              'retirementEffectiveFrom':'2026-08-15'},
    )
    assert blocked.status_code==409
    conn=db.connect(migrated_db)
    unchanged=conn.execute(
        "SELECT status,retired_effective_from FROM employee_work_schedules WHERE id=?",
        (schedule['id'],),
    ).fetchone()
    assert tuple(unchanged)==('active',None)
    september_after=month_close.snapshot(conn,'2026-09',close_id=september['id'])
    assert september_after==september_before
    assert september_after['close']['snapshot_hash']==september['snapshot_hash']

    month_close.reopen(conn,'2026-09','operator','Affected future month correction')
    conn.commit();conn.close()
    allowed=client.post(
        f'/api/v1/employees/{employee_id}/schedules/{schedule["id"]}/retire',
        json={'actor':'operator','reason':'historical correction',
              'retirementEffectiveFrom':'2026-08-15'},
    )
    assert allowed.status_code==200
    conn=db.connect(migrated_db)
    assert operational_safety.resolve_schedule(conn,employee_id,'2026-08-14')['isAuthoritative']
    assert not operational_safety.resolve_schedule(conn,employee_id,'2026-08-15')['isAuthoritative']
    conn.close()


def test_0011_backfills_retired_schedule_history_and_is_idempotent(tmp_path):
    migrations = Path(config.MIGRATIONS_DIR)
    through10 = tmp_path/'through-v10'; through10.mkdir()
    for source in migrations.glob('*.sql'):
        if not source.name.startswith('0011_'):
            (through10/source.name).write_bytes(source.read_bytes())
    database=tmp_path/'v10.db';backups=tmp_path/'backups'
    assert migrate.run_migrations(database,migrations_dir=through10,backups_dir=backups).schema_version==10
    conn=db.connect(database)
    employee_id=conn.execute(
        "INSERT INTO employees(employee_code,name,hire_date,status) VALUES('LEGACY-SCHEDULE','Fictional Legacy','2025-01-01','active')"
    ).lastrowid
    schedule_id=conn.execute(
        "INSERT INTO employee_work_schedules(employee_id,effective_from,effective_to,weekday_mask,status,created_by,retired_at,retired_by) "
        "VALUES(?,'2026-08-01',NULL,'0,1,2,3,4','retired','legacy','2026-09-01T12:00:00Z','legacy')",
        (employee_id,),
    ).lastrowid
    conn.commit();conn.close()
    result=migrate.run_migrations(database,backups_dir=backups)
    assert result.applied==[11] and result.backup_path and result.backup_path.exists()
    conn=db.connect(database)
    row=conn.execute("SELECT retired_effective_from FROM employee_work_schedules WHERE id=?",(schedule_id,)).fetchone()
    assert row[0]=='2026-09-01'
    assert operational_safety.resolve_schedule(conn,employee_id,'2026-08-31')['isAuthoritative']
    assert not operational_safety.resolve_schedule(conn,employee_id,'2026-09-01')['isAuthoritative']
    conn.close()
    assert migrate.run_migrations(database,backups_dir=backups).applied==[]
