"""Shared constants and helpers for the repo tooling. Standard library only."""
import json
import re
from pathlib import Path

OWNER_NAME = "Naren"
GITHUB_USER = "NarenDawar"
MARKETPLACE = "narens-claude-toolkit"
REPO_URL = f"https://github.com/{GITHUB_USER}/{MARKETPLACE}"
REPO_ROOT = Path(__file__).resolve().parent.parent

KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _unquote(value):
    if value[0] == '"':
        try:
            return json.loads(value)
        except ValueError:
            pass
    return value[1:-1]


def parse_frontmatter(text, raw=False):
    """Parse simple single-line `key: value` YAML frontmatter.

    Quoted values are unquoted (double quotes are JSON-unescaped) unless raw=True.
    Returns {} when there is no frontmatter or it is not terminated.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    data = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return data
        if ":" in line and not line.startswith((" ", "\t")):
            key, _, value = line.partition(":")
            value = value.strip()
            if not raw and len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = _unquote(value)
            data[key.strip()] = value
    return {}


def read_text(path):
    """Read UTF-8, dropping a BOM; universal newlines turn CRLF into LF."""
    return Path(path).read_text(encoding="utf-8-sig")


def write_text(path, text):
    """Write UTF-8 with LF line endings on every platform."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def load_json(path):
    return json.loads(read_text(path))


def list_plugin_dirs(root):
    base = Path(root) / "plugins"
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir())


SERVER_MANIFESTS = ("package.json", "pyproject.toml")


def plugin_kinds(pdir):
    """The kinds a plugin has, by its contents: "skill" (a skills/ folder with at least one
    directory in it) and/or "mod" (hooks/hooks.json). plugin.json carries no type field."""
    pdir = Path(pdir)
    kinds = set()
    skills = pdir / "skills"
    if skills.is_dir() and any(p.is_dir() for p in skills.iterdir()):
        kinds.add("skill")
    if (pdir / "hooks" / "hooks.json").is_file():
        kinds.add("mod")
    return kinds


def list_server_dirs(root):
    base = Path(root) / "servers"
    if not base.is_dir():
        return []
    return sorted(p for p in base.iterdir() if p.is_dir())


def server_description(sdir):
    """The first README line that starts with '> ' (marker removed), or None."""
    try:
        text = read_text(Path(sdir) / "README.md")
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        if line.startswith("> "):
            description = line[2:].strip()
            if description:
                return description
    return None
