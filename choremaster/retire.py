"""Retire finished chores: remove the file of every chore `done_when` has ended.

A chore that is done is marked so in the state file and never runs again, but its file would stay in the
chores directory for ever. This removes it, with a day's grace: done on day D, the digest reports it on D+1,
and the file goes on D+2.

Run:  python3 -m choremaster retire [--apply | --check] [--state-dir DIR] [--chores DIR] [--repo DIR] [--base main]
  (no flag)  print the files that are due for removal, one per line. Exit 0.
  --apply    remove them in one pull request from a throwaway clone (the checkout the scheduler reads is
             never edited), arm auto-merge, and record a `retired` row in the ledger for the digest.
             Needs `git` and an authenticated GitHub CLI (`gh`) and an `origin` remote. Exit 0 done or
             nothing to do, 2 could not (also recorded, so the digest says so).
  --check    exit 1 when a chore has been done for more than 7 days and its file is still here, which means
             --apply is not running or not landing. Make it a chore of its own so a stuck retirement is
             reported every day until fixed.

No model. The morning script (bin/choremaster-morning) runs `--apply` when CHOREMASTER_RETIRE=1.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

from choremaster import config, ledger, schedule, tz
from choremaster.chorefile import load_all

GRACE_DAYS = 2          # done on D, reported D+1, removed D+2
OVERDUE_DAYS = 7
RETIRE_ID = "choremaster-retire"
BRANCH = "chore/retire-done-chores"


def _local(dt: datetime) -> date:
    return tz.today(dt)


def done_files(home: str, chores_dir: str, repo: str, now: datetime) -> Tuple[List[Tuple[str, str, int]], Optional[str]]:
    """(chore id, path relative to the repo, whole local days since done) for every done chore whose file is
    still present, oldest first. The second value is why the state could not be read, which must never look
    like 'nothing is done'."""
    state = schedule.load_state(home)
    err = schedule.meta(state).get("state_error")
    if err:
        return [], err
    if not os.path.isdir(chores_dir):
        return [], "no chores directory at %s" % chores_dir
    chores, _errors = load_all(chores_dir)
    out = []
    for c in chores:
        entry = state.get(c.id)
        if not isinstance(entry, dict) or not entry.get("done"):
            continue
        try:
            age = (_local(now) - _local(datetime.fromisoformat(entry["done_at"]))).days
        except (KeyError, ValueError, TypeError):
            continue
        out.append((c.id, os.path.relpath(c.path, repo), age))
    return sorted(out, key=lambda r: (-r[2], r[0])), None


def due(files, days: int):
    return [f for f in files if f[2] >= days]


def _run(cmd: List[str], cwd: str) -> str:
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=300)
    if p.returncode != 0:
        raise RuntimeError("%s: %s" % (" ".join(cmd[:3]), (p.stderr or p.stdout).strip()[:300]))
    return p.stdout.strip()


def apply(home: str, repo: str, now: datetime, files, base: str = "main") -> str:
    """Open (and arm) the removal PR. Returns the note for the ledger."""
    if not files:
        return ""
    open_prs = json.loads(_run(["gh", "pr", "list", "--state", "open", "--json", "headRefName,url",
                                "--limit", "100"], repo) or "[]")
    mine = [p for p in open_prs if p.get("headRefName", "").startswith(BRANCH)]
    if mine:
        return "retire PR already open, left as it is: %s" % mine[0]["url"]
    url = _run(["git", "remote", "get-url", "origin"], repo)
    work = tempfile.mkdtemp(prefix="cm-retire-")
    try:
        _run(["git", "clone", "--quiet", "--depth", "1", "--branch", base, url, work], repo)
        branch = "%s-%s" % (BRANCH, _local(now).isoformat())
        _run(["git", "checkout", "--quiet", "-b", branch], work)
        removed = []
        for cid, path, _age in files:
            if os.path.exists(os.path.join(work, path)):    # already gone on the base branch: nothing to do
                _run(["git", "rm", "--quiet", path], work)
                removed.append(cid)
        if not removed:
            return "every finished chore is already gone from %s" % base
        msg = "chores: retire %d finished chore%s (%s)" % (
            len(removed), "" if len(removed) == 1 else "s", ", ".join(removed))
        _run(["git", "commit", "--quiet", "-m", msg], work)
        _run(["git", "push", "--quiet", "-u", "origin", branch], work)
        body = ("Each chore below has `done_when` passing and was reported done at least a day ago, "
                "so Chore Master has already stopped running it.\n\n"
                + "\n".join("- `%s`" % p for _c, p, _a in files))
        pr = _run(["gh", "pr", "create", "--title", msg, "--body", body, "--base", base, "--head", branch], work)
        try:
            _run(["gh", "pr", "merge", pr, "--squash", "--auto"], work)
            return "%s: PR %s (auto-merge armed)" % (msg, pr)
        except RuntimeError as e:
            return "%s: PR %s, left open (auto-merge not armed: %s)" % (msg, pr, e)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    config.add_state_arg(ap)
    config.add_chores_arg(ap)
    ap.add_argument("--repo", default=None, help="the git checkout that holds the chores directory "
                                                   "(default: the directory above it)")
    ap.add_argument("--base", default="main", help="the branch the removal PR targets (default: main)")
    ap.add_argument("--now", default=None)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--apply", action="store_true")
    g.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    home = config.state_dir(args.home)
    chores_dir = config.chores_dir(args.chores)
    repo = os.path.abspath(args.repo) if args.repo else os.path.dirname(chores_dir)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    files, err = done_files(home, chores_dir, repo, now)
    if err:
        print("could not read what is done: %s" % err)
        return 2
    if args.check:
        late = due(files, OVERDUE_DAYS + 1)
        if not late:
            return 0
        print("%d finished chore file%s still present after %d days: retire --apply is not landing"
              % (len(late), "" if len(late) == 1 else "s", OVERDUE_DAYS))
        for cid, _p, age in late:
            print("- %s (done %d days ago)" % (cid, age))
        return 1
    ready = due(files, GRACE_DAYS)
    if not args.apply:
        for _cid, path, _age in ready:
            print(path)
        return 0
    try:
        note = apply(home, repo, now, ready, base=args.base)
    except (RuntimeError, OSError, subprocess.SubprocessError, ValueError) as e:
        ledger.record(home, now, RETIRE_ID, "error", 2, "could not retire finished chores: %s" % e)
        print("could not retire finished chores: %s" % e)
        return 2
    if note:
        ledger.record(home, now, RETIRE_ID, "retired", 0, note)
        print(note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
