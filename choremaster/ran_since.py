"""Have these chores run since a date?

Run:  python3 -m choremaster ran-since --since YYYY-MM-DD [--state-dir DIR] [--now ISO] ID [ID ...]
Exit: 0 every id has a ledger row since that local date showing it ran (a `ran` row with code 0 or 1, or a
      `done` row); 1 prints one line per id that has not; 2 usage or no ledger directory.

"Ran" is not "found nothing": code 1 is a chore that reported something outstanding, and it ran. An `error`
row, a code 2 ("could not answer") and no row at all are not ran. A new chore's first morning is the case
this exists for: its file merged, its first tick not yet seen.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta, timezone

from choremaster import config, ledger, tz


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", required=True)
    config.add_state_arg(ap)
    ap.add_argument("--now", default=None)
    ap.add_argument("ids", nargs="+")
    args = ap.parse_args(argv)
    home = config.state_dir(args.home)
    try:
        since = date.fromisoformat(args.since)
    except ValueError:
        print("--since must be YYYY-MM-DD", file=sys.stderr)
        return 2
    if not os.path.isdir(os.path.join(home, "ledger")):
        print("no ledger directory under %s" % home, file=sys.stderr)
        return 2
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = tz.today(now)
    ok = set()
    day = since
    while day <= today:
        for r in ledger.read_day(home, day):
            if r.get("kind") == "done" or (r.get("kind") == "ran" and r.get("code") in (0, 1)):
                ok.add(r.get("id"))
        day += timedelta(days=1)
    missing = [i for i in args.ids if i not in ok]
    for i in missing:
        print("%s: no ran or done row since %s" % (i, args.since))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
