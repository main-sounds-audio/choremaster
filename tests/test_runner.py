#!/usr/bin/env python3
"""Tests choremaster/runner.py.

A chore command that hangs must time out, record exit 2, kill
its whole process group, and leave the other chores to run.
"""
from __future__ import annotations

import os
import sys
import time

import _testkit as t  # noqa: E402
from choremaster.runner import run_command  # noqa: E402

check = t.check
cwd = t.tmp()

for code in (0, 1, 2):
    r = run_command("exit %d" % code, cwd)
    check("exit %d passes through" % code, r.code == code and not r.timed_out, r)
for code in (3, 127, 255):
    r = run_command("exit %d" % code, cwd)
    check("exit %d becomes 2 (could not answer)" % code, r.code == 2, r)
r = run_command("kill -9 $$", cwd)
check("a command killed by a signal becomes 2", r.code == 2, r)

r = run_command("echo hello; echo oops >&2", cwd)
check("stdout and stderr are both captured", "hello" in r.output and "oops" in r.output, r.output)

pidfile = os.path.join(cwd, "pids")
t0 = time.time()
r = run_command("echo $$ > %s; sleep 30 & echo $! >> %s; wait" % (pidfile, pidfile), cwd, timeout=1)
took = time.time() - t0
check("a hung command times out with code 2", r.timed_out and r.code == 2, r)
check("and returns promptly (the 30 s sleep is not waited for)", took < 10, took)
time.sleep(0.3)
dead = []
for line in open(pidfile).read().split():
    try:
        os.kill(int(line), 0)
        dead.append(False)
    except ProcessLookupError:
        dead.append(True)
    except PermissionError:
        dead.append(False)
check("the whole process group is killed, background child included", dead and all(dead), dead)

r = run_command("true", os.path.join(cwd, "no-such-dir"))
check("a missing working directory is code 2, not a crash", r.code == 2 and r.output, r)
r = run_command("definitely-not-a-command-xyz", cwd)
check("a missing command is code 2, not a crash", r.code == 2, r)

r = run_command("python3 -c \"print('x' * 20000)\"", cwd)
check("output is truncated to 4000 characters", 0 < len(r.output) <= 4100, len(r.output))
r = run_command("python3 -c \"print('SUMMARY'); print('x' * 20000); print('THE-END')\"", cwd)
check("a long output keeps its first line (the summary) and its last (the reason), and the whole of it is in .full",
      r.output.startswith("SUMMARY") and r.output.rstrip().endswith("THE-END") and len(r.full) > 20000, (r.output[:20], r.output[-20:]))
r = run_command("python3 -c \"raise KeyError('boom')\"", cwd)
check("an uncaught Python exception (exit 1) is 'could not answer' naming the error, not a finding",
      r.code == 2 and r.output.startswith("crashed: KeyError") and "boom" in r.output, r)
r = run_command("echo 'a finding'; exit 1", cwd)
check("an ordinary exit 1 stays a finding", r.code == 1, r)
r = run_command("echo $CM_PROBE", cwd, env={"PATH": os.environ["PATH"], "CM_PROBE": "seen"})
check("env is passed through", "seen" in r.output, r.output)

# --- a timed-out command whose grandchild keeps stdout open must not hang the tick
t0 = time.time()
r = run_command("python3 -c \"import subprocess; subprocess.Popen(['sleep','25'], start_new_session=True)\"; sleep 25",
                cwd, timeout=1)
took = time.time() - t0
check("a grandchild that escaped the process group and holds the pipe does not hang the runner",
      r.timed_out and r.code == 2 and took < 15, (r, took))

t.finish()


def test_checks():
    t.assert_clean(__name__)
