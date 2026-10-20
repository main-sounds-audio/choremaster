"""Runs the bash suites (tests/test_*.sh) under pytest: one test each, failing when the suite does."""
import glob
import os
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(HERE, "test_*.sh"))), ids=os.path.basename)
def test_shell_suite(path):
    p = subprocess.run(["bash", path], capture_output=True, text=True, timeout=600)
    assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-1000:]
