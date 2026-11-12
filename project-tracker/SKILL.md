---
name: project-tracker
description: Tracks software projects worked on with Claude Code - Claude usage (sessions, prompts, tokens per model), time spent working, and a daily build/change log covering the previous day. Use this skill whenever the user wants to start tracking a project, asks how much time or how many tokens/Claude usage a project has consumed, asks "what did I do yesterday / this week" on a project, wants a changelog, build log, work log, timesheet or progress summary for a project, wants an overview across their projects, or when a session-start note mentions "[project-tracker]" draft changelog entries that need writing up.
---

# Project Tracker

Keeps three things per project, stored in `<project>/.project-tracker/`:

| File | What it holds | Who writes it |
|---|---|---|
| `SUMMARY.md` | Claude usage (sessions, prompts, tokens by model) and time spent, in total and per day | script |
| `CHANGELOG.md` | One entry per worked day, newest first: what was built or changed | script drafts, **you** write the real entry |
| `data.json` | Per-session records backing the numbers | script |
| `config.json` | Name, idle threshold, timezone, optional pricing | script / user |

Everything mechanical is done by `scripts/tracker.py` (Python 3.9+, standard library only). Run it as `python3 <this skill's directory>/scripts/tracker.py <command>` from inside the project (or pass `--project <dir>` before the command). Don't compute usage or time by hand — the script's numbers are deduplicated and consistent; hand counts won't be.

## How the numbers are derived

Knowing this lets you answer "why does it say X?" honestly.

- **Claude usage** comes from Claude Code's session transcripts (`~/.claude/projects/…`) for this project directory: tokens from each assistant response (input, output, cache write, cache read), grouped by model and day.
- **Time spent** is measured from transcript activity: consecutive events less than the idle threshold apart (default 15 min) form a work block; longer gaps are treated as a break. Parallel sessions overlap rather than double-count. It is time spent working *with Claude* on the project — work done entirely outside Claude Code isn't visible, so describe it as that rather than as total hours.
- **Persistence**: Claude Code eventually deletes old transcripts, and cloud sessions lose them when the container ends. Each sync folds what it sees into `data.json` and never drops sessions it can no longer see, so `.project-tracker/` is the durable record. That is why it should be committed (see below).
- **Cost** is only shown if the user has put rates in `config.json` under `pricing` (`{"<model-name-substring>": {"input": …, "output": …, "cache_write": …, "cache_read": …}}`, dollars per million tokens). Don't fill in rates from memory — ask the user or look up current pricing — and note that on a subscription plan this is an API-equivalent figure, not a bill.

## Commands

| Command | Use |
|---|---|
| `init [--name N] [--timezone Europe/Amsterdam] [--idle-minutes 15] [--no-hooks]` | Start tracking the current project (git root). Safe to re-run to change settings. Installs session hooks unless `--no-hooks`. |
| `sync` | Refresh `data.json` and `SUMMARY.md`; draft entries for recent worked days missing from the changelog. |
| `report [--days N] [--json]` | Print the usage/time report (syncs first). |
| `digest [--date D]` | Raw material for one day's changelog entry: commits, files touched, the prompts given to Claude, existing entry. `D` is `YYYY-MM-DD`, `today` or `yesterday` (default). |
| `changelog-write [--date D]` | Write or replace that day's entry. Body on stdin (or `--file`). The heading and stats line are added for you. |
| `projects` | Table of every tracked project on this machine. |
| `install-hooks` | (Re)install the hooks. |

## Starting to track a project

1. Run `init`. Ask for the timezone only if the machine's isn't the user's (cloud sessions run in UTC, so there it matters: "yesterday" is cut at midnight in the configured zone).
2. Tell the user what was set up, including the hooks: `SessionStart` syncs and drafts the previous day's changelog entry; `SessionEnd` syncs so the session's usage is captured. If the skill lives inside the project they go in `.claude/settings.json` (shared); otherwise in `.claude/settings.local.json` with a machine-specific path.
3. Recommend committing `.project-tracker/` so history survives transcript cleanup and follows the repo across machines. Mention that `data.json` holds only counts and timestamps, never prompt text; the changelog holds whatever you write in it. If they'd rather keep it private, add `.project-tracker/` to `.gitignore` instead — their call, so ask rather than assume.

## The daily changelog

The goal: each day the user opens the project, `CHANGELOG.md` already has an entry telling them what happened the previous day they worked on it.

The `SessionStart` hook guarantees an entry exists by drafting one from git commits, marked `<!-- auto-generated draft -->`. A list of commit subjects is a poor changelog, though — it misses uncommitted work, the reasons behind changes, and anything left unfinished. So when the hook's note (or `sync`) reports draft entries, write them up properly:

1. `digest --date <day>` to see commits, files and what the user asked for that day. If the commits are terse, look at the actual diffs (`git show --stat <hash>`) for the ones that matter.
2. Write the entry body and pipe it to `changelog-write --date <day>`.

Do this near the start of the session, quickly and without ceremony — a one-line mention that yesterday's log was written is enough. The user came to do something else; finish this in the background of their request, don't make them wait for it or ask permission each day.

Entry body format (omit a section when it has nothing real to say):

```markdown
### Summary
Two or three sentences: what moved forward that day, in plain language.

### Changes
- **Added** … / **Changed** … / **Fixed** … / **Removed** … — one bullet per meaningful change, with the commit hash in backticks when there is one.

### Build & tooling
- Dependency, build, CI, config or deployment changes. Note anything left broken or failing.

### Open threads
- Work started but not finished, known bugs, decisions deferred — what tomorrow needs to know.
```

Write for the user a month from now: outcomes over mechanics ("Login form validates email and shows inline errors", not "edited form.tsx"). Group related commits into one bullet. State only what the digest and the repository support — if the transcripts for that day aren't on this machine and the commits don't explain it, say less rather than guess. The prompts in the digest are the user's own words from their sessions; summarise them, don't quote them at length, since the changelog is usually committed.

The user can also ask for an entry on demand ("log today's work"): use `--date today`. Re-running `changelog-write` for a day replaces that entry, so today's can be redone tomorrow when the day is complete.

## Answering questions

- "How much time / usage on this project?" → `report`, then answer in a sentence or two with the relevant figures; show the table only if they want the breakdown.
- "What did I do yesterday / last week?" → read `CHANGELOG.md` (write up any drafts first); pair with `report --days 7` if they want hours.
- "How are all my projects doing?" → `projects`. The registry is per machine, so projects tracked elsewhere won't be listed.
- Time looks too low or high → explain the idle threshold and offer `init --idle-minutes <n>`. It applies to sessions whose transcripts are still on disk; older stored sessions keep the blocks computed at the time.
