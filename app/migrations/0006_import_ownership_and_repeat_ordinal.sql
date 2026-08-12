-- 0006_import_ownership_and_repeat_ordinal.sql
--
-- ops:allow-destructive
--   Recreates the punch_events immutability trigger and rewrites two derived
--   columns on existing rows (occurrence_index, dedupe_key). No table, column
--   or row is dropped, and no punch is deleted.
--
-- Two defects found by independent review of the Phase 3 import, both
-- reproduced before this migration was written.
--
-- 1. THE ORDINAL IN THE DEDUPE KEY WAS THE WRONG NUMBER
--
--    occurrence_index held a punch's absolute position inside the day's cell,
--    and the dedupe key used it. So a later re-export that adds a punch
--    *earlier in the day* renumbers everything after it:
--
--        first export      07:00 -> 0      16:00 -> 1
--        re-export with    06:50 -> 0      07:00 -> 1      16:00 -> 2
--        a missing punch
--
--    Every key changes, so two punches already in the database are imported a
--    second time. A month re-exported after a late fix would silently double.
--
--    The ordinal must instead count repeats of the same value: it exists only
--    to separate 06:40 from the second 06:40 on the same day. Adding 06:50
--    then leaves 07:00 at ordinal 0, where it was.
--
--    The absolute position is still worth keeping — it is where the punch sat
--    in the cell — so it moves to its own provenance column, cell_position,
--    and stays out of the key.
--
-- 2. AN IMPORT COULD BE ROLLED BACK AND LEAVE ATTENDANCE STANDING
--
--    punch_events.import_run_id is immutable: it records the run that first
--    brought a punch in, which is right for provenance and wrong for "who is
--    responsible for this row now". Re-applying the same file made a second
--    run take over the derived attendance while the punches still pointed at
--    the first run. Rolling back the first run then marked every punch
--    rolled_back, decided the attendance row belonged to somebody else, and
--    left it reading 정상 with zero surviving evidence.
--
--    active_import_run_id answers the second question and is deliberately
--    mutable: the run that most recently activated this event, updated when an
--    event is reactivated by a later import. Rollback works from it.

ALTER TABLE punch_events ADD COLUMN cell_position INTEGER;
ALTER TABLE punch_events ADD COLUMN active_import_run_id INTEGER
    REFERENCES import_runs (id) ON DELETE RESTRICT;

-- The trigger has to stand aside while the derived columns are corrected.
DROP TRIGGER trg_punch_events_source_immutable;

-- Keep the absolute position; it was what occurrence_index used to mean.
UPDATE punch_events SET cell_position = occurrence_index;

-- Recount the ordinal as repeats of the same value, oldest row first.
UPDATE punch_events
   SET occurrence_index = (
       SELECT COUNT(*) FROM punch_events AS earlier
        WHERE earlier.terminal_id        =  punch_events.terminal_id
          AND earlier.terminal_slot_code =  punch_events.terminal_slot_code
          AND earlier.work_date          =  punch_events.work_date
          AND earlier.punch_at           =  punch_events.punch_at
          AND IFNULL(earlier.punch_type, '') = IFNULL(punch_events.punch_type, '')
          AND earlier.id                 <  punch_events.id
   );

-- Rebuild the keys to match. Same format as xls_import.dedupe_key():
--   terminal | slot | work_date | HH:MM | punch_type | ordinal
UPDATE punch_events
   SET dedupe_key = terminal_id || '|' || terminal_slot_code || '|' || work_date
                    || '|' || substr(punch_at, 12, 5)
                    || '|' || IFNULL(punch_type, 'unknown')
                    || '|' || occurrence_index
 WHERE dedupe_key IS NOT NULL;

-- Rows already in the table were activated by the run that imported them,
-- except those already rolled back.
UPDATE punch_events
   SET active_import_run_id = import_run_id
 WHERE rolled_back_at IS NULL;

CREATE INDEX idx_punch_events_active_run ON punch_events (active_import_run_id);

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
  OR OLD.source_sheet       IS NOT NEW.source_sheet
  OR OLD.source_column      IS NOT NEW.source_column
  OR OLD.source_cell        IS NOT NEW.source_cell
  OR OLD.occurrence_index   IS NOT NEW.occurrence_index
  OR OLD.cell_position      IS NOT NEW.cell_position
BEGIN
    SELECT RAISE(ABORT, 'punch_events: raw source columns are immutable');
END;
