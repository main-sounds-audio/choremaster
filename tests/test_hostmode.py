#!/usr/bin/env python3
"""Tests choremaster/hostmode.py: report, run by hand or over ssh, loads the service's env file itself."""
from __future__ import annotations

import os

import _testkit as t
from choremaster import hostmode

check = t.check
d = t.tmp("cm-hostmode-")
f = os.path.join(d, "choremaster.env")
with open(f, "w") as fh:
    fh.write("# comment\n\nA=1\nB = \"two words\"\nC='x'\nnot a var\n9X=no\nKEEP=fromfile\n")

parsed = hostmode.parse(open(f).read())
check("parse reads KEY=VALUE, strips quotes, skips comments and junk",
      parsed == {"A": "1", "B": "two words", "C": "x", "KEEP": "fromfile"}, parsed)

env = {"CHOREMASTER_ENV_FILE": f, "KEEP": "fromenv"}
check("load returns True when the file exists", hostmode.load(env) is True, env)
check("it adds the file's variables", env["A"] == "1" and env["B"] == "two words", env)
check("it never overrides what is already set", env["KEEP"] == "fromenv", env)

env = {"CHOREMASTER_ENV_FILE": os.path.join(d, "missing.env")}
check("with no env file it changes nothing and returns False", hostmode.load(env) is False and env == {"CHOREMASTER_ENV_FILE": env["CHOREMASTER_ENV_FILE"]}, env)

check("the default path is /etc/choremaster/choremaster.env", hostmode.DEFAULT_ENV_FILE == "/etc/choremaster/choremaster.env")

t.finish()


def test_checks():
    t.assert_clean(__name__)
