"""Deterministic review flags over raw punches.

Every rule here only *annotates*. Nothing merges, rewrites or removes a punch:
AI_BUILD_PLAN.md §2.4 and §2.5 make raw events untouchable and reduce
repeated-punch handling to a review flag.

The repeated-punch threshold is configurable and defaults to 20 minutes, the
empirical starting point in §7 Phase 3. In a real month's export, 17 pairs fell
inside that window — including exact repeats of the same timestamp — so the
window is doing real work rather than being decorative.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_REPEATED_PUNCH_MINUTES = 20


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str          # 'info' | 'review' | 'blocking'
    detail: str
    slot_code: str | None = None
    work_date: str | None = None
    employee: str | None = None

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "detail": self.detail,
            "slot": self.slot_code,
            "workDate": self.work_date,
            "employee": self.employee,
        }


def minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:5])


def repeated_punch_indexes(times: list[str], threshold_minutes: int) -> set[int]:
    """Positions of punches that sit within `threshold` of the previous one.

    The first punch of a close pair is not flagged — the later one is the
    candidate for being a re-tap.
    """
    flagged: set[int] = set()
    order = sorted(range(len(times)), key=lambda i: (minutes(times[i]), i))
    for position in range(1, len(order)):
        previous, current = order[position - 1], order[position]
        if minutes(times[current]) - minutes(times[previous]) <= threshold_minutes:
            flagged.add(current)
    return flagged


def review_day(
    times: list[str], threshold_minutes: int = DEFAULT_REPEATED_PUNCH_MINUTES
) -> dict:
    """Describe one employee-day's punches without changing them."""
    flagged = repeated_punch_indexes(times, threshold_minutes)
    exact_repeats = len(times) - len(set(times))
    return {
        "punch_count": len(times),
        "repeated_indexes": sorted(flagged),
        "has_repeated_candidate": bool(flagged),
        "exact_repeat_count": exact_repeats,
        # A day with a single punch is incomplete, not an absence.
        "incomplete": len(times) == 1,
    }


def whole_site_zero_punch_dates(
    dates_in_period: list[str], dates_with_punches: set[str]
) -> list[str]:
    """Dates where nobody punched at all.

    §3: a whole-site zero-punch day can happen — a closure, a terminal outage, a
    partial export — and must never be turned into an absence for every
    employee. It is surfaced as a finding for a human to explain.
    """
    return [date for date in dates_in_period if date not in dates_with_punches]
