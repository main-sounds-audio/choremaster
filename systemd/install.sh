#!/usr/bin/env bash
# Install (or check, or render) the Chore Master systemd units. Idempotent. Bash 3.2 safe.
#
#   sudo bash systemd/install.sh            install system units, replacing older copies
#   bash systemd/install.sh --user          install user units into ~/.config/systemd/user (no root)
#   bash systemd/install.sh --check         exit 0 installed + current + timers enabled and active, 1 not, 2 could not answer
#   bash systemd/install.sh --render        print the rendered units and write nothing
#
# `--check` and `--render` never write. Exit 2: the chores directory does not exist, or install needs root
# (or a writable UNIT_DIR) and was not given it.
#
# Settings, all environment variables with defaults:
#   CHOREMASTER_INSTALL_DIR  the checkout holding bin/choremaster           (default: this script's parent)
#   CHOREMASTER_CHORES       the chores directory                           (default: $PWD/chores)
#   CHOREMASTER_STATE        ledger and state directory                     (default: <home>/.local/state/choremaster)
#   CHOREMASTER_WORKDIR      where chore commands run                       (default: the directory above the chores)
#   CHOREMASTER_USER         the service user (system units)                (default: $SUDO_USER, else the current user)
#   CHOREMASTER_TZ           IANA zone the days and the morning time are read in (default: the machine's zone)
#   MORNING_TIME             HH:MM of the morning report                    (default: 08:00)
#   ENV_FILE                 optional systemd EnvironmentFile               (default: /etc/choremaster/choremaster.env,
#                                                                            ~/.config/choremaster/env with --user)
#   SERVICE_HOME             the service user's home                       (default: from the user database)
#   PYTHON                   the interpreter                                (default: python3 on PATH)
#   UNIT_DIR                 where units go                                 (default: /etc/systemd/system, or the user dir)
#   SYSTEMCTL                the systemctl to call                          (default: systemctl; tests stub it)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE"
UNITS="choremaster.service choremaster.timer choremaster-morning.service choremaster-morning.timer"
TIMERS="choremaster.timer choremaster-morning.timer"
MODE=install
USERMODE=0
for arg in "$@"; do
  case "$arg" in
    --render) MODE=render ;;
    --check) MODE=check ;;
    --user) USERMODE=1 ;;
    *) echo "usage: install.sh [--user] [--check|--render]" >&2; exit 2 ;;
  esac
done

SYSTEMCTL="${SYSTEMCTL:-systemctl}"
[ "$USERMODE" = 1 ] && SYSTEMCTL_ARGS="--user" || SYSTEMCTL_ARGS=""
SVC_USER="${CHOREMASTER_USER:-${SUDO_USER:-$(id -un)}}"
# Under sudo, $HOME is root's, so ask the user database for the service user's home.
SVC_HOME="${SERVICE_HOME:-}"
[ -n "$SVC_HOME" ] || SVC_HOME="$( (getent passwd "$SVC_USER" 2>/dev/null || true) | cut -d: -f6)"
[ -n "$SVC_HOME" ] || SVC_HOME="$HOME"

INSTALL_DIR="${CHOREMASTER_INSTALL_DIR:-$(cd "$HERE/.." && pwd)}"
CHORES="${CHOREMASTER_CHORES:-$PWD/chores}"
STATE="${CHOREMASTER_STATE:-$SVC_HOME/.local/state/choremaster}"
WORKDIR="${CHOREMASTER_WORKDIR:-$(dirname "$CHORES")}"
MORNING_TIME="${MORNING_TIME:-08:00}"
PYTHON="${PYTHON:-$(command -v python3 || true)}"
TZNAME="${CHOREMASTER_TZ:-}"
ZONE_SUFFIX=""; [ -n "$TZNAME" ] && ZONE_SUFFIX=" $TZNAME"
if [ "$USERMODE" = 1 ]; then
  UNIT_DIR="${UNIT_DIR:-$SVC_HOME/.config/systemd/user}"
  ENV_FILE="${ENV_FILE:-$SVC_HOME/.config/choremaster/env}"
  SERVICE_USER_LINE="# (user unit: runs as the logged-in user)"
