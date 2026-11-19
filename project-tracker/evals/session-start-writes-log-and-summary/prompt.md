---
tags: [skill-creator]
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Write, Edit, Bash]
---

SessionStart hook additional context: [project-tracker] The daily changelog (.project-tracker/CHANGELOG.md) has auto-generated draft entry for 2026-11-18. Early in this session, replace each draft with a proper written entry: run `python3 .claude/skills/project-tracker/scripts/tracker.py digest --date <day>` for the raw material, then pipe the entry body to `python3 .claude/skills/project-tracker/scripts/tracker.py changelog-write --date <day>`. Then refresh the project's work summary: `python3 .claude/skills/project-tracker/scripts/tracker.py summary-digest`, and pipe the new summary to `python3 .claude/skills/project-tracker/scripts/tracker.py summary-write`. See the project-tracker skill for both formats. Do this briefly and without derailing the user's request.

ok picking trailmix back up. what did I get done last time?
