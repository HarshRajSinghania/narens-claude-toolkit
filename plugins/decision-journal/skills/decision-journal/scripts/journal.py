#!/usr/bin/env python3
"""Decision journal: log predictions, grade them, and show calibration.

Usage: python journal.py {add,list,grade,stats} ...   (standard library only)
Log: ~/.claude/decision-journal.jsonl (override with DECISION_JOURNAL_PATH).
"""
import argparse
import json
import math
import os
import statistics
import sys
import tempfile
from datetime import date
from pathlib import Path

DEFAULT_PATH = Path.home() / ".claude" / "decision-journal.jsonl"
REQUIRED = {"claim": ("confidence",), "estimate": ("unit", "estimate")}


class JournalError(Exception):
    """Invalid input (exit code 2)."""


class NotFound(Exception):
    """No such entry (exit code 1)."""


def log_path():
    return Path(os.environ.get("DECISION_JOURNAL_PATH") or DEFAULT_PATH)


def parse_date(text):
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        raise JournalError(f"invalid date {text!r}; use YYYY-MM-DD") from None


def today():
    raw = os.environ.get("DECISION_JOURNAL_TODAY")
    return parse_date(raw) if raw else date.today()


def _valid(entry):
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("id"), int)
        and entry.get("type") in REQUIRED
        and isinstance(entry.get("text"), str)
        and entry.get("status") in ("open", "graded")
        and all(key in entry for key in REQUIRED[entry["type"]])
    )


def load(path):
    """Read the log as slots: ("entry", dict) or ("raw", line). Malformed lines are kept."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise JournalError(f"{path} is not valid UTF-8") from None
    slots = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            obj = None
        if _valid(obj):
            slots.append(("entry", obj))
        else:
            slots.append(("raw", line))
            print(f"warning: skipping malformed line {number} in {path}", file=sys.stderr)
    return slots


def entries_of(slots):
    return [value for kind, value in slots if kind == "entry"]


def save(path, slots):
    """Atomically rewrite the log: temp file in the same directory, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(v) if kind == "entry" else v for kind, v in slots]
    data = "".join(line + "\n" for line in lines)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".journal-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _number(value, name):
    if value is None or isinstance(value, bool) or not math.isfinite(value):
        raise JournalError(f"{name} must be a finite number")
    return value


def _normalize_tags(tags):
    if tags is None:
        return []
    if isinstance(tags, str):
        tags = tags.split(",")
    out = []
    for tag in tags:
        tag = tag.strip().lower()
        if tag and tag not in out:
            out.append(tag)
    return out


def add_entry(path, *, type, text, confidence=None, unit=None, estimate=None,
              range_low=None, range_high=None, know_by=None, tags=None, project=None):
    text = (text or "").strip()
    if not text:
        raise JournalError("text must not be empty")
    entry = {"id": 0, "created": today().isoformat(), "type": type, "text": text}
    if type == "claim":
        if any(v is not None for v in (unit, estimate, range_low, range_high)):
            raise JournalError("claims take --confidence only, not --unit, --estimate or --range-*")
        if (not isinstance(confidence, int) or isinstance(confidence, bool)
                or not 50 <= confidence <= 99):
            raise JournalError(
                "confidence must be a whole number from 50 to 99 "
                "(below 50, flip the claim; 100 is not a prediction)"
            )
        entry["confidence"] = confidence
    elif type == "estimate":
        if confidence is not None:
            raise JournalError("estimates take --estimate and --unit, not --confidence")
        unit = (unit or "").strip()
        if not unit:
            raise JournalError("estimates need --unit (for example hours)")
        _number(estimate, "estimate")
        if estimate <= 0:
            raise JournalError("estimate must be greater than 0")
        if (range_low is None) != (range_high is None):
            raise JournalError("give both --range-low and --range-high, or neither")
        if range_low is not None:
            _number(range_low, "range-low")
            _number(range_high, "range-high")
            if not range_low <= estimate <= range_high:
                raise JournalError("range must satisfy range-low <= estimate <= range-high")
        entry.update(unit=unit, estimate=estimate, range_low=range_low, range_high=range_high)
    else:
        raise JournalError(f"unknown type {type!r}; use claim or estimate")
    entry["know_by"] = parse_date(know_by).isoformat() if know_by else None
    entry["tags"] = _normalize_tags(tags)
    entry["project"] = project if project is not None else Path.cwd().name
    entry["status"] = "open"
    slots = load(path)
    entry["id"] = max([e["id"] for e in entries_of(slots)], default=0) + 1
    slots.append(("entry", entry))
    save(path, slots)
    return entry


