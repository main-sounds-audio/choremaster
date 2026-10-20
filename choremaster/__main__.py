"""`python3 -m choremaster <command> [options]`: the one entry point.

  tick         run the chores that are due (every 15 minutes)
  report       print the morning digest
  ran-since    have these chores run since a date?
  retire       remove the files of finished chores (needs git and gh)
  heartbeat    push the heartbeat to the choremaster-ledger branch
  post-report  read a digest on stdin and post it as a comment on a standing GitHub issue
  rule-wait    the "not checked yet" answer a `waits:` chore gives
"""
from __future__ import annotations

import importlib
import sys

COMMANDS = {
    "tick": "choremaster.tick",
    "report": "choremaster.report",
    "ran-since": "choremaster.ran_since",
    "retire": "choremaster.retire",
    "heartbeat": "choremaster.push_heartbeat",
    "post-report": "choremaster.post_report",
    "rule-wait": "choremaster.rule_wait",
}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help") or argv[0] not in COMMANDS:
        out = sys.stdout if argv and argv[0] in ("-h", "--help") else sys.stderr
        print(__doc__.strip(), file=out)
        return 0 if argv and argv[0] in ("-h", "--help") else 2
    mod = importlib.import_module(COMMANDS[argv[0]])
    return mod.main(argv[1:]) or 0


if __name__ == "__main__":
    sys.exit(main())
