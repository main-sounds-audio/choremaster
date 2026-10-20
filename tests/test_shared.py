#!/usr/bin/env python3
"""Tests choremaster/shared.py and ledger.publish: the optional one-way copy for other accounts."""
from __future__ import annotations

import os
import stat
from datetime import datetime, timezone

import _testkit as t
from choremaster import ledger as L, shared

check = t.check
check("with CHOREMASTER_PUBLISH_DIR unset nothing is available", not shared.available() and shared.root() == "")
pub = t.tmp("cm-pub-")
os.environ["CHOREMASTER_PUBLISH_DIR"] = pub
try:
    check("a writable directory is available", shared.available())
    p = shared.write("ledger/x.jsonl", "hello\n")
    check("write puts the file where where() says", p == os.path.join(pub, "ledger", "x.jsonl") == shared.where("ledger/x.jsonl")
          and open(p).read() == "hello\n")
    check("files are mode 0640", stat.S_IMODE(os.stat(p).st_mode) == 0o640, oct(os.stat(p).st_mode))
    for bad in ("../x", "/etc/x", "a//b", "", "a/./b"):
        try:
            shared.write(bad, "x")
            check("a path like %r is refused" % bad, False)
        except ValueError:
            check("a path like %r is refused" % bad, True)
    os.symlink(t.tmp("cm-elsewhere-"), os.path.join(pub, "linked"))
    try:
        shared.write("linked/x", "x")
        check("a symlinked parent is refused", False)
    except OSError:
        check("a symlinked parent is refused", True)
    check("a missing directory is not available", not (lambda: (os.environ.__setitem__("CHOREMASTER_PUBLISH_DIR", pub + "-nope"), shared.available())[1])())
finally:
    del os.environ["CHOREMASTER_PUBLISH_DIR"]

pub = t.tmp("cm-pub-")
os.environ["CHOREMASTER_PUBLISH_DIR"] = pub
try:
    home = t.tmp("cm-home-")
    now = datetime(2026, 9, 30, 8, 0, tzinfo=timezone.utc)
    L.record(home, now, "a", "ran", 1, "public note")
    L.record(home, now, "b", "ran", 1, "private note")
    L.write_heartbeat(home, now)
    written = L.publish(home, now, {"b"})
    text = open(os.path.join(pub, "ledger", "2026-09-30.jsonl")).read()
    check("publish copies today's ledger", "public note" in text and len(written) == 2, written)
    check("a private chore's note is blanked, its row kept", "private note" not in text and '"id": "b"' in text, text)
    check("and the heartbeat is copied", os.path.exists(os.path.join(pub, "heartbeat.json")))
finally:
    del os.environ["CHOREMASTER_PUBLISH_DIR"]

t.finish()


def test_checks():
    t.assert_clean(__name__)