def _is_due(entry, as_of):
    if entry["status"] != "open" or not entry.get("know_by"):
        return False
    try:
        return date.fromisoformat(entry["know_by"]) <= as_of
    except ValueError:
        return False


def list_entries(path, mode=None):
    entries = entries_of(load(path))
    if mode == "open":
        return [e for e in entries if e["status"] == "open"]
    if mode == "due":
        as_of = today()
        return [e for e in entries if _is_due(e, as_of)]
    return entries


def grade_entry(path, entry_id, *, outcome=None, actual=None, note=None, force=False):
    slots = load(path)
    entry = next((v for kind, v in slots if kind == "entry" and v["id"] == entry_id), None)
    if entry is None:
        raise NotFound(f"no entry with id {entry_id}")
    if entry["status"] == "graded" and not force:
        raise JournalError(f"entry {entry_id} is already graded; use --force to overwrite")
    if entry["type"] == "claim":
        if actual is not None:
            raise JournalError("claims are graded with --outcome yes|no, not --actual")
        if outcome not in ("yes", "no"):
            raise JournalError("claims need --outcome yes|no")
    else:
        if outcome is not None:
            raise JournalError("estimates are graded with --actual NUMBER, not --outcome")
        _number(actual, "actual")
        if actual < 0:
            raise JournalError("actual must be 0 or greater")
    entry.pop("outcome", None)
    entry.pop("actual", None)
    entry["status"] = "graded"
    entry["graded"] = today().isoformat()
    if entry["type"] == "claim":
        entry["outcome"] = outcome
    else:
        entry["actual"] = actual
    if note is not None:
        entry["note"] = note.strip()
    save(path, slots)
    return entry


MIN_N = 5
BUCKETS = ((50, 59), (60, 69), (70, 79), (80, 89), (90, 99))


def _claim_slice(claims):
    n = len(claims)
    if not n:
        return None
    stated = sum(c["confidence"] for c in claims) / n
    actual = 100 * sum(1 for c in claims if c["outcome"] == "yes") / n
    return {"n": n, "stated": stated, "actual": actual, "gap": stated - actual}


def _estimate_slice(ests):
    if not ests:
        return None
    ratios = [e["actual"] / e["estimate"] for e in ests]
    return {"n": len(ests), "median_ratio": statistics.median(ratios)}


def compute_stats(entries):
    graded = [e for e in entries if e["status"] == "graded"]
    claims = [e for e in graded if e["type"] == "claim" and e.get("outcome") in ("yes", "no")]
    ests = [e for e in graded
            if e["type"] == "estimate" and isinstance(e.get("actual"), (int, float))]
    result = {
        "graded": len(claims) + len(ests),
        "claim_count": len(claims),
        "estimate_count": len(ests),
        "too_few": len(claims) + len(ests) < MIN_N,
        "claims": None,
        "estimates": None,
        "tags": {},
    }
    if claims:
        brier = sum(
            (c["confidence"] / 100 - (1 if c["outcome"] == "yes" else 0)) ** 2 for c in claims
        ) / len(claims)
        buckets = []
        for low, high in BUCKETS:
            part = _claim_slice([c for c in claims if low <= c["confidence"] <= high])
            if part:
                buckets.append({"label": f"{low}-{high}", **part})
        result["claims"] = {"n": len(claims), "brier": brier, "buckets": buckets}
    if ests:
        ranged = [e for e in ests
                  if e.get("range_low") is not None and e.get("range_high") is not None]
        hits = sum(1 for e in ranged if e["range_low"] <= e["actual"] <= e["range_high"])
        result["estimates"] = {
            **_estimate_slice(ests), "range_n": len(ranged), "range_hits": hits,
        }
    tags = sorted({t for e in claims + ests for t in e.get("tags", [])})
    for tag in tags:
        result["tags"][tag] = {
            "claims": _claim_slice([c for c in claims if tag in c.get("tags", [])]),
            "estimates": _estimate_slice([e for e in ests if tag in e.get("tags", [])]),
        }
    return result


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _small(n):
    return "  (n<5)" if n < MIN_N else ""


def _verdict(ratio):
    if round(ratio, 2) == 1.0:
        return "on target"
    return "you run over" if ratio > 1 else "you run under"


