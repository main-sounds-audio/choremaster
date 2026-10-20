#!/usr/bin/env python3
"""Tests choremaster/schedule.py."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import _testkit as t  # noqa: E402
from choremaster.chorefile import Chore  # noqa: E402
from choremaster import schedule as s  # noqa: E402

check = t.check
UTC = timezone.utc


def chore(**kw):
    base = dict(id="c", due=None, every=None, run="true", done_when=None,
                body="", path="c.md")
    base.update(kw)
    return Chore(**base)


def at(*a):
    return datetime(*a, tzinfo=UTC)


NOW = at(2026, 9, 30, 8, 0)
check("a chore with no due and no history is due", s.is_due(chore(), {}, NOW))
check("not due before its due time",
      not s.is_due(chore(due=at(2026, 9, 30, 9, 0)), {}, NOW))
check("due once its due time has passed",
      s.is_due(chore(due=at(2026, 9, 30, 7, 0)), {}, NOW))

st = {}
s.mark_ran(st, "c", NOW, 1)
check("not due again 5 minutes after running", not s.is_due(chore(), st, NOW + timedelta(minutes=5)))
check("no every means once per local day: not due at 22:00 local time on the same date (08:00Z + 13h)", not s.is_due(chore(), st, NOW + timedelta(hours=13)))
check("and due at the first moment of the next local date, even under 24 hours later",
      s.is_due(chore(), st, NOW + timedelta(hours=17)), "08:00Z + 17h = 02:00 local the next day")
check("a chore that ran at 09:00 local is due the next morning at 06:30 local (not held to 09:00)",
      s.is_due(chore(), {"c": {"last_ran": at(2026, 9, 30, 8, 0).isoformat()}}, at(2026, 10, 1, 5, 30)))
check("every 1d follows the same date rule", s.is_due(chore(every=timedelta(days=1)), st, NOW + timedelta(hours=17)))
check("every 2d is NOT date-based: still elapsed time",
      not s.is_due(chore(every=timedelta(days=2)), st, NOW + timedelta(hours=40)))
check("every 1h repeats after an hour",
      s.is_due(chore(every=timedelta(hours=1)), st, NOW + timedelta(hours=1)))
check("every 1h does not repeat at 59 minutes",
      not s.is_due(chore(every=timedelta(hours=1)), st, NOW + timedelta(minutes=59)))
# last_ran is the tick's start, and a tick a few seconds earlier in
# its minute must not cost the chore a whole extra tick.
drift = {"c": {"last_ran": at(2026, 10, 18, 12, 45, 20).isoformat(), "last_code": 0}}
check("every 1h run at 12:45:20 is due at the 13:45:05 tick (a few seconds early in the minute)",
      s.is_due(chore(every=timedelta(hours=1)), drift, at(2026, 10, 18, 13, 45, 5)))
check("every 1h run at 12:45:20 is not due at 13:40:00 (a tick a few minutes early)",
      not s.is_due(chore(every=timedelta(hours=1)), drift, at(2026, 10, 18, 13, 40, 0)))
drift_retry = {"c": {"last_ran": at(2026, 10, 18, 12, 45, 20).isoformat(), "last_code": 2}}
check("the 1h exit-2 retry from 12:45:20 is due at the 13:45:05 tick too",
      s.is_due(chore(every=timedelta(hours=1)), drift_retry, at(2026, 10, 18, 13, 45, 5)))

# A chore that exited 2 could not answer: it has not run in any sense that
# counts, so it is retried within the day, not held to the next local date
# Not every tick, though: once an hour, so a check that
# cannot answer for a whole morning does not run 4 times an hour.
st2 = {}
s.mark_ran(st2, "c", NOW, 2)
check("a daily chore that exited 2 is not due again 15 minutes later",
      not s.is_due(chore(), st2, NOW + timedelta(minutes=15)))
check("and is due again an hour later, on the same local date",
      s.is_due(chore(), st2, NOW + timedelta(hours=1)))
check("an every-2d chore that exited 2 is also retried after an hour",
      s.is_due(chore(every=timedelta(days=2)), st2, NOW + timedelta(hours=1)))
st3 = {}
s.mark_ran(st3, "c", NOW, 1)
check("a chore that exited 1 (a finding) is NOT retried within the day",
      not s.is_due(chore(), st3, NOW + timedelta(hours=1)))

s.mark_done(st, "c", NOW)
check("a done chore is never due again", not s.is_due(chore(every=timedelta(minutes=15)), st, NOW + timedelta(days=30)))

# a due set at 08:00 local fires once across the change of clocks (2026-10-25)
summer = chore(id="b", due=at(2026, 10, 24, 7, 0))    # 08:00 at UTC+1 = 07:00Z
winter = chore(id="g", due=at(2026, 10, 25, 8, 0))    # 08:00 at UTC = 08:00Z
check("summer side: not due at 06:59Z, due at 07:00Z",
      not s.is_due(summer, {}, at(2026, 10, 24, 6, 59)) and s.is_due(summer, {}, at(2026, 10, 24, 7, 0)))
check("winter side: not due at 07:59Z, due at 08:00Z",
      not s.is_due(winter, {}, at(2026, 10, 25, 7, 59)) and s.is_due(winter, {}, at(2026, 10, 25, 8, 0)))

# state file
home = t.tmp()
check("load_state on an empty home is an empty state without an error",
      s.load_state(home).get("_meta", {}).get("state_error") is None and len(
          [k for k in s.load_state(home) if k != "_meta"]) == 0)
st = {}
s.mark_ran(st, "x", NOW, 2)
s.save_state(home, st)
back = s.load_state(home)
check("state round-trips", back["x"]["last_code"] == 2 and back["x"]["last_ran"].startswith("2026-09-30T08:00"), back)
check("save leaves no temp file behind", not [f for f in os.listdir(home) if f.endswith(".tmp")], os.listdir(home))

with open(os.path.join(home, "state.json"), "w") as f:
    f.write('{"x": {"last_ran": "2026-09-30T08:')          # a truncated write
bad = s.load_state(home)
check("a truncated state file is treated as absent, not a crash", isinstance(bad, dict))
check("and the corruption is reported in the state for the caller to record",
      bool(bad.get("_meta", {}).get("state_error")), bad)
check("after a corrupt read every chore is due again (fail toward running, not silence)",
      s.is_due(chore(id="x"), bad, NOW))

# `after: HH:MM`: a once-a-day chore at noon, not at the first tick after midnight. Local time of day.
# 2026-09-30 is summer time (UTC+1): 08:00Z is 09:00 local, 11:30Z is 12:30 local.
check("after 12:00: not due at 09:00 local", not s.is_due(chore(after="12:00"), {}, at(2026, 9, 30, 8, 0)))
check("after 12:00: due at 12:30 local", s.is_due(chore(after="12:00"), {}, at(2026, 9, 30, 11, 30)))
st_a = {"c": {"last_ran": at(2026, 9, 30, 11, 30).isoformat(), "last_code": 0}}
check("after 12:00: not due again the same local date", not s.is_due(chore(after="12:00"), st_a, at(2026, 9, 30, 15, 0)))
check("after 12:00: not due the next morning before noon", not s.is_due(chore(after="12:00"), st_a, at(2026, 10, 1, 8, 0)))
check("after 12:00: due the next day after noon", s.is_due(chore(after="12:00"), st_a, at(2026, 10, 1, 11, 30)))

t.finish()


def test_checks():
    t.assert_clean(__name__)
