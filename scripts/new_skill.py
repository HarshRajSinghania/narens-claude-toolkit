"""Create a new skill plugin from template/ and register it.

Usage: python scripts/new_skill.py <kebab-name> "Use when ..."
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_catalog  # noqa: E402
import common  # noqa: E402

NAME_TOKEN = "__SKILL_NAME__"
DESC_TOKEN = "__DESCRIPTION__"


def create(root, name, description):
    root = Path(root)
    if not common.KEBAB.match(name):
        raise ValueError(f"name {name!r} must be kebab-case")
    if not description.startswith("Use when") or "\n" in description:
        raise ValueError("description must be a single line starting with 'Use when'")
    dest = root / "plugins" / name
    if dest.exists():
        raise FileExistsError(f"{dest} already exists")

    shutil.copytree(root / "template", dest)
    (dest / "skills" / NAME_TOKEN).rename(dest / "skills" / name)
    for f in dest.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix == ".json":
            desc = json.dumps(description)[1:-1]
        elif f.name == "SKILL.md":
            desc = json.dumps(description, ensure_ascii=False)  # valid YAML double-quoted scalar
        else:
            desc = description
        text = common.read_text(f).replace(NAME_TOKEN, name).replace(DESC_TOKEN, desc)
        common.write_text(f, text)

    mkt_path = root / ".claude-plugin" / "marketplace.json"
    mkt = common.load_json(mkt_path)
    mkt.setdefault("plugins", []).append(
        {"name": name, "source": f"./plugins/{name}", "description": description}
    )
    common.write_text(mkt_path, json.dumps(mkt, indent=2, ensure_ascii=False) + "\n")
    build_catalog.build(root)
    return dest


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print('usage: python scripts/new_skill.py <kebab-name> "Use when ..."', file=sys.stderr)
        return 2
    try:
        dest = create(common.REPO_ROOT, args[0], args[1])
    except (ValueError, FileExistsError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 1
    print(f"Created {dest}. Now edit SKILL.md and README.md, then run validate.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
