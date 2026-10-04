"""Shared test fixtures. Importing this module puts scripts/ on sys.path."""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def write_plugin(
    root,
    name,
    *,
    plugin_json_name=None,
    author="Naren",
    skill_dir=None,
    skill_name=None,
    skill_description="Use when testing things.",
    readme=True,
    with_skill=True,
):
    plugin = Path(root) / "plugins" / name
    (plugin / ".claude-plugin").mkdir(parents=True)
    meta = {
        "name": plugin_json_name or name,
        "version": "0.1.0",
        "description": f"Does {name} things.",
        "author": {"name": author},
    }
    (plugin / ".claude-plugin" / "plugin.json").write_text(json.dumps(meta), encoding="utf-8")
    if with_skill:
        sdir = plugin / "skills" / (skill_dir or name)
        sdir.mkdir(parents=True)
        (sdir / "SKILL.md").write_text(
            f"---\nname: {skill_name or skill_dir or name}\n"
            f"description: {skill_description}\n---\n\n# {name}\n",
            encoding="utf-8",
        )
    if readme:
        (plugin / "README.md").write_text(f"# {name}\n", encoding="utf-8")
    return plugin


def add_mod_files(plugin, modules=("register.ts",), hooks_json=None):
    """Give a plugin folder a hooks/ directory: the module files and hooks.json."""
    hooks = Path(plugin) / "hooks"
    hooks.mkdir(exist_ok=True)
    for m in modules:
        (hooks / m).write_text("export const register = () => {};\n", encoding="utf-8")
    text = hooks_json if hooks_json is not None else json.dumps({"modules": [f"./{m}" for m in modules]})
    (hooks / "hooks.json").write_text(text, encoding="utf-8")


def write_mod(root, name, **kw):
    """A mod plugin: valid plugin.json and README, hooks/hooks.json, no skills/."""
    plugin = write_plugin(root, name, with_skill=False)
    add_mod_files(plugin, **kw)
    return plugin


def write_server(root, name, *, readme=None, manifest="package.json"):
    sdir = Path(root) / "servers" / name
    sdir.mkdir(parents=True)
    text = readme if readme is not None else f"# {name}\n\n> Does {name} things.\n"
    (sdir / "README.md").write_text(text, encoding="utf-8")
    if manifest:
        (sdir / manifest).write_text("{}\n", encoding="utf-8")
    return sdir


def write_marketplace(root, names, *, owner="Naren"):
    d = Path(root) / ".claude-plugin"
    d.mkdir(exist_ok=True)
    data = {
        "name": "narens-claude-toolkit",
        "owner": {"name": owner},
        "plugins": [
            {"name": n, "source": f"./plugins/{n}", "description": f"Does {n} things."}
            for n in names
        ],
    }
    (d / "marketplace.json").write_text(json.dumps(data), encoding="utf-8")


def edit_plugin_json(root, name, fn):
    path = Path(root) / "plugins" / name / ".claude-plugin" / "plugin.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    fn(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def make_valid_repo(root, names, *, mods=(), servers=()):
    """A repo that passes every check, including a current catalog."""
    import build_catalog  # imported late: scripts/ must be on sys.path first

    for n in names:
        write_plugin(root, n)
    for n in mods:
        write_mod(root, n)
    for n in servers:
        write_server(root, n)
    write_marketplace(root, list(names) + list(mods))
    (Path(root) / "README.md").write_text(
        "# Test\n\n<!-- CATALOG:START -->\nold\n<!-- CATALOG:END -->\n\nfooter\n",
        encoding="utf-8",
    )
    build_catalog.build(root)
