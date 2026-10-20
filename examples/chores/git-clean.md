---
id: git-clean
every: 1d
after: 09:00
title: A repository has uncommitted work
do: Commit it, stash it or delete it.
run: dir="${REPO_PATH:-.}"; out=$(git -C "$dir" status --porcelain) || exit 2; [ -z "$out" ] || { echo "$dir has uncommitted changes"; printf '%s\n' "$out" | head -n 10 | sed 's/^/- /'; exit 1; }
---
Fails when the git repository at REPO_PATH (default: the directory the chores run in) has uncommitted changes.
Not a git repository, or git missing: it could not answer (exit 2).
`after: 09:00` keeps it from running before nine o'clock in the configured time zone.
