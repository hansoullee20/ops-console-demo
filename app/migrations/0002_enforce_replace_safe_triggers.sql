-- 0002_enforce_replace_safe_triggers.sql
--
-- ops:allow-destructive
--   This migration drops and recreates the ten updated_at "touch" triggers.
--   No table, column or row is dropped; the marker is required because the
--   safety net (DROP TRIGGER) is itself a protected operation.
--
-- WHY
--
-- SQLite fires BEFORE DELETE triggers for the implicit delete performed by
-- INSERT OR REPLACE *only* when PRAGMA recursive_triggers is ON, and that
-- pragma is OFF by default. With it off, the punch_events and audit_log
-- protections added in 0001 could be bypassed:
--
--     INSERT OR REPLACE INTO punch_events (..., dedupe_key) VALUES (..., 'k1');
--
-- silently destroyed the existing raw punch event carrying dedupe_key 'k1'
-- and replaced it with different content — exactly the reimport idiom Phase 3
-- would reach for, and a direct violation of AI_BUILD_PLAN.md §2.3 / §2.4.
-- The same applied to audit_log via its rowid primary key (§2.12).
--
-- app/db.py now sets PRAGMA recursive_triggers = ON on every connection, which
-- closes that hole. But with recursion enabled the 0001 touch triggers never
-- terminate: each one issues an UPDATE on its own table, which re-fires the
-- trigger, until SQLite aborts with "too many levels of trigger recursion".
--
-- FIX
--
-- Each touch trigger gains a WHEN guard that compares only the business
-- columns — never updated_at (or revision, which the attendance trigger also
-- writes). The trigger's own UPDATE changes nothing the guard looks at, so the
-- second level is always false and recursion provably stops at depth 2,
-- independent of clock resolution. A guard of the form
-- "WHEN OLD.updated_at IS NEW.updated_at" would NOT be safe here: two updates
-- to the same row inside one millisecond leave the timestamp unchanged and
-- recurse until the depth limit.
--
-- Behaviour change: an UPDATE that changes no business column no longer bumps
-- updated_at. Real edits are unaffected.

DROP TRIGGER trg_employees_touch;
CREATE TRIGGER trg_employees_touch
AFTER UPDATE ON employees
FOR EACH ROW
WHEN OLD.id IS NOT NEW.id
  OR OLD.employee_code IS NOT NEW.employee_code
  OR OLD.name IS NOT NEW.name
  OR OLD.zone IS NOT NEW.zone
  OR OLD.hire_date IS NOT NEW.hire_date
  OR OLD.end_date IS NOT NEW.end_date
  OR OLD.employment_type IS NOT NEW.employment_type
  OR OLD.status IS NOT NEW.status
  OR OLD.note IS NOT NEW.note
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
    UPDATE employees
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
     WHERE id = OLD.id;
END;

DROP TRIGGER trg_site_calendar_touch;
CREATE TRIGGER trg_site_calendar_touch
AFTER UPDATE ON site_calendar
FOR EACH ROW
WHEN OLD.calendar_date IS NOT NEW.calendar_date
  OR OLD.day_type IS NOT NEW.day_type
  OR OLD.is_working IS NOT NEW.is_working
  OR OLD.label IS NOT NEW.label
  OR OLD.note IS NOT NEW.note
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
    UPDATE site_calendar
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
     WHERE calendar_date = OLD.calendar_date;
END;

DROP TRIGGER trg_import_runs_touch;
CREATE TRIGGER trg_import_runs_touch
AFTER UPDATE ON import_runs
FOR EACH ROW
WHEN OLD.id IS NOT NEW.id
  OR OLD.source_filename IS NOT NEW.source_filename
  OR OLD.stored_source_path IS NOT NEW.stored_source_path
  OR OLD.source_kind IS NOT NEW.source_kind
  OR OLD.period_start IS NOT NEW.period_start
  OR OLD.period_end IS NOT NEW.period_end
  OR OLD.status IS NOT NEW.status
  OR OLD.snapshot_path IS NOT NEW.snapshot_path
  OR OLD.source_row_count IS NOT NEW.source_row_count
  OR OLD.punch_event_count IS NOT NEW.punch_event_count
  OR OLD.findings_json IS NOT NEW.findings_json
  OR OLD.error_message IS NOT NEW.error_message
  OR OLD.created_by IS NOT NEW.created_by
  OR OLD.started_at IS NOT NEW.started_at
  OR OLD.finished_at IS NOT NEW.finished_at
  OR OLD.rolled_back_at IS NOT NEW.rolled_back_at
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
    UPDATE import_runs
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
     WHERE id = OLD.id;
END;

DROP TRIGGER trg_terminal_slots_touch;
CREATE TRIGGER trg_terminal_slots_touch
AFTER UPDATE ON terminal_slots
FOR EACH ROW
WHEN OLD.id IS NOT NEW.id
  OR OLD.slot_code IS NOT NEW.slot_code
  OR OLD.terminal_id IS NOT NEW.terminal_id
  OR OLD.employee_id IS NOT NEW.employee_id
  OR OLD.display_name IS NOT NEW.display_name
  OR OLD.effective_from IS NOT NEW.effective_from
  OR OLD.effective_to IS NOT NEW.effective_to
  OR OLD.status IS NOT NEW.status
  OR OLD.note IS NOT NEW.note
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
    UPDATE terminal_slots
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
     WHERE id = OLD.id;
END;

