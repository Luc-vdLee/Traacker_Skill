---
name: project-tracker
description: Tracks software projects worked on with Claude Code - Claude usage (sessions, prompts, tokens per model), time spent working, a daily build/change log covering the previous day, a goals/next-steps list, and a visual dashboard published as a Claude Artifact per project. Use this skill whenever the user wants to start tracking a project, asks how much time or how many tokens/Claude usage a project has consumed, asks "what did I do yesterday / this week" on a project, wants a changelog, build log, work log, timesheet, progress summary or dashboard for a project, mentions project goals, next steps or what's left to do, wants an overview across their projects, or when a session-start note mentions "[project-tracker]" draft changelog entries that need writing up.
---

# Project Tracker

Keeps these per project, stored in `<project>/.project-tracker/`:

| File | What it holds | Who writes it |
|---|---|---|
| `SUMMARY.md` | Claude usage (sessions, prompts, tokens by model) and time spent, in total and per day | script |
| `CHANGELOG.md` | One entry per worked day, newest first: what was built or changed | script drafts, **you** write the real entry |
| `GOALS.md` | Checklist of goals and next steps (Now / Later / Done) | **you**, with the user |
| `sessions/*.json` | One small record per Claude session backing the numbers | script |
| `config.json` | Name, idle threshold, timezone, auto-commit, optional pricing | script / user |
| `dashboard*.html` | The dashboard page, generated for the project's Claude Artifact or local viewing (git-ignored) | script |

Everything mechanical is done by `scripts/tracker.py` (Python 3.9+, standard library only). Run it as `python3 <this skill's directory>/scripts/tracker.py <command>` from inside the project (or pass `--project <dir>` before the command). Don't compute usage or time by hand — the script's numbers are deduplicated and consistent; hand counts won't be.

## How the numbers are derived

Knowing this lets you answer "why does it say X?" honestly.

- **Claude usage** comes from Claude Code's session transcripts (`~/.claude/projects/…`) for this project directory: tokens from each assistant response (input, output, cache write, cache read), grouped by model and day.
- **Time spent** is measured from transcript activity: consecutive events less than the idle threshold apart (default 15 min) form a work block; longer gaps are treated as a break. Parallel sessions overlap rather than double-count. It is time spent working *with Claude* on the project — work done entirely outside Claude Code isn't visible, so describe it as that rather than as total hours.
- **Persistence**: Claude Code eventually deletes old transcripts, and cloud sessions lose them when the container ends. Each sync folds what it sees into `sessions/` and never drops sessions it can no longer see, so `.project-tracker/` is the durable record. That is why it is committed (see below).
- **Cost** is only shown if the user has put rates in `config.json` under `pricing` (`{"<model-name-substring>": {"input": …, "output": …, "cache_write": …, "cache_read": …}}`, dollars per million tokens). Don't fill in rates from memory — ask the user or look up current pricing — and note that on a subscription plan this is an API-equivalent figure, not a bill.

## Commands

| Command | Use |
|---|---|
| `init --vendor [--name N] [--timezone Europe/Amsterdam] [--idle-minutes 15] [--no-hooks] [--no-auto-commit]` | Start tracking the current project (git root). Safe to re-run to change settings. `--vendor` copies this skill into `<project>/.claude/skills/` so it also works in cloud sessions. |
| `sync` | Refresh `sessions/` and `SUMMARY.md`; draft entries for recent worked days missing from the changelog. |
| `report [--days N] [--json]` | Print the usage/time report (syncs first). |
| `digest [--date D]` | Raw material for one day's changelog entry: commits, files touched, the prompts given to Claude, existing entry. `D` is `YYYY-MM-DD`, `today` or `yesterday` (default). |
| `changelog-write [--date D]` | Write or replace that day's entry. Body on stdin (or `--file`). The heading and stats line are added for you. |
| `dashboard [--artifact] [--all] [--days 30] [--out FILE]` | Write the dashboard page: time and tokens per day, goals, recent changelog. `--artifact` writes it for publishing as the project's Claude Artifact. |
| `artifact-url [URL]` | Show, or store, the link of the project's Claude Artifact. |
| `commit` | Sync, then git-commit `.project-tracker/` and nothing else. |
| `projects` | Table of every tracked project on this machine. |
| `install-hooks` | (Re)install the hooks. |

## Starting to track a project

The user works both locally and in cloud sessions, so set projects up to work in both:

1. Run `init --vendor --timezone <IANA zone>`. Vendoring puts the skill and its hooks inside the repository (`.claude/skills/project-tracker/`, `.claude/settings.json`), which is the only way a cloud session — a fresh container with nothing but the repo — can run them. Set the timezone explicitly: cloud containers run in UTC, and "yesterday" has to be cut at the user's midnight on every machine. If you don't know their zone, ask once; it is stored in `config.json` for good.
2. Commit what was created: `.project-tracker/`, `.claude/skills/project-tracker/` and `.claude/settings.json`. Tracking data is always committed in this user's projects — it is how history survives transcript cleanup, follows the repo between machines, and exists at all in cloud sessions. `sessions/*.json` hold only counts and timestamps, never prompt text.
3. Publish the project's Claude Artifact (see "The project's Claude Artifact") and give the user its link.
4. Tell the user briefly what now happens automatically (next section), and ask whether they have goals or next steps to record in `GOALS.md`.

## What runs automatically, and committing

- **SessionStart hook**: syncs, drafts changelog entries for recent worked days that lack one, commits `.project-tracker/`, and tells you if drafts need writing up.
- **SessionEnd hook**: syncs so the session's usage is captured, and commits `.project-tracker/`.

