"""Build fingerprint-terminal `.XLS` exports from fictional data.

The layout mirrors a real 2026-07 export exactly — same sheet name, same
period row, same repeating 3-row blocks, same newline-separated punch cells —
so the parser is exercised against the real shape without the real file, which
contains employee names and is never committed.

Everything produced here is invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SlotSpec:
    """One registered terminal slot and its month of punches."""

    slot_code: str
    display_name: str
    # day of month -> list of "HH:MM" strings, in the order the terminal wrote them
    punches: dict[int, list[str]] = field(default_factory=dict)


def build_export(
    path: Path | str,
    *,
    year: int = 2026,
    month: int = 7,
    days_in_month: int = 31,
    slots: list[SlotSpec],
    include_derived_card_sheets: bool = True,
) -> Path:
    """Write a workbook shaped like the terminal's monthly export."""
    import xlwt

    path = Path(path)
    book = xlwt.Workbook(encoding="utf-8")
    sheet = book.add_sheet("근태기록")

    sheet.write(0, 0, "근태기록표")
    sheet.write(2, 0, "출근 일자")
    sheet.write(2, 2, f"{year:04d}/{month:02d}/01 ~ {month:02d}/{days_in_month:02d}")

    row = 3
    for slot in slots:
        for column in range(days_in_month):
            sheet.write(row, column, float(column + 1))
        sheet.write(row + 1, 0, "사원번호")
        sheet.write(row + 1, 2, slot.slot_code)
        sheet.write(row + 1, 8, "성명")
        sheet.write(row + 1, 10, slot.display_name)
        for day, times in slot.punches.items():
            if not times:
                continue
            sheet.write(row + 2, day - 1, "".join(f"{t}\n" for t in times))
        row += 3

    if include_derived_card_sheets:
        # The terminal also emits per-slot cards carrying its own verdicts. They
        # exist here so tests can prove the importer ignores them: an unused
        # slot is marked 결근 on every day, weekends included.
        for index in range(0, len(slots), 3):
            group = slots[index: index + 3]
            card = book.add_sheet(".".join(s.slot_code for s in group))
            card.write(0, 0, "출퇴근카드")
            card.write(1, 0, "출근 일자")
            card.write(1, 3, f"{year:04d}/{month:02d}/01")
            card.write(9, 0, "일자/주")
            card.write(9, 1, "출퇴근")
            card.write(10, 1, "출근")
            card.write(10, 3, "퇴근")
            for day in range(1, days_in_month + 1):
                card.write(10 + day, 0, f"{day:02d}")
                card.write(10 + day, 6, "결근")

    path.parent.mkdir(parents=True, exist_ok=True)
    book.save(str(path))
    return path


def realistic_month() -> list[SlotSpec]:
    """A month with every situation the real export contains.

    Modelled on the shape of a real export: many more registered slots than
    active people, exact repeated timestamps, near-simultaneous punches,
    odd punch counts, and whole-site quiet days.
    """
    slots = [
        # ordinary two-punch days
        SlotSpec("001", "가상민", {1: ["07:24", "16:01"], 2: ["07:22", "16:00"], 3: ["07:25", "16:02"]}),
        # three punches, two of them 10 minutes apart -> repeated-punch candidate
        SlotSpec("002", "나윤슬", {1: ["07:26", "07:36", "16:00"], 2: ["07:27", "16:00"]}),
        # the same timestamp recorded twice in one day
        SlotSpec("003", "다온결", {1: ["07:24", "07:24", "16:01"], 2: ["07:27", "16:03", "16:03"]}),
        # the same timestamp three times, plus a fourth punch
        SlotSpec("004", "라온제", {1: ["06:40", "06:40", "06:40", "16:11"]}),
        # a single punch for the day: arrival with no departure
        SlotSpec("005", "마루한", {1: ["07:30"], 2: ["07:31", "16:04"]}),
        # five punches in one day
        SlotSpec("006", "바다솔", {2: ["06:49", "06:50", "16:06", "16:07", "16:07"]}),
        # registered but never used all month — the terminal still calls it 결근
        SlotSpec("007", "사라진", {}),
        SlotSpec("008", "아직도", {}),
    ]
    return slots
