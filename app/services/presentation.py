"""Turn stored facts back into the labels the existing UI renders.

The database stores what happened; it does not store Korean display strings.
This module is the single place that maps facts -> presentation, and it is used
by both the API and the demo-snapshot exporter, so the operational app and the
public demo can never drift apart in how they label the same situation.

Standard library only — the Pages deploy imports this without `pip install`.
"""

from __future__ import annotations

import sqlite3
from typing import Any

SHIFT_LABEL = "08–17"
NO_SHIFT = "—"

# review_flag -> (cell type, label, punch text when there are no punch times)
ISSUE_PRESENTATION = {
    "cert_period_mismatch": ("sick", "병가", "기간 불일치"),
    "vacancy_unstaffed": ("danger", "결원", "대체 미배치"),
    "leave_punch_conflict": ("warn", "휴가·근태 충돌", None),
    "repeated_punch": ("warn", "다중 태그", None),
    "other": ("warn", "확인", None),
}

STATUS_PRESENTATION = {
    "normal": ("ok", "정상", None, SHIFT_LABEL),
    "late": ("ok", "정상", None, SHIFT_LABEL),
    "leave": ("leave", "연차", "승인", NO_SHIFT),
    "half_day": ("leave", "반차", "승인", NO_SHIFT),
    "sick_leave": ("sick", "병가", "승인", NO_SHIFT),
    "off": ("off", "휴무", "", NO_SHIFT),
    "holiday": ("off", "휴무", "", NO_SHIFT),
    "absent": ("danger", "결원", "미출근", SHIFT_LABEL),
    "unknown": ("gray", "확인 필요", "", SHIFT_LABEL),
}


def format_punches(times: list[str]) -> str:
    """`07:55 / 16:02` for a normal pair, `07:55 · 08:01 · 16:04` for more.

    Three or more punches can be legitimate (출 / 외 / 퇴 / 복), so they are
    shown in full rather than collapsed to a first/last pair.
    """
    if not times:
        return ""
    if len(times) <= 2:
        return " / ".join(times)
    return " · ".join(times)


def build_cell(
    attendance: dict[str, Any] | None,
    punch_times: list[str],
    replacement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one operations-grid cell from that employee-day's facts."""
    if replacement is not None and replacement.get("substitute_is_this_employee"):
        covered = replacement.get("absent_name") or ""
        return {
            "type": "replacement",
            "label": "대체",
            "punch": f"{covered} 대체".strip(),
            "shift": SHIFT_LABEL,
        }

    if attendance is None:
        return {"type": "gray", "label": "기록 없음", "punch": "", "shift": NO_SHIFT}

    status = attendance.get("status") or "unknown"
    flag = attendance.get("review_flag")

    if flag:
        cell_type, label, fixed_punch = ISSUE_PRESENTATION.get(
            flag, ISSUE_PRESENTATION["other"]
        )
        punch = fixed_punch if fixed_punch is not None else format_punches(punch_times)
        cell = {
            "type": cell_type,
            "label": label,
            "punch": punch,
            "issue": True,
            "shift": NO_SHIFT if cell_type == "sick" else SHIFT_LABEL,
        }
        detail = attendance.get("review_note")
        if detail:
            cell["detail"] = detail
        return cell

    cell_type, label, fixed_punch, shift = STATUS_PRESENTATION.get(
        status, STATUS_PRESENTATION["unknown"]
    )
    punch = fixed_punch if fixed_punch is not None else format_punches(punch_times)
    return {"type": cell_type, "label": label, "punch": punch, "shift": shift}


def employee_state(cells: list[dict[str, Any]]) -> str:
    """The 재직 / 병가 / 대체 badge shown on the employee list and profile."""
    if any(c.get("type") == "sick" for c in cells):
        return "병가"
    if any(c.get("type") == "replacement" for c in cells):
        return "대체"
    return "재직"


DOW = ["월", "화", "수", "목", "금", "토", "일"]


def build_days(dates: list[str], today: str | None) -> list[dict[str, Any]]:
    """The weekly header: `8/11`, `화 · 오늘`, day number."""
    days = []
    for iso in dates:
        year, month, day = (int(part) for part in iso.split("-"))
        weekday = _weekday_index(year, month, day)
        entry: dict[str, Any] = {
            "date": f"{month}/{day}",
            "dow": DOW[weekday],
            "num": day,
        }
        if today is not None and iso == today:
            entry["dow"] = f"{DOW[weekday]} · 오늘"
            entry["today"] = True
        days.append(entry)
    return days


def _weekday_index(year: int, month: int, day: int) -> int:
    """Monday = 0. Sakamoto's algorithm, so no datetime import is needed."""
    table = [0, 3, 2, 5, 0, 3, 5, 1, 4, 6, 2, 4]
    y = year - (1 if month < 3 else 0)
    dow = (y + y // 4 - y // 100 + y // 400 + table[month - 1] + day) % 7
    return (dow + 6) % 7  # shift Sunday-first to Monday-first


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
