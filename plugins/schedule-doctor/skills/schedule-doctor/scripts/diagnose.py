#!/usr/bin/env python3
"""diagnose: classify why a scheduled run did not fire or halted, from a normalized run record.

    python diagnose.py --record FILE [--late-minutes N] [--json]

Read-only. Standard library only. A timestamp without an offset is read as UTC. The record holds
only times, a status and short event names; prompts and transcripts are never read or printed.
Exit code 0 for any verdict, 2 when the record cannot be read.
"""
import argparse
import json
import math
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

LATE_MINUTES = 30
SURFACES = ("desktop", "code-cron", "routine")
SLEEP_KINDS = ("sleep", "hibernate", "lid-close")
EVENT_KINDS = SLEEP_KINDS + ("wake",)
# Words in `last_event` or `status` that mean the run stopped or is waiting on a permission.
HALT_WORDS = ("permission", "denied", "approval", "approve")
OK_STATUSES = ("completed", "succeeded", "success", "ok", "done", "finished")
FAILED_STATUSES = ("failed", "error", "errored", "timed-out", "timeout", "aborted")
MAX_ERROR_TEXT = 200
MAX_STATUS_TEXT = 40


class DiagnoseError(Exception):
    """A problem the user can fix; reported as `error: ...` with exit 2."""


def parse_time(value, field):
    if value is None:
        return None
    if not isinstance(value, str):
        raise DiagnoseError(f"{field}: expected an ISO-8601 string, got {type(value).__name__}")
    text = value.strip()
    try:
        date.fromisoformat(text)
    except ValueError:
        pass
    else:
        raise DiagnoseError(f"{field}: expected a time component, not a date-only value")
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    # Python 3.9/3.10 require 3 or 6 fractional digits and a colon in UTC offsets.
    # Windows events use 100-nanosecond precision; datetime retains microseconds.
    text = re.sub(
        r"^(\d{4}-\d{2}-\d{2}.\d{2}:\d{2}:\d{2})\.(\d+)",
        lambda match: match[1] + "." + match[2][:6].ljust(6, "0"),
        text,
    )
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise DiagnoseError(f"{field}: not an ISO-8601 time: {value!r}") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def norm(value):
    """Lower-case, trimmed, with underscores as hyphens; anything that is not text becomes ''."""
    return value.strip().lower().replace("_", "-") if isinstance(value, str) else ""


