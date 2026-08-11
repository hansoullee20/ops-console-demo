"""OPS Console backend — FastAPI application.

Phase 1 scope (AI_BUILD_PLAN.md §7): backend skeleton only.

  * SQLite initialisation and migrations on start-up
  * a health endpoint

Explicitly NOT in this phase: business endpoints, seeding the demo dataset,
serving or connecting the frontend, XLS import, AI tooling, remote access.
The static demo under the repository root is untouched and still runs
standalone on GitHub Pages.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import config, migrate
from app.routers import health

logger = logging.getLogger("ops_console")

DESCRIPTION = (
    "Backend skeleton for the university cleaning-staff operations console. "
    "Phase 1: database, migrations and health only."
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
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="OPS Console Backend",
        description=DESCRIPTION,
        version="0.1.0",
        lifespan=lifespan,
    )
    app.include_router(health.router)
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
    # Loopback by default: the backend is a work-PC host, not a public service.
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, reload=False)


if __name__ == "__main__":  # pragma: no cover
    main()
