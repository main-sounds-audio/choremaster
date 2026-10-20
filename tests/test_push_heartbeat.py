#!/usr/bin/env python3
"""Tests choremaster/push_heartbeat.py.

Real git against a local bare repo standing in for origin. The checkout's own
working tree must never be touched: the push works from a throwaway clone.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import _testkit as t  # noqa: E402
from choremaster import ledger as L, push_heartbeat as P  # noqa: E402

check = t.check
UTC = timezone.utc
NOW = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)
IDENT = ["-c", "user.email=t@example.invalid", "-c", "user.name=t", "-c", "commit.gpgsign=false"]


def git(*args, cwd=None):
    return subprocess.run(["git", *IDENT, *args], cwd=cwd, capture_output=True, text=True)


def world():
    """(repo, bare, home): a checkout whose origin is a local bare repo."""
    root = t.tmp("cm-hb-")
    bare = os.path.join(root, "origin.git")
    repo = os.path.join(root, "repo")
    subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
    subprocess.run(["git", "init", "-q", repo], check=True)
    open(os.path.join(repo, "f"), "w").write("x")
    git("add", "f", cwd=repo)
    git("commit", "-q", "-m", "init", cwd=repo)
    git("remote", "add", "origin", bare, cwd=repo)
    return repo, bare, t.tmp("cm-home-")


def remote_file(bare):
    out = subprocess.run(["git", "--git-dir", bare, "show", "choremaster-ledger:heartbeat.json"],
                         capture_output=True, text=True)
    return json.loads(out.stdout) if out.returncode == 0 else None


def remote_sha(bare):
    out = subprocess.run(["git", "--git-dir", bare, "rev-parse", "choremaster-ledger"], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else None


repo, bare, home = world()
head_before = git("rev-parse", "HEAD", cwd=repo).stdout
st = {}
rc = P.push(home, repo, NOW, st)
check("a push returns 0", rc == 0, rc)
hb = remote_file(bare)
check("the branch choremaster-ledger has heartbeat.json with the tick time", hb and hb["at"] == NOW.isoformat(), hb)
tree = subprocess.run(["git", "--git-dir", bare, "ls-tree", "-r", "--name-only", "choremaster-ledger"],
                      capture_output=True, text=True).stdout.split()
check("the branch holds only heartbeat.json (an orphan, no repo files)", tree == ["heartbeat.json"], tree)
count = subprocess.run(["git", "--git-dir", bare, "rev-list", "--count", "choremaster-ledger"],
                       capture_output=True, text=True).stdout.strip()
check("and is a single commit", count == "1", count)
check("the checkout's HEAD and working tree are untouched",
      git("rev-parse", "HEAD", cwd=repo).stdout == head_before and git("status", "--porcelain", cwd=repo).stdout == ""
      and git("branch", "--show-current", cwd=repo).stdout.strip() != "choremaster-ledger")
first = remote_sha(bare)

P.push(home, repo, NOW + timedelta(minutes=30), st)
check("a second push within the hour does nothing", remote_sha(bare) == first)
check("and does not move the heartbeat", remote_file(bare)["at"] == NOW.isoformat())
P.push(home, repo, NOW + timedelta(minutes=61), st)
check("after an hour it pushes again", remote_sha(bare) != first and remote_file(bare)["at"] ==
      (NOW + timedelta(minutes=61)).isoformat(), remote_file(bare))
count = subprocess.run(["git", "--git-dir", bare, "rev-list", "--count", "choremaster-ledger"],
                       capture_output=True, text=True).stdout.strip()
check("the branch never grows (still one commit)", count == "1", count)

# no origin: skip quietly
repo2 = t.tmp("cm-repo-")
subprocess.run(["git", "init", "-q", repo2], check=True)
home2, st2 = t.tmp("cm-home-"), {}
check("a checkout with no origin skips quietly (0, no error row)",
      P.push(home2, repo2, NOW, st2) == 0 and not L.read_day(home2, date(2026, 9, 30)))
check("a directory that is not a git checkout skips quietly",
      P.push(home2, t.tmp("cm-plain-"), NOW, st2) == 0)

# failure is recorded, not raised
repo3, bare3, home3 = world()
git("remote", "set-url", "origin", os.path.join(t.tmp(), "does-not-exist.git"), cwd=repo3)
st3 = {}
rc = P.push(home3, repo3, NOW, st3)
check("a failing push returns 2 without raising", rc == 2, rc)
errs = [r for r in L.read_day(home3, date(2026, 9, 30)) if r["kind"] == "error"]
check("and records an error row", errs and "heartbeat" in errs[0]["note"], errs)
P.push(home3, repo3, NOW + timedelta(minutes=15), st3)
check("the error is recorded once per day",
      len([r for r in L.read_day(home3, date(2026, 9, 30)) if r["kind"] == "error"]) == 1)
check("a failed push does not count as pushed (it retries next tick)", "heartbeat_pushed_at" not in st3.get("_meta", {}), st3)

t.finish()


def test_checks():
    t.assert_clean(__name__)
