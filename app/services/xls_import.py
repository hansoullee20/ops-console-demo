"""Parse the fingerprint terminal's monthly `.XLS` export.

The real export is a genuine OLE2/BIFF8 workbook (not CSV or HTML with an .xls
name), so it needs `xlrd` 1.x — xlrd 2.x dropped .xls support entirely. The
dependency is optional at import time: a host without it gets a clear error
instead of a crash on start-up.

Layout, from a real 2026-07 export:

    sheet "근태기록"          the raw record, and the only thing parsed here
      row 2                 period, e.g. "출근 일자" | "2026/07/01 ~ 07/31"
      then repeating 3-row blocks, one per registered terminal slot:
        +0  day-number header      1.0  2.0  3.0 ... 31.0
        +1  metadata               "사원번호" <slot>  …  "성명" <name>
        +2  punches per day        "07:26\\n07:36\\n16:00\\n"

    sheets "1.2.3", "4.5.6", …   per-slot cards the terminal derives itself

WHAT IS DELIBERATELY NOT READ
-----------------------------
The per-slot card sheets carry the terminal's own verdicts (결근 / 출근일수 /
지각 / 조퇴 …). Those are never imported. In the sample export, every one of the
19 registered-but-unused slots is marked 결근 on all 31 days — weekends
included. Trusting that would have manufactured 589 absences out of nothing.
This module reads raw punch times only; attendance is derived separately, and a
day with no punches stays unknown rather than becoming an absence
(AI_BUILD_PLAN.md §2.14, §3).

Two more properties of the real data shape the model here:

* The same timestamp legitimately repeats inside one cell — the sample contains
  06:40 three times in a single day. Every occurrence is preserved and gets its
  own ordinal, because §2.4 forbids dropping a punch for looking like a
  duplicate. The ordinal counts *repeats of that value*, not position in the
  cell: a later re-export that adds a missing 06:50 must not renumber the
  07:00 that was already imported.
* There are no 출/외/퇴/복 markers anywhere in the workbook; the terminal emits
  bare times. Imported events therefore carry punch_type 'unknown' rather than
  a guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RAW_SHEET_NAME = "근태기록"
SLOT_LABEL = "사원번호"
NAME_LABEL = "성명"
PERIOD_LABEL = "출근 일자"

TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
PERIOD_RE = re.compile(
    r"(\d{4})/(\d{1,2})/(\d{1,2})\s*~\s*(?:(\d{4})/)?(\d{1,2})/(\d{1,2})"
)


class XlsImportError(RuntimeError):
    """The workbook could not be read as a terminal export."""


class XlsDependencyMissing(XlsImportError):
    """xlrd 1.x is not installed on this host."""


def _column_letters(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA — spreadsheet column naming."""
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


@dataclass(frozen=True)
class ParsedPunch:
    """One punch *occurrence*, not one spreadsheet row.

    The export packs a whole day into a single cell, so several occurrences
    share one row, column and cell address. `cell_position` says where in that
    cell this one sat; `occurrence_index` distinguishes genuine repeats of the
    same time and is the part that belongs in the identity.
    """

    slot_code: str
    work_date: str          # ISO
    punch_time: str         # HH:MM
    punch_type: str         # this terminal emits none, so 'unknown'
    # How many punches with this exact value came before it on this day. It is
    # 0 unless the same time repeats, and it is the only part of the identity
    # that distinguishes those repeats. NOT the position in the cell — see
    # migration 0006 for why that was wrong.
    occurrence_index: int
    cell_position: int      # 0-based position inside that day's cell; provenance only
    raw_cell: str
    source_sheet: str
    source_row: int         # 0-based row in the sheet
    source_column: int      # 0-based column in the sheet

    @property
    def punch_at(self) -> str:
        return f"{self.work_date}T{self.punch_time}:00"

    @property
    def source_cell(self) -> str:
        return f"{_column_letters(self.source_column)}{self.source_row + 1}"


@dataclass
class ParsedSlot:
    slot_code: str
    display_name: str | None
    punch_count: int = 0
    day_count: int = 0


