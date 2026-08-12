-- 0004_import_provenance_and_coverage.sql
--
-- ops:allow-destructive
--   Recreates the punch_events immutability trigger so it also guards the new
--   provenance columns. No table, column or row is dropped.
--
-- Two gaps this closes, both found by review of the Phase 3 importer:
--
-- 1. PROVENANCE
--    A punch_event is one punch *occurrence*, not one spreadsheet row: the real
--    export puts a whole day's punches in a single cell, separated by newlines.
--    Until now the occurrence index was being stored in source_row_no, which
--    left no way to point back at the cell a punch actually came from. Sheet,
--    row, column and cell address are now recorded separately from the
--    occurrence ordinal, so any imported punch can be traced to its exact
--    origin in the source file.
--
-- 2. IMPORT COVERAGE
--    Without a record of which dates a file covered, "the export contained
--    2026-07-17 and it had no punches at all" is indistinguishable from
--    "August was never imported". The first is a fact about the source that a
--    human must explain (a closure, a terminal outage, a partial export); the
--    second is simply absence of data. Conflating them is how a quiet day
--    turns into 18 absences. import_run_days records the fact, and records it
--    as a fact — never as an attendance verdict.

ALTER TABLE punch_events ADD COLUMN source_sheet TEXT;
ALTER TABLE punch_events ADD COLUMN source_column INTEGER;
ALTER TABLE punch_events ADD COLUMN source_cell TEXT;
ALTER TABLE punch_events ADD COLUMN occurrence_index INTEGER;

DROP TRIGGER trg_punch_events_source_immutable;

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
BEGIN
    SELECT RAISE(ABORT, 'punch_events: raw source columns are immutable');
END;

-- ---------------------------------------------------------------------------
-- import_run_days — what each import actually covered
--
-- coverage_status:
--   has_punches    the source carried this date and it had punches
--   reported_zero  the source carried this date and it had none. A fact about
--                  the file, not a judgement about anyone's attendance.
-- A date with no row here was never covered by any import at all.
-- ---------------------------------------------------------------------------
CREATE TABLE import_run_days (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    import_run_id      INTEGER NOT NULL REFERENCES import_runs (id) ON DELETE RESTRICT,
    work_date          TEXT    NOT NULL,
    source_date_present INTEGER NOT NULL DEFAULT 1 CHECK (source_date_present IN (0, 1)),
    raw_punch_count    INTEGER NOT NULL DEFAULT 0,
    coverage_status    TEXT    NOT NULL
                       CHECK (coverage_status IN ('has_punches', 'reported_zero')),
    note               TEXT,
    created_at         TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (import_run_id, work_date)
);

CREATE INDEX idx_import_run_days_date ON import_run_days (work_date, coverage_status);

-- ---------------------------------------------------------------------------
-- The preview fingerprint the apply step must still match.
-- ---------------------------------------------------------------------------
ALTER TABLE import_runs ADD COLUMN preview_fingerprint TEXT;
ALTER TABLE import_runs ADD COLUMN confirmation_token TEXT;
