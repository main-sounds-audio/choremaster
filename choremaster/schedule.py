"""Is a chore due, and what has it done so far.

State is one JSON file, `<state dir>/state.json`, keyed by chore id, plus a `_meta` dict for the tick's own
bookkeeping (heartbeat push time, and `state_error` when the file could not be read). A file that cannot be
read is treated as absent, which makes every chore due again: that fails toward running a check twice,
never toward silence.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Dict

from choremaster import tz
from choremaster.chorefile import Chore

DEFAULT_EVERY = timedelta(days=1)
# Exit 2 is "could not answer": the chore has not run in any sense that counts, so it is retried after this
# long instead of waiting for its next period. An hour, not every 15-minute tick.
RETRY_CANNOT_ANSWER = timedelta(hours=1)
# last_ran is the start of the tick that ran the chore, and ticks start anywhere in their minute. A timed
# chore due one period later must be due on the tick that is that period later, even when that tick starts
# a few seconds earlier in its minute, so the period is read with this margin.
TICK_MARGIN = timedelta(minutes=1)
STATE = "state.json"


def meta(state: dict) -> dict:
    return state.setdefault("_meta", {})


def load_state(home: str) -> Dict[str, dict]:
    path = os.path.join(home, STATE)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("state.json is not an object")
        return data
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        return {"_meta": {"state_error": "state.json unreadable: %s" % e}}


def save_state(home: str, state: dict) -> None:
    os.makedirs(home, exist_ok=True)
    state = dict(state)
    m = dict(state.get("_meta", {}))
    m.pop("state_error", None)
    if m:
        state["_meta"] = m
    else:
        state.pop("_meta", None)
    tmp = os.path.join(home, STATE + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True)
    os.replace(tmp, os.path.join(home, STATE))


def is_due(chore: Chore, state: dict, now: datetime) -> bool:
    entry = state.get(chore.id, {})
    if entry.get("done"):
        return False
    if chore.due is not None and now < chore.due:
        return False
    if chore.after and _local_minutes(now) < _minutes_of(chore.after):
        return False
    last = entry.get("last_ran")
    if not last:
        return True
    last_dt = datetime.fromisoformat(last)
    if entry.get("last_code") == 2 and now > last_dt + RETRY_CANNOT_ANSWER - TICK_MARGIN:
        return True
    every = chore.every or DEFAULT_EVERY
    if every == DEFAULT_EVERY:
        # Daily means once per local DATE, not 24 hours after the last run: with elapsed-time semantics one
        # late wake pushed a chore later every day and the morning digest showed yesterday's result as today's.
        return tz.today(now) > tz.today(last_dt)
    return now > last_dt + every - TICK_MARGIN


def _minutes_of(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _local_minutes(dt: datetime) -> int:
    local = tz.local(dt)
    return local.hour * 60 + local.minute


def mark_ran(state: dict, chore_id: str, now: datetime, code: int) -> None:
    entry = state.setdefault(chore_id, {})
    entry["last_ran"] = now.isoformat()
    entry["last_code"] = code


def mark_done(state: dict, chore_id: str, now: datetime) -> None:
    entry = state.setdefault(chore_id, {})
    entry["done"] = True
    entry["done_at"] = now.isoformat()
