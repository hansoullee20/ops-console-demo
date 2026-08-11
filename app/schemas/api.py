"""Response models for the read API.

The bootstrap payload is deliberately the same shape the demo snapshot has, so
the frontend renders operational data and demo data through one code path and
the two cannot drift apart.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Cell(BaseModel):
    type: str
    label: str
    punch: str
    shift: str
    issue: bool | None = None
    detail: str | None = None


class Day(BaseModel):
    date: str
    dow: str
    num: int
    today: bool | None = None


class EmployeeRow(BaseModel):
    name: str
    zone: str | None = None
    hire: str | None = None
    end: str | None = None
    leave: float | int | None = None
    slot: str | None = None
    state: str
    cells: list[Cell] = Field(default_factory=list)


class FingerprintInfo(BaseModel):
    lastImportAt: str | None = None
    isStale: bool = True


class LeaveCase(BaseModel):
    employee: str
    zone: str | None = None
    leaveType: str
    startDate: str
    endDate: str
    status: str
    workingDayCount: float | None = None
    certStartDate: str | None = None
    certEndDate: str | None = None
    finding: str | None = None


class MonthGridRow(BaseModel):
    name: str
    marks: list[str] = Field(default_factory=list)
    issues: int = 0


class MonthGrid(BaseModel):
    year: int
    month: int
    days: int
    employees: list[MonthGridRow] = Field(default_factory=list)


class Bootstrap(BaseModel):
    """Everything the operations views need in one round trip."""

    mode: str
    dataContext: str
    weekStart: str
    today: str | None = None
    days: list[Day] = Field(default_factory=list)
    employees: list[EmployeeRow] = Field(default_factory=list)
    monthStats: dict[str, dict[str, int]] = Field(default_factory=dict)
    leave: list[LeaveCase] = Field(default_factory=list)
    monthGrid: MonthGrid | None = None
    fingerprint: FingerprintInfo


class ReplacementRow(BaseModel):
    workDate: str
    shift: str
    zone: str | None = None
    absent: str | None = None
    substitute: str | None = None
    status: str
    reason: str | None = None


class NoteRow(BaseModel):
    employee: str | None = None
    workDate: str | None = None
    category: str
    body: str
    author: str | None = None
    createdAt: str


class DocumentRow(BaseModel):
    employee: str | None = None
    docType: str
    title: str | None = None
    originalFilename: str
    status: str
    createdAt: str


class AttendanceDetail(BaseModel):
    employee: str
    workDate: str
    status: str
    revision: int
    scheduledStart: str | None = None
    scheduledEnd: str | None = None
    reviewFlag: str | None = None
    reviewNote: str | None = None
    punches: list[dict[str, Any]] = Field(default_factory=list)
