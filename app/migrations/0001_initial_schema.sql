-- 0001_initial_schema.sql
-- OPS Console — Phase 1 initial schema.
--
-- Design rules enforced here (AI_BUILD_PLAN.md §2, §3):
--   * foreign keys are declared on every relationship (enforcement requires
--     PRAGMA foreign_keys=ON, which app/db.py sets on every connection)
--   * every table carries created_at; mutable tables carry updated_at
--   * attendance is unique per (employee_id, work_date)
--   * punch_events is an immutable raw source table: DELETE is always refused
--     and raw source columns can never be updated (triggers below)
--   * substitute staffing lives in its own table and never overwrites attendance
--   * terminal registration slots are mapped to employees, and the mapping is
--     separate from the active employee roster

-- ---------------------------------------------------------------------------
-- employees
-- ---------------------------------------------------------------------------
CREATE TABLE employees (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_code   TEXT    NOT NULL UNIQUE,
    name            TEXT    NOT NULL,
    zone            TEXT,
    hire_date       TEXT    NOT NULL,
    end_date        TEXT,
    employment_type TEXT    NOT NULL DEFAULT 'regular'
                    CHECK (employment_type IN ('regular', 'substitute', 'temporary')),
    status          TEXT    NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active', 'on_leave', 'suspended', 'terminated')),
    note            TEXT,
    created_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (end_date IS NULL OR end_date >= hire_date)
);

CREATE INDEX idx_employees_status ON employees (status);
CREATE INDEX idx_employees_zone   ON employees (zone);

-- ---------------------------------------------------------------------------
-- site_calendar — site-specific working / non-working days (§2.8, §2.17)
-- ---------------------------------------------------------------------------
CREATE TABLE site_calendar (
    calendar_date TEXT    PRIMARY KEY,
    day_type      TEXT    NOT NULL
                  CHECK (day_type IN ('working', 'weekend', 'holiday', 'site_closed', 'special')),
    is_working    INTEGER NOT NULL DEFAULT 1 CHECK (is_working IN (0, 1)),
    label         TEXT,
    note          TEXT,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- ---------------------------------------------------------------------------
-- import_runs — one row per fingerprint XLS import attempt (§3, §7 phase 3)
-- ---------------------------------------------------------------------------
CREATE TABLE import_runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    source_filename    TEXT    NOT NULL,
    stored_source_path TEXT,
    source_sha256      TEXT,
    source_kind        TEXT    NOT NULL DEFAULT 'fingerprint_xls'
                       CHECK (source_kind IN ('fingerprint_xls', 'manual', 'other')),
    period_start       TEXT,
    period_end         TEXT,
    status             TEXT    NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'previewed', 'applied', 'failed', 'rolled_back')),
    snapshot_path      TEXT,
    source_row_count   INTEGER NOT NULL DEFAULT 0,
    punch_event_count  INTEGER NOT NULL DEFAULT 0,
    findings_json      TEXT,
    error_message      TEXT,
    created_by         TEXT,
    started_at         TEXT,
    finished_at        TEXT,
    rolled_back_at     TEXT,
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_import_runs_status ON import_runs (status, finished_at);

-- ---------------------------------------------------------------------------
-- terminal_slots — fingerprint terminal registration slot <-> employee (§3)
-- A slot is NOT the roster: it may be unmapped, and mapping can change over
-- time, so the mapping is date-scoped rather than a column on employees.
-- ---------------------------------------------------------------------------
CREATE TABLE terminal_slots (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_code      TEXT    NOT NULL,
    terminal_id    TEXT    NOT NULL DEFAULT 'default',
    employee_id    INTEGER REFERENCES employees (id) ON DELETE RESTRICT,
    display_name   TEXT,
    effective_from TEXT,
    effective_to   TEXT,
    status         TEXT    NOT NULL DEFAULT 'mapped'
                   CHECK (status IN ('mapped', 'unmapped', 'retired')),
    note           TEXT,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (terminal_id, slot_code, effective_from)
);

CREATE INDEX idx_terminal_slots_employee ON terminal_slots (employee_id);

