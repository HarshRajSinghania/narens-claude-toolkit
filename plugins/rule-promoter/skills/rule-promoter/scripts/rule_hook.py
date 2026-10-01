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
import subprocess
import sys
from pathlib import Path

RULE_TYPES = ("protected_path", "blocked_command", "banned_content", "stop_check")
PATH_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
PATH_KEYS = ("file_path", "notebook_path")
TEXT_KEYS = ("content", "file_content", "new_string", "new_content", "new_source")
_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_NT = os.name == "nt"


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
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE if _NT else 0)


def glob_match(globs, rel):
    return any(glob_to_regex(g).match(rel) for g in globs)


def relative_path(path_text, project):
    """Project-relative path with forward slashes; the absolute path when outside the project."""
    full = os.path.normpath(os.path.join(project, path_text))
    try:
        rel = os.path.relpath(full, project)
    except ValueError:  # a different drive on Windows
        rel = full
    rel = rel.replace("\\", "/")
    if rel == ".." or rel.startswith("../"):
        rel = full.replace("\\", "/")
    return rel


def _collect(obj, keys):
    found = []

    def visit(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in keys and isinstance(value, str):
                    found.append(value)
                elif key in keys and isinstance(value, list):
                    found.extend(v for v in value if isinstance(v, str))
                else:
                    visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(obj)
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


def _validate_fields(label, rule, kind):
    errors = []
    for key, required in _FIELDS[kind]:
        problem = _str_list(rule, key, required)
        if problem:
            errors.append(f"{label}: {key} {problem}")
    if not errors:
        for key in ("patterns", "except_patterns"):
            for pattern in rule.get(key) or []:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    errors.append(f"{label}: {key} has an invalid regular expression {pattern!r} ({exc})")
    if kind == "stop_check":
        if not (isinstance(rule.get("command"), str) and rule["command"].strip()):
            errors.append(f"{label}: command is required")
        timeout = rule.get("timeout_seconds")
        if timeout is not None and not (
            isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0
        ):
            errors.append(f"{label}: timeout_seconds must be a positive number")
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
        if rule.get("enabled", True):
            proof = rule.get("proof")
            if not (isinstance(proof, dict) and isinstance(proof.get("violation"), dict)
                    and isinstance(proof.get("pass"), dict)):
                errors.append(f"{label}: proof needs a violation and a pass payload")
    return errors


# --- rule checks ---------------------------------------------------------------------------

def _matches_any(patterns, text):
    return any(re.search(p, text) for p in patterns)


def check_rule(rule, payload, project, simulate=False):
    """Return a short violation detail, or None when the payload is allowed."""
    event = payload.get("hook_event_name")
    kind = rule["type"]
    if kind == "stop_check":
        return _stop_check(rule, payload, project, simulate) if event == "Stop" else None
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
    paths = [relative_path(p, project) for p in collect_paths(tool_input)]
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


def split_segments(command):
    """Split a shell command into segments on &&, ||, ;, |, & and newlines (quotes respected)."""
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


def _changed_paths(project):
    """Changed paths from `git status --porcelain`, or None when git cannot tell."""
    try:
        done = subprocess.run(
            ["git", "status", "--porcelain", "-uall"], cwd=project, capture_output=True,
            encoding="utf-8", errors="replace", timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    paths = []
    for line in done.stdout.splitlines():
        entry = line[3:]
        if " -> " in entry:
            entry = entry.split(" -> ")[-1]
        paths.append(entry.strip().strip('"').replace("\\", "/"))
    return paths


def _stop_check(rule, payload, project, simulate):
    if payload.get("stop_hook_active"):
        return None
    if simulate and "simulate_exit" in payload:
        return "the check failed (simulated)" if payload["simulate_exit"] else None
    globs = rule.get("when_changed_globs")
    if globs:
        changed = _changed_paths(project)
        if changed is not None and not any(glob_match(globs, p) for p in changed):
            return None
    command = rule["command"]
    try:
        done = subprocess.run(
            command, shell=True, cwd=project, capture_output=True, encoding="utf-8",
            errors="replace", timeout=rule.get("timeout_seconds", 120),
        )
    except subprocess.TimeoutExpired:
        print(f"[rule_hook] stop check {rule['id']} timed out; allowing the stop", file=sys.stderr)
        return None
    if done.returncode == 0:
        return None
    tail = "\n".join((done.stdout + done.stderr).splitlines()[-20:])[-2000:]
    return f"`{command}` exited {done.returncode}:\n{tail}"