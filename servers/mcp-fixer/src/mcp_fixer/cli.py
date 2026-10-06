"""Command line: mcp-fixer score, patch and wrap."""
import argparse
import json
import math
import os
import sys
from pathlib import Path

from . import __version__
from .patch_format import PatchError, load_patch
from .patch_gen import generate_patch, render_patch
from .report import render_json, render_text
from .score import FILE_SOURCE, score_tools
from .stdio_client import ClientError, list_tools_stdio
from .wrap import run_wrapper


class UsageError(Exception):
    """A problem with the command line or an input file, reported as `error: ...` with exit 2."""


def _add_input_options(parser):
    parser.add_argument("--tools-json", metavar="FILE", help="a saved tools/list result (a JSON array or an object with a tools array)")
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VALUE", help="environment variable for the server (repeatable)")
    parser.add_argument("--timeout", type=float, default=30.0, metavar="SECONDS", help="per-request timeout (default 30)")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mcp-fixer",
        description="Score an MCP server's tool definitions, write a patch for them, and run a wrapper that applies it.",
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
    _add_input_options(score)
    score.add_argument("--format", choices=("text", "json"), default="text", help="output format (default text)")
    score.add_argument("--out", metavar="FILE", help="write the report to FILE instead of stdout")
    score.add_argument("--min-score", type=float, metavar="N", help="exit with code 1 when the score is below N")

    patch = sub.add_parser(
        "patch",
        usage="mcp-fixer patch [options] (--tools-json FILE | -- SERVER_COMMAND [ARGS...])",
        description=(
            "Write a patch file for a server's tool definitions from the lint findings: enums and "
            "trimmed descriptions are filled in (listed under review), everything else becomes a "
            "todo entry. Read-only like score."
        ),
    )
    _add_input_options(patch)
    patch.add_argument("--out", metavar="FILE", help="write the patch to FILE instead of stdout (never overwrites without --force)")
    patch.add_argument("--force", action="store_true", help="overwrite an existing --out file")

    wrap = sub.add_parser(
        "wrap",
        usage="mcp-fixer wrap --patch FILE [--allow-stale] -- SERVER_COMMAND [ARGS...]",
        description=(
            "Run a stdio MCP server behind a patch: the client sees the patched tool definitions and "
            "every other message passes through unchanged. Use this command where the client config "
            "would have the real server's command."
        ),
    )
    wrap.add_argument("--patch", required=True, metavar="FILE", help="the patch file (see mcp-fixer patch)")
    wrap.add_argument("--allow-stale", action="store_true", help="apply a patch entry even when the server's tool has changed since the patch was made")
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
    except RecursionError:
        raise UsageError(f"{path} is not valid JSON (nested too deeply)") from None
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


def read_tools(args, command):
    """The tool list and its source description, from --tools-json or a spawned server."""
    if args.tools_json and command:
        raise UsageError("give either --tools-json or a server command after --, not both")
    if not args.tools_json and not command:
        raise UsageError("give --tools-json FILE, or a server command after --")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise UsageError("--timeout must be a finite number greater than 0")
    env = parse_env(args.env)
    if args.tools_json:
        return load_tools_file(args.tools_json), dict(FILE_SOURCE)
    tools, info = list_tools_stdio(command, env, args.timeout)
    return tools, {"kind": "stdio", **info}


def write_file(path, text, overwrite):
    try:
        with open(path, "w" if overwrite else "x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError:
        raise UsageError(f"{path} exists; use --force to overwrite") from None
    except OSError as exc:
        raise UsageError(f"cannot write {path}: {exc.strerror or exc}") from None


def run_score(args, command):
    if args.min_score is not None and not math.isfinite(args.min_score):
        raise UsageError("--min-score must be a finite number")
    tools, source = read_tools(args, command)
    try:
        result = score_tools(tools, source)
    except RecursionError:
        raise UsageError("the tool list is nested too deeply to score") from None
    text = render_json(result) if args.format == "json" else render_text(result)
    if args.out:
        write_file(args.out, text, overwrite=True)
    else:
        emit(text)
    if args.min_score is not None and result["score"] < args.min_score:
        return 1
    return 0


def run_patch(args, command):
    tools, source = read_tools(args, command)
    try:
        text = render_patch(generate_patch(tools, source))
    except RecursionError:
        raise UsageError("the tool list is nested too deeply to patch") from None
    if args.out:
        write_file(args.out, text, overwrite=args.force)
    else:
        emit(text)
    return 0


def run_wrap(args, command):
    patch = load_patch(args.patch)
    if not command:
        raise UsageError("give the real server command after --")
    return run_wrapper(patch, command, args.allow_stale)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    command = []
    if "--" in args:
        split = args.index("--")
        command, args = args[split + 1:], args[:split]
    parsed = build_parser().parse_args(args)
    handlers = {"score": run_score, "patch": run_patch, "wrap": run_wrap}
    try:
        return handlers[parsed.command](parsed, command)
    except (UsageError, ClientError, PatchError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def run():
    """The console-script entry point: `main`, then leave without waiting on any thread.

    The wrapper's client-reading thread may still be blocked on stdin; a normal interpreter
    shutdown can then fail with a fatal error. Output is flushed first.
    """
    code = main()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError):
            pass
    os._exit(code)
