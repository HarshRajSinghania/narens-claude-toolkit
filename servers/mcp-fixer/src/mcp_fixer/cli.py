"""Command line: mcp-fixer score."""
import argparse
import json
import math
import sys
from pathlib import Path

from . import __version__
from .report import render_json, render_text
from .score import FILE_SOURCE, score_tools
from .stdio_client import ClientError, list_tools_stdio


class UsageError(Exception):
    """A problem with the command line or an input file, reported as `error: ...` with exit 2."""


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mcp-fixer",
        description="Score an MCP server's tool definitions with deterministic lint rules.",
    )
    parser.add_argument("--version", action="version", version=f"mcp-fixer {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser(
        "score",
        usage="mcp-fixer score [options] (--tools-json FILE | -- SERVER_COMMAND [ARGS...])",
        description=(
            "Read a server's tool list and print a lint score from 0 to 100. Give either a saved "
            "tools/list result (--tools-json) or, after --, the command that starts a stdio MCP "
            "server. Only initialize and tools/list are ever sent; no tool is called."
        ),
    )
    score.add_argument("--tools-json", metavar="FILE", help="a saved tools/list result (a JSON array or an object with a tools array)")
    score.add_argument("--env", action="append", default=[], metavar="KEY=VALUE", help="environment variable for the server (repeatable)")
    score.add_argument("--timeout", type=float, default=30.0, metavar="SECONDS", help="per-request timeout (default 30)")
    score.add_argument("--format", choices=("text", "json"), default="text", help="output format (default text)")
    score.add_argument("--out", metavar="FILE", help="write the report to FILE instead of stdout")
    score.add_argument("--min-score", type=float, metavar="N", help="exit with code 1 when the score is below N")
    return parser


def load_tools_file(path):
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise UsageError(f"cannot read {path}: {exc.strerror or exc}") from None
    except UnicodeDecodeError:
        raise UsageError(f"{path} is not UTF-8 text") from None
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise UsageError(f"{path} is not valid JSON ({exc})") from None
    if isinstance(data, dict) and isinstance(data.get("tools"), list):
        return data["tools"]
    if isinstance(data, list):
        return data
    raise UsageError(f'{path} must be a JSON array or an object with a "tools" array')


def parse_env(pairs):
    env = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator or not key:
            raise UsageError(f"--env needs KEY=VALUE, got {pair!r}")
        env[key] = value
    return env


def emit(text):
    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        # A legacy console encoding must not crash the report; unknown characters become "?".
        stream.reconfigure(encoding="utf-8", errors="replace")
    stream.write(text)


def run_score(args, command):
    if args.tools_json and command:
        raise UsageError("give either --tools-json or a server command after --, not both")
    if not args.tools_json and not command:
        raise UsageError("give --tools-json FILE, or a server command after --")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise UsageError("--timeout must be a finite number greater than 0")
    if args.min_score is not None and not math.isfinite(args.min_score):
        raise UsageError("--min-score must be a finite number")
    env = parse_env(args.env)
    if args.tools_json:
        tools = load_tools_file(args.tools_json)
        source = dict(FILE_SOURCE)
    else:
        tools, info = list_tools_stdio(command, env, args.timeout)
        source = {"kind": "stdio", **info}
    result = score_tools(tools, source)
    text = render_json(result) if args.format == "json" else render_text(result)
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except OSError as exc:
            raise UsageError(f"cannot write {args.out}: {exc.strerror or exc}") from None
    else:
        emit(text)
    if args.min_score is not None and result["score"] < args.min_score:
        return 1
    return 0


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    command = []
    if "--" in args:
        split = args.index("--")
        command, args = args[split + 1:], args[:split]
    parsed = build_parser().parse_args(args)
    try:
        return run_score(parsed, command)
    except (UsageError, ClientError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
