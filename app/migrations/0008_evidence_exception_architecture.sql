-- Phase 4.25: additive evidence, exception, manual correction, schedule, and source-quality model.
CREATE TABLE operational_exceptions (
    id INTEGER PRIMARY KEY,
    exception_code TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info','review','critical')),
    scope TEXT NOT NULL CHECK (scope IN ('employee','site','source','mapping','replacement')),
    employee_id INTEGER REFERENCES employees(id) ON DELETE RESTRICT,
    work_date TEXT,
    import_run_id INTEGER REFERENCES import_runs(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','acknowledged','resolved','waived')),
    occurrence_key TEXT NOT NULL,
    observation_fingerprint TEXT NOT NULL,
    summary TEXT NOT NULL,
    detail TEXT,
    previous_occurrence_id INTEGER REFERENCES operational_exceptions(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    created_by TEXT NOT NULL,
    acknowledged_at TEXT, acknowledged_by TEXT,
    resolved_at TEXT, resolved_by TEXT,
    waived_at TEXT, waived_by TEXT,
    resolution_note TEXT
);
CREATE UNIQUE INDEX uq_operational_exceptions_active_occurrence
 ON operational_exceptions(occurrence_key) WHERE status IN ('open','acknowledged');
CREATE INDEX idx_operational_exceptions_queue
 ON operational_exceptions(status,work_date,severity,exception_code,employee_id);

CREATE TABLE exception_events (
    id INTEGER PRIMARY KEY,
    exception_id INTEGER NOT NULL REFERENCES operational_exceptions(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    note TEXT,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX idx_exception_events_exception ON exception_events(exception_id,id);
CREATE TRIGGER exception_events_no_update BEFORE UPDATE ON exception_events
BEGIN SELECT RAISE(ABORT,'exception_events are append-only'); END;
CREATE TRIGGER exception_events_no_delete BEFORE DELETE ON exception_events
BEGIN SELECT RAISE(ABORT,'exception_events are append-only'); END;

CREATE TABLE exception_evidence_links (
    id INTEGER PRIMARY KEY,
    exception_id INTEGER NOT NULL REFERENCES operational_exceptions(id) ON DELETE RESTRICT,
    evidence_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    import_run_id INTEGER REFERENCES import_runs(id) ON DELETE RESTRICT,
    punch_event_id INTEGER REFERENCES punch_events(id) ON DELETE RESTRICT,
    reference_text TEXT,
    evidence_key TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    created_by TEXT NOT NULL,
    UNIQUE(exception_id,evidence_key)
);
CREATE TRIGGER exception_evidence_no_update BEFORE UPDATE ON exception_evidence_links
BEGIN SELECT RAISE(ABORT,'exception evidence is append-only'); END;
CREATE TRIGGER exception_evidence_no_delete BEFORE DELETE ON exception_evidence_links
BEGIN SELECT RAISE(ABORT,'exception evidence is append-only'); END;

CREATE TABLE manual_attendance_adjustments (
    id INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    work_date TEXT NOT NULL,
    recognized_in_at TEXT,
    recognized_out_at TEXT,
    resulting_status TEXT NOT NULL,
    reason TEXT NOT NULL,
    reference_note TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','voided','cancelled')),
    supersedes_adjustment_id INTEGER REFERENCES manual_attendance_adjustments(id) ON DELETE RESTRICT,
    superseded_by_adjustment_id INTEGER REFERENCES manual_attendance_adjustments(id) ON DELETE RESTRICT,
    attendance_id INTEGER REFERENCES attendance_days(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    created_by TEXT NOT NULL,
    ended_at TEXT, ended_by TEXT, end_reason TEXT
);
CREATE UNIQUE INDEX uq_manual_adjustment_active_employee_date
 ON manual_attendance_adjustments(employee_id,work_date) WHERE status='active';

CREATE TABLE employee_work_schedules (
    id INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    weekday_mask TEXT NOT NULL,
    expected_start_time TEXT,
    expected_end_time TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','retired')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    created_by TEXT NOT NULL,
    retired_at TEXT, retired_by TEXT,
    CHECK (effective_to IS NULL OR effective_from <= effective_to)
);
CREATE INDEX idx_employee_schedules_range ON employee_work_schedules(employee_id,effective_from,effective_to,status);

CREATE TABLE employee_schedule_dates (
    id INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE RESTRICT,
    work_date TEXT NOT NULL,
    is_scheduled INTEGER NOT NULL CHECK (is_scheduled IN (0,1)),
    expected_start_time TEXT,
    expected_end_time TEXT,
    label TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','cancelled')),
    supersedes_date_id INTEGER REFERENCES employee_schedule_dates(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    created_by TEXT NOT NULL
);
CREATE UNIQUE INDEX uq_employee_schedule_date_active
 ON employee_schedule_dates(employee_id,work_date) WHERE status='active';

CREATE TABLE source_quality_observations (
    id INTEGER PRIMARY KEY,
    observation_code TEXT NOT NULL,
    work_date TEXT,
    period_start TEXT,
    period_end TEXT,
    import_run_id INTEGER REFERENCES import_runs(id) ON DELETE RESTRICT,
    observed_value REAL,
    expected_value REAL,
    scheduled_worker_count INTEGER,
    rule_version TEXT NOT NULL,
    measurement_json TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE UNIQUE INDEX uq_source_quality_measurement
 ON source_quality_observations(observation_code,IFNULL(work_date,''),IFNULL(period_start,''),IFNULL(period_end,''),IFNULL(import_run_id,-1),rule_version);
