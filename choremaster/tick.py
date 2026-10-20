"""The 15-minute tick. Runs with no model.

Run:  python3 -m choremaster tick [--chores DIR] [--state-dir DIR] [--workdir DIR] [--pull] [--now ISO]
Exit: 0 all fine (or another tick holds the lock, or this host is retired),
      1 some chore is outstanding or could not answer (each is named on stdout, so the journal says why),
      2 the tick itself could not do its job.

Reads the chore files, runs each due command chore, applies `done_when`, and writes the ledger, state and
heartbeat under the state directory. It never edits the chores directory.

A retired host never ticks: while the marker file `retired_marker()` exists, it prints one line and exits 0
before it takes the lock or touches the state directory. See `retired_marker`.
"""
from __future__ import annotations

import argparse
import fcntl
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from choremaster import config, ledger, paused, push_heartbeat, rule_wait, schedule, shared, tz
from choremaster.chorefile import load_all
from choremaster.runner import run_command


def retired_marker() -> str:
    """The file that retires this host's tick; its first line names the host that runs it now.
    Use it when you move the scheduler to another machine: create the file on the old one and its timer can
    stay enabled without a second scheduler writing a second ledger. It lives beside the config directory
    (not in the state directory, so copying the state to the new host cannot carry the marker with it and
    retire the new host's own tick)."""
    return os.environ.get("CHOREMASTER_RETIRED_MARKER") or os.path.expanduser("~/.config/choremaster-retired-host")


def retired_line(marker: str) -> Optional[str]:
    """None when this host is live; else the one line the retired tick prints."""
    try:
        with open(marker) as f:
            host = f.readline().strip()
    except FileNotFoundError:
        return None
    except OSError:
        host = ""  # unreadable is still there: a retired host must not tick on a guess
    return ("this host's Chore Master is retired and runs on %s; this tick recorded nothing. "
            "To undo, delete %s" % (host or "another machine", marker))


def with_extra_path(env: dict) -> dict:
    """Append the directories in CHOREMASTER_EXTRA_PATH (colon-separated) to PATH when they are not on it.
    A launchd or systemd job starts with a minimal PATH that lacks /usr/local/bin or /opt/homebrew/bin."""
    env = dict(env)
    extra = [p for p in (env.get("CHOREMASTER_EXTRA_PATH") or "").split(os.pathsep) if p]
    if extra:
        have = [p for p in env.get("PATH", "").split(os.pathsep) if p]
        env["PATH"] = os.pathsep.join(have + [p for p in extra if p not in have])
    return env


_LOCK_FD = None


