#!/usr/bin/env bash
# Self-test for bin/keep-matching.sh.
#
# Run: bash tests/test_keep_matching.sh
#
# The wrapper exists because a long linter prints a page of
# explanation before its findings, and the morning digest shows the first lines
# of a note. THE CASE THAT CARRIES THE SUITE IS 4: the exit code must pass
# through untouched, or a filter that only makes output tidy would turn a
# finding into a clean run.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUT="$ROOT/bin/keep-matching.sh"
pass=0; fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s\n' "$1"; }
check(){ local reason=""
  [ "$3" = "$4" ] || reason="exit $4, wanted $3"
  if [ -n "$2" ]; then case "$5" in *"$2"*) :;; *) reason="$reason${reason:+; }output lacks '$2'";; esac; fi
  if [ -z "$reason" ]; then ok "$1"; else bad "$1 - $reason"; printf '%s\n' "$5" | sed 's/^/     | /'; fi; }
lacks(){ case "$3" in *"$2"*) bad "$1 - output has '$2'"; printf '%s\n' "$3" | sed 's/^/     | /';; *) ok "$1";; esac; }


out="$(bash "$SUT" 'UNSET|FAIL' bash -c 'echo preamble one; echo preamble two; echo "repo-a  UNSET"; echo "FAIL: bad"; exit 1' 2>&1)"; rc=$?
check "1. on failure it prints the matching lines" "repo-a  UNSET" 1 $rc "$out"
check "1. including the second" "FAIL: bad" 1 $rc "$out"
lacks "2. and drops the preamble" "preamble" "$out"
out="$(bash "$SUT" 'UNSET' bash -c 'echo preamble; exit 0' 2>&1)"; rc=$?
check "3. a command that succeeds is exit 0 and prints nothing" "" 0 $rc "$out"
[ -z "$out" ] && ok "3. no output on success" || bad "3. no output on success"
out="$(bash "$SUT" 'UNSET' bash -c 'echo "x UNSET"; exit 2' 2>&1)"; rc=$?
check "4. exit 2 passes through as 2" "UNSET" 2 $rc "$out"
out="$(bash "$SUT" 'UNSET' bash -c 'echo "x UNSET"; exit 1' 2>&1)"; rc=$?
check "4. exit 1 passes through as 1" "UNSET" 1 $rc "$out"
out="$(bash "$SUT" 'NEVERMATCHES' bash -c 'for i in 1 2 3 4 5 6 7 8; do echo "line $i"; done; exit 1' 2>&1)"; rc=$?
check "5. with no match, a failure shows the last five lines instead of nothing" "line 8" 1 $rc "$out"
lacks "5. and not the earlier ones" "line 2" "$out"
out="$(bash "$SUT" 'a|b(c' bash -c 'echo "abc"; exit 1' 2>&1)"; rc=$?
check "6. an invalid regex is a usage failure (2), never a clean run" "" 2 $rc "$out"
out="$(bash "$SUT" 2>&1)"; rc=$?
check "7. no arguments is 2 with a usage line" "usage" 2 $rc "$out"
out="$(bash "$SUT" 'x' 2>&1)"; rc=$?
check "7. a pattern with no command is 2" "usage" 2 $rc "$out"
out="$(bash "$SUT" 'x' definitely-not-a-command-xyz 2>&1)"; rc=$?
check "8. a missing command is 2" "" 2 $rc "$out"
printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
