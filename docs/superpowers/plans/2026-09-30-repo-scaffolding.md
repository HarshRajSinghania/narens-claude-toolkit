# Naren's Claude Skills Repo Scaffolding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the public `narens-claude-skills` repo: marketplace metadata, validation and catalog tooling, a skill template, branded README and assets, and CI, so skills can be added one at a time afterwards.

**Architecture:** One Claude Code plugin per skill under `plugins/`, listed in `.claude-plugin/marketplace.json`. Two stdlib-only Python scripts enforce conventions (`validate.py`) and generate the README catalog and `llms.txt` (`build_catalog.py`). A `template/` directory plus `new_skill.py` create new skills that pass validation by construction. CI runs the unit tests and the validator.

**Tech Stack:** Python 3.9+ (standard library only, tests via `unittest`), JSON, Markdown, SVG, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-30-repo-scaffolding-design.md`

## Global Constraints

- Repo name `narens-claude-skills`; marketplace name `narens-claude-skills`; installs read `<plugin>@narens-claude-skills`.
- GitHub username `NarenDawar`; repo URL `https://github.com/NarenDawar/narens-claude-skills`.
- Author/owner name is `Naren` in `plugin.json` and `marketplace.json`.
- Skill and plugin names are kebab-case; the skill directory name equals the `name` frontmatter.
- `SKILL.md` requires `name` and `description`; the description is a single line starting with `Use when`.
- `SKILL.md` carries no branding footer. Branding lives in READMEs and metadata only.
- License is MIT.
- No third-party dependencies. Scripts and tests run with plain `python` (3.9+) from the repo root.
- Files are written with LF line endings and read tolerant of CRLF and a UTF-8 BOM (the repo is developed on Windows).
- The root README catalog table and `llms.txt` are generated; never edit them by hand between the markers.
- Do not create or push a remote GitHub repo (out of scope).
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- **CRLF line endings and a UTF-8 BOM** in `SKILL.md` or `plugin.json` (likely on Windows): parsed correctly, no false errors. Pinned in Task 1 (`test_crlf`, `test_read_text_strips_bom`) and Task 3 (`test_crlf_and_bom_files_are_valid`).
- **A `|` or newline inside a skill description**: must not break the README Markdown table. Pinned in Task 2 (`test_pipe_in_description_is_escaped`).
- **Malformed `plugin.json` or `marketplace.json`**: reported as a validation error naming the file, never a Python traceback. Pinned in Task 3 (`test_malformed_plugin_json`, `test_malformed_marketplace_json`).
- **Empty repo (no `plugins/` yet, which is the launch state)**: validation passes, and the catalog shows a placeholder instead of an empty table. Pinned in Task 3 (`test_empty_repo_is_valid`) and Task 2 (`test_empty_catalog_placeholder`).
- **Multi-line YAML description (`>` or `|`)**: gives a clear "single line starting with 'Use when'" error instead of passing silently. Pinned in Task 3 (`test_multiline_description_rejected`). Also: a description containing quotes and a colon survives `new_skill.py` into valid JSON, pinned in Task 4 (`test_description_with_quotes_and_colon`).

---

## File Structure

| File | Responsibility |
|---|---|
| `scripts/common.py` | Constants, kebab regex, frontmatter parser, tolerant file IO, plugin discovery |
| `scripts/validate.py` | Convention checks; `validate(root) -> list[str]`; CLI exit code |
| `scripts/build_catalog.py` | Render and write README catalog and `llms.txt`; `--check` mode |
| `scripts/new_skill.py` | Create a skill from `template/` and register it |
| `template/` | Skeleton plugin with `__SKILL_NAME__` / `__DESCRIPTION__` tokens |
| `tests/helpers.py` | `sys.path` setup and fixture builders |
| `tests/test_*.py` | Unit tests per script, plus a real-repo check |
| `.claude-plugin/marketplace.json` | Marketplace listing (empty `plugins` at launch) |
| `README.md`, `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `llms.txt`, `.gitignore`, `.gitattributes` | Root repo files |
| `assets/` | Logo mark, banner, social preview (SVG + PNG) |
| `.github/` | Issue/PR templates, CI workflow |
| `docs/conventions.md`, `docs/launch-checklist.md` | Contributor conventions; manual GitHub settings |

Run all tests with: `python -m unittest discover -s tests -v`

---

### Task 1: Shared library and test helpers

**Files:**
- Create: `scripts/common.py`
- Create: `tests/helpers.py`
- Test: `tests/test_common.py`

**Interfaces:**
- Produces (`common`): `OWNER_NAME="Naren"`, `GITHUB_USER="NarenDawar"`, `MARKETPLACE="narens-claude-skills"`, `REPO_URL`, `REPO_ROOT: Path`, `KEBAB: re.Pattern`, `parse_frontmatter(text: str) -> dict[str, str]`, `read_text(path) -> str`, `write_text(path, text) -> None`, `load_json(path) -> dict`, `list_plugin_dirs(root) -> list[Path]`.
- Produces (`helpers`): `REPO_ROOT`, `write_plugin(root, name, *, plugin_json_name=None, author="Naren", skill_dir=None, skill_name=None, skill_description="Use when testing things.", readme=True, with_skill=True) -> Path`, `write_marketplace(root, names, *, owner="Naren")`, `edit_plugin_json(root, name, fn)`, `make_valid_repo(root, names)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_common.py`:

```python
import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (sets sys.path)
import common


