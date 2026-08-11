-- 0003_app_meta.sql
--
-- A single key/value table for database-level facts about *this* database.
--
-- Its first use is marking a database that has been filled with the fictional
-- demo dataset, so a demo-seeded file can never be mistaken for a real one.
-- This deliberately replaces the alternative of an is_demo column on every
-- business table: per-row flags would leak demo concerns into every future
-- query and rule, while the fact being recorded ("what is this database?") is
-- a property of the database, not of individual rows.

CREATE TABLE app_meta (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TRIGGER trg_app_meta_touch
AFTER UPDATE ON app_meta
FOR EACH ROW
WHEN OLD.key IS NOT NEW.key
  OR OLD.value IS NOT NEW.value
  OR OLD.created_at IS NOT NEW.created_at
BEGIN
    UPDATE app_meta
       SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
     WHERE key = OLD.key;
END;

-- Absence of a data_context row means "unknown"; the seeder writes 'demo'.
INSERT INTO app_meta (key, value) VALUES ('data_context', 'unknown');
