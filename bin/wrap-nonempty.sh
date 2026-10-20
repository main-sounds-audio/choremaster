#!/usr/bin/env bash
# Turn "a check that prints nothing when clean" into the 0/1/2 convention.
#
#   bash bin/wrap-nonempty.sh COMMAND [ARGS...]
#
# Exit 0 the command succeeded and printed nothing (clean); 1 it succeeded and
# printed something (outstanding, and what it printed is shown); 2 it FAILED or
# there was no command (could not answer: a crashed check is never clean, so its
# silence must not read as good news). Output on stderr counts as output.
# A deadline checker that lists late items and prints nothing when all is well is the case this exists for.
set -uo pipefail
if [ $# -eq 0 ]; then echo "usage: wrap-nonempty.sh COMMAND [ARGS...]" >&2; exit 2; fi
out="$("$@" 2>&1)"; rc=$?
if [ "$rc" -ne 0 ]; then
  [ -n "$out" ] && printf '%s\n' "$out"
  echo "(the command exited $rc)"
  exit 2
fi
if [ -n "$out" ]; then printf '%s\n' "$out"; exit 1; fi
exit 0
