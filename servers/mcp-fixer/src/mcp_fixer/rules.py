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


_TYPE_KEYS = ("type", "enum", "oneOf", "anyOf", "$ref")
_MAX_DEPTH_SCAN = 50

_TRIGGER = re.compile(
    r"\b(?:one of|either|must be|can be|should be|options?|allowed values?|valid values?"
    r"|possible values?|choices?|supported values?)\b[:\s]*",
    re.IGNORECASE,
)
_LEAD = re.compile(r"^(?:(?:are|is)\s+)?(?:(?:the following|these|below)\b)?[:\s]*", re.IGNORECASE)
_SPLIT = re.compile(r"\s*,\s*(?:or\s+|and\s+)?|\s+or\s+|\s*\|\s*|\s*/\s*", re.IGNORECASE)
_SENTENCE_END = re.compile(r"\.(?:\s|$)|\n")
_QUOTED = re.compile(r"""(['"`])([^'"`\n]{1,30})\1""")
_ARTICLE = re.compile(r"^(?:a|an|the)\s", re.IGNORECASE)
_MAX_VALUE_WORDS = 2
_MAX_VALUES = 20


def _clean_values(parts):
    """The values in `parts`, or [] when any part looks like prose instead of a value."""
    values = []
    for part in parts:
        value = part.strip().strip("'\"`()[]{}.,;:").strip()
        if not value:
            continue
        if len(value.split()) > _MAX_VALUE_WORDS or _ARTICLE.match(value):
            return []
        values.append(value)
    return values


def extract_enum_values(text):
    """Allowed values a description lists in prose ('one of: a, b'), in order; [] when none."""
    if not isinstance(text, str):
        return []
    for match in _TRIGGER.finditer(text):
        rest = _SENTENCE_END.split(text[match.end():], maxsplit=1)[0]
        rest = _LEAD.sub("", rest, count=1).strip()
        values = _clean_values(_SPLIT.split(rest))
        if len(values) >= 2:
            return values[:_MAX_VALUES]
    quoted = []
    for found in _QUOTED.finditer(text):
        value = found.group(2).strip()
        if value and value not in quoted:
            quoted.append(value)
    if len(quoted) >= 3:
        return quoted[:_MAX_VALUES]
    return []


def schema_depth(schema, level=0):
    """Levels of nested schemas below `schema` (properties, items, anyOf, oneOf, allOf).

    A schema with no nested schema is 0. Scanning stops at a fixed depth, so a hostile or
    runaway document cannot exhaust the stack.
    """
    if not isinstance(schema, dict):
        return 0
    if level >= _MAX_DEPTH_SCAN:
        return 1
    children = []
    props = schema.get("properties")
    if isinstance(props, dict):
        children.extend(props.values())
    items = schema.get("items")
    if isinstance(items, dict):
        children.append(items)
    elif isinstance(items, list):
        children.extend(items)
    for key in ("anyOf", "oneOf", "allOf"):
        options = schema.get(key)
        if isinstance(options, list):
            children.extend(options)
    if not children:
        return 0
    return 1 + max(schema_depth(child, level + 1) for child in children)


def _has_description(schema):
    text = schema.get("description")
    return isinstance(text, str) and bool(text.strip())


def _describe(schema):
    if schema is None:
        return "missing"
    if isinstance(schema, dict):
        return f"type is {schema.get('type')!r}"
    return f"a {type(schema).__name__}"


def check_schema(tool):
    """P001 to P006: the input schema and its top-level parameters."""
    name = tool["name"]
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return [
            finding(
                "P004",
                "high",
                "inputSchema is missing or is not an object schema",
                tool=name,
                evidence=_describe(schema),
                fix='Declare inputSchema as {"type": "object", "properties": {...}}.',
                data={"action": "fix-input-schema"},
            )
        ]
    found = []
    raw = schema.get("properties")
    props = raw if isinstance(raw, dict) else {}
    for pname, pschema in props.items():
        pschema = pschema if isinstance(pschema, dict) else {}
        if not _has_description(pschema):
            found.append(
                finding(
                    "P001",
                    "medium",
                    f"parameter '{pname}' has no description",
                    tool=name,
                    param=pname,
                    fix="Say what the value means and what format it takes.",
                    data={"action": "add-param-description"},
                )
            )
        if not any(key in pschema for key in _TYPE_KEYS):
            found.append(
                finding(
                    "P002",
                    "medium",
                    f"parameter '{pname}' has no type",
                    tool=name,
                    param=pname,
                    fix="Declare its type, or an enum of the allowed values.",
                    data={"action": "add-param-type"},
                )
            )
        if pschema.get("type") == "string" and "enum" not in pschema:
            values = extract_enum_values(pschema.get("description"))
            if values:
                found.append(
                    finding(
                        "P003",
                        "medium",
                        f"parameter '{pname}' lists its allowed values in prose but has no enum",
                        tool=name,
                        param=pname,
                        evidence=", ".join(values),
                        fix="Declare them as an enum so the model cannot invent other values.",
                        data={"action": "add-enum", "values": values},
                    )
                )
    required = schema.get("required")
    if len(props) >= 2 and not (isinstance(required, list) and required):
        found.append(
            finding(
                "P005",
                "low",
                f"{len(props)} parameters and no required list",
                tool=name,
                fix="List the parameters the tool cannot work without in required.",
                data={"action": "add-required"},
            )
        )
    depth = schema_depth(schema)
    if depth > THRESHOLDS["max_nesting"]:
        found.append(
            finding(
                "P006",
                "low",
                f"input schema is nested {depth} levels deep",
                tool=name,
                evidence=f"limit {THRESHOLDS['max_nesting']}",
                fix="Flatten the parameters; deeply nested objects are easy to fill in wrongly.",
                data={"depth": depth},
            )
        )
    return found
