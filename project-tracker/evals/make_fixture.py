#!/usr/bin/env python3
"""Build a tracked test project for the evals: a small hiking-log app with six days
of git history and Claude transcripts, relative to today.

usage: make_fixture.py <dest> <variant>
  variant: no-summary     written changelog for older days, yesterday is a draft,
                          no work summary yet
           stale-summary  every day written up, but the work summary dates from day 2
Creates <dest>/trailmix (the project) and <dest>/claude-home (CLAUDE_CONFIG_DIR).
"""
import datetime as dt, json, os, re, subprocess, sys, uuid
from pathlib import Path

dest, variant = Path(sys.argv[1]).resolve(), sys.argv[2]
proj, home = dest / "trailmix", dest / "claude-home"
TRACKER = Path(__file__).resolve().parent.parent / "scripts" / "tracker.py"
TZ = "Europe/Amsterdam"
today = dt.date.today()
D = lambda n: today - dt.timedelta(days=n)  # noqa: E731

DAYS = [  # (days ago, start hour UTC, prompts, commits[(msg, {file: content})])
 (6, 8, ["Set up a Flask app for logging hiking trails, with SQLite via SQLAlchemy",
         "Add a Trail model: name, region, distance_km, elevation_gain_m, difficulty"],
  [("Scaffold Flask app with SQLAlchemy", {"app.py": "from flask import Flask\napp = Flask(__name__)\n",
    "requirements.txt": "flask\nsqlalchemy\n"}),
   ("Add Trail model", {"models.py": "class Trail: ...\n"})]),
 (5, 13, ["Make a page listing all trails with a search box by name or region",
          "The search is case sensitive, fix that"],
  [("Trail list page with search", {"templates/trails.html": "<ul></ul>\n"}),
   ("Make trail search case-insensitive", {"app.py": "from flask import Flask\napp = Flask(__name__)\n# search\n"})]),
 (3, 9, ["Let users upload a GPX file for a trail and show an elevation profile chart",
         "Dates from some GPX files crash the parser, can you handle timezone offsets",
         "Add tests for the GPX parser"],
  [("GPX upload and elevation profile chart", {"gpx.py": "def parse(f): ...\n", "static/chart.js": "//\n"}),
   ("Fix GPX timestamp parsing with timezone offsets", {"gpx.py": "def parse(f): ...  # tz\n"}),
   ("Add GPX parser tests", {"tests/test_gpx.py": "def test_parse(): pass\n"})]),
 (1, 10, ["Add user accounts: sign up, log in, log out, with hashed passwords",
          "Only logged-in users should be able to upload GPX files",
          "Start on letting users favorite trails - just the model for now, we'll do the UI tomorrow"],
  [("User accounts with signup/login and password hashing", {"auth.py": "def login(): ...\n",
    "templates/login.html": "<form></form>\n"}),
   ("Require login for GPX upload", {"app.py": "from flask import Flask\napp = Flask(__name__)\n# search\n# login_required\n"}),
   ("WIP: Favorite model (no UI yet)", {"models.py": "class Trail: ...\nclass Favorite: ...\n"})]),
]

WRITTEN = {
 6: """### Summary
Started TrailMix, a Flask app for logging hiking trails. The skeleton runs and trails can be stored in SQLite.

### Changes
- **Added** Flask app skeleton with SQLAlchemy (`{h0}`).
- **Added** Trail model with name, region, distance, elevation gain and difficulty (`{h1}`).""",
 5: """### Summary
Trails can now be browsed and searched.

### Changes
- **Added** trail list page with search by name or region (`{h0}`).
- **Fixed** search is now case-insensitive (`{h1}`).""",
 3: """### Summary
Trails can now carry a GPX track with an elevation profile chart; the parser copes with timezone offsets and has tests.

### Changes
- **Added** GPX upload and elevation profile chart (`{h0}`).
- **Fixed** GPX timestamps with timezone offsets no longer crash the parser (`{h1}`).
- **Added** tests for the GPX parser (`{h2}`).""",
 1: """### Summary
Added user accounts and locked GPX uploads behind login. Began on favorites.

### Changes
- **Added** sign up, log in and log out with hashed passwords (`{h0}`).
- **Changed** GPX upload now requires being logged in (`{h1}`).
- **Added** Favorite model, no UI yet (`{h2}`).

### Open threads
- Favorites UI still to build.""",
}

