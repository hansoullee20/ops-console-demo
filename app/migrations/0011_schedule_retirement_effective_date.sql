-- Preserve the dates on which a retired employee schedule was authoritative.
-- Retirement ends applicability from this date; it does not erase earlier history.
ALTER TABLE employee_work_schedules
    ADD COLUMN retired_effective_from TEXT;

UPDATE employee_work_schedules
SET retired_effective_from = substr(COALESCE(retired_at, created_at), 1, 10)
WHERE status = 'retired' AND retired_effective_from IS NULL;

CREATE INDEX idx_employee_schedules_historical_range
ON employee_work_schedules(employee_id, effective_from, effective_to,
                           retired_effective_from, status);

CREATE TRIGGER employee_work_schedule_retirement_insert_guard
BEFORE INSERT ON employee_work_schedules
WHEN (NEW.status = 'retired' AND NEW.retired_effective_from IS NULL)
  OR (NEW.status = 'active' AND NEW.retired_effective_from IS NOT NULL)
  OR (NEW.retired_effective_from IS NOT NULL
      AND NEW.retired_effective_from < NEW.effective_from)
BEGIN
    SELECT RAISE(ABORT, 'invalid schedule retirement effective date');
END;

CREATE TRIGGER employee_work_schedule_retirement_update_guard
BEFORE UPDATE ON employee_work_schedules
WHEN (NEW.status = 'retired' AND NEW.retired_effective_from IS NULL)
  OR (NEW.status = 'active' AND NEW.retired_effective_from IS NOT NULL)
  OR (NEW.retired_effective_from IS NOT NULL
      AND NEW.retired_effective_from < NEW.effective_from)
BEGIN
    SELECT RAISE(ABORT, 'invalid schedule retirement effective date');
END;
