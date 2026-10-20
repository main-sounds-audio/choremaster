"""The time zone a day is read in.

A "daily" chore runs once per local calendar date, `after: 12:00` is a local time of day, a naive `due:`
is a local time, and the ledger files are named by local date. The zone is, in order:

  1. CHOREMASTER_TZ, an IANA name such as `Europe/Paris` or `America/New_York`;
  2. otherwise the machine's own local zone (what `datetime.astimezone()` uses).

A name the system's zone database does not know falls back to UTC, and `problem()` returns the reason so the
tick can record it.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, tzinfo
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python older than 3.9
    ZoneInfo = None  # type: ignore

ENV = "CHOREMASTER_TZ"


def zone() -> Optional[tzinfo]:
    """The configured zone, or None for the machine's local zone."""
    name = os.environ.get(ENV, "").strip()
    if not name:
        return None
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - unknown key, missing tzdata, bad characters
        return timezone.utc


def problem() -> Optional[str]:
    """Why CHOREMASTER_TZ cannot be used, or None when it is fine or unset."""
    name = os.environ.get(ENV, "").strip()
    if not name:
        return None
    if ZoneInfo is None:
        return "%s=%s ignored: this Python has no zoneinfo; using UTC" % (ENV, name)
    try:
        ZoneInfo(name)
    except Exception as e:  # noqa: BLE001
        return "%s=%s is not a known time zone (%s); using UTC" % (ENV, name, type(e).__name__)
    return None


def local(dt: datetime) -> datetime:
    """`dt` (timezone-aware) in the configured zone."""
    z = zone()
    return dt.astimezone(z) if z is not None else dt.astimezone()


def attach(dt: datetime) -> datetime:
    """A naive datetime read as a wall-clock time in the configured zone."""
    z = zone()
    return dt.replace(tzinfo=z) if z is not None else dt.astimezone()


def today(now: datetime):
    """The local calendar date of `now`."""
    return local(now).date()
