#!/usr/bin/env python3
"""Tests choremaster/ran_since.py: "ran" means a row showing it ran, not that it found nothing."""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone

import _testkit as t  # noqa: E402
from choremaster import ledger as L  # noqa: E402

check = t.check
home = t.tmp("cm-rs-")
D = lambda d, h=8: datetime(2026, 10, d, h, 0, tzinfo=timezone.utc)
L.record(home, D(6), "clean", "ran", 0, "")
L.record(home, D(6), "outstanding", "ran", 1, "something")
L.record(home, D(6), "ended", "done", 0, "")
L.record(home, D(6), "unanswered", "ran", 2, "could not answer")
L.record(home, D(6), "errored", "error", 2, "problem")
L.record(home, D(5), "before", "ran", 0, "")


def run(*ids, since="2026-10-06"):
    p = subprocess.run([sys.executable, t.BIN, "ran-since", "--since", since, "--state-dir", home, "--now", D(7).isoformat(), *ids],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


check("clean, outstanding and ended all count as ran", run("clean", "outstanding", "ended") == (0, ""))
rc, out = run("unanswered")
check("a code 2 is not ran", rc == 1 and "unanswered" in out, (rc, out))
rc, out = run("errored")
check("an error row is not ran", rc == 1 and "errored" in out, (rc, out))
rc, out = run("never-seen")
check("no row at all is not ran", rc == 1 and "never-seen" in out, (rc, out))
rc, out = run("before")
check("a row from before the date does not count", rc == 1 and "before" in out, (rc, out))
rc, out = run("clean", "never-seen", "unanswered")
check("every id that has not run is named, the ones that have are not", rc == 1 and "never-seen" in out
      and "unanswered" in out and "clean" not in out, out)
check("a bad date is exit 2", run("clean", since="soon")[0] == 2)
p = subprocess.run([sys.executable, t.BIN, "ran-since", "--since", "2026-10-06", "--state-dir", os.path.join(home, "nope"), "x"], capture_output=True, text=True)
check("no ledger directory is exit 2, never 'all ran'", p.returncode == 2, p.stderr)
t.finish()


def test_checks():
    t.assert_clean(__name__)
