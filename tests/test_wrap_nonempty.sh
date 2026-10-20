#!/usr/bin/env bash
# Self-test for bin/wrap-nonempty.sh.
#
# Run: bash tests/test_wrap_nonempty.sh
#
# The wrapper turns "a check that prints nothing when clean" into the 0/1/2 exit convention.
# The case that matters
# is a command that FAILS: silence from a crashed check must be 2, never 0.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUT="$ROOT/bin/wrap-nonempty.sh"
TMP="$(mktemp -d)" || { echo "cannot mktemp"; exit 2; }
case "$TMP" in /*) :;; *) echo "mktemp gave a relative path: $TMP"; exit 2;; esac
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s\n' "$1"; }
check(){ local reason=""
  [ "$3" = "$4" ] || reason="exit $4, wanted $3"
  if [ -n "$2" ]; then case "$5" in *"$2"*) :;; *) reason="$reason${reason:+; }output lacks '$2'";; esac; fi
  if [ -z "$reason" ]; then ok "$1"; else bad "$1 - $reason"; printf '%s\n' "$5" | sed 's/^/     | /'; fi; }

out="$(bash "$SUT" true 2>&1)"; rc=$?
check "1. a silent command that succeeds is clean (0)" "" 0 $rc "$out"
[ -z "$out" ] && ok "1. and prints nothing" || bad "1. and prints nothing"
out="$(bash "$SUT" echo "MISSED: item 3" 2>&1)"; rc=$?
check "2. a command that prints something is outstanding (1)" "MISSED: item 3" 1 $rc "$out"
out="$(bash "$SUT" bash -c 'echo "two rows"; echo "row two"' 2>&1)"; rc=$?
check "3. all its lines are kept" "row two" 1 $rc "$out"
out="$(bash "$SUT" bash -c 'echo boom >&2' 2>&1)"; rc=$?
check "4. output on stderr counts as output (1)" "boom" 1 $rc "$out"
out="$(bash "$SUT" bash -c 'exit 3' 2>&1)"; rc=$?
check "5. a silent command that FAILS is 2, never clean" "exited 3" 2 $rc "$out"
out="$(bash "$SUT" bash -c 'echo trace; exit 1' 2>&1)"; rc=$?
check "6. a command that prints and fails is 2 and shows what it printed" "trace" 2 $rc "$out"
out="$(bash "$SUT" definitely-not-a-command-xyz 2>&1)"; rc=$?
check "7. a missing command is 2" "" 2 $rc "$out"
out="$(bash "$SUT" 2>&1)"; rc=$?
check "8. no command at all is 2 with a usage line" "usage" 2 $rc "$out"
printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
