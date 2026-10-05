"""Rendering a score report as JSON (for programs) or text (for people)."""
import json


def _safe(value):
    """Text for a terminal: control characters become visible escapes.

    Tool names, parameter names and descriptions come from the server and are untrusted (a remote
    server's saved tool list is scored with --tools-json). Raw escape sequences could clear the
    screen, retitle the window or forge report lines.
    """
    out = []
    for char in str(value):
        code = ord(char)
        if char == "\n":
            out.append("\\n")
        elif char == "\r":
            out.append("\\r")
        elif char == "\t":
            out.append("\\t")
        elif code < 32 or 127 <= code <= 159 or char in "\u2028\u2029":
            out.append(f"\\x{code:02x}" if code < 256 else f"\\u{code:04x}")
        else:
            out.append(char)
    return "".join(out)


def render_json(report):
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def _source_line(source):
    if source.get("kind") == "stdio":
        who = " ".join(_safe(x) for x in (source.get("serverName"), source.get("serverVersion")) if x)
        line = f"server: {who or 'unnamed server'}"
        if source.get("protocolVersion"):
            line += f" (protocol {_safe(source['protocolVersion'])})"
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
        lines.append(f"note: {_safe(note)}")
    per_tool = metrics["perTool"]
    if per_tool:
        names = {name: _safe(name) for name in per_tool}
        width = max(len(shown) for shown in names.values())
        lines += ["", f"{'tool'.ljust(width)}  score  findings  tokens"]
        for name, entry in per_tool.items():
            lines.append(
                f"{names[name].ljust(width)}  {entry['score']:>5}  {entry['findings']:>8}  {entry['estimatedTokens']:>6}"
            )
    if report["findings"]:
        lines += ["", "findings"]
        for f in report["findings"]:
            where = _safe(f["tool"]) if f["tool"] else "server"
            if f["param"]:
                where += f".{_safe(f['param'])}"
            lines.append(f"  [{f['severity']}] {f['rule']} {where}: {_safe(f['message'])}")
            if f["evidence"]:
                lines.append(f"      evidence: {_safe(f['evidence'])}")
            if f["fix"]:
                lines.append(f"      fix: {_safe(f['fix'])}")
    return "\n".join(lines) + "\n"
