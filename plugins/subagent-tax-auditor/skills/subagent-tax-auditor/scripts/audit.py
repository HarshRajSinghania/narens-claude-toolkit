#!/usr/bin/env python3
"""audit: attribute Claude Code token usage to the main thread and to each subagent type.

    python audit.py report   [--project PATH | --all] [--since D] [--until D] [--projects-dir DIR]
                             [--rates FILE] [--json] [--show-descriptions]
    python audit.py snapshot --out FILE [same selectors]
    python audit.py compare  --snapshot FILE [same selectors]

Read-only (snapshot writes only its --out file). Standard library only. Prompts, responses and
file contents are never printed.
"""
import argparse
import json
import os
import re
import statistics
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

KINDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
MIN_SPAWNS = 5
STALE_DAYS = 90
SYNTHETIC = "<synthetic>"


class AuditError(Exception):
    """A problem the user can fix; reported as `error: ...` with exit 2."""


# --- locating transcripts ------------------------------------------------------------------

def projects_dir(arg=None):
    if arg:
        return Path(arg)
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "projects"


def slug_for(path):
    """Claude Code names a project folder after its path with every non-alphanumeric character as -."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(str(path)))


def project_dirs(root, project=None, everything=False):
    root = Path(root)
    if not root.is_dir():
        raise AuditError(f"transcripts directory not found: {root}")
    if everything:
        return sorted(p for p in root.iterdir() if p.is_dir())
    target = root / slug_for(project or os.getcwd())
    return [target] if target.is_dir() else []


# --- reading transcripts -------------------------------------------------------------------

def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def usage_counts(usage):
    breakdown = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    write_5m = _count(breakdown.get("ephemeral_5m_input_tokens"))
    write_1h = _count(breakdown.get("ephemeral_1h_input_tokens"))
    total = _count(usage.get("cache_creation_input_tokens"))
    if write_5m + write_1h < total:
        write_5m += total - (write_5m + write_1h)
    return {
        "input": _count(usage.get("input_tokens")),
        "output": _count(usage.get("output_tokens")),
        "cache_read": _count(usage.get("cache_read_input_tokens")),
        "cache_write_5m": write_5m,
        "cache_write_1h": write_1h,
    }


def new_quality():
    return {"malformed_lines": 0, "lines_without_usage": 0, "unreadable_files": 0, "subagents_without_meta": 0}


def read_messages(path, quality):
    """(first timestamp, messages) for one transcript file.

    A message id can span several lines (one per content block, usage still growing), so each id
    is counted once, with the largest value seen for every token kind.
    """
    by_id, order, start, anonymous = {}, [], None, 0
    try:
        handle = open(path, "rb")
    except OSError:
        quality["unreadable_files"] += 1
        return None, []
    with handle:
        for raw in handle:
            if not raw.strip():
                continue
            try:
                record = json.loads(raw.decode("utf-8-sig"))
            except ValueError:
                quality["malformed_lines"] += 1
                continue
            if not isinstance(record, dict):
                quality["malformed_lines"] += 1
                continue
            stamp = record.get("timestamp")
            if isinstance(stamp, str) and (start is None or stamp < start):
                start = stamp
            message = record.get("message")
            if record.get("type") != "assistant" or not isinstance(message, dict):
                continue
            model = message.get("model")
            if model == SYNTHETIC:
                continue
            if not isinstance(message.get("usage"), dict):
                quality["lines_without_usage"] += 1
                continue
            mid = message.get("id")
            if not isinstance(mid, str) or not mid:
                anonymous += 1
                mid = f"line-{anonymous}"
            tokens = usage_counts(message["usage"])
            if mid in by_id:
                seen = by_id[mid]["tokens"]
                for kind in KINDS:
                    seen[kind] = max(seen[kind], tokens[kind])
            else:
                by_id[mid] = {"model": model if isinstance(model, str) and model else "unknown", "tokens": tokens}
                order.append(mid)
    return start, [by_id[i] for i in order]


def read_meta(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _unit(kind, path, description, since, until, quality):
    start, messages = read_messages(path, quality)
    if not messages or start is None:
        return None
    day = start[:10]
    if (since and day < since) or (until and day > until):
        return None
    return {"type": kind, "start": start, "messages": messages, "description": description}


def load_units(dirs, since, until, quality):
    """Every main session and every subagent run, as units attributed to a type."""
    units = []
    for pdir in dirs:
        for session in sorted(pdir.glob("*.jsonl")):
            unit = _unit("main", session, "", since, until, quality)
            if unit:
                units.append(unit)
        for subdir in sorted(p / "subagents" for p in pdir.iterdir() if (p / "subagents").is_dir()):
            for agent in sorted(subdir.glob("agent-*.jsonl")):
                meta = read_meta(agent.with_suffix(".meta.json"))
                kind = meta.get("agentType") if meta else None
                if not isinstance(kind, str) or not kind:
                    kind = "unknown"
                    quality["subagents_without_meta"] += 1
                description = meta.get("description", "") if meta else ""
                unit = _unit(kind, agent, description if isinstance(description, str) else "", since, until, quality)
                if unit:
                    units.append(unit)
    return units


# --- rates and cost ------------------------------------------------------------------------

def load_rates(path=None):
    path = Path(path) if path else Path(__file__).resolve().parent.parent / "rates.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise AuditError(f"cannot read the rates file {path} ({exc.strerror or exc})") from None
    except ValueError as exc:
        raise AuditError(f"{path} is not valid JSON ({exc})") from None
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, dict) or not isinstance(data.get("as_of"), str):
        raise AuditError(f'{path} needs "as_of" and "models"')
    for name, rate in models.items():
        if not isinstance(rate, dict) or any(
            not isinstance(rate.get(k), (int, float)) or isinstance(rate.get(k), bool) or rate[k] < 0 for k in KINDS
        ):
            raise AuditError(f"{path}: model {name!r} needs a non-negative number for each of {', '.join(KINDS)}")
    return data


def rate_for(rates, model):
    models = rates["models"]
    if model in models:
        return models[model]
    prefixes = [name for name in models if model.startswith(name)]
    return models[max(prefixes, key=len)] if prefixes else None


def cost_of(tokens, rate):
    return sum(tokens[kind] * rate[kind] for kind in KINDS) / 1_000_000


def rates_stale(rates, today=None):
    try:
        as_of = date.fromisoformat(rates["as_of"])
    except ValueError:
        return True
    return ((today or date.today()) - as_of).days > STALE_DAYS


# --- one unit's numbers --------------------------------------------------------------------

def summarize(unit, rates):
    models, per_model = Counter(), {}
    for message in unit["messages"]:
        models[message["model"]] += 1
        slot = per_model.setdefault(message["model"], dict.fromkeys(KINDS, 0))
        for kind in KINDS:
            slot[kind] += message["tokens"][kind]
    total, cost, priced = dict.fromkeys(KINDS, 0), 0.0, True
    for model, tokens in per_model.items():
        for kind in KINDS:
            total[kind] += tokens[kind]
        rate = rate_for(rates, model)
        if rate is None:
            priced = False
        else:
            cost += cost_of(tokens, rate)
    first = unit["messages"][0]
    return {
        "type": unit["type"],
        "start": unit["start"],
        "models": models,
        "per_model": per_model,
        "first_model": first["model"],
        "tokens": total,
        "cost": cost if priced else None,
        "fixed": first["tokens"]["cache_read"] + first["tokens"]["cache_write_5m"] + first["tokens"]["cache_write_1h"],
        "messages": len(unit["messages"]),
        "description": unit["description"],
    }


if __name__ == "__main__":
    sys.exit("audit.py: the command line is added in the next task")