-- ---------------------------------------------------------------------------
-- punch_events — IMMUTABLE raw fingerprint source events (§2.3, §2.4, §4)
-- Every raw punch is preserved forever. Nothing in this system may delete one,
-- including cascades, and the raw source columns may never be rewritten.
-- Derived/review columns (employee mapping, review flags, rollback marks) are
-- the only mutable part.
-- ---------------------------------------------------------------------------
CREATE TABLE punch_events (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    -- raw source (immutable)
    terminal_id        TEXT    NOT NULL DEFAULT 'default',
    terminal_slot_code TEXT    NOT NULL,
    punch_at           TEXT    NOT NULL,
    work_date          TEXT    NOT NULL,
    punch_type         TEXT    NOT NULL DEFAULT 'unknown'
                       CHECK (punch_type IN ('출', '외', '퇴', '복', 'unknown')),
    raw_payload        TEXT,
    source_filename    TEXT,
    source_row_no      INTEGER,
    source_hash        TEXT,
    dedupe_key         TEXT    UNIQUE,
    import_run_id      INTEGER REFERENCES import_runs (id) ON DELETE RESTRICT,
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    -- derived / review (mutable)
    employee_id        INTEGER REFERENCES employees (id) ON DELETE RESTRICT,
    review_flag        TEXT    CHECK (review_flag IS NULL OR review_flag IN
                                ('repeated_punch_candidate', 'unmapped_slot',
                                 'inactive_employee', 'before_hire_date',
                                 'leave_conflict', 'other')),
    review_note        TEXT,
    rolled_back_at     TEXT,
    rolled_back_reason TEXT
);

CREATE INDEX idx_punch_events_employee_date ON punch_events (employee_id, work_date);
CREATE INDEX idx_punch_events_slot_date     ON punch_events (terminal_slot_code, work_date);
CREATE INDEX idx_punch_events_import_run    ON punch_events (import_run_id);
CREATE INDEX idx_punch_events_review        ON punch_events (review_flag);

-- Raw punch records must never be deleted (§2.4). This also blocks any
-- accidental cascade or bulk cleanup.
CREATE TRIGGER trg_punch_events_no_delete
BEFORE DELETE ON punch_events
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'punch_events: raw fingerprint punch records must never be deleted');
END;

-- Raw source columns are immutable (§2.3, §4). Derived columns stay editable.
CREATE TRIGGER trg_punch_events_source_immutable
BEFORE UPDATE ON punch_events
FOR EACH ROW
WHEN OLD.terminal_id        IS NOT NEW.terminal_id
  OR OLD.terminal_slot_code IS NOT NEW.terminal_slot_code
  OR OLD.punch_at           IS NOT NEW.punch_at
  OR OLD.work_date          IS NOT NEW.work_date
  OR OLD.punch_type         IS NOT NEW.punch_type
  OR OLD.raw_payload        IS NOT NEW.raw_payload
  OR OLD.source_filename    IS NOT NEW.source_filename
  OR OLD.source_row_no      IS NOT NEW.source_row_no
  OR OLD.source_hash        IS NOT NEW.source_hash
  OR OLD.dedupe_key         IS NOT NEW.dedupe_key
  OR OLD.import_run_id      IS NOT NEW.import_run_id
  OR OLD.created_at         IS NOT NEW.created_at
BEGIN
    SELECT RAISE(ABORT, 'punch_events: raw source columns are immutable');
END;

-- ---------------------------------------------------------------------------
-- attendance_days — derived, one row per employee per work date (§2.2, §2.11)
-- Corrections are updates with a revision bump, never DELETE -> INSERT.
-- ---------------------------------------------------------------------------
CREATE TABLE attendance_days (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id      INTEGER NOT NULL REFERENCES employees (id) ON DELETE RESTRICT,
    work_date        TEXT    NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'unknown'
                     CHECK (status IN ('normal', 'late', 'early_leave', 'absent',
                                       'leave', 'half_day', 'sick_leave',
                                       'holiday', 'off', 'unknown')),
    scheduled_start  TEXT,
    scheduled_end    TEXT,
    actual_in_at     TEXT,
    actual_out_at    TEXT,
    worked_minutes   INTEGER,
    source           TEXT    NOT NULL DEFAULT 'derived'
                     CHECK (source IN ('fingerprint', 'manual', 'derived', 'import')),
    review_flag      TEXT,
    review_note      TEXT,
    confirmed_at     TEXT,
    confirmed_by     TEXT,
    revision         INTEGER NOT NULL DEFAULT 1,
    last_import_run_id INTEGER REFERENCES import_runs (id) ON DELETE RESTRICT,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (employee_id, work_date)
);

CREATE INDEX idx_attendance_days_date   ON attendance_days (work_date);
CREATE INDEX idx_attendance_days_status ON attendance_days (status);

