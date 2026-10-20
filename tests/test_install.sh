#!/usr/bin/env bash
# Self-test for systemd/install.sh and its unit files.
# Run: bash tests/test_install.sh   (bash 3.2 clean)
# systemctl is a stub; UNIT_DIR, HOME and the chores directory are fixtures, so nothing real is touched.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUT="$ROOT/systemd/install.sh"
TMP="$(mktemp -d)" || { echo "cannot mktemp"; exit 2; }
case "$TMP" in /*) :;; *) echo "mktemp gave a relative path: $TMP"; exit 2;; esac
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s\n' "$1"; }
has() { case "$2" in *"$1"*) return 0;; *) return 1;; esac; }
t() { if [ "$1" = 0 ]; then ok "$2"; else bad "$2"; fi; }

BIN="$TMP/bin"; H="$TMP/home"; UD="$TMP/units"; LOG="$TMP/systemctl.log"; CH="$TMP/site/chores"
mkdir -p "$BIN" "$H" "$UD" "$CH"
cat > "$BIN/systemctl" <<STUB
#!/usr/bin/env bash
echo "\$@" >> "$LOG"
case "\$1" in
  --user) shift;;
esac
case "\$1" in
  is-enabled) [ "\${FAKE_ON:-1}" = "1" ] && exit 0 || exit 1;;
  is-active) [ "\${FAKE_ACTIVE:-\${FAKE_ON:-1}}" = "1" ] && exit 0 || exit 1;;
  *) exit 0;;
esac
STUB
chmod +x "$BIN/systemctl"

run() {
  out="$(HOME="$H" SERVICE_HOME="$H" CHOREMASTER_USER="$(id -un)" CHOREMASTER_CHORES="$CH" UNIT_DIR="$UD" \
         SYSTEMCTL="$BIN/systemctl" PYTHON=/usr/bin/python3 ENV_FILE="$H/choremaster.env" "$@" 2>&1)"; rc=$?
}
nofiles() { [ -z "$(find "$UD" "$H" -type f 2>/dev/null)" ]; }

# 1. render
run bash "$SUT" --render
[ $rc = 0 ]; t $? "1. --render succeeds"
if printf '%s\n' "$out" | grep '@[A-Z_]*@' >/dev/null; then bad "1. no @PLACEHOLDER@ is left unreplaced"; else ok "1. no @PLACEHOLDER@ is left unreplaced"; fi
has "OnCalendar=*:0/15" "$out"; t $? "1. the tick timer fires every 15 minutes"
has "OnCalendar=*-*-* 08:00:00" "$out"; t $? "1. the morning timer defaults to 08:00 in the machine's own zone"
c="$(printf '%s\n' "$out" | grep -c '^Persistent=true')"
[ "$c" = 2 ]; t $? "1. both timers are Persistent=true"
c="$(printf '%s\n' "$out" | grep -c '^RandomizedDelaySec=0')"
[ "$c" = 2 ]; t $? "1. both timers have RandomizedDelaySec=0"
has "User=$(id -un)" "$out"; t $? "1. the services run as the service user"
has "ExecStart=/usr/bin/python3 $ROOT/bin/choremaster tick" "$out"; t $? "1. the tick runs bin/choremaster tick from the checkout"
has "ExecStart=/bin/bash $ROOT/bin/choremaster-morning" "$out"; t $? "1. the morning unit runs choremaster-morning"
has "Environment=CHOREMASTER_CHORES=$CH" "$out"; t $? "1. the chores directory is passed in the environment"
has "Environment=CHOREMASTER_STATE=$H/.local/state/choremaster" "$out"; t $? "1. the state directory defaults under the service user's home"
has "WorkingDirectory=$TMP/site" "$out"; t $? "1. chores run in the directory above the chores directory"
has "EnvironmentFile=-$H/choremaster.env" "$out"; t $? "1. the env file is optional"
has "SuccessExitStatus=1" "$out"; t $? "1. exit 1 (a chore is outstanding) does not fail the unit"
nofiles; t $? "1. --render wrote nothing"

# 2. zone and time are configurable
run env CHOREMASTER_TZ=America/New_York MORNING_TIME=07:30 bash "$SUT" --render
has "OnCalendar=*-*-* 07:30:00 America/New_York" "$out"; t $? "2. MORNING_TIME and CHOREMASTER_TZ set the morning timer"
run env MORNING_TIME=7am bash "$SUT" --render
[ $rc = 2 ]; t $? "2. a bad MORNING_TIME is exit 2"

# 3. check with nothing installed
run bash "$SUT" --check
[ $rc = 1 ]; t $? "3. --check with nothing installed exits 1"
has "not installed" "$out"; t $? "3. and says so"
nofiles; t $? "3. --check wrote nothing"

# 4. install
run bash "$SUT"
[ $rc = 0 ]; t $? "4. install succeeds ($out)"
for u in choremaster.service choremaster.timer choremaster-morning.service choremaster-morning.timer; do
  [ -f "$UD/$u" ]; t $? "4. $u is installed"
done
grep -q 'enable --now choremaster.timer' "$LOG"; t $? "4. the tick timer is enabled and started"
grep -q 'enable --now choremaster-morning.timer' "$LOG"; t $? "4. the morning timer is enabled and started"
has "to remove" "$out"; t $? "4. the install says how to remove it"
run bash "$SUT" --check
[ $rc = 0 ]; t $? "4. --check after install exits 0"
echo "# edited" >> "$UD/choremaster.service"
run bash "$SUT" --check
[ $rc = 1 ] && has "out of date" "$out"; t $? "4. an edited unit is reported out of date"
FAKE_ON=0 run bash "$SUT" --check
[ $rc = 1 ] && has "not enabled" "$out"; t $? "4. timers that are not enabled are reported"

# 5. refusals
run env CHOREMASTER_CHORES="$TMP/nowhere" bash "$SUT" --render
[ $rc = 2 ]; t $? "5. a chores directory that does not exist is exit 2"
run env UNIT_DIR="/proc/nope/units" bash "$SUT"
[ $rc = 2 ]; t $? "5. an unwritable unit directory is exit 2 (needs sudo)"
run bash "$SUT" --bogus
[ $rc = 2 ]; t $? "5. an unknown flag is exit 2"

# 6. --user installs user units and calls systemctl --user
rm -f "$LOG"
run env UNIT_DIR="$TMP/user-units" bash "$SUT" --user
[ $rc = 0 ] && [ -f "$TMP/user-units/choremaster.timer" ]; t $? "6. --user installs into the user unit directory"
grep -q '^--user ' "$LOG"; t $? "6. and drives systemctl --user"
if grep -q '^User=' "$TMP/user-units/choremaster.service"; then bad "6. a user unit has no User= line"; else ok "6. a user unit has no User= line"; fi

echo; echo "$pass passed, $fail failed"
[ "$fail" = 0 ]