GOALS = f"""# Goals & next steps

Checklist for this project. `- [ ]` is open, `- [x]` is done (add the date).

## Now
- [ ] Users can favorite trails and see their favorites

## Later
- [ ] Trails can be shared publicly with a link
- [ ] Deploy to a small VPS

## Done
- [x] Upload GPX tracks with an elevation chart ({D(3)})
- [x] Users can sign up and log in ({D(1)})
"""

def run(*a, **kw):
    return subprocess.run(a, check=True, capture_output=True, text=True, **kw).stdout

proj.mkdir(parents=True); home.mkdir(parents=True)
env = dict(os.environ, CLAUDE_CONFIG_DIR=str(home))
run("git", "init", "-q", "-b", "main", str(proj))
run("git", "-C", str(proj), "config", "user.email", "dev@example.com")
run("git", "-C", str(proj), "config", "user.name", "Dev")
(proj / "README.md").write_text("# TrailMix\n\nLog the hikes you've done: trails, GPX tracks, elevation.\n")
tdir = home / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(proj)); tdir.mkdir(parents=True)
hashes = {}
for ago, hour, prompts, commits in DAYS:
    day = D(ago); sid = str(uuid.uuid4()); lines = []
    t = dt.datetime(day.year, day.month, day.day, hour, 0, tzinfo=dt.timezone.utc)
    for i, p in enumerate(prompts):
        lines.append({"type": "user", "sessionId": sid, "cwd": str(proj), "uuid": str(uuid.uuid4()),
                      "timestamp": t.isoformat(), "message": {"role": "user", "content": p}})
        for k in range(4):  # four responses, 3 minutes apart
            t += dt.timedelta(minutes=3)
            lines.append({"type": "assistant", "sessionId": sid, "cwd": str(proj), "uuid": str(uuid.uuid4()),
                          "timestamp": t.isoformat(), "message": {"id": str(uuid.uuid4()),
                          "model": "claude-opus-5-5", "usage": {"input_tokens": 1200 + 100 * k,
                          "output_tokens": 800 + 50 * i, "cache_creation_input_tokens": 3000,
                          "cache_read_input_tokens": 20000}}})
        t += dt.timedelta(minutes=8)
    (tdir / f"{sid}.jsonl").write_text("\n".join(json.dumps(l) for l in lines) + "\n")
    hashes[ago] = []
    for j, (msg, files) in enumerate(commits):
        for f, c in files.items():
            (proj / f).parent.mkdir(parents=True, exist_ok=True); (proj / f).write_text(c)
        ct = dt.datetime(day.year, day.month, day.day, hour, 20 + 15 * j, tzinfo=dt.timezone.utc).isoformat()
        run("git", "-C", str(proj), "add", "-A")
        run("git", "-C", str(proj), "commit", "-q", "-m", msg,
            env=dict(env, GIT_AUTHOR_DATE=ct, GIT_COMMITTER_DATE=ct))
        hashes[ago].append(run("git", "-C", str(proj), "rev-parse", "--short", "HEAD").strip())

tr = lambda *a, stdin=None: subprocess.run(  # noqa: E731
    ["python3", str(TRACKER), "--project", str(proj), *a], input=stdin, env=env,
    check=True, capture_output=True, text=True).stdout
tr("init", "--timezone", TZ, "--no-hooks", "--no-auto-commit", "--name", "TrailMix")
written = [6, 5, 3] + ([1] if variant == "stale-summary" else [])
for ago in written:
    body = WRITTEN[ago].format(**{f"h{i}": h for i, h in enumerate(hashes[ago])})
    tr("changelog-write", "--date", D(ago).isoformat(), stdin=body)
(proj / ".project-tracker" / "GOALS.md").write_text(GOALS)
tr("sync")
if variant == "stale-summary":
    s = proj / ".project-tracker" / "SUMMARY.md"
    s.write_text(s.read_text().replace(
        "_No summary written yet. Ask Claude to \"update the project summary\"._",
        f"<!-- work-summary:start -->\n_Written {D(5)}_\n\nTrailMix is a Flask app for logging "
        "hiking trails. So far it has a Trail model in SQLite and a searchable trail list page.\n"
        "<!-- work-summary:end -->"))
run("git", "-C", str(proj), "add", "-A")
run("git", "-C", str(proj), "commit", "-q", "-m", "chore(tracker): start tracking")
print(f"project: {proj}\nCLAUDE_CONFIG_DIR: {home}")
