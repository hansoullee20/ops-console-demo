"""Generate the public demo snapshot (`demo-data.js`) from a database.

The GitHub Pages site has no backend, so the demo needs its data embedded. That
embedded data is NOT a second hand-maintained dataset: this exporter seeds a
throw-away database from the canonical fixture and serialises what the API
would have returned, using the same read models (`app/services/ops.py`).

Run by the Pages workflow at deploy time, so nothing generated is committed:

    python -m app.exporters.demo_snapshot _site/demo-data.js

Standard library only — the deploy must not need `pip install`.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

from app import db, migrate
from app.seed.canonical import DEMO_MONTH, DEMO_TODAY, DEMO_WEEK_START, DEMO_YEAR
from app.seed.demo_dataset import seed_demo_database
from app.services import ops

BANNER = """\
// GENERATED FILE — do not edit, and do not commit.
//
// Built at deploy time by `python -m app.exporters.demo_snapshot` from the
// canonical fixture in app/seed/canonical.py, via a real seeded database and
// the same read models the API uses. Editing this by hand would recreate the
// duplicate dataset it exists to avoid.
//
// This file is only ever shipped to the public GitHub Pages demo. The
// operational app never loads it: if the API is unavailable the app shows an
// error, it does not fall back to fictional data.
"""


def build_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    meta = ops.data_context(conn)
    week_start = meta.get("demo_week_start") or DEMO_WEEK_START
    today = meta.get("demo_today") or DEMO_TODAY
    view = ops.week_view(conn, week_start, today)
    return {
        "mode": "demo",
        "generatedFrom": "app/seed/canonical.py",
        "weekStart": week_start,
        "today": today,
        "days": view["days"],
        "employees": view["employees"],
        "monthStats": ops.month_stats(conn, DEMO_YEAR, DEMO_MONTH),
        "fingerprint": {"lastImportAt": None, "isStale": True},
    }


def render(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, indent=1, sort_keys=False)
    return f"{BANNER}window.OPS_DEMO_SNAPSHOT = {payload};\n"


def generate(target: Path | str) -> Path:
    """Seed a throw-away database and write the snapshot file."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "demo.db"
        migrate.run_migrations(db_path, backups_dir=Path(tmp) / "backups")
        seed_demo_database(db_path)
        with db.connection(db_path) as conn:
            snapshot = build_snapshot(conn)

    target.write_text(render(snapshot), encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    args = list(sys.argv[1:] if argv is None else argv)
    target = Path(args[0]) if args else Path("demo-data.js")
    written = generate(target)
    size = written.stat().st_size
    print(f"wrote {written} ({size} bytes)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
