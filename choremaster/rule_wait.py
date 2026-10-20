"""A check that cannot answer until something else lands: "not checked" for 7 days, then failing.

Run: python3 -m choremaster rule-wait REF WHAT
     prints one line and exits with the chore's code:
       2  "not checked: WHAT waits on REF" (could not answer), for 7 days from the first day it was seen;
       1  "WHAT has not been checked for N days: it waits on REF" (outstanding), after.
Env:  CHOREMASTER_STATE         the first-seen dates live in <it>/rule-waits/<REF>
      CHOREMASTER_RESPECT_WAITS 1: the tick applies `waits:` (see below)
      NOW=<epoch seconds>       tests only: the clock

A chore with `waits: REF what is not checked` is not run while the tick respects waits
(`tick --respect-waits`, or CHOREMASTER_RESPECT_WAITS=1 in a unit's environment). Use it for a check that
needs something that does not exist yet where the tick runs (a permission, a credential, another team's
change). It reports that it could not answer while you sort that out, and after a week it is a failing check
in the morning report, so a lost check cannot stay quiet.
"""
import os
import sys
import time

DAYS = 7


def respects_waits(environ=None) -> bool:
    env = os.environ if environ is None else environ
    return (env.get("CHOREMASTER_RESPECT_WAITS") or "").strip().lower() in ("1", "true", "yes")


def _state_dir():
    return os.path.expanduser(os.environ.get("CHOREMASTER_STATE") or "~/.local/state/choremaster")


def wait(ref, what, home=None, now=None):
    """(exit code, line) for this check; records the first time it was seen."""
    home = home or _state_dir()
    now = int(now if now is not None else os.environ.get("NOW") or time.time())
    d = os.path.join(home, "rule-waits")
    f = os.path.join(d, "".join(c if c.isalnum() or c in "._-" else "_" for c in str(ref)))
    first = None
    try:
        with open(f, encoding="utf-8") as fh:
            first = int(fh.read().strip())
    except (OSError, ValueError):
        try:
            os.makedirs(d, exist_ok=True)
            with open(f, "w", encoding="utf-8") as fh:
                fh.write("%d\n" % now)
        except OSError:
            pass
    days = (now - (first if first is not None else now)) // 86400
    if days >= DAYS:
        return 1, "%s has not been checked for %d days: it waits on %s" % (what, days, ref)
    return 2, "not checked: %s waits on %s" % (what, ref)


def main(argv):
    if len(argv) != 2 or not argv[0]:
        print("usage: rule-wait REF WHAT", file=sys.stderr)
        return 2
    rc, line = wait(argv[0], argv[1])
    print(line)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
