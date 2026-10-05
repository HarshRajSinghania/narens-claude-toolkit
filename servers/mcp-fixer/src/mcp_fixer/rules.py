"""Lint rules for MCP tool definitions. Deterministic; standard library only."""
import json
import math
import re

# Points a finding takes off the tool it is about.
SEVERITY_PENALTY = {"high": 25, "medium": 10, "low": 4}

THRESHOLDS = {
    "description_min_chars": 20,
    "description_max_chars": 500,
    "duplicate_overlap": 0.8,
    "max_nesting": 3,
    "max_tools": 40,
    "tokens_medium": 8000,
    "tokens_high": 20000,
}

# Points a server-level finding takes off the server score.
SERVER_PENALTY = {"T001": 5, "T002": {"medium": 5, "high": 15}, "N002": 4, "M001": 25}

GENERIC_NAMES = frozenset({"run", "execute", "call", "do", "action", "tool", "query"})

_SNAKE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)+$")
_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
_CAMEL = re.compile(r"^[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+$")
_WORD = re.compile(r"\w+")


def finding(rule, severity, message, *, tool=None, param=None, evidence="", fix="", data=None):
    return {
        "rule": rule,
        "severity": severity,
        "tool": tool,
        "param": param,
        "message": message,
        "evidence": evidence,
        "fix": fix,
        "data": data or {},
    }


def estimate_tokens(tool):
    """Canonical JSON length over 4, rounded up: a heuristic, not a tokenizer."""
    text = json.dumps(tool, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return math.ceil(len(text) / 4)


def check_description(tool):
    name = tool["name"]
    raw = tool.get("description")
    text = raw.strip() if isinstance(raw, str) else ""
    if not text:
        return [
            finding(
                "D001",
                "high",
                "no description",
                tool=name,
                fix="Add a description that says what the tool does and when to use it.",
                data={"action": "add-description"},
            )
        ]
    size = len(text)
    if size < THRESHOLDS["description_min_chars"]:
        return [
            finding(
                "D002",
                "medium",
                f"description is only {size} characters",
                tool=name,
                evidence=text,
                fix="Say what the tool does, what it returns and when to choose it.",
                data={"action": "expand-description"},
            )
        ]
    limit = THRESHOLDS["description_max_chars"]
    if size > limit:
        return [
            finding(
                "D003",
                "medium",
                f"description is {size} characters",
                tool=name,
                evidence=f"limit {limit}",
                fix="Shorten it: every tool description is sent to the model on every request.",
                data={"action": "shorten-description", "maxChars": limit},
            )
        ]
    return []


def _words(tool):
    raw = tool.get("description")
    return set(_WORD.findall(raw.lower())) if isinstance(raw, str) else set()


def check_duplicates(tools):
    """Pairs of tools whose descriptions share 80% or more of their words.

    Returns (index, finding) pairs, index being the position in `tools`; both tools of a pair
    get a finding.
    """
    found = []
    words = [_words(t) for t in tools]
    limit = THRESHOLDS["duplicate_overlap"]
    for i in range(len(tools)):
        for j in range(i + 1, len(tools)):
            a, b = words[i], words[j]
            if not a or not b:
                continue
            overlap = len(a & b) / len(a | b)
            if overlap < limit:
                continue
            for mine, other in ((i, j), (j, i)):
                found.append(
                    (
                        mine,
                        finding(
                            "D004",
                            "medium",
                            f"description is almost the same as {tools[other]['name']}",
                            tool=tools[mine]["name"],
                            evidence=f"{overlap:.0%} of words shared",
                            fix="Say what makes this tool different, so the model can tell them apart.",
                            data={"other": tools[other]["name"], "overlap": round(overlap, 2)},
                        ),
                    )
                )
    return found


def check_name(tool):
    name = tool["name"]
    if name.strip().lower() in GENERIC_NAMES:
        return [
            finding(
                "N001",
                "medium",
                f"'{name}' is too generic to choose between tools",
                tool=name,
                fix="Name it after what it does, for example search_orders.",
                data={"action": "rename"},
            )
        ]
    return []


def _style(name):
    if _SNAKE.match(name):
        return "snake_case"
    if _KEBAB.match(name):
        return "kebab-case"
    if _CAMEL.match(name):
        return "camelCase"
    return None


def check_server(tools):
    """N002, T001 and T002: findings about the server as a whole (tool is None)."""
    found = []
    styles = {}
    for tool in tools:
        style = _style(tool["name"])
        if style:
            styles[style] = styles.get(style, 0) + 1
    if len(styles) > 1:
        ordered = dict(sorted(styles.items()))
        found.append(
            finding(
                "N002",
                "low",
                "tool names mix naming styles",
                evidence=", ".join(f"{k} ({v})" for k, v in ordered.items()),
                fix="Pick one naming style for every tool.",
                data={"styles": ordered},
            )
        )
    limit = THRESHOLDS["max_tools"]
    if len(tools) > limit:
        found.append(
            finding(
                "T001",
                "medium",
                f"{len(tools)} tools is more than agents choose well between",
                evidence=f"limit {limit}",
                fix="Split the server, or hide the rarely used tools.",
                data={"toolCount": len(tools)},
            )
        )
    total = sum(estimate_tokens(t) for t in tools)
    if total > THRESHOLDS["tokens_high"]:
        severity = "high"
    elif total > THRESHOLDS["tokens_medium"]:
        severity = "medium"
    else:
        severity = None
    if severity:
        found.append(
            finding(
                "T002",
                severity,
                f"tool definitions take about {total:,} tokens on every request",
                evidence=f"limit {THRESHOLDS['tokens_medium']:,} (medium), {THRESHOLDS['tokens_high']:,} (high)",
                fix="Shorten descriptions and trim schemas, or expose fewer tools.",
                data={"estimatedTokens": total},
            )
        )
    return found


def malformed_finding(index, entry):
    if isinstance(entry, dict):
        evidence = "an object with no non-empty string name"
    else:
        evidence = f"a {type(entry).__name__} instead of an object"
    return finding(
        "M001",
        "high",
        f"tool entry {index} is malformed",
        evidence=evidence,
        fix="Return each tool as an object with a non-empty string name.",
    )
