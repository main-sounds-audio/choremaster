"""Run one chore command with a timeout.

Exit codes follow the check convention: 0 answered clean, 1 finding,
2 could not answer. Anything else (a signal, 127 command-not-found, a timeout,
a missing directory) is 2: a check that did not answer is never a clean check.
The command runs in its own session so a timeout can kill the whole process
group, background children included.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

MAX_OUTPUT = 4000
MAX_FULL = 2_000_000


@dataclass
class Result:
    code: int
    output: str
    seconds: float
    timed_out: bool
    full: str = ""  # the whole output, uncapped (up to MAX_FULL), for callers that want every line


def _cap(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    # Keep the head as well as the tail: a check prints its summary line first and the digest's
    # headline is that line, while a crash's reason is at the end.
    keep = MAX_OUTPUT - 15
    return text[:keep // 3] + "\n…(truncated)…\n" + text[-(keep - keep // 3):]


def run_command(cmd: str, cwd: str, timeout: int = 600, env: Optional[dict] = None) -> Result:
    start = time.time()
    try:
        proc = subprocess.Popen(
            ["/bin/bash", "-c", cmd], cwd=cwd, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as e:
        return Result(2, "could not start: %s" % e, time.time() - start, False)
    try:
        out, _ = proc.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        # A grandchild that left the process group (setsid) can keep the pipe open
        # after the group is killed; waiting for EOF would hang the whole tick.
        try:
            out, _ = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out = b""
            try:
                proc.stdout.close()
            except OSError:
                pass
            proc.wait()
        timed_out = True
    full = (out or b"").decode("utf-8", "replace")[:MAX_FULL]
    text = _cap(full)
    code = proc.returncode
    if timed_out:
        text = ("timed out after %ds\n" % timeout) + text
        code = 2
    elif code not in (0, 1, 2):
        code = 2
    elif code == 1 and "Traceback (most recent call last)" in full:
        # An uncaught Python exception exits 1, which is this convention's "finding": a crashed check
        # would read as a result with a traceback for bullets. It is "could not answer", naming the error.
        tail = [ln for ln in full.splitlines() if ln.strip()][-1].strip()[:200]
        code, text = 2, "crashed: %s\n%s" % (tail, text)
    return Result(code, text, time.time() - start, timed_out, full)
