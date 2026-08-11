"""Response models for the health endpoint."""

from __future__ import annotations

from pydantic import BaseModel, Field


class DatabaseHealth(BaseModel):
    path: str
    exists: bool
    reachable: bool
    foreign_keys_enforced: bool
    schema_version: int
    applied_migrations: list[int] = Field(default_factory=list)
    missing_tables: list[str] = Field(default_factory=list)


class FingerprintHealth(BaseModel):
    """Fingerprint punch data is imported from monthly XLS exports and is
    routinely stale; the UI must always be able to show when it was last
    refreshed (AI_BUILD_PLAN.md §3)."""

    last_import_at: str | None = None
    last_import_id: int | None = None
    source_filename: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    is_stale: bool = True
    stale_after_hours: int


class HealthResponse(BaseModel):
    status: str
    app: str
    phase: int
    database: DatabaseHealth
    fingerprint: FingerprintHealth
    detail: str | None = None
