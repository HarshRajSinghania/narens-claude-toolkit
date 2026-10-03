#!/usr/bin/env python3
"""rule_hook: enforce typed rules from .claude/rules.json as Claude Code hooks.

    python rule_hook.py check                   # hook entry point (hook payload on stdin)
    python rule_hook.py selftest [--rules PATH] # prove every rule blocks its violation and allows its pass

Standard library only. Hooks are guardrails, not a security boundary.
"""
import functools
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:  # Python 3.11+
    from re import _constants as _sre_const, _parser as _sre_parse
except ImportError:  # Python 3.9 and 3.10
    import sre_constants as _sre_const
    import sre_parse as _sre_parse

RULE_TYPES = ("protected_path", "blocked_command", "banned_content", "stop_check")
PATH_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
PATH_KEYS = ("file_path", "notebook_path")
TEXT_KEYS = ("content", "file_content", "new_string", "new_content", "new_source")
_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_TIMEOUT = 280  # seconds: the installed Stop hook allows 300
TOTAL_STOP_BUDGET = MAX_TIMEOUT  # all stop checks in one Stop event share this many seconds
_INTERPRETERS = frozenset((
    "sh", "bash", "zsh", "dash", "ksh", "source", "eval", "xargs", "ssh", "python", "python3", "py",
    "node", "perl", "ruby", "powershell", "pwsh", "cmd"))
_HEREDOC = re.compile(r"<<-?[ \t]*(?:'([^']+)'|\"([^\"]+)\"|\\?([A-Za-z0-9_]+))")
GLOB_KEYS = ("globs", "allow_globs", "when_changed_globs")
_NT = os.name == "nt"
_CI = _NT or sys.platform == "darwin"  # case-insensitive file systems by default


class RulesError(Exception):
    """The rules file is missing or invalid."""


# --- paths and globs -----------------------------------------------------------------------

