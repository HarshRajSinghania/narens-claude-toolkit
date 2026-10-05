"""Pure scoring: a list of MCP tool definitions in, a report dict out."""
import math

from . import rules

EMPTY_NOTE = "no tools listed"
FILE_SOURCE = {"kind": "file", "protocolVersion": None, "serverName": None, "serverVersion": None}


def _round_half_up(value):
    return int(math.floor(value + 0.5))


def _unique_keys(names):
    """name, name#2, name#3 ... so duplicate tool names keep separate entries."""
    seen = {}
    keys = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        keys.append(name if seen[name] == 1 else f"{name}#{seen[name]}")
    return keys


def _tool_score(findings):
    return max(0, 100 - sum(rules.SEVERITY_PENALTY[f["severity"]] for f in findings))


def _server_penalty(finding):
    penalty = rules.SERVER_PENALTY[finding["rule"]]
    return penalty[finding["severity"]] if isinstance(penalty, dict) else penalty


def _sort_key(finding):
    return (
        finding["tool"] or "",
        finding["rule"],
        finding["param"] or "",
        finding["evidence"],
        finding["message"],
    )


def score_tools(tools, source=None):
    valid = []
    server_findings = []
    for index, entry in enumerate(tools):
        if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"]:
            valid.append(entry)
        else:
            server_findings.append(rules.malformed_finding(index, entry))

    by_tool = [[] for _ in valid]
    for position, tool in enumerate(valid):
        by_tool[position].extend(rules.check_description(tool))
        by_tool[position].extend(rules.check_schema(tool))
        by_tool[position].extend(rules.check_name(tool))
    for position, finding in rules.check_duplicates(valid):
        by_tool[position].append(finding)
    server_findings.extend(rules.check_server(valid))

    per_tool = {}
    for key, tool, findings in zip(_unique_keys([t["name"] for t in valid]), valid, by_tool):
        per_tool[key] = {
            "estimatedTokens": rules.estimate_tokens(tool),
            "score": _tool_score(findings),
            "findings": len(findings),
        }
    scores = [entry["score"] for entry in per_tool.values()]
    mean = sum(scores) / len(scores) if scores else 100
    penalty = sum(_server_penalty(f) for f in server_findings)
    total = min(100, max(0, _round_half_up(mean - penalty)))

    findings = sorted(
        [f for group in by_tool for f in group] + server_findings, key=_sort_key
    )
    notes = [EMPTY_NOTE] if not tools else []
    return {
        "schemaVersion": 1,
        "source": dict(source) if source else dict(FILE_SOURCE),
        "score": total,
        "metrics": {
            "toolCount": len(valid),
            "estimatedTokens": sum(entry["estimatedTokens"] for entry in per_tool.values()),
            "perTool": per_tool,
        },
        "findings": findings,
        "notes": notes,
    }
