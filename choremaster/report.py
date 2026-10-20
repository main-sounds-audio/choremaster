"""The morning digest. Pure and deterministic: no model.

Run:  python3 -m choremaster report [--state-dir DIR] [--chores DIR] [--now ISO]
Prints the headline on line 1 (use it as an email subject or a notification title), then the numbered body.

Every way this can look fine and not be fine is a test: exit 2 is "could not answer", never clear; an empty
ledger is "nothing recorded", never "all clear"; a stale heartbeat is something that needs attention.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from choremaster import config, hostmode, ledger, tz
from choremaster.chorefile import load_all

WINDOW = timedelta(hours=26)
STALE_HEARTBEAT = timedelta(minutes=30)
TICK_ID = "choremaster"
HEAD = "Chore Master"


def _parse(at: str, fallback: datetime) -> datetime:
    try:
        return datetime.fromisoformat(at)
    except (ValueError, TypeError):
        return fallback


def _window_rows(home: str, now: datetime) -> List[dict]:
    local = tz.local(now)
    days = [(local - timedelta(days=1)).date(), local.date()]
    rows = []
    for day in days:
        for r in ledger.read_day(home, day):
            when = _parse(r.get("at", ""), now)
            if now - WINDOW <= when <= now + timedelta(minutes=5):
                r = dict(r)
                r["_when"] = when
                rows.append(r)
    return rows


MAX_NOTE_LINES = 12


def _lines(note: str) -> List[str]:
    """The note's non-empty lines, at most twelve: the first is the item's summary and the rest are its
    bullets. Deliberately no cleverness about which lines matter: a heuristic once kept a report's heading
    and dropped its rows. A chore whose output leads with preamble is fixed at its source (see
    bin/keep-matching.sh)."""
    return [ln.strip()[:240] for ln in str(note).splitlines() if ln.strip()][:MAX_NOTE_LINES]


def _bullet(text: str) -> str:
    return text[2:].strip() if text.startswith(("- ", "* ")) else text


def _age(d: timedelta) -> str:
    mins = int(d.total_seconds() // 60)
    return "%dh %dm" % (mins // 60, mins % 60) if mins >= 60 else "%dm" % mins


def render_digest(home: str, now: datetime, chores_dir: Optional[str] = None) -> Tuple[str, str]:
    rows = _window_rows(home, now)
    latest: Dict[Tuple[str, str], dict] = {}
    for r in sorted(rows, key=lambda r: r["_when"]):
        key = (r.get("id", "?"), r.get("note", "") if r.get("id") == TICK_ID else "")
        latest[key] = r

    by_id: Dict[str, object] = {}
    if chores_dir and os.path.isdir(chores_dir):
        chores, load_errors = load_all(chores_dir)
        by_id = {c.id: c for c in chores}
        # A recorded "<file>.md: problem" is only true while that file still fails to load: the tick
        # records each once a day, so a problem fixed since then would otherwise stay all day.
        still_bad = {os.path.basename(e.path) for e in load_errors}
        for key in [k for k in latest if k[0] == TICK_ID]:
            m = re.match(r"^([^\s:]+\.md): ", key[1])
            if m and m.group(1) not in still_bad:
                del latest[key]

    def name(cid: str) -> str:
        c = by_id.get(cid)
        return c.title if c is not None and c.title else cid

    needs: List[Tuple[str, str, List[str]]] = []
    done: List[str] = []
    retired: List[str] = []
    clean: List[str] = []
    for (cid, _), r in sorted(latest.items()):
        kind, code = r.get("kind"), r.get("code", 2)
        nl = _lines(r.get("note", ""))
        first, more = (nl[0] if nl else ""), nl[1:]
        if kind == "retired":
            retired.append("- %s" % (first or "retired finished chores"))
        elif kind == "done":
            done.append("- %s: %s" % (name(cid), first or "finished"))
        elif kind == "error":
            needs.append((cid, "problem: %s" % first, more))
        elif kind == "ran" and code == 0:
            clean.append(name(cid))
        elif kind == "ran" and code == 1:
            needs.append((cid, "outstanding: %s" % first, more))
        else:
            needs.append((cid, "could not answer: %s" % first, more))

    items: List[str] = []
    for cid, text, more in needs:
        c = by_id.get(cid)
        titled = c is not None and bool(c.title)
        reminder = c is not None and c.run is None
        summary = text.split(": ", 1)[1] if ": " in text else text
        if titled:
            # to-do style: bold title, then the summary unless it is a reminder's own first line
            prefix = "" if text.startswith("outstanding: ") else text.split(": ", 1)[0] + ": "
            # The title stands alone on its line; the summary is the next line, then the italic "your call":
            # one idea per line reads as a to-do list.
            block = ["**%s**" % c.title]
            if not reminder and (prefix + summary).strip():
                block.append("   " + prefix + summary)
            if c.do:
                block.append("   *%s*" % c.do)
            if reminder:
                bullets = [ln.strip()[2:].strip() for ln in c.body.splitlines() if ln.strip().startswith("- ")]
            else:
                bullets = [_bullet(b) for b in more]
            block += ["   - " + b for b in bullets[:MAX_NOTE_LINES]]
            if c.links:
                block.append("   " + " · ".join("[%s](%s)" % (label, url) for label, url in c.links))
        else:
            block = ["**%s** — %s" % (cid, text)]
            block += ["   - " + _bullet(b) for b in more]
            if c is not None and c.run:
                block.append("   command: " + c.run)
            if reminder:
                shown = {summary} | set(more)
                block += ["   " + ln.strip() for ln in c.body.splitlines() if ln.strip() and ln.strip() not in shown][:6]
        items.append("\n".join(block))

    age = ledger.heartbeat_age(home, now)
    if age is None:
        items.append("**The Chore Master tick** — has never written a heartbeat: it may not be installed or running.")
    elif age > STALE_HEARTBEAT:
        items.append("**The Chore Master tick** — last heartbeat was %s ago; it should tick every 15 minutes." % _age(age))

    lines: List[str] = []
    if not rows:
        head = HEAD + ": nothing recorded"
        lines.append("No chore has run or been recorded in the last 26 hours. That is not the same as all clear.")
        if items:
            lines += ["", "Needs attention (%d):" % len(items), ""] + ["%d. %s" % (n, t) for n, t in enumerate(items, 1)]
        return head, "\n".join(lines) + "\n"

    if items:
        head = HEAD + ": %d need%s attention" % (len(items), "s" if len(items) == 1 else "")
        lines += ["Needs attention (%d):" % len(items), ""] + ["%d. %s" % (n, t) for n, t in enumerate(items, 1)]
    else:
        head = HEAD + ": all clear"
        lines.append("Nothing needs attention.")
    if done:
        lines += ["", "Done since yesterday (%d):" % len(done)] + done
    if retired:
        lines += ["", "Retired finished chores (their files are removed by pull request, a day after they are reported done):"] + retired
    if clean:
        lines += ["", "Ran clean (%d): %s" % (len(clean), ", ".join(clean))]
    return head, "\n".join(lines) + "\n"


def main(argv=None) -> int:
    hostmode.load()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    config.add_state_arg(ap)
    config.add_chores_arg(ap)
    ap.add_argument("--now", default=None)
    args = ap.parse_args(argv)
    now = datetime.fromisoformat(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    head, body = render_digest(config.state_dir(args.home), now, chores_dir=config.chores_dir(args.chores))
    print(head)
    print(body, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