else
  UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"
  ENV_FILE="${ENV_FILE:-/etc/choremaster/choremaster.env}"
  SERVICE_USER_LINE="User=$SVC_USER"
fi

if [ -z "$PYTHON" ]; then echo "choremaster: python3 was not found on PATH" >&2; exit 2; fi
case "$MORNING_TIME" in [0-2][0-9]:[0-5][0-9]) ;; *) echo "choremaster: MORNING_TIME must look like 08:00, got $MORNING_TIME" >&2; exit 2;; esac
# Units that point at no chores directory fail every tick: refuse to render, check or install them.
if [ ! -d "$CHORES" ]; then
  echo "choremaster: $CHORES does not exist; set CHOREMASTER_CHORES to your chores directory" >&2
  exit 2
fi

esc() { printf '%s' "$1" | sed -e 's/[\\|&]/\\&/g'; }
render_unit() { # $1 = unit file name
  sed -e "s|@SERVICE_USER_LINE@|$(esc "$SERVICE_USER_LINE")|g" \
      -e "s|@HOME@|$(esc "$SVC_HOME")|g" \
      -e "s|@INSTALL_DIR@|$(esc "$INSTALL_DIR")|g" \
      -e "s|@CHORES@|$(esc "$CHORES")|g" \
      -e "s|@STATE@|$(esc "$STATE")|g" \
      -e "s|@WORKDIR@|$(esc "$WORKDIR")|g" \
      -e "s|@ENV_FILE@|$(esc "$ENV_FILE")|g" \
      -e "s|@PYTHON@|$(esc "$PYTHON")|g" \
      -e "s|@MORNING_TIME@|$(esc "$MORNING_TIME")|g" \
      -e "s|@ZONE_SUFFIX@|$(esc "$ZONE_SUFFIX")|g" \
      "$SRC/$1"
}

case "$MODE" in
  render)
    for u in $UNITS; do
      printf '# ==== %s ====\n' "$u"
      render_unit "$u"
    done
    ;;
  check)
    bad=0
    for u in $UNITS; do
      if [ ! -f "$UNIT_DIR/$u" ]; then echo "choremaster: $u is not installed ($UNIT_DIR/$u is missing)"; bad=1; continue; fi
      if ! render_unit "$u" | diff -q - "$UNIT_DIR/$u" >/dev/null 2>&1; then
        echo "choremaster: the installed $u is out of date; re-run install.sh"; bad=1
      fi
    done
    for t in $TIMERS; do
      "$SYSTEMCTL" $SYSTEMCTL_ARGS is-enabled --quiet "$t" 2>/dev/null || { echo "choremaster: $t is not enabled; re-run install.sh"; bad=1; }
      "$SYSTEMCTL" $SYSTEMCTL_ARGS is-active --quiet "$t" 2>/dev/null || { echo "choremaster: $t is not active; re-run install.sh"; bad=1; }
    done
    if [ "$bad" = 0 ]; then echo "choremaster: units installed, current, timers enabled and active"; exit 0; fi
    exit 1
    ;;
  install)
    mkdir -p "$UNIT_DIR" 2>/dev/null || true
    if [ ! -d "$UNIT_DIR" ] || [ ! -w "$UNIT_DIR" ]; then
      echo "choremaster: cannot write $UNIT_DIR; run with sudo (or use --user)" >&2
      exit 2
    fi
    for u in $UNITS; do
      render_unit "$u" > "$UNIT_DIR/$u.tmp"
      mv "$UNIT_DIR/$u.tmp" "$UNIT_DIR/$u"
    done
    "$SYSTEMCTL" $SYSTEMCTL_ARGS daemon-reload
    for t in $TIMERS; do "$SYSTEMCTL" $SYSTEMCTL_ARGS enable --now "$t"; done
    echo "choremaster: installed units in $UNIT_DIR (tick every 15 minutes, report daily at $MORNING_TIME${TZNAME:+ $TZNAME})"
    echo "choremaster: to remove: systemctl ${SYSTEMCTL_ARGS:+$SYSTEMCTL_ARGS }disable --now $TIMERS; delete $UNITS from $UNIT_DIR"
    ;;
esac
