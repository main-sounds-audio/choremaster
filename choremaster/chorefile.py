"""Parse and validate one chore file.

A chore is a markdown file: flat `key: value` front matter between `---` fences, then a free-text body.
Hand-rolled on purpose: standard library only, so it runs on a stock system Python with no PyYAML.

Errors are returned, never swallowed: `load_all` gives the caller every broken file so the tick can put
each one in the ledger.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from choremaster import tz

KEYS = {"id", "due", "every", "run", "done_when", "title", "do", "links", "names_paused", "after", "private",
        "waits"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# `waits: <ref> <what>`: the check waits on that blocker (see rule_wait.py).
WAITS_RE = re.compile(r"^(\S+)\s+(\S.*)$")
AFTER_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
EVERY_RE = re.compile(r"^(\d+)([mhd])$")
UNIT = {"m": "minutes", "h": "hours", "d": "days"}
MAX_EVERY = timedelta(days=3650)

# http:// only to this machine or a home-network host (`.local` is mDNS, answered only on the LAN);
# anything else must be https.
LINK_OK = re.compile(r"^(https://|http://127\.0\.0\.1[:/]|http://localhost[:/]|http://[a-z0-9][a-z0-9-]*\.local[:/])")
MAX_TITLE = 100


class ChoreError(Exception):
    def __init__(self, msg: str, path: str = "") -> None:
        super().__init__(msg)
        self.path = path


@dataclass
class Chore:
    id: str
    due: Optional[datetime]
    every: Optional[timedelta]
    run: Optional[str]
    done_when: Optional[str]
    body: str
    path: str
    # For the morning digest (all optional): a bold heading, the one-line "your call", and clickable links
    # as (label, url).
    title: Optional[str] = None
    do: Optional[str] = None
    links: List[Tuple[str, str]] = field(default_factory=list)
    names_paused: bool = False  # true: output naming a paused name is kept (paused.py)
    after: Optional[str] = None  # "HH:MM" local time: not due before this time of day
    private: bool = False  # yes: its output is not copied to the publish directory (shared.py)
    # (ref, what): while the tick runs with waits respected (rule_wait.py), this chore is not run and says
    # "not checked" (exit 2) for 7 days, then fails.
    waits: Optional[Tuple[str, str]] = None


def _strip_comment(value: str) -> str:
    # A comment is whitespace, `#`, then whitespace or the end: "ticket #42" inside a value is not one.
    m = re.search(r"\s#(?=\s|$)", value)
    return (value[: m.start()] if m else value).strip()


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _parse_due(value: str, path: str) -> datetime:
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise ChoreError("due is not an ISO 8601 time: %r" % value, path)
    if dt.tzinfo is None:
        dt = tz.attach(dt)
    return dt


def load_chore(path: str) -> Chore:
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except (OSError, UnicodeDecodeError) as e:
        raise ChoreError("cannot read (is it UTF-8 text?): %s" % e, path)
    if not lines or lines[0].strip() != "---":
        raise ChoreError("no front matter (the file must start with ---)", path)
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        raise ChoreError("unterminated front matter (no closing ---)", path)

    fields = {}
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if ":" not in raw:
            raise ChoreError("front matter line is not key: value: %r" % raw, path)
        key, _, value = raw.partition(":")
        key = key.strip()
        if key not in KEYS:
            raise ChoreError("unknown key %r (allowed: %s)" % (key, ", ".join(sorted(KEYS))), path)
        fields[key] = _unquote(_strip_comment(value))

    cid = fields.get("id", "")
    if not ID_RE.match(cid):
        raise ChoreError("id must match %s, got %r" % (ID_RE.pattern, cid), path)

    every = None
    if fields.get("every"):
        m = EVERY_RE.match(fields["every"])
        if not m or int(m.group(1)) <= 0:
            raise ChoreError("every must look like 15m, 1h or 1d, got %r" % fields["every"], path)
        try:
            every = timedelta(**{UNIT[m.group(2)]: int(m.group(1))})
        except OverflowError:
            every = None
        if every is None or every > MAX_EVERY:
            raise ChoreError("every is absurdly large (limit %d days): %r" % (MAX_EVERY.days, fields["every"]), path)

    run = fields.get("run") or None
    title = fields.get("title") or None
    if title and len(title) > MAX_TITLE:
        raise ChoreError("title is too long (limit %d characters)" % MAX_TITLE, path)
    links: List[Tuple[str, str]] = []
    for part in (fields.get("links") or "").split(";"):
        if not part.strip():
            continue
        label, sep, url = part.partition("|")
        label, url = label.strip(), url.strip()
        if not sep or not label or not url:
            raise ChoreError("links must be `label|url` pairs separated by `;`, got %r" % part.strip(), path)
        # No userinfo: in http://x.local:80@evil.example/ the host is evil.example.
        if not LINK_OK.match(url) or (url.startswith("http://") and "@" in url.split("/", 3)[2]):
            raise ChoreError("links: only https:// (or http://127.0.0.1, http://localhost, http://<name>.local) "
                             "links are allowed, got %r" % url, path)
        links.append((label, url))

    np_ = (fields.get("names_paused") or "false").lower()
    if np_ not in ("true", "false"):
        raise ChoreError("names_paused must be true or false, got %r" % np_, path)
    private = (fields.get("private") or "no").lower()
    if private not in ("yes", "no"):
        raise ChoreError("private must be yes or no, got %r" % private, path)
    after = fields.get("after") or None
    if after is not None and not AFTER_RE.match(after):
        raise ChoreError("after must be a local time of day like 12:00, got %r" % after, path)
    waits = None
    if fields.get("waits"):
        m = WAITS_RE.match(fields["waits"])
        if not m:
            raise ChoreError("waits must be `<ref> <what is not checked>`, got %r" % fields["waits"], path)
        if not (run or fields.get("done_when")):
            raise ChoreError("waits belongs only to a chore with run or done_when (it replaces running them)", path)
        waits = (m.group(1), m.group(2).strip())
    due = _parse_due(fields["due"], path) if fields.get("due") else None
    body = "\n".join(lines[end + 1:])
    return Chore(cid, due, every, run, fields.get("done_when") or None, body, path,
                 title=title, do=fields.get("do") or None, links=links,
                 names_paused=np_ == "true", after=after, private=private == "yes", waits=waits)


def load_all(directory: str) -> Tuple[List[Chore], List[ChoreError]]:
    chores: List[Chore] = []
    errors: List[ChoreError] = []
    seen = {}
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".md") or name.lower() == "readme.md":
            continue
        path = os.path.join(directory, name)
        try:
            chore = load_chore(path)
        except ChoreError as e:
            errors.append(e)
            continue
        except Exception as e:  # noqa: BLE001 - one bad file must never stop every chore
            errors.append(ChoreError("unexpected error reading this file: %r" % (e,), path))
            continue
        if chore.id in seen:
            errors.append(ChoreError("duplicate id %r (first defined in %s)" % (chore.id, seen[chore.id]), path))
            continue
        seen[chore.id] = path
        chores.append(chore)
    return chores, errors
