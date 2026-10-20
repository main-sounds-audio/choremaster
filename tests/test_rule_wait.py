#!/usr/bin/env python3
"""Tests choremaster/rule_wait.py: "not checked" for 7 days, then failing."""
from __future__ import annotations

import os
import subprocess
import sys

import _testkit as t
from choremaster import rule_wait as W

check = t.check
home = t.tmp("cm-rw-")
DAY = 86400
T0 = 1_790_000_000

rc, line = W.wait("TICKET-7", "the audit log", home=home, now=T0)
check("first sight: could not answer (2), naming the check and what it waits on",
      rc == 2 and line == "not checked: the audit log waits on TICKET-7", (rc, line))
check("and the first-seen day is recorded", os.path.exists(os.path.join(home, "rule-waits", "TICKET-7")))
rc, line = W.wait("TICKET-7", "the audit log", home=home, now=T0 + 6 * DAY + 3600)
check("still 2 on day 6", rc == 2, (rc, line))
rc, line = W.wait("TICKET-7", "the audit log", home=home, now=T0 + 7 * DAY)
check("on day 7 it is outstanding (1), saying how long", rc == 1 and "7 days" in line and "TICKET-7" in line, (rc, line))
rc, line = W.wait("../../etc/passwd", "x", home=home, now=T0)
check("a ref with path characters cannot escape the directory",
      rc == 2 and not os.path.exists(os.path.join(home, "etc")) and os.path.exists(os.path.join(home, "rule-waits", ".._.._etc_passwd")), os.listdir(os.path.join(home, "rule-waits")))
rc, line = W.wait("OTHER", "b", home=t.tmp("cm-rw-"), now=T0)
check("each ref has its own clock", rc == 2)

check("respects_waits reads CHOREMASTER_RESPECT_WAITS", W.respects_waits({"CHOREMASTER_RESPECT_WAITS": "1"})
      and W.respects_waits({"CHOREMASTER_RESPECT_WAITS": "true"}) and not W.respects_waits({}) and not W.respects_waits({"CHOREMASTER_RESPECT_WAITS": "0"}))

env = dict(os.environ, CHOREMASTER_STATE=home, NOW=str(T0 + 10 * DAY))
p = subprocess.run([sys.executable, t.BIN, "rule-wait", "TICKET-7", "the audit log"], capture_output=True, text=True, env=env)
check("the CLI prints the line and exits with the chore's code", p.returncode == 1 and "10 days" in p.stdout, (p.returncode, p.stdout, p.stderr))
p = subprocess.run([sys.executable, t.BIN, "rule-wait", "only-one-arg"], capture_output=True, text=True, env=env)
check("bad usage is exit 2", p.returncode == 2 and "usage" in p.stderr)

t.finish()


def test_checks():
    t.assert_clean(__name__)
