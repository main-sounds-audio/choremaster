#!/usr/bin/env bash
# Run a check, keep its exit code, and on failure print only its finding lines.
#
#   bash bin/keep-matching.sh REGEX COMMAND [ARGS...]
#
# The morning digest shows the first lines of a chore's output, and some check
# scripts print a page of explanation before the finding
# (a long linter does). This filters the output and NOTHING ELSE: the
# exit code passes through untouched (1 finding, 2 could not answer), because a
# filter that made the output tidy by turning a finding into a clean run would
# be worse than the noise. On success it prints nothing. On failure it prints
# the lines matching REGEX (extended), or, if none match, the last five lines so
# an unrecognised failure still says something. Exit 2 for bad usage or a regex
# that does not compile.
set -uo pipefail
if [ $# -lt 2 ]; then echo "usage: keep-matching.sh REGEX COMMAND [ARGS...]" >&2; exit 2; fi
pattern="$1"; shift
# an invalid extended regex makes grep exit 2 even on empty input
printf '' | grep -E -- "$pattern" >/dev/null 2>&1
if [ $? -eq 2 ]; then echo "keep-matching: invalid regex: $pattern" >&2; exit 2; fi

out="$("$@" 2>&1)"; rc=$?
if [ "$rc" -eq 0 ]; then exit 0; fi
matched="$(printf '%s\n' "$out" | grep -E -- "$pattern" || true)"
if [ -n "$matched" ]; then
  printf '%s\n' "$matched"
else
  printf '%s\n' "$out" | tail -n 5
fi
case "$rc" in 1|2) exit "$rc";; *) exit 2;; esac
