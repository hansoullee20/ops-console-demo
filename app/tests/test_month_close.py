from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
import xlrd
from fastapi.testclient import TestClient

from app import config, db
from app import migrate
from app.main import create_app
from app.services import leave_operations, month_close, operational_safety


def operational_db(migrated_db):
    conn = db.connect(migrated_db)
    conn.execute("UPDATE app_meta SET value='operational' WHERE key='data_context'")
    conn.commit(); conn.close()
    return migrated_db


def test_reconciliation_blocking_policy_and_lifecycle(migrated_db):
    path = operational_db(migrated_db); conn = db.connect(path)
    employee = conn.execute("INSERT INTO employees(employee_code,name,hire_date,end_date) VALUES('MC1','가상마감01','2026-08-03','2026-08-03')").lastrowid
    exception = operational_safety.ensure_exception(conn, code="scheduled_no_punch", severity="review", scope="employee", employee_id=employee, work_date="2026-08-03", summary="확인 필요")
    result = month_close.reconcile(conn, "2026-08")
    assert result["reconciliationStatus"] == "blocked"
    assert result["blockingItems"][0]["code"] == "scheduled_no_punch"
    operational_safety.transition_exception(conn, exception["id"], "waived", "관리자 확인 완료")
    result = month_close.reconcile(conn, "2026-08")
    assert result["reconciliationStatus"] == "ready"
    assert not result["blockingItems"]
    conn.close()


def test_close_snapshot_hash_reopen_revision_and_export(migrated_db):
    path = operational_db(migrated_db); conn = db.connect(path)
    first = month_close.close_month(conn, "2026-08", "operator", "월 마감 확인")
    conn.commit()
    assert len(first["snapshot_hash"]) == 64
    with pytest.raises(month_close.MonthCloseError): month_close.close_month(conn, "2026-08", "operator", "중복")
    frozen = month_close.snapshot(conn, "2026-08")
    with pytest.raises(Exception): conn.execute("DELETE FROM month_closes WHERE id=?", (first["id"],))
    conn.rollback()
    month_close.reopen(conn, "2026-08", "operator", "정정 필요")
    second = month_close.close_month(conn, "2026-08", "operator", "재마감")
    conn.commit()
    assert second["revision"] == 2 and second["id"] != first["id"]
    assert month_close.get_close(conn, first["id"])["status"] == "reopened"
    payload = month_close.export_xls(conn, "2026-08")
    book = xlrd.open_workbook(file_contents=payload)
    assert book.sheet_names() == ["제출용 근태자료"]
    assert "일반 형식" in book.sheet_by_index(0).cell_value(0, 0)
    assert frozen["close"]["snapshot_hash"] == first["snapshot_hash"]
    conn.close()


def test_close_is_atomic_and_concurrent(migrated_db):
    path = operational_db(migrated_db)
    def attempt():
        conn = db.connect(path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            result = month_close.close_month(conn, "2026-09", "operator", "동시 마감")
            conn.commit(); return ("ok", result["id"])
        except Exception as exc:
            conn.rollback(); return ("error", str(exc))
        finally: conn.close()
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: attempt(), range(2)))
    assert [x[0] for x in results].count("ok") == 1
    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM month_closes WHERE month_key='2026-09'").fetchone()[0] == 1
    conn.close()


def test_closed_month_rejects_leave_manual_and_schedule_mutations(migrated_db):
    path = operational_db(migrated_db); conn = db.connect(path)
    month_close.close_month(conn, "2026-08", "operator", "월 마감"); conn.commit()
    employee = conn.execute("INSERT INTO employees(employee_code,name,hire_date) VALUES('MC2','가상마감02','2025-01-01')").lastrowid
    with pytest.raises(leave_operations.LeaveError):
        leave_operations.create_leave(conn, employee_id=employee, leave_type="annual_leave", start_date="2026-08-10", end_date="2026-08-10")
    with pytest.raises(operational_safety.SafetyError):
        operational_safety.create_adjustment(conn, employee_id=employee, work_date="2026-08-10", reason="관리자 확인")
    with pytest.raises(operational_safety.SafetyError):
        operational_safety.set_schedule_date(conn, employee_id=employee, work_date="2026-08-10", is_scheduled=True)
    conn.close()


def test_month_close_http_and_demo_guard(migrated_db, monkeypatch):
    path = operational_db(migrated_db); monkeypatch.setattr(config, "DB_PATH", path)
    client = TestClient(create_app())
    assert client.get("/api/v1/month-close/2026-08/reconciliation").json()["reconciliationStatus"] == "ready"
    response = client.post("/api/v1/month-close/2026-08/close", json={"actor": "operator", "reason": "월 마감"})
    assert response.status_code == 200
    assert client.post("/api/v1/month-close/2026-08/close", json={"actor": "operator", "reason": "중복"}).status_code == 409
    assert client.get("/api/v1/month-close/2026-08/export.xlsx").status_code == 200
    conn = db.connect(path); conn.execute("UPDATE app_meta SET value='demo' WHERE key='data_context'"); conn.commit(); conn.close()
    assert client.get("/api/v1/month-close/2026-08/reconciliation").status_code == 409


def test_0009_upgrade_is_additive_backed_up_and_idempotent(tmp_path):
    source = config.MIGRATIONS_DIR; old = tmp_path / "v8"; old.mkdir()
    for migration in source.glob("000[1-8]_*.sql"):
        (old / migration.name).write_bytes(migration.read_bytes())
    path = tmp_path / "phase425.db"; backups = tmp_path / "backups"
    migrate.run_migrations(path, migrations_dir=old, backups_dir=backups)
    conn = db.connect(path)
    conn.execute("INSERT INTO employees(employee_code,name,hire_date) VALUES('LEGACY45','가상기존','2025-01-01')")
    conn.commit(); before = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]; conn.close()
    result = migrate.run_migrations(path, backups_dir=backups)
    assert result.applied == [9] and result.backup_path and result.backup_path.exists()
    conn = db.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == before
    assert conn.execute("SELECT COUNT(*) FROM month_closes").fetchone()[0] == 0
    conn.close()
    assert migrate.run_migrations(path, backups_dir=backups).applied == []
