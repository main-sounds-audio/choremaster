# Chore Master

A small scheduler for the checks and reminders you would otherwise forget. A **chore** is a markdown file with a
`run:` command and an `every:` interval. Every 15 minutes a **tick** runs the chores that are due, records each
outcome in a **ledger**, and once a morning a **report** tells you what needs attention.

- Standard library only (Python 3.9+, plus `bash`, `git` for the optional parts). Nothing to `pip install`.
- No model, no daemon, no database: a timer, one lock file, JSON lines on disk.
- A check that could not answer is never a clean check. Exit 2, a timeout, a crash, a missing command, an empty
  ledger and a dead scheduler are all reported as "needs attention", never as "all clear".

## The chore file

One `.md` file per chore in your chores directory. Flat `key: value` front matter between `---` lines, then a free-text
body (a note to whoever reads the report; for a reminder, the checklist).

```markdown
---
id: disk-space
every: 1h
title: Disk is nearly full
do: Free some space before something fails.
run: df -P / | awk 'NR==2 { gsub("%","",$5); exit ($5 >= 90) }'
---
Fails when `/` is 90% full or more.
```

| key | meaning |
| --- | --- |
| `id` | Required. Lower-case letters, digits and `-`. Unique across the directory. |
| `run` | A shell command (run with `bash -c`, in the work directory). Its exit code is the answer, see below. No `run` makes a **reminder**: outstanding until `done_when` passes or you delete the file. |
| `every` | `15m`, `1h`, `1d`. How often it runs. Default `1d`, meaning once per local calendar date. A chore that exits 2 is retried after an hour, not at its next period. |
| `due` | ISO 8601 time. Not run before it. A time with no offset is read in your time zone. |
| `after` | `HH:MM` local time of day. A daily chore does not run before it (a check at noon, not at the first tick after midnight). |
| `done_when` | A command run before `run`. Exit 0 marks the chore done for good: it never runs again and the report lists it once under "Done". Exit 2 (could not answer) leaves the chore open and still runs it. |
| `title` | A heading for the report. With a title the item prints as a to-do: bold title, the summary, the italic `do:` line, bullets, links. |
| `do` | One line telling the reader what to do. |
| `links` | `label\|url; label\|url`. `https://` only (plus `http://127.0.0.1`, `http://localhost`, `http://name.local`). |
| `names_paused` | `true`: do not filter this chore's output through the pause list (below). |
| `private` | `yes`: its output is blanked in the optional published ledger copy (below). |
| `waits` | `<ref> <what>`: see "Waiting on something" below. |

A `#` after whitespace starts a comment in front matter; `#` inside a value (`ticket #12`) does not. Any other key is an
error, so a typo is a finding and not a silent no-op. A broken file never stops the other chores: it is recorded in the
ledger and shown in the report.

### The exit-code convention

| exit | meaning | report says |
| --- | --- | --- |
| 0 | answered, nothing to do | ran clean |
| 1 | answered, something is outstanding | outstanding, with the command's first lines |
| 2 | could not answer | could not answer |

Anything else (a signal, `127` command not found, a timeout, a missing directory) counts as 2. An uncaught Python
traceback exits 1 by default, so a command that prints one is recorded as 2, "crashed". Print the summary on the first
line and findings as `- ` bullets on the lines after it: the report shows up to twelve lines of a command's output.

Two small wrappers in `bin/` help old scripts fit the convention: `keep-matching.sh REGEX COMMAND...` (on failure print only the
matching lines, exit code untouched) and `wrap-nonempty.sh COMMAND...` ("prints nothing when clean" becomes 0, prints something
becomes 1, crashes become 2).

## Install

```sh
git clone <this repository> choremaster && cd choremaster
mkdir -p ~/chores && cp examples/chores/*.md ~/chores/     # start from the examples
export CHOREMASTER_CHORES=~/chores
python3 bin/choremaster tick                               # run what is due, once
python3 bin/choremaster report                             # print the digest
```

Or install the `choremaster` command: `pip install .` (then `choremaster tick`, `choremaster report`; `python3 -m choremaster ...`
works from a checkout too).

### Run it every 15 minutes (systemd)