-- ---------------------------------------------------------------------------
-- documents — uploaded files / photos metadata (bytes live on disk)
-- ---------------------------------------------------------------------------
CREATE TABLE documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id   INTEGER REFERENCES employees (id) ON DELETE RESTRICT,
    entity_type   TEXT    NOT NULL DEFAULT 'employee'
                  CHECK (entity_type IN ('employee', 'leave_request', 'attendance_day',
                                         'replacement_assignment', 'import_run', 'other')),
    entity_id     INTEGER,
    doc_type      TEXT    NOT NULL DEFAULT 'other'
                  CHECK (doc_type IN ('medical_certificate', 'leave_form', 'photo',
                                      'contract', 'import_source', 'other')),
    title         TEXT,
    original_filename TEXT NOT NULL,
    stored_path   TEXT    NOT NULL,
    mime_type     TEXT,
    byte_size     INTEGER,
    sha256        TEXT,
    status        TEXT    NOT NULL DEFAULT 'stored'
                  CHECK (status IN ('pending', 'stored', 'quarantined', 'archived')),
    uploaded_by   TEXT,
    created_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_documents_employee ON documents (employee_id);
CREATE INDEX idx_documents_entity   ON documents (entity_type, entity_id);

-- ---------------------------------------------------------------------------
-- leave_requests (§2.8, §2.9, §2.13, §2.16)
-- ---------------------------------------------------------------------------
CREATE TABLE leave_requests (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id          INTEGER NOT NULL REFERENCES employees (id) ON DELETE RESTRICT,
    leave_type           TEXT    NOT NULL
                         CHECK (leave_type IN ('annual', 'half_day', 'sick', 'unpaid', 'special', 'other')),
    half_day_period      TEXT    CHECK (half_day_period IS NULL OR half_day_period IN ('am', 'pm')),
    start_date           TEXT    NOT NULL,
    end_date             TEXT    NOT NULL,
    -- working-day count from the site calendar, not naive date subtraction
    working_day_count    REAL,
    leave_year           INTEGER NOT NULL,
    status               TEXT    NOT NULL DEFAULT 'requested'
                         CHECK (status IN ('draft', 'requested', 'approved', 'rejected', 'cancelled')),
    reason               TEXT,
    evidence_document_id INTEGER REFERENCES documents (id) ON DELETE RESTRICT,
    cert_start_date      TEXT,
    cert_end_date        TEXT,
    return_to_work_date  TEXT,
    review_flag          TEXT,
    review_note          TEXT,
    approved_by          TEXT,
    approved_at          TEXT,
    created_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at           TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (end_date >= start_date),
    CHECK (cert_end_date IS NULL OR cert_start_date IS NULL OR cert_end_date >= cert_start_date),
    CHECK (leave_type <> 'half_day' OR half_day_period IS NOT NULL)
);

CREATE INDEX idx_leave_requests_employee ON leave_requests (employee_id, start_date, end_date);
CREATE INDEX idx_leave_requests_year     ON leave_requests (employee_id, leave_year);
CREATE INDEX idx_leave_requests_status   ON leave_requests (status);

-- ---------------------------------------------------------------------------
-- leave_balances — year-specific annual leave balance (§2.9)
-- ---------------------------------------------------------------------------
CREATE TABLE leave_balances (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id    INTEGER NOT NULL REFERENCES employees (id) ON DELETE RESTRICT,
    leave_year     INTEGER NOT NULL,
    granted_days   REAL    NOT NULL DEFAULT 0,
    carried_days   REAL    NOT NULL DEFAULT 0,
    used_days      REAL    NOT NULL DEFAULT 0,
    note           TEXT,
    created_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (employee_id, leave_year)
);

-- ---------------------------------------------------------------------------
-- replacement_assignments — substitute staffing (§2.7)
-- Deliberately a separate table: assigning a substitute can never overwrite the
-- normal attendance row of either employee.
-- ---------------------------------------------------------------------------
CREATE TABLE replacement_assignments (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    work_date              TEXT    NOT NULL,
    shift                  TEXT    NOT NULL DEFAULT 'day',
    zone                   TEXT,
    absent_employee_id     INTEGER REFERENCES employees (id) ON DELETE RESTRICT,
    substitute_employee_id INTEGER REFERENCES employees (id) ON DELETE RESTRICT,
    leave_request_id       INTEGER REFERENCES leave_requests (id) ON DELETE RESTRICT,
    status                 TEXT    NOT NULL DEFAULT 'vacancy'
                           CHECK (status IN ('vacancy', 'candidate', 'assigned', 'completed', 'cancelled')),
    reason                 TEXT,
    note                   TEXT,
    assigned_by            TEXT,
    assigned_at            TEXT,
    created_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at             TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (absent_employee_id IS NOT NULL OR substitute_employee_id IS NOT NULL),
    CHECK (absent_employee_id IS NULL OR substitute_employee_id IS NULL
           OR absent_employee_id <> substitute_employee_id)
);

