"""
shared/time_parse.py — Unified time/deadline parsing.

Consolidates duplicate implementations from:
  - core/context.py::_parse_deadline_dt / _calc_working_hours
  - memory/event_detector.py::_extract_time

All time parsing now goes through this module.
"""

import re
from datetime import datetime, timedelta, date

WORK_START = 8
WORK_END = 18

WEEKDAY_MAP = {
    "周一": 0, "周二": 1, "周三": 2, "周四": 3, "周五": 4, "周六": 5, "周日": 6,
    "星期一": 0, "星期二": 1, "星期三": 2, "星期四": 3, "星期五": 4, "星期六": 5, "星期日": 6,
    "星期天": 6,
}


def parse_deadline_dt(deadline_str: str, ref: datetime = None) -> datetime | None:
    """Parse deadline string into a datetime. Returns None if unparseable.

    Supports: YYYY-MM-DD, DD日, 周X, 周X9点/上午
    """
    deadline_str = deadline_str.strip()
    if not deadline_str:
        return None
    if ref is None:
        ref = datetime.now()
    today = ref.date()

    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', deadline_str)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), WORK_END, 0)

    m = re.match(r'(\d{1,2})日', deadline_str)
    if m:
        day = int(m.group(1))
        hour = 9 if any(kw in deadline_str for kw in ['9点', '9:00', '上午']) else WORK_END
        try:
            return datetime(today.year, today.month, day, hour, 0)
        except ValueError:
            return None

    for name, wd in WEEKDAY_MAP.items():
        if name in deadline_str:
            days_ahead = wd - today.weekday()
            if days_ahead < 0:
                days_ahead += 7
            elif days_ahead == 0:
                hour = 9 if any(kw in deadline_str for kw in ['9点', '9:00', '上午']) else WORK_END
                candidate = datetime(today.year, today.month, today.day, hour, 0)
                if candidate <= ref:
                    days_ahead = 7
            target = today + timedelta(days=days_ahead)
            hour = 9 if any(kw in deadline_str for kw in ['9点', '9:00', '上午']) else WORK_END
            return datetime(target.year, target.month, target.day, hour, 0)

    return None


def calc_working_hours(start: datetime, end: datetime) -> float:
    """Count working hours between two datetimes (8-18 Mon-Fri, excl weekends)."""
    if end <= start:
        return 0.0

    total = 0.0
    cur = start.date()
    end_date = end.date()

    while cur <= end_date:
        if cur.weekday() < 5:
            day_start = datetime(cur.year, cur.month, cur.day, WORK_START, 0)
            day_end = datetime(cur.year, cur.month, cur.day, WORK_END, 0)
            seg_start = max(start, day_start)
            seg_end = min(end, day_end)
            if seg_start < seg_end:
                total += (seg_end - seg_start).total_seconds() / 3600
        cur += timedelta(days=1)

    return round(total, 1)
