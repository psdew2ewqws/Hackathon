"""Jordan public holidays 2026. Surface only — feature is not in the trained
model yet (see limitations.md), so ``is_holiday`` is advisory metadata for
the dashboard and any future retrain."""
from __future__ import annotations

from datetime import date, datetime, timedelta


# Source: Jordan official holiday announcements (approximate; Islamic dates move).
_HOLIDAYS_2026: dict[str, str] = {
    "2026-01-01": "New Year's Day",
    "2026-03-20": "Ramadan begins (approx)",
    "2026-04-19": "Eid al-Fitr (approx)",
    "2026-04-20": "Eid al-Fitr day 2",
    "2026-04-21": "Eid al-Fitr day 3",
    "2026-05-01": "Labour Day",
    "2026-05-25": "Independence Day",
    "2026-06-26": "Eid al-Adha (approx)",
    "2026-06-27": "Eid al-Adha day 2",
    "2026-06-28": "Eid al-Adha day 3",
    "2026-07-17": "Islamic New Year (approx)",
    "2026-09-24": "The Prophet's Birthday (approx)",
    "2026-12-25": "Christmas Day",
}


def is_holiday(d: date | datetime | str) -> tuple[bool, str | None]:
    if isinstance(d, datetime):
        d = d.date()
    if isinstance(d, str):
        key = d[:10]
    else:
        key = d.isoformat()
    name = _HOLIDAYS_2026.get(key)
    return (name is not None, name)


def next_holiday(d: date | datetime | str | None = None) -> tuple[str | None, str | None]:
    if d is None:
        d = datetime.now().date()
    elif isinstance(d, datetime):
        d = d.date()
    elif isinstance(d, str):
        d = date.fromisoformat(d[:10])
    upcoming = sorted(_HOLIDAYS_2026.items())
    for iso, name in upcoming:
        if iso >= d.isoformat():
            return iso, name
    return None, None
