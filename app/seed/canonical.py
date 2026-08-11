"""Canonical fictional demo dataset.

This is the ONE place the demo's 18 fictional people are defined. The public
GitHub Pages snapshot is generated from it by seeding a database and exporting
that database (app/exporters/demo_snapshot.py) — it is never hand-maintained as
a second copy in JavaScript.

Nothing here is real personal data. Dates are deliberately fixed: the demo must
render identically forever, and must not drift with the real calendar.
"""

from __future__ import annotations

# The demo week is fixed. DEMO_TODAY is the day the demo presents as "today".
DEMO_YEAR = 2026
DEMO_MONTH = 8
DEMO_WEEK_START = "2026-08-10"
DEMO_TODAY = "2026-08-11"

# index in a cells[] row -> ISO date in the fixed demo week
DEMO_WEEK_DATES = [
    "2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13",
    "2026-08-14", "2026-08-15", "2026-08-16",
]

DEMO_DAYS = [
    {
        "date": "8/10",
        "dow": "월",
        "num": 10
    },
    {
        "date": "8/11",
        "dow": "화 · 오늘",
        "num": 11,
        "today": True
    },
    {
        "date": "8/12",
        "dow": "수",
        "num": 12
    },
    {
        "date": "8/13",
        "dow": "목",
        "num": 13
    },
    {
        "date": "8/14",
        "dow": "금",
        "num": 14
    },
    {
        "date": "8/15",
        "dow": "토",
        "num": 15
    },
    {
        "date": "8/16",
        "dow": "일",
        "num": 16
    }
]

DEMO_EMPLOYEES = [
    {
        "name": "김가람",
        "zone": "본관 4층",
        "hire": "2024-03-01",
        "end": "2026-12-31",
        "leave": 5,
        "slot": "001",
        "state": "병가",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "sick",
                "label": "병가",
                "punch": "기간 불일치",
                "detail": "병가 신청 8/4~9/11 · 진단서 8/4~8/31",
                "issue": True,
                "shift": "—"
            },
            {
                "type": "sick",
                "label": "병가",
                "punch": "승인",
                "shift": "—"
            },
            {
                "type": "sick",
                "label": "병가",
                "punch": "승인",
                "shift": "—"
            },
            {
                "type": "sick",
                "label": "병가",
                "punch": "승인",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "박나래",
        "zone": "공학관 3층",
        "hire": "2023-09-01",
        "end": "2026-12-31",
        "leave": 8.5,
        "slot": "002",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "danger",
                "label": "결원",
                "punch": "대체 미배치",
                "detail": "예정 08:00–17:00 · 지문 없음",
                "issue": True,
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "이도연",
        "zone": "인문관 2층",
        "hire": "2024-01-15",
        "end": "2026-12-31",
        "leave": 6,
        "slot": "003",
        "state": "재직",
        "cells": [
            {
                "type": "leave",
                "label": "연차",
                "punch": "승인",
                "shift": "—"
            },
            {
                "type": "warn",
                "label": "휴가·근태 충돌",
                "punch": "07:58 / 16:01",
                "detail": "승인 연차 1일인데 지문기록 존재",
                "issue": True,
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "최라온",
        "zone": "본관 5층",
        "hire": "2022-06-01",
        "end": "2026-12-31",
        "leave": 11,
        "slot": "004",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "warn",
                "label": "다중 태그",
                "punch": "07:55 · 08:01 · 16:04",
                "detail": "20분 이내 재태그 후보 포함 · 원본 보존",
                "issue": True,
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "정마루",
        "zone": "학생회관 1층",
        "hire": "2025-02-01",
        "end": "2027-01-31",
        "leave": 4,
        "slot": "005",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "leave",
                "label": "연차",
                "punch": "승인",
                "shift": "—"
            },
            {
                "type": "leave",
                "label": "연차",
                "punch": "승인",
                "shift": "—"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "한보람",
        "zone": "본관 2층",
        "hire": "2023-01-02",
        "end": "2026-12-31",
        "leave": 9,
        "slot": "006",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "윤새봄",
        "zone": "본관 3층",
        "hire": "2025-04-01",
        "end": "2027-03-31",
        "leave": 3.5,
        "slot": "007",
        "state": "대체",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "replacement",
                "label": "대체",
                "punch": "김가람 대체",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "임서윤",
        "zone": "공학관 1층",
        "hire": "2024-07-01",
        "end": "2026-12-31",
        "leave": 7,
        "slot": "008",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "강하늘",
        "zone": "공학관 2층",
        "hire": "2021-03-01",
        "end": "2026-12-31",
        "leave": 12,
        "slot": "009",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "오예린",
        "zone": "도서관 1층",
        "hire": "2022-11-01",
        "end": "2026-12-31",
        "leave": 4.5,
        "slot": "010",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "leave",
                "label": "연차",
                "punch": "승인",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "송지우",
        "zone": "도서관 2층",
        "hire": "2024-05-01",
        "end": "2026-12-31",
        "leave": 6,
        "slot": "011",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "문채원",
        "zone": "체육관 1층",
        "hire": "2023-08-01",
        "end": "2026-12-31",
        "leave": 8,
        "slot": "012",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "백하린",
        "zone": "체육관 2층",
        "hire": "2025-01-01",
        "end": "2026-12-31",
        "leave": 4,
        "slot": "013",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "권유진",
        "zone": "본관 1층",
        "hire": "2020-03-01",
        "end": "2026-12-31",
        "leave": 14,
        "slot": "014",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "서지안",
        "zone": "인문관 1층",
        "hire": "2024-09-01",
        "end": "2026-12-31",
        "leave": 6.5,
        "slot": "015",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "홍다은",
        "zone": "학생회관 2층",
        "hire": "2022-04-01",
        "end": "2026-12-31",
        "leave": 10,
        "slot": "016",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "노수빈",
        "zone": "공학관 4층",
        "hire": "2025-06-01",
        "end": "2027-05-31",
        "leave": 2,
        "slot": "017",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    },
    {
        "name": "배예나",
        "zone": "본관 6층",
        "hire": "2021-12-01",
        "end": "2026-12-31",
        "leave": 9.5,
        "slot": "018",
        "state": "재직",
        "cells": [
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "ok",
                "label": "정상",
                "punch": "07:55 / 16:02",
                "shift": "08–17"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            },
            {
                "type": "off",
                "label": "휴무",
                "punch": "",
                "shift": "—"
            }
        ]
    }
]

DEMO_MONTH_STATS = {
    "3": {
        "leave": 1
    },
    "4": {
        "leave": 2
    },
    "5": {
        "issue": 1
    },
    "10": {
        "leave": 1
    },
    "11": {
        "issue": 4,
        "replace": 1
    },
    "12": {
        "leave": 1
    },
    "13": {
        "leave": 1
    },
    "14": {
        "leave": 1
    },
    "17": {
        "issue": 1
    },
    "18": {
        "leave": 1
    },
    "20": {
        "sick": 1
    },
    "21": {
        "sick": 1
    },
    "24": {
        "issue": 2
    },
    "27": {
        "leave": 1
    },
    "28": {
        "leave": 1
    },
    "31": {
        "issue": 1
    }
}
