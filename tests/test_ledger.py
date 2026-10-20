#!/usr/bin/env python3
"""Tests choremaster/ledger.py."""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta, timezone

import _testkit as t  # noqa: E402
from choremaster import ledger as L  # noqa: E402

check = t.check
UTC = timezone.utc
home = t.tmp()
now = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)

L.record(home, now, "a", "ran", 1, "outstanding thing")
path = os.path.join(home, "ledger", "2026-09-30.jsonl")
check("record writes to ledger/YYYY-MM-DD.jsonl", os.path.exists(path), os.listdir(home))
check("and appends exactly one line per record", len(open(path).read().splitlines()) == 1)
L.record(home, now + timedelta(minutes=15), "b", "done", 0, "")
rows = L.read_day(home, date(2026, 9, 30))
check("read_day returns rows in order", [r["id"] for r in rows] == ["a", "b"], rows)
check("a row carries at, id, kind, code, note",
      set(rows[0]) >= {"at", "id", "kind", "code", "note"} and rows[0]["code"] == 1, rows[0])
check("read_day of a day with no ledger is empty", L.read_day(home, date(2026, 1, 1)) == [])

# the ledger day is the local date in the configured zone (UTC+1 in September), so 23:30Z lands on the next day
L.record(home, datetime(2026, 9, 30, 23, 30, tzinfo=UTC), "late", "ran", 0, "")
check("the day file is the local date (23:30Z at UTC+1 is the next day)",
      any(r["id"] == "late" for r in L.read_day(home, date(2026, 10, 1))))

with open(path, "a") as f:
    f.write("{this is not json\n")
rows = L.read_day(home, date(2026, 9, 30))
check("a corrupt line does not raise", isinstance(rows, list))
bad = [r for r in rows if r["kind"] == "error"]
check("and shows up as a synthetic error row (code 2), never silently dropped",
      len(bad) == 1 and bad[0]["code"] == 2 and "corrupt" in bad[0]["note"], rows)

L.record(home, now, "leak", "error", 2, "token sk-ant-oat01-AbCdEf_12345-xyz was here")
row = [r for r in L.read_day(home, date(2026, 9, 30)) if r["id"] == "leak"][0]
check("a secret-shaped string is redacted before it is written",
      "sk-ant-" not in row["note"] and "REDACTED" in row["note"], row["note"])
check("and is not present anywhere in the file",
      "AbCdEf" not in open(path).read())
L.record(home, now, "long", "ran", 1, "x" * 10000)
row = [r for r in L.read_day(home, date(2026, 9, 30)) if r["id"] == "long"][0]
check("a very long note is capped", len(row["note"]) <= 4100, len(row["note"]))

check("heartbeat_age is None when never written", L.heartbeat_age(home, now) is None)
L.write_heartbeat(home, now)
check("heartbeat_age after a write is zero", L.heartbeat_age(home, now) == timedelta(0), L.heartbeat_age(home, now))
check("and grows with time", L.heartbeat_age(home, now + timedelta(minutes=40)) == timedelta(minutes=40))
with open(os.path.join(home, "heartbeat.json"), "w") as f:
    f.write("garbage")
check("an unreadable heartbeat reads as never written (None), not a crash",
      L.heartbeat_age(home, now) is None)

# record_once: the tick-level errors are written once per local day per key
st = {}
h2 = t.tmp()
L.record_once(h2, now, st, "k", "choremaster", "problem")
L.record_once(h2, now + timedelta(minutes=15), st, "k", "choremaster", "problem")
check("record_once writes a key once per day",
      len([r for r in L.read_day(h2, date(2026, 9, 30)) if r["kind"] == "error"]) == 1)
L.record_once(h2, now, st, "other", "choremaster", "different problem")
check("a different key is written too",
      len([r for r in L.read_day(h2, date(2026, 9, 30)) if r["kind"] == "error"]) == 2)
L.record_once(h2, now + timedelta(days=1), st, "k", "choremaster", "problem")
check("and the same key is written again the next day",
      len([r for r in L.read_day(h2, date(2026, 10, 1)) if r["kind"] == "error"]) == 1)

t.finish()


def test_checks():
    t.assert_clean(__name__)
