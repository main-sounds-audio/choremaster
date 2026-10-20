"""Shared harness for the suites.

Each suite is a plain script: it makes `check(label, ok)` calls at module level and ends with `t.finish()`.
Run one with `python3 tests/test_ledger.py` (exit 1 on a failure, last line `N passed, M failed`), or run
them all with `python3 -m pytest` (each file is one test that fails if any of its checks failed).

Every suite runs under a throwaway HOME and a fixed time zone, set before any choremaster module is
imported: defaults such as ~/.local/state/choremaster then resolve into the throwaway, so a suite that
forgets to pass an override can never touch the real state.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "choremaster")
sys.path.insert(0, ROOT)

_CREATED = []


def tmp(prefix: str = "cm-") -> str:
    """A fresh directory, removed when the interpreter exits."""
    d = tempfile.mkdtemp(prefix=prefix)
    _CREATED.append(d)
    return d


@atexit.register
def _sweep() -> None:
    for d in _CREATED:
        shutil.rmtree(d, ignore_errors=True)


FAKE_HOME = os.environ.get("CM_TEST_HOME") or tmp("cm-home-")
os.environ["CM_TEST_HOME"] = FAKE_HOME
os.environ["HOME"] = FAKE_HOME
# A zone that is UTC+1 in summer and UTC in winter, with daylight saving ending on 2026-10-25, so the
# suites can pin day boundaries and the change of clocks.
os.environ["CHOREMASTER_TZ"] = "Europe/Dublin"
for _k in list(os.environ):
    if _k.startswith("CHOREMASTER_") and _k != "CHOREMASTER_TZ":
        del os.environ[_k]

_TALLY = {}   # module name -> [passed, failed, [failed labels]]


def _module() -> str:
    return sys._getframe(2).f_globals.get("__name__", "?")


def check(label: str, ok: bool, detail=None) -> None:
    tally = _TALLY.setdefault(_module(), [0, 0, []])
    if ok:
        tally[0] += 1
        print("  ok   - " + label)
    else:
        tally[1] += 1
        tally[2].append(label)
        print("  FAIL - " + label)
        if detail is not None:
            print("         " + str(detail)[:600])


def finish() -> None:
    """Print `N passed, M failed`; exit non-zero when run as a script (under pytest, test_checks() asserts)."""
    name = _module()
    passed, failed, _ = _TALLY.get(name, [0, 0, []])
    print()
    print("%d passed, %d failed" % (passed, failed))
    if name == "__main__":
        sys.exit(1 if failed else 0)


def assert_clean(module_name: str) -> None:
    passed, failed, labels = _TALLY.get(module_name, [0, 0, []])
    assert passed + failed > 0, "no checks ran in %s" % module_name
    assert failed == 0, "%d check(s) failed in %s: %s" % (failed, module_name, "; ".join(labels))
