-- 0005_watched_imports.sql
--
-- The terminal's PC program can be told to export each month to a fixed
-- folder. The backend watches that folder and runs the *preview* by itself, so
-- nobody has to remember to upload a file. Applying stays manual, always: a
-- partial export or a terminal outage that imported itself would show a whole
-- site as absent, and nobody would know where the number came from.
--
-- Two columns support that:
--
--   preview_json   the whole preview payload as the operator would have seen
--                  it. A run previewed by the watcher hours ago has to be
--                  renderable later, when a human finally opens it. Storing it
--                  is what makes "확인 대기 중" a real queue rather than a
--                  number with nothing behind it. It is a snapshot for review;
--                  apply still recomputes everything from the preserved file.
--
--   discovered_by  'upload' or 'watch'. Where a run came from changes how it
--                  should be read: nobody chose a watched file, so an operator
--                  looking at the queue is seeing the folder's contents, not
--                  their own action.

ALTER TABLE import_runs ADD COLUMN preview_json TEXT;
ALTER TABLE import_runs ADD COLUMN discovered_by TEXT NOT NULL DEFAULT 'upload'
    CHECK (discovered_by IN ('upload', 'watch'));

-- The watcher's two lookups: "have I already seen this file?" (by digest) and
-- "what is waiting on a human?" — the status index from 0001 already covers
-- the second one.
CREATE INDEX idx_import_runs_sha ON import_runs (source_sha256);
