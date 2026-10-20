#!/usr/bin/env python3
"""Tests choremaster/paused.py: paused names are kept out of chore output."""
from __future__ import annotations

import os

import _testkit as t
from choremaster import paused

check = t.check
d = t.tmp("cm-paused-")
f = os.path.join(d, "paused.txt")
open(f, "w").write("# header\n\nold-service   mothballed in June\nretired-box  # gone\n")
check("names reads the first word of each line, skipping comments and blanks",
      paused.names(f) == {"old-service", "retired-box"}, paused.names(f))
check("a missing file is an empty list", paused.names(os.path.join(d, "none.txt")) == set())
os.environ["CHOREMASTER_PAUSED_FILE"] = f
try:
    check("CHOREMASTER_PAUSED_FILE names the list", paused.names() == {"old-service", "retired-box"})
finally:
    del os.environ["CHOREMASTER_PAUSED_FILE"]
check("with no list nothing is dropped", paused.drop(1, "1 x\n- old-service#1 y", set()) == (1, "1 x\n- old-service#1 y"))
code, text = paused.drop(1, "1 x\n- old-service#1 y", {"old-service"})
check("a finding whose only bullet names a paused name is no finding", (code, text) == (0, ""), (code, text))
code, text = paused.drop(1, "3 things\n- a\n- old-service: b\n- c", {"old-service"})
check("a mixed finding keeps the other bullets and recounts its summary", code == 1 and text == "2 things\n- a\n- c", (code, text))
check("matching ignores case", paused.drop(1, "1 x\n- OLD-SERVICE y", {"old-service"}) == (0, ""))
check("a name inside a longer name is not a mention", paused.drop(1, "1 x\n- not-old-service y", {"old-service"})[0] == 1)
check("a path segment is a mention", paused.drop(1, "2 x\n- /srv/old-service/data\n- ok", {"old-service"})[1] == "1 x\n- ok")
check("exit 0 output is left alone", paused.drop(0, "", {"old-service"}) == (0, ""))

t.finish()


def test_checks():
    t.assert_clean(__name__)
