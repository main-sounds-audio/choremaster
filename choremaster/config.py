"""Where things live: the chores directory and the state directory.

Chores directory   --chores, else $CHOREMASTER_CHORES, else ./chores
State directory    --state-dir, else $CHOREMASTER_STATE, else ~/.local/state/choremaster
                   (ledger/, state.json, heartbeat.json and tick.lock live there)
"""
from __future__ import annotations

import os
from typing import Optional

DEFAULT_CHORES = "chores"
DEFAULT_STATE = "~/.local/state/choremaster"


def state_dir(arg: Optional[str] = None) -> str:
    return os.path.expanduser(arg or os.environ.get("CHOREMASTER_STATE") or DEFAULT_STATE)


def chores_dir(arg: Optional[str] = None) -> str:
    return os.path.abspath(os.path.expanduser(arg or os.environ.get("CHOREMASTER_CHORES") or DEFAULT_CHORES))


def add_state_arg(ap) -> None:
    ap.add_argument("--state-dir", "--home", dest="home", default=None,
                    help="where the ledger and state live (default: $CHOREMASTER_STATE or %s)" % DEFAULT_STATE)


def add_chores_arg(ap) -> None:
    ap.add_argument("--chores", default=None,
                    help="the directory of chore files (default: $CHOREMASTER_CHORES or ./%s)" % DEFAULT_CHORES)
