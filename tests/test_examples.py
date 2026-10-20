#!/usr/bin/env python3
"""Tests examples/chores: every example loads, and each one answers the way its file says."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from datetime import date, datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import _testkit as t
from choremaster import ledger as L, tick
from choremaster.chorefile import load_all

check = t.check
EXAMPLES = os.path.join(t.ROOT, "examples", "chores")
NOW = datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc)
DAY = date(2026, 9, 30)

chores, errors = load_all(EXAMPLES)
check("every example chore loads", not errors and len(chores) >= 3, [str(e) for e in errors])
check("there are three to four of them", 3 <= len(chores) <= 4, [c.id for c in chores])
check("each has a title and a body", all(c.title and c.body.strip() for c in chores))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/up" else 503)
        self.end_headers()

    def log_message(self, *a):
        pass


server = HTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
port = server.server_address[1]


def run_tick(env_extra, now=NOW):
    state = t.tmp("cm-ex-state-")
    env = dict(os.environ, **env_extra)
    p = subprocess.run([sys.executable, t.BIN, "tick", "--chores", EXAMPLES, "--state-dir", state, "--now", now.isoformat(),
                        "--chore-timeout", "20"], capture_output=True, text=True, env=env, timeout=120)
    rows = {r["id"]: r for r in L.read_day(state, DAY) if r["kind"] in ("ran", "done")}
    return p, rows


clean_repo = t.tmp("cm-ex-repo-")
subprocess.run(["git", "init", "-q", clean_repo], check=True)
marker = os.path.join(t.tmp("cm-ex-marker-"), "rotated")
good = {"CHECK_URL": "http://127.0.0.1:%d/up" % port, "REPO_PATH": clean_repo, "MAX_PERCENT": "101",
        "KEY_ROTATED_MARKER": marker}
p, rows = run_tick(good)
check("disk-space is clean under a limit of 101%", rows["disk-space"]["code"] == 0, rows.get("disk-space"))
check("url-answers is clean against a server that answers 200", rows["url-answers"]["code"] == 0, rows.get("url-answers"))
check("git-clean is clean on an empty repository (after 09:00)", rows["git-clean"]["code"] == 0, rows.get("git-clean"))
check("the reminder is outstanding until its marker exists", rows["rotate-key-reminder"]["code"] == 1, rows.get("rotate-key-reminder"))

open(marker, "w").write("")
p, rows = run_tick(good)
check("the reminder is done once its done_when passes", rows.get("rotate-key-reminder", {}).get("kind") == "done", rows.get("rotate-key-reminder"))

bad = {"CHECK_URL": "http://127.0.0.1:%d/down" % port, "REPO_PATH": clean_repo, "MAX_PERCENT": "0",
       "KEY_ROTATED_MARKER": marker}
open(os.path.join(clean_repo, "dirty.txt"), "w").write("x")
p, rows = run_tick(bad)
check("disk-space reports a finding when the limit is 0%", rows["disk-space"]["code"] == 1 and "full" in rows["disk-space"]["note"], rows["disk-space"])
check("url-answers reports the status it got", rows["url-answers"]["code"] == 1 and "503" in rows["url-answers"]["note"], rows["url-answers"])
check("git-clean lists the dirty files as bullets", rows["git-clean"]["code"] == 1 and "- ?? dirty.txt" in rows["git-clean"]["note"], rows["git-clean"])
check("and the tick exits 1, naming them", p.returncode == 1 and "git-clean" in p.stdout, p.stdout)

nogit = t.tmp("cm-ex-nogit-")
p, rows = run_tick(dict(good, REPO_PATH=nogit, CHECK_URL="http://127.0.0.1:%d/up" % port))
check("git-clean on something that is not a repository could not answer (2), never clean", rows["git-clean"]["code"] == 2, rows["git-clean"])

p, rows = run_tick(good, datetime(2026, 9, 30, 6, 0, tzinfo=timezone.utc))
check("`after: 09:00` keeps git-clean from running at 07:00 local", "git-clean" not in rows, rows.keys())

server.shutdown()
t.finish()


def test_checks():
    t.assert_clean(__name__)
