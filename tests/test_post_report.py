#!/usr/bin/env python3
"""Tests choremaster/post_report.py: posts the digest as a comment on a standing issue.

A digest that fails to post must never read as a quiet morning: non-zero exit, the digest on stdout, and the
file on disk. The fake `gh` records every call so the mention and the find-or-create-by-exact-title
behaviour are asserted on what was actually sent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import _testkit as t

check = t.check
DIGEST = "Chore Master: 1 needs attention\nNeeds attention (1):\n\n1. **Thing** - outstanding: x\n"
TITLE = "Chore Master morning report"


def fake_gh(existing, fail_on=None):
    """A gh stub: `issue list` prints `existing` as JSON, `issue create` prints a URL, `issue comment`
    logs its stdin. Every call is appended to calls.log; a subcommand named in fail_on exits 1."""
    d = t.tmp("cm-gh-")
    path = os.path.join(d, "gh")
    open(path, "w").write("""#!/usr/bin/env python3
import json, sys
a = sys.argv[1:]
log = open(%r, "a")
body = sys.stdin.read() if "--body-file" in a else ""
log.write(json.dumps({"args": a, "stdin": body}) + "\\n")
sub = a[1]
if sub == %r:
    sys.stderr.write("boom\\n"); sys.exit(1)
if sub == "list": print(json.dumps(%s))
elif sub == "create": print("https://github.com/acme/ops/issues/777")
""" % (os.path.join(d, "calls.log"), fail_on or "", json.dumps(existing)))
    os.chmod(path, 0o755)
    return path, os.path.join(d, "calls.log")


def calls(log):
    return [json.loads(ln) for ln in open(log)] if os.path.exists(log) else []


def post(gh, home, stdin=DIGEST, *more, repo="acme/ops"):
    env = dict(os.environ, GH=gh)
    args = [sys.executable, t.BIN, "post-report", "--state-dir", home, "--date", "2026-10-02"]
    if repo:
        args += ["--repo", repo]
    p = subprocess.run(args + list(more), input=stdin, capture_output=True, text=True, env=env)
    return p.returncode, p.stdout, p.stderr


# existing issue found by exact title (a near-miss title must not be taken)
gh, log = fake_gh([{"number": 5, "title": TITLE + " (old)"}, {"number": 9, "title": TITLE}])
home = t.tmp("cm-home-")
rc, out, err = post(gh, home, DIGEST, "--mention", "octocat")
cs = calls(log)
cmt = [c for c in cs if c["args"][:2] == ["issue", "comment"]]
check("posts and exits 0", rc == 0, (rc, out, err))
check("comments on the issue whose title matches exactly (9, not the near-miss 5)", len(cmt) == 1 and cmt[0]["args"][2] == "9", cs)
check("and creates nothing when it exists", not any(c["args"][:2] == ["issue", "create"] for c in cs), cs)
body = cmt[0]["stdin"] if cmt else ""
lines = body.splitlines()
check("the comment opens with a heading naming the day", lines[:1] == ["Chore Master morning report, 2026-10-02"], lines[:2])
check("then @octocat on its own line", lines[1:2] == ["@octocat"], lines[:4])
check("then the digest verbatim", DIGEST.rstrip("\n") in body and body.index("@octocat") < body.index("Chore Master: 1 needs attention"), body)
check("the digest is also in last-report.txt", open(os.path.join(home, "last-report.txt")).read() == DIGEST)
check("it targets the repository it was given", "acme/ops" in cmt[0]["args"], cmt[0]["args"])

rc, out, err = post(gh, t.tmp("cm-home-"))
check("with no --mention nobody is mentioned", "@" not in calls(log)[-1]["stdin"], calls(log)[-1])

# --title and the environment
gh, log = fake_gh([{"number": 3, "title": "Ops digest"}])
rc, out, err = post(gh, t.tmp("cm-home-"), DIGEST, "--title", "Ops digest")
check("--title picks the standing issue", [c["args"][2] for c in calls(log) if c["args"][:2] == ["issue", "comment"]] == ["3"], calls(log))

# no such issue: created, then commented on
gh, log = fake_gh([])
rc, out, err = post(gh, t.tmp("cm-home-"), DIGEST, "--label", "standing")
cs = calls(log)
create = [c for c in cs if c["args"][:2] == ["issue", "create"]]
check("creates the issue when absent, titled exactly", len(create) == 1
      and create[0]["args"][create[0]["args"].index("--title") + 1] == TITLE, cs)
check("with the label asked for", [a for i, a in enumerate(create[0]["args"]) if i and create[0]["args"][i - 1] == "--label"] == ["standing"], create)
check("then comments on the number gh printed (777)", [c["args"][2] for c in cs if c["args"][:2] == ["issue", "comment"]] == ["777"], cs)
gh, log = fake_gh([])
post(gh, t.tmp("cm-home-"))
create = [c for c in calls(log) if c["args"][:2] == ["issue", "create"]]
check("without --label it creates the issue with no label", "--label" not in create[0]["args"], create)

# failure: non-zero, digest on stdout, file still written
gh, log = fake_gh([{"number": 9, "title": TITLE}], fail_on="comment")
home = t.tmp("cm-home-")
rc, out, err = post(gh, home)
check("a failed post exits non-zero", rc != 0, rc)
check("and prints the digest to stdout so the journal carries it", DIGEST.strip() in out, out)
check("and says why on stderr", "could not post" in err and "boom" in err, err)
check("and the digest is still on disk", open(os.path.join(home, "last-report.txt")).read() == DIGEST)
gh, log = fake_gh([], fail_on="list")
rc, out, err = post(gh, t.tmp("cm-home-"))
check("a failure finding the issue is also non-zero with the digest printed", rc != 0 and DIGEST.strip() in out, (rc, out))
rc, out, err = post("/nonexistent/gh", t.tmp("cm-home-"))
check("a missing gh is non-zero with the digest printed", rc != 0 and DIGEST.strip() in out, (rc, out, err))
gh, log = fake_gh([])
rc, out, err = post(gh, t.tmp("cm-home-"), stdin="")
check("an empty digest is never posted", rc != 0 and not calls(log), (rc, calls(log)))
rc, out, err = post(gh, t.tmp("cm-home-"), repo=None)
check("with no repository it posts nothing, prints the digest and exits non-zero",
      rc != 0 and DIGEST.strip() in out and not calls(log) and "--repo" in err, (rc, out, err))

t.finish()


def test_checks():
    t.assert_clean(__name__)