@functools.lru_cache(maxsize=512)
def glob_to_regex(glob):
    g = glob.replace("\\", "/")
    out, i = [], 0
    while i < len(g):
        if g.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif g.startswith("**", i):
            out.append(".*")
            i += 2
        elif g[i] == "*":
            out.append("[^/]*")
            i += 1
        elif g[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(g[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE if _CI else 0)


def glob_match(globs, rel):
    return any(glob_to_regex(g).match(rel) for g in globs)


def _clean_windows(path_text):
    """Drop a Windows extended-length prefix and an NTFS alternate-data-stream suffix (.env::$DATA)."""
    if path_text.startswith("\\\\?\\"):
        path_text = path_text[4:]
    drive, rest = os.path.splitdrive(path_text)
    head, tail = os.path.split(rest)
    if ":" in tail:
        tail = tail.split(":", 1)[0]
    return drive + os.path.join(head, tail) if tail else path_text


def relative_path(path_text, project):
    """Project-relative path with forward slashes; the absolute path when outside the project."""
    if _NT:
        path_text = _clean_windows(path_text)
    full = os.path.normpath(os.path.join(project, path_text))
    try:
        rel = os.path.relpath(full, project)
    except ValueError:  # a different drive on Windows
        rel = full
    rel = rel.replace("\\", "/")
    if rel == ".." or rel.startswith("../"):
        rel = full.replace("\\", "/")
    return rel


def path_forms(path_text, project):
    """Forms of a path to test: as written, and with symlinks, junctions and short names resolved."""
    forms = [relative_path(path_text, project)]
    try:
        full = os.path.normpath(os.path.join(project, path_text))
        resolved = relative_path(os.path.realpath(full), os.path.realpath(project))
    except (OSError, ValueError):
        resolved = None
    if resolved and resolved not in forms:
        forms.append(resolved)
    return forms


def _collect(obj, keys):
    found, todo = [], [obj]
    while todo:  # iterative, so deep nesting cannot hit the recursion limit and fail open
        node = todo.pop()
        if isinstance(node, dict):
            for key, value in reversed(list(node.items())):
                if key in keys and isinstance(value, str):
                    found.append(value)
                elif key in keys and isinstance(value, list):
                    found.extend(v for v in value if isinstance(v, str))
                else:
                    todo.append(value)
        elif isinstance(node, list):
            todo.extend(reversed(node))
    return found


def collect_paths(tool_input):
    return _collect(tool_input, PATH_KEYS)


def collect_text(tool_input):
    """Only the new text being written (never old_string or what is on disk)."""
    return _collect(tool_input, TEXT_KEYS)


# --- validation ----------------------------------------------------------------------------

def _str_list(rule, key, required):
    value = rule.get(key)
    if value is None:
        return "is required" if required else None
    if not (isinstance(value, list) and all(isinstance(v, str) and v for v in value)):
        return "must be a list of non-empty strings"
    if required and not value:
        return "must not be empty"
    return None


_FIELDS = {
    "protected_path": (("globs", True), ("allow_globs", False)),
    "blocked_command": (("patterns", True), ("except_patterns", False)),
    "banned_content": (("patterns", True), ("globs", False)),
    "stop_check": (("when_changed_globs", False),),
}


def _nested_repeat(pattern):
    """True when an unbounded repeat contains another one, as in (a+)+ (catastrophic backtracking)."""
    try:
        parsed = _sre_parse.parse(pattern)
    except Exception:  # noqa: BLE001 - an invalid pattern is reported by re.compile
        return False

    def subs(value):
        if isinstance(value, _sre_parse.SubPattern):
            yield value
        elif isinstance(value, (tuple, list)):
            for item in value:
                yield from subs(item)

    def walk(node):
        for op, av in node:
            yield op, av
            for sub in subs(av):
                yield from walk(sub)

    repeats = (_sre_const.MAX_REPEAT, _sre_const.MIN_REPEAT)

    def unbounded(op, av):
        return op in repeats and av[1] == _sre_const.MAXREPEAT

    return any(unbounded(op, av) and any(unbounded(o, a) for o, a in walk(av[2]))
               for op, av in walk(parsed))


def _glob_problem(glob):
    """Why a glob would never match as its author expects, or None. Only * ** ? are supported."""
    if any(ch in glob for ch in "[]{}"):
        return "uses [ ] or { }, which are not supported (only *, ** and ?)"
    if glob.startswith(("./", "/", ".\\", "\\")):
        return "must be relative to the project, with no leading ./ or /"
    return None


def _validate_fields(label, rule, kind):
    errors = []
    for key, required in _FIELDS[kind]:
        problem = _str_list(rule, key, required)
        if problem:
            errors.append(f"{label}: {key} {problem}")
    if not errors:
        for key in GLOB_KEYS:
            for glob in rule.get(key) or []:
                problem = _glob_problem(glob)
                if problem:
                    errors.append(f"{label}: {key} glob {glob!r} {problem}")
        for key in ("patterns", "except_patterns"):
            for pattern in rule.get(key) or []:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    errors.append(f"{label}: {key} has an invalid regular expression {pattern!r} ({exc})")
                    continue
                if _nested_repeat(pattern):
                    errors.append(f"{label}: {key} pattern {pattern!r} may take exponential time "
                                  "(a repeated group that itself repeats); simplify it")
    if kind == "stop_check":
        if not (isinstance(rule.get("command"), str) and rule["command"].strip()):
            errors.append(f"{label}: command is required")
        timeout = rule.get("timeout_seconds")
        if timeout is not None and not (
            isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and 0 < timeout <= MAX_TIMEOUT
        ):
            errors.append(f"{label}: timeout_seconds must be a number from 1 to {MAX_TIMEOUT}")
    return errors


def validate_rules(data):
    if not isinstance(data, dict) or data.get("version") != 1:
        return ['rules.json must be an object with "version": 1']
    rules = data.get("rules")
    if not isinstance(rules, list):
        return ['"rules" must be a list']
    errors, seen = [], set()
    for number, rule in enumerate(rules, 1):
        label = f"rule {number}"
        if not isinstance(rule, dict):
            errors.append(f"{label}: must be an object")
            continue
        rule_id = rule.get("id")
        if isinstance(rule_id, str):
            label = f"rule {rule_id!r}"
        if not (isinstance(rule_id, str) and _ID.match(rule_id)):
            errors.append(f"{label}: id must be kebab-case")
        elif rule_id in seen:
            errors.append(f"{label}: duplicate id")
        else:
            seen.add(rule_id)
        kind = rule.get("type")
        if kind not in RULE_TYPES:
            errors.append(f"{label}: type must be one of {', '.join(RULE_TYPES)}")
            continue
        if not (isinstance(rule.get("message"), str) and rule["message"].strip()):
            errors.append(f"{label}: message is required")
        errors += _validate_fields(label, rule, kind)
        if "enabled" in rule and not isinstance(rule["enabled"], bool):
            errors.append(f"{label}: enabled must be true or false")
        if rule.get("enabled", True) is True:
            proof = rule.get("proof")
            if not (isinstance(proof, dict) and isinstance(proof.get("violation"), dict)
                    and isinstance(proof.get("pass"), dict)):
                errors.append(f"{label}: proof needs a violation and a pass payload")
    return errors


# --- rule checks ---------------------------------------------------------------------------

def _matches_any(patterns, text):
    return any(re.search(p, text, re.MULTILINE) for p in patterns)


def check_rule(rule, payload, project, simulate=False, deadline=None):
    """Return a short violation detail, or None when the payload is allowed."""
    event = payload.get("hook_event_name")
    kind = rule["type"]
    if kind == "stop_check":
        return _stop_check(rule, payload, project, simulate, deadline) if event == "Stop" else None
    if event != "PreToolUse":
        return None
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    if kind == "blocked_command":
        return _blocked_command(rule, tool, tool_input)
    if tool not in PATH_TOOLS:
        return None
    paths = [rel for p in collect_paths(tool_input) for rel in path_forms(p, project)]
    if kind == "protected_path":
        for rel in paths:
            if glob_match(rule["globs"], rel) and not glob_match(rule.get("allow_globs", []), rel):
                return f"path: {rel}"
        return None
    if kind == "banned_content":
        globs = rule.get("globs")
        if globs and not any(glob_match(globs, rel) for rel in paths):
            return None
        for text in collect_text(tool_input):
            if _matches_any(rule["patterns"], text):
                return "the new text matches a banned pattern"
    return None


def _strip_noise(command):
    """Remove what a shell never runs as a command: unquoted # comments and the body of a heredoc
    whose line has no shell or interpreter on it (for example the text of a commit message). A
    heredoc fed to bash, sh, python and the like is kept, because that text does run. A heredoc
    inside "$( ... )" is handled too, since that is how commit messages are usually written."""
    out, cur, pending = [], [], []
    state = {"i": 0, "line_start": 0}
    quote, n = None, len(command)

    def heredoc_here():
        i = state["i"]
        if not command.startswith("<<", i) or command.startswith("<<<", i):
            return False
        match = _HEREDOC.match(command, i)
        if not match:
            return False
        eol = command.find("\n", i)
        words = set(re.findall(r"[A-Za-z0-9_]+", command[state["line_start"]:n if eol == -1 else eol]))
        pending.append((match.group(1) or match.group(2) or match.group(3), bool(words & _INTERPRETERS)))
        out.append(match.group(0))
        cur.append(match.group(0))
        state["i"] = match.end()
        return True

    def newline_here():
        out.append("\n")
        i = state["i"] + 1
        while pending:
            delimiter, keep = pending.pop(0)
            while i < n:
                end = command.find("\n", i)
                end = n if end == -1 else end
                line = command[i:end]
                i = min(end + 1, n)
                if keep:
                    out.append(line + "\n")
                if line.strip() == delimiter:
                    break
        cur.clear()
        state["i"], state["line_start"] = i, i

    while state["i"] < n:
        i = state["i"]
        ch = command[i]
        if quote:
            if quote == '"' and heredoc_here():
                continue
            if ch == "\n":
                newline_here()
                continue
            out.append(ch)
            cur.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < n:
                out.append(command[i + 1])
                cur.append(command[i + 1])
                i += 1
            elif ch == quote:
                quote = None
            state["i"] = i + 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append(command[i:i + 2])
            cur.append(command[i:i + 2])
            state["i"] = i + 2
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            cur.append(ch)
            state["i"] = i + 1
            continue
        if ch == "#" and (not cur or cur[-1][-1] in " \t;&|("):
            while i < n and command[i] != "\n":
                i += 1
            state["i"] = i
            continue
        if heredoc_here():
            continue
        if ch == "\n":
            newline_here()
            continue
        out.append(ch)
        cur.append(ch)
        state["i"] = i + 1
    return "".join(out)


def split_segments(command):
    """Split a shell command into segments on &&, ||, ;, |, & and newlines (quotes respected)."""
    command = command.replace("\\\r\n", "").replace("\\\n", "")  # line continuations
    command = _strip_noise(command)
    segments, buf, quote, i = [], [], None, 0
    while i < len(command):
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(command):
                buf.append(command[i + 1])
                i += 1
            elif ch == quote:
                quote = None
        elif ch == "\\" and i + 1 < len(command):
            buf.append(ch)
            buf.append(command[i + 1])
            i += 1
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif command.startswith(("&&", "||"), i):
            segments.append("".join(buf))
            buf = []
            i += 1
        elif ch in ";|&\n":
            segments.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return [s.strip() for s in segments if s.strip()]


def _blocked_command(rule, tool, tool_input):
    if tool != "Bash":
        return None
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    for segment in split_segments(command):
        if _matches_any(rule["patterns"], segment) and not _matches_any(rule.get("except_patterns", []), segment):
            return f"command: {segment}"
    return None


def _git_output(args, project):
    try:
        done = subprocess.run(["git", *args], cwd=project, capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", errors="replace")


def _changed_paths(project):
    """Uncommitted changes relative to the project (renames list both paths), or None if git cannot tell."""
    prefix = _git_output(["rev-parse", "--show-prefix"], project)
    status = _git_output(["status", "--porcelain=v1", "-z", "-uall", "--", "."], project)
    if prefix is None or status is None:
        return None
    prefix = prefix.strip().replace("\\", "/")
    fields = status.split("\0")
    paths, i = [], 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        code, names = entry[:2], [entry[3:]]
        if "R" in code or "C" in code:  # a rename or copy: the original path follows
            if i < len(fields):
                names.append(fields[i])
                i += 1
        for name in names:
            name = name.replace("\\", "/")
            if prefix:
                if not name.startswith(prefix):
                    continue
                name = name[len(prefix):]
            paths.append(name)
    return paths


def _kill_tree(proc):
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.SubprocessError:
        pass


def _console_encoding():
    if os.name == "nt":
        try:
            import ctypes
            return f"cp{ctypes.windll.kernel32.GetOEMCP()}"
        except (AttributeError, ImportError, OSError):
            return "cp437"
    import locale
    return locale.getpreferredencoding(False) or "utf-8"


def _decode_output(data):
    """Command output as text: UTF-8 when it is valid, else the console's own code page."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode(_console_encoding(), errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def _run_command(command, project, timeout):
    """Run a shell command, killing its whole process tree on timeout. Returns (code, output) or None."""
    options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
               else {"start_new_session": True})
    with tempfile.TemporaryFile() as sink:
        proc = subprocess.Popen(
            command, shell=True, cwd=project, stdin=subprocess.DEVNULL,
            stdout=sink, stderr=subprocess.STDOUT, **options,
        )
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc)
            return None
        sink.seek(0)
        return proc.returncode, _decode_output(sink.read())


def _stop_check(rule, payload, project, simulate, deadline=None):
    if payload.get("stop_hook_active"):
        return None
    remaining = None if deadline is None else deadline - time.monotonic()
    if remaining is not None and remaining <= 0 and not (simulate and "simulate_exit" in payload):
        print(f"[rule_hook] stop check {rule['id']} skipped: the Stop hook's time budget is used up; "
              "allowing the stop", file=sys.stderr)
        return None
    if simulate and "simulate_exit" in payload:
        return "the check failed (simulated)" if payload["simulate_exit"] else None
    globs = rule.get("when_changed_globs")
    if globs:
        changed = _changed_paths(project)
        if changed is not None and not any(glob_match(globs, p) for p in changed):
            return None
    command = rule["command"]
    timeout = rule.get("timeout_seconds", 120)
    if remaining is not None:
        timeout = min(timeout, remaining)
    result = _run_command(command, project, timeout)
    if result is None:
        why = " (the shared Stop-hook budget ran out)" if remaining is not None and timeout == remaining else ""
        print(f"[rule_hook] stop check {rule['id']} timed out{why}; allowing the stop", file=sys.stderr)
        return None
    code, output = result
    if code == 0:
        return None
    tail = "\n".join(output.splitlines()[-20:])[-2000:]
    return f"`{command}` exited {code}:\n{tail}"


# --- evaluation, output, CLI ---------------------------------------------------------------

def project_dir(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def _read_rules_data(path):
    path = Path(path)
    if not path.is_file():
        raise RulesError(f"rules file not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise RulesError(f"{path} is not valid JSON ({exc})") from None


def split_rules(data):
    """(valid rules, problems). Each rule is validated on its own; a later duplicate id is a problem."""
    if not isinstance(data, dict) or data.get("version") != 1:
        raise RulesError('rules.json must be an object with "version": 1')
    rules = data.get("rules")
    if not isinstance(rules, list):
        raise RulesError('"rules" must be a list')
    good, problems, seen = [], [], set()
    for rule in rules:
        errors = validate_rules({"version": 1, "rules": [rule]})
        rule_id = rule.get("id") if isinstance(rule, dict) else None
        if not errors and rule_id in seen:
            errors = [f"rule {rule_id!r}: duplicate id"]
        if errors:
            problems += errors
        else:
            good.append(rule)
            seen.add(rule_id)
    return good, problems


def load_rules(path, strict=True):
    """strict: the valid rules, or RulesError if any rule is invalid. lenient: (valid rules, problems)."""
    good, problems = split_rules(_read_rules_data(path))
    if strict:
        if problems:
            raise RulesError("; ".join(problems))
        return good
    return good, problems


def evaluate(payload, rules, project, simulate=False):
    """The first enabled rule that the payload violates, as (rule, detail), else None."""
    deadline = time.monotonic() + TOTAL_STOP_BUDGET if payload.get("hook_event_name") == "Stop" else None
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        detail = check_rule(rule, payload, project, simulate, deadline)
        if detail is not None:
            return rule, detail
    return None


def decision(payload, rule, detail):
    source = f" (from {rule['source']})" if rule.get("source") else ""
    reason = f"Rule {rule['id']}: {rule['message']}{source}"
    if payload.get("hook_event_name") == "Stop":
        return {"decision": "block", "reason": f"{reason}\n{detail}"}
    reason = f"{reason} [{detail}]"
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def run_check(stream):
    raw = stream.read()
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("the hook payload must be a JSON object")
    project = project_dir(payload)
    rules, problems = load_rules(Path(project) / ".claude" / "rules.json", strict=False)
    hit = evaluate(payload, rules, project)
    for problem in problems:
        print(f"[rule_hook] {problem}", file=sys.stderr)
    if hit:
        print(json.dumps(decision(payload, *hit)))
        return 0
    return 1 if problems else 0


def run_selftest(rules_path=None):
    project = project_dir({})
    path = Path(rules_path) if rules_path else Path(project) / ".claude" / "rules.json"
    try:
        rules = load_rules(path)
    except RulesError as exc:
        for problem in str(exc).split("; "):
            print(f"INVALID  {problem}")
        return 1
    failed = 0
    for rule in rules:
        if not rule.get("enabled", True):
            print(f"SKIP  {rule['id']} (disabled)")
            continue
        proof = rule["proof"]
        blocked = evaluate(proof["violation"], [rule], project, simulate=True)
        allowed = evaluate(proof["pass"], [rule], project, simulate=True) is None
        if blocked is not None and allowed:
            print(f"PASS  {rule['id']}")
        else:
            failed += 1
            print(
                f"FAIL  {rule['id']} (violation {'blocked' if blocked else 'NOT blocked'}, "
                f"pass {'allowed' if allowed else 'BLOCKED'})"
            )
    return 1 if failed else 0


def main(argv=None):
    import argparse

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="rule_hook.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="hook entry point (payload on stdin)")
    selftest = sub.add_parser("selftest", help="prove every rule blocks its violation and allows its pass")
    selftest.add_argument("--rules", help="path to rules.json (default: <project>/.claude/rules.json)")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "check":
            return run_check(sys.stdin.buffer)
        return run_selftest(args.rules)
    except Exception as exc:  # noqa: BLE001 - fail open: a broken engine must not block every tool call
        print(f"[rule_hook] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
