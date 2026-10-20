#!/usr/bin/env python3
"""Tests choremaster/tz.py: the zone days are read in."""
from __future__ import annotations

import os
from datetime import datetime, timezone

import _testkit as t
from choremaster import tz

check = t.check
UTC = timezone.utc
now = datetime(2026, 7, 1, 23, 30, tzinfo=UTC)

os.environ["CHOREMASTER_TZ"] = "Asia/Tokyo"
check("CHOREMASTER_TZ sets the local date (23:30Z is already the next day in Tokyo)", tz.today(now).isoformat() == "2026-07-02")
check("local() converts into the zone", tz.local(now).hour == 8, tz.local(now))
check("a valid zone has no problem", tz.problem() is None)
check("attach reads a naive time as wall-clock in the zone",
      tz.attach(datetime(2026, 7, 1, 9, 0)).astimezone(UTC).hour == 0)

os.environ["CHOREMASTER_TZ"] = "Not/AZone"
check("an unknown zone falls back to UTC", tz.today(now).isoformat() == "2026-07-01" and tz.local(now).hour == 23)
check("and problem() says why", "CHOREMASTER_TZ" in (tz.problem() or "") and "UTC" in tz.problem(), tz.problem())

del os.environ["CHOREMASTER_TZ"]
check("with no setting the machine's own zone is used", tz.zone() is None and tz.problem() is None)
check("and local() agrees with astimezone()", tz.local(now) == now.astimezone() and tz.today(now) == now.astimezone().date())
os.environ["CHOREMASTER_TZ"] = "Europe/Dublin"

t.finish()


def test_checks():
    t.assert_clean(__name__)
