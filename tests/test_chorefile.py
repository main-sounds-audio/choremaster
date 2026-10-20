#!/usr/bin/env python3
"""Tests choremaster/chorefile.py.

A broken chore file must come back as an error the caller can put in the ledger, never be skipped silently
and never crash the whole load.
"""
from __future__ import annotations

import os
from datetime import timedelta, timezone

import _testkit as t
from choremaster.chorefile import ChoreError, load_all, load_chore

check = t.check


def write(d, name, text):
    p = os.path.join(d, name)
    with open(p, "w") as f:
        f.write(text)
    return p


FULL = """---
id: p3-check
due: 2026-09-30T08:00:00+01:00   # a comment
every: 1d
run: bash scripts/check-x.sh
done_when: bash scripts/check-y.sh
---
Body line one.
Body line two.
"""

d = t.tmp()
c = load_chore(write(d, "a.md", FULL))
check("parses id", c.id == "p3-check", c.id)
check("parses aware due to UTC", c.due is not None and c.due.utcoffset() == timedelta(hours=1)
      and c.due.astimezone(timezone.utc).hour == 7, c.due)
check("parses every 1d", c.every == timedelta(days=1), c.every)
check("parses run with the comment stripped", c.run == "bash scripts/check-x.sh", c.run)
check("parses done_when", c.done_when == "bash scripts/check-y.sh", c.done_when)
check("body is kept verbatim", c.body == "Body line one.\nBody line two.\n", repr(c.body))

# CHOREMASTER_TZ=Europe/Dublin in the suites: UTC+1 in summer, UTC in winter
c = load_chore(write(d, "b.md", "---\nid: n\ndue: 2026-09-30T08:00\n---\nx\n"))
check("naive due means the configured zone (08:00 summer time is 07:00 UTC)",
      c.due.astimezone(timezone.utc).hour == 7, c.due)
c = load_chore(write(d, "b2.md", "---\nid: n\ndue: 2026-12-15T08:00\n---\nx\n"))
check("naive due in winter means 08:00 UTC",
      c.due.astimezone(timezone.utc).hour == 8, c.due)
c = load_chore(write(d, "b3.md", "---\nid: n\ndue: 2026-09-30T08:00:00Z\n---\nx\n"))
check("a trailing Z is accepted", c.due.astimezone(timezone.utc).hour == 8, c.due)
os.environ["CHOREMASTER_TZ"] = "America/New_York"
try:
    c = load_chore(write(d, "b4.md", "---\nid: n\ndue: 2026-12-15T08:00\n---\nx\n"))
    check("the zone is configurable: naive due in New York in winter is 13:00 UTC",
          c.due.astimezone(timezone.utc).hour == 13, c.due)
finally:
    os.environ["CHOREMASTER_TZ"] = "Europe/Dublin"

for text, want in (("15m", timedelta(minutes=15)), ("1h", timedelta(hours=1)), ("1d", timedelta(days=1))):
    c = load_chore(write(d, "e.md", "---\nid: e\nevery: %s\n---\n" % text))
    check("every accepts " + text, c.every == want, c.every)


def raises(text, label, needle=None):
    try:
        load_chore(write(d, "bad.md", text))
    except ChoreError as e:
        check(label, needle is None or needle in str(e), str(e))
    else:
        check(label, False, "no ChoreError raised")


raises("---\nrun: x\n---\n", "a missing id is an error", "id")
raises("---\nid: Bad Id\n---\n", "an id with spaces or capitals is an error", "id")
raises("---\nid: a\nevery: soon\n---\n", "a bad every is an error", "every")
raises("---\nid: a\ndue: not-a-date\n---\n", "a bad due is an error", "due")
raises("---\nid: a\nsurprise: 1\n---\n", "an unknown key is an error (typos are findings)", "surprise")
raises("---\nid: a\nneeds_model: true\n---\n", "a key this scheduler does not have is an error", "needs_model")
raises("no front matter here\n", "a file with no front matter is an error", "front matter")
raises("---\nid: a\n", "an unterminated front matter block is an error", "front matter")

c = load_chore(write(d, "r.md", "---\nid: r\n---\nJust a reminder.\n"))
check("a reminder (no run) is valid", c.run is None)

# load_all: population, duplicates, broken files, README
d2 = t.tmp()
write(d2, "a.md", "---\nid: one\n---\n")
write(d2, "b.md", "---\nid: two\nrun: true\n---\n")
write(d2, "broken.md", "---\nid: three\nsurprise: 1\n---\n")
write(d2, "dup.md", "---\nid: one\n---\n")
write(d2, "README.md", "# not a chore\n")
write(d2, "notes.txt", "ignored")
chores, errors = load_all(d2)
check("load_all returns the good chores", sorted(c.id for c in chores) == ["one", "two"], [c.id for c in chores])
check("load_all reports the broken file, not raising", any("broken.md" in e.path for e in errors), [e.path for e in errors])
check("load_all reports the duplicate id", any("dup.md" in e.path and "duplicate" in str(e) for e in errors),
      [str(e) for e in errors])
check("load_all skips README.md and non-.md files", not any("README" in e.path or "notes" in e.path for e in errors)
      and len(errors) == 2, [e.path for e in errors])
check("the first file by name keeps a duplicate id", [c.path for c in chores if c.id == "one"][0].endswith("a.md"))

# one unreadable or absurd file must not crash the whole load
d3 = t.tmp()
write(d3, "ok.md", "---\nid: ok\n---\n")
open(os.path.join(d3, "latin1.md"), "wb").write(b"---\nid: \xff\xfe\n---\nbody\n")
write(d3, "huge.md", "---\nid: huge\nevery: 1000000000d\n---\n")
open(os.path.join(d3, "utf16.md"), "wb").write("---\nid: u\n---\n".encode("utf-16"))
try:
    load_chore(os.path.join(d3, "latin1.md"))
    check("a non-UTF-8 chore file raises ChoreError, not UnicodeDecodeError", False)