CREATE INDEX idx_replacement_date ON replacement_assignments (work_date, status);
-- a substitute cannot be double-booked for the same date/shift
CREATE UNIQUE INDEX uq_replacement_substitute_slot
    ON replacement_assignments (substitute_employee_id, work_date, shift)
    WHERE substitute_employee_id IS NOT NULL AND status IN ('assigned', 'completed');

-- ---------------------------------------------------------------------------
-- notes
-- ---------------------------------------------------------------------------
CREATE TABLE notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER REFERENCES employees (id) ON DELETE RESTRICT,
    work_date   TEXT,
    category    TEXT    NOT NULL DEFAULT 'general'
                CHECK (category IN ('general', 'attendance', 'leave', 'replacement', 'document')),
    body        TEXT    NOT NULL,
    author      TEXT,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_notes_employee_date ON notes (employee_id, work_date);

-- ---------------------------------------------------------------------------
-- audit_log — append-only history for manual and AI-assisted changes (§2.12)
-- ---------------------------------------------------------------------------
CREATE TABLE audit_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    actor_type         TEXT    NOT NULL DEFAULT 'system'
                       CHECK (actor_type IN ('user', 'ai', 'system', 'import')),
    actor_id           TEXT,
    provider           TEXT,
    session_ref        TEXT,
    action             TEXT    NOT NULL,
    entity_type        TEXT    NOT NULL,
    entity_id          INTEGER,
    before_json        TEXT,
    after_json         TEXT,
    reason             TEXT,
    confirmation_token TEXT,
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_audit_log_entity   ON audit_log (entity_type, entity_id);
CREATE INDEX idx_audit_log_occurred ON audit_log (occurred_at);

-- The audit log is append-only: history may never be rewritten or erased.
CREATE TRIGGER trg_audit_log_no_update
BEFORE UPDATE ON audit_log
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: rows cannot be updated');
END;

CREATE TRIGGER trg_audit_log_no_delete
BEFORE DELETE ON audit_log
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: rows cannot be deleted');
END;

-- ---------------------------------------------------------------------------
-- updated_at maintenance
-- SQLite recursive triggers are OFF by default, so the UPDATE issued inside an
-- AFTER UPDATE trigger does not re-fire the trigger.
-- ---------------------------------------------------------------------------
CREATE TRIGGER trg_employees_touch AFTER UPDATE ON employees FOR EACH ROW
BEGIN
    UPDATE employees SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_site_calendar_touch AFTER UPDATE ON site_calendar FOR EACH ROW
BEGIN
    UPDATE site_calendar SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
     WHERE calendar_date = OLD.calendar_date;
END;

CREATE TRIGGER trg_import_runs_touch AFTER UPDATE ON import_runs FOR EACH ROW
BEGIN
    UPDATE import_runs SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_terminal_slots_touch AFTER UPDATE ON terminal_slots FOR EACH ROW
BEGIN
    UPDATE terminal_slots SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

-- attendance corrections bump the revision counter instead of being deleted
CREATE TRIGGER trg_attendance_days_touch AFTER UPDATE ON attendance_days FOR EACH ROW
BEGIN
    UPDATE attendance_days
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
           revision    = OLD.revision + 1
     WHERE id = OLD.id;
END;

CREATE TRIGGER trg_leave_requests_touch AFTER UPDATE ON leave_requests FOR EACH ROW
BEGIN
    UPDATE leave_requests SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_leave_balances_touch AFTER UPDATE ON leave_balances FOR EACH ROW
BEGIN
    UPDATE leave_balances SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_replacement_touch AFTER UPDATE ON replacement_assignments FOR EACH ROW
BEGIN
    UPDATE replacement_assignments SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_documents_touch AFTER UPDATE ON documents FOR EACH ROW
BEGIN
    UPDATE documents SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;

CREATE TRIGGER trg_notes_touch AFTER UPDATE ON notes FOR EACH ROW
BEGIN
    UPDATE notes SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = OLD.id;
END;
