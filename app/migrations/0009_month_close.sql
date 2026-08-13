-- Phase 4.5: additive, immutable monthly close revisions and normalized evidence links.
CREATE TABLE month_closes (
 id INTEGER PRIMARY KEY,
 month_key TEXT NOT NULL,
 revision INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('closed','reopened','superseded')),
 reconciliation_version TEXT NOT NULL,
 policy_version TEXT NOT NULL,
 closed_at TEXT NOT NULL,
 closed_by TEXT NOT NULL,
 close_note TEXT NOT NULL,
 snapshot_hash TEXT NOT NULL,
 reopened_at TEXT, reopened_by TEXT, reopen_reason TEXT,
 created_at TEXT NOT NULL DEFAULT(strftime('%Y-%m-%dT%H:%M:%fZ','now')),
 UNIQUE(month_key,revision)
);
CREATE UNIQUE INDEX uq_month_close_current_closed ON month_closes(month_key) WHERE status='closed';

CREATE TABLE month_close_items (
 id INTEGER PRIMARY KEY,
 close_id INTEGER NOT NULL REFERENCES month_closes(id) ON DELETE RESTRICT,
 sort_key TEXT NOT NULL,
 employee_id INTEGER REFERENCES employees(id) ON DELETE RESTRICT,
 work_date TEXT,
 record_type TEXT NOT NULL,
 record_id INTEGER,
 normalized_state TEXT NOT NULL,
 evidence_json TEXT NOT NULL,
 UNIQUE(close_id,sort_key)
);
CREATE INDEX idx_month_close_items_close ON month_close_items(close_id,sort_key);

CREATE TABLE month_close_exception_links (
 close_id INTEGER NOT NULL REFERENCES month_closes(id) ON DELETE RESTRICT,
 exception_id INTEGER NOT NULL REFERENCES operational_exceptions(id) ON DELETE RESTRICT,
 status_at_close TEXT NOT NULL,
 resolution_note TEXT,
 PRIMARY KEY(close_id,exception_id)
);
CREATE TABLE month_close_source_links (
 close_id INTEGER NOT NULL REFERENCES month_closes(id) ON DELETE RESTRICT,
 source_type TEXT NOT NULL,
 source_id INTEGER NOT NULL,
 PRIMARY KEY(close_id,source_type,source_id)
);

CREATE TRIGGER month_closes_no_delete BEFORE DELETE ON month_closes BEGIN SELECT RAISE(ABORT,'month close history is immutable'); END;
CREATE TRIGGER month_close_items_no_update BEFORE UPDATE ON month_close_items BEGIN SELECT RAISE(ABORT,'month close snapshot is immutable'); END;
CREATE TRIGGER month_close_items_no_delete BEFORE DELETE ON month_close_items BEGIN SELECT RAISE(ABORT,'month close snapshot is immutable'); END;
CREATE TRIGGER month_close_exception_links_no_update BEFORE UPDATE ON month_close_exception_links BEGIN SELECT RAISE(ABORT,'month close snapshot is immutable'); END;
CREATE TRIGGER month_close_exception_links_no_delete BEFORE DELETE ON month_close_exception_links BEGIN SELECT RAISE(ABORT,'month close snapshot is immutable'); END;
CREATE TRIGGER month_close_source_links_no_update BEFORE UPDATE ON month_close_source_links BEGIN SELECT RAISE(ABORT,'month close snapshot is immutable'); END;
CREATE TRIGGER month_close_source_links_no_delete BEFORE DELETE ON month_close_source_links BEGIN SELECT RAISE(ABORT,'month close snapshot is immutable'); END;
