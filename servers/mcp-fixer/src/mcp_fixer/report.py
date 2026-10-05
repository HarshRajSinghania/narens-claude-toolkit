"""Rendering a score report as JSON (for programs) or text (for people)."""
import json


def render_json(report):
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def _source_line(source):
    if source.get("kind") == "stdio":
        who = " ".join(x for x in (source.get("serverName"), source.get("serverVersion")) if x)
        line = f"server: {who or 'unnamed server'}"
        if source.get("protocolVersion"):
            line += f" (protocol {source['protocolVersion']})"
        return line
    return "source: tool list file"


def render_text(report):
    metrics = report["metrics"]
    lines = [
        f"mcp-fixer score: {report['score']}/100",
        _source_line(report["source"]),
        f"tools: {metrics['toolCount']}, estimated definition size: {metrics['estimatedTokens']:,} tokens",
    ]
    for note in report["notes"]:
        lines.append(f"note: {note}")
    per_tool = metrics["perTool"]
    if per_tool:
        width = max(len(name) for name in per_tool)
        lines += ["", f"{'tool'.ljust(width)}  score  findings  tokens"]
        for name, entry in per_tool.items():
            lines.append(
                f"{name.ljust(width)}  {entry['score']:>5}  {entry['findings']:>8}  {entry['estimatedTokens']:>6}"
            )
    if report["findings"]:
        lines += ["", "findings"]
        for f in report["findings"]:
            where = f["tool"] or "server"
            if f["param"]:
                where += f".{f['param']}"
            lines.append(f"  [{f['severity']}] {f['rule']} {where}: {f['message']}")
            if f["evidence"]:
                lines.append(f"      evidence: {f['evidence']}")
            if f["fix"]:
                lines.append(f"      fix: {f['fix']}")
    return "\n".join(lines) + "\n"