@dataclass
class ParsedWorkbook:
    source_filename: str
    period_start: str
    period_end: str
    slots: list[ParsedSlot] = field(default_factory=list)
    punches: list[ParsedPunch] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Dates the source actually carried a column for. A date here with no
    # punches is "the file said nothing happened"; a date missing from here was
    # never covered by this import at all. Conflating the two is how a quiet
    # day becomes a roomful of absences.
    covered_dates: list[str] = field(default_factory=list)

    @property
    def active_slots(self) -> list[ParsedSlot]:
        return [s for s in self.slots if s.punch_count]

    @property
    def dates(self) -> list[str]:
        return sorted({p.work_date for p in self.punches})


def _require_xlrd():
    try:
        import xlrd  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on host
        raise XlsDependencyMissing(
            "reading the terminal's .XLS export needs xlrd 1.x "
            "(xlrd 2.x removed .xls support). Install it with:\n"
            "    pip install 'xlrd==1.2.0'"
        ) from exc
    version = getattr(xlrd, "__version__", "0")
    if int(str(version).split(".")[0]) >= 2:  # pragma: no cover - depends on host
        raise XlsDependencyMissing(
            f"xlrd {version} cannot read .xls files; pin 'xlrd==1.2.0'"
        )
    return xlrd


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _value_after(row: list[Any], label: str) -> str | None:
    """The first non-empty cell following `label` on the same row.

    Reading by label rather than by fixed column index, so a small layout shift
    in a future export does not silently pick up the wrong field.
    """
    for index, cell in enumerate(row):
        if _text(cell) == label:
            for candidate in row[index + 1:]:
                text = _text(candidate)
                if text:
                    return text
            return None
    return None


def _parse_period(text: str, warnings: list[str]) -> tuple[str, str]:
    match = PERIOD_RE.search(text or "")
    if not match:
        raise XlsImportError(f"could not read the export period from {text!r}")
    year, month, day, end_year, end_month, end_day = match.groups()
    end_year = end_year or year
    return (
        f"{int(year):04d}-{int(month):02d}-{int(day):02d}",
        f"{int(end_year):04d}-{int(end_month):02d}-{int(end_day):02d}",
    )


def _day_columns(row: list[Any]) -> dict[int, int]:
    """column index -> day of month, from a `1.0 2.0 3.0 …` header row."""
    mapping: dict[int, int] = {}
    for index, cell in enumerate(row):
        text = _text(cell)
        if text.isdigit() and 1 <= int(text) <= 31:
            mapping[index] = int(text)
    return mapping


