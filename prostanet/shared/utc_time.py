"""UTC datetime helpers — EPIC 32.G (GodiBot G78 MOD complete).

Pre-EPIC32 the codebase mixed:
- `datetime.now()` (naive local time)
- `datetime.utcnow()` (DeprecationWarning Python 3.12+, naive UTC)
- SQL `CURRENT_TIMESTAMP` (UTC string, no tz)
- ISO strings with/without tz suffix

Mixed-TZ ordering caused:
- PSADT calculations crossing midnight local → ±1 day errors
- `created_at` vs `source_date` inconsistent ordering in queries
- Audit trails ambiguous (HIPAA §164.312(b) needs deterministic timestamps)

This module is the canonical source of UTC-aware "now" for all code paths.
Migration plan: replace `datetime.now().isoformat()` → `utc_now_iso()`,
`datetime.utcnow()` → `utc_now()`, etc.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def utc_now() -> datetime:
    """UTC-aware current datetime. Replaces `datetime.utcnow()` (deprecated)."""
    return datetime.now(timezone.utc)


def utc_now_iso(timespec: str = "seconds") -> str:
    """UTC-aware ISO timestamp string. Replaces `datetime.now().isoformat()`."""
    return utc_now().isoformat(timespec=timespec)


def utc_today() -> date:
    """UTC today's date (consistent across server TZ)."""
    return utc_now().date()


def utc_date_isoformat() -> str:
    """UTC today as ISO date string (YYYY-MM-DD)."""
    return utc_today().isoformat()


def parse_iso_to_utc(value: str | None) -> datetime | None:
    """Parse ISO string to UTC-aware datetime. Returns None on failure.

    Handles:
    - ISO with tz suffix ("2026-05-16T10:00:00+00:00")
    - ISO without tz ("2026-05-16T10:00:00") → treats as UTC
    - Date only ("2026-05-16") → midnight UTC
    """
    if not value:
        return None
    try:
        s = str(value).strip()
        if len(s) == 10:  # date only
            return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def days_since_utc(iso_date: str | None) -> int | None:
    """Days from given UTC date to today (UTC). Returns None if invalid."""
    d = parse_iso_to_utc(iso_date)
    if d is None:
        return None
    return (utc_today() - d.date()).days


__all__ = [
    "utc_now",
    "utc_now_iso",
    "utc_today",
    "utc_date_isoformat",
    "parse_iso_to_utc",
    "days_since_utc",
]
