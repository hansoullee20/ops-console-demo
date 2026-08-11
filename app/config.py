"""Runtime paths and settings for the OPS Console backend.

Everything is resolved from the repository root so the backend behaves the same
whether it is started from the repo, a service manager, or a test.
All values can be overridden with environment variables, which keeps the work
PC deployment configurable without secrets in code (AI_BUILD_PLAN.md §4).
"""

from __future__ import annotations

import os
from pathlib import Path

# app/config.py -> app/ -> repository root
REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "app"

MIGRATIONS_DIR = Path(os.environ.get("OPS_MIGRATIONS_DIR", APP_DIR / "migrations"))
DATA_DIR = Path(os.environ.get("OPS_DATA_DIR", REPO_ROOT / "data"))
UPLOADS_DIR = Path(os.environ.get("OPS_UPLOADS_DIR", REPO_ROOT / "uploads"))
BACKUPS_DIR = Path(os.environ.get("OPS_BACKUPS_DIR", REPO_ROOT / "backups"))

DB_PATH = Path(os.environ.get("OPS_DB_PATH", DATA_DIR / "ops_console.db"))

# The backend is a work-PC host, not an internet service (AI_BUILD_PLAN.md §4).
# The bind address stays loopback unless a later, explicitly approved phase
# changes it.
HOST = os.environ.get("OPS_HOST", "127.0.0.1")
PORT = int(os.environ.get("OPS_PORT", "8000"))

# Fingerprint data is imported from monthly XLS exports, so it is routinely
# stale. Anything older than this many hours is reported as stale by /health
# (AI_BUILD_PLAN.md §3).
FINGERPRINT_STALE_AFTER_HOURS = int(os.environ.get("OPS_FINGERPRINT_STALE_HOURS", "24"))

# A monthly terminal export is a small file — the real 2026-07 one is under
# 300 KB. The cap exists so a wrong file (a video, a disk image) fails at once
# instead of filling the work PC's disk.
MAX_UPLOAD_BYTES = int(os.environ.get("OPS_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))

# A demo-seeded database contains 18 invented people. Importing a real terminal
# export into it would attach real punches to fictional staff and leave a file
# nobody can tell apart from real operations data. Imports are therefore refused
# on a database marked data_context=demo. The override exists so the flow can be
# exercised against the demo seed on purpose, never by accident.
ALLOW_DEMO_IMPORT = os.environ.get("OPS_ALLOW_DEMO_IMPORT", "").strip() == "1"


def ensure_runtime_dirs() -> None:
    """Create the writable runtime directories if they do not exist."""
    for path in (DATA_DIR, UPLOADS_DIR, BACKUPS_DIR):
        path.mkdir(parents=True, exist_ok=True)