class ParseFrontmatter(unittest.TestCase):
    def test_basic(self):
        text = "---\nname: demo\ndescription: Use when testing.\n---\nbody"
        self.assertEqual(
            common.parse_frontmatter(text),
            {"name": "demo", "description": "Use when testing."},
        )

    def test_crlf(self):
        text = "---\r\nname: demo\r\ndescription: Use when x.\r\n---\r\nbody\r\n"
        self.assertEqual(
            common.parse_frontmatter(text),
            {"name": "demo", "description": "Use when x."},
        )

    def test_quoted_value_with_colon(self):
        text = '---\nname: demo\ndescription: "Use when a: b."\n---\n'
        self.assertEqual(common.parse_frontmatter(text)["description"], "Use when a: b.")

    def test_no_frontmatter(self):
        self.assertEqual(common.parse_frontmatter("# just a heading\n"), {})

    def test_unterminated_frontmatter(self):
        self.assertEqual(common.parse_frontmatter("---\nname: demo\n"), {})


class FileIO(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_read_text_strips_bom(self):
        p = self.root / "SKILL.md"
        p.write_bytes(b"\xef\xbb\xbf---\nname: x\n---\n")
        self.assertEqual(common.parse_frontmatter(common.read_text(p)), {"name": "x"})

    def test_write_text_uses_lf(self):
        p = self.root / "out.txt"
        common.write_text(p, "a\nb\n")
        self.assertEqual(p.read_bytes(), b"a\nb\n")

    def test_load_json_tolerates_bom(self):
        p = self.root / "x.json"
        p.write_bytes(b'\xef\xbb\xbf{"a": 1}')
        self.assertEqual(common.load_json(p), {"a": 1})


class Discovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_no_plugins_dir(self):
        self.assertEqual(common.list_plugin_dirs(self.root), [])

    def test_sorted_directories_only(self):
        (self.root / "plugins" / "beta").mkdir(parents=True)
        (self.root / "plugins" / "alpha").mkdir()
        (self.root / "plugins" / "notes.txt").write_text("x")
        names = [p.name for p in common.list_plugin_dirs(self.root)]
        self.assertEqual(names, ["alpha", "beta"])


class KebabCase(unittest.TestCase):
    def test_valid(self):
        for name in ("pdf-surgeon", "a", "tool2", "a-b-c"):
            self.assertTrue(common.KEBAB.match(name), name)

    def test_invalid(self):
        for name in ("Pdf", "a_b", "-a", "a-", "a--b", "", "a b"):
            self.assertFalse(common.KEBAB.match(name), name)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Create the helpers module (test infrastructure)**

Create `tests/helpers.py`:

```python
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


def write_marketplace(root, names, *, owner="Naren"):
    d = Path(root) / ".claude-plugin"
    d.mkdir(exist_ok=True)
    data = {
        "name": "narens-claude-skills",
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


def make_valid_repo(root, names):
    """A repo that passes every check, including a current catalog."""
    import build_catalog  # imported late: scripts/ must be on sys.path first

    for n in names:
        write_plugin(root, n)
    write_marketplace(root, names)
    (Path(root) / "README.md").write_text(
        "# Test\n\n<!-- CATALOG:START -->\nold\n<!-- CATALOG:END -->\n\nfooter\n",
        encoding="utf-8",
    )
    build_catalog.build(root)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m unittest tests.test_common -v` — if the dotted path fails, use `python -m unittest discover -s tests -p "test_common.py" -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'common'`

- [ ] **Step 4: Write the implementation**

Create `scripts/common.py`:

```python
"""Shared constants and helpers for the repo tooling. Standard library only."""
import json
import re
from pathlib import Path

OWNER_NAME = "Naren"
GITHUB_USER = "NarenDawar"
MARKETPLACE = "narens-claude-skills"
REPO_URL = f"https://github.com/{GITHUB_USER}/{MARKETPLACE}"
REPO_ROOT = Path(__file__).resolve().parent.parent

KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def parse_frontmatter(text):
    """Parse simple single-line `key: value` YAML frontmatter.

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
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -p "test_common.py" -v`
Expected: PASS (all tests in `test_common.py`)

- [ ] **Step 6: Commit**

```bash
git add scripts/common.py tests/helpers.py tests/test_common.py
git commit -m "feat: add shared tooling library and test helpers" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Catalog generator

(Built before the validator because the validator's final check calls it.)

**Files:**
- Create: `scripts/build_catalog.py`
- Test: `tests/test_build_catalog.py`

**Interfaces:**
- Consumes: `common.load_json`, `common.read_text`, `common.write_text`, `common.list_plugin_dirs`, `common.MARKETPLACE`, `common.GITHUB_USER`, `common.REPO_URL`, `common.REPO_ROOT`; `helpers.write_plugin`, `helpers.write_marketplace`, `helpers.edit_plugin_json`.
- Produces: `START`, `END` marker strings; `collect(root) -> list[dict]` (keys `name`, `description`); `render_table(items) -> str`; `render_llms(items) -> str`; `replace_between(text, new) -> str` (raises `ValueError` if markers are missing); `check_outputs(root) -> list[str]`; `build(root) -> None`; `main(argv=None) -> int`.

> Note: `tests/helpers.py::make_valid_repo` already imports `build_catalog.build`, so Task 1's helper starts working once this task lands.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_build_catalog.py`:

```python
import tempfile
import unittest
from pathlib import Path

import helpers
import build_catalog
import common


class RenderTable(unittest.TestCase):
    def test_empty_catalog_placeholder(self):
        out = build_catalog.render_table([])
        self.assertNotIn("| Skill |", out)
        self.assertIn("on the way", out)

    def test_table_rows(self):
        out = build_catalog.render_table([{"name": "alpha", "description": "Does alpha."}])
        self.assertIn("| Skill | What it does | Install |", out)
        self.assertIn(
            "| [`alpha`](plugins/alpha/README.md) | Does alpha. | "
            "`/plugin install alpha@narens-claude-skills` |",
            out,
        )

    def test_pipe_in_description_is_escaped(self):
        out = build_catalog.render_table([{"name": "alpha", "description": "a | b\nc"}])
        self.assertIn("a \\| b c", out)
        row = [l for l in out.splitlines() if "alpha" in l][0]
        # 3 columns => 4 unescaped pipes
        self.assertEqual(row.replace("\\|", "").count("|"), 4)


class RenderLlms(unittest.TestCase):
    def test_empty(self):
        out = build_catalog.render_llms([])
        self.assertTrue(out.startswith("# Naren's Claude Skills"))
        self.assertIn("Coming soon", out)
        self.assertTrue(out.endswith("\n"))

    def test_with_skills(self):
        out = build_catalog.render_llms([{"name": "alpha", "description": "Does alpha."}])
        self.assertIn(
            "- [alpha](https://github.com/NarenDawar/narens-claude-skills/blob/main/"
            "plugins/alpha/README.md): Does alpha.",
            out,
        )


class ReplaceBetween(unittest.TestCase):
    def test_replaces_content(self):
        text = "a\n<!-- CATALOG:START -->\nold\n<!-- CATALOG:END -->\nb\n"
        self.assertEqual(
            build_catalog.replace_between(text, "NEW"),
            "a\n<!-- CATALOG:START -->\nNEW\n<!-- CATALOG:END -->\nb\n",
        )

    def test_is_idempotent(self):
        text = "a\n<!-- CATALOG:START -->\nold\n<!-- CATALOG:END -->\nb\n"
        once = build_catalog.replace_between(text, "NEW")
        self.assertEqual(build_catalog.replace_between(once, "NEW"), once)

    def test_missing_markers(self):
        with self.assertRaises(ValueError):
            build_catalog.replace_between("no markers here", "NEW")


class BuildAndCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_build_then_check_clean(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        self.assertEqual(build_catalog.check_outputs(self.root), [])
        readme = common.read_text(self.root / "README.md")
        self.assertIn("`alpha`", readme)
        self.assertTrue((self.root / "llms.txt").is_file())

    def test_check_detects_stale_readme(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.write_plugin(self.root, "beta")
        errs = build_catalog.check_outputs(self.root)
        self.assertTrue(any("README.md" in e and "out of date" in e for e in errs), errs)
        self.assertTrue(any("llms.txt" in e for e in errs), errs)

    def test_check_reports_missing_markers(self):
        helpers.make_valid_repo(self.root, [])
        common.write_text(self.root / "README.md", "# no markers\n")
        errs = build_catalog.check_outputs(self.root)
        self.assertTrue(any("CATALOG" in e for e in errs), errs)

    def test_main_check_exit_codes(self):
        import contextlib
        import io

        helpers.make_valid_repo(self.root, ["alpha"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_catalog.main(["--check", str(self.root)]), 0)
            helpers.write_plugin(self.root, "beta")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(build_catalog.main(["--check", str(self.root)]), 1)
            self.assertEqual(build_catalog.main([str(self.root)]), 0)
            self.assertEqual(build_catalog.main(["--check", str(self.root)]), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_build_catalog.py" -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'build_catalog'`

- [ ] **Step 3: Write the implementation**

Create `scripts/build_catalog.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v`
Expected: PASS (`test_common` and `test_build_catalog`)

- [ ] **Step 5: Commit**

```bash
git add scripts/build_catalog.py tests/test_build_catalog.py
git commit -m "feat: add README catalog and llms.txt generator" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Validator

**Files:**
- Create: `scripts/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Consumes: `common.*` (see Task 1), `build_catalog.check_outputs(root) -> list[str]`; `helpers.make_valid_repo`, `write_plugin`, `write_marketplace`, `edit_plugin_json`.
- Produces: `validate(root) -> list[str]` (empty list means valid; each message names the offending path), `check_plugin(pdir) -> list[str]`, `check_skill(sdir, rel) -> list[str]`, `check_marketplace(root, plugin_dirs) -> list[str]`, `main(argv=None) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_validate.py`:

```python
import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
import common
import validate


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def errors(self):
        return validate.validate(self.root)

    def assertHasError(self, fragment):
        errs = self.errors()
        self.assertTrue(any(fragment in e for e in errs), errs)

    # --- happy paths -------------------------------------------------
    def test_valid_repo(self):
        helpers.make_valid_repo(self.root, ["alpha", "beta-tool"])
        self.assertEqual(self.errors(), [])

    def test_empty_repo_is_valid(self):
        helpers.make_valid_repo(self.root, [])
        self.assertEqual(self.errors(), [])

    def test_crlf_and_bom_files_are_valid(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        skill = self.root / "plugins/alpha/skills/alpha/SKILL.md"
        skill.write_bytes(
            b"\xef\xbb\xbf---\r\nname: alpha\r\ndescription: Use when testing things.\r\n---\r\n\r\n# alpha\r\n"
        )
        pj = self.root / "plugins/alpha/.claude-plugin/plugin.json"
        pj.write_bytes(b"\xef\xbb\xbf" + pj.read_bytes())
        self.assertEqual(self.errors(), [])

    # --- plugin.json -------------------------------------------------
    def test_plugin_name_mismatch(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.edit_plugin_json(self.root, "alpha", lambda d: d.update(name="other"))
        self.assertHasError("must equal directory name")

    def test_wrong_author(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.edit_plugin_json(self.root, "alpha", lambda d: d.update(author={"name": "Someone"}))
        self.assertHasError("author.name must be 'Naren'")

    def test_missing_description(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.edit_plugin_json(self.root, "alpha", lambda d: d.pop("description"))
        self.assertHasError("missing 'description'")

    def test_missing_version(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.edit_plugin_json(self.root, "alpha", lambda d: d.pop("version"))
        self.assertHasError("missing 'version'")

    def test_malformed_plugin_json(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/.claude-plugin/plugin.json").write_text("{not json")
        self.assertHasError("plugin.json: invalid JSON")

    def test_missing_plugin_json(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/.claude-plugin/plugin.json").unlink()
        self.assertHasError("plugin.json: missing")

    # --- plugin layout -----------------------------------------------
    def test_non_kebab_plugin_dir(self):
        helpers.make_valid_repo(self.root, ["BadName"])
        self.assertHasError("plugins/BadName: directory name must be kebab-case")

    def test_missing_plugin_readme(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/README.md").unlink()
        self.assertHasError("plugins/alpha/README.md: missing")

    def test_no_skills(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        shutil.rmtree(self.root / "plugins/alpha/skills")
        self.assertHasError("needs at least one skill directory")

    # --- SKILL.md ----------------------------------------------------
    def test_skill_name_mismatch(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/skills/alpha/SKILL.md").write_text(
            "---\nname: other\ndescription: Use when x.\n---\n"
        )
        self.assertHasError("must equal directory name")

    def test_missing_skill_md(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/skills/alpha/SKILL.md").unlink()
        self.assertHasError("skills/alpha/SKILL.md: missing")

    def test_missing_frontmatter_description(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/skills/alpha/SKILL.md").write_text("---\nname: alpha\n---\n")
        self.assertHasError("frontmatter 'description' missing")

    def test_description_must_start_with_use_when(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/skills/alpha/SKILL.md").write_text(
            "---\nname: alpha\ndescription: A cool tool.\n---\n"
        )
        self.assertHasError("starting with 'Use when'")

    def test_multiline_description_rejected(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/skills/alpha/SKILL.md").write_text(
            "---\nname: alpha\ndescription: >\n  Use when folded.\n---\n"
        )
        self.assertHasError("single line starting with 'Use when'")

    # --- marketplace.json --------------------------------------------
    def test_plugin_not_listed(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.write_marketplace(self.root, [])
        self.assertHasError("plugin 'alpha' is not listed")

    def test_listed_plugin_missing_on_disk(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.write_marketplace(self.root, ["alpha", "ghost"])
        self.assertHasError("'ghost' source './plugins/ghost' does not exist")

    def test_marketplace_wrong_owner(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.write_marketplace(self.root, ["alpha"], owner="Someone")
        self.assertHasError("owner.name must be 'Naren'")

    def test_malformed_marketplace_json(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / ".claude-plugin/marketplace.json").write_text("[oops")
        self.assertHasError("marketplace.json: invalid JSON")

    def test_missing_marketplace(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / ".claude-plugin/marketplace.json").unlink()
        self.assertHasError("marketplace.json: missing")

    # --- catalog freshness -------------------------------------------
    def test_stale_catalog(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.write_plugin(self.root, "gamma")
        helpers.write_marketplace(self.root, ["alpha", "gamma"])
        self.assertHasError("out of date")

    # --- CLI ---------------------------------------------------------
    def test_main_exit_codes(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(validate.main([str(self.root)]), 0)
        (self.root / "plugins/alpha/README.md").unlink()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(validate.main([str(self.root)]), 1)
        self.assertIn("ERROR plugins/alpha/README.md: missing", err.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_validate.py" -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'validate'`

- [ ] **Step 3: Write the implementation**

Create `scripts/validate.py`:

```python
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
        fm = common.parse_frontmatter(common.read_text(skill_md))
    except ValueError as exc:
        return errors + [f"{where}: unreadable ({exc})"]
    if not fm.get("name"):
        errors.append(f"{where}: frontmatter 'name' missing")
    elif fm["name"] != sdir.name:
        errors.append(
            f"{where}: name {fm['name']!r} must equal directory name {sdir.name!r}"
        )
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
                if not meta.get(key):
                    errors.append(f"{pj_rel}: missing '{key}'")
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
    listed = set()
    for entry in data.get("plugins", []):
        if not isinstance(entry, dict):
            errors.append(f"{where}: plugin entries must be objects")
            continue
        listed.add(entry.get("name"))
        src = entry.get("source")
        if not isinstance(src, str) or not (Path(root) / src).is_dir():
            errors.append(
                f"{where}: plugin {entry.get('name')!r} source {src!r} does not exist"
            )
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```bash
git add scripts/validate.py tests/test_validate.py
git commit -m "feat: add convention validator" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Skill template and `new_skill.py`

**Files:**
- Create: `template/.claude-plugin/plugin.json`
- Create: `template/README.md`
- Create: `template/skills/__SKILL_NAME__/SKILL.md`
- Create: `scripts/new_skill.py`
- Test: `tests/test_new_skill.py`

**Interfaces:**
- Consumes: `common.KEBAB`, `common.read_text`, `common.write_text`, `common.load_json`, `build_catalog.build(root)`, `validate.validate(root)`, `helpers.make_valid_repo`, `helpers.REPO_ROOT`.
- Produces: `new_skill.create(root, name, description) -> Path` (returns the new plugin dir; raises `ValueError` for a bad name/description, `FileExistsError` if the plugin exists), `new_skill.main(argv=None) -> int`. Tokens: `__SKILL_NAME__`, `__DESCRIPTION__`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_new_skill.py`:

```python
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
import common
import new_skill
import validate


class NewSkillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        helpers.make_valid_repo(self.root, [])
        shutil.copytree(helpers.REPO_ROOT / "template", self.root / "template")

    def test_created_skill_passes_validation(self):
        plugin = new_skill.create(self.root, "pdf-surgeon", "Use when editing PDF files.")
        self.assertEqual(plugin, self.root / "plugins" / "pdf-surgeon")
        self.assertTrue((plugin / "skills/pdf-surgeon/SKILL.md").is_file())
        self.assertEqual(validate.validate(self.root), [])

    def test_registers_in_marketplace_and_catalog(self):
        new_skill.create(self.root, "pdf-surgeon", "Use when editing PDF files.")
        data = common.load_json(self.root / ".claude-plugin/marketplace.json")
        self.assertEqual(
            data["plugins"],
            [
                {
                    "name": "pdf-surgeon",
                    "source": "./plugins/pdf-surgeon",
                    "description": "Use when editing PDF files.",
                }
            ],
        )
        self.assertIn("`pdf-surgeon`", common.read_text(self.root / "README.md"))

    def test_no_tokens_left_behind(self):
        plugin = new_skill.create(self.root, "pdf-surgeon", "Use when editing PDF files.")
        for f in plugin.rglob("*"):
            if f.is_file():
                text = common.read_text(f)
                self.assertNotIn("__SKILL_NAME__", text, f)
                self.assertNotIn("__DESCRIPTION__", text, f)

    def test_description_with_quotes_and_colon(self):
        desc = 'Use when a user says "fix it": quotes, colons & pipes | all fine.'
        new_skill.create(self.root, "quoty", desc)
        meta = common.load_json(self.root / "plugins/quoty/.claude-plugin/plugin.json")
        self.assertEqual(meta["description"], desc)
        self.assertEqual(validate.validate(self.root), [])

    def test_rejects_bad_name(self):
        with self.assertRaises(ValueError):
            new_skill.create(self.root, "Bad_Name", "Use when x.")

    def test_rejects_bad_description(self):
        with self.assertRaises(ValueError):
            new_skill.create(self.root, "good-name", "A cool tool.")

    def test_rejects_existing(self):
        new_skill.create(self.root, "pdf-surgeon", "Use when editing PDF files.")
        with self.assertRaises(FileExistsError):
            new_skill.create(self.root, "pdf-surgeon", "Use when editing PDF files.")

    def test_real_template_has_expected_files(self):
        t = helpers.REPO_ROOT / "template"
        self.assertTrue((t / ".claude-plugin/plugin.json").is_file())
        self.assertTrue((t / "README.md").is_file())
        self.assertTrue((t / "skills/__SKILL_NAME__/SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_new_skill.py" -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'new_skill'`

- [ ] **Step 3: Create the template files**

Create `template/.claude-plugin/plugin.json`:

```json
{
  "name": "__SKILL_NAME__",
  "version": "0.1.0",
  "description": "__DESCRIPTION__",
  "author": {
    "name": "Naren",
    "url": "https://github.com/NarenDawar"
  },
  "homepage": "https://github.com/NarenDawar/narens-claude-skills/tree/main/plugins/__SKILL_NAME__",
  "repository": "https://github.com/NarenDawar/narens-claude-skills",
  "license": "MIT",
  "keywords": ["claude-code", "claude-skills", "agent-skills"]
}
```

Create `template/skills/__SKILL_NAME__/SKILL.md`:

```markdown
---
name: __SKILL_NAME__
description: __DESCRIPTION__
---

# __SKILL_NAME__

## Overview

One or two sentences: what this skill does and the core principle behind it.

## When to Use

- Concrete trigger situations, symptoms, and phrasings.
- When NOT to use it.

## Process

1. Step one.
2. Step two.

## Common Mistakes

- What goes wrong and how to avoid it.
```

Create `template/README.md`:

````markdown
# __SKILL_NAME__: a Claude Code skill by Naren

> __DESCRIPTION__

Part of [Naren's Claude Skills](https://github.com/NarenDawar/narens-claude-skills).

## When it triggers

Describe the situations and example user phrasings that activate this skill.

## Install

**Plugin marketplace (recommended)**

```text
/plugin marketplace add NarenDawar/narens-claude-skills
/plugin install __SKILL_NAME__@narens-claude-skills
```

**Manual**

Copy `plugins/__SKILL_NAME__/skills/__SKILL_NAME__` into `~/.claude/skills/`.

## Example

**Before:** what Claude does without this skill.

**After:** what Claude does with it.

---

Made by [Naren](https://github.com/NarenDawar). If this helped, star the repo.
````

- [ ] **Step 4: Write `new_skill.py`**

Create `scripts/new_skill.py`:

```python
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
        desc = json.dumps(description)[1:-1] if f.suffix == ".json" else description
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v`
Expected: PASS (all tests so far)

- [ ] **Step 6: Commit**

```bash
git add template scripts/new_skill.py tests/test_new_skill.py
git commit -m "feat: add skill template and new_skill scaffolder" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Root repo files, marketplace, README

**Files:**
- Create: `.claude-plugin/marketplace.json`, `README.md`, `LICENSE`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `CHANGELOG.md`, `.gitignore`, `.gitattributes`, `llms.txt` (generated)
- Test: `tests/test_repo.py`

**Interfaces:**
- Consumes: `validate.validate(root)`, `build_catalog.build(root)`, `helpers.REPO_ROOT`.
- Produces: a repo root that passes `python scripts/validate.py`. README contains the `<!-- CATALOG:START -->` / `<!-- CATALOG:END -->` markers. Banner path referenced by README: `assets/banner.png` (created in Task 6; README references `assets/banner.svg` until PNG export is needed, which GitHub renders natively).

- [ ] **Step 1: Write the failing test**

Create `tests/test_repo.py`:

```python
import unittest

import helpers
import common
import validate


class RealRepo(unittest.TestCase):
    def test_repo_passes_validation(self):
        self.assertEqual(validate.validate(helpers.REPO_ROOT), [])

    def test_required_root_files_exist(self):
        for name in (
            "README.md", "LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
            "CHANGELOG.md", "llms.txt", ".gitignore", ".gitattributes",
            ".claude-plugin/marketplace.json",
        ):
            self.assertTrue((helpers.REPO_ROOT / name).is_file(), name)

    def test_branding_present(self):
        readme = common.read_text(helpers.REPO_ROOT / "README.md")
        self.assertTrue(readme.startswith("# Naren's Claude Skills"))
        self.assertIn("NarenDawar/narens-claude-skills", readme)
        self.assertIn("Made by [Naren]", readme)
        self.assertIn("alt=", readme)  # banner has alt text


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s tests -p "test_repo.py" -v`
Expected: FAIL (`marketplace.json: missing`, root files missing)

- [ ] **Step 3: Create marketplace and ignore files**

Create `.claude-plugin/marketplace.json`:

```json
{
  "name": "narens-claude-skills",
  "owner": {
    "name": "Naren",
    "url": "https://github.com/NarenDawar"
  },
  "metadata": {
    "description": "Naren's Claude skills: unique, installable Agent Skills and Claude Code plugins.",
    "version": "0.1.0"
  },
  "plugins": []
}
```

Create `.gitignore`:

```gitignore
__pycache__/
*.pyc
.venv/
.DS_Store
Thumbs.db
.idea/
.vscode/
```

Create `.gitattributes`:

```gitattributes
* text=auto eol=lf
*.png binary
```

- [ ] **Step 4: Create README.md**

Create `README.md`:

````markdown
# Naren's Claude Skills

<p align="center">
  <img src="assets/banner.svg" alt="Naren's Claude Skills: unique Agent Skills and Claude Code plugins" width="100%">
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/license-MIT-7C5CFF"></a>
  <img alt="Skills" src="https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2FNarenDawar%2Fnarens-claude-skills%2Fmain%2F.claude-plugin%2Fmarketplace.json&query=%24.plugins.length&label=skills&color=7C5CFF">
  <a href="https://github.com/NarenDawar/narens-claude-skills/stargazers"><img alt="GitHub stars" src="https://img.shields.io/github/stars/NarenDawar/narens-claude-skills?style=flat&color=7C5CFF"></a>
</p>

**A growing collection of unique, installable [Claude Code](https://claude.com/claude-code) skills (Agent Skills) and plugins, crafted by Naren.** Install any skill in one command through the Claude Code plugin marketplace, or copy a `SKILL.md` folder into your own setup.

## Install

**Plugin marketplace (recommended)**

```text
/plugin marketplace add NarenDawar/narens-claude-skills
/plugin install <skill-name>@narens-claude-skills
```

**Manual copy**

Copy any `plugins/<skill-name>/skills/<skill-name>/` folder into `~/.claude/skills/`. Claude picks it up on the next session.

## Skills

<!-- CATALOG:START -->
<!-- CATALOG:END -->

## Why these skills

Most skill collections are generic prompt dumps. These are small, focused, and opinionated: each one solves a specific problem, triggers precisely when it should, and is tested before it ships. Every skill is its own plugin, so you install only what you need.

## Build your own

The repo includes a skill template and a validator. See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/conventions.md](docs/conventions.md) for how skills are structured (`SKILL.md` frontmatter, trigger-first descriptions, per-skill READMEs).

## License

[MIT](LICENSE)

---

Made by [Naren](https://github.com/NarenDawar). If a skill saved you time, please star the repo.
````

- [ ] **Step 5: Create LICENSE, CONTRIBUTING, CODE_OF_CONDUCT, CHANGELOG**

Create `LICENSE`:

```text
MIT License

Copyright (c) 2026 Naren Dawar

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

Create `CONTRIBUTING.md`:

````markdown
# Contributing

Thanks for helping improve Naren's Claude Skills. Bug reports and skill ideas are welcome via issues.

## Adding a skill

```bash
python scripts/new_skill.py my-skill "Use when ..."
```

This copies `template/` into `plugins/my-skill/`, registers it in `.claude-plugin/marketplace.json`, and refreshes the README catalog. Then edit `SKILL.md` and the plugin `README.md`.

## Before opening a PR

```bash
python -m unittest discover -s tests -v
python scripts/validate.py
```

CI runs the same two commands. Conventions are in [docs/conventions.md](docs/conventions.md). Never edit the README catalog by hand; run `python scripts/build_catalog.py`.
````

Create `CODE_OF_CONDUCT.md`:

```markdown
# Code of Conduct

Be kind and constructive. Treat everyone with respect, assume good intent, and keep feedback focused on the work, not the person.

Harassment, discrimination, personal attacks, and publishing others' private information are not acceptable. Maintainers may remove comments, issues, or contributions that violate this and may block repeat offenders.

To report a problem, open an issue or contact the maintainer, Naren, through the GitHub profile linked in the README.
```

Create `CHANGELOG.md`:

```markdown
# Changelog

All notable changes are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- Repo scaffolding: plugin marketplace, skill template, validator, catalog generator, CI.
```

- [ ] **Step 6: Generate `llms.txt` and the catalog**

Run: `python scripts/build_catalog.py`
Expected: `Catalog and llms.txt updated`; `README.md` now contains the placeholder line between the markers and `llms.txt` exists.

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v` then `python scripts/validate.py`
Expected: all tests PASS; validator prints `OK: all plugins valid`

- [ ] **Step 8: Commit**

```bash
git add .
git commit -m "feat: add root repo files, marketplace manifest and README" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

> Note: `README.md` references `assets/banner.svg`, which is created in Task 6. Commit order is fine, but the image renders only after Task 6.

---

### Task 6: Brand assets

**Files:**
- Create: `assets/logo.svg`, `assets/banner.svg`, `assets/social-preview.svg`
- Create (generated): `assets/social-preview.png`

**Interfaces:**
- Consumes: README's `assets/banner.svg` reference (Task 5).
- Produces: logo mark (128x128 "N"), banner (1280x320), social preview (1280x640). Accent color `#7C5CFF`, background `#0F0B1E`.

- [ ] **Step 1: Create the logo**

Create `assets/logo.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128" role="img" aria-label="Naren monogram">
  <rect width="128" height="128" rx="28" fill="#7C5CFF"/>
  <path d="M38 94V34h10l32 40V34h10v60H80L48 54v40z" fill="#FFFFFF"/>
</svg>
```

- [ ] **Step 2: Create the banner**

Create `assets/banner.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="320" viewBox="0 0 1280 320" role="img" aria-label="Naren's Claude Skills">
  <rect width="1280" height="320" fill="#0F0B1E"/>
  <rect x="0" y="0" width="1280" height="6" fill="#7C5CFF"/>
  <g transform="translate(96 96)">
    <rect width="128" height="128" rx="28" fill="#7C5CFF"/>
    <path d="M38 94V34h10l32 40V34h10v60H80L48 54v40z" fill="#FFFFFF"/>
  </g>
  <text x="272" y="156" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="64" font-weight="700" fill="#FFFFFF">Naren's Claude Skills</text>
  <text x="272" y="208" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="28" fill="#B8A9FF">Unique Agent Skills and Claude Code plugins</text>
</svg>
```

- [ ] **Step 3: Create the social preview**

Create `assets/social-preview.svg`:

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="640" viewBox="0 0 1280 640" role="img" aria-label="Naren's Claude Skills">
  <rect width="1280" height="640" fill="#0F0B1E"/>
  <rect x="0" y="0" width="1280" height="10" fill="#7C5CFF"/>
  <g transform="translate(96 120)">
    <rect width="160" height="160" rx="36" fill="#7C5CFF"/>
    <path d="M48 118V42h12l40 50V42h12v76H100L60 68v50z" fill="#FFFFFF"/>
  </g>
  <text x="96" y="400" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="88" font-weight="700" fill="#FFFFFF">Naren's Claude Skills</text>
  <text x="96" y="470" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="38" fill="#B8A9FF">Unique Agent Skills and Claude Code plugins.</text>
  <text x="96" y="540" font-family="Segoe UI, Helvetica, Arial, sans-serif" font-size="30" fill="#8C7FD6">One-command install  ·  github.com/NarenDawar/narens-claude-skills</text>
</svg>
```

- [ ] **Step 4: Export the social preview to PNG**

GitHub's social preview upload requires PNG/JPG (1280x640). Use headless Edge (preinstalled on Windows):

```bash
"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" --headless --disable-gpu --hide-scrollbars --window-size=1280,640 --screenshot="C:/Users/naren/Documents/claude-skills/assets/social-preview.png" "file:///C:/Users/naren/Documents/claude-skills/assets/social-preview.svg"
```

Expected: `assets/social-preview.png` exists. If Edge is not at that path, use Chrome with the same flags, or open the SVG in a browser and screenshot at 1280x640.

- [ ] **Step 5: Visually verify the assets**

Use the Read tool on `assets/social-preview.png` and confirm: dark background, violet "N" logo, title text fully visible and not clipped, tagline and URL line readable. Then open `assets/banner.svg` in a browser (or Read a screenshot) and confirm the title does not overflow 1280px. Fix font sizes or `x` offsets if anything is clipped and re-export.

- [ ] **Step 6: Commit**

```bash
git add assets
git commit -m "feat: add logo, banner and social preview assets" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: GitHub config, docs and final verification

**Files:**
- Create: `.github/workflows/validate.yml`, `.github/PULL_REQUEST_TEMPLATE.md`, `.github/ISSUE_TEMPLATE/bug_report.md`, `.github/ISSUE_TEMPLATE/skill_idea.md`
- Create: `docs/conventions.md`, `docs/launch-checklist.md`
- Modify: `tests/test_repo.py` (add file-existence assertions)

**Interfaces:**
- Consumes: the commands `python -m unittest discover -s tests -v` and `python scripts/validate.py`.
- Produces: CI that runs both on push and PR; documented conventions and the manual GitHub settings (description, topics, social preview).

- [ ] **Step 1: Extend the failing test**

Append this test method inside `class RealRepo` in `tests/test_repo.py`:

```python
    def test_github_and_docs_files_exist(self):
        for name in (
            ".github/workflows/validate.yml",
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/ISSUE_TEMPLATE/bug_report.md",
            ".github/ISSUE_TEMPLATE/skill_idea.md",
            "docs/conventions.md",
            "docs/launch-checklist.md",
            "assets/logo.svg",
            "assets/banner.svg",
            "assets/social-preview.svg",
            "assets/social-preview.png",
        ):
            self.assertTrue((helpers.REPO_ROOT / name).is_file(), name)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest discover -s tests -p "test_repo.py" -v`
Expected: FAIL on `.github/workflows/validate.yml`

- [ ] **Step 3: Create CI workflow and templates**

Create `.github/workflows/validate.yml`:

```yaml
name: validate

on:
  push:
    branches: [main]
  pull_request:

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Unit tests
        run: python -m unittest discover -s tests -v
      - name: Validate plugins and catalog
        run: python scripts/validate.py
```

Create `.github/PULL_REQUEST_TEMPLATE.md`:

```markdown
## What this changes

## Checklist

- [ ] `python -m unittest discover -s tests -v` passes
- [ ] `python scripts/validate.py` passes
- [ ] README catalog regenerated with `python scripts/build_catalog.py` (not hand-edited)
- [ ] New skill: description starts with "Use when" and the plugin README has an example
```

Create `.github/ISSUE_TEMPLATE/bug_report.md`:

```markdown
---
name: Bug report
about: A skill misbehaves, fails to trigger, or the tooling breaks
labels: bug
---

**Skill or script affected**

**What happened**

**What you expected**

**Steps to reproduce** (include your Claude Code version)
```

Create `.github/ISSUE_TEMPLATE/skill_idea.md`:

```markdown
---
name: Skill idea
about: Suggest a skill you would like to see
labels: idea
---

**The problem this skill would solve**

**When it should trigger** (example phrasings)

**What good output looks like**
```

- [ ] **Step 4: Create docs**

Create `docs/conventions.md`:

````markdown
# Conventions

## Layout

One plugin per skill: `plugins/<name>/` containing `.claude-plugin/plugin.json`, `README.md`, and `skills/<name>/SKILL.md` (plus optional `references/` and `scripts/`).

## Naming

Plugin and skill names are kebab-case, and the skill directory name equals the `name` in `SKILL.md` frontmatter.

## SKILL.md

- Frontmatter requires `name` and `description`.
- The description is a single line that starts with `Use when` and describes the triggering situation, not the workflow. It is what Claude and search engines see first.
- No branding footer; branding lives in READMEs and metadata so it costs no tokens when the skill loads.

## Metadata

`plugin.json` and `marketplace.json` set the author/owner to `Naren`. `plugin.json` also needs `version` and `description`.

## Per-skill README

Keyword-rich H1 ("<name>: a Claude Code skill by Naren"), a "When it triggers" section, install commands, and a before/after example.

## Generated files

The README skill table and `llms.txt` come from `python scripts/build_catalog.py`. `python scripts/validate.py` fails if they are stale.
````

Create `docs/launch-checklist.md`:

````markdown
# Launch checklist (manual GitHub steps)

Done once, after the first push to `github.com/NarenDawar/narens-claude-skills`.

1. **Description:** "Naren's Claude skills: unique, installable Agent Skills & Claude Code plugins for developers. One-command install via plugin marketplace."
2. **Website:** your site or profile link, if any.
3. **Topics:** claude, claude-code, claude-skills, agent-skills, anthropic, ai-agents, claude-code-plugins, claude-code-skills, prompt-engineering, llm, developer-tools, ai-tools, plugin-marketplace, skill-md, productivity, automation.
4. **Social preview:** Settings > General > Social preview > upload `assets/social-preview.png`.
5. **Verify install:** in Claude Code run `/plugin marketplace add NarenDawar/narens-claude-skills` and confirm the marketplace loads.
6. **Verify the skills badge** in the README renders a number (it reads `marketplace.json` on `main`).
7. **After the first skills ship:** submit to relevant awesome-claude lists.
````

- [ ] **Step 5: Run the full verification**

Run: `python -m unittest discover -s tests -v`
Expected: PASS for every test in `test_common`, `test_build_catalog`, `test_validate`, `test_new_skill`, `test_repo`.

Run: `python scripts/validate.py`
Expected: `OK: all plugins valid`

Run: `python scripts/build_catalog.py --check`
Expected: exit code 0, no output.

Run: `git status --short`
Expected: only the files from this task are listed (no `__pycache__`, thanks to `.gitignore`).

- [ ] **Step 6: Commit**

```bash
git add .
git commit -m "feat: add CI, GitHub templates and contributor docs" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Spec coverage self-check

| Spec requirement | Task |
|---|---|
| Layout (README, LICENSE, CONTRIBUTING, CoC, CHANGELOG, llms.txt, marketplace, plugins, template, scripts, docs, assets, .github) | 1-7 |
| Conventions: kebab names, frontmatter, "Use when", no SKILL.md footer, author Naren | 3, 4, 7 (docs) |
| Marketplace name and install form `<plugin>@narens-claude-skills` | 5 |
| Catalog generated; validate checks it; CI runs both | 2, 3, 7 |
| README structure, banner alt text, badges, install, catalog, why, footer | 5 |
| Per-skill README (H1, triggers, example, install) | 4 |
| GitHub description, topics, social preview | 6, 7 (`launch-checklist.md`) |
| Logo monogram, accent color, banner template | 6 |
| `llms.txt` | 2, 5 |
| Tests with fixtures, template smoke test | 1-4 |
| Out of scope: remote repo, Pages | not implemented, by design |

**Known deviations from the spec (flag to the user):**
- The social preview image carries no hard-coded skill count (it would go stale on every new skill). The README's live "skills" badge shows the count instead.
- The LICENSE copyright holder is written as "Naren Dawar", inferred from the GitHub username; the user should confirm the legal name.
- The dynamic skills badge reads `marketplace.json` from `main` via shields.io, so it only renders after the first push.
