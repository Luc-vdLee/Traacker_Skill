# Traacker_Skill

A Claude skill that keeps track of your projects. For each project it maintains, in `<project>/.project-tracker/`:

- **`SUMMARY.md`** — Claude usage (sessions, prompts, tokens per model) and time spent working, in total and per day
- **`CHANGELOG.md`** — a daily build/change log; each day's first session writes up the previous day
- **`GOALS.md`** — goals and next steps, ticked off as the daily log records them done
- **A Claude Artifact** — a private page on claude.ai per project showing all of the above with charts, refreshed whenever the daily log is written
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

## Try it out

1. Install as above, then open a project (a git repository) in Claude Code and say **"start tracking this project"**. Claude asks for your timezone once.
2. Work as usual for a bit, then ask **"how much time and usage so far?"** — the numbers should match your session.
3. Ask **"log today's work"** and read `.project-tracker/CHANGELOG.md`.
4. Ask **"add a goal: …"**, then **"show me the dashboard"** and open the artifact link Claude gives you.
5. Next day, start a new session: yesterday's changelog entry should be written up within the first exchange, and `git log` should show `chore(tracker): update project tracking` commits.

To stop tracking a project, delete `.project-tracker/`, `.claude/skills/project-tracker/` and the two `tracker.py` hook entries in `.claude/settings.json`.

## How it works

Usage and time are read from Claude Code's own session transcripts, so nothing has to be logged by hand. Time counts stretches of activity; gaps longer than 15 minutes (configurable) are treated as breaks. Results are stored as one small file per session in `.project-tracker/sessions/`, so history survives after Claude Code cleans up old transcripts and merges cleanly when you work from several machines. See `project-tracker/SKILL.md` for details.
