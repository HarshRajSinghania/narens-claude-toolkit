"""Validate repo conventions.

Usage: python scripts/validate.py [repo_root]
Exits 1 and prints one `ERROR <path>: <problem>` line per violation.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_catalog  # noqa: E402
import common  # noqa: E402


def check_skill(sdir, rel):
    where = f"{rel}/skills/{sdir.name}/SKILL.md"
    skill_md = sdir / "SKILL.md"
    if not skill_md.is_file():
        return [f"{where}: missing"]
    errors = []
    if not common.KEBAB.match(sdir.name):
        errors.append(f"{rel}/skills/{sdir.name}: directory name must be kebab-case")
    try:
        text = common.read_text(skill_md)
        fm = common.parse_frontmatter(text)
    except ValueError as exc:
        return errors + [f"{where}: unreadable ({exc})"]
    if not fm.get("name"):
        errors.append(f"{where}: frontmatter 'name' missing")
    elif fm["name"] != sdir.name:
        errors.append(
            f"{where}: name {fm['name']!r} must equal directory name {sdir.name!r}"
        )
    raw_desc = common.parse_frontmatter(text, raw=True).get("description", "")
    if raw_desc and raw_desc[0] not in "\"'" and (": " in raw_desc or " #" in raw_desc):
        errors.append(f"{where}: description contains ': ' or ' #'; wrap it in double quotes")
    desc = fm.get("description", "")
    if not desc:
        errors.append(f"{where}: frontmatter 'description' missing")
    elif not desc.startswith("Use when"):
        errors.append(f"{where}: description must be a single line starting with 'Use when'")
    return errors


def check_plugin(pdir):
    name = pdir.name
    rel = f"plugins/{name}"
    errors = []
    if not common.KEBAB.match(name):
        errors.append(f"{rel}: directory name must be kebab-case")
    pj = pdir / ".claude-plugin" / "plugin.json"
    pj_rel = f"{rel}/.claude-plugin/plugin.json"
    if not pj.is_file():
        errors.append(f"{pj_rel}: missing")
    else:
        try:
            meta = common.load_json(pj)
        except ValueError as exc:
            errors.append(f"{pj_rel}: invalid JSON ({exc})")
            meta = None
        if isinstance(meta, dict):
            if meta.get("name") != name:
                errors.append(
                    f"{pj_rel}: name {meta.get('name')!r} must equal directory name {name!r}"
                )
            for key in ("version", "description"):
                value = meta.get(key)
                if value is None:
                    errors.append(f"{pj_rel}: missing '{key}'")
                elif not isinstance(value, str) or not value.strip():
                    errors.append(f"{pj_rel}: '{key}' must be a non-empty string")
            author = meta.get("author")
            if not isinstance(author, dict) or author.get("name") != common.OWNER_NAME:
                errors.append(f"{pj_rel}: author.name must be '{common.OWNER_NAME}'")
        elif meta is not None:
            errors.append(f"{pj_rel}: must be a JSON object")
    if not (pdir / "README.md").is_file():
        errors.append(f"{rel}/README.md: missing")
    skills = pdir / "skills"
    skill_dirs = sorted(p for p in skills.iterdir() if p.is_dir()) if skills.is_dir() else []
    if not skill_dirs:
        errors.append(f"{rel}/skills: needs at least one skill directory")
    for sdir in skill_dirs:
        errors += check_skill(sdir, rel)
    return errors


def check_marketplace(root, plugin_dirs):
    where = ".claude-plugin/marketplace.json"
    path = Path(root) / ".claude-plugin" / "marketplace.json"
    if not path.is_file():
        return [f"{where}: missing"]
    try:
        data = common.load_json(path)
    except ValueError as exc:
        return [f"{where}: invalid JSON ({exc})"]
    if not isinstance(data, dict):
        return [f"{where}: must be a JSON object"]
    errors = []
    if data.get("name") != common.MARKETPLACE:
        errors.append(f"{where}: name must be '{common.MARKETPLACE}'")
    owner = data.get("owner")
    if not isinstance(owner, dict) or owner.get("name") != common.OWNER_NAME:
        errors.append(f"{where}: owner.name must be '{common.OWNER_NAME}'")
    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        errors.append(f"{where}: 'plugins' must be an array")
        plugins = []
    listed = set()
    for entry in plugins:
        if not isinstance(entry, dict):
            errors.append(f"{where}: plugin entries must be objects")
            continue
        name = entry.get("name")
        if name in listed:
            errors.append(f"{where}: duplicate plugin name {name!r}")
        listed.add(name)
        src = entry.get("source")
        expected = f"./plugins/{name}"
        if src != expected:
            errors.append(f"{where}: plugin {name!r} source {src!r} must be {expected!r}")
        elif not (Path(root) / src).is_dir():
            errors.append(f"{where}: plugin {name!r} source {src!r} does not exist")
    for pdir in plugin_dirs:
        if pdir.name not in listed:
            errors.append(f"{where}: plugin {pdir.name!r} is not listed")
    return errors


def validate(root):
    root = Path(root)
    plugin_dirs = common.list_plugin_dirs(root)
    errors = []
    for pdir in plugin_dirs:
        errors += check_plugin(pdir)
    errors += check_marketplace(root, plugin_dirs)
    if not errors:  # the catalog can only be rendered from valid plugin metadata
        errors += build_catalog.check_outputs(root)
    return errors


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path(args[0]) if args else common.REPO_ROOT
    errors = validate(root)
    for err in errors:
        print(f"ERROR {err}", file=sys.stderr)
    if errors:
        print(f"{len(errors)} problem(s) found", file=sys.stderr)
        return 1
    print("OK: all plugins valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