def parse_workbook(path: Path | str, *, source_filename: str | None = None) -> ParsedWorkbook:
    """Read raw punches out of a terminal export. Touches no database."""
    xlrd = _require_xlrd()
    path = Path(path)
    try:
        book = xlrd.open_workbook(str(path))
    except Exception as exc:
        raise XlsImportError(f"not a readable .xls workbook: {exc}") from exc

    if RAW_SHEET_NAME not in book.sheet_names():
        raise XlsImportError(
            f"sheet {RAW_SHEET_NAME!r} not found; this does not look like a "
            f"terminal export (sheets: {', '.join(book.sheet_names())})"
        )
    sheet = book.sheet_by_name(RAW_SHEET_NAME)
    rows = [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]

    warnings: list[str] = []

    period_row = next(
        (row for row in rows[:10] if any(_text(cell) == PERIOD_LABEL for cell in row)), None
    )
    if period_row is None:
        raise XlsImportError(f"could not find the {PERIOD_LABEL!r} row")
    period_text = _value_after(period_row, PERIOD_LABEL) or ""
    period_start, period_end = _parse_period(period_text, warnings)
    year, month = int(period_start[:4]), int(period_start[5:7])

    result = ParsedWorkbook(
        source_filename=source_filename or path.name,
        period_start=period_start,
        period_end=period_end,
        warnings=warnings,
    )

    index = rows.index(period_row) + 1
    seen_slots: set[str] = set()
    covered: set[str] = set()
    while index + 2 < len(rows) + 1:
        header = rows[index] if index < len(rows) else None
        if header is None:
            break
        day_columns = _day_columns(header)
        if not day_columns:
            index += 1
            continue
        for day in day_columns.values():
            covered.add(f"{year:04d}-{month:02d}-{day:02d}")
        if index + 1 >= len(rows):
            warnings.append(f"row {index}: day header with no metadata row after it")
            break

        meta = rows[index + 1]
        slot_code = _value_after(meta, SLOT_LABEL)
        display_name = _value_after(meta, NAME_LABEL)
        if not slot_code:
            warnings.append(f"row {index + 1}: block without a {SLOT_LABEL}; skipped")
            index += 3
            continue
        if slot_code in seen_slots:
            warnings.append(f"slot {slot_code} appears more than once; later block skipped")
            index += 3
            continue
        seen_slots.add(slot_code)

        slot = ParsedSlot(slot_code=slot_code, display_name=display_name or None)
        punch_row = rows[index + 2] if index + 2 < len(rows) else []
        days_with_punches = 0
        for column, day in day_columns.items():
            raw = _text(punch_row[column]) if column < len(punch_row) else ""
            if not raw:
                continue
            times = [t for t in (part.strip() for part in raw.splitlines()) if t]
            valid: list[str] = []
            for token in times:
                match = TIME_RE.match(token)
                if not match:
                    warnings.append(
                        f"slot {slot_code} day {day}: unreadable time {token!r}; kept out of the import"
                    )
                    continue
                hour, minute = int(match.group(1)), int(match.group(2))
                if hour > 23 or minute > 59:
                    warnings.append(f"slot {slot_code} day {day}: impossible time {token!r}")
                    continue
                valid.append(f"{hour:02d}:{minute:02d}")
            if not valid:
                continue
            days_with_punches += 1
            work_date = f"{year:04d}-{month:02d}-{day:02d}"
            repeats: dict[str, int] = {}
            for position, punch_time in enumerate(valid):
                # Every occurrence is kept, including exact repeats of the same
                # timestamp: the sample export has 06:40 three times in one day,
                # and §2.4 forbids dropping a punch for looking duplicated.
                # The ordinal counts repeats of this value only, so inserting an
                # earlier punch in a later re-export does not renumber the rest.
                occurrence = repeats.get(punch_time, 0)
                repeats[punch_time] = occurrence + 1
                result.punches.append(
                    ParsedPunch(
                        slot_code=slot_code,
                        work_date=work_date,
                        punch_time=punch_time,
                        punch_type="unknown",
                        occurrence_index=occurrence,
                        cell_position=position,
                        raw_cell=raw,
                        source_sheet=RAW_SHEET_NAME,
                        source_row=index + 2,
                        source_column=column,
                    )
                )
                slot.punch_count += 1
        slot.day_count = days_with_punches
        result.slots.append(slot)
        index += 3

    if not result.slots:
        raise XlsImportError("no slot blocks found in 근태기록")
    result.covered_dates = sorted(covered)
    return result


def dedupe_key(terminal_id: str, punch: ParsedPunch) -> str:
    """Stable identity for one raw punch, used to make reimport idempotent.

    Definition: terminal + slot + work_date + punch_at + punch_type, plus an
    occurrence ordinal when the same value repeats.

    The ordinal is part of the key on purpose. Without it, a day containing the
    same timestamp twice collides on the unique index and one of the two raw
    events is silently refused — 12 real punches in one sample month.

    It counts repeats of that value and nothing else. It used to be the punch's
    position in the cell, which meant a re-export containing one extra earlier
    punch renumbered every later punch and re-imported all of them as new
    (migration 0006). Neither the cell address nor the row number belongs in the
    key either: both are provenance, and both move when a file is re-exported.
    """
    return (
        f"{terminal_id}|{punch.slot_code}|{punch.work_date}"
        f"|{punch.punch_time}|{punch.punch_type}|{punch.occurrence_index}"
    )
