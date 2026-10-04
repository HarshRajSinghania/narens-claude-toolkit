"""Generate the README catalog (skills, mods, MCP servers) and llms.txt from the repo contents.

Usage:
    python scripts/build_catalog.py            # rewrite README.md and llms.txt
    python scripts/build_catalog.py --check    # exit 1 if they are out of date
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

START = "<!-- CATALOG:START -->"
END = "<!-- CATALOG:END -->"
REGEN_HINT = "run `python scripts/build_catalog.py`"


SECTIONS = (("skills", "Skills"), ("mods", "Mods"), ("servers", "MCP servers"))
COMING_SOON = "_Coming soon._"


def collect(root):
    groups = {"skills": [], "mods": [], "servers": []}
    for pdir in common.list_plugin_dirs(root):
        meta = common.load_json(pdir / ".claude-plugin" / "plugin.json")
        item = {"name": meta["name"], "description": meta["description"]}
        kinds = common.plugin_kinds(pdir)
        if "skill" in kinds:
            groups["skills"].append(item)
        if "mod" in kinds:
            groups["mods"].append(item)
    for sdir in common.list_server_dirs(root):
        groups["servers"].append(
            {"name": sdir.name, "description": common.server_description(sdir) or ""}
        )
    return groups


def _cell(text):
    return " ".join(text.replace("|", "\\|").split())


def render_plugin_table(items, label):
    if not items:
        return COMING_SOON
    lines = [f"| {label} | What it does | Install |", "| --- | --- | --- |"]
    for it in items:
        n = it["name"]
        lines.append(
            f"| [`{n}`](plugins/{n}/README.md) | {_cell(it['description'])} | "
            f"`/plugin install {n}@{common.MARKETPLACE}` |"
        )
    return "\n".join(lines)


def render_server_table(items):
    if not items:
        return COMING_SOON
    lines = ["| Server | What it does | Folder |", "| --- | --- | --- |"]
    for it in items:
        n = it["name"]
        lines.append(
            f"| [`{n}`](servers/{n}/README.md) | {_cell(it['description'])} | "
            f"[`servers/{n}`](servers/{n}) |"
        )
    return "\n".join(lines)


def render_catalog(groups):
    return "\n\n".join(
        [
            "### Skills\n\n" + render_plugin_table(groups["skills"], "Skill"),
            "### Mods\n\n" + render_plugin_table(groups["mods"], "Mod"),
            "### MCP servers\n\n" + render_server_table(groups["servers"]),
        ]
    )


def render_llms(groups):
    lines = [
        "# Naren's Claude Toolkit",
        "",
        "> Original Claude Code skills, mods and MCP servers by Naren. Install plugins through the "
        f"plugin marketplace `{common.GITHUB_USER}/{common.MARKETPLACE}`.",
        "",
    ]
    for key, heading in SECTIONS:
        lines += [f"## {heading}", ""]
        items = groups[key]
        if not items:
            lines += ["- Coming soon.", ""]
            continue
        folder = "servers" if key == "servers" else "plugins"
        for it in items:
            n = it["name"]
            url = f"{common.REPO_URL}/blob/main/{folder}/{n}/README.md"
            lines.append(f"- [{n}]({url}): {_cell(it['description'])}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def replace_between(text, new):
    s = text.find(START)
    e = text.find(END)
    if s == -1 or e == -1 or e < s:
        raise ValueError(f"missing {START} / {END} markers")
    return text[: s + len(START)] + "\n" + new + "\n" + text[e:]


def check_outputs(root):
    root = Path(root)
    errors = []
    items = collect(root)
    readme = root / "README.md"
    if not readme.is_file():
        errors.append("README.md: missing")
    else:
        try:
            text = common.read_text(readme)
            expected = replace_between(text, render_catalog(items))
        except UnicodeDecodeError as exc:
            errors.append(f"README.md: unreadable ({exc})")
        except ValueError as exc:
            errors.append(f"README.md: {exc}")
        else:
            if expected != text:
                errors.append(f"README.md: catalog is out of date; {REGEN_HINT}")
    llms = root / "llms.txt"
    try:
        llms_current = llms.is_file() and common.read_text(llms) == render_llms(items)
    except UnicodeDecodeError:
        llms_current = False
    if not llms_current:
        errors.append(f"llms.txt: missing or out of date; {REGEN_HINT}")
    return errors


def build(root):
    root = Path(root)
    items = collect(root)
    readme = root / "README.md"
    common.write_text(readme, replace_between(common.read_text(readme), render_catalog(items)))
    common.write_text(root / "llms.txt", render_llms(items))


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    check = "--check" in args
    args = [a for a in args if a != "--check"]
    root = Path(args[0]) if args else common.REPO_ROOT
    if check:
        errors = check_outputs(root)
        for err in errors:
            print(f"ERROR {err}", file=sys.stderr)
        return 1 if errors else 0
    build(root)
    print("Catalog and llms.txt updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
