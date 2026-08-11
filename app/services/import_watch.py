"""Watch a folder for terminal exports and preview them automatically.

The console cannot reach the fingerprint terminal: the operator's PC program
produces the monthly `.XLS`. That program can usually be told to export on a
schedule into a fixed folder — and if it cannot, a person can still drop the
file there. Either way, this watcher notices the file and does the reading.

WHAT IT DOES NOT DO
-------------------
It never applies. A watched run stops at `previewed` and waits for a human,
exactly like an uploaded one. Automatic applying is the one thing that could
turn a partial export or a terminal outage into a site full of absences with
nobody in the loop — §3 and §2.14 exist precisely because that data is not
trustworthy without a look. So the automation removes the fetching, not the
judgement.

Three details that matter in a real folder:

* A file still being written is not read. Size and mtime must be unchanged
  between two passes before it is touched; half an export parses as a truncated
  month, which would look like real missing days.
* Files are recognised by content hash, not by name. The program may export
  `2026_7_MON.XLS` every month to the same path; a re-export with identical
  content is skipped, a changed one is previewed again.
* The operator's file is never moved or deleted. The watcher copies it (as the
  upload path does) and leaves the original where the program put it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path

from app import config, db
from app.services import ops, xls_import, xls_pipeline

logger = logging.getLogger("ops_console.import_watch")

SUFFIXES = (".xls",)


@dataclass
class ScanResult:
    previewed: list[int] = field(default_factory=list)
    skipped_already_seen: int = 0
    skipped_unstable: int = 0
    failed: list[str] = field(default_factory=list)
    reason: str | None = None      # set when the scan did not run at all

    def as_dict(self) -> dict:
        return {
            "previewed": self.previewed,
            "skippedAlreadySeen": self.skipped_already_seen,
            "skippedUnstable": self.skipped_unstable,
            "failed": self.failed,
            "reason": self.reason,
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def _already_seen(conn: sqlite3.Connection, digest: str) -> bool:
    """Has this exact file been through the pipeline before?

    Any prior run counts — including a failed one. Re-reading a file that
    already failed to parse would just refill the log every interval.
    """
    return conn.execute(
        "SELECT 1 FROM import_runs WHERE source_sha256 = ? LIMIT 1", (digest,)
    ).fetchone() is not None


def _context_allows_import(db_path: Path) -> bool:
    if config.ALLOW_DEMO_IMPORT:
        return True
    with db.connection(db_path, read_only=True) as conn:
        return ops.data_context(conn)["data_context"] != "demo"


class FolderWatcher:
    """Scans a folder on demand; `start()` runs it on an interval in a thread."""

    def __init__(
        self,
        watch_dir: Path,
        *,
        db_path: Path | None = None,
        interval_seconds: int = 600,
    ) -> None:
        self.watch_dir = Path(watch_dir)
        self.db_path = Path(db_path) if db_path else None
        self.interval_seconds = max(30, int(interval_seconds))
        # path -> (size, mtime_ns) from the previous pass; a file is only read
        # once these stop changing.
        self._seen_state: dict[str, tuple[int, int]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- one pass ----------------------------------------------------------
    def scan_once(self) -> ScanResult:
        result = ScanResult()
        db_path = self.db_path or config.DB_PATH

        if not self.watch_dir.is_dir():
            result.reason = f"watch directory does not exist: {self.watch_dir}"
            return result
        if not db_path.exists():
            result.reason = "database not initialised"
            return result
        if not _context_allows_import(db_path):
            # Same rule as the upload endpoint: real punches must not land in a
            # database full of invented people.
            result.reason = "database is demo-seeded; watched imports are refused"
            return result

        candidates = sorted(
            path for path in self.watch_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SUFFIXES
        )

        with db.connection(db_path, read_only=True) as conn:
            for path in candidates:
                try:
                    state = _fingerprint(path)
                except OSError:                      # vanished mid-scan
                    continue

                key = str(path)
                if self._seen_state.get(key) != state:
                    # First sighting, or it changed since the last pass: it may
                    # still be being written. Remember it and look again next time.
                    self._seen_state[key] = state
                    result.skipped_unstable += 1
                    continue

                try:
                    digest = _sha256(path)
                except OSError:
                    continue
                if _already_seen(conn, digest):
                    result.skipped_already_seen += 1
                    continue

                try:
                    preview = xls_pipeline.preview_import(
                        path,
                        db_path=db_path,
                        original_filename=path.name,
                        created_by="folder-watch",
                        discovered_by="watch",
                    )
                except xls_import.XlsImportError as exc:
                    # The run row exists and records the failure; the file is
                    # left alone for a human to look at.
                    logger.warning("watched file could not be read: %s (%s)", path.name, exc)
                    result.failed.append(path.name)
                    continue
                except Exception as exc:             # pragma: no cover - defensive
                    logger.exception("watched import failed for %s: %s", path.name, exc)
                    result.failed.append(path.name)
                    continue

                logger.info(
                    "watched import previewed: %s -> run %d (%d new punches, waiting for confirmation)",
                    path.name, preview.import_run_id, preview.new_punches,
                )
                result.previewed.append(preview.import_run_id)

        return result

    # -- background loop ---------------------------------------------------
    def _loop(self) -> None:  # pragma: no cover - timing
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception as exc:
                # A watcher that dies quietly is worse than one that logs and
                # keeps going; the operator can always upload by hand.
                logger.exception("import watch pass failed: %s", exc)
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:  # pragma: no cover - timing
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="ops-import-watch", daemon=True
        )
        self._thread.start()
        logger.info(
            "watching %s for terminal exports every %ds (preview only; applying stays manual)",
            self.watch_dir, self.interval_seconds,
        )

    def stop(self) -> None:  # pragma: no cover - timing
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None


def build_from_config() -> FolderWatcher | None:
    """The watcher only exists if a folder was configured."""
    if not config.WATCH_DIR:
        return None
    return FolderWatcher(
        config.WATCH_DIR, interval_seconds=config.WATCH_INTERVAL_SECONDS
    )


def pending_runs(conn: sqlite3.Connection) -> list[dict]:
    """Previewed imports waiting for somebody to confirm or discard them."""
    rows = conn.execute(
        """
        SELECT id, source_filename, period_start, period_end, started_at,
               discovered_by, preview_json
          FROM import_runs
         WHERE status = 'previewed' AND source_kind = 'fingerprint_xls'
         ORDER BY id DESC
        """
    ).fetchall()
    out = []
    for row in rows:
        new_punches = None
        if row["preview_json"]:
            try:
                new_punches = json.loads(row["preview_json"]).get("newPunches")
            except ValueError:  # pragma: no cover - defensive
                new_punches = None
        out.append({
            "importRunId": row["id"],
            "sourceFilename": row["source_filename"],
            "periodStart": row["period_start"],
            "periodEnd": row["period_end"],
            "startedAt": row["started_at"],
            "discoveredBy": row["discovered_by"],
            "newPunches": new_punches,
        })
    return out
