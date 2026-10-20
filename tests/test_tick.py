#!/usr/bin/env python3
"""Tests choremaster/tick.py.

Broken chore files are recorded, overlapping ticks do not overlap, a hung chore does not stop the rest, and
a done_when that cannot answer never marks a chore done: all named cases below.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import date, datetime, timedelta, timezone

import _testkit as t
from choremaster import ledger as L, paused, schedule as S, tick

check = t.check
UTC = timezone.utc
NOW = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)
DAY = date(2026, 9, 30)


def fixture(chores):
    """A workdir with chores/ and a marker-writing helper. Returns (repo, home)."""
    repo, home = t.tmp("cm-repo-"), t.tmp("cm-home-")
    os.makedirs(os.path.join(repo, "chores"))
    for name, text in chores.items():
        with open(os.path.join(repo, "chores", name + ".md"), "w") as f:
            f.write(text.replace("{REPO}", repo))
    return repo, home


def chore(cid, run=None, done_when=None, extra="", body="Body.\n"):
    lines = ["---", "id: " + cid]
    if run:
        lines.append("run: " + run)
    if done_when:
        lines.append("done_when: " + done_when)
    if extra:
        lines.append(extra)
    return "\n".join(lines + ["---", body])


def tick_args(repo, home, now=NOW, *more):
    return ["--state-dir", home, "--chores", os.path.join(repo, "chores"), "--now", now.isoformat(),
            "--chore-timeout", "5", *more]


def go(repo, home, now=NOW, *more):
    return tick.main(tick_args(repo, home, now, *more))


def cli(repo, home, now=NOW, *more, env=None):
    """The tick as a real process, the way a timer runs it."""
    return subprocess.run([sys.executable, t.BIN, "tick", *tick_args(repo, home, now, *more)],
                          capture_output=True, text=True, env=env or dict(os.environ), timeout=60)


def rows(home, day=DAY):
    return L.read_day(home, day)


def ran(home, cid, day=DAY):
    return [r for r in rows(home, day) if r["id"] == cid and r["kind"] == "ran"]


# --- which chores run
repo, home = fixture({
    "due": chore("due", run="echo hi > {REPO}/due.marker"),
    "later": chore("later", run="echo hi > {REPO}/later.marker", extra="due: 2026-10-01T08:00:00Z"),
})
rc = go(repo, home)
check("runs a due chore", os.path.exists(os.path.join(repo, "due.marker")) and rc == 0, rc)
check("does not run a chore that is not due yet", not os.path.exists(os.path.join(repo, "later.marker")))
check("a run is recorded in the ledger with its exit code", ran(home, "due") and ran(home, "due")[0]["code"] == 0)
go(repo, home, NOW + timedelta(minutes=15))
check("a chore that ran is not run again 15 minutes later", len(ran(home, "due")) == 1)

repo, home = fixture({"wd": chore("wd", run="pwd > wd.out")})
go(repo, home)
check("by default chore commands run in the directory above chores/",
      open(os.path.join(repo, "wd.out")).read().strip() == os.path.realpath(repo))
repo, home = fixture({"wd": chore("wd", run="pwd > wd.out")})
other = t.tmp("cm-workdir-")
go(repo, home, NOW, "--workdir", other)
check("--workdir sets where chore commands run",
      os.path.exists(os.path.join(other, "wd.out")) and not os.path.exists(os.path.join(repo, "wd.out")))

repo, home = fixture({"who": chore("who", run="echo $CHOREMASTER_CHORE > {REPO}/who.out")})
go(repo, home)
check("the chore's id is in CHOREMASTER_CHORE for wrappers that attribute calls",
      open(os.path.join(repo, "who.out")).read().strip() == "who")

# --- paused names: no chore output names one; the chore that reports on them is the exception
PAUSED = os.path.join(t.tmp("cm-paused-"), "paused.txt")
open(PAUSED, "w").write("# test\nold-service  mothballed\nretired-box  gone\n")
os.environ["CHOREMASTER_PAUSED_FILE"] = PAUSED
only = "printf '1 open thing\\n- acme/old-service#3 Fold the hand\\n'; exit 1"
mixed = ("printf '3 open things\\n- acme/alpha#1 Keep me\\n- /srv/old-service-wt/proc: dirty\\n"
         "- retired-box#9 Refresh\\n'; exit 1")
repo, home = fixture({"only": chore("only", run=only), "mixed": chore("mixed", run=mixed),
                      "watch": chore("watch", run=only, extra="names_paused: true")})
go(repo, home)
r = ran(home, "only")[0]
check("a finding naming only paused names is no finding: exit 0, nothing recorded", r["code"] == 0 and "old-service" not in str(r), r)
r = ran(home, "mixed")[0]
check("a mixed finding keeps its other bullets and loses every paused-name line (worktree paths too)",
      r["code"] == 1 and "alpha#1" in str(r) and "old-service" not in str(r) and "retired-box" not in str(r), r)
check("the summary's count is recounted to the bullets left", r["note"].startswith("1 open things"), r)
r = ran(home, "watch")[0]
check("names_paused: true passes the output through", r["code"] == 1 and "old-service#3" in str(r), r)
check("a name inside another word is not a mention", paused.drop(1, "1 x\n- not-old-service#1 y", {"old-service"})[0] == 1)
del os.environ["CHOREMASTER_PAUSED_FILE"]

# --- exit codes and the tick's return
repo, home = fixture({"bad": chore("bad", run="echo nope; exit 1")})
check("a chore reporting outstanding makes the tick return 1", go(repo, home) == 1)
check("and its output is in the ledger note", "nope" in ran(home, "bad")[0]["note"])

# --- done_when
repo, home = fixture({"fin": chore("fin", run="echo x > {REPO}/main.marker", done_when="true")})
go(repo, home)
kinds = [r["kind"] for r in rows(home)]
check("done_when exiting 0 records done", "done" in kinds, kinds)
check("and marks the chore done in state", S.load_state(home)["fin"].get("done") is True)
check("and the main command is not run once it is done", not os.path.exists(os.path.join(repo, "main.marker")))
go(repo, home, NOW + timedelta(days=3))
check("a done chore is never run again", not os.path.exists(os.path.join(repo, "main.marker")))

for label, dw in (("exiting 2", "exit 2"), ("crashing (command missing)", "definitely-not-a-command-xyz")):
    repo, home = fixture({"g": chore("g", run="echo ran > {REPO}/g.marker", done_when=dw)})
    go(repo, home)
    check("done_when %s does NOT mark the chore done" % label, not S.load_state(home)["g"].get("done"))
    check("and the main command still runs (a broken check must not switch the chore off)",
          os.path.exists(os.path.join(repo, "g.marker")))

# --- broken files
repo, home = fixture({"good": chore("good", run="true"), "broken": "---\nid: x\nsurprise: 1\n---\n",
                      "dup": chore("good", run="true")})
go(repo, home)
errs = [r for r in rows(home) if r["kind"] == "error"]
check("a broken chore file is recorded as an error row", any("broken.md" in r["note"] for r in errs), errs)
check("a duplicate id is recorded as an error row", any("duplicate" in r["note"] for r in errs), errs)
check("the good chore still ran", ran(home, "good"))
n = len(errs)
go(repo, home, NOW + timedelta(minutes=15))
check("the same error is recorded once per day, not every tick",
      len([r for r in rows(home) if r["kind"] == "error"]) == n)

# --- locking (flock on a held descriptor: no pid liveness, no age, no wall clock)


def can_lock(home_dir):
    fd = os.open(os.path.join(home_dir, "tick.lock"), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


repo, home = fixture({"a": chore("a", run="echo x > {REPO}/lock.marker")})
os.makedirs(home, exist_ok=True)
held = os.open(os.path.join(home, "tick.lock"), os.O_CREAT | os.O_RDWR, 0o600)
fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
rc = go(repo, home)
check("a second tick exits cleanly while another holds the lock", rc == 0, rc)
check("and runs nothing", not os.path.exists(os.path.join(repo, "lock.marker")))
check("and leaves the other tick's lock held", not can_lock(home))
ancient = 1_000_000_000
os.utime(os.path.join(home, "tick.lock"), (ancient, ancient))
rc = go(repo, home)
check("a held lock is respected however old the file looks (there is no age rule to take over a live lock)",
      rc == 0 and not os.path.exists(os.path.join(repo, "lock.marker")))
os.close(held)
open(os.path.join(home, "tick.lock"), "w").write("999999")     # a leftover file with a dead pid and NO lock held
go(repo, home)
check("a leftover lock file that nobody holds is simply taken (a crashed tick needs no cleanup)",
      os.path.exists(os.path.join(repo, "lock.marker")))
check("and the lock is released when the tick ends", can_lock(home))
os.remove(os.path.join(repo, "lock.marker"))
open(os.path.join(home, "tick.lock"), "w").close()               # an EMPTY lock file
go(repo, home, NOW + timedelta(days=1))                              # next day: the chore is due again
check("an empty lock file that nobody holds is not mistaken for a held lock", os.path.exists(os.path.join(repo, "lock.marker")))

# --- --lock-wait: a tick that must run waits for the lock instead of skipping
repo, home = fixture({"w1": chore("w1", run="echo x > {REPO}/wait.marker")})
os.makedirs(home, exist_ok=True)
held = os.open(os.path.join(home, "tick.lock"), os.O_CREAT | os.O_RDWR, 0o600)
fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
threading.Timer(1.0, os.close, [held]).start()                 # the other tick finishes a second later
rc = go(repo, home, NOW, "--lock-wait", "20")
check("--lock-wait waits for a held lock and then runs", os.path.exists(os.path.join(repo, "wait.marker")), rc)
check("and releases the lock when it ends", can_lock(home))

# --- a hung chore
repo, home = fixture({"a-hang": chore("a-hang", run="sleep 30"), "b-after": chore("b-after", run="true")})
t0 = time.time()
go(repo, home)
check("a hung chore is recorded as code 2", ran(home, "a-hang") and ran(home, "a-hang")[0]["code"] == 2)
check("and the chore after it still ran", ran(home, "b-after"))
check("and the tick did not wait for the sleep", time.time() - t0 < 20)

# --- missing chores dir, heartbeat, reminders
repo, home = t.tmp("cm-repo-"), t.tmp("cm-home-")
rc = go(repo, home)
check("a missing chores dir exits 2", rc == 2, rc)
check("and records it", any(r["kind"] == "error" and "chores" in r["note"] for r in rows(home)))
check("and still writes the heartbeat (the script is alive; the digest shows the error)",
      L.heartbeat_age(home, NOW) == timedelta(0))

repo, home = fixture({"r": chore("r", body="Renew the token.\nMore.\n")})
go(repo, home)
row = ran(home, "r")
check("a reminder chore is recorded as outstanding (code 1) with its first line",
      row and row[0]["code"] == 1 and "Renew the token." in row[0]["note"], row)

# --- a bad CHOREMASTER_TZ is said once, and the tick still runs (on UTC)
os.environ["CHOREMASTER_TZ"] = "Not/AZone"
try:
    repo, home = fixture({"z": chore("z", run="true")})
    go(repo, home)
    go(repo, home, NOW + timedelta(minutes=15))
    errs = [r for r in rows(home) if r["kind"] == "error" and "time zone" in r["note"]]
    check("an unknown time zone is one error row a day, naming the variable", len(errs) == 1 and "CHOREMASTER_TZ" in errs[0]["note"], errs)
    check("and the chore still ran", ran(home, "z"))
finally:
    os.environ["CHOREMASTER_TZ"] = "Europe/Dublin"

# --- --pull: a checkout with no upstream cannot pull; the failure is recorded and the chores still run
repo, home = fixture({"a": chore("a", run="true")})
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
rc = go(repo, home, NOW, "--pull")
check("a failing git pull is recorded", any(r["kind"] == "error" and "pull" in r["note"] for r in rows(home)), rows(home))
check("and the chores in the checkout still run", ran(home, "a"))
repo, home = fixture({"a": chore("a", run="true")})
subprocess.run(["git", "-C", repo, "init", "-q"], check=True)
go(repo, home)
check("without --pull the tick never touches git", not any("pull" in r["note"] for r in rows(home) if r["kind"] == "error"))

# --- PATH
env = tick.with_extra_path({"PATH": "/usr/bin:/bin", "CHOREMASTER_EXTRA_PATH": "/opt/tools/bin:/usr/bin"})
check("CHOREMASTER_EXTRA_PATH is appended after PATH, without duplicates",
      env["PATH"] == "/usr/bin:/bin:/opt/tools/bin", env["PATH"])
env = tick.with_extra_path({"PATH": "/usr/bin:/bin"})
check("with no extra path, PATH is untouched", env["PATH"] == "/usr/bin:/bin")

# --- the heartbeat push (optional): a git checkout with an origin publishes it
def git_world(with_chores=True):
    root = t.tmp("cm-push-")
    bare, repo = os.path.join(root, "origin.git"), os.path.join(root, "repo")
    subprocess.run(["git", "init", "-q", "--bare", bare], check=True)
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "remote", "add", "origin", bare], check=True)
    if with_chores:
        os.makedirs(os.path.join(repo, "chores"))
        open(os.path.join(repo, "chores", "a.md"), "w").write("---\nid: a\nrun: true\n---\n")
    return repo, bare, t.tmp("cm-home-")


def remote_hb(bare):
    out = subprocess.run(["git", "--git-dir", bare, "show", "choremaster-ledger:heartbeat.json"],
                         capture_output=True, text=True)
    return json.loads(out.stdout)["at"] if out.returncode == 0 else None


repo, bare, home = git_world()
go(repo, home)
check("by default a tick pushes nothing, even from a checkout with an origin", remote_hb(bare) is None)
go(repo, home, NOW, "--push-heartbeat")
check("with --push-heartbeat a tick pushes the heartbeat", remote_hb(bare) == NOW.isoformat(), remote_hb(bare))
go(repo, home, NOW + timedelta(minutes=15), "--push-heartbeat")
check("and not again 15 minutes later (at most hourly)", remote_hb(bare) == NOW.isoformat())
go(repo, home, NOW + timedelta(minutes=61), "--push-heartbeat")
check("but again after an hour", remote_hb(bare) == (NOW + timedelta(minutes=61)).isoformat(), remote_hb(bare))
repo, bare, home = git_world(with_chores=False)
os.environ["CHOREMASTER_PUSH_HEARTBEAT"] = "1"
try:
    go(repo, home, NOW, "--chores", os.path.join(repo, "chores"))
finally:
    del os.environ["CHOREMASTER_PUSH_HEARTBEAT"]
check("CHOREMASTER_PUSH_HEARTBEAT=1 turns it on too, and it is pushed even when chores/ is missing "
      "(the script is alive)", remote_hb(bare) == NOW.isoformat())

# --- one bad file must not stop the tick or the ledger
repo, home = fixture({"good": chore("good", run="true")})
open(os.path.join(repo, "chores", "latin1.md"), "wb").write(b"---\nid: \xff\n---\n")
try:
    rc = go(repo, home)
    crashed = False
except Exception as e:  # noqa: BLE001
    rc, crashed = None, repr(e)
check("a binary chore file does not crash the tick", not crashed, crashed)
check("it is recorded as an error row naming the file", any("latin1.md" in r["note"] for r in rows(home) if r["kind"] == "error"), rows(home))
check("the good chore still ran and the heartbeat was written", ran(home, "good") and L.heartbeat_age(home, NOW) == timedelta(0))

# --- --pull fast-forwards to the upstream ref, and never reads FETCH_HEAD: a `git pull` that refuses (as it does
# when concurrent fetchers leave FETCH_HEAD listing main twice) must not leave the tick on a stale checkout.
def git(cwd, *a):
    return subprocess.run(["git", "-C", cwd, "-c", "user.email=t@example.com", "-c", "user.name=t", *a],
                          capture_output=True, text=True, check=True)


origin = t.tmp("cm-origin-")
git(origin, "init", "-q", "-b", "main")
os.makedirs(os.path.join(origin, "chores"))
open(os.path.join(origin, "chores", "a.md"), "w").write(chore("a", run="true"))
git(origin, "add", "-A"); git(origin, "commit", "-q", "-m", "one")
clone = os.path.join(t.tmp("cm-clone-parent-"), "clone")
subprocess.run(["git", "clone", "-q", origin, clone], check=True)
open(os.path.join(origin, "chores", "b.md"), "w").write(chore("b", run="true"))
git(origin, "add", "-A"); git(origin, "commit", "-q", "-m", "two")
home = t.tmp("cm-home-")
rc = go(clone, home, NOW, "--pull")
check("--pull brings the new chore file in before the tick reads the chores", ran(home, "b") and ran(home, "a"), rows(home))
check("and records no pull error", not [x for x in rows(home) if x["kind"] == "error"], rows(home))

wrap = t.tmp("cm-gitwrap-")
real_git = shutil.which("git")
with open(os.path.join(wrap, "git"), "w") as f:
    f.write('#!/bin/sh\nfor a in "$@"; do [ "$a" = pull ] && { echo "fatal: Cannot fast-forward to multiple branches." >&2; exit 128; }; done\n'
            'exec %s "$@"\n' % real_git)
os.chmod(os.path.join(wrap, "git"), 0o755)
open(os.path.join(origin, "chores", "c.md"), "w").write(chore("c", run="true"))
git(origin, "add", "-A"); git(origin, "commit", "-q", "-m", "three")
home = t.tmp("cm-home-")
env = dict(os.environ, PATH=wrap + os.pathsep + os.environ.get("PATH", ""))
r = cli(clone, home, NOW, "--pull", env=env)
check("the tick updates the checkout without `git pull`, so a refused pull cannot leave it stale",
      ran(home, "c") and not [x for x in rows(home) if x["kind"] == "error" and "pull" in x["note"]],
      (r.stderr[-300:], rows(home)))

# --- exit 1 must name its cause in the journal (stdout), not only in the ledger. A fresh install runs every chore
# once on its first tick; any chore that reports outstanding makes the tick exit 1, and systemd showed "failed"
# with an empty journal. The cause must be on stdout.
repo, home = fixture({"bad": chore("bad", run="echo nope-detail; exit 1"), "ok": chore("ok", run="true")})
r = cli(repo, home)
check("exit 1 from an outstanding chore names the chore and its exit code on stdout (the journal)",
      r.returncode == 1 and "bad" in r.stdout and "exit 1" in r.stdout and "nope-detail" in r.stdout, (r.returncode, r.stdout, r.stderr))
check("and the tick says why it exited 1", "exiting 1" in r.stdout and "outstanding" in r.stdout, r.stdout)
check("a chore that passed is not named as outstanding", "ok" not in [l.split()[2] for l in r.stdout.splitlines() if l.startswith("choremaster: chore ")], r.stdout)
repo, home = fixture({"ok": chore("ok", run="true")})
r = cli(repo, home)
check("a clean tick exits 0 and prints nothing about outstanding chores", r.returncode == 0 and "outstanding" not in r.stdout, (r.returncode, r.stdout))

# --- a retired host never ticks: after moving the scheduler to another machine, the old machine's timer is still
# enabled and would run a second Chore Master writing a second ledger and doubling every write chore. The marker
# is created on the old machine; the tick refuses while it exists.
RETIRED = os.path.join(t.tmp("cm-retired-"), "choremaster-retired-host")
os.environ["CHOREMASTER_RETIRED_MARKER"] = RETIRED
repo, home = fixture({"w": chore("w", run="echo hi > {REPO}/w.marker")})
open(RETIRED, "w").write("new-box.local\n")
tick_out = cli(repo, home)
lines = [l for l in tick_out.stdout.splitlines() if l.strip()]
check("a retired host's tick exits 0", tick_out.returncode == 0, (tick_out.returncode, tick_out.stdout, tick_out.stderr))
check("and prints one line saying this host is retired, naming the host that runs it and the marker to delete",
      len(lines) == 1 and "retired" in lines[0] and "new-box.local" in lines[0] and RETIRED in lines[0], tick_out.stdout)
check("it ran no chore", not os.path.exists(os.path.join(repo, "w.marker")))
check("and recorded nothing: no ledger, state, heartbeat or lock in the state directory", not os.path.exists(home) or os.listdir(home) == [],
      os.listdir(home) if os.path.exists(home) else None)
open(RETIRED, "w").write("")
check("a marker that names no host still retires the tick (exit 0, nothing recorded)",
      go(repo, home) == 0 and (not os.path.exists(home) or os.listdir(home) == []) and not os.path.exists(os.path.join(repo, "w.marker")))
os.remove(RETIRED)
check("with the marker gone the tick runs again", go(repo, home) == 0 and os.path.exists(os.path.join(repo, "w.marker")))
del os.environ["CHOREMASTER_RETIRED_MARKER"]
check("the default marker is ~/.config/choremaster-retired-host, outside the state directory so copying the state "
      "to the new host cannot carry the marker with it",
      tick.retired_marker() == os.path.join(t.FAKE_HOME, ".config", "choremaster-retired-host"), tick.retired_marker())

# --- waits: with waits respected, a chore marked `waits:` is not run. It says "not checked" (exit 2) for 7 days,
# then is outstanding (exit 1); otherwise it runs as before.
repo, home = fixture({"wt": chore("wt", run="echo hi > {REPO}/wt.marker", extra="waits: TICKET-7 the audit log")})
go(repo, home)
check("waits: by default the chore runs", os.path.exists(os.path.join(repo, "wt.marker")))
repo, home = fixture({"wt": chore("wt", run="echo hi > {REPO}/wt.marker", extra="waits: TICKET-7 the audit log")})
rc = go(repo, home, NOW, "--respect-waits")
r = ran(home, "wt")
check("waits: with --respect-waits it is not run", not os.path.exists(os.path.join(repo, "wt.marker")))
check("and its row is could-not-answer naming the check and what it waits on",
      r and r[0]["code"] == 2 and "not checked: the audit log waits on TICKET-7" in r[0]["note"] and rc == 1, r)
later = NOW + timedelta(days=8)
go(repo, home, later, "--respect-waits")
r8 = ran(home, "wt", later.date())
check("after 7 days it is outstanding (exit 1), not quiet", r8 and r8[-1]["code"] == 1 and "8 days" in r8[-1]["note"], r8)
repo, home = fixture({"wt": chore("wt", run="echo hi > {REPO}/wt.marker", extra="waits: TICKET-7 the audit log")})
os.environ["CHOREMASTER_RESPECT_WAITS"] = "1"
try:
    go(repo, home)
finally:
    del os.environ["CHOREMASTER_RESPECT_WAITS"]
check("CHOREMASTER_RESPECT_WAITS=1 turns it on from a unit's environment", not os.path.exists(os.path.join(repo, "wt.marker")))

# --- the publish directory: after a tick, the last two days of ledger are copied one way; private chores are blanked
pub = t.tmp("cm-pub-")
os.environ["CHOREMASTER_PUBLISH_DIR"] = pub
try:
    repo, home = fixture({"pubc": chore("pubc", run="echo visible; exit 1"),
                          "privc": chore("privc", run="echo secret-detail; exit 1", extra="private: yes")})
    go(repo, home)
    copy = open(os.path.join(pub, "ledger", "2026-09-30.jsonl")).read()
    check("a tick copies the ledger to CHOREMASTER_PUBLISH_DIR", "visible" in copy, copy)
    check("a private chore's output is not in the copy", "secret-detail" not in copy and "private chore" in copy, copy)
    check("the heartbeat goes with it", os.path.exists(os.path.join(pub, "heartbeat.json")))
finally:
    del os.environ["CHOREMASTER_PUBLISH_DIR"]
repo, home = fixture({"x": chore("x", run="true")})
go(repo, home)
check("with no publish directory configured nothing is published", not os.path.exists(os.path.join(repo, "ledger")))

t.finish()


def test_checks():
    t.assert_clean(__name__)