```sh
CHOREMASTER_CHORES=$HOME/chores CHOREMASTER_TZ=Europe/Paris MORNING_TIME=08:00 bash systemd/install.sh --user      # no root
sudo CHOREMASTER_CHORES=/srv/chores CHOREMASTER_USER=chores bash systemd/install.sh                                 # or system units
bash systemd/install.sh --render        # print the units and write nothing
bash systemd/install.sh --check         # 0 installed, current and the timers enabled and active
```

That installs `choremaster.timer` (every 15 minutes, `Persistent=true` so a missed tick runs once at boot) and
`choremaster-morning.timer` (daily at `MORNING_TIME`, a full tick then the report). Every path is a variable, see the header
of `systemd/install.sh`. Variables the chores need (an API token, `CHOREMASTER_TZ`) go in the optional env file,
`/etc/choremaster/choremaster.env` (`~/.config/choremaster/env` with `--user`), in systemd `EnvironmentFile` syntax. To remove:
`systemctl disable --now choremaster.timer choremaster-morning.timer` and delete the four unit files.

No systemd? Any scheduler that runs `python3 /path/to/bin/choremaster tick` every 15 minutes works (cron:
`*/15 * * * * ...`; launchd: `StartInterval` 900). One tick at a time is guaranteed by a lock file, so overlapping runs are harmless.

## Settings

| what | flag | environment | default |
| --- | --- | --- | --- |
| chores directory | `--chores` | `CHOREMASTER_CHORES` | `./chores` |
| ledger and state directory | `--state-dir` | `CHOREMASTER_STATE` | `~/.local/state/choremaster` |
| directory chore commands run in | `--workdir` (tick) | | the directory above the chores directory |
| time zone for "a day", `after:` and naive `due:` | | `CHOREMASTER_TZ` (an IANA name such as `America/New_York`) | the machine's local zone |
| extra `PATH` entries for chore commands | | `CHOREMASTER_EXTRA_PATH` (colon-separated) | none |
| service env file read by `report`, `ran-since` run by hand | | `CHOREMASTER_ENV_FILE` | `/etc/choremaster/choremaster.env` |

An unknown `CHOREMASTER_TZ` falls back to UTC and says so, once a day, in the report.

## Run a tick

```console
$ python3 bin/choremaster tick
choremaster: chore git-clean reported outstanding (exit 1): ./ has uncommitted changes
choremaster: exiting 1: 1 chore(s) outstanding, not a tick failure (git-clean); the ledger has the detail
```

For each due chore the tick: runs `done_when` (if any), then `run`, with a 10-minute timeout (`--chore-timeout`) that kills
the command's whole process group; records one ledger row; updates `state.json`; and finally writes `heartbeat.json`. The
chore's id is in `$CHOREMASTER_CHORE`, so a wrapper it calls can attribute the call to it. Exit code of the tick: 0 all fine,
1 some chore is outstanding (each named on stdout, so the journal says why), 2 the tick itself failed. Other flags:

- `--pull` first fetches and fast-forwards the git checkout in the work directory (never merges; it ignores `FETCH_HEAD`). Keep
  your chores in a repository and merging a chore is deploying it.
- `--lock-wait SECONDS` waits for another tick's lock instead of skipping.
- `--now ISO` pretends it is that time (used by the tests).
- **Retiring a host:** while the file `~/.config/choremaster-retired-host` (or `$CHOREMASTER_RETIRED_MARKER`) exists, the tick
  prints one line naming the host written in it and exits 0, recording nothing. Use it when you move the scheduler to another
  machine and want the old timer to stay enabled but quiet.

### Where things are written

```
<state dir>/ledger/YYYY-MM-DD.jsonl   one JSON line per event: at, id, kind (ran|done|error|retired), code, note
<state dir>/state.json                per chore: last_ran, last_code, done
<state dir>/heartbeat.json            written at the end of every tick
<state dir>/tick.lock                 flock; the kernel drops it if the tick dies
```

Anything that looks like a token (`sk-ant-...`, `ghp_...`, `github_pat_...`, AWS and Slack keys) is redacted before a note is
written, and a note is capped at 4000 characters.

## The report

```console
$ python3 bin/choremaster report
Chore Master: 2 need attention
Needs attention (2):

1. **Disk is nearly full**
   outstanding: / is 93% full (limit 90%)
   *Free some space before something fails.*
2. **rotate-key-reminder** — outstanding: Rotate the deploy key
   ...

Done since yesterday (1):
- ...

Ran clean (2): url-answers, git-clean
```