def acquire_lock(home: str) -> bool:
    """One tick at a time, by `flock` on a held descriptor. The kernel releases it when the holder dies, so
    there is no pid to check, no age to compare and no wall clock involved. The file is never unlinked:
    unlinking while another process locks the old inode is the classic way to lose mutual exclusion."""
    global _LOCK_FD
    os.makedirs(home, exist_ok=True)
    fd = os.open(os.path.join(home, "tick.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return False
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    _LOCK_FD = fd
    return True


def wait_for_lock(home: str, seconds: int, poll: float = 2.0) -> bool:
    """acquire_lock, tried every `poll` seconds for up to `seconds` (0: one try)."""
    deadline = time.monotonic() + seconds
    while not acquire_lock(home):
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll)
    return True


def release_lock(home: str) -> None:
    global _LOCK_FD
    if _LOCK_FD is not None:
        try:
            os.close(_LOCK_FD)
        except OSError:
            pass
        _LOCK_FD = None


def say(msg: str) -> None:
    """One line to stdout, flushed: under systemd that is the journal. The ledger holds the full record, but
    a non-zero exit with an empty journal looks like a crash."""
    print("choremaster: " + msg, flush=True)


def _first_line(body: str) -> str:
    for line in body.splitlines():
        if line.strip():
            return line.strip()
    return "(no description)"


def _env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    config.add_state_arg(ap)
    config.add_chores_arg(ap)
    ap.add_argument("--workdir", default=None,
                    help="the directory chore commands run in (default: the directory above the chores directory)")
    ap.add_argument("--now", default=None)
    ap.add_argument("--pull", action="store_true",
                    help="first fetch and fast-forward the git checkout in --workdir (it never merges or rebases)")
    ap.add_argument("--lock-wait", type=int, default=0,
                    help="seconds to wait for another tick's lock (default 0: one try)")
    ap.add_argument("--chore-timeout", type=int, default=600)
    ap.add_argument("--respect-waits", action="store_true",
                    help="do not run chores marked `waits:`; report them as not checked (see rule_wait.py)")
    ap.add_argument("--push-heartbeat", action="store_true",
                    help="also push the heartbeat to the choremaster-ledger branch of the workdir's origin "
                         "(or set CHOREMASTER_PUSH_HEARTBEAT=1)")
    args = ap.parse_args(argv)

    retired = retired_line(retired_marker())
    if retired:  # before the lock and the home: a retired host writes no ledger, state or heartbeat
        say(retired)
        return 0

    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    home = config.state_dir(args.home)
    args.chores_dir = config.chores_dir(args.chores)
    args.workdir = os.path.abspath(args.workdir) if args.workdir else os.path.dirname(args.chores_dir)
    env = with_extra_path(dict(os.environ))

    if not wait_for_lock(home, args.lock_wait):
        print("choremaster: another tick holds the lock; nothing to do")
        return 0
    try:
        return _tick(args, now, home, env)
    except Exception as e:  # a crash leaves a ledger row and a state file, never only a log line
        ledger.record(home, now, "choremaster", "error", 2, "the tick crashed: %s: %s" % (type(e).__name__, e))
        say("the tick crashed: %s: %s (exiting 2)" % (type(e).__name__, e))
        return 2
    finally:
        release_lock(home)


def _q(path: str) -> str:
    return "'" + path.replace("'", "'\\''") + "'"


def _tick(args, now: datetime, home: str, env: dict) -> int:
    pull_failed = None
    if args.pull and os.path.isdir(os.path.join(args.workdir, ".git")):
        # Fetch, then fast-forward to the upstream REF, not `git pull`: pull merges whatever FETCH_HEAD lists,
        # and concurrent fetchers in one checkout can leave it listing `main` twice, so pull refuses with
        # "Cannot fast-forward to multiple branches" and the tick runs on a stale checkout. The ref cannot be
        # listed twice.
        r = run_command("git -C %s fetch -q origin && git -C %s merge --ff-only -q '@{u}'"
                        % (_q(args.workdir), _q(args.workdir)), args.workdir, timeout=60, env=env)
        if r.code != 0:
            pull_failed = r.output.strip()

    state = schedule.load_state(home)
    worst = 0
    outstanding = []

    def once(key: str, chore_id: str, note: str) -> None:
        ledger.record_once(home, now, state, key, chore_id, note)

    if schedule.meta(state).get("state_error"):
        once("state", "choremaster", schedule.meta(state)["state_error"])
    if tz.problem():
        once("tz", "choremaster", tz.problem())

    if pull_failed is not None:
        once("pull", "choremaster", "git pull failed (using the checkout as it is): " + pull_failed)

    push_hb = args.push_heartbeat or _env_flag("CHOREMASTER_PUSH_HEARTBEAT")
    chores_dir = args.chores_dir
    if not os.path.isdir(chores_dir):
        once("nochores", "choremaster", "no chores directory at %s" % chores_dir)
        ledger.write_heartbeat(home, now)
        if push_hb:
            push_heartbeat.push(home, args.workdir, now, state)
        schedule.save_state(home, state)
        return 2

    chores, errors = load_all(chores_dir)
    for e in errors:
        once("file:%s:%s" % (e.path, e), "choremaster", "%s: %s" % (os.path.basename(e.path), e))

    respect_waits = args.respect_waits or rule_wait.respects_waits()
    for chore in chores:
        if not schedule.is_due(chore, state, now):
            continue
        if chore.waits and respect_waits:
            code, note = rule_wait.wait(chore.waits[0], chore.waits[1], home=home, now=now.timestamp())
            schedule.mark_ran(state, chore.id, now, code)
            ledger.record(home, now, chore.id, "ran", code, note)
            worst = 1
            outstanding.append(chore.id)
            say("chore %s waits: %s" % (chore.id, note))
            continue
        if chore.done_when:
            d = run_command(chore.done_when, args.workdir, timeout=args.chore_timeout, env=env)
            if d.code == 0:
                schedule.mark_done(state, chore.id, now)
                ledger.record(home, now, chore.id, "done", 0, d.output.strip())
                continue
            if d.code == 2:
                ledger.record(home, now, chore.id, "error", 2,
                              "done_when could not answer (chore stays open): " + d.output.strip())
        if chore.run:
            # CHOREMASTER_CHORE names the chore to the command, so a wrapper it calls (an API shim, a
            # logging proxy) can attribute the call to it.
            r = run_command(chore.run, args.workdir, timeout=args.chore_timeout,
                            env=dict(env, CHOREMASTER_CHORE=chore.id))
            code, note = r.code, r.output.strip()
            if not chore.names_paused:
                code, note = paused.drop(code, note)
        else:
            code, note = 1, _first_line(chore.body)   # a reminder: outstanding until its file is removed
        schedule.mark_ran(state, chore.id, now, code)
        ledger.record(home, now, chore.id, "ran", code, note)
        if code != 0:
            worst = 1
            outstanding.append(chore.id)
            say("chore %s reported outstanding (exit %d): %s" % (chore.id, code, _first_line(note)))

    ledger.write_heartbeat(home, now)
    if push_hb:
        push_heartbeat.push(home, args.workdir, now, state)
    # The read-only copy other accounts read (shared.py): one way, after the tick's own rows are in.
    if shared.available():
        try:
            ledger.publish(home, now, {c.id for c in chores if c.private})
        except (OSError, ValueError) as e:
            once("shared", "choremaster", "could not copy the ledger to %s: %s" % (shared.root(), e))
    schedule.save_state(home, state)
    if worst:
        say("exiting 1: %d chore(s) outstanding, not a tick failure (%s); the ledger has the detail"
            % (len(outstanding), ", ".join(outstanding)))
    return worst


if __name__ == "__main__":
    sys.exit(main())
