---
id: disk-space
every: 1h
title: Disk is nearly full
do: Free some space before something fails.
run: used=$(df -P "${CHECK_PATH:-/}" | awk 'NR==2{gsub("%","",$5);print $5}'); [ "$used" -lt "${MAX_PERCENT:-90}" ] || { echo "${CHECK_PATH:-/} is ${used}% full (limit ${MAX_PERCENT:-90}%)"; exit 1; }
---
Fails (exit 1) when the filesystem holding CHECK_PATH (default `/`) is MAX_PERCENT (default 90) full or more.
If `df` itself breaks, the shell test errors and the chore reports "could not answer" (exit 2), never "clean".
