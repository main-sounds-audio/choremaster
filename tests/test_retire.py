#!/usr/bin/env python3
"""Tests choremaster/retire.py: finished chores' files are removed after a day's grace.

Failure modes that look fine and are not: removing a chore that is not done, removing on the day it finished
(nobody sees it finish), an unreadable state read as 'nothing done', a failed removal that leaves no trace in
the digest, and the watchdog staying silent while the removal quietly never lands.
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import _testkit as t
from choremaster import ledger as L, report as R, retire as RT, schedule as S

check = t.check
UTC = timezone.utc
NOW = datetime(2026, 10, 3, 7, 0, tzinfo=UTC)


def repo_with(ids):
    repo = t.tmp("cm-repo-")
    os.makedirs(os.path.join(repo, "chores"))
    for i in ids:
        with open(os.path.join(repo, "chores", i + ".md"), "w") as f:
            f.write("---\nid: %s\nrun: true\n---\nbody\n" % i)
    return repo


def home_done(done):
    """done: {id: days ago it was marked done}"""
    home = t.tmp("cm-home-")
    state = {}
    for cid, days in done.items():
        S.mark_done(state, cid, NOW - timedelta(days=days))
    S.save_state(home, state)
    return home


def run(args, home, repo):
    return subprocess.run([sys.executable, t.BIN, "retire", "--state-dir", home, "--chores", os.path.join(repo, "chores"),
                           "--repo", repo, "--now", NOW.isoformat()] + args, capture_output=True, text=True)


def files_of(home, repo):
    return RT.done_files(home, os.path.join(repo, "chores"), repo, NOW)


repo = repo_with(["fresh", "grace", "old", "notdone", "ancient"])
home = home_done({"fresh": 0, "grace": 1, "old": 2, "ancient": 9})
files, err = files_of(home, repo)
ready = [c for c, _p, _a in RT.due(files, RT.GRACE_DAYS)]
check("done on the day it is reported (age 1) is kept: the reader sees it finish first", "grace" not in ready, ready)
check("done today is kept", "fresh" not in ready, ready)
check("done two days ago is due", "old" in ready and "ancient" in ready, ready)
check("a chore that is not done is never due", "notdone" not in ready, ready)
check("oldest first", ready == ["ancient", "old"], ready)

p = run([], home, repo)
check("no flag prints the due paths and removes nothing", p.stdout.split() == ["chores/ancient.md", "chores/old.md"]
      and os.path.exists(os.path.join(repo, "chores", "old.md")), p.stdout + p.stderr)

# a done chore whose file is already gone is not a candidate
check("a done chore with no file is not listed", "gone" not in [c for c, _p, _a in files])
home2 = home_done({"gone": 5})
check("nothing due when the file is already removed", files_of(home2, repo)[0] == [])

# unreadable state is could-not-answer, never 'nothing done'
bad = t.tmp("cm-home-")
open(os.path.join(bad, S.STATE), "w").write("{not json")
p = run([], bad, repo)
check("an unreadable state exits 2 and says why", p.returncode == 2 and "unreadable" in p.stdout, p.stdout)
check("so does --check", run(["--check"], bad, repo).returncode == 2)
check("a missing chores directory is could-not-answer too", run([], home, t.tmp("cm-empty-")).returncode == 2)

# the watchdog: more than 7 days
p = run(["--check"], home, repo)
check("--check fires on a file done more than 7 days ago", p.returncode == 1 and "ancient" in p.stdout, p.stdout)
check("and does not name one inside the week", "old (" not in p.stdout, p.stdout)
check("--check is clean when nothing is overdue", run(["--check"], home_done({"old": 3}), repo).returncode == 0)
check("--check at exactly 7 days is clean (grace is 7, not 6)", run(["--check"], home_done({"old": 7}), repo).returncode == 0)

# --apply failures are recorded for the digest, never silent
nogit = repo_with(["old"])
home3 = home_done({"old": 3})
p = run(["--apply"], home3, nogit)
check("--apply outside a git repo exits 2", p.returncode == 2, p.stdout + p.stderr)
rows = L.read_day(home3, NOW.date())
check("and records an error row the digest will show", any(r["id"] == RT.RETIRE_ID and r["kind"] == "error" for r in rows), rows)
check("--apply with nothing due prints nothing and exits 0",
      (lambda q: q.returncode == 0 and q.stdout == "")(run(["--apply"], home_done({"fresh": 0}), repo)))

# digest
h = t.tmp("cm-home-")
L.record(h, NOW - timedelta(hours=1), RT.RETIRE_ID, "retired", 0, "chores: retire 2 finished chores (a, b): PR https://x/1 (auto-merge armed)")
L.write_heartbeat(h, NOW - timedelta(minutes=5))
head, body = R.render_digest(h, NOW)
check("the digest reports a retirement and does not count it as needing attention",
      "Retired finished chores" in body and "retire 2 finished chores" in body and head == "Chore Master: all clear", head + body)
L.record(h, NOW - timedelta(minutes=30), RT.RETIRE_ID, "error", 2, "could not retire finished chores: boom")
check("a failed retirement is a problem in the digest", "problem: could not retire" in R.render_digest(h, NOW)[1])

# the morning script runs it, between the tick and the digest, only when asked
morning = open(os.path.join(t.ROOT, "bin", "choremaster-morning")).read()
check("the morning run does retire --apply between the tick and the digest, and only when CHOREMASTER_RETIRE=1",
      morning.index("tick") < morning.index("retire --apply") < morning.index("report") and "CHOREMASTER_RETIRE:-0" in morning, None)


# end to end against a local remote and a stub gh: the file really leaves a pushed branch
def sh(*a, cwd=None):
    return subprocess.run(a, cwd=cwd, capture_output=True, text=True, check=True).stdout


gx = t.tmp("cm-git-")
bare = os.path.join(gx, "origin.git")
sh("git", "init", "--bare", "-b", "main", bare)
seed = os.path.join(gx, "seed")
sh("git", "clone", bare, seed)
os.makedirs(os.path.join(seed, "chores"))
for i in ("old", "live"):
    open(os.path.join(seed, "chores", i + ".md"), "w").write("---\nid: %s\nrun: true\n---\nb\n" % i)
env_git = ["-c", "user.name=t", "-c", "user.email=t@example.com"]
sh("git", *env_git, "add", ".", cwd=seed)
sh("git", *env_git, "commit", "-m", "seed", cwd=seed)
sh("git", "push", "origin", "HEAD:main", cwd=seed)
checkout = os.path.join(gx, "checkout")
sh("git", "clone", bare, checkout)
stub = t.tmp("cm-bin-")
open(os.path.join(stub, "gh"), "w").write(
    "#!/bin/sh\ncase \"$2\" in list) echo '[]';; create) echo https://example.test/pull/1;; *) ;; esac\n")
os.chmod(os.path.join(stub, "gh"), 0o755)
os.environ["PATH"] = stub + os.pathsep + os.environ["PATH"]
os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
home4 = home_done({"old": 3, "live": 0})
p = run(["--apply"], home4, checkout)
check("--apply succeeds against a real remote", p.returncode == 0 and "auto-merge armed" in p.stdout, p.stdout + p.stderr)
branches = sh("git", "branch", "--list", "chore/retire-done-chores-*", cwd=bare)
check("it pushed a branch", "chore/retire-done-chores-2026-10-03" in branches, branches)
tree = sh("git", "ls-tree", "-r", "--name-only", "chore/retire-done-chores-2026-10-03", cwd=bare)
check("the branch drops the done chore and keeps the live one", "chores/old.md" not in tree and "chores/live.md" in tree, tree)
check("the checkout the scheduler reads is untouched", os.path.exists(os.path.join(checkout, "chores", "old.md")))
check("a retired row is in the ledger", any(r["kind"] == "retired" for r in L.read_day(home4, NOW.date())))

t.finish()


def test_checks():
    t.assert_clean(__name__)
