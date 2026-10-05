#!/usr/bin/env python3
"""preflight: lint a scheduled task's prompt before it is scheduled.

    python preflight.py --prompt-file FILE [--guard-hours N] [--json]

Read-only. Standard library only. The tool list is a heuristic ("likely needs"), not a guarantee.
Only short matched snippets are printed, never the whole prompt.
Exit code 0 on success, 2 when the prompt cannot be read.
"""
import argparse
import json
import re
import sys
from pathlib import Path

MAX_PROMPT_CHARS = 20000
MAX_SNIPPET = 40
MAX_GUARD_SNIPPET = 80
MAX_SNIPPETS_PER_TOOL = 3
DEFAULT_GUARD_HOURS = 2.0
PRE_APPROVE = "pre-approve"
APPROVE_ONCE = "approve once with Run now"


class PreflightError(Exception):
    """A problem the user can fix; reported as `error: ...` with exit 2."""


def rx(pattern):
    return re.compile(pattern, re.IGNORECASE)


FILE_NAME = r"[\w./\\-]{1,60}\.(?:md|txt|json|csv|log|html|yaml|yml|py|js|ts|toml|cfg|ini)\b"


# (tool name or None to use the matched text, advice, pattern). Every quantifier is bounded so the
# patterns stay fast on a prompt of up to MAX_PROMPT_CHARS.
TOOL_RULES = [
    (None, PRE_APPROVE, rx(r"\bmcp__[A-Za-z0-9_\-]+")),
    (
        "Bash(git push)",
        APPROVE_ONCE,
        rx(
            r"\bgit\s+push\b|\bforce[- ]push\b|\bcommit\s+and\s+push\b"
            r"|\bpush\s+(?:\w+\s+){0,2}(?:commits?|changes|branch|fix|code|work|origin|remote)\b"
        ),
    ),
    (
        "Bash(destructive)",
        APPROVE_ONCE,
        rx(
            r"\brm\s+-\w+|\bdrop\s+(?:table|database)\b|\breset\s+--hard\b"
            r"|\bdelete\s+(?:\w+\s+){0,2}(?:files?|folders?|directory|directories|branch(?:es)?)\b"
        ),
    ),
    (
        "External send or deploy",
        APPROVE_ONCE,
        rx(
            r"\bdeploy(?:ing)?\b"
            r"|\b(?:send|post|publish)\b[^.\n]{0,40}\b(?:email|e-mail|slack|discord|tweet|webhook|release)\b"
            r"|\b(?:open|create|file|submit)\s+(?:a\s+|an\s+|the\s+)?(?:pull request|pr|issue|ticket)\b"
            r"|\b(?:email|e-mail|dm|message|slack|notify)\s+(?:me|us|him|her|them|the team)\b"
        ),
    ),
    (
        "Bash",
        PRE_APPROVE,
        rx(
            r"\b(?:npm|npx|pnpm|yarn|pip3?|pytest|cargo|docker|kubectl|python3?|node|bash|powershell"
            r"|curl|wget|git|gh|terraform|aws|gcloud|uv|deno|bun|ruff|mypy|eslint|tsc)\b"
            r"|\bgo\s+(?:test|build|run|vet|mod)\b|\baz\s+\w+"
            r"|\bmake\s+(?:test|build|install|all|lint|check|clean)\b"
            r"|\brun\s+(?:the\s+|a\s+|my\s+)?(?:tests?|script|command|build|migration)s?\b"
        ),
    ),
    (
        "Write/Edit",
        PRE_APPROVE,
        rx(
            r"\b(?:write|create|save|edit|update|modify|append|overwrite)\b[^.\n]{0,60}"
            r"\b(?:files?|folders?|director(?:y|ies)|reports?|notes?|logs?)\b"
            r"|\b(?:write|save)\s+(?:it\s+)?to\b"
            r"|\b(?:write|create|save|edit|update|modify|append|overwrite)\s+(?:to\s+|the\s+|my\s+)?"
            + FILE_NAME
            + r"|\b(?:in|into|to)\s+"
            + FILE_NAME
        ),
    ),
    (
        "MCP connector (likely)",
        PRE_APPROVE,
        rx(
            r"\b(?:gmail|google calendar|google drive|gcal|slack|notion|linear|jira|github|asana"
            r"|figma|salesforce|hubspot|stripe)\b"
        ),
    ),
    (
        "WebFetch/WebSearch",
        PRE_APPROVE,
        rx(r"https?://\S+|\bweb\s?search\b|\bsearch the web\b|\b(?:fetch|browse|scrape|download)\b"),
    ),
]

# A guard has to be about time: a condition with no clock in it ("skip merge commits when ...",
# "only run the tests if the build passed") is not one, and calling it one would hide the snippet.
TIME_WORD = (
    r"(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)\b|\d+\s*(?:minutes?|hours?)\b|noon\b|midnight\b"
    r"|scheduled\b|late\b|time\b)"
)
GUARD_PATTERNS = [
    rx(r"\bskip\b[^.\n]{0,80}\b(?:if|when|unless)\b[^.\n]{0,80}\b" + TIME_WORD),
    rx(
        r"\b(?:if|when)\b[^.\n]{0,100}"
        r"\b(?:(?:after|past|later than)\s+(?:\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b|noon\b|midnight\b"
        r"|the scheduled\b)|more than \d+\s*(?:minutes?|hours?)\b|too late\b|late\b)[^.\n]{0,100}"
        r"\b(?:skip|stop|abort|exit|do nothing)\b"
    ),
    rx(
        r"\bonly\s+(?:run|act|proceed)\b[^.\n]{0,60}\b(?:if|before|between|within)\b[^.\n]{0,60}\b"
        + TIME_WORD
    ),
]