The hook commits (`chore(tracker): update project tracking`) include only paths under `.project-tracker/` — never the user's other staged or unstaged work — and are never pushed by the hook. Turn them off with `init --no-auto-commit`.

When you change tracker files yourself (a changelog entry, goals), run `commit` afterwards rather than leaving them dirty. Push along with the user's normal flow; in a cloud session, push before the session ends, because unpushed commits vanish with the container. Don't open pull requests just for tracking data.

Working from several machines is expected: each session is its own file, and `CHANGELOG.md`/`SUMMARY.md` use git's union merge, so pulls merge cleanly. After a merge, run `sync` to regenerate `SUMMARY.md`. If `CHANGELOG.md` ends up with two entries for one day, `digest` that day and rewrite it with `changelog-write`, which collapses them into one.

## The daily changelog

The goal: each day the user opens the project, `CHANGELOG.md` already has an entry telling them what happened the previous day they worked on it.

The `SessionStart` hook guarantees an entry exists by drafting one from git commits, marked `<!-- auto-generated draft -->`. A list of commit subjects is a poor changelog, though — it misses uncommitted work, the reasons behind changes, and anything left unfinished. So when the hook's note (or `sync`) reports draft entries, write them up properly:

1. `digest --date <day>` to see commits, files and what the user asked for that day. If the commits are terse, look at the actual diffs (`git show --stat <hash>`) for the ones that matter.
2. Write the entry body and pipe it to `changelog-write --date <day>`.
3. Update `GOALS.md` if needed, then run `commit`.
4. Refresh the project's Claude Artifact (see below).

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

When an entry shows a goal was finished, tick it in `GOALS.md` at the same time (see below), and let unfinished goals inform "Open threads" — the digest lists the open ones.

Write for the user a month from now: outcomes over mechanics ("Login form validates email and shows inline errors", not "edited form.tsx"). Group related commits into one bullet. State only what the digest and the repository support — if the transcripts for that day aren't on this machine and the commits don't explain it, say less rather than guess. The prompts in the digest are the user's own words from their sessions; summarise them, don't quote them at length, since the changelog is usually committed.

The user can also ask for an entry on demand ("log today's work"): use `--date today`. Re-running `changelog-write` for a day replaces that entry, so today's can be redone tomorrow when the day is complete.

## Goals and next steps

`GOALS.md` is a plain checklist with three sections — **Now**, **Later**, **Done** — that you maintain by editing the file directly:

- Add items when the user states a goal, milestone or "we still need to…", phrased as an outcome (`- [ ] Users can reset their password by email`).
- When work completes one, change it to `- [x] … (YYYY-MM-DD)` and move it under Done. Do this as part of writing the daily entry, when you can see from the digest what got finished.
- Keep Now short (what's actually in progress or next); park the rest under Later.

It is the user's list: record what they say they want, and suggest additions rather than inventing goals for them. Open/done counts appear in `SUMMARY.md` and the dashboard.

## The project's Claude Artifact

Each tracked project has one private Claude Artifact — a page on claude.ai — that is the readable home of its tracked info: usage, time, goals and the recent changelog. The files in `.project-tracker/` remain the source of truth; the artifact is the view the user actually opens, from any device. Its link is stored in `config.json` (`artifact_url`) so that every session, on any machine, updates the same page instead of creating a new one.

Refresh it whenever the tracked info has meaningfully changed: after writing a daily changelog entry (so it is current at least once per worked day), after editing goals, and whenever the user asks to see the tracker or dashboard.

1. Run `dashboard --artifact`. It writes `.project-tracker/dashboard.artifact.html` in the form the Artifact tool expects and prints the stored link, if any.
2. **No link yet** — publish the file as a new artifact (icon `chart`, a one-sentence description naming the project), then store the link with `artifact-url <url>` and run `commit` so other machines find it.
3. **Link exists** — update that artifact in place: read it first with the Artifact tool (`action: read`, the tool refuses to overwrite a page the session hasn't seen), then publish the file with that `url`. Don't publish without the `url`; that would create a second page and orphan the link the user has bookmarked.
4. Give the user the link, in one line.

If the stored link can't be read or updated (deleted, or owned by a different account), tell the user rather than silently creating a replacement. If this session has no Artifact tool, skip the artifact without fuss — run plain `dashboard` if they want to see something, and the next session that has the tool will bring the artifact up to date.

The artifact is private until the user shares it. It contains the changelog and goals, so sharing is their decision — don't change visibility or suggest it is public.

`dashboard` without `--artifact` writes the same page as a standalone `dashboard.html` for opening locally. `dashboard --all` covers every tracked project on this machine in one page (written under `~/.claude/project-tracker/` unless `--out` is given; in a cloud session pass `--out` inside the project so the user can open it). An all-projects page can be published as its own artifact on request, but its link isn't stored anywhere — ask the user for it when updating.

## Answering questions

- "How much time / usage on this project?" → `report`, then answer in a sentence or two with the relevant figures; show the table only if they want the breakdown.
- "What did I do yesterday / last week?" → read `CHANGELOG.md` (write up any drafts first); pair with `report --days 7` if they want hours.
- "Show me the tracker / dashboard" → refresh the project's artifact and give the link.
- "How are all my projects doing?" → `projects`, or `dashboard --all` for the visual version. The registry is per machine (and empty in a fresh cloud container), so only projects opened on this machine are listed — say so if the list looks short.
- "What's left / what's next?" → `GOALS.md`, plus Open threads from the latest changelog entries.
- Time looks too low or high → explain the idle threshold and offer `init --idle-minutes <n>`. It applies to sessions whose transcripts are still on disk; older stored sessions keep the blocks computed at the time.
