#!/usr/bin/env python3
"""Tests choremaster/report.py.

The digest is the ONLY thing the reader sees. Its failure modes are all "looks fine and is not": exit 2 shown
as clean, an empty ledger shown as all clear, a dead script shown as a quiet day.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import _testkit as t
from choremaster import ledger as L, report as R

check = t.check
UTC = timezone.utc
NOW = datetime(2026, 9, 30, 7, 0, tzinfo=UTC)         # 08:00 at UTC+1


def home_with(rows, heartbeat_age=timedelta(minutes=5)):
    home = t.tmp("cm-home-")
    for at, cid, kind, code, note in rows:
        L.record(home, at, cid, kind, code, note)
    if heartbeat_age is not None:
        L.write_heartbeat(home, NOW - heartbeat_age)
    return home


ago = lambda **kw: NOW - timedelta(**kw)

# outstanding count and headline
home = home_with([(ago(hours=1), "b-chore", "ran", 1, "two things wrong"),
                  (ago(hours=2), "a-chore", "ran", 1, "one thing wrong"),
                  (ago(hours=1), "fine", "ran", 0, "")])
head, body = R.render_digest(home, NOW)
check("headline counts what needs attention", head == "Chore Master: 2 need attention", head)
check("singular reads '1 needs attention'", R.render_digest(home_with([(ago(hours=1), "x", "ran", 1, "n")]), NOW)[0]
      == "Chore Master: 1 needs attention")
check("numbering is by chore id, not by insertion order (a before b)",
      body.index("a-chore") < body.index("b-chore") and "1. **a-chore**" in body and "2. **b-chore**" in body, body)
check("the same ledger renders identically twice", R.render_digest(home, NOW) == (head, body))
check("a clean chore is not listed as needing anything", "fine" not in body.split("Needs attention")[1].split("\n\n")[0]
      if "Needs attention" in body else True, body)

# all clear
head, body = R.render_digest(home_with([(ago(hours=1), "fine", "ran", 0, "")]), NOW)
check("all clear when everything ran clean and the heartbeat is fresh", head == "Chore Master: all clear", head)

# exit 2 is never clear
head, body = R.render_digest(home_with([(ago(hours=1), "unsure", "ran", 2, "curl failed")]), NOW)
check("exit 2 counts as needing attention", head == "Chore Master: 1 needs attention", head)
check("and is worded 'could not answer', never 'clear'", "could not answer" in body and "all clear" not in body, body)

# latest row wins
head, _ = R.render_digest(home_with([(ago(hours=3), "c", "ran", 1, "bad"), (ago(hours=1), "c", "ran", 0, "")]), NOW)
check("the latest row per chore wins (outstanding earlier, clean later = clear)", head == "Chore Master: all clear", head)
head, _ = R.render_digest(home_with([(ago(hours=40), "old", "ran", 1, "ancient")]), NOW)
check("rows older than the 26-hour window are ignored", "need" not in head, head)

# heartbeat
head, body = R.render_digest(home_with([(ago(hours=1), "fine", "ran", 0, "")], heartbeat_age=timedelta(hours=2)), NOW)
check("a stale heartbeat is reported and counts", "heartbeat" in body.lower() and head == "Chore Master: 1 needs attention", (head, body))
head, body = R.render_digest(home_with([(ago(hours=1), "fine", "ran", 0, "")], heartbeat_age=None), NOW)
check("a missing heartbeat is reported and counts", "heartbeat" in body.lower() and "1 needs attention" in head, (head, body))

# empty ledger
head, body = R.render_digest(home_with([], heartbeat_age=None), NOW)
check("an empty ledger says nothing was recorded, not all clear",
      "nothing recorded" in head.lower() and "all clear" not in head.lower(), head)

# done and tick-level errors
head, body = R.render_digest(home_with([(ago(hours=1), "fin", "done", 0, "condition met"),
                                        (ago(hours=1), "choremaster", "error", 2, "no chores directory")]), NOW)
check("a chore that finished is listed under done", "fin" in body.split("Done")[1] if "Done" in body else False, body)
check("a tick-level error is listed as needing attention", "no chores directory" in body and "1 needs attention" in head, (head, body))

# body text from the chores directory
chores = t.tmp("cm-chores-")
open(os.path.join(chores, "x.md"), "w").write("---\nid: x\n---\nRotate the key and replace the file.\nThen tell the team.\n")
head, body = R.render_digest(home_with([(ago(hours=1), "x", "ran", 1, "renew")]), NOW, chores_dir=chores)
check("with a chores directory, the chore's own instructions are shown under the item",
      "Rotate the key" in body, body)

# CLI: headline on line 1
home = home_with([(datetime.now(UTC) - timedelta(hours=1), "cli", "ran", 1, "n")], heartbeat_age=timedelta(minutes=1))
L.write_heartbeat(home, datetime.now(UTC))
out = subprocess.run([sys.executable, t.BIN, "report", "--state-dir", home], capture_output=True, text=True)
check("the CLI prints the headline on line 1", out.stdout.splitlines()[0] == "Chore Master: 1 needs attention", out.stdout + out.stderr)

# multi-line notes (a report listing several rows)
home = home_with([(ago(hours=1), "rows", "ran", 1, "MISSED: item 3\nCLOSING: item 7\nQUIET: item 9\n1\n2\n3")])
head, body = R.render_digest(home, NOW)
check("a note of up to twelve lines is shown whole, as bullets", "- CLOSING: item 7" in body and "- QUIET: item 9" in body and "- 3" in body, body)
home = home_with([(ago(hours=1), "rows", "ran", 1, "\n".join("row %d" % n for n in range(1, 21)))])
head, body = R.render_digest(home, NOW)
check("a longer note is cut at twelve lines (the first is the summary, the rest are bullets)",
      "row 12" in body and "row 13" not in body, body)

# --- command chores and reminders
chores = t.tmp("cm-chores-")
open(os.path.join(chores, "cmdc.md"), "w").write("---\nid: cmdc\nrun: bash check-x.sh\n---\nBODY-OF-A-COMMAND-CHORE.\n")
open(os.path.join(chores, "remind.md"), "w").write("---\nid: remind\n---\nDelete the old tokens.\nIn the console.\nThen say so.\n")
home = home_with([(ago(hours=1), "cmdc", "ran", 1, "the command's finding"),
                  (ago(hours=1), "remind", "ran", 1, "Delete the old tokens.")])
head, body = R.render_digest(home, NOW, chores_dir=chores)
check("a command chore's body is not repeated under its finding", "BODY-OF-A-COMMAND-CHORE" not in body, body)
check("but the finding is", "the command's finding" in body)
check("a command chore shows the command that reproduces its finding", "command: bash check-x.sh" in body, body)
check("a reminder shows the rest of its body", "In the console." in body and "Then say so." in body, body)
check("and does not repeat the first line the item already shows", body.count("Delete the old tokens.") == 1, body)

long_plain = "\n".join("plain line %d" % i for i in range(20))
home = home_with([(ago(hours=1), "plain", "ran", 1, long_plain)])
head, body = R.render_digest(home, NOW)
check("a long note with nothing finding-shaped shows its first twelve lines",
      "plain line 11" in body and "plain line 12" not in body, body)

# --- the to-do digest: bold titles, a "your call" line, bullets, clickable links
todo = t.tmp("cm-chores-")


def chore_file(name, text):
    open(os.path.join(todo, name + ".md"), "w").write(text)


chore_file("backup", """---
id: backup
run: python3 check_backup.py
title: Backups: jobs that need a decision
do: Re-run or retire each one.
links: Open the dashboard|http://127.0.0.1:8765/#outcome
---
Body that must not be dumped.
""")
chore_file("ci", """---
id: ci
run: bash ci.sh
title: Repos on paid CI runners
do: Your call per repo.
links: Ticket 919|https://example.com/issues/919; Console|https://example.com/console
---
""")
chore_file("bare", "---\nid: bare\nrun: bash z.sh\n---\n")
chore_file("remind", """---
id: remind
title: Delete two retired tasks
do: In the console, delete:
---
Some prose that must not be repeated.

