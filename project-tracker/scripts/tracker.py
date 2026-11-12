#!/usr/bin/env python3
"""Project tracker: Claude usage, time spent and a daily changelog per project.

Reads Claude Code session transcripts (~/.claude/projects/...) and git history,
and keeps the results in <project>/.project-tracker/. Standard library only.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TRACK_DIR = ".project-tracker"
DEFAULT_IDLE_MINUTES = 15
BACKFILL_DAYS = 14
TOKEN_KEYS = ("input", "output", "cache_write", "cache_read")
AUTO_MARK = "<!-- auto-generated draft -->"
HEADING_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})\b.*$", re.M)


# ---------------------------------------------------------------- basics

def die(msg: str) -> "None":
    print(f"project-tracker: {msg}", file=sys.stderr)
    sys.exit(1)


def git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                           text=True, timeout=30)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def find_root(start: Path, must_exist: bool = True) -> Path:
    start = start.resolve()
    for p in (start, *start.parents):
        if (p / TRACK_DIR / "config.json").is_file():
            return p
    if must_exist:
        die(f"no tracked project found at or above {start}. Run `init` first.")
    top = git(start, "rev-parse", "--show-toplevel").strip()
    return Path(top) if top else start


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def get_tz(cfg: dict):
    name = cfg.get("timezone")
    if name:
        try:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
        except Exception:
            print(f"project-tracker: unknown timezone {name!r}, using system local",
                  file=sys.stderr)
    return None  # system local


def local(ts: float, tz) -> dt.datetime:
    return dt.datetime.fromtimestamp(ts, tz) if tz else dt.datetime.fromtimestamp(ts).astimezone()


def today(tz) -> dt.date:
    return local(dt.datetime.now().timestamp(), tz).date()


def day_bounds(day: dt.date, tz) -> tuple[float, float]:
    def start(d):
        naive = dt.datetime(d.year, d.month, d.day)
        return (naive.replace(tzinfo=tz) if tz else naive.astimezone()).timestamp()
    return start(day), start(day + dt.timedelta(days=1))


def fmt_dur(seconds: float) -> str:
    m = int(round(seconds / 60))
    return f"{m // 60}h {m % 60:02d}m" if m >= 60 else f"{m}m"


def fmt_n(n: float) -> str:
    for unit, div in (("M", 1e6), ("k", 1e3)):
        if n >= div:
            return f"{n / div:.1f}{unit}"
    return str(int(n))


# ---------------------------------------------------------------- transcripts

def transcript_files(root: Path) -> list[Path]:
    base = claude_home() / "projects"
    enc = re.sub(r"[^A-Za-z0-9]", "-", str(root))
    files: list[Path] = []
    if base.is_dir():
        for d in base.iterdir():
            if d.is_dir() and (d.name == enc or d.name.startswith(enc + "-")):
                files.extend(d.rglob("*.jsonl"))
    return sorted(files)


def parse_ts(s) -> float | None:
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def prompt_text(entry: dict) -> str | None:
    """Text of a prompt the human typed, or None for tool results/system noise."""
    if entry.get("isMeta") or entry.get("isSidechain"):
        return None
    content = (entry.get("message") or {}).get("content")
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        content = " ".join(b.get("text", "") for b in content
                           if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str):
        return None
    content = content.strip()
    if not content or content.startswith("<") or content.startswith("[Request interrupted"):
        return None
    return content


def scan(root: Path, cfg: dict) -> tuple[dict, list[dict]]:
    """Return ({session_id: record}, [prompt dicts]) from transcripts on disk."""
    tz = get_tz(cfg)
    idle = float(cfg.get("idle_minutes", DEFAULT_IDLE_MINUTES)) * 60
    stamps: dict[str, set] = {}
    msgs: dict[str, dict] = {}       # assistant message id -> usage record
    prompts: dict[str, dict] = {}    # uuid -> prompt
    root_s = str(root)
    for f in transcript_files(root):
        try:
            fh = open(f, errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                kind = e.get("type")
                if kind not in ("user", "assistant"):
                    continue
                cwd = e.get("cwd")
                if cwd and not (cwd == root_s or cwd.startswith(root_s + os.sep)):
                    continue
                ts = parse_ts(e.get("timestamp"))
                sid = e.get("sessionId") or f.stem
                if ts is None:
                    continue
                stamps.setdefault(sid, set()).add(ts)
                msg = e.get("message") or {}
                if kind == "assistant":
                    u = msg.get("usage") or {}
                    model = msg.get("model") or "unknown"
                    if not u or model == "<synthetic>":
                        continue
                    mid = msg.get("id") or e.get("uuid")
                    rec = {"sid": sid, "ts": ts, "model": model,
                           "input": u.get("input_tokens") or 0,
                           "output": u.get("output_tokens") or 0,
                           "cache_write": u.get("cache_creation_input_tokens") or 0,
                           "cache_read": u.get("cache_read_input_tokens") or 0}
                    old = msgs.get(mid)
                    # streamed blocks repeat the same message id; keep the fullest
                    if old is None or rec["output"] >= old["output"]:
                        if old:
                            rec["sid"], rec["ts"] = old["sid"], old["ts"]
                        msgs[mid] = rec
                else:
                    text = prompt_text(e)
                    if text:
                        prompts[e.get("uuid") or f"{sid}{ts}"] = {
                            "sid": sid, "ts": ts, "text": text,
                            "branch": e.get("gitBranch")}

    sessions: dict[str, dict] = {}
    for sid, ts_set in stamps.items():
        ordered = sorted(ts_set)
        intervals, start, prev = [], ordered[0], ordered[0]
        for t in ordered[1:]:
            if t - prev > idle:
                intervals.append([int(start), int(prev)])
                start = t
            prev = t
        intervals.append([int(start), int(prev)])
        sessions[sid] = {"first": int(ordered[0]), "last": int(ordered[-1]),
                         "intervals": intervals, "usage": {}, "prompts": {}}
    for m in msgs.values():
        day = local(m["ts"], tz).date().isoformat()
        slot = sessions[m["sid"]]["usage"].setdefault(day, {}).setdefault(
            m["model"], {k: 0 for k in (*TOKEN_KEYS, "messages")})
        for k in TOKEN_KEYS:
            slot[k] += m[k]
        slot["messages"] += 1
    plist = sorted(prompts.values(), key=lambda p: p["ts"])
    for p in plist:
        day = local(p["ts"], tz).date().isoformat()
        d = sessions[p["sid"]]["prompts"]
        d[day] = d.get(day, 0) + 1
    return sessions, plist


def weight(rec: dict) -> int:
    return sum(m["messages"] for d in rec.get("usage", {}).values() for m in d.values())


def sync(root: Path, cfg: dict) -> tuple[dict, list[dict]]:
    """Merge transcripts into data.json. Sessions whose transcripts are gone
    (cleanup, another machine, ephemeral cloud container) are kept as stored."""
    path = root / TRACK_DIR / "data.json"
    data = read_json(path, {"version": 1, "sessions": {}})
    fresh, prompts = scan(root, cfg)
    changed = False
    for sid, rec in fresh.items():
        old = data["sessions"].get(sid)
        if old != rec and (old is None or weight(rec) >= weight(old)):
            data["sessions"][sid] = rec
            changed = True
    if changed or not path.exists():
        write_json(path, data)
    write_summary(root, cfg, data)
    return data, prompts


# ---------------------------------------------------------------- aggregation

def merged_intervals(data: dict) -> list[list[int]]:
    out: list[list[int]] = []
    for a, b in sorted(iv for s in data["sessions"].values() for iv in s["intervals"]):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def time_by_day(data: dict, tz) -> dict[str, float]:
    """Wall-clock active seconds per local day; parallel sessions count once."""
    days: dict[str, float] = {}
    for a, b in merged_intervals(data):
        while a < b:
            d = local(a, tz).date()
            end = min(b, day_bounds(d, tz)[1])
            days[d.isoformat()] = days.get(d.isoformat(), 0) + (end - a)
            a = end
    return days


def cost_of(model: str, tok: dict, pricing: dict) -> float | None:
    """pricing: {model-substring: {input, output, cache_write, cache_read}} in $/MTok."""
    best = max((k for k in pricing if k in model), key=len, default=None)
    if best is None:
        return None
    rates = pricing[best]
    return sum(tok[k] * float(rates.get(k, 0)) for k in TOKEN_KEYS) / 1e6


def aggregate(data: dict, cfg: dict) -> dict:
    tz = get_tz(cfg)
    pricing = cfg.get("pricing") or {}
    days: dict[str, dict] = {}
    models: dict[str, dict] = {}

    def day(d):
        return days.setdefault(d, {"seconds": 0, "sessions": 0, "prompts": 0, "messages": 0,
                                   "cost": 0.0, **{k: 0 for k in TOKEN_KEYS}})
    for d, secs in time_by_day(data, tz).items():
        day(d)["seconds"] = secs
    priced = bool(pricing)
    for s in data["sessions"].values():
        for d in set(s["usage"]) | set(s["prompts"]):
            day(d)["sessions"] += 1
        for d, n in s["prompts"].items():
            day(d)["prompts"] += n
        for d, by_model in s["usage"].items():
            for model, tok in by_model.items():
                m = models.setdefault(model, {"messages": 0, "cost": 0.0,
                                              **{k: 0 for k in TOKEN_KEYS}})
                c = cost_of(model, tok, pricing)
                if c is None:
                    priced = False
                for tgt in (day(d), m):
                    for k in (*TOKEN_KEYS, "messages"):
                        tgt[k] += tok[k]
                    tgt["cost"] += c or 0
    total = {"seconds": 0, "prompts": 0, "messages": 0, "cost": 0.0,
             **{k: 0 for k in TOKEN_KEYS}}
    for v in days.values():
        for k in total:
            total[k] += v[k]
    total["sessions"] = len(data["sessions"])
    return {"days": dict(sorted(days.items())), "models": models, "total": total,
            "priced": priced}


def tokens_total(v: dict) -> int:
    return sum(v[k] for k in TOKEN_KEYS)


def stats_line(v: dict, priced: bool = False) -> str:
    s = (f"**Time:** {fmt_dur(v['seconds'])} · **Claude:** {v['sessions']} session(s), "
         f"{v['prompts']} prompt(s), {v['messages']} responses, "
         f"{fmt_n(tokens_total(v))} tokens ({fmt_n(v['output'])} output)")
    if priced and v.get("cost"):
        s += f", ~${v['cost']:.2f}"
    return s


def render_report(cfg: dict, agg: dict, days: int) -> str:
    t, priced = agg["total"], agg["priced"]
    cost_h, cost_s = (" Est. cost |", "---:|") if priced else ("", "")
    out = [f"# {cfg.get('name', 'Project')} — tracker summary", "",
           f"_Updated {dt.datetime.now().astimezone():%Y-%m-%d %H:%M %Z}. "
           f"Idle gaps over {cfg.get('idle_minutes', DEFAULT_IDLE_MINUTES)} min are not counted as work time._",
           "", "## Totals", "",
           f"- **Time spent:** {fmt_dur(t['seconds'])} across {len(agg['days'])} active day(s)",
           f"- **Claude sessions:** {t['sessions']} · **prompts:** {t['prompts']} · "
           f"**responses:** {t['messages']}",
           f"- **Tokens:** {fmt_n(tokens_total(t))} total — input {fmt_n(t['input'])}, "
           f"output {fmt_n(t['output'])}, cache write {fmt_n(t['cache_write'])}, "
           f"cache read {fmt_n(t['cache_read'])}"]
    if priced:
        out.append(f"- **Estimated cost:** ${t['cost']:.2f} (from rates in config.json)")
    out += ["", "## By model", "",
            f"| Model | Responses | Input | Output | Cache write | Cache read |{cost_h}",
            f"|---|---:|---:|---:|---:|---:|{cost_s}"]
    for name, m in sorted(agg["models"].items(), key=lambda kv: -tokens_total(kv[1])):
        c = f" ${m['cost']:.2f} |" if priced else ""
        out.append(f"| {name} | {m['messages']} | {fmt_n(m['input'])} | {fmt_n(m['output'])} | "
                   f"{fmt_n(m['cache_write'])} | {fmt_n(m['cache_read'])} |{c}")
    shown = list(agg["days"].items())[-days:]
    out += ["", f"## Daily (last {len(shown)} active day(s))", "",
            f"| Date | Time | Sessions | Prompts | Responses | Tokens | Output |{cost_h}",
            f"|---|---:|---:|---:|---:|---:|---:|{cost_s}"]
    for d, v in reversed(shown):
        c = f" ${v['cost']:.2f} |" if priced else ""
        out.append(f"| {d} | {fmt_dur(v['seconds'])} | {v['sessions']} | {v['prompts']} | "
                   f"{v['messages']} | {fmt_n(tokens_total(v))} | {fmt_n(v['output'])} |{c}")
    return "\n".join(out) + "\n"


def write_summary(root: Path, cfg: dict, data: dict) -> None:
    text = render_report(cfg, aggregate(data, cfg), 30)
    path = root / TRACK_DIR / "SUMMARY.md"
    old = path.read_text() if path.exists() else ""
    strip = lambda s: re.sub(r"_Updated [^_]*_", "", s)  # noqa: E731
    if strip(old) != strip(text):  # avoid timestamp-only churn in git
        path.write_text(text)


# ---------------------------------------------------------------- changelog

def commits_on(root: Path, day: dt.date, tz) -> list[dict]:
    a, b = day_bounds(day, tz)
    raw = git(root, "log", "--all", "--no-merges", f"--since={int(a)}", f"--until={int(b) - 1}",
              "--date=unix", "--pretty=format:\x1e%h\x1f%ad\x1f%an\x1f%s\x1f%b\x1f", "--numstat")
    out = []
    for chunk in raw.split("\x1e")[1:]:
        parts = chunk.split("\x1f")
        if len(parts) < 6:
            continue
        files, add, rem = [], 0, 0
        for line in parts[5].strip().splitlines():
            cols = line.split("\t")
            if len(cols) == 3:
                files.append(cols[2])
                add += int(cols[0]) if cols[0].isdigit() else 0
                rem += int(cols[1]) if cols[1].isdigit() else 0
        out.append({"hash": parts[0], "ts": int(parts[1]), "author": parts[2],
                    "subject": parts[3], "body": parts[4].strip(), "files": files,
                    "added": add, "removed": rem})
    return sorted(out, key=lambda c: c["ts"])


def changelog_path(root: Path) -> Path:
    return root / TRACK_DIR / "CHANGELOG.md"


def read_entries(root: Path) -> dict[str, str]:
    path = changelog_path(root)
    text = path.read_text() if path.exists() else ""
    heads = list(HEADING_RE.finditer(text))
    return {m.group(1): text[m.start():(heads[i + 1].start() if i + 1 < len(heads) else len(text))].strip()
            for i, m in enumerate(heads)}


def write_entries(root: Path, cfg: dict, entries: dict[str, str]) -> None:
    head = (f"# {cfg.get('name', 'Project')} — daily build/change log\n\n"
            "One entry per day the project was worked on, newest first. "
            "Maintained by the project-tracker skill.\n")
    body = "\n\n".join(entries[d] for d in sorted(entries, reverse=True))
    changelog_path(root).write_text(head + ("\n" + body + "\n" if body else ""))


def empty_day() -> dict:
    return {"seconds": 0, "sessions": 0, "prompts": 0, "messages": 0, "cost": 0.0,
            **{k: 0 for k in TOKEN_KEYS}}


def entry_text(day: dt.date, agg: dict, body: str, auto: bool) -> str:
    v = agg["days"].get(day.isoformat()) or empty_day()
    lines = [f"## {day.isoformat()} ({day:%A})", ""]
    if auto:
        lines += [AUTO_MARK, ""]
    lines += [stats_line(v, agg["priced"]), "", body.strip()]
    return "\n".join(lines).strip()


def auto_body(commits: list[dict]) -> str:
    if not commits:
        return "### Changes\n\n- No commits recorded; work this day was uncommitted or exploratory."
    lines = ["### Changes", ""]
    for c in commits:
        lines.append(f"- `{c['hash']}` {c['subject']} "
                     f"(+{c['added']}/−{c['removed']}, {len(c['files'])} file(s))")
    return "\n".join(lines)


def active_days(root: Path, agg: dict, tz, since: dt.date, until: dt.date) -> list[dt.date]:
    out, d = [], since
    while d <= until:
        if d.isoformat() in agg["days"] or commits_on(root, d, tz):
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def fill_missing(root: Path, cfg: dict, data: dict) -> tuple[list[str], list[str]]:
    """Write draft entries for recent active days (up to yesterday) lacking one.
    Returns (newly drafted days, all days still holding an unrefined draft)."""
    tz = get_tz(cfg)
    agg = aggregate(data, cfg)
    entries = read_entries(root)
    yesterday = today(tz) - dt.timedelta(days=1)
    created = []
    for d in active_days(root, agg, tz, yesterday - dt.timedelta(days=BACKFILL_DAYS - 1), yesterday):
        if d.isoformat() not in entries:
            entries[d.isoformat()] = entry_text(d, agg, auto_body(commits_on(root, d, tz)), True)
            created.append(d.isoformat())
    if created or not changelog_path(root).exists():
        write_entries(root, cfg, entries)
    drafts = sorted(d for d, t in entries.items() if AUTO_MARK in t)
    return created, drafts


def parse_day(s: str | None, tz) -> dt.date:
    if not s or s == "yesterday":
        return today(tz) - dt.timedelta(days=1)
    if s == "today":
        return today(tz)
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        die(f"bad date {s!r}; use YYYY-MM-DD, 'today' or 'yesterday'")


# ---------------------------------------------------------------- hooks/registry

def registry_path() -> Path:
    return claude_home() / "project-tracker" / "registry.json"


def register(root: Path, cfg: dict) -> None:
    try:
        reg = read_json(registry_path(), {})
        if reg.get(str(root)) != cfg.get("name"):
            reg[str(root)] = cfg.get("name")
            write_json(registry_path(), reg)
    except OSError:
        pass


def install_hooks(root: Path) -> Path:
    script = Path(__file__).resolve()
    try:
        rel = script.relative_to(root)
        cmd, target = f'python3 "$CLAUDE_PROJECT_DIR/{rel.as_posix()}"', "settings.json"
    except ValueError:  # skill installed outside the project: machine-specific path
        cmd, target = f'python3 "{script}"', "settings.local.json"
    path = root / ".claude" / target
    settings = read_json(path, {})
    hooks = settings.setdefault("hooks", {})
    for event, arg in (("SessionStart", "session-start"), ("SessionEnd", "session-end")):
        groups = [g for g in hooks.get(event, [])
                  if not any("tracker.py" in h.get("command", "") and " hook " in h.get("command", "")
                             for h in g.get("hooks", []))]
        groups.append({"hooks": [{"type": "command", "command": f"{cmd} hook {arg}",
                                  "timeout": 30}]})
        hooks[event] = groups
    write_json(path, settings)
    return path


# ---------------------------------------------------------------- commands

def load(args) -> tuple[Path, dict]:
    root = find_root(Path(args.project or os.getcwd()))
    return root, read_json(root / TRACK_DIR / "config.json", {})


def cmd_init(args) -> None:
    root = find_root(Path(args.project or os.getcwd()), must_exist=False)
    cfg_path = root / TRACK_DIR / "config.json"
    cfg = read_json(cfg_path, {})
    cfg.setdefault("name", root.name)
    cfg.setdefault("created", dt.date.today().isoformat())
    cfg.setdefault("idle_minutes", DEFAULT_IDLE_MINUTES)
    cfg.setdefault("timezone", None)
    cfg.setdefault("pricing", {})
    for key in ("name", "idle_minutes", "timezone"):
        if getattr(args, key) is not None:
            cfg[key] = getattr(args, key)
    write_json(cfg_path, cfg)
    data, _ = sync(root, cfg)
    fill_missing(root, cfg, data)
    register(root, cfg)
    print(f"Tracking '{cfg['name']}' at {root / TRACK_DIR}")
    if not args.no_hooks:
        print(f"Hooks installed in {install_hooks(root)}")
    print(f"Sessions found so far: {len(data['sessions'])}")


def cmd_sync(args) -> None:
    root, cfg = load(args)
    data, _ = sync(root, cfg)
    created, drafts = fill_missing(root, cfg, data)
    register(root, cfg)
    print(f"Synced {len(data['sessions'])} session(s) -> {root / TRACK_DIR / 'SUMMARY.md'}")
    if created:
        print("Drafted changelog entries: " + ", ".join(created))
    if drafts:
        print("Unrefined draft entries: " + ", ".join(drafts))


def cmd_report(args) -> None:
    root, cfg = load(args)
    data, _ = sync(root, cfg)
    agg = aggregate(data, cfg)
    print(json.dumps(agg, indent=1) if args.json else render_report(cfg, agg, args.days))


def cmd_digest(args) -> None:
    """Raw material for writing one day's changelog entry."""
    root, cfg = load(args)
    tz = get_tz(cfg)
    day = parse_day(args.date, tz)
    data, prompts = sync(root, cfg)
    agg = aggregate(data, cfg)
    a, b = day_bounds(day, tz)
    out = [f"# Digest for {day.isoformat()} ({day:%A}) — {cfg.get('name')}", "",
           stats_line(agg["days"].get(day.isoformat()) or empty_day(), agg["priced"]), "",
           "## Commits"]
    commits = commits_on(root, day, tz)
    for c in commits:
        out.append(f"- {c['hash']} {local(c['ts'], tz):%H:%M} {c['subject']} "
                   f"(+{c['added']}/-{c['removed']}) [{c['author']}]")
        if c["body"]:
            out += [f"    {ln}" for ln in c["body"].splitlines()[:6]]
        out += [f"    · {f}" for f in c["files"][:15]]
        if len(c["files"]) > 15:
            out.append(f"    · … {len(c['files']) - 15} more file(s)")
    if not commits:
        out.append("- (none)")
    if day == today(tz):
        status = git(root, "status", "--short").rstrip()
        if status:
            out += ["", "## Uncommitted changes", "```", status, "```"]
    out += ["", "## What was asked of Claude (prompts, in order)"]
    todays = [p for p in prompts if a <= p["ts"] < b]
    for p in todays:
        text = " ".join(p["text"].split())
        out.append(f"- {local(p['ts'], tz):%H:%M} {text[:args.max_chars]}"
                   + ("…" if len(text) > args.max_chars else ""))
    if not todays:
        out.append("- (no transcripts available for this day on this machine)")
    existing = read_entries(root).get(day.isoformat())
    if existing:
        out += ["", "## Existing entry" + (" (auto draft)" if AUTO_MARK in existing else ""),
                existing]
    print("\n".join(out))