Line 1 is the headline (use it as an email subject or notification title). The report reads the last 26 hours of the ledger,
takes the latest row per chore, and says "nothing recorded" (not "all clear") when there is none, and "the Chore Master tick
has never written a heartbeat / last heartbeat was N ago" when the tick is not running. The same ledger always renders the
same report. `python3 -m choremaster report --now ISO` prints it as of another time.

`bin/choremaster-morning` is the morning run for a timer: tick, optionally retire finished chores
(`CHOREMASTER_RETIRE=1`), report, and, when `CHOREMASTER_POST_REPO=OWNER/REPO` is set, post it.

### Posting the report to a GitHub issue

```sh
CHOREMASTER_POST_REPO=acme/ops CHOREMASTER_POST_MENTION=octocat bash bin/choremaster-morning
```

`post-report` (needs the GitHub CLI `gh`, logged in) finds the open issue titled exactly "Chore Master morning report"
(`CHOREMASTER_POST_TITLE`), creates it if absent (`CHOREMASTER_POST_LABEL` puts a label on it), and adds the digest as a
comment, with `@octocat` on its own line so GitHub notifies that user. The digest is written to `<state dir>/last-report.txt` before
any network call, and a failed post exits non-zero and prints the digest, so a failure is never a quiet morning.

## Other commands

- `choremaster ran-since --since YYYY-MM-DD ID...` exits 0 only if every id has a `ran` (code 0 or 1) or `done` row since that
  local date; names the ones that have not. A code 2 or an error row is not "ran".
- `choremaster retire [--apply | --check]` removes the files of chores `done_when` has finished, two days after (so the report
  announces them first), in one pull request opened from a throwaway clone (needs `git`, `gh` and an `origin`). `--check` fails when a
  done chore's file is still there after seven days: run it as a chore of its own.
- `choremaster heartbeat` / `tick --push-heartbeat` / `CHOREMASTER_PUSH_HEARTBEAT=1` force-pushes `heartbeat.json` to a single-commit
  orphan branch `choremaster-ledger` of the work directory's `origin`, at most hourly, so a watchdog that can only see the
  repository (a CI schedule) can tell the scheduler is alive. Off by default.
- **Pause list.** Names listed in `~/.config/choremaster/paused.txt` (`CHOREMASTER_PAUSED_FILE`; one name per line, first word is the
  name, `#` comments) are removed from every chore's output: a line naming one is dropped, a finding left with no bullet becomes a
  clean run, and a leading count ("3 items") is recounted. Chores that query a whole account then need no filter of their own.
  `names_paused: true` opts a chore out.
- **Waiting on something.** `waits: REF what is not checked` on a chore that has a `run` or `done_when`: when the tick runs with
  `--respect-waits` (or `CHOREMASTER_RESPECT_WAITS=1` in that unit's environment) the command is not run. The row says "not checked: ... waits on REF"
  (exit 2) for 7 days, then outstanding, so a check lost to a missing permission becomes a loud failure after a week.
- **Published copy.** With `CHOREMASTER_PUBLISH_DIR` set to a directory the tick can write, each tick copies the last two days
  of ledger and the heartbeat there (files mode 0640, atomic, no symlinks followed, one way: nothing ever reads it back), so another
  account can run `choremaster report --state-dir <that directory>`. `private: yes` chores are blanked in the copy.

## Tests

```sh
python3 -m pytest          # 16 python suites and 4 bash suites, one test each
python3 tests/test_tick.py # or any suite on its own: prints "N passed, M failed", exits 1 on a failure
bash tests/test_install.sh
```

Suites run under a throwaway `HOME` and a fixed time zone, so they never touch real state. `pytest` is only a runner; the suites
need nothing else.

## Layout

```
choremaster/     the package: tick, chorefile, schedule, runner, ledger, report, retire, ran_since, post_report, ...
bin/             choremaster (run from a checkout), choremaster-morning, keep-matching.sh, wrap-nonempty.sh
systemd/         the unit templates and install.sh
examples/chores/ four small chores to copy
tests/           the suites
```

## License

MIT, see [LICENSE](LICENSE).
