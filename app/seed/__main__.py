"""`python -m app.seed` — migrate and seed the configured database.

Writes the fictional demo dataset and marks the database `data_context=demo`,
so a demo-seeded file can never be mistaken for a real one.
"""

from __future__ import annotations

import sys

from app import config, migrate
from app.seed.demo_dataset import seed_demo_database


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    force = "--force" in argv

    config.ensure_runtime_dirs()
    result = migrate.init_database()
    print(f"schema version: {result.schema_version:04d}")

    summary = seed_demo_database(force=force)
    if summary.skipped:
        print(
            "database already contains data; nothing seeded. "
            "Re-run with --force to reseed an empty-able demo database."
        )
        return 0
    for table, count in summary.counts.items():
        print(f"  {table:<24} {count}")
    print(f"seeded demo dataset into {config.DB_PATH}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