STALENESS = rx(
    r"\b(?:latest|newest|most recent|today(?:'s)?|yesterday(?:'s)?|this morning|tonight"
    r"|this week|last night)\b"
)


def find_tools(lines):
    found = {}
    for tool, advice, pattern in TOOL_RULES:
        for number, line in enumerate(lines, 1):
            for match in pattern.finditer(line):
                name = tool or match.group(0)
                entry = found.setdefault(
                    name, {"tool": name, "advice": advice, "matched": [], "lines": []}
                )
                snippet = match.group(0).strip()[:MAX_SNIPPET]
                known = [s.lower() for s in entry["matched"]]
                if snippet.lower() not in known and len(entry["matched"]) < MAX_SNIPPETS_PER_TOOL:
                    entry["matched"].append(snippet)
                if number not in entry["lines"]:
                    entry["lines"].append(number)
    return list(found.values())


def find_guard(lines):
    for number, line in enumerate(lines, 1):
        for pattern in GUARD_PATTERNS:
            match = pattern.search(line)
            if match:
                return match.group(0).strip()[:MAX_GUARD_SNIPPET], number
    return None, None


def find_staleness(lines):
    seen = {}
    for number, line in enumerate(lines, 1):
        for match in STALENESS.finditer(line):
            phrase = match.group(0).lower()
            entry = seen.setdefault(phrase, {"phrase": phrase, "lines": []})
            if number not in entry["lines"]:
                entry["lines"].append(number)
    return list(seen.values())


def guard_snippet(hours):
    return (
        "Before doing anything else, compare the current time with this task's scheduled time. "
        f"If this run started more than {hours:g} hours after the scheduled time, stop: "
        "do not act on any data, and report that the run was late."
    )


def analyze(text, guard_hours=DEFAULT_GUARD_HOURS):
    if guard_hours <= 0:
        raise PreflightError("--guard-hours must be greater than 0")
    if not text.strip():
        raise PreflightError("the prompt is empty")
    if len(text) > MAX_PROMPT_CHARS:
        raise PreflightError(f"the prompt is longer than {MAX_PROMPT_CHARS} characters")
    lines = text.split("\n")
    matched, number = find_guard(lines)
    return {
        "tools": find_tools(lines),
        "time_guard": {
            "present": matched is not None,
            "matched": matched,
            "line": number,
            "hours": guard_hours,
            "snippet": None if matched else guard_snippet(guard_hours),
        },
        "staleness_hints": find_staleness(lines),
    }


def ascii_safe(text):
    """Matched snippets come from the prompt; a console on a legacy code page cannot print them all."""
    return text.encode("ascii", "backslashreplace").decode("ascii")


def render(res):
    out = ["tools (likely needs; a heuristic, not a guarantee):"]
    if not res["tools"]:
        out.append("  none detected; ask the user what the task touches (this only reads the prompt text)")
    for t in res["tools"]:
        lines = ", ".join(str(n) for n in t["lines"])
        matched = ascii_safe(", ".join(t["matched"]))
        out.append(f"  {t['tool']}: {t['advice']} (matched: {matched}; line {lines})")
    guard = res["time_guard"]
    if guard["present"]:
        out.append(f"time guard: found ({ascii_safe(guard['matched'])!r} on line {guard['line']})")
    else:
        out.append("time guard: missing")
        out.append(f"  paste this into the prompt (assumed {guard['hours']:g} hours; ask the user):")
        out.append(f"  {guard['snippet']}")
    if res["staleness_hints"]:
        out.append("staleness hints (a late run would read these against the wrong date):")
        for hint in res["staleness_hints"]:
            lines = ", ".join(str(n) for n in hint["lines"])
            out.append(f"  {hint['phrase']} (line {lines})")
    return "\n".join(out)


def read_prompt(path):
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise PreflightError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        # Windows PowerShell 5.1 writes UTF-16 with a byte order mark when it redirects with `>`.
        text = raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig")
    except UnicodeDecodeError:
        raise PreflightError(f"{path} is not UTF-8 or UTF-16 text") from None
    return text.replace("\r\n", "\n").replace("\r", "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="preflight.py", description="Lint a scheduled task's prompt before it is scheduled."
    )
    parser.add_argument("--prompt-file", required=True, help="the task prompt, as a text file")
    parser.add_argument(
        "--guard-hours",
        type=float,
        default=DEFAULT_GUARD_HOURS,
        help=f"hours of lateness the time guard tolerates (default {DEFAULT_GUARD_HOURS:g})",
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args(argv)
    try:
        res = analyze(read_prompt(args.prompt_file), args.guard_hours)
    except PreflightError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2) if args.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