except ChoreError as e:
    check("a non-UTF-8 chore file raises ChoreError, not UnicodeDecodeError", "latin1.md" in e.path, e)
except Exception as e:  # noqa: BLE001
    check("a non-UTF-8 chore file raises ChoreError, not UnicodeDecodeError", False, repr(e))
try:
    load_chore(os.path.join(d3, "huge.md"))
    check("an absurd every raises ChoreError, not OverflowError", False)
except ChoreError:
    check("an absurd every raises ChoreError, not OverflowError", True)
except Exception as e:  # noqa: BLE001
    check("an absurd every raises ChoreError, not OverflowError", False, repr(e))
try:
    chores, errors = load_all(d3)
    check("load_all survives binary and absurd files and still returns the good chore",
          [c.id for c in chores] == ["ok"] and len(errors) == 3, ([c.id for c in chores], [str(e) for e in errors]))
except Exception as e:  # noqa: BLE001
    check("load_all survives binary and absurd files and still returns the good chore", False, repr(e))

# the digest keys: title, do, links
c = load_chore(write(d, "t.md", """---
id: t
title: Backups: the nightly job missed a run
do: Check the job and re-run it.
links: Open the dashboard|http://127.0.0.1:8765/#outcome; Ticket 919|https://example.com/issues/919
---
"""))
check("title and do parse (a colon inside the value is kept)",
      c.title == "Backups: the nightly job missed a run" and c.do == "Check the job and re-run it.", (c.title, c.do))
c = load_chore(write(d, "t1.md", "---\nid: t1\ndo: See ticket #42 for details\n---\n"))
check("a ` #42` inside a value is NOT a comment", "#42" in (c.do or ""), c.do)
c = load_chore(write(d, "t.md", """---
id: t
links: Open the dashboard|http://127.0.0.1:8765/#outcome; Ticket 919|https://example.com/issues/919
---
"""))
check("links parse into (label, url) pairs, in order",
      c.links == [("Open the dashboard", "http://127.0.0.1:8765/#outcome"),
                  ("Ticket 919", "https://example.com/issues/919")], c.links)
c = load_chore(write(d, "t2.md", "---\nid: t2\n---\n"))
check("the digest keys default to nothing", c.title is None and c.do is None and c.links == [])
c = load_chore(write(d, "t3.md", "---\nid: t3\nrun: true   # a real comment\n---\n"))
check("a real `# comment` after whitespace is still stripped", c.run == "true", c.run)
raises("---\nid: a\nlinks: no separator here\n---\n", "a link with no label|url separator is an error", "links")
raises("---\nid: a\nlinks: Bad|app://open/thing\n---\n", "a custom-scheme link is refused", "https")
raises("---\nid: a\nlinks: Bad|javascript:alert(1)\n---\n", "a javascript: link is refused", "https")
raises("---\nid: a\nlinks: Bad|file:///etc/passwd\n---\n", "a file: link is refused", "https")
# A home-network host by its mDNS name is allowed over http; a public name over http is not, nor a path that
# merely ends in ".local".
c = load_chore(write(d, "lan.md", "---\nid: a\nlinks: Open the dashboard|http://nas.local:8765/\n---\n"))
check("an http link to a home-network .local host is allowed",
      c.links == [("Open the dashboard", "http://nas.local:8765/")], c.links)
raises("---\nid: a\nlinks: Bad|http://example.com/\n---\n", "an http link to a public host is refused", "https")
raises("---\nid: a\nlinks: Bad|http://evil.example/x.local/\n---\n", "a path ending in .local does not make a host local", "https")
raises("---\nid: a\nlinks: Bad|http://notlocal/\n---\n", "a bare name over http is refused", "https")
raises("---\nid: a\nlinks: Bad|http://x.local:80@evil.example/\n---\n", "userinfo cannot smuggle another host past the .local rule", "https")
raises("---\nid: a\nlinks: Bad|http://127.0.0.1:80@evil.example/\n---\n", "nor past the 127.0.0.1 rule", "https")
raises("---\nid: a\ntitle: " + "x" * 200 + "\n---\n", "a title over 100 characters is an error", "title")
c = load_chore(write(d, "t4.md", "---\nid: t4\nlinks: Local|http://localhost:3000/x; Site|https://example.com\n---\n"))
check("http://localhost and https are both allowed", len(c.links) == 2, c.links)

c = load_chore(write(d, "t5.md", "---\nid: t5\nafter: 12:00\n---\n"))
check("after: HH:MM is read", c.after == "12:00", c.after)
raises("---\nid: a\nafter: noon\n---\n", "after must be HH:MM", "after")
raises("---\nid: a\nafter: 25:00\n---\n", "after: an hour past 23 is an error", "after")

c = load_chore(write(d, "w.md", "---\nid: w\nrun: true\nwaits: TICKET-7 the audit log\n---\n"))
check("waits: `<ref> <what>` parses", c.waits == ("TICKET-7", "the audit log"), c.waits)
raises("---\nid: a\nrun: true\nwaits: justone\n---\n", "waits needs a ref and a description", "waits")
raises("---\nid: a\nwaits: 7 something\n---\n", "waits needs a run or done_when to replace", "waits")
c = load_chore(write(d, "p.md", "---\nid: p\nprivate: yes\nnames_paused: true\n---\n"))
check("private and names_paused parse", c.private is True and c.names_paused is True)
raises("---\nid: a\nprivate: maybe\n---\n", "private must be yes or no", "private")

t.finish()


def test_checks():
    t.assert_clean(__name__)
