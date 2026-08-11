"""Request and response shapes for the fingerprint XLS import endpoints.

Field names are camelCase because the frontend consumes them directly, matching
the rest of the API and the generated demo snapshot.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ApplyRequest(BaseModel):
    """The second, explicit step. Without the preview's token, nothing applies."""

    confirmationToken: str = Field(min_length=16, max_length=200)


class RollbackRequest(BaseModel):
    """A rollback must say why: the reason goes straight into the audit log."""

    reason: str = Field(min_length=2, max_length=500)


class ApplyResult(BaseModel):
    importRunId: int
    inserted: int
    alreadyPresent: int
    reactivated: int
    attendanceRows: int
    snapshotPath: str


class RollbackResult(BaseModel):
    importRunId: int
    punchesMarkedRolledBack: int
    attendanceRecomputed: int
    # Always 0. §2.4: a rollback marks raw events, it never deletes one.
    punchesDeleted: int
    # Rows this rollback deliberately did not touch, because somebody had
    # confirmed or corrected them since the import.
    conflicts: list[dict] = Field(default_factory=list)


class ImportRunSummary(BaseModel):
    id: int
    sourceFilename: str | None = None
    status: str
    periodStart: str | None = None
    periodEnd: str | None = None
    punchEventCount: int | None = None
    startedAt: str | None = None
    finishedAt: str | None = None
    rolledBackAt: str | None = None
    errorMessage: str | None = None
    coveredDays: int = 0


class ImportRunDetail(ImportRunSummary):
    sourceSha256: str | None = None
    findings: list[dict] = Field(default_factory=list)
    days: list[dict] = Field(default_factory=list)
