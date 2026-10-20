"""Keep paused names out of every chore's output.

A name on the pause list is something you have put on hold (a mothballed repository, a retired host, a
customer on leave). Many chores query a whole account, so instead of a filter in each, the tick passes
every chore's output through `drop()` here: each line naming a paused name is removed, and a finding left
with no bullet is no finding (exit 0, silent). A chore whose job is to report on a paused name sets
`names_paused: true` and is passed through unchanged. Deleting the name's line from the list brings its
lines back.

The list is a text file: one name per line, the first word is the name, anything after it is a note, `#`
starts a comment. Its path is $CHOREMASTER_PAUSED_FILE, else ~/.config/choremaster/paused.txt; a missing
file is an empty list.
"""
from __future__ import annotations

import os
import re
from typing import Iterable, Optional, Tuple

DEFAULT_FILE = "~/.config/choremaster/paused.txt"


def names(path: Optional[str] = None) -> set:
    """The paused names; a missing or unreadable list is an empty one."""
    path = os.path.expanduser(path or os.environ.get("CHOREMASTER_PAUSED_FILE") or DEFAULT_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return set()
    out = set()
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line.split()[0])
    return out


def pattern(paused: Iterable[str]):
    """A name as a token: `old-service`, `owner/old-service#3`, `/old-service-wt/`, not `not-old-service`."""
    alts = sorted((re.escape(n) for n in paused if n), key=len, reverse=True)
    return re.compile(r"(?<![\w.-])(?:%s)(?![A-Za-z0-9_])" % "|".join(alts), re.IGNORECASE) if alts else None


def drop(code: int, text: str, paused: Iterable[str] = None) -> Tuple[int, str]:
    """(code, text) with every line naming a paused name removed; a finding with no bullet left becomes (0, "")."""
    rx = pattern(names() if paused is None else paused)
    if rx is None or not text:
        return code, text
    lines = text.splitlines()
    kept = [ln for ln in lines if not rx.search(ln)]
    if len(kept) == len(lines):
        return code, text
    bullets = sum(1 for ln in kept if ln.lstrip().startswith("- "))
    if code == 1 and not bullets:
        return 0, ""
    # A summary line that counted every bullet ("3 item(s) ...") is recounted, so it matches what is left.
    m = re.match(r"^(\d+)\b", kept[0]) if kept else None
    if m and int(m.group(1)) == sum(1 for ln in lines if ln.lstrip().startswith("- ")):
        kept[0] = str(bullets) + kept[0][m.end():]
    return code, "\n".join(kept)
