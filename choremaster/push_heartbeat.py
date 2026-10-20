"""Push the scheduler's heartbeat to an orphan branch of the chores repository (optional).

A watchdog that runs somewhere else (a CI schedule, a hosted cron) can only see what is pushed, so the
scheduler publishes "I am alive" there: one file, `heartbeat.json`, on the branch `choremaster-ledger`, at
most once an hour. The branch is an orphan and a single commit that is force-pushed each time, so it never
grows and never shares history with anything. The push is made from a throwaway clone under
`<state dir>/hb-repo`: the checkout's own branch and working tree are never touched.

Off unless asked for (`tick --push-heartbeat` or CHOREMASTER_PUSH_HEARTBEAT=1). A failed push is an error
row (once a day) and returns 2; it is retried on the next tick because a failure does not count as pushed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone

from choremaster import config, ledger, schedule

BRANCH = "choremaster-ledger"
IDENT = ["-c", "user.name=Chore Master", "-c", "user.email=choremaster@localhost", "-c", "commit.gpgsign=false"]


def _git(args, cwd):
    return subprocess.run(["git"] + IDENT + args, cwd=cwd, capture_output=True, text=True, timeout=60)


def push(home: str, repo: str, now: datetime, state: dict, min_interval: timedelta = timedelta(hours=1)) -> int:
    meta = schedule.meta(state)
    last = meta.get("heartbeat_pushed_at")
    if last and now - datetime.fromisoformat(last) < min_interval:
        return 0
    if not os.path.isdir(os.path.join(repo, ".git")):
        return 0
    try:
        url = _git(["remote", "get-url", "origin"], repo)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if url.returncode != 0 or not url.stdout.strip():
        return 0

    work = os.path.join(home, "hb-repo")
    try:
        shutil.rmtree(work, ignore_errors=True)
        os.makedirs(work)
        for args in (["init", "-q"], ["remote", "add", "origin", url.stdout.strip()],
                     ["checkout", "-q", "--orphan", BRANCH]):
            r = _git(args, work)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip() or "git %s failed" % args[0])
        with open(os.path.join(work, "heartbeat.json"), "w", encoding="utf-8") as f:
            json.dump({"at": now.isoformat()}, f)
        for args in (["add", "heartbeat.json"], ["commit", "-q", "-m", "heartbeat"],
                     ["push", "-q", "--force", "origin", BRANCH]):
            r = _git(args, work)
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip() or "git %s failed" % args[0])
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
        ledger.record_once(home, now, state, "heartbeat-push", "choremaster",
                           "heartbeat push failed (will retry next tick): %s" % str(e)[:300])
        return 2
    meta["heartbeat_pushed_at"] = now.isoformat()
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Push the heartbeat to the choremaster-ledger branch of REPO's origin.")
    config.add_state_arg(ap)
    ap.add_argument("--repo", default=".", help="the git checkout whose origin receives the branch (default: .)")
    args = ap.parse_args(argv)
    home = config.state_dir(args.home)
    state = schedule.load_state(home)
    rc = push(home, os.path.abspath(args.repo), datetime.now(timezone.utc), state)
    schedule.save_state(home, state)
    return rc


if __name__ == "__main__":
    sys.exit(main())
