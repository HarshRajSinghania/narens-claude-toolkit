"""Generate the README skill catalog and llms.txt from plugin metadata.

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


def collect(root):
    items = []
    for pdir in common.list_plugin_dirs(root):
        meta = common.load_json(pdir / ".claude-plugin" / "plugin.json")
        items.append({"name": meta["name"], "description": meta["description"]})
    return items


def _cell(text):
    return " ".join(text.replace("|", "\\|").split())


def render_table(items):
    if not items:
        return "_The first skills are on the way. Star the repo to follow along._"
    lines = ["| Skill | What it does | Install |", "| --- | --- | --- |"]
    for it in items:
        n = it["name"]
        lines.append(
            f"| [`{n}`](plugins/{n}/README.md) | {_cell(it['description'])} | "
            f"`/plugin install {n}@{common.MARKETPLACE}` |"
        )
    return "\n".join(lines)


def render_llms(items):
    lines = [
        "# Naren's Claude Skills",
        "",
        "> Original Claude Code skills and plugins by Naren. Install through the plugin "
        f"marketplace `{common.GITHUB_USER}/{common.MARKETPLACE}`.",
        "",
        "## Skills",
        "",
    ]
    if items:
        for it in items:
            n = it["name"]
            url = f"{common.REPO_URL}/blob/main/plugins/{n}/README.md"
            lines.append(f"- [{n}]({url}): {_cell(it['description'])}")
    else:
        lines.append("- Coming soon.")
    return "\n".join(lines) + "\n"


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
        text = common.read_text(readme)
        try:
            expected = replace_between(text, render_table(items))
        except ValueError as exc:
            errors.append(f"README.md: {exc}")
        else:
            if expected != text:
                errors.append(f"README.md: skill catalog is out of date; {REGEN_HINT}")
    llms = root / "llms.txt"
    if not llms.is_file() or common.read_text(llms) != render_llms(items):
        errors.append(f"llms.txt: missing or out of date; {REGEN_HINT}")
    return errors


def build(root):
    root = Path(root)
    items = collect(root)
    readme = root / "README.md"
    common.write_text(readme, replace_between(common.read_text(readme), render_table(items)))
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