def cmd_changelog_write(args) -> None:
    root, cfg = load(args)
    tz = get_tz(cfg)
    day = parse_day(args.date, tz)
    body = Path(args.file).read_text() if args.file else sys.stdin.read()
    # the heading and stats line are generated; drop any the author included
    body = HEADING_RE.sub("", body).replace(AUTO_MARK, "")
    body = "\n".join(ln for ln in body.splitlines() if not ln.startswith("**Time:**")).strip()
    if not body:
        die("empty changelog body")
    data, _ = sync(root, cfg)
    entries = read_entries(root)
    entries[day.isoformat()] = entry_text(day, aggregate(data, cfg), body, False)
    write_entries(root, cfg, entries)
    print(f"Wrote entry for {day.isoformat()} -> {changelog_path(root)}")


def cmd_install_hooks(args) -> None:
    root, _ = load(args)
    print(f"Hooks installed in {install_hooks(root)}")


def cmd_projects(args) -> None:
    reg = read_json(registry_path(), {})
    rows = []
    for root_s, name in sorted(reg.items(), key=lambda kv: str(kv[1])):
        root = Path(root_s)
        cfg = read_json(root / TRACK_DIR / "config.json", None)
        if cfg is None:
            continue
        t = aggregate(sync(root, cfg)[0], cfg)
        last = max(t["days"], default="-")
        rows.append(f"| {cfg.get('name', name)} | {fmt_dur(t['total']['seconds'])} | "
                    f"{t['total']['sessions']} | {fmt_n(tokens_total(t['total']))} | {last} | {root} |")
    if not rows:
        print("No tracked projects registered on this machine.")
        return
    print("| Project | Time | Sessions | Tokens | Last active | Path |\n|---|---:|---:|---:|---|---|")
    print("\n".join(rows))


