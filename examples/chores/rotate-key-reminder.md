---
id: rotate-key-reminder
title: Rotate the deploy key
do: Do it in the provider's console, then create the marker file below.
done_when: test -e "${KEY_ROTATED_MARKER:-$HOME/.deploy-key-rotated}"
links: Provider console|https://example.com/console
---
A reminder has no `run:`: it stays outstanding until `done_when` passes (or you delete the file).
Add `due: 2026-12-01T09:00` to hold it back until then (read in the configured time zone).

- Create a new deploy key
- Update the CI secret
- Delete the old key
