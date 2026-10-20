"""The daily ledger and the heartbeat.

One JSON line per event in `<state dir>/ledger/YYYY-MM-DD.jsonl`, where the day is the local date in the
configured zone (tz.py). Nothing that looks like a token is ever written: `redact` runs before every write.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta
from typing import List, Optional

from choremaster import shared, tz
from choremaster.schedule import meta

MAX_NOTE = 4000
SECRET = re.compile(r"sk-ant-[A-Za-z0-9_-]+|github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9]{20,}"
                    r"|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}")
HEARTBEAT = "heartbeat.json"


def redact(text: str) -> str:
    return SECRET.sub("sk-REDACTED", text)


def _day(now: datetime) -> date:
    return tz.today(now)


def _path(home: str, day: date) -> str:
    return os.path.join(home, "ledger", day.isoformat() + ".jsonl")


def record(home: str, now: datetime, chore_id: str, kind: str, code: int, note: str) -> None:
    os.makedirs(os.path.join(home, "ledger"), exist_ok=True)
    row = {"at": now.isoformat(), "id": chore_id, "kind": kind, "code": code,
           "note": redact(note)[:MAX_NOTE]}
    with open(_path(home, _day(now)), "a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def read_day(home: str, day: date) -> List[dict]:
    try:
        with open(_path(home, day), encoding="utf-8") as f:
            lines = f.read().splitlines()
    except FileNotFoundError:
        return []
    rows = []
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("not an object")
            rows.append(row)
        except ValueError:
            rows.append({"at": "", "id": "ledger", "kind": "error", "code": 2,
                         "note": "corrupt ledger line %d in %s" % (n, day.isoformat())})
    return rows


PRIVATE_NOTE = "(private chore: its output is not copied here)"


def publish(home: str, now: datetime, private: set) -> List[str]:
    """Copy yesterday's and today's ledger and the heartbeat to the publish directory (shared.py), so another
    account can run report.py or ran_since.py with `--state-dir` there. A `private` chore's notes are blanked.
    Reads only `home`; writes only through shared.write. The paths written; OSError when one cannot be."""
    out = []
    today = _day(now)
    for day in (today - timedelta(days=1), today):
        rows = read_day(home, day)
        if not rows:
            continue
        text = "".join(json.dumps(dict(r, note=PRIVATE_NOTE) if r.get("id") in private else r, sort_keys=True) + "\n"
                       for r in rows)
        out.append(shared.write("ledger/%s.jsonl" % day.isoformat(), text))
    try:
        with open(os.path.join(home, HEARTBEAT), encoding="utf-8") as f:
            beat = f.read()
    except OSError:
        beat = ""
    if beat:
        out.append(shared.write(HEARTBEAT, beat))
    return out


def write_heartbeat(home: str, now: datetime) -> None:
    os.makedirs(home, exist_ok=True)
    tmp = os.path.join(home, HEARTBEAT + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"at": now.isoformat()}, f)
    os.replace(tmp, os.path.join(home, HEARTBEAT))


def heartbeat_age(home: str, now: datetime) -> Optional[timedelta]:
    try:
        with open(os.path.join(home, HEARTBEAT), encoding="utf-8") as f:
            return now - datetime.fromisoformat(json.load(f)["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def record_once(home: str, now: datetime, state: dict, key: str, chore_id: str, note: str) -> None:
    """Write an error row once per local day per key (tick-level problems would otherwise repeat every
    15 minutes and bury the digest). The key is kept in `state` (`_meta.errors_recorded`), which the caller
    saves."""
    seen = meta(state).setdefault("errors_recorded", {})
    day = _day(now).isoformat()
    if seen.get(key) != day:
        record(home, now, chore_id, "error", 2, note)
        seen[key] = day
