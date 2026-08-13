"""One authoritative site work-calendar used by leave and attendance rules."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta


class CalendarError(ValueError):
    pass


def dates_between(start_date: str, end_date: str) -> list[str]:
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise CalendarError("날짜 형식이 올바르지 않습니다.") from exc
    if end < start:
        raise CalendarError("종료일은 시작일보다 빠를 수 없습니다.")
    result = []
    current = start
    while current <= end:
        result.append(current.isoformat())
        current += timedelta(days=1)
    return result


def is_working_day(conn: sqlite3.Connection, iso_date: str) -> bool:
    row = conn.execute(
        "SELECT is_working FROM site_calendar WHERE calendar_date = ?", (iso_date,)
    ).fetchone()
    if row is not None:
        return bool(row["is_working"])
    return date.fromisoformat(iso_date).weekday() < 5


def working_dates(conn: sqlite3.Connection, start_date: str, end_date: str) -> list[str]:
    return [iso for iso in dates_between(start_date, end_date) if is_working_day(conn, iso)]


def leave_days(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
    portion: str = "full",
) -> float:
    days = working_dates(conn, start_date, end_date)
    if portion in {"am", "pm"}:
        if start_date != end_date:
            raise CalendarError("반차는 하루만 등록할 수 있습니다.")
        return 0.5 if days else 0.0
    if portion != "full":
        raise CalendarError("휴가 시간 구분이 올바르지 않습니다.")
    return float(len(days))
