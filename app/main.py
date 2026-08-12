"""OPS Console backend — FastAPI application.

Phase 3 scope (AI_BUILD_PLAN.md §7): the fingerprint XLS import, on top of
Phase 2's one backend source behind the same UI.

  * SQLite initialisation and migrations on start-up
  * a health endpoint
  * a read-only operations API
  * the fingerprint import: upload -> preview -> confirm -> apply -> rollback
  * an optional watch on the folder the terminal's PC program exports into,
    which previews new files but never applies them
  * the console UI, served by an explicit file allowlist

Explicitly NOT in this phase: the attendance correction endpoint (the service
exists and is tested, but stays off HTTP until the UI needs editing), AI
tooling, remote access. The backend binds to loopback.

The public GitHub Pages demo is a separate, static artifact built from the same
seed; it never talks to this API, and this app never serves demo data.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import config, migrate
from app.routers import api, frontend, health, imports, slots
from app.services import import_watch

logger = logging.getLogger("ops_console")

DESCRIPTION = (
    "Backend for the university cleaning-staff operations console. "
    "Phase 3: database, migrations, health, the operations read API, and the "
    "fingerprint XLS import."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Bring the database up to date before serving; degrade, never crash."""
    try:
        result = migrate.init_database()
        if result.applied:
            logger.info(
                "applied migrations: %s",
                ", ".join(f"{v:04d}" for v in result.applied),
            )
        if result.backup_path:
            logger.info("pre-migration backup: %s", result.backup_path)
        logger.info("schema version %04d", result.schema_version)
    except Exception as exc:
        # A failed migration must not silently start a half-configured host.
        # /health reports the problem instead.
        logger.error("database initialisation failed: %s", exc)

    # Optional folder watch: previews new terminal exports, never applies them.
    watcher = import_watch.build_from_config()
    if watcher is not None:
        watcher.start()
    try:
        yield
    finally:
        if watcher is not None:
            watcher.stop()


def create_app() -> FastAPI:
    app = FastAPI(
        title="OPS Console Backend",
        description=DESCRIPTION,
        version="0.3.0",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(api.router)
    app.include_router(imports.router)
    app.include_router(slots.router)
    # last: its catch-all /{filename} route must not shadow the API
    app.include_router(frontend.router)
    return app


app = create_app()


def main() -> None:  # pragma: no cover - CLI convenience
    try:
        import uvicorn
    except ImportError:
        raise SystemExit(
            "uvicorn is not installed. Install backend dependencies with:\n"
            "    pip install -r requirements.txt"
        )
    # uvicorn only configures its own loggers, so without this the folder
    # watcher would run completely silently — including when it refuses to run
    # (wrong folder, demo database). Unattended work has to be visible.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    # Loopback by default: the backend is a work-PC host, not a public service.
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()
