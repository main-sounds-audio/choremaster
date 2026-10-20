"""Post the morning digest as a comment on one standing GitHub issue, so you are notified wherever you are.

Run:  python3 -m choremaster report | python3 -m choremaster post-report --repo OWNER/REPO [options]
Exit: 0 posted; 1 could not post (the digest is printed to stdout so the journal carries it).

Options (each also read from the environment):
  --repo OWNER/REPO   the repository holding the issue          CHOREMASTER_POST_REPO (required)
  --title TEXT        the standing issue's exact title          CHOREMASTER_POST_TITLE (default "Chore Master morning report")
  --mention USER      a GitHub user to @-mention on its own line, so GitHub notifies them   CHOREMASTER_POST_MENTION
  --label NAME        a label to put on the issue when it is created                       CHOREMASTER_POST_LABEL
  --state-dir DIR     where last-report.txt is written

WHY AN ISSUE COMMENT. A digest in a journal nobody reads is a quiet day. One standing issue takes a comment
a day; the mention line is what makes GitHub notify the person. The issue is found by EXACT title among open
issues (a search is fuzzy, so the title is compared here) and created only when absent.

THE FILE COMES FIRST. <state dir>/last-report.txt is written before any network call, so a failed post still
leaves the digest on disk as well as in the journal.

Needs the GitHub CLI (`gh`) logged in. Env: GH=<path to gh>, tests point this at a stub.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

from choremaster import config, tz

DEFAULT_TITLE = "Chore Master morning report"
CREATE_BODY = ("The standing issue Chore Master posts its morning digest to, one comment a day. "
               "Leave it open; it is a notice board, not work.")


class PostError(Exception):
    pass


def gh(args, stdin=None):
    try:
        p = subprocess.run([os.environ.get("GH", "gh"), *args], input=stdin, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise PostError("could not run gh: %s" % e)
    if p.returncode != 0:
        raise PostError("gh %s failed (exit %d): %s" % (" ".join(args[:2]), p.returncode, (p.stderr or p.stdout).strip()[:300]))
    return p.stdout


def find_or_create(slug: str, title: str, label: str = "") -> str:
    out = gh(["issue", "list", "--repo", slug, "--state", "open", "--search", '"%s" in:title' % title,
              "--json", "number,title", "--limit", "100"])
    try:
        rows = json.loads(out or "[]")
    except ValueError as e:
        raise PostError("gh issue list printed something that is not JSON: %s" % e)
    for r in rows:
        if r.get("title") == title:
            return str(r["number"])
    cmd = ["issue", "create", "--repo", slug, "--title", title, "--body", CREATE_BODY]
    if label:
        cmd += ["--label", label]
    made = gh(cmd)
    m = re.search(r"/issues/(\d+)", made)
    if not m:
        raise PostError("gh issue create did not print an issue URL: %r" % made.strip()[:200])
    return m.group(1)


def comment_body(digest: str, day: str, mention: str = "") -> str:
    head = "Chore Master morning report, %s\n" % day
    if mention:
        head += "@%s\n" % mention.lstrip("@")
    return "%s\n%s" % (head, digest.rstrip("\n") + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    config.add_state_arg(ap)
    ap.add_argument("--repo", default=os.environ.get("CHOREMASTER_POST_REPO"))
    ap.add_argument("--title", default=os.environ.get("CHOREMASTER_POST_TITLE") or DEFAULT_TITLE)
    ap.add_argument("--mention", default=os.environ.get("CHOREMASTER_POST_MENTION") or "")
    ap.add_argument("--label", default=os.environ.get("CHOREMASTER_POST_LABEL") or "")
    ap.add_argument("--date", default=None)
    args = ap.parse_args(argv)
    home = config.state_dir(args.home)
    digest = sys.stdin.read()
    day = args.date or tz.today(datetime.now(timezone.utc)).isoformat()
    try:
        os.makedirs(home, exist_ok=True)
        with open(os.path.join(home, "last-report.txt"), "w", encoding="utf-8") as f:
            f.write(digest)
    except OSError as e:
        print("post_report: could not write last-report.txt: %s" % e, file=sys.stderr)
    if not args.repo:
        print("post_report: no repository given (--repo OWNER/REPO or CHOREMASTER_POST_REPO); not posting", file=sys.stderr)
        print(digest, end="" if digest.endswith("\n") else "\n")
        return 1
    if not digest.strip():
        print("post_report: the digest was empty; not posting an empty comment", file=sys.stderr)
        return 1
    try:
        number = find_or_create(args.repo, args.title, args.label)
        gh(["issue", "comment", number, "--repo", args.repo, "--body-file", "-"],
           stdin=comment_body(digest, day, args.mention))
    except PostError as e:
        print("post_report: could not post the digest: %s" % e, file=sys.stderr)
        print(digest, end="" if digest.endswith("\n") else "\n")
        return 1
    print("post_report: posted to %s#%s" % (args.repo, number))
    return 0


if __name__ == "__main__":
    sys.exit(main())
