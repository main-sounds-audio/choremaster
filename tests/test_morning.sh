#!/usr/bin/env bash
# Self-test for bin/choremaster-morning, the morning run. Bash 3.2 clean.
# Run: bash tests/test_morning.sh
# The chores directory is a fixture, HOME and CHOREMASTER_STATE are throwaway, and `gh` is a stub that records
# what it was sent. THE CASE THAT CARRIES THE SUITE IS 2: a post that fails must be loud (non-zero) and the
# digest must still reach stdout and the disk.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUT="$ROOT/bin/choremaster-morning"
TMP="$(mktemp -d)" || { echo "cannot mktemp"; exit 2; }
case "$TMP" in /*) :;; *) echo "mktemp gave a relative path: $TMP"; exit 2;; esac
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s\n' "$1"; }
has() { case "$2" in *"$1"*) return 0;; *) return 1;; esac; }
t() { if [ "$1" = 0 ]; then ok "$2"; else bad "$2"; fi; }

H="$TMP/home"; WORK="$TMP/work"; STATE="$TMP/state"; BIN="$TMP/bin"; CALLS="$TMP/gh.calls"
mkdir -p "$WORK/chores" "$H" "$STATE" "$BIN"
printf -- '---\nid: always-red\nrun: echo a finding; exit 1\n---\n' > "$WORK/chores/always-red.md"
cat > "$BIN/gh" <<STUB
#!/usr/bin/env bash
echo "\$*" >> "$CALLS"
[ "\${1:-}" = issue ] && [ "\${2:-}" = comment ] && cat >> "$CALLS.body"
case "\${2:-}" in
  list) echo '[{"number":42,"title":"Chore Master morning report"}]';;
  comment) [ "\${FAKE_GH_FAIL:-0}" = 1 ] && { echo "HTTP 502" >&2; exit 1; } ;;
esac
exit 0
STUB
chmod +x "$BIN/gh"

BASE_ENV="HOME=$H CHOREMASTER_STATE=$STATE CHOREMASTER_CHORES=$WORK/chores CHOREMASTER_TZ=Europe/Dublin CHOREMASTER_ENV_FILE=$TMP/none.env CHOREMASTER_RETIRED_MARKER=$TMP/no-marker"
run() {
  out="$(env $BASE_ENV GH="$BIN/gh" CHOREMASTER_POST_REPO=acme/ops CHOREMASTER_POST_MENTION=octocat bash "$SUT" 2>"$TMP/err")"; rc=$?
  err="$(cat "$TMP/err")"
}

# 1. the good path
run
[ $rc = 0 ]; t $? "1. a good morning exits 0 ($err)"
[ -s "$STATE/last-report.txt" ]; t $? "1. the digest is written to last-report.txt"
grep -q 'issue comment 42' "$CALLS"; t $? "1. it commented on the standing issue"
grep -q '^@octocat$' "$CALLS.body"; t $? "1. the comment mentions the configured user on its own line"
grep -q '^Chore Master:' "$CALLS.body"; t $? "1. the comment carries the digest headline"
grep -q 'always-red' "$CALLS.body"; t $? "1. the tick ran first (the failing chore is in the digest)"
[ -f "$STATE/heartbeat.json" ]; t $? "1. the tick wrote its heartbeat"

# 2. the post fails: loud, with the digest
rm -f "$CALLS" "$CALLS.body"
FAKE_GH_FAIL=1 run
[ $rc != 0 ]; t $? "2. a failed post exits non-zero"
has "Chore Master:" "$out"; t $? "2. the digest is printed to stdout so the journal carries it"
has "could not post" "$err"; t $? "2. stderr says the post failed"
[ -s "$STATE/last-report.txt" ]; t $? "2. last-report.txt still holds the digest"

# 3. the digest cannot be produced: loud, nothing posted
rm -f "$CALLS" "$CALLS.body"
cat > "$BIN/py" <<'STUB'
#!/usr/bin/env bash
case "$*" in *" report"*) echo "boom" >&2; exit 3;; esac
exec python3 "$@"
STUB
chmod +x "$BIN/py"
out="$(env $BASE_ENV GH="$BIN/gh" PYTHON="$BIN/py" CHOREMASTER_POST_REPO=acme/ops bash "$SUT" 2>"$TMP/err")"; rc=$?
[ $rc = 1 ]; t $? "3. no digest exits 1"
grep -q "no digest to post" "$TMP/err"; t $? "3. and says so"
[ ! -e "$CALLS.body" ]; t $? "3. and posts nothing"

# 4. with no repository configured the digest is simply printed
rm -f "$CALLS" "$CALLS.body"
out="$(env $BASE_ENV GH="$BIN/gh" bash "$SUT" 2>"$TMP/err")"; rc=$?
[ $rc = 0 ]; t $? "4. no CHOREMASTER_POST_REPO: exits 0"
has "Chore Master:" "$out"; t $? "4. and prints the digest to stdout"
[ ! -e "$CALLS" ]; t $? "4. and never calls gh"

# 5. it is plain: no desktop app, no GUI launcher
case "$(cat "$SUT")" in *"open "*|*xdg-open*|*osascript*) bad "5. no app launcher in the script";; *) ok "5. no app launcher in the script";; esac

echo; echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
