"""Load the service's environment file when a command runs outside its systemd unit.

The units read /etc/choremaster/choremaster.env (systemd `EnvironmentFile`), so a tick sees the variables
the file sets. A report run by hand, or over ssh, does not: `load()` is called first in `report`'s main and
adds the file's variables to the environment unless they are already set, so the report is read in the same
time zone, with the same state directory, as the tick wrote it. Nothing already in the environment is
overridden.

Env: CHOREMASTER_ENV_FILE  path of the env file (default /etc/choremaster/choremaster.env; tests point it elsewhere).
"""
from __future__ import annotations

import os

DEFAULT_ENV_FILE = "/etc/choremaster/choremaster.env"


def parse(text: str) -> dict:
    """systemd EnvironmentFile syntax, the simple part: KEY=VALUE lines, # and ; comments, optional quotes."""
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line[0] in "#;" or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key.isidentifier():
            out[key] = val
    return out


def load(environ=None) -> bool:
    """True when the env file was found. An unreadable file counts as found; the variables it would have
    added are simply missing."""
    env = os.environ if environ is None else environ
    path = env.get("CHOREMASTER_ENV_FILE") or DEFAULT_ENV_FILE
    if not os.path.exists(path):
        return False
    try:
        with open(path, encoding="utf-8") as f:
            for k, v in parse(f.read()).items():
                env.setdefault(k, v)
    except OSError:
        pass
    return True
