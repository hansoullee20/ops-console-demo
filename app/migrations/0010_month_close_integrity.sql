-- Phase 4.5 integrity hardening: immutable close metadata, explicit lineage,
-- and frozen exception event/evidence membership for every revision.
ALTER TABLE month_closes
    ADD COLUMN supersedes_close_id INTEGER REFERENCES month_closes(id) ON DELETE RESTRICT;

UPDATE month_closes
SET supersedes_close_id = (
    SELECT previous.id
    FROM month_closes AS previous
    WHERE previous.month_key = month_closes.month_key
      AND previous.revision = month_closes.revision - 1
)
WHERE revision > 1 AND supersedes_close_id IS NULL;

CREATE INDEX idx_month_closes_lineage ON month_closes(supersedes_close_id);

CREATE TABLE month_close_exception_event_links (
    close_id INTEGER NOT NULL REFERENCES month_closes(id) ON DELETE RESTRICT,
    exception_event_id INTEGER NOT NULL REFERENCES exception_events(id) ON DELETE RESTRICT,
    PRIMARY KEY(close_id, exception_event_id)
);

CREATE TABLE month_close_exception_evidence_links (
    close_id INTEGER NOT NULL REFERENCES month_closes(id) ON DELETE RESTRICT,
    exception_evidence_link_id INTEGER NOT NULL REFERENCES exception_evidence_links(id) ON DELETE RESTRICT,
    PRIMARY KEY(close_id, exception_evidence_link_id)
);

CREATE TRIGGER month_closes_update_guard
BEFORE UPDATE ON month_closes
WHEN NOT (
    OLD.status = 'closed' AND NEW.status = 'reopened'
    AND NEW.id IS OLD.id
    AND NEW.month_key IS OLD.month_key
    AND NEW.revision IS OLD.revision
    AND NEW.snapshot_hash IS OLD.snapshot_hash
    AND NEW.closed_at IS OLD.closed_at
    AND NEW.closed_by IS OLD.closed_by
    AND NEW.close_note IS OLD.close_note
    AND NEW.policy_version IS OLD.policy_version
    AND NEW.reconciliation_version IS OLD.reconciliation_version
    AND NEW.supersedes_close_id IS OLD.supersedes_close_id
    AND NEW.created_at IS OLD.created_at
    AND OLD.reopened_at IS NULL AND NEW.reopened_at IS NOT NULL
    AND OLD.reopened_by IS NULL AND NEW.reopened_by IS NOT NULL
    AND OLD.reopen_reason IS NULL AND NEW.reopen_reason IS NOT NULL
)
BEGIN
    SELECT RAISE(ABORT, 'month close metadata is immutable except explicit reopen');
END;

CREATE TRIGGER month_close_exception_event_links_no_update
BEFORE UPDATE ON month_close_exception_event_links
BEGIN SELECT RAISE(ABORT,'month close snapshot is immutable'); END;
CREATE TRIGGER month_close_exception_event_links_no_delete
BEFORE DELETE ON month_close_exception_event_links
BEGIN SELECT RAISE(ABORT,'month close snapshot is immutable'); END;
CREATE TRIGGER month_close_exception_evidence_links_no_update
BEFORE UPDATE ON month_close_exception_evidence_links
BEGIN SELECT RAISE(ABORT,'month close snapshot is immutable'); END;
CREATE TRIGGER month_close_exception_evidence_links_no_delete
BEFORE DELETE ON month_close_exception_evidence_links
BEGIN SELECT RAISE(ABORT,'month close snapshot is immutable'); END;