def cmd_hook(args) -> None:
    """Never block or fail a session: all errors are swallowed."""
    try:
        try:
            payload = json.loads(sys.stdin.read() or "{}") if not sys.stdin.isatty() else {}
        except ValueError:
            payload = {}
        start = Path(os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd())
        root = None
        for p in (start.resolve(), *start.resolve().parents):
            if (p / TRACK_DIR / "config.json").is_file():
                root = p
                break
        if root is None:
            return
        cfg = read_json(root / TRACK_DIR / "config.json", {})
        data, _ = sync(root, cfg)
        if args.event != "session-start":
            return
        _, drafts = fill_missing(root, cfg, data)
        register(root, cfg)
        if drafts:
            me = Path(__file__).resolve()
            print(f"[project-tracker] The daily changelog ({TRACK_DIR}/CHANGELOG.md) has "
                  f"auto-generated draft entr{'y' if len(drafts) == 1 else 'ies'} for "
                  f"{', '.join(drafts[-3:])}. Early in this session, replace each draft with a "
                  f"proper written entry: run `python3 \"{me}\" digest --date <day>` for the raw "
                  f"material, then pipe the entry body to `python3 \"{me}\" changelog-write "
                  f"--date <day>`. See the project-tracker skill for the entry format. Do this "
                  f"briefly and without derailing the user's request.")
    except Exception as exc:  # noqa: BLE001
        print(f"project-tracker hook: {exc}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--project", help="project directory (default: current directory)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="start tracking a project (safe to re-run)")
    p.add_argument("--name")
    p.add_argument("--idle-minutes", type=float, dest="idle_minutes")
    p.add_argument("--timezone", help="IANA name, e.g. Europe/Amsterdam (default: system)")
    p.add_argument("--no-hooks", action="store_true")
    p.set_defaults(fn=cmd_init)

    sub.add_parser("sync", help="update data, SUMMARY.md and draft changelog entries") \
        .set_defaults(fn=cmd_sync)

    p = sub.add_parser("report", help="print usage and time report")
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_report)

    p = sub.add_parser("digest", help="raw material for one day's changelog entry")
    p.add_argument("--date", help="YYYY-MM-DD | today | yesterday (default)")
    p.add_argument("--max-chars", type=int, default=400)
    p.set_defaults(fn=cmd_digest)

    p = sub.add_parser("changelog-write", help="write/replace a day's entry (body on stdin)")
    p.add_argument("--date", help="YYYY-MM-DD | today | yesterday (default)")
    p.add_argument("--file")
    p.set_defaults(fn=cmd_changelog_write)

    sub.add_parser("install-hooks", help="(re)install the session hooks") \
        .set_defaults(fn=cmd_install_hooks)
    sub.add_parser("projects", help="overview of all tracked projects on this machine") \
        .set_defaults(fn=cmd_projects)

    p = sub.add_parser("hook", help="entry point for Claude Code hooks")
    p.add_argument("event", choices=["session-start", "session-end"])
    p.set_defaults(fn=cmd_hook)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
