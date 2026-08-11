"""The one sanctioned way to change an attendance day.

Background (finding N1 from the Phase 1 review): `INSERT OR REPLACE INTO
attendance_days` silently destroys and recreates the row — a new `id`, the
`revision` counter reset, `review_note` lost, `created_at` reset, and no audit
record. `UPDATE OR REPLACE` can destroy a *different* day's row when it forces
a unique collision. Both are reachable through ordinary operation; neither
needs an attacker. AI_BUILD_PLAN.md §2.11 forbids exactly this.

Nothing in the schema prevents it. A `BEFORE INSERT` guard would also block the
legitimate `ON CONFLICT DO UPDATE` upsert that deriving attendance from punches
needs, and a no-DELETE trigger would block import rollback — so the rule lives
here, in code, and is held in place by regression tests.

Guarantees of `correct_attendance`:

    * the same attendance_days.id  — the row is updated, never replaced
    * the same created_at
    * revision increments exactly once
    * an audit_log row written in the same transaction
    * rolling back the transaction cancels both changes together

The function deliberately does not commit. The caller owns the transaction,
which is what makes the last guarantee real.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

# Columns a correction may touch. Identity and history are not among them.
EDITABLE_FIELDS = frozenset({
    "status",
    "scheduled_start",
    "scheduled_end",
    "actual_in_at",
    "actual_out_at",
    "worked_minutes",
    "review_flag",
    "review_note",
    "confirmed_at",
    "confirmed_by",
})

PROTECTED_FIELDS = frozenset({
    "id", "employee_id", "work_date", "created_at", "revision", "updated_at",
})


class AttendanceCorrectionError(ValueError):
    """A correction was refused before anything was written."""


@dataclass
class CorrectionResult:
    attendance_id: int
    revision_before: int
    revision_after: int
    audit_id: int
    before: dict[str, Any]
    after: dict[str, Any]

    @property
    def changed_fields(self) -> list[str]:
        return sorted(k for k in self.after if self.before.get(k) != self.after[k])


def correct_attendance(
    conn: sqlite3.Connection,
    *,
    employee_id: int,
    work_date: str,
    changes: dict[str, Any],
    actor_id: str,
    reason: str,
    actor_type: str = "user",
    provider: str | None = None,
    session_ref: str | None = None,
    confirmation_token: str | None = None,
) -> CorrectionResult:
    """Update one attendance day and record the change. Does not commit."""
    if not changes:
        raise AttendanceCorrectionError("a correction must change at least one field")

    unknown = set(changes) - EDITABLE_FIELDS
    if unknown:
        protected = sorted(unknown & PROTECTED_FIELDS)
        if protected:
            raise AttendanceCorrectionError(
                f"refusing to change protected field(s): {', '.join(protected)}. "
                "A correction updates a row in place; it never replaces its identity."
            )
        raise AttendanceCorrectionError(
            f"unknown attendance field(s): {', '.join(sorted(unknown))}"
        )

    if not reason or not reason.strip():
        raise AttendanceCorrectionError("a correction must carry a reason for the audit log")

    row = conn.execute(
        "SELECT * FROM attendance_days WHERE employee_id = ? AND work_date = ?",
        (employee_id, work_date),
    ).fetchone()
    if row is None:
        # Creating a missing day here is what tempts callers into
        # INSERT OR REPLACE. Deriving a new attendance day is a separate
        # operation with its own rules; this function only corrects.
        raise AttendanceCorrectionError(
            f"no attendance row for employee {employee_id} on {work_date}; "
            "corrections update an existing day and never create one"
        )

    existing = dict(row)
    before = {field: existing[field] for field in changes}
    after = dict(changes)

    assignments = ", ".join(f"{field} = ?" for field in changes)
    conn.execute(
        f"UPDATE attendance_days SET {assignments} WHERE id = ?",
        (*changes.values(), existing["id"]),
    )

    cursor = conn.execute(
        """
        INSERT INTO audit_log (actor_type, actor_id, provider, session_ref, action,
                               entity_type, entity_id, before_json, after_json,
                               reason, confirmation_token)
        VALUES (?, ?, ?, ?, 'attendance.correct', 'attendance_days', ?, ?, ?, ?, ?)
        """,
        (
            actor_type,
            actor_id,
            provider,
            session_ref,
            existing["id"],
            json.dumps(before, ensure_ascii=False, sort_keys=True),
            json.dumps(after, ensure_ascii=False, sort_keys=True),
            reason,
            confirmation_token,
        ),
    )

    updated = conn.execute(
        "SELECT id, revision, created_at FROM attendance_days WHERE id = ?",
        (existing["id"],),
    ).fetchone()

    if updated["id"] != existing["id"] or updated["created_at"] != existing["created_at"]:
        # Defensive: if this ever trips, something replaced the row.
        raise AttendanceCorrectionError(
            "attendance row identity changed during correction — refusing to continue"
        )

    return CorrectionResult(
        attendance_id=existing["id"],
        revision_before=existing["revision"],
        revision_after=updated["revision"],
        audit_id=int(cursor.lastrowid),
        before=before,
        after=after,
    )
