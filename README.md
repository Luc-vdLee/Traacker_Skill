# Traacker_Skill

A Claude skill that keeps track of your projects. For each project it maintains, in `<project>/.project-tracker/`:

- **`SUMMARY.md`** — Claude usage (sessions, prompts, tokens per model) and time spent working, in total and per day
- **`CHANGELOG.md`** — a daily build/change log; each day's first session writes up the previous day
- **`GOALS.md`** — goals and next steps, ticked off as the daily log records them done
- **`dashboard.html`** — charts of time and usage per day, on request
- `sessions/` / `config.json` — the underlying records and settings

## Install

Copy the `project-tracker/` folder to one of:

- `~/.claude/skills/project-tracker/` — available in all your projects
- `<project>/.claude/skills/project-tracker/` — travels with that repository (needed for cloud sessions)

Requires Python 3.9+; no other dependencies.

## Use

In a project, tell Claude: **"start tracking this project"**. Claude copies the skill into the repo (so it also works in cloud sessions), installs two session hooks and commits the setup. After that it runs itself: tracking data is committed automatically (only files under `.project-tracker/`, never pushed by the hook). Ask things like:

- "How much time and Claude usage has this project used?"
- "What did I do yesterday?"
- "Log today's work"
- "Show me the dashboard" / "Show all my tracked projects"
- "Add a goal: users can reset their password"

Or run the script directly:

```bash
python3 project-tracker/scripts/tracker.py --help
```

## How it works

Usage and time are read from Claude Code's own session transcripts, so nothing has to be logged by hand. Time counts stretches of activity; gaps longer than 15 minutes (configurable) are treated as breaks. Results are stored as one small file per session in `.project-tracker/sessions/`, so history survives after Claude Code cleans up old transcripts and merges cleanly when you work from several machines. See `project-tracker/SKILL.md` for details.
