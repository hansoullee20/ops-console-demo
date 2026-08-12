-- Phase 4 operational metadata. Additive only: existing Phase 3.5 rows remain intact.
ALTER TABLE leave_requests ADD COLUMN evidence_received INTEGER NOT NULL DEFAULT 0
    CHECK (evidence_received IN (0, 1));
ALTER TABLE leave_requests ADD COLUMN evidence_checked_date TEXT;
ALTER TABLE leave_requests ADD COLUMN evidence_note TEXT;
ALTER TABLE leave_requests ADD COLUMN cancelled_at TEXT;

ALTER TABLE replacement_assignments ADD COLUMN start_date TEXT;
ALTER TABLE replacement_assignments ADD COLUMN end_date TEXT;
ALTER TABLE replacement_assignments ADD COLUMN key_received INTEGER NOT NULL DEFAULT 0
    CHECK (key_received IN (0, 1));
ALTER TABLE replacement_assignments ADD COLUMN uniform_ready INTEGER NOT NULL DEFAULT 0
    CHECK (uniform_ready IN (0, 1));
ALTER TABLE replacement_assignments ADD COLUMN orientation_done INTEGER NOT NULL DEFAULT 0
    CHECK (orientation_done IN (0, 1));
ALTER TABLE replacement_assignments ADD COLUMN completed_at TEXT;
ALTER TABLE replacement_assignments ADD COLUMN cancelled_at TEXT;

UPDATE replacement_assignments
   SET start_date = work_date, end_date = work_date
 WHERE start_date IS NULL OR end_date IS NULL;

CREATE INDEX idx_replacement_period
    ON replacement_assignments (substitute_employee_id, start_date, end_date, status);