DROP TRIGGER trg_attendance_days_touch;
CREATE TRIGGER trg_attendance_days_touch
AFTER UPDATE ON attendance_days
FOR EACH ROW
WHEN OLD.id IS NOT NEW.id
  OR OLD.employee_id IS NOT NEW.employee_id
  OR OLD.work_date IS NOT NEW.work_date
  OR OLD.status IS NOT NEW.status
  OR OLD.scheduled_start IS NOT NEW.scheduled_start
  OR OLD.scheduled_end IS NOT NEW.scheduled_end
  OR OLD.actual_in_at IS NOT NEW.actual_in_at
  OR OLD.actual_out_at IS NOT NEW.actual_out_at
  OR OLD.worked_minutes IS NOT NEW.worked_minutes
  OR OLD.source IS NOT NEW.source
  OR OLD.review_flag IS NOT NEW.review_flag
  OR OLD.review_note IS NOT NEW.review_note
  OR OLD.confirmed_at IS NOT NEW.confirmed_at
  OR OLD.confirmed_by IS NOT NEW.confirmed_by
  OR OLD.last_import_run_id IS NOT NEW.last_import_run_id
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
    UPDATE attendance_days
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
           revision   = OLD.revision + 1
     WHERE id = OLD.id;
END;

DROP TRIGGER trg_leave_requests_touch;
CREATE TRIGGER trg_leave_requests_touch
AFTER UPDATE ON leave_requests
FOR EACH ROW
WHEN OLD.id IS NOT NEW.id
  OR OLD.employee_id IS NOT NEW.employee_id
  OR OLD.leave_type IS NOT NEW.leave_type
  OR OLD.half_day_period IS NOT NEW.half_day_period
  OR OLD.start_date IS NOT NEW.start_date
  OR OLD.end_date IS NOT NEW.end_date
  OR OLD.working_day_count IS NOT NEW.working_day_count
  OR OLD.leave_year IS NOT NEW.leave_year
  OR OLD.status IS NOT NEW.status
  OR OLD.reason IS NOT NEW.reason
  OR OLD.evidence_document_id IS NOT NEW.evidence_document_id
  OR OLD.cert_start_date IS NOT NEW.cert_start_date
  OR OLD.cert_end_date IS NOT NEW.cert_end_date
  OR OLD.return_to_work_date IS NOT NEW.return_to_work_date
  OR OLD.review_flag IS NOT NEW.review_flag
  OR OLD.review_note IS NOT NEW.review_note
  OR OLD.approved_by IS NOT NEW.approved_by
  OR OLD.approved_at IS NOT NEW.approved_at
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
    UPDATE leave_requests
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
     WHERE id = OLD.id;
END;

DROP TRIGGER trg_leave_balances_touch;
CREATE TRIGGER trg_leave_balances_touch
AFTER UPDATE ON leave_balances
FOR EACH ROW
WHEN OLD.id IS NOT NEW.id
  OR OLD.employee_id IS NOT NEW.employee_id
  OR OLD.leave_year IS NOT NEW.leave_year
  OR OLD.granted_days IS NOT NEW.granted_days
  OR OLD.carried_days IS NOT NEW.carried_days
  OR OLD.used_days IS NOT NEW.used_days
  OR OLD.note IS NOT NEW.note
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
    UPDATE leave_balances
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
     WHERE id = OLD.id;
END;

DROP TRIGGER trg_replacement_touch;
CREATE TRIGGER trg_replacement_touch
AFTER UPDATE ON replacement_assignments
FOR EACH ROW
WHEN OLD.id IS NOT NEW.id
  OR OLD.work_date IS NOT NEW.work_date
  OR OLD.shift IS NOT NEW.shift
  OR OLD.zone IS NOT NEW.zone
  OR OLD.absent_employee_id IS NOT NEW.absent_employee_id
  OR OLD.substitute_employee_id IS NOT NEW.substitute_employee_id
  OR OLD.leave_request_id IS NOT NEW.leave_request_id
  OR OLD.status IS NOT NEW.status
  OR OLD.reason IS NOT NEW.reason
  OR OLD.note IS NOT NEW.note
  OR OLD.assigned_by IS NOT NEW.assigned_by
  OR OLD.assigned_at IS NOT NEW.assigned_at
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
    UPDATE replacement_assignments
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
     WHERE id = OLD.id;
END;

DROP TRIGGER trg_documents_touch;
CREATE TRIGGER trg_documents_touch
AFTER UPDATE ON documents
FOR EACH ROW
WHEN OLD.id IS NOT NEW.id
  OR OLD.employee_id IS NOT NEW.employee_id
  OR OLD.entity_type IS NOT NEW.entity_type
  OR OLD.entity_id IS NOT NEW.entity_id
  OR OLD.doc_type IS NOT NEW.doc_type
  OR OLD.title IS NOT NEW.title
  OR OLD.original_filename IS NOT NEW.original_filename
  OR OLD.stored_path IS NOT NEW.stored_path
  OR OLD.mime_type IS NOT NEW.mime_type
  OR OLD.byte_size IS NOT NEW.byte_size
  OR OLD.status IS NOT NEW.status
  OR OLD.uploaded_by IS NOT NEW.uploaded_by
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
    UPDATE documents
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
     WHERE id = OLD.id;
END;

DROP TRIGGER trg_notes_touch;
CREATE TRIGGER trg_notes_touch
AFTER UPDATE ON notes
FOR EACH ROW
WHEN OLD.id IS NOT NEW.id
  OR OLD.employee_id IS NOT NEW.employee_id
  OR OLD.work_date IS NOT NEW.work_date
  OR OLD.category IS NOT NEW.category
  OR OLD.body IS NOT NEW.body
  OR OLD.author IS NOT NEW.author
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
    UPDATE notes
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
     WHERE id = OLD.id;
END;
