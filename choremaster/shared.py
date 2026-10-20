"""An optional one-way copy of the ledger to a directory other accounts can read.

Set CHOREMASTER_PUBLISH_DIR to a directory this user can write and the tick copies the last two days of
ledger and the heartbeat there after each run (ledger.publish), so another account (a dashboard, an agent) can
run `choremaster report --state-dir <that directory>` without being able to read the real state directory.
Unset, or a directory this user cannot write, and nothing is published.

ONE WAY: nothing in this package reads anything back from that directory. A file another account can write
must never steer the scheduler.

A chore with `private: yes` is blanked in the copy (ledger.publish).

Everything goes through `write` (umask 027, files 0640, an atomic rename so a reader never sees half a file,
no symlink followed).
"""
from __future__ import annotations

import os
import tempfile

ENV = "CHOREMASTER_PUBLISH_DIR"


def root() -> str:
    """The publish directory, or "" when none is configured."""
    return os.environ.get(ENV) or ""


def where(rel: str) -> str:
    """The path `write(rel, ...)` writes."""
    return os.path.join(root(), _clean(rel))


def available() -> bool:
    """A directory is configured, is a real directory, and this user may write it."""
    r = root()
    return bool(r) and os.path.isdir(r) and not os.path.islink(r) and os.access(r, os.W_OK | os.X_OK)


def _clean(rel: str) -> str:
    parts = rel.split("/")
    if os.path.isabs(rel) or not rel or any(p in ("", ".", "..") for p in parts):
        raise ValueError("not a plain relative path: %r" % rel)
    return rel


def write(rel: str, text: str) -> str:
    """Write `text` to root()/rel, mode 0640, atomically; the path written. OSError when it cannot.
    Never follows a symlink: the parents are checked, the temp file is made with O_EXCL, and the rename
    replaces whatever is at the destination rather than writing through it."""
    dest = where(rel)
    r = root()
    old = os.umask(0o027)
    try:
        d = r
        for part in _clean(rel).split("/")[:-1]:
            d = os.path.join(d, part)
            if os.path.islink(d):
                raise OSError("%s is a symlink; the publish directory holds none" % d)
            if not os.path.isdir(d):
                os.mkdir(d, 0o2750)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(dest), prefix="." + os.path.basename(dest) + ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.chmod(tmp, 0o640)
            os.replace(tmp, dest)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    finally:
        os.umask(old)
    return dest