- first-task
- second-task

More prose.
""")
chore_file("unable", "---\nid: unable\nrun: true\ntitle: Convention rollout\n---\nInstructions.\n")
home = home_with([
    (ago(hours=1), "backup", "ran", 1, "4 jobs need a decision\n- nightly-db: missed (19 days)\n- logs: missed (15 days)\n- media: missed (13 days)\n- archive: missed (10 days)"),
    (ago(hours=1), "ci", "ran", 1, "7 repos use paid runners by accident\n- alpha\n- beta"),
    (ago(hours=1), "bare", "ran", 1, "raw untitled output"),
    (ago(hours=1), "remind", "ran", 1, "Delete two retired tasks"),
    (ago(hours=1), "unable", "ran", 2, "unable: needs find over the user's folders"),
    (ago(hours=1), "cleanone", "ran", 0, ""),
])
head, body = R.render_digest(home, NOW, chores_dir=todo)
check("a titled item is a numbered bold title ALONE on its line (no hyphen and summary hanging off it)",
      ". **Backups: jobs that need a decision**\n" in body, body)
check("the summary is on its own line under the title", ". **Backups: jobs that need a decision**\n   4 jobs need a decision\n" in body, body)
check("and the italic 'your call' line follows it on ITS own line",
      "   4 jobs need a decision\n   *Re-run or retire each one.*\n" in body, body)
check("no ` — ` separates a title from its summary", "**Backups: jobs that need a decision** —" not in body
      and "**Repos on paid CI runners** —" not in body, body)
check("every row is listed as a bullet (none cut off)",
      all(("- " + x) in body for x in ("nightly-db: missed (19 days)", "logs: missed (15 days)",
                                      "media: missed (13 days)", "archive: missed (10 days)")), body)
check("links are markdown links on their own line", "   [Open the dashboard](http://127.0.0.1:8765/#outcome)" in body, body)
check("two links sit on one line separated by a dot (and nothing else is on that line)",
      "[Ticket 919](https://example.com/issues/919) · [Console](https://example.com/console)" in body, body)
check("a titled command chore has no `command:` line (the digest is a to-do list, not a log)",
      "command: python3 check_backup.py" not in body and "command: bash ci.sh" not in body, body)
check("the chore's body is not dumped under a titled item", "Body that must not be dumped." not in body)
check("an untitled command chore keeps the plain form: bold id, and its command",
      "**bare**" in body and "command: bash z.sh" in body, body)
check("a titled reminder shows only its bullet lines, not its prose",
      "- first-task" in body and "- second-task" in body and "Some prose that must not be repeated." not in body
      and "More prose." not in body, body)
check("a titled item that could not answer says so on its summary line, never bare",
      ". **Convention rollout**\n   could not answer: unable: needs find over the user's folders\n" in body, body)
check("Ran clean lists a chore by its title when it has one, else its id", "Ran clean (1): cleanone" in body, body)

# a tick-level "file.md: problem" that no longer applies is not shown (a tick that read new chore files with old
# code once recorded seven false problems that stayed in the digest all day)
chores = t.tmp("cm-chores-")
with open(os.path.join(chores, "fixed.md"), "w") as f:
    f.write("---\nid: fixed\nrun: true\n---\nBody.\n")
with open(os.path.join(chores, "broken.md"), "w") as f:
    f.write("---\nid: broken\nnot_a_key: x\n---\nBody.\n")
home = home_with([(ago(hours=2), "choremaster", "error", 2, "fixed.md: unknown key 'title'"),
                  (ago(hours=2), "choremaster", "error", 2, "broken.md: unknown key 'not_a_key'"),
                  (ago(hours=2), "choremaster", "error", 2, "git pull failed (using the checkout as it is): x")])
head, body = R.render_digest(home, NOW, chores_dir=chores)
check("a file problem that has since cleared is dropped", "fixed.md" not in body, body)
check("a file problem that still applies is kept", "broken.md" in body, body)
check("a tick problem that is not about a file is kept", "git pull failed" in body, body)

# retired chores are listed, and do not count as needing attention
h = t.tmp("cm-home-")
L.record(h, NOW - timedelta(hours=1), "choremaster-retire", "retired", 0, "chores: retire 2 finished chores (a, b)")
L.write_heartbeat(h, NOW - timedelta(minutes=5))
head, body = R.render_digest(h, NOW)
check("a retirement is reported and does not count as needing attention",
      "Retired finished chores" in body and "retire 2 finished chores" in body and head == "Chore Master: all clear", head + body)

# the CLI reads the service's env file when run by hand (hostmode.load), so it reads the same state directory
envf = os.path.join(t.tmp("cm-env-"), "choremaster.env")
open(envf, "w").write("# service env\nCHOREMASTER_STATE=%s\n" % home)
clean = {k: v for k, v in os.environ.items() if k != "CHOREMASTER_STATE"}
clean["CHOREMASTER_ENV_FILE"] = envf
p = subprocess.run([sys.executable, t.BIN, "report", "--chores", todo, "--now", NOW.isoformat()],
                   capture_output=True, text=True, env=clean)
check("report run with no flags reads the state directory named in the service's env file",
      p.returncode == 0 and "git pull failed" in p.stdout, (p.returncode, p.stdout[:300], p.stderr))

# the timezone sets which two local days are read: a row at 23:30 local on the 29th is in the window at 08:00 on the 30th
home = home_with([(datetime(2026, 9, 29, 22, 30, tzinfo=UTC), "late", "ran", 1, "from last night")])
check("rows from the previous local day inside 26 hours are shown", "from last night" in R.render_digest(home, NOW)[1])

t.finish()


def test_checks():
    t.assert_clean(__name__)