def parse_events(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DiagnoseError("machine_events must be a list")
    events = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or not isinstance(item.get("kind"), str):
            raise DiagnoseError(f"machine_events[{i}]: needs a string 'kind'")
        kind = norm(item["kind"])
        if kind not in EVENT_KINDS:
            raise DiagnoseError(
                f"machine_events[{i}]: kind {item['kind']!r} is not one of: " + ", ".join(EVENT_KINDS)
            )
        at = parse_time(item.get("at"), f"machine_events[{i}].at")
        if at is None:
            raise DiagnoseError(f"machine_events[{i}]: needs an 'at' time")
        events.append((at, kind))
    return sorted(events, key=lambda event: event[0])


def asleep_at(events, moment):
    """True when the last sleep or lid event at or before `moment` has not been followed by a wake."""
    asleep = False
    for at, kind in events:
        if at > moment:
            break
        if kind in SLEEP_KINDS:
            asleep = True
        elif kind == "wake":
            asleep = False
    return asleep


def result(verdict, why, evidence):
    return {"verdict": verdict, "why": why, "evidence": evidence}


def classify(record, late_minutes=LATE_MINUTES):
    if not isinstance(record, dict):
        raise DiagnoseError("the record must be a JSON object")
    surface = record.get("surface")
    if surface not in SURFACES:
        raise DiagnoseError("surface must be one of: " + ", ".join(SURFACES))
    scheduled = parse_time(record.get("scheduled_for"), "scheduled_for")
    if scheduled is None:
        raise DiagnoseError("scheduled_for is required")
    started = parse_time(record.get("started_at"), "started_at")
    ended = parse_time(record.get("ended_at"), "ended_at")
    status = norm(record.get("status"))
    events = parse_events(record.get("machine_events"))

    asleep = asleep_at(events, scheduled)
    delay = None if started is None else round((started - scheduled).total_seconds() / 60, 1)
    error_text = record.get("error_text")
    if isinstance(error_text, str):
        error_text = error_text.strip()[:MAX_ERROR_TEXT]
    evidence = {
        "surface": surface,
        "scheduled_for": record["scheduled_for"],
        "started_at": record.get("started_at"),
        "delay_minutes": delay,
        "late_threshold_minutes": late_minutes,
        "asleep_at_schedule": asleep,
        "error_text": error_text or None,
    }

    tool = record.get("permission_denied_tool")
    if tool is not None and not isinstance(tool, str):
        raise DiagnoseError("permission_denied_tool: expected a string or null")
    last_event = record.get("last_event")
    last = norm(last_event)
    if tool or any(word in last or word in status for word in HALT_WORDS):
        evidence["permission_denied_tool"] = tool or None
        evidence["last_event"] = last_event
        what = f"the tool {tool}" if tool else "a tool"
        return result(
            "permission-halt",
            f"The run stopped when {what} needed a permission nobody had approved. "
            "Approve it once with Run now, or pre-approve it, then schedule again.",
            evidence,
        )
    if started is None:
        if asleep:
            return result(
                "slept-through",
                "No run started, and the machine was asleep (or the lid was closed) "
                "at the scheduled time.",
                evidence,
            )
        return result(
            "never-ran-unknown",
            "No run started and nothing shows the machine was asleep at the scheduled time. "
            "Not enough data to say why.",
            evidence,
        )
    if delay > late_minutes:
        note = " The machine was asleep at the scheduled time, so this is a catch-up run." if asleep else ""
        return result(
            "late-catchup",
            f"The run started {delay:g} minutes after its scheduled time "
            f"(threshold {late_minutes:g}).{note} Anything it read may be stale.",
            evidence,
        )
    if error_text or status in FAILED_STATUSES:
        return result(
            "failed-unknown",
            "The run started on time but ended with an error that is not a permission halt.",
            evidence,
        )
    if status in OK_STATUSES or (status == "" and ended is not None):
        return result("healthy", "The run started on time and ended without an error.", evidence)
    return result(
        "unfinished-unknown",
        "The run started on time but there is no sign it finished "
        f"(status: {status[:MAX_STATUS_TEXT] or 'none'}, ended_at: {'set' if ended else 'missing'}).",
        evidence,
    )


def render(res):
    lines = [f"verdict: {res['verdict']}", f"why: {res['why']}", "evidence:"]
    for key, value in res["evidence"].items():
        lines.append(f"  {key}: {json.dumps(value)}")
    return "\n".join(lines)


def load_record(path):
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise DiagnoseError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        # Windows PowerShell 5.1 writes UTF-16 with a byte order mark when it redirects with `>`.
        text = raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig")
    except UnicodeDecodeError:
        raise DiagnoseError(f"{path} is not UTF-8 or UTF-16 text") from None
    try:
        return json.loads(text)
    except ValueError as exc:
        raise DiagnoseError(f"{path} is not valid JSON ({exc})") from None


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="diagnose.py", description="Classify why a scheduled run did not fire or halted."
    )
    parser.add_argument("--record", required=True, help="normalized run record (JSON file)")
    parser.add_argument(
        "--late-minutes",
        type=float,
        default=LATE_MINUTES,
        help=f"minutes after the schedule that count as a late catch-up (default {LATE_MINUTES})",
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args(argv)
    try:
        if not math.isfinite(args.late_minutes):
            raise DiagnoseError("--late-minutes must be finite")
        if args.late_minutes < 0:
            raise DiagnoseError("--late-minutes must not be negative")
        res = classify(load_record(args.record), args.late_minutes)
    except DiagnoseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2) if args.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
