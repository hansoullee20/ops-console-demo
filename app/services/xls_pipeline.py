"""Preview, apply and roll back a fingerprint XLS import.

The flow is the one AI_BUILD_PLAN.md Â§7 Phase 3 requires:

     1. upload, preserve the original, open an import_run (pending)
     2. hash the source
     3. parse
     4. build the preview            (no business data written)
     5. slot mapping / findings
     6. preview fingerprint + snapshot
     7. explicit confirmation
     8. verify the token still matches this file AND this preview
     9. apply, in one transaction
    10. import_run -> applied, with per-date coverage recorded
    11. rollback available

The import_run exists from the upload, not from the apply: it represents the
whole lifecycle, which is what its pending/previewed/applied/failed/rolled_back
states were designed for.

The confirmation token is bound to import_run_id + source_sha256 + a fingerprint
of the preview itself. If the file or the slot mapping changed after the
operator reviewed it, the old confirmation no longer applies. This guards
against a work mistake, not an attacker.

Rollback never deletes a punch. Raw events are marked `rolled_back_at` and stay
in the table forever (Â§2.4). Derived attendance is recomputed from what remains,
but only for rows this import actually produced and that nobody has touched
since â€” anything else becomes a rollback_conflict finding instead of being
overwritten.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from app import config, db, migrate
from app.rules import punch_review
from app.rules.punch_review import Finding
from app.services import leave_operations, xls_import
from app.services.xls_import import ParsedWorkbook, dedupe_key

TERMINAL_ID = "default"


class ImportError_(RuntimeError):
    """The import could not proceed."""


class DemoContextRefused(ImportError_):
    """This database holds the fictional demo dataset; imports are refused."""


def ensure_import_allowed(db_path: Path | None = None) -> None:
    """Refuse to import real records into a database full of invented people.

    This lives in the service layer, not in the HTTP router, because it is a
    business rule rather than a transport concern. Every interface that can
    start an import â€” the API, the folder watcher, and any later tool layer â€”
    gets it by calling the same service functions, instead of each remembering
    to re-check. It used to be implemented separately in two places, which is
    how a third caller ends up without it.
    """
    if config.ALLOW_DEMO_IMPORT:
        return
    path = Path(db_path or config.DB_PATH)
    if not path.exists():
        return
    from app.services import ops  # noqa: PLC0415 - avoids an import cycle

    with db.connection(path, read_only=True) as conn:
        context = ops.data_context(conn)["data_context"]
    if context == "demo":
        raise DemoContextRefused(
            "ì´ ë°ì´í„°ë² ì´ìŠ¤ëŠ” ë°ëª¨ ì‹œë“œ(data_context=demo)ìž…ë‹ˆë‹¤. ì‹¤ì œ ì§€ë¬¸ ê¸°ë¡ì„ "
            "ê°€ì ¸ì˜¤ë©´ ê°€ìƒ ì§ì› 18ëª…ê³¼ ì„žì—¬ ì–´ëŠ ìª½ì´ ì‹¤ì œì¸ì§€ êµ¬ë¶„í•  ìˆ˜ ì—†ê²Œ ë©ë‹ˆë‹¤. "
            "ìš´ì˜ìš© ë°ì´í„°ë² ì´ìŠ¤ì—ì„œ ì‹¤í–‰í•˜ì‹­ì‹œì˜¤. ë°ëª¨ ì‹œë“œë¡œ íë¦„ë§Œ í™•ì¸í•˜ë ¤ë©´ "
            "OPS_ALLOW_DEMO_IMPORT=1 ë¡œ ë°±ì—”ë“œë¥¼ ì‹¤í–‰í•˜ì‹­ì‹œì˜¤."
        )


@dataclass
class ImportPreview:
    import_run_id: int
    source_filename: str
    stored_source_path: str
    source_sha256: str
    period_start: str
    period_end: str
    confirmation_token: str
    preview_fingerprint: str = ""
    previewed_at: str = ""
    slots: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    new_punches: int = 0
    already_imported: int = 0
    # Punches this file would bring back: the same raw events, currently marked
    # rolled_back. Re-applying a rolled-back source is a legitimate operation
    # (Â§E) and it inserts nothing, so "no new punches" cannot mean "no work".
    reactivatable_punches: int = 0
    zero_punch_dates: list[str] = field(default_factory=list)
    covered_dates: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> list[dict]:
        return [f for f in self.findings if f["severity"] == "blocking"]

    def as_dict(self) -> dict:
        return {
            "importRunId": self.import_run_id,
            "sourceFilename": self.source_filename,
            "sourceHash": self.source_sha256,
            "periodStart": self.period_start,
            "periodEnd": self.period_end,
            "confirmationToken": self.confirmation_token,
            "slots": self.slots,
            "findings": self.findings,
            "newPunches": self.new_punches,
            "alreadyImported": self.already_imported,
            "reactivatablePunches": self.reactivatable_punches,
            "zeroPunchDates": self.zero_punch_dates,
            "coveredDates": self.covered_dates,
            "previewFingerprint": self.preview_fingerprint,
            "previewedAt": self.previewed_at,
            "canApply": self.can_apply,
        }

    @property
    def can_apply(self) -> bool:
        """Is there anything for an apply to do?

        A file whose punches are all present and active is a no-op: applying it
        would produce an 'applied' run that changed nothing. A file whose
        punches were rolled back inserts nothing either, but reactivating them
        is real work, so it must stay allowed.
        """
        return not self.blocking and (self.new_punches + self.reactivatable_punches) > 0


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_name(filename: str) -> str:
    """A filename that can only ever land inside the uploads directory.

    The operator's file name is recorded verbatim in import_runs; this is only
    for the stored copy's path. Without it, a name like `../../index.html`
    would write outside uploads/.
    """
    name = Path(str(filename or "")).name
    name = re.sub(r"[^0-9A-Za-zê°€-íž£._-]+", "_", name).strip("._") or "upload.xls"
    return name[:120]


def _dates_in(period_start: str, period_end: str) -> list[str]:
    from app.services.ops import _date_range

    start_day = int(period_start[8:10])
    end_day = int(period_end[8:10])
    return _date_range(period_start, end_day - start_day + 1)


def _slot_intervals(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """Every mapping a slot has ever had, in date order.

    terminal_slots is date-scoped on purpose: a slot changes hands when someone
    leaves and their replacement inherits the finger. Reading it as one row per
    slot attributes July's punches to whoever holds the slot today â€” which is
    how a departed employee's month lands on their successor's record.
    """
    rows = conn.execute(
        """
        SELECT t.id, t.slot_code, t.status AS slot_status, t.effective_from, t.effective_to,
               e.id AS employee_id, e.name, e.status AS employee_status,
               e.hire_date, e.end_date
          FROM terminal_slots t
          LEFT JOIN employees e ON e.id = t.employee_id
         WHERE t.terminal_id = ? AND t.status = 'mapped'
         ORDER BY t.slot_code, IFNULL(t.effective_from, ''), t.id
        """,
        (TERMINAL_ID,),
    ).fetchall()
    intervals: dict[str, list[dict]] = {}
    for row in rows:
        intervals.setdefault(row["slot_code"], []).append(dict(row))
    return intervals


def _resolve_slot(
    intervals: dict[str, list[dict]], slot_code: str, work_date: str
) -> dict | None:
    """Who held this slot on this date, or None if nobody did.

    An open `effective_from` means "as far back as the records go"; an open
    `effective_to` means "still current". A punch on a date no mapping covers is
    left unattached rather than guessed at.
    """
    covering = [
        row for row in intervals.get(slot_code, [])
        if (not row["effective_from"] or row["effective_from"] <= work_date)
        and (not row["effective_to"] or work_date <= row["effective_to"])
    ]
    if not covering:
        return None
    # Latest applicable mapping wins if two overlap â€” a data problem, but a
    # deterministic answer beats an arbitrary one.
    return sorted(covering, key=lambda r: (r["effective_from"] or "", r["id"] if "id" in r.keys() else 0))[-1]


def _employment_review(employee: dict, work_date: str) -> str | None:
    """Return the date-scoped employment finding for a mapped punch."""
    if employee.get("hire_date") and work_date < employee["hire_date"]:
        return "before_hire_date"
    if employee.get("end_date") and work_date > employee["end_date"]:
        return "after_end_date"
    # Current termination is not historical evidence: dates through the
    # inclusive end date remain valid. Other non-active states still need review.
    if employee.get("employee_status") != "active" and not (
        employee.get("employee_status") == "terminated" and employee.get("end_date")
    ):
        return "inactive_employee"
    return None


# ---------------------------------------------------------------------------
# preview
# ---------------------------------------------------------------------------
def _preview_fingerprint(
    digest: str,
    slot_rows: list[dict],
    new_punches: int,
    findings: list[dict],
    reactivatable: int = 0,
) -> str:
    """A digest of what the operator actually reviewed.

    Everything on the screen goes in, so anything that would have changed the
    screen invalidates the confirmation:

    * the file, by hash;
    * the slot mapping *by employee id* â€” the display name is not identity, and
      remapping a slot from one ê¹€ë™ëª… to another must not slip through;
    * the findings themselves â€” a leave request approved between the review and
      the apply creates a leave_conflict the operator never saw.
    """
    payload = json.dumps(
        {
            "source": digest,
            "slots": [
                {k: row[k] for k in ("slot", "employee", "employeeIds", "status", "punchCount")}
                for row in slot_rows
            ],
            "newPunches": new_punches,
            # Part of the reviewed state: if rolled-back events came back
            # between the review and the apply, this is not what was agreed.
            "reactivatablePunches": reactivatable,
            "findings": sorted(
                json.dumps(f, ensure_ascii=False, sort_keys=True) for f in findings
            ),
        },
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _confirmation_token(run_id: int, digest: str, fingerprint: str, nonce: str) -> str:
    material = f"{run_id}|{digest}|{fingerprint}|{nonce}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def preview_import(
    source_path: Path | str,
    *,
    db_path: Path | None = None,
    uploads_dir: Path | None = None,
    original_filename: str | None = None,
    threshold_minutes: int = punch_review.DEFAULT_REPEATED_PUNCH_MINUTES,
    created_by: str = "operator",
    discovered_by: str = "upload",
) -> ImportPreview:
    """Preserve the original, open an import run, and report what apply would do.

    Writes no punch, attendance, leave or replacement data.
    """
    ensure_import_allowed(db_path)
    source_path = Path(source_path)
    uploads = Path(uploads_dir) if uploads_dir else config.UPLOADS_DIR
    uploads.mkdir(parents=True, exist_ok=True)

    filename = original_filename or source_path.name
    digest = _sha256(source_path)
    stored = uploads / (
        f"{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{digest[:12]}-{_safe_name(filename)}"
    )
    if source_path.resolve() != stored.resolve():
        shutil.copy2(source_path, stored)

    conn = db.connect(db_path or config.DB_PATH)
    try:
        # Step 1: the run exists from the upload, before anything is parsed, so
        # a file that fails to parse still leaves a record of the attempt.
        cursor = conn.execute(
            """
            INSERT INTO import_runs
                (source_filename, stored_source_path, source_sha256, source_kind,
                 status, created_by, started_at, discovered_by)
            VALUES (?, ?, ?, 'fingerprint_xls', 'pending', ?, ?, ?)
            """,
            (filename, str(stored), digest, created_by, _now(), discovered_by),
        )
        run_id = int(cursor.lastrowid)
        conn.commit()

        try:
            parsed = xls_import.parse_workbook(stored, source_filename=filename)
        except xls_import.XlsImportError as exc:
            conn.execute(
                "UPDATE import_runs SET status = 'failed', error_message = ? WHERE id = ?",
                (str(exc), run_id),
            )
            conn.commit()
            raise

        preview = _build_preview(conn, parsed, run_id, stored, digest, threshold_minutes)
        conn.execute(
            """
            UPDATE import_runs
               SET status = 'previewed', period_start = ?, period_end = ?,
                   source_row_count = ?, findings_json = ?,
                   preview_fingerprint = ?, confirmation_token = ?,
                   preview_json = ?
             WHERE id = ?
            """,
            (
                parsed.period_start, parsed.period_end, len(parsed.punches),
                json.dumps({"findings": preview.findings}, ensure_ascii=False),
                preview.preview_fingerprint, preview.confirmation_token,
                # Kept so a run previewed by the folder watcher can still be
                # reviewed hours later, by someone who never saw it happen.
                json.dumps(preview.as_dict(), ensure_ascii=False),
                run_id,
            ),
        )
        conn.commit()
        return preview
    finally:
        conn.close()


def _build_preview(
    conn: sqlite3.Connection,
    parsed: ParsedWorkbook,
    run_id: int,
    stored: Path,
    digest: str,
    threshold_minutes: int,
) -> ImportPreview:
    intervals = _slot_intervals(conn)
    # key -> is this event currently rolled back? The three states are
    # different work: absent = insert, rolled back = reactivate, active = no-op.
    existing = {
        row["dedupe_key"]: row["rolled_back_at"] is not None
        for row in conn.execute(
            "SELECT dedupe_key, rolled_back_at FROM punch_events "
            " WHERE dedupe_key IS NOT NULL"
        )
    }

    findings: list[Finding] = []
    slot_rows: list[dict] = []
    new_punches = already = reactivatable = 0

    by_slot_day: dict[tuple[ó½¶‰žËkºwµçQ…¹•}‘…åÌ€ˆ(€€€€€€€€€€€€€€€€€€€€ˆ€€MPÍÑ…ÑÕÌ€ô€Õ¹­¹½Ý¸œ°…ÑÕ…±}¥¹}…Ð€ô9U10°…ÑÕ…±}½ÕÑ}…Ð€ô9U10°€ˆ(€€€€€€€€€€€€€€€€€€€€ˆ€€€€€€É•Ù¥•Ý}™±…œ€ô€¥µÁ½ÉÑ}É½±±•‘}‰…¬œ€ˆ(€€€€€€€€€€€€€€€€€€€€ˆ]!I¥€ô€üˆ°(€€€€€€€€€€€€€€€€€€€€¡•á¥ÍÑ¥¹l‰¥‰t°¤°(€€€€€€€€€€€€€€€€¤(€€€€€€€€€€€€€€€ÝÉ¥ÑÑ•¸€¬ô€Ä(€€€€€€€€€€€½¹Ñ¥¹Õ”((€€€€€€€¥˜•µÁ±½åµ•¹Ñ}É•Ù¥•Ü¥¸ì‰‰•™½É•}¡¥É•}‘…Ñ”ˆ°€‰…™Ñ•É}•¹‘}‘…Ñ”‰ôè(€€€€€€€€€€€ÍÑ…ÑÕÌ€ô€‰Õ¹­¹½Ý¸ˆ(€€€€€€€€€€€É•Ù¥•Ý}™±…œ€ô•µÁ±½åµ•¹Ñ}É•Ù¥•Ü(€€€€€€€•±¥˜±•…Ù•}½Ù•É…•l‰½Ù•É…”‰t€„ô€‰¹½¹”ˆè(€€€€€€€€€€€±•…Ù•}ÑåÁ”€ô±•…Ù•}½Ù•É…•l‰±•…Ù•QåÁ”‰t(€€€€€€€€€€€ÍÑ…ÑÕÌ€ô€‰¡…±™}‘…äˆ¥˜±•…Ù•}½Ù•É…•l‰½Ù•É…”‰t¥¸ì‰…´ˆ°€‰Á´‰ô•±Í”€‰Í¥­}±•…Ù”ˆ¥˜±•…Ù•}ÑåÁ”€ôô€‰Í¥¬ˆ•±Í”€‰±•…Ù”ˆ(€€€€€€€€€€€É•Ù¥•Ý}™±…œ€ô€‰Á…ÉÑ¥…±}±•…Ù•}É•Ù¥•Üˆ¥˜±•…Ù•}½Ù•É…•l‰½Ù•É…”‰t¥¸ì‰…´ˆ°€‰Á´‰ô•±Í”€‰±•…Ù•}…ÑÑ•¹‘…¹•}½¹™±¥Ðˆ(€€€€€€€•±Í”è(€€€€€€€€€€€ÍÑ…ÑÕÌ€ô€‰¹½Éµ…°ˆ¥˜±•¸¡Ñ¥µ•Ì¤€øô€È•±Í”€‰Õ¹­¹½Ý¸ˆ(€€€€€€€€€€€É•Ù¥•Ý}™±…œ€ô9½¹”¥˜±•¸¡Ñ¥µ•Ì¤€øô€È•±Í”€‰¥¹½µÁ±•Ñ•}‘…äˆ(€€€€€€€½¹¸¹•á•ÕÑ” (€€€€€€€€€€€€ˆˆˆ(€€€€€€€€€€€%9MIP%9Q<…ÑÑ•¹‘…¹•}‘…åÌ(€€€€€€€€€€€€€€€€¡•µÁ±½å••}¥°Ý½É­}‘…Ñ”°ÍÑ…ÑÕÌ°…ÑÕ…±}¥¹}…Ð°…ÑÕ…±}½ÕÑ}…Ð°Í½ÕÉ”°(€€€€€€€€€€€€€€€€É•Ù¥•Ý}™±…œ°±…ÍÑ}¥µÁ½ÉÑ}ÉÕ¹}¥¤(€€€€€€€€€€€Y1UL€ ü°€ü°€ü°€ü°€ü°€™¥¹•ÉÁÉ¥¹Ðœ°€ü°€ü¤(€€€€€€€€€€€=8=91%P¡•µÁ±½å••}¥°Ý½É­}‘…Ñ”¤<UAQMP(€€€€€€€€€€€€€€€ÍÑ…ÑÕÌ€ô•á±Õ‘•¹ÍÑ…ÑÕÌ°(€€€€€€€€€€€€€€€…ÑÕ…±}¥¹}…Ð€ô•á±Õ‘•¹…ÑÕ…±}¥¹}…Ð°(€€€€€€€€€€€€€€€…ÑÕ…±}½ÕÑ}…Ð€ô•á±Õ‘•¹…ÑÕ…±}½ÕÑ}…Ð°(€€€€€€€€€€€€€€€Í½ÕÉ”€ô€™¥¹•ÉÁÉ¥¹Ðœ°(€€€€€€€€€€€€€€€€´´™±…œÑ¡”¥µÁ½ÉÑ•ÈÉ…¥Í•¥Ì±•…É•½¹”¥ÐÍÑ½ÁÌ‰•¥¹œ(€€€€€€€€€€€€€€€€´´ÑÉÕ”è„‘…äÑ¡…ÐÝ…Ì¥¹½µÁ±•Ñ”°½ÈÝ…ÌÉ½±±•‰…¬°µÕÍÐ¹½Ð(€€€€€€€€€€€€€€€€´´­••ÀÝ…É¹¥¹œ…‰½ÕÐ¥Ð…™Ñ•ÈÑ¡”µ¥ÍÍ¥¹œÁÕ¹ …ÉÉ¥Ù•Ì¸(€€€€€€€€€€€€€€€€´´¹åÑ¡¥¹œ„¡Õµ…¸ÁÕÐÑ¡•É”¥Ì±•™Ð…±½¹”¸(€€€€€€€€€€€€€€€É•Ù¥•Ý}™±…œ€ôM(€€€€€€€€€€€€€€€€€€€]!8…ÑÑ•¹‘…¹•}‘…åÌ¹É•Ù¥•Ý}™±…œ%8€ ü°€ü°€ü°€ü¤Q!8•á±Õ‘•¹É•Ù¥•Ý}™±…œ(€€€€€€€€€€€€€€€€€€€1M=1M¡…ÑÑ•¹‘…¹•}‘…åÌ¹É•Ù¥•Ý}™±…œ°•á±Õ‘•¹É•Ù¥•Ý}™±…œ¤(€€€€€€€€€€€€€€€9°(€€€€€€€€€€€€€€€±…ÍÑ}¥µÁ½ÉÑ}ÉÕ¹}¥€ô=1M¡•á±Õ‘•¹±…ÍÑ}¥µÁ½ÉÑ}ÉÕ¹}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…ÑÑ•¹‘…¹•}‘…åÌ¹±…ÍÑ}¥µÁ½ÉÑ}ÉÕ¹}¥¤(€€€€€€€€€€€€ˆˆˆ°(€€€€€€€€€€€€¡•µÁ±½å••}¥°Ý½É­}‘…Ñ”°ÍÑ…ÑÕÌ°Ñ¥µ•ÍlÁt°(€€€€€€€€€€€€Ñ¥µ•Íl´Åt¥˜±•¸¡Ñ¥µ•Ì¤€ø€Ä•±Í”9½¹”°É•Ù¥•Ý}™±…œ°(€€€€€€€€€€€€¥µÁ½ÉÑ}ÉÕ¹}¥¥˜±…¥µÌ•±Í”9½¹”°€©%5A=IQ}IY%]}1L¤°(€€€€€€€€¤(€€€€€€€ÝÉ¥ÑÑ•¸€¬ô€Ä(€€€É•ÑÕÉ¸ÝÉ¥ÑÑ•¸(((Œ€´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´(ŒÉ½±±‰…¬(Œ€´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´)‘•˜}É½±±‰…­}½¹™±¥ÑÌ (€€€½¹¸èÍÅ±¥Ñ”Ì¹½¹¹•Ñ¥½¸°¥µÁ½ÉÑ}ÉÕ¹}¥è¥¹Ð°™¥¹¥Í¡•‘}…ÐèÍÑÈð9½¹”(¤€´øÑÕÁ±•m±¥ÍÑmÑÕÁ±•m¥¹Ð°ÍÑÉut°±¥ÍÑm¥¹‘¥¹utè(€€€€ˆˆ‰MÁ±¥Ð…™™•Ñ•…ÑÑ•¹‘…¹”É½ÝÌ¥¹Ñ¼€Í…™”Ñ¼É•Ù•ÉÐœ…¹€Ñ½Õ¡•Í¥¹”œ¸((€€€É½Ü¥Ì½¹±äÉ•Ù•ÉÑ•Ý¡•¸Ñ¡¥Ì¥µÁ½ÉÐ¥ÌÑ¡”½¹”Ñ¡…ÐÁÉ½‘Õ•¥Ð…¹(€€€¹½‰½‘ä¡…Ì¡…¹•¥ÐÍ¥¹”¸¹åÑ¡¥¹œ•±Í”¥ÌÉ•Á½ÉÑ•…Ì„½¹™±¥ÐÉ…Ñ¡•È(€€€Ñ¡…¸‰•¥¹œÍ¥±•¹Ñ±ä½Ù•ÉÝÉ¥ÑÑ•¸ƒŠP„É½±±‰…¬µÕÍÐ¹½ÐÕ¹‘¼Í½µ•‰½‘äÌ(€€€µ…¹Õ…°½ÉÉ•Ñ¥½¸¸(€€€€ˆˆˆ(€€€É½ÝÌ€ô½¹¸¹•á•ÕÑ” (€€€€€€€€ˆˆˆ(€€€€€€€M1P%MQ%9P„¹¥°„¹•µÁ±½å••}¥°„¹Ý½É­}‘…Ñ”°„¹½¹™¥Éµ•‘}…Ð°(€€€€€€€€€€€€€€„¹±…ÍÑ}¥µÁ½ÉÑ}ÉÕ¹}¥°„¹Í½ÕÉ”°”¹¹…µ”(€€€€€€€€€I=4ÁÕ¹¡}•Ù•¹ÑÌÀ(€€€€€€€€€)=%8…ÑÑ•¹‘…¹•}‘…åÌ„(€€€€€€€€€€€=8„¹•µÁ±½å••}¥€ôÀ¹•µÁ±½å••}¥9„¹Ý½É­}‘…Ñ”€ôÀ¹Ý½É­}‘…Ñ”(€€€€€€€€€)=%8•µÁ±½å••Ì”=8”¹¥€ô„¹•µÁ±½å••}¥(€€€€€€€€]!IÀ¹…Ñ¥Ù•}¥µÁ½ÉÑ}ÉÕ¹}¥€ô€ü9À¹•µÁ±½å••}¥%L9=P9U10(€€€€€€€€ˆˆˆ°(€€€€€€€€¡¥µÁ½ÉÑ}ÉÕ¹}¥°¤°(€€€€¤¹™•Ñ¡…±° ¤((€€€Í…™”è±¥ÍÑmÑÕÁ±•m¥¹Ð°ÍÑÉut€ômt(€€€½¹™±¥ÑÌè±¥ÍÑm¥¹‘¥¹t€ômt(€€€™½ÈÉ½Ü¥¸É½ÝÌè(€€€€€€€¥˜É½Ýl‰½¹™¥Éµ•‘}…Ð‰tè(€€€€€€€€€€€½¹™±¥ÑÌ¹…ÁÁ•¹¡¥¹‘¥¹œ (€€€€€€€€€€€€€€€€‰É½±±‰…­}½¹™±¥Ðˆ°€‰É•Ù¥•Üˆ°(€€€€€€€€€€€€€€€€‹ªÒ®š³²zCªÂ ƒ¶fW²‚W¶VpƒªÞó¶s²z®.#®.¸ƒ®†“®ÂÇ²vÐƒªÂK²vƒ®Bc®>3®š³²ž ƒ²V+²Vc²*×®.#®.¸ˆ°(€€€€€€€€€€€€€€€Ý½É­}‘…Ñ”õÉ½Ýl‰Ý½É­}‘…Ñ”‰t°•µÁ±½å•”õÉ½Ýl‰¹…µ”‰t°(€€€€€€€€€€€€¤¤(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€¥˜É½Ýl‰±…ÍÑ}¥µÁ½ÉÑ}ÉÕ¹}¥‰t€„ô¥µÁ½ÉÑ}ÉÕ¹}¥è(€€€€€€€€€€€½¹™±¥ÑÌ¹…ÁÁ•¹¡¥¹‘¥¹œ (€€€€€€€€€€€€€€€€‰É½±±‰…­}½¹™±¥Ðˆ°€‰É•Ù¥•Üˆ°(€€€€€€€€€€€€€€€€‹²vÐ¥µÁ½ÉÐƒªÂ ƒ®ž3®N€ƒ¶Z'²vÐƒ²V®.g®.#®.£®.“®–à¥µÁ½ÉÐƒ®bC®*Pƒ²"cªâÀƒ²z®‚”¤¸€ˆ(€€€€€€€€€€€€€€€€‹®†“®ÂÇ²vÐƒªÂK²vƒ®Bc®>3®š³²ž ƒ²V+²Vc²*×®.#®.¸ˆ°(€€€€€€€€€€€€€€€Ý½É­}‘…Ñ”õÉ½Ýl‰Ý½É­}‘…Ñ”‰t°•µÁ±½å•”õÉ½Ýl‰¹…µ”‰t°(€€€€€€€€€€€€¤¤(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€•‘¥Ñ•€ô½¹¸¹•á•ÕÑ” (€€€€€€€€€€€€ˆˆˆ(€€€€€€€€€€€M1P€ÄI=4…Õ‘¥Ñ}±½œ(€€€€€€€€€€€€]!I•¹Ñ¥Ñå}ÑåÁ”€ô€…ÑÑ•¹‘…¹•}‘…åÌœ9•¹Ñ¥Ñå}¥€ô€ü(€€€€€€€€€€€€€€9…Ñ¥½¸€ô€…ÑÑ•¹‘…¹”¹½ÉÉ•Ðœ(€€€€€€€€€€€€€€9€ ü%L9U10=H½ÕÉÉ•‘}…Ð€ø€ü¤(€€€€€€€€€€€€1%5%P€Ä(€€€€€€€€€€€€ˆˆˆ°(€€€€€€€€€€€€¡É½Ýl‰¥‰t°™¥¹¥Í¡•‘}…Ð°™¥¹¥Í¡•‘}…Ð¤°(€€€€€€€€¤¹™•Ñ¡½¹” ¤(€€€€€€€¥˜•‘¥Ñ•è(€€€€€€€€€€€½¹™±¥ÑÌ¹…ÁÁ•¹¡¥¹‘¥¹œ (€€€€€€€€€€€€€€€€‰É½±±‰…­}½¹™±¥Ðˆ°€‰É•Ù¥•Üˆ°(€€€€€€€€€€€€€€€€‰¥µÁ½ÉÐƒ²vÓ¶nƒ²"c®>g²ró®†pƒ²"c²‚W®BpƒªÞó¶s²z®.#®.¸ƒ®†“®ÂÇ²vÐƒªÂK²vƒ®Bc®>3®š³²ž ƒ²V+²Vc²*×®.#®.¸ˆ°(€€€€€€€€€€€€€€€Ý½É­}‘…Ñ”õÉ½Ýl‰Ý½É­}‘…Ñ”‰t°•µÁ±½å•”õÉ½Ýl‰¹…µ”‰t°(€€€€€€€€€€€€¤¤(€€€€€€€€€€€½¹Ñ¥¹Õ”(€€€€€€€Í…™”¹…ÁÁ•¹ ¡É½Ýl‰•µÁ±½å••}¥‰t°É½Ýl‰Ý½É­}‘…Ñ”‰t¤¤(€€€É•ÑÕÉ¸Í…™”°½¹™±¥ÑÌ(()‘•˜É½±±‰…­}¥µÁ½ÉÐ (€€€¥µÁ½ÉÑ}ÉÕ¹}¥è¥¹Ð°(€€€É•…Í½¸èÍÑÈ°(€€€€¨°(€€€‘‰}Á…Ñ èA…Ñ ð9½¹”€ô9½¹”°(€€€…Ñ½É}¥èÍÑÈ€ô€‰½Á•É…Ñ½Èˆ°(¤€´ø‘¥Ðè(€€€€ˆˆ‰U¹‘¼…¸…ÁÁ±¥•¥µÁ½ÉÐÝ¥Ñ¡½ÕÐ‘•±•Ñ¥¹œ„Í¥¹±”É…ÜÁÕ¹ ¸((€€€ƒ
œÈ¸Ð¥Ì…‰Í½±ÕÑ”èÉ…Ü•Ù•¹ÑÌ…É”µ…É­•É½±±•‘}‰…­}…Ð…¹ÍÑ…ä¥¸Ñ¡”(€€€Ñ…‰±”¸•É¥Ù•…ÑÑ•¹‘…¹”¥ÌÉ•½µÁÕÑ•½¹±ä™½ÈÉ½ÝÌÑ¡¥Ì¥µÁ½ÉÐÁÉ½‘Õ•(€€€…¹Ñ¡…Ð¹½‰½‘ä¡…ÌÑ½Õ¡•Í¥¹”ìÑ¡”É•ÍÐ‰•½µ”É½±±‰…­}½¹™±¥Ð(€€€™¥¹‘¥¹Ì™½È„¡Õµ…¸Ñ¼É•Í½±Ù”¸(€€€€ˆˆˆ(€€€¥˜¹½ÐÉ•…Í½¸½È¹½ÐÉ•…Í½¸¹ÍÑÉ¥À ¤è(€€€€€€€É…¥Í”%µÁ½ÉÑÉÉ½É| ‰„É½±±‰…¬µÕÍÐ…ÉÉä„É•…Í½¸™½ÈÑ¡”…Õ‘¥Ð±½œˆ¤((€€€½¹¸€ô‘ˆ¹½¹¹•Ð¡A…Ñ ¡‘‰}Á…Ñ ½È½¹™¥œ¹	}AQ ¤¤(€€€ÑÉäè(€€€€€€€ÉÕ¸€ô½¹¸¹•á•ÕÑ” ‰M1P€¨I=4¥µÁ½ÉÑ}ÉÕ¹Ì]!I¥€ô€üˆ°€¡¥µÁ½ÉÑ}ÉÕ¹}¥°¤¤¹™•Ñ¡½¹” ¤(€€€€€€€¥˜ÉÕ¸¥Ì9½¹”è(€€€€€€€€€€€É…¥Í”%µÁ½ÉÑÉÉ½É|¡˜‰¹¼¥µÁ½ÉÐÉÕ¸í¥µÁ½ÉÑ}ÉÕ¹}¥‘ôˆ¤(€€€€€€€¥˜ÉÕ¹l‰ÍÑ…ÑÕÌ‰t€„ô€‰…ÁÁ±¥•ˆè(€€€€€€€€€€€É…¥Í”%µÁ½ÉÑÉÉ½É| (€€€€€€€€€€€€€€€˜‰¥µÁ½ÉÐÉÕ¸í¥µÁ½ÉÑ}ÉÕ¹}¥‘ô¥Ì€íÉÕ¹lÍÑ…ÑÕÌuôœì½¹±ä…¸…ÁÁ±¥•ÉÕ¸…¸‰”É½±±•‰…¬ˆ(€€€€€€€€€€€€¤(€€€€€€€™É½´…ÁÀ¹Í•ÉÙ¥•Ì¹µ½¹Ñ¡}±½Í”¥µÁ½ÉÐ5½¹Ñ¡±½Í•ÉÉ½È°…ÍÍ•ÉÑ}É…¹•}½Á•¸(€€€€€€€ÑÉäè…ÍÍ•ÉÑ}É…¹•}½Á•¸¡½¹¸°ÉÕ¹l‰Á•É¥½‘}ÍÑ…ÉÐ‰t°ÉÕ¹l‰Á•É¥½‘}•¹‰t¤(€€€€€€€•á•ÁÐ5½¹Ñ¡±½Í•ÉÉ½È…Ì•áŒèÉ…¥Í”%µÁ½ÉÑÉÉ½É|¡ÍÑÈ¡•áŒ¤¤™É½´•áŒ((€€€€€€€Í…™”°½¹™±¥ÑÌ€ô}É½±±‰…­}½¹™±¥ÑÌ¡½¹¸°¥µÁ½ÉÑ}ÉÕ¹}¥°ÉÕ¹l‰™¥¹¥Í¡•‘}…Ð‰t¤((€€€€€€€½¹¸¹•á•ÕÑ” ‰	%8ˆ¤(€€€€€€€€Œ	ä…Ñ¥Ù•}¥µÁ½ÉÑ}ÉÕ¹}¥°¹½Ð¥µÁ½ÉÑ}ÉÕ¹}¥è…¸•Ù•¹Ð™¥ÉÍÐ¥µÁ½ÉÑ•‰ä(€€€€€€€€ŒÉÕ¸€Ä…¹É•…Ñ¥Ù…Ñ•‰äÉÕ¸€Ì¥ÌÉÕ¸€ÌÌÑ¼Õ¹‘¼¸¥µÁ½ÉÑ}ÉÕ¹}¥¥Ì(€€€€€€€€Œ¥µµÕÑ…‰±”ÁÉ½Ù•¹…¹”…¹…¹ÍÝ•ÉÌ„‘¥™™•É•¹ÐÅÕ•ÍÑ¥½¸¸(€€€€€€€µ…É­•€ô½¹¸¹•á•ÕÑ” (€€€€€€€€€€€€‰UAQÁÕ¹¡}•Ù•¹ÑÌMPÉ½±±•‘}‰…­}…Ð€ô€ü°É½±±•‘}‰…­}É•…Í½¸€ô€ü€ˆ(€€€€€€€€€€€€ˆ]!I…Ñ¥Ù•}¥µÁ½ÉÑ}ÉÕ¹}¥€ô€ü9É½±±•‘}‰…­}…Ð%L9U10ˆ°(€€€€€€€€€€€€¡}¹½Ü ¤°É•…Í½¸°¥µÁ½ÉÑ}ÉÕ¹}¥¤°(€€€€€€€€¤¹É½Ý½Õ¹Ð(€€€€€€€É•‘½¹”€ô‘•É¥Ù•}…ÑÑ•¹‘…¹” (€€€€€€€€€€€½¹¸°Í…™”°¥µÁ½ÉÑ}ÉÕ¹}¥õ¥µÁ½ÉÑ}ÉÕ¹}¥°½Ý¹•õÍ•Ð¡Í…™”¤(€€€€€€€€¤((€€€€€€€½¹¸¹•á•ÕÑ” (€€€€€€€€€€€€‰UAQ¥µÁ½ÉÑ}ÉÕ¹ÌMPÍÑ…ÑÕÌ€ô€É½±±•‘}‰…¬œ°É½±±•‘}‰…­}…Ð€ô€ü°€ˆ(€€€€€€€€€€€€ˆ€€€€€€™¥¹‘¥¹Í}©Í½¸€ô€ü]!I¥€ô€üˆ°(€€€€€€€€€€€€¡}¹½Ü ¤°(€€€€€€€€€€€€©Í½¸¹‘ÕµÁÌ¡ì‰É½±±‰…­½¹™±¥ÑÌˆèmŒ¹…Í}‘¥Ð ¤™½ÈŒ¥¸½¹™±¥ÑÍuô°(€€€€€€€€€€€€€€€€€€€€€€€•¹ÍÕÉ•}…Í¥¤õ…±Í”¤°(€€€€€€€€€€€€¥µÁ½ÉÑ}ÉÕ¹}¥¤°(€€€€€€€€¤(€€€€€€€½¹¸¹•á•ÕÑ” (€€€€€€€€€€€€ˆˆˆ(€€€€€€€€€€€%9MIP%9Q<…Õ‘¥Ñ}±½œ€¡…Ñ½É}ÑåÁ”°…Ñ½É}¥°…Ñ¥½¸°•¹Ñ¥Ñå}ÑåÁ”°•¹Ñ¥Ñå}¥°(€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€€…™Ñ•É}©Í½¸°É•…Í½¸¤(€€€€€€€€€€€Y1UL€ ¥µÁ½ÉÐœ°€ü°€¥µÁ½ÉÐ¹É½±±‰…¬œ°€¥µÁ½ÉÑ}ÉÕ¹Ìœ°€ü°€ü°€ü¤(€€€€€€€€€€€€ˆˆˆ°(€€€€€€€€€€€€¡…Ñ½É}¥°¥µÁ½ÉÑ}ÉÕ¹}¥°(€€€€€€€€€€€€©Í½¸¹‘ÕµÁÌ¡ì‰ÁÕ¹¡•Í5…É­•ˆèµ…É­•°€‰…ÑÑ•¹‘…¹•I•‘½¹”ˆèÉ•‘½¹”°(€€€€€€€€€€€€€€€€€€€€€€€€€‰½¹™±¥ÑÌˆè±•¸¡½¹™±¥ÑÌ¥ô°•¹ÍÕÉ•}…Í¥¤õ…±Í”¤°(€€€€€€€€€€€€É•…Í½¸¤°(€€€€€€€€¤(€€€€€€€½¹¸¹½µµ¥Ð ¤(€€€€€€€É•ÑÕÉ¸ì(€€€€€€€€€€€€‰¥µÁ½ÉÑIÕ¹%ˆè¥µÁ½ÉÑ}ÉÕ¹}¥°(€€€€€€€€€€€€‰ÁÕ¹¡•Í5…É­•‘I½±±•‘	…¬ˆèµ…É­•°(€€€€€€€€€€€€‰…ÑÑ•¹‘…¹•I•½µÁÕÑ•ˆèÉ•‘½¹”°(€€€€€€€€€€€€‰ÁÕ¹¡•Í•±•Ñ•ˆè€À°(€€€€€€€€€€€€‰½¹™±¥ÑÌˆèmŒ¹…Í}‘¥Ð ¤™½ÈŒ¥¸½¹™±¥ÑÍt°(€€€€€€€ô(€€€•á•ÁÐá•ÁÑ¥½¸è(€€€€€€€½¹¸¹É½±±‰…¬ ¤(€€€€€€€É…¥Í”(€€€™¥¹…±±äè(€€€€€€€½¹¸¹±½Í” ¤(((Œ€´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´(ŒÉ•…µ½‘•±Ì(Œ(ŒQ¡”A$É•¹‘•ÉÌÑ¡•Í”ì¹½Ñ¡¥¹œÉ”µÅÕ•É¥•Ì¥µÁ½ÉÑ}ÉÕ¹Ì½¸¥ÑÌ½Ý¸¸A¡…Í”€È(Œ•ÍÑ…‰±¥Í¡•Ñ¡”Á…ÑÑ•É¸Ý¥Ñ …ÁÀ½Í•ÉÙ¥•Ì½½ÁÌ¹Áä°Ý¡•É”Ñ¡”A$…¹Ñ¡”‘•µ¼(ŒÍ¹…ÁÍ¡½Ð•áÁ½ÉÑ•ÈÍ¡…É”½¹”Í•Ð½˜É•…µ½‘•±ÌÍ¼Ñ¡”ÑÝ¼É•¹‘•É¥¹Ì…¹¹½Ð(Œ‘É¥™Ð¸Q¡”Í…µ”É•…Í½¸…ÁÁ±¥•ÌÑ¼…¹ä±…Ñ•È¥¹Ñ•É™…”è„Í•½¹…±±•ÈÑ¡…Ð(ŒÝÉ¥Ñ•Ì¥ÑÌ½Ý¸ME0¥Ì„Í•½¹‘•™¥¹¥Ñ¥½¸½˜Ý¡…Ð…¸¥µÁ½ÉÐ€‰¥Ìˆ¸(Œ€´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´´)‘•˜¥µÁ½ÉÑ}¡¥ÍÑ½Éä¡½¹¸èÍÅ±¥Ñ”Ì¹½¹¹•Ñ¥½¸°±¥µ¥Ðè¥¹Ð€ô€ÔÀ¤€´ø±¥ÍÑm‘¥Ñtè(€€€É½ÝÌ€ô½¹¸¹•á•ÕÑ” (€€€€€€€€ˆˆˆ(€€€€€€€M1PÈ¹¥°È¹Í½ÕÉ•}™¥±•¹…µ”°È¹ÍÑ…ÑÕÌ°È¹Á•É¥½‘}ÍÑ…ÉÐ°È¹Á•É¥½‘}•¹°(€€€€€€€€€€€€€€È¹ÁÕ¹¡}•Ù•¹Ñ}½Õ¹Ð°È¹ÍÑ…ÉÑ•‘}…Ð°È¹™¥¹¥Í¡•‘}…Ð°È¹É½±±•‘}‰…­}…Ð°(€€€€€€€€€€€€€€È¹•ÉÉ½É}µ•ÍÍ…”°(€€€€€€€€€€€€€€€¡M1P=U9P ¨¤I=4¥µÁ½ÉÑ}ÉÕ¹}‘…åÌ]!I¹¥µÁ½ÉÑ}ÉÕ¹}¥€ôÈ¹¥¤(€€€€€€€€€€€€€€€€€€L½Ù•É•‘}‘…åÌ(€€€€€€€€€I=4¥µÁ½ÉÑ}ÉÕ¹ÌÈ(€€€€€€€€]!IÈ¹Í½ÕÉ•}­¥¹€ô€™¥¹•ÉÁÉ¥¹Ñ}á±Ìœ(€€€€€€€€=IH	dÈ¹¥M1%5%P€ü(€€€€€€€€ˆˆˆ°(€€€€€€€€¡µ…à Ä°µ¥¸¡±¥µ¥Ð°€ÈÀÀ¤¤°¤°(€€€€¤¹™•Ñ¡…±° ¤(€€€É•ÑÕÉ¸l(€€€€€€€ì(€€€€€€€€€€€€‰¥ˆèÉ½Ýl‰¥‰t°(€€€€€€€€€€€€‰Í½ÕÉ•¥±•¹…µ”ˆèÉ½Ýl‰Í½ÕÉ•}™¥±•¹…µ”‰t°(€€€€€€€€€€€€‰ÍÑ…ÑÕÌˆèÉ½Ýl‰ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€‰Á•É¥½‘MÑ…ÉÐˆèÉ½Ýl‰Á•É¥½‘}ÍÑ…ÉÐ‰t°(€€€€€€€€€€€€‰Á•É¥½‘¹ˆèÉ½Ýl‰Á•É¥½‘}•¹‰t°(€€€€€€€€€€€€‰ÁÕ¹¡Ù•¹Ñ½Õ¹ÐˆèÉ½Ýl‰ÁÕ¹¡}•Ù•¹Ñ}½Õ¹Ð‰t°(€€€€€€€€€€€€‰ÍÑ…ÉÑ•‘ÐˆèÉ½Ýl‰ÍÑ…ÉÑ•‘}…Ð‰t°(€€€€€€€€€€€€‰™¥¹¥Í¡•‘ÐˆèÉ½Ýl‰™¥¹¥Í¡•‘}…Ð‰t°(€€€€€€€€€€€€‰É½±±•‘	…­ÐˆèÉ½Ýl‰É½±±•‘}‰…­}…Ð‰t°(€€€€€€€€€€€€‰•ÉÉ½É5•ÍÍ…”ˆèÉ½Ýl‰•ÉÉ½É}µ•ÍÍ…”‰t°(€€€€€€€€€€€€‰½Ù•É•‘…åÌˆèÉ½Ýl‰½Ù•É•‘}‘…åÌ‰t°(€€€€€€€ô(€€€€€€€™½ÈÉ½Ü¥¸É½ÝÌ(€€€t(()‘•˜¥µÁ½ÉÑ}ÉÕ¹}‘•Ñ…¥°¡½¹¸èÍÅ±¥Ñ”Ì¹½¹¹•Ñ¥½¸°ÉÕ¹}¥è¥¹Ð¤€´ø‘¥Ðð9½¹”è(€€€É½Ü€ô½¹¸¹•á•ÕÑ” ‰M1P€¨I=4¥µÁ½ÉÑ}ÉÕ¹Ì]!I¥€ô€üˆ°€¡ÉÕ¹}¥°¤¤¹™•Ñ¡½¹” ¤(€€€¥˜É½Ü¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸9½¹”(€€€‘…åÌ€ô½¹¸¹•á•ÕÑ” (€€€€€€€€‰M1PÝ½É­}‘…Ñ”°½Ù•É…•}ÍÑ…ÑÕÌ°É…Ý}ÁÕ¹¡}½Õ¹ÐI=4¥µÁ½ÉÑ}ÉÕ¹}‘…åÌ€ˆ(€€€€€€€€ˆ]!I¥µÁ½ÉÑ}ÉÕ¹}¥€ô€ü=IH	dÝ½É­}‘…Ñ”ˆ°(€€€€€€€€¡ÉÕ¹}¥°¤°(€€€€¤¹™•Ñ¡…±° ¤(€€€™¥¹‘¥¹Ìè±¥ÍÑm‘¥Ñt€ômt(€€€¥˜É½Ýl‰™¥¹‘¥¹Í}©Í½¸‰tè(€€€€€€€ÑÉäè(€€€€€€€€€€€™¥¹‘¥¹Ì€ô©Í½¸¹±½…‘Ì¡É½Ýl‰™¥¹‘¥¹Í}©Í½¸‰t¤¹•Ð ‰™¥¹‘¥¹Ìˆ°mt¤(€€€€€€€•á•ÁÐY…±Õ•ÉÉ½Èè€€ŒÁÉ…µ„è¹¼½Ù•È€´‘•™•¹Í¥Ù”(€€€€€€€€€€€™¥¹‘¥¹Ì€ômt(€€€É•ÑÕÉ¸ì(€€€€€€€€‰¥ˆèÉ½Ýl‰¥‰t°(€€€€€€€€‰Í½ÕÉ•¥±•¹…µ”ˆèÉ½Ýl‰Í½ÕÉ•}™¥±•¹…µ”‰t°(€€€€€€€€‰ÍÑ…ÑÕÌˆèÉ½Ýl‰ÍÑ…ÑÕÌ‰t°(€€€€€€€€‰Á•É¥½‘MÑ…ÉÐˆèÉ½Ýl‰Á•É¥½‘}ÍÑ…ÉÐ‰t°(€€€€€€€€‰Á•É¥½‘¹ˆèÉ½Ýl‰Á•É¥½‘}•¹‰t°(€€€€€€€€‰ÁÕ¹¡Ù•¹Ñ½Õ¹ÐˆèÉ½Ýl‰ÁÕ¹¡}•Ù•¹Ñ}½Õ¹Ð‰t°(€€€€€€€€‰ÍÑ…ÉÑ•‘ÐˆèÉ½Ýl‰ÍÑ…ÉÑ•‘}…Ð‰t°(€€€€€€€€‰™¥¹¥Í¡•‘ÐˆèÉ½Ýl‰™¥¹¥Í¡•‘}…Ð‰t°(€€€€€€€€‰É½±±•‘	…­ÐˆèÉ½Ýl‰É½±±•‘}‰…­}…Ð‰t°(€€€€€€€€‰•ÉÉ½É5•ÍÍ…”ˆèÉ½Ýl‰•ÉÉ½É}µ•ÍÍ…”‰t°(€€€€€€€€‰½Ù•É•‘…åÌˆè±•¸¡‘…åÌ¤°(€€€€€€€€‰Í½ÕÉ•M¡„ÈÔØˆèÉ½Ýl‰Í½ÕÉ•}Í¡„ÈÔØ‰t°(€€€€€€€€‰™¥¹‘¥¹Ìˆè™¥¹‘¥¹Ì°(€€€€€€€€Œ½Ù•É…”™…ÑÌ°­•ÁÐ…Á…ÉÐ™É½´…¹ä…ÑÑ•¹‘…¹”Ù•É‘¥Ðè„(€€€€€€€€ŒÉ•Á½ÉÑ•‘}é•É¼‘…ä¥ÌÝ¡…ÐÑ¡”™¥±”Í…¥°¹½Ð…¸…‰Í•¹”¸(€€€€€€€€‰‘…åÌˆèl(€€€€€€€€€€€ì(€€€€€€€€€€€€€€€€‰Ý½É­…Ñ”ˆè‘…ål‰Ý½É­}‘…Ñ”‰t°(€€€€€€€€€€€€€€€€‰½Ù•É…”ˆè‘…ål‰½Ù•É…•}ÍÑ…ÑÕÌ‰t°(€€€€€€€€€€€€€€€€‰ÁÕ¹¡•Ìˆè‘…ål‰É…Ý}ÁÕ¹¡}½Õ¹Ð‰t°(€€€€€€€€€€€ô(€€€€€€€€€€€™½È‘…ä¥¸‘…åÌ(€€€€€€€t°(€€€ô(()‘•˜ÍÑ½É•‘}ÁÉ•Ù¥•Ü¡½¹¸èÍÅ±¥Ñ”Ì¹½¹¹•Ñ¥½¸°ÉÕ¹}¥è¥¹Ð¤€´ø‘¥Ðð9½¹”è(€€€€ˆˆ‰Q¡”ÁÉ•Ù¥•ÜÍ¹…ÁÍ¡½Ð…ÌÑ¡”½Á•É…Ñ½ÈÝ½Õ±¡…Ù”Í••¸¥Ð¸((€€€I•ÑÕÉ¹Ì9½¹”Ý¡•¸Ñ¡”ÉÕ¸¡…Ì¹½¹”ƒŠP„ÉÕ¸Ñ¡…Ð™…¥±•Ñ¼Á…ÉÍ”°½È½¹”(€€€…±É•…‘ä…ÁÁ±¥•¸ÁÁ±å¥¹œ¹•Ù•ÈÑÉÕÍÑÌÑ¡¥Ìè¥ÐÉ”µÉ•…‘ÌÑ¡”ÁÉ•Í•ÉÙ•™¥±”(€€€…¹É•½µÁÕÑ•Ì……¥¹ÍÐÑ¡”ÕÉÉ•¹ÐÍ±½Ðµ…ÁÁ¥¹œ¸(€€€€ˆˆˆ(€€€É½Ü€ô½¹¸¹•á•ÕÑ” (€€€€€€€€‰M1PÁÉ•Ù¥•Ý}©Í½¸I=4¥µÁ½ÉÑ}ÉÕ¹Ì]!I¥€ô€üˆ°€¡ÉÕ¹}¥°¤(€€€€¤¹™•Ñ¡½¹” ¤(€€€¥˜É½Ü¥Ì9½¹”½È¹½ÐÉ½Ýl‰ÁÉ•Ù¥•Ý}©Í½¸‰tè(€€€€€€€É•ÑÕÉ¸9½¹”(€€€É•ÑÕÉ¸©Í½¸¹±½…‘Ì¡É½Ýl‰ÁÉ•Ù¥•Ý}©Í½¸‰t¤(()‘•˜ÁÉ•Í•ÉÙ•‘}Í½ÕÉ”¡½¹¸èÍÅ±¥Ñ”Ì¹½¹¹•Ñ¥½¸°ÉÕ¹}¥è¥¹Ð¤€´ø‘¥Ðð9½¹”è(€€€€ˆˆ‰]¡•É”Ñ¡”Õ¹Ñ½Õ¡•½É¥¥¹…°¥Ì­•ÁÐ¸((€€€Q¡”Á…Ñ °¹½ÐÑ¡”‰åÑ•ÌèÑ¡”™¥±”ÍÑ…åÌ½¸Ñ¡”Ý½É¬AÌ‘¥Í¬…¹¥Ì¹•Ù•È(€€€Í•ÉÙ•Ñ¼„…±±•È¸(€€€€ˆˆˆ(€€€É½Ü€ô½¹¸¹•á•ÕÑ” (€€€€€€€€‰M1PÍÑ½É•‘}Í½ÕÉ•}Á…Ñ °Í½ÕÉ•}™¥±•¹…µ”°Í½ÕÉ•}Í¡„ÈÔØ€ˆ(€€€€€€€€ˆ€I=4¥µÁ½ÉÑ}ÉÕ¹Ì]!I¥€ô€üˆ°(€€€€€€€€¡ÉÕ¹}¥°¤°(€€€€¤¹™•Ñ¡½¹” ¤(€€€¥˜É½Ü¥Ì9½¹”è(€€€€€€€É•ÑÕÉ¸9½¹”(€€€ÍÑ½É•€ôA…Ñ ¡É½Ýl‰ÍÑ½É•‘}Í½ÕÉ•}Á…Ñ ‰t½È€ˆˆ¤(€€€É•ÑÕÉ¸ì(€€€€€€€€‰Í½ÕÉ•¥±•¹…µ”ˆèÉ½Ýl‰Í½ÕÉ•}™¥±•¹…µ”‰t°(€€€€€€€€‰ÍÑ½É•‘A…Ñ ˆèÍÑÈ¡ÍÑ½É•¤°(€€€€€€€€‰•á¥ÍÑÌˆèÍÑ½É•¹¥Í}™¥±” ¤°(€€€€€€€€‰Í¡„ÈÔØˆèÉ½Ýl‰Í½ÕÉ•}Í¡„ÈÔØ‰t°(€€€ô(()‘•˜Á•¹‘¥¹}¥µÁ½ÉÑÌ¡½¹¸èÍÅ±¥Ñ”Ì¹½¹¹•Ñ¥½¸¤€´ø±¥ÍÑm‘¥Ñtè(€€€€ˆˆ‰AÉ•Ù¥•Ý•¥µÁ½ÉÑÌÝ…¥Ñ¥¹œ™½ÈÍ½µ•‰½‘äÑ¼½¹™¥É´½È‘¥Í…ÉÑ¡•´¸ˆˆˆ(€€€É½ÝÌ€ô½¹¸¹•á•ÕÑ” (€€€€€€€€ˆˆˆ(€€€€€€€M1P¥°Í½ÕÉ•}™¥±•¹…µ”°Á•É¥½‘}ÍÑ…ÉÐ°Á•É¥½‘}•¹°ÍÑ…ÉÑ•‘}…Ð°(€€€€€€€€€€€€€€‘¥Í½Ù•É•‘}‰ä°ÁÉ•Ù¥•Ý}©Í½¸(€€€€€€€€€I=4¥µÁ½ÉÑ}ÉÕ¹Ì(€€€€€€€€]!IÍÑ…ÑÕÌ€ô€ÁÉ•Ù¥•Ý•œ9Í½ÕÉ•}­¥¹€ô€™¥¹•ÉÁÉ¥¹Ñ}á±Ìœ(€€€€€€€€=IH	d¥M(€€€€€€€€ˆˆˆ(€€€€¤¹™•Ñ¡…±° ¤(€€€½ÕÐ€ômt(€€€™½ÈÉ½Ü¥¸É½ÝÌè(€€€€€€€¹•Ý}ÁÕ¹¡•Ì€ô9½¹”(€€€€€€€ÍÑ…Ñ”€ô€‹ªÊ¶€ƒ¶V²jPˆ(€€€€€€€¥˜É½Ýl‰ÁÉ•Ù¥•Ý}©Í½¸‰tè(€€€€€€€€€€€ÑÉäè(€€€€€€€€€€€€€€€Í…Ù•€ô©Í½¸¹±½…‘Ì¡É½Ýl‰ÁÉ•Ù¥•Ý}©Í½¸‰t¤(€€€€€€€€€€€€€€€¹•Ý}ÁÕ¹¡•Ì€ôÍ…Ù•¹•Ð ‰¹•ÝAÕ¹¡•Ìˆ¤(€€€€€€€€€€€€€€€¥˜…¹ä¡Ì¹•Ð ‰ÍÑ…ÑÕÌˆ¤€ôô€‰Õ¹µ…ÁÁ•ˆ…¹Ì¹•Ð ‰ÁÕ¹¡½Õ¹Ðˆ°€À¤€ø€À™½ÈÌ¥¸Í…Ù•¹•Ð ‰Í±½ÑÌˆ°mt¤¤è(€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”€ô€‹²ž²n@ƒ²^ÃªÊÀƒ¶V²jPˆ(€€€€€€€€€€€€€€€•±¥˜Í…Ù•¹•Ð ‰…¹ÁÁ±äˆ¤è(€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”€ô€‹®Âc²bƒªÂ®*”ˆ(€€€€€€€€€€€€€€€•±¥˜¹½Ð¹•Ý}ÁÕ¹¡•Ì…¹¹½ÐÍ…Ù•¹•Ð ‰É•…Ñ¥Ù…Ñ…‰±•AÕ¹¡•Ìˆ¤è(€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”€ô€‹²vÓ®¾àƒªÂ²‚ã²b ƒ¶23²vðˆ(€€€€€€€€€€€€€€€•±Í”è(€€€€€€€€€€€€€€€€€€€ÍÑ…Ñ”€ô€‹²Â£®.£®B ˆ(€€€€€€€€€€€•á•ÁÐY…±Õ•ÉÉ½Èè€€ŒÁÉ…µ„è¹¼½Ù•È€´‘•™•¹Í¥Ù”(€€€€€€€€€€€€€€€¹•Ý}ÁÕ¹¡•Ì€ô9½¹”(€€€€€€€½ÕÐ¹…ÁÁ•¹¡ì(€€€€€€€€€€€€‰¥µÁ½ÉÑIÕ¹%ˆèÉ½Ýl‰¥‰t°(€€€€€€€€€€€€‰Í½ÕÉ•¥±•¹…µ”ˆèÉ½Ýl‰Í½ÕÉ•}™¥±•¹…µ”‰t°(€€€€€€€€€€€€‰Á•É¥½‘MÑ…ÉÐˆèÉ½Ýl‰Á•É¥½‘}ÍÑ…ÉÐ‰t°(€€€€€€€€€€€€‰Á•É¥½‘¹ˆèÉ½Ýl‰Á•É¥½‘}•¹‰t°(€€€€€€€€€€€€‰ÍÑ…ÉÑ•‘ÐˆèÉ½Ýl‰ÍÑ…ÉÑ•‘}…Ð‰t°(€€€€€€€€€€€€‰‘¥Í½Ù•É•‘	äˆèÉ½Ýl‰‘¥Í½Ù•É•‘}‰ä‰t°(€€€€€€€€€€€€‰¹•ÝAÕ¹¡•Ìˆè¹•Ý}ÁÕ¹¡•Ì°(€€€€€€€€€€€€‰ÍÑ…Ñ”ˆèÍÑ…Ñ”°(€€€€€€€ô¤(€€€É•ÑÕÉ¸½ÕÐ(()‘•˜±…ÍÑ}…ÁÁ±¥•‘}¥µÁ½ÉÐ¡½¹¸èÍÅ±¥Ñ”Ì¹½¹¹•Ñ¥½¸¤€´ø‘¥Ðð9½¹”è(€€€É½Ü€ô½¹¸¹•á•ÕÑ” (€€€€€€€€‰M1P¥°Í½ÕÉ•}™¥±•¹…µ”°Á•É¥½‘}ÍÑ…ÉÐ°Á•É¥½‘}•¹°™¥¹¥Í¡•‘}…Ð°ÁÕ¹¡}•Ù•¹Ñ}½Õ¹Ð€ˆ(€€€€€€€€ˆ€I=4¥µÁ½ÉÑ}ÉÕ¹Ì]!IÍÑ…ÑÕÌ€ô€…ÁÁ±¥•œ9Í½ÕÉ•}­¥¹€ô€™¥¹•ÉÁÉ¥¹Ñ}á±Ìœ€ˆ(€€€€€€€€ˆ=IH	d=1M¡™¥¹¥Í¡•‘}…Ð°ÕÁ‘…Ñ•‘}…Ð¤M°¥M1%5%P€Äˆ(€€€€¤¹™•Ñ¡½¹” ¤(€€€É•ÑÕÉ¸‘¥Ð¡É½Ü¤¥˜É½Ü•±Í”9½¹”(