def format_stats(stats, tag=None):
    label = f" (tag: {tag})" if tag else ""
    lines = [
        f"Decision journal{label}: {stats['graded']} graded "
        f"({_plural(stats['claim_count'], 'claim')}, {_plural(stats['estimate_count'], 'estimate')})"
    ]
    if stats["too_few"]:
        lines.append(f"Too few graded entries to conclude (need at least {MIN_N}).")
        return "\n".join(lines)
    claims = stats["claims"]
    if claims:
        lines += ["", f"Claims (n={claims['n']}): Brier {claims['brier']:.3f}{_small(claims['n'])}"]
        for b in claims["buckets"]:
            lines.append(
                f"  {b['label']}  n={b['n']}  stated {b['stated']:.0f}%  "
                f"actual {b['actual']:.0f}%  gap {b['gap']:+.0f}{_small(b['n'])}"
            )
        lines.append("  gap = stated - actual; positive means overconfident")
    est = stats["estimates"]
    if est:
        lines += [
            "",
            f"Estimates (n={est['n']}): median actual/estimate {est['median_ratio']:.2f}x "
            f"({_verdict(est['median_ratio'])}){_small(est['n'])}",
        ]
        if est["range_n"]:
            pct = 100 * est["range_hits"] / est["range_n"]
            lines.append(
                f"  Range hit: {est['range_hits']} of {est['range_n']} = {pct:.0f}% "
                "(an 80% range should hit about 80%)"
            )
    if stats["tags"]:
        lines += ["", "By tag:"]
        for name, parts in stats["tags"].items():
            c, e = parts["claims"], parts["estimates"]
            if c:
                lines.append(
                    f"  {name}: claims n={c['n']} stated {c['stated']:.0f}% "
                    f"actual {c['actual']:.0f}% gap {c['gap']:+.0f}{_small(c['n'])}"
                )
            if e:
                lines.append(
                    f"  {name}: estimates n={e['n']} median {e['median_ratio']:.2f}x{_small(e['n'])}"
                )
    return "\n".join(lines)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="journal.py", description="Log predictions, grade them, and review calibration."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="record a prediction")
    add.add_argument("--type", required=True, choices=["claim", "estimate"])
    add.add_argument("--text", required=True)
    add.add_argument("--confidence", type=int, help="claims: 50-99")
    add.add_argument("--unit", help="estimates: for example hours")
    add.add_argument("--estimate", type=float, help="estimates: your point estimate")
    add.add_argument("--range-low", type=float, help="estimates: low end of your 80%% range")
    add.add_argument("--range-high", type=float, help="estimates: high end of your 80%% range")
    add.add_argument("--know-by", help="date you expect to know the outcome (YYYY-MM-DD)")
    add.add_argument("--tag", help="comma-separated tags")

    lst = sub.add_parser("list", help="print entries as JSON")
    group = lst.add_mutually_exclusive_group()
    group.add_argument("--open", action="store_true")
    group.add_argument("--due", action="store_true")

    grade = sub.add_parser("grade", help="record the outcome of a prediction")
    grade.add_argument("id", type=int)
    grade.add_argument("--outcome", choices=["yes", "no"])
    grade.add_argument("--actual", type=float)
    grade.add_argument("--note")
    grade.add_argument("--force", action="store_true", help="overwrite an existing grade")
    stats = sub.add_parser("stats", help="print the calibration report")
    stats.add_argument("--tag", help="only entries carrying this tag")
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    path = log_path()
    try:
        if args.cmd == "add":
            result = add_entry(
                path, type=args.type, text=args.text, confidence=args.confidence,
                unit=args.unit, estimate=args.estimate, range_low=args.range_low,
                range_high=args.range_high, know_by=args.know_by, tags=args.tag,
            )
            print(json.dumps(result))
        elif args.cmd == "list":
            mode = "open" if args.open else "due" if args.due else None
            print(json.dumps(list_entries(path, mode)))
        elif args.cmd == "grade":
            result = grade_entry(
                path, args.id, outcome=args.outcome, actual=args.actual,
                note=args.note, force=args.force,
            )
            print(json.dumps(result))
        elif args.cmd == "stats":
            entries = entries_of(load(path))
            if args.tag:
                tag = args.tag.strip().lower()
                entries = [e for e in entries if tag in e.get("tags", [])]
            print(format_stats(compute_stats(entries), tag=args.tag and args.tag.strip().lower()))
    except JournalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except NotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
