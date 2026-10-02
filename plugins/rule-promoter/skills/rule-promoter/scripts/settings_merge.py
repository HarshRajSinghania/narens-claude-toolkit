#!/usr/bin/env python3
"""Install helper for rule-promoter: pick a working Python launcher and merge hook entries
into .claude/settings.json without touching anything else. Standard library only.

    python settings_merge.py launcher --script PATH [--rules PATH]
    python settings_merge.py plan  --settings PATH --launcher "python3" [--pretool] [--stop] [--shell-form]
    python settings_merge.py apply --settings PATH --launcher "python3" [--pretool] [--stop] [--shell-form]
"""
import argparse
import difflib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = "rule_hook.py"
_OURS = re.compile(r"\.claude/hooks/rule_hook\.py")
SCRIPT_ARG = "${CLAUDE_PROJECT_DIR}/.claude/hooks/rule_hook.py"
PRETOOL_MATCHER = "Edit|Write|MultiEdit|NotebookEdit|Bash"
CANDIDATES = ("python3", "python", "py -3")


class SettingsError(Exception):
    """The settings file cannot be merged safely."""


def build_groups(launcher, pretool, stop, shell_form=False):
    command, *prefix = launcher

    def hook(timeout):
        if shell_form:
            line = " ".join(launcher) + ' "$CLAUDE_PROJECT_DIR/.claude/hooks/rule_hook.py" check'
            return {"type": "command", "command": line, "timeout": timeout}
        return {"type": "command", "command": command,
                "args": prefix + [SCRIPT_ARG, "check"], "timeout": timeout}

    def group(matcher, timeout):
        built = {"hooks": [hook(timeout)]}
        return {"matcher": matcher, **built} if matcher else built

    groups = {}
    if pretool:
        groups["PreToolUse"] = [group(PRETOOL_MATCHER, 5)]
    if stop:
        groups["Stop"] = [group(None, 300)]
    return groups


def _is_ours(hook):
    """True only for a hook entry that runs this project's .claude/hooks/rule_hook.py."""
    if not isinstance(hook, dict):
        return False
    text = " ".join([str(hook.get("command", ""))] + [str(a) for a in hook.get("args", []) or []])
    return bool(_OURS.search(text.replace("\\", "/")))


def merge(settings, groups):
    result = json.loads(json.dumps(settings))
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SettingsError('"hooks" in settings.json must be an object')
    for event in list(hooks):
        if not isinstance(hooks[event], list):
            raise SettingsError(f"hooks.{event} in settings.json must be a list")
        kept_groups = []
        for group in hooks[event]:
            if not isinstance(group, dict) or "hooks" not in group:
                kept_groups.append(group)
                continue
            if not isinstance(group["hooks"], list):
                raise SettingsError(f"a hooks.{event} group in settings.json has a non-list \"hooks\" value")
            remaining = [h for h in group["hooks"] if not _is_ours(h)]
            if len(remaining) == len(group["hooks"]):
                kept_groups.append(group)       # none of ours: untouched
            elif remaining:
                kept_groups.append({**group, "hooks": remaining})  # keep the rest of the group
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    for event, new_groups in groups.items():
        hooks.setdefault(event, []).extend(new_groups)
    if not hooks:
        del result["hooks"]
    return result


def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise ValueError(f"duplicate key {key!r}")
        seen[key] = value
    return seen


def raw_text(path):
    return Path(path).read_bytes().decode("utf-8-sig")


def load_settings(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(raw_text(path), object_pairs_hook=_no_duplicates)
    except ValueError as exc:
        raise SettingsError(f"{path} is not valid JSON ({exc}); fix it first") from None
    if not isinstance(data, dict):
        raise SettingsError(f"{path} must contain a JSON object")
    return data


def render(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _merged(path, launcher, pretool, stop, shell_form=False):
    return merge(load_settings(path), build_groups(launcher, pretool, stop, shell_form))


def plan(path, launcher, pretool, stop, shell_form=False):
    after = render(_merged(path, launcher, pretool, stop, shell_form))
    before = raw_text(path) if Path(path).exists() else ""
    if before == after:
        return "No changes: settings.json already has these hook entries.\n"
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=str(path), tofile=str(path) + " (after)"))


def apply(path, launcher, pretool, stop, shell_form=False):
    """Write the merged settings atomically. Returns True if the file changed."""
    path = Path(path)
    before = path.read_bytes() if path.exists() else None
    after = render(_merged(path, launcher, pretool, stop, shell_form)).encode("utf-8")
    if before == after:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(after)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True


def find_launcher(script, rules=None):
    for candidate in CANDIDATES:
        cmd = shlex.split(candidate) + [script, "selftest"] + (["--rules", rules] if rules else [])
        try:
            done = subprocess.run(cmd, capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0:
            return candidate
    return None


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="settings_merge.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    launch = sub.add_parser("launcher", help="print the first Python launcher that runs rule_hook.py selftest")
    launch.add_argument("--script", required=True)
    launch.add_argument("--rules")
    for name in ("plan", "apply"):
        p = sub.add_parser(name)
        p.add_argument("--settings", required=True)
        p.add_argument("--launcher", required=True)
        p.add_argument("--pretool", action="store_true")
        p.add_argument("--stop", action="store_true")
        p.add_argument("--shell-form", action="store_true",
                       help="write the hook as one shell command (for Claude Code versions without exec-form args)")
    args = parser.parse_args(argv)
    if args.cmd == "launcher":
        found = find_launcher(args.script, args.rules)
        if found is None:
            print("No working Python launcher found (tried python3, python, py -3).", file=sys.stderr)
            return 1
        print(found)
        return 0
    if not (args.pretool or args.stop):
        print("error: pass --pretool and/or --stop", file=sys.stderr)
        return 2
    launcher = shlex.split(args.launcher)
    try:
        if args.cmd == "plan":
            print(plan(args.settings, launcher, args.pretool, args.stop, args.shell_form), end="")
        else:
            changed = apply(args.settings, launcher, args.pretool, args.stop, args.shell_form)
            print("settings.json updated." if changed else "No changes: settings.json already up to date.")
    except SettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
