# mcp-fixer scorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build sub-project 1 of mcp-fixer: `python -m mcp_fixer score` reads an MCP server's tool list (by spawning a stdio server, or from a saved JSON file) and prints a deterministic lint score from 0 to 100 with per-tool scores and findings.

**Architecture:** One Python package, `servers/mcp-fixer/src/mcp_fixer/`, standard library only. `rules.py` holds the lint rules and the one weights/thresholds table; `score.py` is pure scoring over a tool list; `report.py` renders text and JSON; `stdio_client.py` is a minimal MCP stdio client (`initialize`, then paged `tools/list`, read-only); `cli.py` ties them together. Tests use `unittest` with a plain-Python fake stdio server. The repo gets a CI job for the server's tests on Python 3.9 and 3.12.

**Tech Stack:** Python 3.9+ standard library (`argparse`, `json`, `subprocess`, `threading`, `queue`, `shutil`, `re`, `unittest`), Markdown, YAML (one CI job).

**Spec:** `docs/superpowers/specs/2026-10-05-mcp-fixer-scorer-design.md`

## Global Constraints

- Python 3.9+ standard library only; no MCP SDK and no third-party packages; files written with LF line endings; UTF-8 read with BOM tolerance; code must run on Python 3.9 (no `match`, no `X | Y` type unions, no parenthesized context managers).
- Read-only: the client sends only `initialize`, `notifications/initialized` and `tools/list` (plus answering the server's `ping`); it never sends `tools/call`.
- Deterministic: the same input gives the same score, the same findings in the same order and byte-identical JSON; no model, no network, no randomness, no clock.
- Rules, thresholds and weights live in one table in `rules.py` and are exactly those in the spec: D001 high, D002 medium (under 20 characters), D003 medium (over 500), D004 medium (word-set overlap of 0.8 or more), P001 medium, P002 medium, P003 medium, P004 high, P005 low, P006 low (nesting deeper than 3), N001 medium, N002 low, T001 medium (more than 40 tools), T002 medium over 8,000 and high over 20,000 estimated tokens, M001 high.
- Estimated tokens are the length of a tool's canonical JSON (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`) divided by 4, rounded up; it is a heuristic, not a tokenizer.
- Score: each tool starts at 100 and loses 25 per high, 10 per medium, 4 per low finding about it, never below 0; the server score is the mean of the tool scores minus the server-level penalties (T001 5, T002 5 or 15, N002 4, each M001 25), clamped to 0..100 and rounded half up; an empty tool list scores 100 with the note `no tools listed`.
- A server problem (hang, crash, early exit, error response, bad result, endless paging) is a one-line `error: ...` with exit code 2, never a hang or a traceback, and the server process tree is never left running.
- Report: `schemaVersion: 1`; `--format json` is the machine format the patcher will consume.
- Do not push, merge, rename or change GitHub settings in this plan.
- Work on branch `mcp-fixer-scorer` (already created, holds the spec commit).
- Repo rules: no old marketplace name outside history, the README catalog is generated (never hand-edited), existing files under `docs/superpowers/` are untouched except the new mcp-fixer spec edit in Task 1.
- Scratch files live in the session scratchpad: `C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/4ec2fd29-f30d-4793-83a9-f979fbae59a4/scratchpad` (called `$SP`). Write patch scripts with the Write tool, not shell heredocs (the shell collapses backslashes).
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

**Clarifications decided in this plan** (spec details the plan makes precise; Task 1 edits the spec to match):

- The base environment passed to a spawned server is `PATH`, `PATHEXT`, `COMSPEC`, `SYSTEMROOT`, `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TEMP`, `TMP`, `LANG` (the Windows and Node launchers need several of these), plus the `--env` values.
- `--timeout` is the per-request timeout; the whole connection is also capped at four times the timeout.
- The report also carries a `notes` array of plain strings, and each `perTool` entry also carries `findings` (its number of findings). Both are additions to the spec's shape, `schemaVersion` stays 1.
- Duplicate tool names are scored as separate entries; in `perTool` the second and later get the keys `name#2`, `name#3`.
- Parameter rules (P001 to P003) look at a tool's top-level `properties` only; P006 measures nesting through `properties`, `items`, `anyOf`, `oneOf` and `allOf`.
- P003 recognizes values listed after the trigger phrases `one of`, `either`, `must be`, `can be`, `should be`, `option(s)`, `allowed values`, `valid values`, `possible values`, `choice(s)`, `supported values`, or three or more quoted values; each value is at most two words and does not start with `a`, `an` or `the`.

## Review Focus

Failure modes the spec implies but a first pass is likely to skip. Each has a test in the task that owns the code:

1. A misbehaving server: one that hangs on `initialize` or on `tools/list`, crashes after `initialize`, exits at once, prints banners and junk to stdout, answers with a JSON-RPC error or a bad `tools` value, or pages forever. Each gives a one-line error (or a result) quickly, and the child process is gone afterwards. (Task 5)
2. P003 false positives and negatives: prose such as "can be used to filter", "must be a valid path or URL" and "one of the supported formats" must not fire; "one of: asc, desc", "either 'json' or 'csv'", "Options: json, csv, or xml", "Allowed values are a, b, c" and three quoted values must. (Task 3)
3. Score arithmetic edges: half-up rounding (87.5 becomes 88), the floor at 0, server penalties stacking and clamping, a malformed entry, an empty list, and duplicate tool names. (Task 4)
4. Determinism and shape: byte-identical JSON on a repeat run, stable finding order, `schemaVersion`, non-ASCII descriptions, and a text report that cannot crash a legacy console encoding. (Tasks 4 and 6)
5. CLI input validation: neither or both input modes, a missing or invalid JSON file, a file with neither a `tools` array nor an array, a bad `--env`, non-finite or non-positive `--timeout`, a non-finite `--min-score`, the `--min-score` boundary (equal passes), and an unwritable `--out`: all one-line errors with exit 2. (Task 6)

---

### Task 1: Scaffold the package and integrate it in the repo

**Files:**
- Create: `servers/mcp-fixer/pyproject.toml`, `servers/mcp-fixer/README.md` (stub), `servers/mcp-fixer/src/mcp_fixer/__init__.py`, `servers/mcp-fixer/tests/support.py`, `servers/mcp-fixer/tests/test_package.py`
- Modify: `.github/workflows/validate.yml`, `.gitignore`, `CHANGELOG.md`, `README.md` and `llms.txt` (regenerated), `docs/superpowers/specs/2026-10-05-mcp-fixer-scorer-design.md`

**Interfaces:**
- Produces: the importable package `mcp_fixer` with `__version__ == "0.1.0"`; `tests/support.py` (puts `src` on `sys.path`, defines `FAKE_SERVER`, `process_alive(pid)`), used by every later test file.

- [ ] **Step 1: Write the failing test**

`servers/mcp-fixer/tests/support.py`:

```python
"""Shared test setup: puts src/ on sys.path and offers a few helpers."""
import os
import subprocess
import sys
import time
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
SRC = ROOT / "src"
FAKE_SERVER = TESTS / "fake_server.py"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def process_alive(pid):
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
        ).stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def wait_until_gone(pid, seconds=5.0):
    """True when the process is gone within `seconds`."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not process_alive(pid):
            return True
        time.sleep(0.05)
    return not process_alive(pid)
```

`servers/mcp-fixer/tests/test_package.py`:

```python
import re
import unittest

import support
import mcp_fixer


class PackageTests(unittest.TestCase):
    def test_version_matches_pyproject(self):
        text = (support.ROOT / "pyproject.toml").read_text(encoding="utf-8")
        declared = re.search(r'^version = "([^"]+)"', text, re.MULTILINE).group(1)
        self.assertEqual(mcp_fixer.__version__, declared)

    def test_package_has_no_third_party_dependencies(self):
        text = (support.ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("dependencies = []", text)
        self.assertIn('requires-python = ">=3.9"', text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'mcp_fixer'` (and no `pyproject.toml`).

- [ ] **Step 3: Write the manifest, package and README stub**

`servers/mcp-fixer/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "mcp-fixer"
version = "0.1.0"
description = "Score an MCP server's tool definitions with deterministic lint rules."
readme = "README.md"
requires-python = ">=3.9"
license = { text = "MIT" }
authors = [{ name = "Naren" }]
dependencies = []

[project.scripts]
mcp-fixer = "mcp_fixer.cli:main"

[tool.setuptools.packages.find]
where = ["src"]
```

`servers/mcp-fixer/src/mcp_fixer/__init__.py`:

```python
"""mcp-fixer: score an MCP server's tool definitions."""

__version__ = "0.1.0"
```

`servers/mcp-fixer/README.md` (a stub, completed in Task 7):

```markdown
# mcp-fixer: score an MCP server's tool definitions

> Scores an MCP server's tool definitions with deterministic lint rules, so you can see what makes agents pick the wrong tool or waste tokens.
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Integrate it in the repo and align the spec**

Write this script to `$SP/integrate_mcp_fixer.py` and run `python $SP/integrate_mcp_fixer.py` from the repo root:

```python
from pathlib import Path


def edit(path, pairs):
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    for old, new in pairs:
        assert old in text, f"{path}: {old[:70]!r}"
        text = text.replace(old, new, 1)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


JOB = """
  mcp-fixer:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.9", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - name: mcp-fixer tests
        run: python -m unittest discover -s servers/mcp-fixer/tests -v
"""
wf = Path(".github/workflows/validate.yml")
text = wf.read_text(encoding="utf-8")
assert "mcp-fixer:" not in text
with open(wf, "w", encoding="utf-8", newline="\n") as f:
    f.write(text.rstrip("\n") + "\n" + JOB)

gi = Path(".gitignore")
text = gi.read_text(encoding="utf-8")
lines = ["servers/*/.venv/", "servers/*/build/", "servers/*/dist/", "*.egg-info/"]
missing = [line for line in lines if line not in text]
if missing:
    with open(gi, "w", encoding="utf-8", newline="\n") as f:
        f.write(text.rstrip("\n") + "\n" + "\n".join(missing) + "\n")

edit("CHANGELOG.md", [(
    "### Added\n",
    "### Added\n"
    "- `mcp-fixer` MCP server tool (first of three parts): `python -m mcp_fixer score` reads an MCP server's tool list, from a spawned stdio server or a saved JSON file, and prints a deterministic lint score from 0 to 100 with per-tool scores and findings (missing or bloated descriptions, undescribed or untyped parameters, values listed in prose that should be enums, generic or inconsistent names, and tool-count and token-size limits). Read-only: it never calls a tool. The patcher and the accuracy proof come next.\n",
)])

edit("docs/superpowers/specs/2026-10-05-mcp-fixer-scorer-design.md", [
    ("in addition to a minimal base (`PATH`, `HOME`/`USERPROFILE`, `SYSTEMROOT`, `TEMP`/`TMP`).",
     "in addition to a minimal base (`PATH`, `PATHEXT`, `COMSPEC`, `SYSTEMROOT`, `HOME`, `USERPROFILE`, `APPDATA`, `LOCALAPPDATA`, `TEMP`, `TMP`, `LANG`; the Windows and Node launchers need several of these)."),
    ("per-request timeout and overall cap for the connection phase.",
     "per-request timeout; the whole connection is also capped at four times the timeout."),
    ("`serverName`, `serverVersion` and `protocolVersion` are null for the file mode.",
     "`serverName`, `serverVersion` and `protocolVersion` are null for the file mode. The report also has a `notes` array of plain strings (for example `no tools listed`), and each `perTool` entry also carries `findings`, the number of findings about that tool."),
])
print("ok")
```

Expected output: `ok`.

- [ ] **Step 6: Regenerate the catalog and run all checks**

```bash
python scripts/build_catalog.py
python -m unittest discover -s tests 2>&1 | tail -3
python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -3
python scripts/validate.py
git status --short
```

Expected: `Catalog and llms.txt updated`; the repo tests PASS (522 or more, 5 skipped); the server tests PASS; `OK: all plugins valid`; the README catalog now lists `mcp-fixer` under MCP servers with its README's `> ` line; `git status` shows only this task's files.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat: scaffold mcp-fixer and add its CI job

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Description, name, server-level and malformed-entry rules

**Files:**
- Create: `servers/mcp-fixer/src/mcp_fixer/rules.py`, `servers/mcp-fixer/tests/test_rules.py`

**Interfaces:**
- Consumes: nothing from earlier tasks except the package and `tests/support.py`.
- Produces: in `rules.py`: `SEVERITY_PENALTY`, `THRESHOLDS`, `SERVER_PENALTY`, `GENERIC_NAMES`; `finding(rule, severity, message, *, tool=None, param=None, evidence="", fix="", data=None) -> dict` (keys `rule`, `severity`, `tool`, `param`, `message`, `evidence`, `fix`, `data`); `estimate_tokens(tool) -> int`; `check_description(tool) -> list`; `check_duplicates(tools) -> list of (index, finding)` (index into the given list); `check_name(tool) -> list`; `check_server(tools) -> list` (N002, T001, T002); `malformed_finding(index, entry) -> dict`. Task 3 adds `check_schema`; Task 4 consumes all of them. Every `check_*` that takes a tool expects a dict with a string `name`.

- [ ] **Step 1: Write the failing tests**

`servers/mcp-fixer/tests/test_rules.py`:

```python
import unittest

import support  # noqa: F401  (puts src/ on sys.path)
from mcp_fixer import rules


def tool(name="get_item", description="Fetch a single item by its identifier.", **extra):
    base = {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {"item_id": {"type": "string", "description": "Identifier of the item"}},
            "required": ["item_id"],
        },
    }
    base.update(extra)
    return base


def ids(findings):
    return [f["rule"] for f in findings]


def big_tool(count):
    """A tool with `count` described, typed properties: about 63 characters of JSON each."""
    properties = {
        f"p{i:04d}": {"type": "string", "description": "Parameter number one"} for i in range(count)
    }
    return {
        "name": "big_tool",
        "description": "A tool with a very large input schema.",
        "inputSchema": {"type": "object", "properties": properties, "required": ["p0000"]},
    }


class EstimateTokensTests(unittest.TestCase):
    def test_canonical_json_length_over_four_rounded_up(self):
        self.assertEqual(rules.estimate_tokens({"name": "a"}), 3)  # {"name":"a"} is 12 characters
        self.assertEqual(rules.estimate_tokens({"name": "abc"}), 4)  # 14 characters -> 3.5 -> 4

    def test_non_ascii_counts_characters_not_escapes(self):
        self.assertEqual(rules.estimate_tokens({"name": "\u00e9"}), 3)

    def test_key_order_does_not_matter(self):
        self.assertEqual(
            rules.estimate_tokens({"name": "a", "description": "b"}),
            rules.estimate_tokens({"description": "b", "name": "a"}),
        )


class DescriptionTests(unittest.TestCase):
    def test_a_good_description_is_clean(self):
        self.assertEqual(rules.check_description(tool()), [])

    def test_d001_missing_empty_blank_or_non_string(self):
        for value in (None, "", "   \n", 5, ["x"]):
            with self.subTest(value):
                t = tool()
                t["description"] = value
                self.assertEqual(ids(rules.check_description(t)), ["D001"])
        t = tool()
        del t["description"]
        self.assertEqual(ids(rules.check_description(t)), ["D001"])

    def test_d001_is_high_and_names_the_tool(self):
        found = rules.check_description(tool(description=""))[0]
        self.assertEqual((found["severity"], found["tool"]), ("high", "get_item"))
        self.assertEqual(found["data"], {"action": "add-description"})

    def test_d002_short_description_boundary(self):
        self.assertEqual(ids(rules.check_description(tool(description="x" * 19))), ["D002"])
        self.assertEqual(rules.check_description(tool(description="x" * 20)), [])
        self.assertEqual(ids(rules.check_description(tool(description="Runs it"))), ["D002"])

    def test_d002_ignores_surrounding_whitespace(self):
        self.assertEqual(ids(rules.check_description(tool(description="   short   "))), ["D002"])

    def test_d003_long_description_boundary(self):
        self.assertEqual(rules.check_description(tool(description="x" * 500)), [])
        found = rules.check_description(tool(description="x" * 501))
        self.assertEqual(ids(found), ["D003"])
        self.assertEqual(found[0]["data"], {"action": "shorten-description", "maxChars": 500})


class DuplicateTests(unittest.TestCase):
    def test_identical_descriptions_flag_both_tools(self):
        tools = [tool("a_tool", "Search the catalog for products."), tool("b_tool", "Search the catalog for products.")]
        found = rules.check_duplicates(tools)
        self.assertEqual([(i, f["rule"], f["tool"]) for i, f in found], [(0, "D004", "a_tool"), (1, "D004", "b_tool")])
        self.assertEqual(found[0][1]["data"], {"other": "b_tool", "overlap": 1.0})

    def test_overlap_of_exactly_point_eight_fires(self):
        tools = [tool("a_tool", "alpha beta gamma delta"), tool("b_tool", "alpha beta gamma delta epsilon")]
        self.assertEqual(len(rules.check_duplicates(tools)), 2)  # 4 of 5 words shared

    def test_overlap_below_point_eight_does_not(self):
        tools = [tool("a_tool", "alpha beta gamma"), tool("b_tool", "alpha beta gamma delta epsilon")]
        self.assertEqual(rules.check_duplicates(tools), [])  # 3 of 5 words shared

    def test_case_and_punctuation_do_not_hide_duplicates(self):
        tools = [tool("a_tool", "Search the Catalog!"), tool("b_tool", "search the catalog")]
        self.assertEqual(len(rules.check_duplicates(tools)), 2)

    def test_empty_descriptions_are_not_duplicates(self):
        tools = [tool("a_tool", ""), tool("b_tool", "")]
        self.assertEqual(rules.check_duplicates(tools), [])

    def test_three_tools_report_each_close_pair(self):
        tools = [tool("a_tool", "one two three four"), tool("b_tool", "one two three four"), tool("c_tool", "entirely different words here")]
        found = rules.check_duplicates(tools)
        self.assertEqual(sorted(i for i, _ in found), [0, 1])


class NameTests(unittest.TestCase):
    def test_n001_generic_names_whole_name_case_insensitive(self):
        for name in ("run", "Execute", "QUERY", "do", "action", "tool", "call"):
            with self.subTest(name):
                self.assertEqual(ids(rules.check_name(tool(name))), ["N001"])

    def test_descriptive_names_are_fine(self):
        for name in ("run_query", "search", "get_item", "executeJob"):
            with self.subTest(name):
                self.assertEqual(rules.check_name(tool(name)), [])


class ServerLevelTests(unittest.TestCase):
    def named(self, *names):
        return [{"name": n} for n in names]

    def test_n002_mixed_styles(self):
        found = rules.check_server(self.named("get_item", "list-items"))
        self.assertEqual(ids(found), ["N002"])
        self.assertIsNone(found[0]["tool"])
        self.assertEqual(found[0]["data"], {"styles": {"kebab-case": 1, "snake_case": 1}})

    def test_n002_one_style_is_fine(self):
        for names in (("get_item", "list_items"), ("getItem", "listItems"), ("get-item", "list-items")):
            with self.subTest(names):
                self.assertEqual(rules.check_server(self.named(*names)), [])

    def test_n002_single_words_have_no_style(self):
        self.assertEqual(rules.check_server(self.named("get", "list")), [])
        self.assertEqual(ids(rules.check_server(self.named("get_item", "listItems", "x"))), ["N002"])

    def test_t001_tool_count_boundary(self):
        self.assertEqual(rules.check_server(self.named(*[f"tool_{i}" for i in range(40)])), [])
        found = rules.check_server(self.named(*[f"tool_{i}" for i in range(41)]))
        self.assertEqual(ids(found), ["T001"])
        self.assertEqual(found[0]["data"], {"toolCount": 41})

    def test_t002_size_thresholds(self):
        self.assertLess(rules.estimate_tokens(big_tool(400)), 8000)
        self.assertEqual(rules.check_server([big_tool(400)]), [])
        self.assertTrue(8000 < rules.estimate_tokens(big_tool(800)) <= 20000)
        found = rules.check_server([big_tool(800)])
        self.assertEqual([(f["rule"], f["severity"]) for f in found], [("T002", "medium")])
        self.assertGreater(rules.estimate_tokens(big_tool(2000)), 20000)
        found = rules.check_server([big_tool(2000)])
        self.assertEqual([(f["rule"], f["severity"]) for f in found], [("T002", "high")])

    def test_server_findings_have_no_tool(self):
        for f in rules.check_server([big_tool(2000)]):
            self.assertIsNone(f["tool"])


class MalformedTests(unittest.TestCase):
    def test_m001_for_anything_that_is_not_a_named_object(self):
        for index, entry in enumerate(("oops", None, 5, {"description": "no name"}, {"name": ""}, {"name": 7})):
            with self.subTest(entry):
                found = rules.malformed_finding(index, entry)
                self.assertEqual((found["rule"], found["severity"], found["tool"]), ("M001", "high", None))
                self.assertIn(str(index), found["message"])


class FindingShapeTests(unittest.TestCase):
    def test_every_finding_has_the_same_keys(self):
        f = rules.finding("D001", "high", "msg")
        self.assertEqual(set(f), {"rule", "severity", "tool", "param", "message", "evidence", "fix", "data"})
        self.assertEqual((f["tool"], f["param"], f["evidence"], f["fix"], f["data"]), (None, None, "", "", {}))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_rules.py" 2>&1 | tail -4`
Expected: ERROR, `ImportError: cannot import name 'rules' from 'mcp_fixer'`.

- [ ] **Step 3: Write the implementation**

`servers/mcp-fixer/src/mcp_fixer/rules.py`:

```python
"""Lint rules for MCP tool definitions. Deterministic; standard library only."""
import json
import math
import re

# Points a finding takes off the tool it is about.
SEVERITY_PENALTY = {"high": 25, "medium": 10, "low": 4}

THRESHOLDS = {
    "description_min_chars": 20,
    "description_max_chars": 500,
    "duplicate_overlap": 0.8,
    "max_nesting": 3,
    "max_tools": 40,
    "tokens_medium": 8000,
    "tokens_high": 20000,
}

# Points a server-level finding takes off the server score.
SERVER_PENALTY = {"T001": 5, "T002": {"medium": 5, "high": 15}, "N002": 4, "M001": 25}

GENERIC_NAMES = frozenset({"run", "execute", "call", "do", "action", "tool", "query"})

_SNAKE = re.compile(r"^[a-z0-9]+(?:_[a-z0-9]+)+$")
_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
_CAMEL = re.compile(r"^[a-z][a-z0-9]*(?:[A-Z][a-z0-9]*)+$")
_WORD = re.compile(r"\w+")


def finding(rule, severity, message, *, tool=None, param=None, evidence="", fix="", data=None):
    return {
        "rule": rule,
        "severity": severity,
        "tool": tool,
        "param": param,
        "message": message,
        "evidence": evidence,
        "fix": fix,
        "data": data or {},
    }


def estimate_tokens(tool):
    """Canonical JSON length over 4, rounded up: a heuristic, not a tokenizer."""
    text = json.dumps(tool, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return math.ceil(len(text) / 4)


def check_description(tool):
    name = tool["name"]
    raw = tool.get("description")
    text = raw.strip() if isinstance(raw, str) else ""
    if not text:
        return [
            finding(
                "D001",
                "high",
                "no description",
                tool=name,
                fix="Add a description that says what the tool does and when to use it.",
                data={"action": "add-description"},
            )
        ]
    size = len(text)
    if size < THRESHOLDS["description_min_chars"]:
        return [
            finding(
                "D002",
                "medium",
                f"description is only {size} characters",
                tool=name,
                evidence=text,
                fix="Say what the tool does, what it returns and when to choose it.",
                data={"action": "expand-description"},
            )
        ]
    limit = THRESHOLDS["description_max_chars"]
    if size > limit:
        return [
            finding(
                "D003",
                "medium",
                f"description is {size} characters",
                tool=name,
                evidence=f"limit {limit}",
                fix="Shorten it: every tool description is sent to the model on every request.",
                data={"action": "shorten-description", "maxChars": limit},
            )
        ]
    return []


def _words(tool):
    raw = tool.get("description")
    return set(_WORD.findall(raw.lower())) if isinstance(raw, str) else set()


def check_duplicates(tools):
    """Pairs of tools whose descriptions share 80% or more of their words.

    Returns (index, finding) pairs, index being the position in `tools`; both tools of a pair
    get a finding.
    """
    found = []
    words = [_words(t) for t in tools]
    limit = THRESHOLDS["duplicate_overlap"]
    for i in range(len(tools)):
        for j in range(i + 1, len(tools)):
            a, b = words[i], words[j]
            if not a or not b:
                continue
            overlap = len(a & b) / len(a | b)
            if overlap < limit:
                continue
            for mine, other in ((i, j), (j, i)):
                found.append(
                    (
                        mine,
                        finding(
                            "D004",
                            "medium",
                            f"description is almost the same as {tools[other]['name']}",
                            tool=tools[mine]["name"],
                            evidence=f"{overlap:.0%} of words shared",
                            fix="Say what makes this tool different, so the model can tell them apart.",
                            data={"other": tools[other]["name"], "overlap": round(overlap, 2)},
                        ),
                    )
                )
    return found


def check_name(tool):
    name = tool["name"]
    if name.strip().lower() in GENERIC_NAMES:
        return [
            finding(
                "N001",
                "medium",
                f"'{name}' is too generic to choose between tools",
                tool=name,
                fix="Name it after what it does, for example search_orders.",
                data={"action": "rename"},
            )
        ]
    return []


def _style(name):
    if _SNAKE.match(name):
        return "snake_case"
    if _KEBAB.match(name):
        return "kebab-case"
    if _CAMEL.match(name):
        return "camelCase"
    return None


def check_server(tools):
    """N002, T001 and T002: findings about the server as a whole (tool is None)."""
    found = []
    styles = {}
    for tool in tools:
        style = _style(tool["name"])
        if style:
            styles[style] = styles.get(style, 0) + 1
    if len(styles) > 1:
        ordered = dict(sorted(styles.items()))
        found.append(
            finding(
                "N002",
                "low",
                "tool names mix naming styles",
                evidence=", ".join(f"{k} ({v})" for k, v in ordered.items()),
                fix="Pick one naming style for every tool.",
                data={"styles": ordered},
            )
        )
    limit = THRESHOLDS["max_tools"]
    if len(tools) > limit:
        found.append(
            finding(
                "T001",
                "medium",
                f"{len(tools)} tools is more than agents choose well between",
                evidence=f"limit {limit}",
                fix="Split the server, or hide the rarely used tools.",
                data={"toolCount": len(tools)},
            )
        )
    total = sum(estimate_tokens(t) for t in tools)
    if total > THRESHOLDS["tokens_high"]:
        severity = "high"
    elif total > THRESHOLDS["tokens_medium"]:
        severity = "medium"
    else:
        severity = None
    if severity:
        found.append(
            finding(
                "T002",
                severity,
                f"tool definitions take about {total:,} tokens on every request",
                evidence=f"limit {THRESHOLDS['tokens_medium']:,} (medium), {THRESHOLDS['tokens_high']:,} (high)",
                fix="Shorten descriptions and trim schemas, or expose fewer tools.",
                data={"estimatedTokens": total},
            )
        )
    return found


def malformed_finding(index, entry):
    if isinstance(entry, dict):
        evidence = "an object with no non-empty string name"
    else:
        evidence = f"a {type(entry).__name__} instead of an object"
    return finding(
        "M001",
        "high",
        f"tool entry {index} is malformed",
        evidence=evidence,
        fix="Return each tool as an object with a non-empty string name.",
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -4`
Expected: all tests PASS (this task's plus Task 1's).

- [ ] **Step 5: Commit**

```bash
python -m unittest discover -s tests 2>&1 | tail -2
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer description, name and server-level rules

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Schema rules and enum detection

**Files:**
- Modify: `servers/mcp-fixer/src/mcp_fixer/rules.py` (append), `servers/mcp-fixer/tests/test_rules.py` (append two classes before `if __name__`)

**Interfaces:**
- Consumes: `finding`, `THRESHOLDS` from Task 2.
- Produces: `extract_enum_values(text) -> list[str]`; `schema_depth(schema) -> int`; `check_schema(tool) -> list` covering P001 to P006. Task 4 calls `check_schema`.

- [ ] **Step 1: Write the failing tests**

Add to `servers/mcp-fixer/tests/test_rules.py`, before the `if __name__` line:

```python
def with_params(**props):
    """A tool whose input schema has exactly these properties (and a required list)."""
    return {
        "name": "get_item",
        "description": "Fetch a single item by its identifier.",
        "inputSchema": {"type": "object", "properties": props, "required": list(props)},
    }


def str_param(description):
    return {"type": "string", "description": description}


class EnumExtractionTests(unittest.TestCase):
    def test_values_listed_in_prose_are_found(self):
        cases = {
            "Sort order, one of: asc, desc": ["asc", "desc"],
            "Either 'json' or 'csv'.": ["json", "csv"],
            "Output format. Options: json, csv, or xml": ["json", "csv", "xml"],
            "Allowed values are a, b, c": ["a", "b", "c"],
            "One of the following: low, medium, high": ["low", "medium", "high"],
            "Status: 'open', 'closed', or 'merged'": ["open", "closed", "merged"],
            "Valid values: red | green | blue": ["red", "green", "blue"],
            "The kind. Can be file or folder.": ["file", "folder"],
        }
        for text, expected in cases.items():
            with self.subTest(text):
                self.assertEqual(rules.extract_enum_values(text), expected)

    def test_prose_that_is_not_a_value_list_is_ignored(self):
        for text in (
            "Can be used to filter by name",
            "Must be a valid path or URL",
            "One of the supported formats",
            "Path to a file or URL",
            "Number of items to return",
            "Additional options for the request",
            "Name like 'foo' or 'bar'",
            "",
            None,
            5,
        ):
            with self.subTest(text):
                self.assertEqual(rules.extract_enum_values(text), [])

    def test_at_most_twenty_values(self):
        text = "One of: " + ", ".join(f"v{i}" for i in range(30))
        self.assertEqual(len(rules.extract_enum_values(text)), 20)

    def test_quoted_values_repeat_once(self):
        self.assertEqual(rules.extract_enum_values("'a' then 'b' then 'a' then 'c'"), ["a", "b", "c"])


class SchemaDepthTests(unittest.TestCase):
    def test_depth_counts_levels_of_nested_schemas(self):
        self.assertEqual(rules.schema_depth({"type": "string"}), 0)
        self.assertEqual(rules.schema_depth({"type": "object", "properties": {"a": {"type": "string"}}}), 1)
        nested = {"type": "object", "properties": {"a": {"type": "object", "properties": {"b": {"type": "string"}}}}}
        self.assertEqual(rules.schema_depth(nested), 2)

    def test_depth_follows_items_and_combinators(self):
        arr = {"type": "array", "items": {"type": "object", "properties": {"x": {"type": "string"}}}}
        self.assertEqual(rules.schema_depth(arr), 2)
        self.assertEqual(rules.schema_depth({"anyOf": [{"type": "object", "properties": {"x": {}}}]}), 2)
        self.assertEqual(rules.schema_depth({"items": [{"type": "string"}]}), 1)

    def test_garbage_and_runaway_nesting_are_safe(self):
        self.assertEqual(rules.schema_depth("nope"), 0)
        self.assertEqual(rules.schema_depth({"properties": {"a": 5}}), 1)
        deep = {"type": "string"}
        for _ in range(500):
            deep = {"type": "object", "properties": {"x": deep}}
        self.assertGreater(rules.schema_depth(deep), 3)  # capped, no RecursionError


class SchemaRuleTests(unittest.TestCase):
    def test_a_clean_tool_has_no_schema_findings(self):
        self.assertEqual(rules.check_schema(tool()), [])

    def test_p004_missing_or_not_an_object_schema(self):
        cases = [
            ("missing", None),
            ("empty", {}),
            ("string schema", {"type": "string"}),
            ("not a dict", "x"),
        ]
        for label, schema in cases:
            with self.subTest(label):
                t = tool()
                if schema is None:
                    del t["inputSchema"]
                else:
                    t["inputSchema"] = schema
                found = rules.check_schema(t)
                self.assertEqual(ids(found), ["P004"])
                self.assertEqual(found[0]["severity"], "high")

    def test_p001_parameter_without_a_description(self):
        for description in (None, "", "   "):
            with self.subTest(description):
                prop = {"type": "string"}
                if description is not None:
                    prop["description"] = description
                found = rules.check_schema(with_params(q=prop))
                self.assertEqual(ids(found), ["P001"])
                self.assertEqual(found[0]["param"], "q")

    def test_p002_parameter_without_a_type(self):
        found = rules.check_schema(with_params(q={"description": "A search query"}))
        self.assertEqual(ids(found), ["P002"])

    def test_p002_not_raised_when_enum_oneof_anyof_or_ref_stand_in_for_type(self):
        for extra in ({"enum": ["a", "b"]}, {"oneOf": [{"type": "string"}]}, {"anyOf": [{"type": "string"}]}, {"$ref": "#/x"}):
            with self.subTest(extra):
                prop = {"description": "A value"}
                prop.update(extra)
                self.assertEqual(rules.check_schema(with_params(q=prop)), [])

    def test_an_empty_property_schema_is_both_undescribed_and_untyped(self):
        self.assertEqual(ids(rules.check_schema(with_params(q={}))), ["P001", "P002"])
        self.assertEqual(ids(rules.check_schema(with_params(q="nope"))), ["P001", "P002"])

    def test_p003_enum_values_listed_in_prose(self):
        found = rules.check_schema(with_params(order=str_param("Sort order, one of: asc, desc")))
        self.assertEqual(ids(found), ["P003"])
        self.assertEqual(found[0]["data"], {"action": "add-enum", "values": ["asc", "desc"]})
        self.assertEqual(found[0]["evidence"], "asc, desc")
        self.assertEqual(found[0]["param"], "order")

    def test_p003_not_raised_with_an_enum_or_a_non_string_type_or_plain_prose(self):
        self.assertEqual(rules.check_schema(with_params(order={"type": "string", "description": "one of: asc, desc", "enum": ["asc", "desc"]})), [])
        self.assertEqual(rules.check_schema(with_params(order={"type": "integer", "description": "one of: 1, 2"})), [])
        self.assertEqual(rules.check_schema(with_params(path=str_param("Must be a valid path or URL"))), [])

    def test_p005_two_parameters_and_no_required_list(self):
        t = with_params(a=str_param("First value here"), b=str_param("Second value here"))
        for required in (None, []):
            with self.subTest(required):
                if required is None:
                    del t["inputSchema"]["required"]
                else:
                    t["inputSchema"]["required"] = required
                self.assertEqual(ids(rules.check_schema(t)), ["P005"])

    def test_p005_not_raised_with_a_required_list_or_a_single_parameter(self):
        self.assertEqual(rules.check_schema(with_params(a=str_param("First value here"), b=str_param("Second value here"))), [])
        t = with_params(a=str_param("First value here"))
        del t["inputSchema"]["required"]
        self.assertEqual(rules.check_schema(t), [])

    def test_p006_nesting_deeper_than_three_levels(self):
        leaf = {"type": "string", "description": "A leaf value"}
        three = {"type": "object", "description": "a", "properties": {"b": {"type": "object", "description": "b", "properties": {"c": {"type": "object", "description": "c", "properties": {"d": leaf}}}}}}
        t = with_params(a=three)
        self.assertEqual([f["rule"] for f in rules.check_schema(t) if f["rule"] == "P006"], ["P006"])
        shallow = {"type": "object", "description": "a", "properties": {"b": {"type": "object", "description": "b", "properties": {"c": leaf}}}}
        self.assertEqual([f for f in rules.check_schema(with_params(a=shallow)) if f["rule"] == "P006"], [])

    def test_only_top_level_parameters_get_p001_to_p003(self):
        inner = {"type": "object", "description": "wrapper", "properties": {"x": {}}}
        self.assertEqual(rules.check_schema(with_params(a=inner)), [])

    def test_properties_that_is_not_an_object_means_no_parameters(self):
        t = tool()
        t["inputSchema"] = {"type": "object", "properties": "nope"}
        self.assertEqual(rules.check_schema(t), [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_rules.py" 2>&1 | tail -6`
Expected: the new classes ERROR with `AttributeError: module 'mcp_fixer.rules' has no attribute 'extract_enum_values'` / `check_schema` / `schema_depth`; the Task 2 tests still pass.

- [ ] **Step 3: Write the implementation**

Append to `servers/mcp-fixer/src/mcp_fixer/rules.py`:

```python
_TYPE_KEYS = ("type", "enum", "oneOf", "anyOf", "$ref")
_MAX_DEPTH_SCAN = 50

_TRIGGER = re.compile(
    r"\b(?:one of|either|must be|can be|should be|options?|allowed values?|valid values?"
    r"|possible values?|choices?|supported values?)\b[:\s]*",
    re.IGNORECASE,
)
_LEAD = re.compile(r"^(?:(?:are|is)\s+)?(?:(?:the following|these|below)\b)?[:\s]*", re.IGNORECASE)
_SPLIT = re.compile(r"\s*,\s*(?:or\s+|and\s+)?|\s+or\s+|\s*\|\s*|\s*/\s*", re.IGNORECASE)
_SENTENCE_END = re.compile(r"\.(?:\s|$)|\n")
_QUOTED = re.compile(r"""(['"`])([^'"`\n]{1,30})\1""")
_ARTICLE = re.compile(r"^(?:a|an|the)\s", re.IGNORECASE)
_MAX_VALUE_WORDS = 2
_MAX_VALUES = 20


def _clean_values(parts):
    """The values in `parts`, or [] when any part looks like prose instead of a value."""
    values = []
    for part in parts:
        value = part.strip().strip("'\"`()[]{}.,;:").strip()
        if not value:
            continue
        if len(value.split()) > _MAX_VALUE_WORDS or _ARTICLE.match(value):
            return []
        values.append(value)
    return values


def extract_enum_values(text):
    """Allowed values a description lists in prose ('one of: a, b'), in order; [] when none."""
    if not isinstance(text, str):
        return []
    for match in _TRIGGER.finditer(text):
        rest = _SENTENCE_END.split(text[match.end():], maxsplit=1)[0]
        rest = _LEAD.sub("", rest, count=1).strip()
        values = _clean_values(_SPLIT.split(rest))
        if len(values) >= 2:
            return values[:_MAX_VALUES]
    quoted = []
    for found in _QUOTED.finditer(text):
        value = found.group(2).strip()
        if value and value not in quoted:
            quoted.append(value)
    if len(quoted) >= 3:
        return quoted[:_MAX_VALUES]
    return []


def schema_depth(schema, level=0):
    """Levels of nested schemas below `schema` (properties, items, anyOf, oneOf, allOf).

    A schema with no nested schema is 0. Scanning stops at a fixed depth, so a hostile or
    runaway document cannot exhaust the stack.
    """
    if not isinstance(schema, dict):
        return 0
    if level >= _MAX_DEPTH_SCAN:
        return 1
    children = []
    props = schema.get("properties")
    if isinstance(props, dict):
        children.extend(props.values())
    items = schema.get("items")
    if isinstance(items, dict):
        children.append(items)
    elif isinstance(items, list):
        children.extend(items)
    for key in ("anyOf", "oneOf", "allOf"):
        options = schema.get(key)
        if isinstance(options, list):
            children.extend(options)
    if not children:
        return 0
    return 1 + max(schema_depth(child, level + 1) for child in children)


def _has_description(schema):
    text = schema.get("description")
    return isinstance(text, str) and bool(text.strip())


def _describe(schema):
    if schema is None:
        return "missing"
    if isinstance(schema, dict):
        return f"type is {schema.get('type')!r}"
    return f"a {type(schema).__name__}"


def check_schema(tool):
    """P001 to P006: the input schema and its top-level parameters."""
    name = tool["name"]
    schema = tool.get("inputSchema")
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return [
            finding(
                "P004",
                "high",
                "inputSchema is missing or is not an object schema",
                tool=name,
                evidence=_describe(schema),
                fix='Declare inputSchema as {"type": "object", "properties": {...}}.',
                data={"action": "fix-input-schema"},
            )
        ]
    found = []
    raw = schema.get("properties")
    props = raw if isinstance(raw, dict) else {}
    for pname, pschema in props.items():
        pschema = pschema if isinstance(pschema, dict) else {}
        if not _has_description(pschema):
            found.append(
                finding(
                    "P001",
                    "medium",
                    f"parameter '{pname}' has no description",
                    tool=name,
                    param=pname,
                    fix="Say what the value means and what format it takes.",
                    data={"action": "add-param-description"},
                )
            )
        if not any(key in pschema for key in _TYPE_KEYS):
            found.append(
                finding(
                    "P002",
                    "medium",
                    f"parameter '{pname}' has no type",
                    tool=name,
                    param=pname,
                    fix="Declare its type, or an enum of the allowed values.",
                    data={"action": "add-param-type"},
                )
            )
        if pschema.get("type") == "string" and "enum" not in pschema:
            values = extract_enum_values(pschema.get("description"))
            if values:
                found.append(
                    finding(
                        "P003",
                        "medium",
                        f"parameter '{pname}' lists its allowed values in prose but has no enum",
                        tool=name,
                        param=pname,
                        evidence=", ".join(values),
                        fix="Declare them as an enum so the model cannot invent other values.",
                        data={"action": "add-enum", "values": values},
                    )
                )
    required = schema.get("required")
    if len(props) >= 2 and not (isinstance(required, list) and required):
        found.append(
            finding(
                "P005",
                "low",
                f"{len(props)} parameters and no required list",
                tool=name,
                fix="List the parameters the tool cannot work without in required.",
                data={"action": "add-required"},
            )
        )
    depth = schema_depth(schema)
    if depth > THRESHOLDS["max_nesting"]:
        found.append(
            finding(
                "P006",
                "low",
                f"input schema is nested {depth} levels deep",
                tool=name,
                evidence=f"limit {THRESHOLDS['max_nesting']}",
                fix="Flatten the parameters; deeply nested objects are easy to fill in wrongly.",
                data={"depth": depth},
            )
        )
    return found
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -4`
Expected: all tests PASS. If an extraction case fails, adjust the regexes in `rules.py` (not the table in the test) unless the case contradicts the spec's P003 description; the "prose that is not a value list" cases are Review Focus items and must stay.

- [ ] **Step 5: Commit**

```bash
python -m unittest discover -s tests 2>&1 | tail -2
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer schema rules and enum detection

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Scoring and the report

**Files:**
- Create: `servers/mcp-fixer/src/mcp_fixer/score.py`, `servers/mcp-fixer/src/mcp_fixer/report.py`, `servers/mcp-fixer/tests/test_score.py`, `servers/mcp-fixer/tests/test_report.py`

**Interfaces:**
- Consumes: everything `rules.py` exports (Tasks 2 and 3).
- Produces: `score.score_tools(tools, source=None) -> report dict` with keys `schemaVersion`, `source`, `score`, `metrics` (`toolCount`, `estimatedTokens`, `perTool`: name or `name#2` -> `{estimatedTokens, score, findings}`), `findings` (sorted), `notes`; `report.render_json(report) -> str` and `report.render_text(report) -> str`. Task 6 uses all three.

- [ ] **Step 1: Write the failing tests**

`servers/mcp-fixer/tests/test_score.py`:

```python
import unittest

import support  # noqa: F401
from mcp_fixer import score


def clean(name="get_item", description="Fetch a single item by its identifier."):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {"item_id": {"type": "string", "description": "Identifier of the item"}},
            "required": ["item_id"],
        },
    }


def rule_ids(report):
    return [f["rule"] for f in report["findings"]]


class ScoreTests(unittest.TestCase):
    def test_a_clean_server_scores_100(self):
        report = score.score_tools([clean("get_item", "Fetch a single item by its identifier."),
                                    clean("list_orders", "List the orders placed by one customer.")])
        self.assertEqual(report["score"], 100)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["notes"], [])
        self.assertEqual(report["schemaVersion"], 1)

    def test_findings_take_points_off_the_tool(self):
        # "run" is generic (N001, -10) and "Runs it" is 7 characters (D002, -10): 80.
        report = score.score_tools([clean("run", "Runs it")])
        self.assertEqual(report["score"], 80)
        self.assertEqual(rule_ids(report), ["D002", "N001"])
        self.assertEqual(report["metrics"]["perTool"]["run"]["score"], 80)
        self.assertEqual(report["metrics"]["perTool"]["run"]["findings"], 2)

    def test_the_server_score_is_the_mean_rounded_half_up(self):
        # tool scores 75 (D001, high -25) and 100: mean 87.5 -> 88
        broken = clean("alpha_tool", "")
        report = score.score_tools([broken, clean("beta_tool", "Fetch a single item by its identifier.")])
        self.assertEqual(report["score"], 88)

    def test_a_tool_never_scores_below_zero(self):
        props = {f"p{i}": {} for i in range(10)}  # each: P001 + P002 = -20, ten of them
        tool = {"name": "messy_tool", "description": "A tool with plenty of problems in it.",
                "inputSchema": {"type": "object", "properties": props}}
        report = score.score_tools([tool])
        self.assertEqual(report["metrics"]["perTool"]["messy_tool"]["score"], 0)
        self.assertEqual(report["score"], 0)

    def test_t001_takes_five_points_off_the_server(self):
        tools = [clean(f"tool_{i}", f"Describe topic t{i:03d} thoroughly") for i in range(41)]
        report = score.score_tools(tools)
        self.assertEqual(rule_ids(report), ["T001"])
        self.assertEqual(report["score"], 95)

    def test_t002_takes_five_or_fifteen_points_off(self):
        def big(count):
            props = {f"p{i:04d}": {"type": "string", "description": "Parameter number one"} for i in range(count)}
            return {"name": "big_tool", "description": "A tool with a very large input schema.",
                    "inputSchema": {"type": "object", "properties": props, "required": ["p0000"]}}
        medium = score.score_tools([big(800)])
        self.assertEqual((rule_ids(medium), medium["score"]), (["T002"], 95))
        high = score.score_tools([big(2000)])
        self.assertEqual((rule_ids(high), high["score"]), (["T002"], 85))

    def test_n002_takes_four_points_off(self):
        report = score.score_tools([clean("get_item", "Fetch a single item by its identifier."),
                                    clean("listItems", "List the orders placed by one customer.")])
        self.assertEqual((rule_ids(report), report["score"]), (["N002"], 96))

    def test_penalties_stack_and_the_score_is_clamped(self):
        tools = [clean(f"tool_{i}", f"Describe topic t{i:03d} thoroughly") for i in range(41)]
        tools[0]["name"] = "listItems"  # N002 (-4) on top of T001 (-5)
        report = score.score_tools(tools)
        self.assertEqual(report["score"], 91)
        report = score.score_tools([{"name": f"t{i}"} for i in range(200)] + ["bad"] * 20)
        self.assertEqual(report["score"], 0)

    def test_a_malformed_entry_costs_25_and_is_skipped(self):
        report = score.score_tools([clean(), "oops"])
        self.assertEqual(rule_ids(report), ["M001"])
        self.assertEqual(report["score"], 75)
        self.assertEqual(report["metrics"]["toolCount"], 1)
        self.assertEqual(list(report["metrics"]["perTool"]), ["get_item"])

    def test_an_empty_list_scores_100_with_a_note(self):
        report = score.score_tools([])
        self.assertEqual((report["score"], report["findings"]), (100, []))
        self.assertEqual(report["notes"], ["no tools listed"])
        self.assertEqual(report["metrics"]["toolCount"], 0)

    def test_duplicate_names_are_scored_as_separate_entries(self):
        report = score.score_tools([clean(), clean()])
        self.assertEqual(list(report["metrics"]["perTool"]), ["get_item", "get_item#2"])
        self.assertEqual(rule_ids(report), ["D004", "D004"])
        self.assertEqual(report["score"], 90)

    def test_pair_findings_count_against_both_tools(self):
        a = clean("alpha_tool", "Search the catalog for products.")
        b = clean("beta_tool", "Search the catalog for products.")
        report = score.score_tools([a, b])
        self.assertEqual([report["metrics"]["perTool"][k]["score"] for k in ("alpha_tool", "beta_tool")], [90, 90])

    def test_metrics_count_tokens(self):
        report = score.score_tools([clean(), clean("list_orders", "List the orders placed by one customer.")])
        per = report["metrics"]["perTool"]
        self.assertEqual(report["metrics"]["estimatedTokens"], sum(v["estimatedTokens"] for v in per.values()))
        self.assertGreater(report["metrics"]["estimatedTokens"], 0)

    def test_source_defaults_to_a_file_with_unknown_server_details(self):
        self.assertEqual(score.score_tools([])["source"],
                         {"kind": "file", "protocolVersion": None, "serverName": None, "serverVersion": None})
        given = {"kind": "stdio", "protocolVersion": "2025-06-18", "serverName": "x", "serverVersion": "1"}
        self.assertEqual(score.score_tools([], given)["source"], given)

    def test_findings_are_sorted_and_stable(self):
        tools = [clean("zeta_tool", ""), clean("alpha_tool", "")]
        first = score.score_tools(tools)
        self.assertEqual([f["tool"] for f in first["findings"]], ["alpha_tool", "zeta_tool"])
        self.assertEqual(first, score.score_tools(tools))

    def test_non_ascii_text_is_fine(self):
        report = score.score_tools([clean("recuperer", "R\u00e9cup\u00e8re l'\u00e9l\u00e9ment \u2014 \u65e5\u672c\u8a9e is supported")])
        self.assertEqual(report["findings"], [])


if __name__ == "__main__":
    unittest.main()
```

`servers/mcp-fixer/tests/test_report.py`:

```python
import json
import unittest

import support  # noqa: F401
from mcp_fixer import report as report_module
from mcp_fixer import score


def sample_tools():
    good = {"name": "beta_tool", "description": "Fetch a single item by its identifier.",
            "inputSchema": {"type": "object", "properties": {"item_id": {"type": "string", "description": "Identifier of the item"}}, "required": ["item_id"]}}
    broken = dict(good, name="alpha_tool", description="")
    return [broken, good]


class JsonTests(unittest.TestCase):
    def test_json_parses_and_keeps_the_pinned_shape(self):
        data = json.loads(report_module.render_json(score.score_tools(sample_tools())))
        self.assertEqual(list(data), ["schemaVersion", "source", "score", "metrics", "findings", "notes"])
        self.assertEqual(data["score"], 88)
        self.assertEqual(list(data["metrics"]), ["toolCount", "estimatedTokens", "perTool"])
        self.assertEqual(
            list(data["findings"][0]),
            ["rule", "severity", "tool", "param", "message", "evidence", "fix", "data"],
        )

    def test_json_is_byte_identical_on_a_repeat_run(self):
        first = report_module.render_json(score.score_tools(sample_tools()))
        second = report_module.render_json(score.score_tools(sample_tools()))
        self.assertEqual(first, second)
        self.assertTrue(first.endswith("\n"))

    def test_json_keeps_non_ascii_text_readable(self):
        tool = {"name": "recuperer", "description": "R\u00e9cup\u00e8re l'\u00e9l\u00e9ment \u2014 \u65e5\u672c\u8a9e",
                "inputSchema": {"type": "object", "properties": {}}}
        text = report_module.render_json(score.score_tools([tool]))
        self.assertNotIn("\\u", text)


class TextTests(unittest.TestCase):
    def setUp(self):
        self.text = report_module.render_text(score.score_tools(sample_tools()))

    def test_headline_and_metrics(self):
        self.assertIn("mcp-fixer score: 88/100", self.text)
        self.assertIn("source: tool list file", self.text)
        self.assertRegex(self.text, r"tools: 2, estimated definition size: [\d,]+ tokens")

    def test_per_tool_table_and_findings(self):
        self.assertIn("alpha_tool", self.text)
        self.assertIn("beta_tool", self.text)
        self.assertIn("[high] D001 alpha_tool: no description", self.text)
        self.assertIn("fix:", self.text)

    def test_server_findings_are_labelled_server(self):
        tools = sample_tools()
        tools.append(dict(tools[1], name="listItems", description="List the orders placed by one customer."))
        text = report_module.render_text(score.score_tools(tools))
        self.assertIn("N002 server: tool names mix naming styles", text)

    def test_param_findings_name_the_parameter(self):
        tool = {"name": "get_item", "description": "Fetch a single item by its identifier.",
                "inputSchema": {"type": "object", "properties": {"q": {}}, "required": ["q"]}}
        text = report_module.render_text(score.score_tools([tool]))
        self.assertIn("P001 get_item.q:", text)

    def test_stdio_source_shows_the_server(self):
        source = {"kind": "stdio", "protocolVersion": "2025-06-18", "serverName": "fake-server", "serverVersion": "1.2.3"}
        text = report_module.render_text(score.score_tools(sample_tools(), source))
        self.assertIn("server: fake-server 1.2.3 (protocol 2025-06-18)", text)

    def test_an_empty_list_shows_the_note(self):
        text = report_module.render_text(score.score_tools([]))
        self.assertIn("mcp-fixer score: 100/100", text)
        self.assertIn("note: no tools listed", text)

    def test_non_ascii_text_renders(self):
        tool = {"name": "recuperer", "description": "", "inputSchema": {"type": "object", "properties": {}}}
        tool["description"] = ""
        text = report_module.render_text(score.score_tools([tool]))
        self.assertIsInstance(text, str)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_score.py" 2>&1 | tail -4`
Expected: ERROR, `ImportError: cannot import name 'score' from 'mcp_fixer'`.

- [ ] **Step 3: Write the scoring**

`servers/mcp-fixer/src/mcp_fixer/score.py`:

```python
"""Pure scoring: a list of MCP tool definitions in, a report dict out."""
import math

from . import rules

EMPTY_NOTE = "no tools listed"
FILE_SOURCE = {"kind": "file", "protocolVersion": None, "serverName": None, "serverVersion": None}


def _round_half_up(value):
    return int(math.floor(value + 0.5))


def _unique_keys(names):
    """name, name#2, name#3 ... so duplicate tool names keep separate entries."""
    seen = {}
    keys = []
    for name in names:
        seen[name] = seen.get(name, 0) + 1
        keys.append(name if seen[name] == 1 else f"{name}#{seen[name]}")
    return keys


def _tool_score(findings):
    return max(0, 100 - sum(rules.SEVERITY_PENALTY[f["severity"]] for f in findings))


def _server_penalty(finding):
    penalty = rules.SERVER_PENALTY[finding["rule"]]
    return penalty[finding["severity"]] if isinstance(penalty, dict) else penalty


def _sort_key(finding):
    return (
        finding["tool"] or "",
        finding["rule"],
        finding["param"] or "",
        finding["evidence"],
        finding["message"],
    )


def score_tools(tools, source=None):
    valid = []
    server_findings = []
    for index, entry in enumerate(tools):
        if isinstance(entry, dict) and isinstance(entry.get("name"), str) and entry["name"]:
            valid.append(entry)
        else:
            server_findings.append(rules.malformed_finding(index, entry))

    by_tool = [[] for _ in valid]
    for position, tool in enumerate(valid):
        by_tool[position].extend(rules.check_description(tool))
        by_tool[position].extend(rules.check_schema(tool))
        by_tool[position].extend(rules.check_name(tool))
    for position, finding in rules.check_duplicates(valid):
        by_tool[position].append(finding)
    server_findings.extend(rules.check_server(valid))

    per_tool = {}
    for key, tool, findings in zip(_unique_keys([t["name"] for t in valid]), valid, by_tool):
        per_tool[key] = {
            "estimatedTokens": rules.estimate_tokens(tool),
            "score": _tool_score(findings),
            "findings": len(findings),
        }
    scores = [entry["score"] for entry in per_tool.values()]
    mean = sum(scores) / len(scores) if scores else 100
    penalty = sum(_server_penalty(f) for f in server_findings)
    total = min(100, max(0, _round_half_up(mean - penalty)))

    findings = sorted(
        [f for group in by_tool for f in group] + server_findings, key=_sort_key
    )
    notes = [EMPTY_NOTE] if not tools else []
    return {
        "schemaVersion": 1,
        "source": dict(source) if source else dict(FILE_SOURCE),
        "score": total,
        "metrics": {
            "toolCount": len(valid),
            "estimatedTokens": sum(entry["estimatedTokens"] for entry in per_tool.values()),
            "perTool": per_tool,
        },
        "findings": findings,
        "notes": notes,
    }
```

- [ ] **Step 4: Write the report rendering**

`servers/mcp-fixer/src/mcp_fixer/report.py`:

```python
"""Rendering a score report as JSON (for programs) or text (for people)."""
import json


def render_json(report):
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def _source_line(source):
    if source.get("kind") == "stdio":
        who = " ".join(x for x in (source.get("serverName"), source.get("serverVersion")) if x)
        line = f"server: {who or 'unnamed server'}"
        if source.get("protocolVersion"):
            line += f" (protocol {source['protocolVersion']})"
        return line
    return "source: tool list file"


def render_text(report):
    metrics = report["metrics"]
    lines = [
        f"mcp-fixer score: {report['score']}/100",
        _source_line(report["source"]),
        f"tools: {metrics['toolCount']}, estimated definition size: {metrics['estimatedTokens']:,} tokens",
    ]
    for note in report["notes"]:
        lines.append(f"note: {note}")
    per_tool = metrics["perTool"]
    if per_tool:
        width = max(len(name) for name in per_tool)
        lines += ["", f"{'tool'.ljust(width)}  score  findings  tokens"]
        for name, entry in per_tool.items():
            lines.append(
                f"{name.ljust(width)}  {entry['score']:>5}  {entry['findings']:>8}  {entry['estimatedTokens']:>6}"
            )
    if report["findings"]:
        lines += ["", "findings"]
        for f in report["findings"]:
            where = f["tool"] or "server"
            if f["param"]:
                where += f".{f['param']}"
            lines.append(f"  [{f['severity']}] {f['rule']} {where}: {f['message']}")
            if f["evidence"]:
                lines.append(f"      evidence: {f['evidence']}")
            if f["fix"]:
                lines.append(f"      fix: {f['fix']}")
    return "\n".join(lines) + "\n"
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -4`
Expected: all tests PASS. If an arithmetic test disagrees with the code, recompute by hand from the spec's formula first, and fix the implementation only if the formula is not what the spec says.

- [ ] **Step 6: Commit**

```bash
python -m unittest discover -s tests 2>&1 | tail -2
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer scoring and text and JSON reports

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: The stdio client and its fake server

**Files:**
- Create: `servers/mcp-fixer/src/mcp_fixer/stdio_client.py`, `servers/mcp-fixer/tests/fake_server.py`, `servers/mcp-fixer/tests/test_stdio_client.py`

**Interfaces:**
- Consumes: `tests/support.py` (Task 1).
- Produces: `stdio_client.ClientError(Exception)`; `stdio_client.list_tools_stdio(command, env=None, timeout=30.0) -> (tools, info)` where `tools` is the list of tool dicts exactly as received and `info = {"protocolVersion": str|None, "serverName": str|None, "serverVersion": str|None}`; `stdio_client.resolve_command(command) -> argv`. Task 6 uses `list_tools_stdio` and `ClientError`.

- [ ] **Step 1: Write the fake server**

`servers/mcp-fixer/tests/fake_server.py`:

```python
"""A tiny stdio MCP server for the client tests. The behavior is chosen with --mode."""
import argparse
import json
import os
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--mode", default="normal")
parser.add_argument("--tools")
parser.add_argument("--page-size", type=int, default=0)
parser.add_argument("--pid-file")
args = parser.parse_args()

if args.pid_file:
    with open(args.pid_file, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))

TOOLS = []
if args.tools:
    with open(args.tools, encoding="utf-8") as handle:
        TOOLS = json.load(handle)


def send(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def tools_page(params):
    cursor = (params or {}).get("cursor")
    start = int(cursor) if cursor else 0
    if args.mode == "forever":
        return {
            "tools": [{"name": f"t{start}", "description": "x" * 25, "inputSchema": {"type": "object"}}],
            "nextCursor": str(start + 1),
        }
    if args.page_size:
        result = {"tools": TOOLS[start:start + args.page_size]}
        if start + args.page_size < len(TOOLS):
            result["nextCursor"] = str(start + args.page_size)
        return result
    return {"tools": TOOLS}


if args.mode == "exit":
    sys.exit(4)
if args.mode == "noisy":
    for junk in ("Fake server starting up...", "{not json", "[1, 2, 3]", ""):
        sys.stdout.write(junk + "\n")
    sys.stdout.flush()

waiting_for_ping = False
held = None

for line in sys.stdin:
    try:
        message = json.loads(line)
    except ValueError:
        continue
    if not isinstance(message, dict):
        continue
    method = message.get("method")
    mid = message.get("id")
    if method is None:
        if mid == "ping-1" and waiting_for_ping:
            waiting_for_ping = False
            if held is not None:
                send({"jsonrpc": "2.0", "id": held[0], "result": tools_page(held[1])})
                held = None
        continue
    if method == "initialize":
        if args.mode == "hang":
            time.sleep(60)
        if args.mode == "error":
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "Unsupported protocol version"}})
            continue
        send(
            {
                "jsonrpc": "2.0",
                "id": mid,
                "result": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "fake-server", "version": "1.2.3"},
                },
            }
        )
        if args.mode == "crash":
            sys.exit(3)
    elif method == "notifications/initialized":
        if args.mode == "ping":
            waiting_for_ping = True
            send({"jsonrpc": "2.0", "id": "ping-1", "method": "ping"})
    elif method == "tools/list":
        if args.mode == "hang-list":
            time.sleep(60)
        if args.mode == "slow":
            time.sleep(0.2)
        if args.mode == "badresult":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": "nope"}})
            continue
        if waiting_for_ping:
            held = (mid, message.get("params"))
            continue
        send({"jsonrpc": "2.0", "id": mid, "result": tools_page(message.get("params"))})
```

- [ ] **Step 2: Write the failing tests**

`servers/mcp-fixer/tests/test_stdio_client.py`:

```python
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import support
from mcp_fixer import stdio_client
from mcp_fixer.stdio_client import ClientError, list_tools_stdio

TOOLS = [
    {"name": f"tool_{i}", "description": f"Describe topic t{i:03d} thoroughly",
     "inputSchema": {"type": "object", "properties": {}}}
    for i in range(5)
]


class ClientCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.tools_file = self.dir / "tools.json"
        self.tools_file.write_text(json.dumps(TOOLS), encoding="utf-8")

    def command(self, mode="normal", *extra, pid_file=None):
        argv = [sys.executable, str(support.FAKE_SERVER), "--mode", mode, "--tools", str(self.tools_file), *extra]
        if pid_file:
            argv += ["--pid-file", str(pid_file)]
        return argv

    def assert_error(self, mode, fragment, timeout=5, *extra):
        started = time.monotonic()
        with self.assertRaises(ClientError) as ctx:
            list_tools_stdio(self.command(mode, *extra), timeout=timeout)
        self.assertIn(fragment, str(ctx.exception))
        self.assertNotIn("\n", str(ctx.exception))
        return time.monotonic() - started


class HappyPathTests(ClientCase):
    def test_normal_handshake_returns_the_tools_and_server_info(self):
        tools, info = list_tools_stdio(self.command("normal"), timeout=10)
        self.assertEqual(tools, TOOLS)
        self.assertEqual(info, {"protocolVersion": "2025-06-18", "serverName": "fake-server", "serverVersion": "1.2.3"})

    def test_paginated_tools_list_is_followed_to_the_end(self):
        tools, _ = list_tools_stdio(self.command("normal", "--page-size", "2"), timeout=10)
        self.assertEqual(tools, TOOLS)

    def test_junk_on_stdout_is_ignored(self):
        tools, _ = list_tools_stdio(self.command("noisy"), timeout=10)
        self.assertEqual(tools, TOOLS)

    def test_a_ping_request_from_the_server_is_answered(self):
        # The fake server holds back tools/list until its ping has been answered.
        tools, _ = list_tools_stdio(self.command("ping"), timeout=10)
        self.assertEqual(tools, TOOLS)

    def test_a_slow_but_in_time_server_works(self):
        tools, _ = list_tools_stdio(self.command("slow"), timeout=10)
        self.assertEqual(tools, TOOLS)

    def test_the_server_process_is_gone_afterwards(self):
        pid_file = self.dir / "pid"
        list_tools_stdio(self.command("normal", pid_file=pid_file), timeout=10)
        self.assertTrue(support.wait_until_gone(int(pid_file.read_text())))

    def test_the_server_only_sees_the_base_environment_and_what_is_passed(self):
        os.environ["MCP_FIXER_SECRET_FOR_TEST"] = "do-not-leak"
        self.addCleanup(os.environ.pop, "MCP_FIXER_SECRET_FOR_TEST", None)
        env = stdio_client.child_environment({"API_KEY": "abc"})
        self.assertNotIn("MCP_FIXER_SECRET_FOR_TEST", env)
        self.assertEqual(env["API_KEY"], "abc")
        self.assertIn("PATH", env)


class MisbehavingServerTests(ClientCase):
    def test_a_server_that_never_answers_initialize_times_out_and_is_killed(self):
        pid_file = self.dir / "pid"
        started = time.monotonic()
        with self.assertRaises(ClientError) as ctx:
            list_tools_stdio(self.command("hang", pid_file=pid_file), timeout=0.8)
        self.assertIn("timed out", str(ctx.exception))
        self.assertLess(time.monotonic() - started, 8)
        self.assertTrue(support.wait_until_gone(int(pid_file.read_text())))

    def test_a_server_that_never_answers_tools_list_times_out_and_is_killed(self):
        pid_file = self.dir / "pid"
        with self.assertRaises(ClientError) as ctx:
            list_tools_stdio(self.command("hang-list", pid_file=pid_file), timeout=0.8)
        self.assertIn("timed out", str(ctx.exception))
        self.assertTrue(support.wait_until_gone(int(pid_file.read_text())))

    def test_a_crash_after_initialize(self):
        self.assert_error("crash", "the server")

    def test_a_server_that_exits_at_once(self):
        self.assert_error("exit", "exited with code 4")

    def test_an_error_response_to_initialize(self):
        self.assert_error("error", "Unsupported protocol version")

    def test_a_bad_tools_value(self):
        self.assert_error("badresult", "tools array")

    def test_endless_paging_stops(self):
        started = time.monotonic()
        self.assert_error("forever", "pages", timeout=20)
        self.assertLess(time.monotonic() - started, 20)

    def test_the_whole_connection_is_capped(self):
        # Every page comes back in time, but there are too many of them for the overall cap.
        big = [{"name": f"t{i}", "description": "x" * 25, "inputSchema": {"type": "object"}} for i in range(100)]
        self.tools_file.write_text(json.dumps(big), encoding="utf-8")
        started = time.monotonic()
        with self.assertRaises(ClientError) as ctx:
            list_tools_stdio(self.command("slow", "--page-size", "1"), timeout=0.5)
        self.assertIn("timed out", str(ctx.exception))
        self.assertLess(time.monotonic() - started, 10)

    def test_a_command_that_does_not_exist(self):
        with self.assertRaises(ClientError) as ctx:
            list_tools_stdio(["definitely-not-a-real-command-xyz"], timeout=5)
        self.assertIn("cannot find the server command", str(ctx.exception))

    def test_an_empty_command(self):
        with self.assertRaises(ClientError):
            list_tools_stdio([], timeout=5)

    def test_a_server_that_is_not_an_mcp_server_at_all(self):
        with self.assertRaises(ClientError):
            list_tools_stdio([sys.executable, "-c", "print('hello'); import sys; sys.stdin.read()"], timeout=1.5)


@unittest.skipUnless(os.name == "nt", "a .cmd launcher only exists on Windows")
class WindowsLauncherTests(ClientCase):
    def test_a_cmd_shim_is_resolved_and_run(self):
        shim = self.dir / "launcher.cmd"
        shim.write_text(
            f'@echo off\r\n"{sys.executable}" "{support.FAKE_SERVER}" --mode normal --tools "{self.tools_file}"\r\n',
            encoding="utf-8",
        )
        tools, _ = list_tools_stdio([str(shim)], timeout=10)
        self.assertEqual(tools, TOOLS)


class ResolveCommandTests(unittest.TestCase):
    def test_a_real_program_resolves_to_a_path(self):
        argv = stdio_client.resolve_command([sys.executable, "-V"])
        self.assertEqual(argv[1:], ["-V"])
        self.assertTrue(os.path.exists(argv[0]))

    def test_a_missing_program_is_a_client_error(self):
        with self.assertRaises(ClientError):
            stdio_client.resolve_command(["definitely-not-a-real-command-xyz"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_stdio_client.py" 2>&1 | tail -4`
Expected: ERROR, `ImportError: cannot import name 'stdio_client' from 'mcp_fixer'`.

- [ ] **Step 4: Write the client**

`servers/mcp-fixer/src/mcp_fixer/stdio_client.py`:

```python
"""A minimal MCP stdio client: initialize, then page through tools/list. Read-only.

Only `initialize`, `notifications/initialized` and `tools/list` are ever sent (and the server's
`ping` is answered); no tool is ever called. Standard library only.
"""
import json
import os
import queue
import shutil
import signal
import subprocess
import threading
import time

from . import __version__

PROTOCOL_VERSION = "2025-06-18"
MAX_PAGES = 200
OVERALL_TIMEOUT_FACTOR = 4
STDERR_TAIL_BYTES = 8192
SHUTDOWN_WAIT_SECONDS = 2.0

# What a spawned server inherits from this process; everything else must be passed with --env.
BASE_ENV_KEYS = (
    "PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "HOME", "USERPROFILE",
    "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "LANG",
)


class ClientError(Exception):
    """A problem with the server connection, reported as one line."""


def resolve_command(command):
    """The argv to run: the program resolved to a full path (so Windows .cmd shims work)."""
    if not command or not command[0]:
        raise ClientError("no server command given")
    program = shutil.which(command[0])
    if program is None:
        raise ClientError(f"cannot find the server command: {command[0]}")
    return [program] + list(command[1:])


def child_environment(extra=None):
    env = {key: os.environ[key] for key in BASE_ENV_KEYS if key in os.environ}
    env.update(extra or {})
    return env


def _kill_tree(proc, graceful):
    """Stop the server and any children it started."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10
            )
            return
        os.killpg(proc.pid, signal.SIGTERM if graceful else signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        try:
            proc.kill()
        except OSError:
            pass


class _Session:
    def __init__(self, proc, timeout):
        self.proc = proc
        self.timeout = timeout
        self.deadline = time.monotonic() + timeout * OVERALL_TIMEOUT_FACTOR
        self.next_id = 0
        self.inbox = queue.Queue()
        self.stderr_tail = b""
        self.closed = False
        for target in (self._read_stdout, self._read_stderr):
            threading.Thread(target=target, daemon=True).start()

    # --- reader threads -------------------------------------------------------------------
    def _read_stdout(self):
        try:
            for raw in self.proc.stdout:
                try:
                    message = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if isinstance(message, dict):
                    self.inbox.put(message)
        except (OSError, ValueError):
            pass
        self.inbox.put(None)

    def _read_stderr(self):
        try:
            while True:
                chunk = self.proc.stderr.read1(1024) if hasattr(self.proc.stderr, "read1") else self.proc.stderr.read(1024)
                if not chunk:
                    break
                self.stderr_tail = (self.stderr_tail + chunk)[-STDERR_TAIL_BYTES:]
        except (OSError, ValueError):
            pass

    # --- helpers ---------------------------------------------------------------------------
    def hint(self):
        lines = [
            line.strip()
            for line in self.stderr_tail.decode("utf-8", errors="replace").splitlines()
            if line.strip()
        ]
        return f"; the server said: {lines[-1][:200]}" if lines else ""

    def _send(self, message):
        try:
            self.proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError):
            code = self.proc.poll()
            if code is None:
                try:
                    code = self.proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    code = None
            if code is not None:
                raise ClientError(f"the server exited with code {code}" + self.hint()) from None
            raise ClientError("the server closed its input" + self.hint()) from None

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def _answer_server_request(self, message):
        if message.get("method") == "ping":
            self._send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
        else:
            self._send(
                {"jsonrpc": "2.0", "id": message["id"],
                 "error": {"code": -32601, "message": "method not supported by this client"}}
            )

    def request(self, method, params=None):
        self.next_id += 1
        request_id = self.next_id
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)
        limit = min(time.monotonic() + self.timeout, self.deadline)
        while True:
            remaining = limit - time.monotonic()
            if remaining <= 0:
                raise ClientError(f"timed out waiting for {method}" + self.hint())
            try:
                incoming = self.inbox.get(timeout=remaining)
            except queue.Empty:
                continue
            if incoming is None:
                try:
                    code = self.proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    code = None
                if code is None:
                    raise ClientError("the server closed its output" + self.hint())
                raise ClientError(f"the server exited with code {code} before answering {method}" + self.hint())
            if "method" in incoming and "id" in incoming:
                self._answer_server_request(incoming)
                continue
            if incoming.get("id") != request_id:
                continue
            if "error" in incoming:
                error = incoming["error"]
                text = error.get("message") if isinstance(error, dict) else error
                raise ClientError(f"{method} failed: {text}")
            result = incoming.get("result")
            return result if isinstance(result, dict) else {}

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.proc.wait(timeout=SHUTDOWN_WAIT_SECONDS)
            return
        except subprocess.TimeoutExpired:
            pass
        _kill_tree(self.proc, graceful=True)
        try:
            self.proc.wait(timeout=SHUTDOWN_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_tree(self.proc, graceful=False)
            try:
                self.proc.wait(timeout=SHUTDOWN_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                pass


def _spawn(argv, env):
    kwargs = {}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            **kwargs,
        )
    except OSError as exc:
        raise ClientError(f"cannot start the server: {exc.strerror or exc}") from None


def list_tools_stdio(command, env=None, timeout=30.0):
    """Start a stdio MCP server, read its tools, shut it down. Returns (tools, info)."""
    argv = resolve_command(command)
    proc = _spawn(argv, child_environment(env))
    session = _Session(proc, timeout)
    try:
        init = session.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp-fixer", "version": __version__},
            },
        )
        server = init.get("serverInfo") if isinstance(init.get("serverInfo"), dict) else {}
        info = {
            "protocolVersion": init.get("protocolVersion") if isinstance(init.get("protocolVersion"), str) else None,
            "serverName": server.get("name") if isinstance(server.get("name"), str) else None,
            "serverVersion": server.get("version") if isinstance(server.get("version"), str) else None,
        }
        session.notify("notifications/initialized")
        tools = []
        cursor = None
        for _ in range(MAX_PAGES):
            result = session.request("tools/list", {"cursor": cursor} if cursor else None)
            page = result.get("tools")
            if not isinstance(page, list):
                raise ClientError("tools/list did not return a tools array")
            tools.extend(page)
            cursor = result.get("nextCursor")
            if not cursor:
                return tools, info
        raise ClientError(f"tools/list kept returning pages (stopped after {MAX_PAGES} pages)")
    finally:
        session.close()
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_stdio_client.py" -v 2>&1 | tail -30`
Expected: every test PASSES (the Windows launcher test is skipped on other systems). If a process-gone test fails, the process tree was not killed: fix `_kill_tree`/`close`, do not weaken `wait_until_gone`. If `test_a_crash_after_initialize` fails because the message lacks "the server", read the message and make it say so (it is the "closed its output" or "exited with code" wording); the point is a one-line error, not a traceback.

- [ ] **Step 6: Run the whole server suite and the repo checks, then commit**

```bash
python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -3
python -m unittest discover -s tests 2>&1 | tail -2
python scripts/validate.py
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer read-only MCP stdio client and fake server

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: The command line

**Files:**
- Create: `servers/mcp-fixer/src/mcp_fixer/cli.py`, `servers/mcp-fixer/src/mcp_fixer/__main__.py`, `servers/mcp-fixer/tests/test_cli.py`, `servers/mcp-fixer/tests/fixtures/clean_tools.json`, `servers/mcp-fixer/tests/fixtures/messy_tools.json`

**Interfaces:**
- Consumes: `score.score_tools`, `report.render_text`/`render_json` (Task 4), `stdio_client.list_tools_stdio`/`ClientError` (Task 5).
- Produces: `cli.main(argv=None) -> int` (0, 1 or 2); `python -m mcp_fixer`; the console script `mcp-fixer` from `pyproject.toml`.

- [ ] **Step 1: Write the fixtures**

`servers/mcp-fixer/tests/fixtures/clean_tools.json`:

```json
{
  "tools": [
    {
      "name": "get_item",
      "description": "Fetch a single item by its identifier.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "item_id": {"type": "string", "description": "Identifier of the item"}
        },
        "required": ["item_id"]
      }
    },
    {
      "name": "list_orders",
      "description": "List the orders placed by one customer.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "customer_id": {"type": "string", "description": "Identifier of the customer"},
          "status": {"type": "string", "description": "Order status", "enum": ["open", "shipped", "cancelled"]}
        },
        "required": ["customer_id"]
      }
    }
  ]
}
```

`servers/mcp-fixer/tests/fixtures/messy_tools.json` (a bare array, with problems on purpose):

```json
[
  {
    "name": "run",
    "description": "Runs it",
    "inputSchema": {
      "type": "object",
      "properties": {
        "order": {"type": "string", "description": "Sort order, one of: asc, desc"},
        "q": {}
      }
    }
  },
  {
    "name": "searchItems",
    "description": "",
    "inputSchema": {"type": "object", "properties": {}}
  },
  {
    "name": "list_items",
    "description": "List the items in the store.",
    "inputSchema": {"type": "object", "properties": {}}
  }
]
```

- [ ] **Step 2: Write the failing tests**

`servers/mcp-fixer/tests/test_cli.py`:

```python
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import support
from mcp_fixer import cli

FIXTURES = support.TESTS / "fixtures"
CLEAN = str(FIXTURES / "clean_tools.json")
MESSY = str(FIXTURES / "messy_tools.json")


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(list(argv))
        except SystemExit as exc:  # argparse's own usage errors
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, text):
        path = self.dir / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def assert_usage_error(self, *argv, fragment=None):
        code, out, err = run(*argv)
        self.assertEqual(code, 2, (out, err))
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("error: "), err)
        self.assertEqual(err.count("\n"), 1, err)
        self.assertNotIn("Traceback", err)
        if fragment:
            self.assertIn(fragment, err)


class FileModeTests(CliCase):
    def test_a_clean_file_scores_100_as_text(self):
        code, out, err = run("score", "--tools-json", CLEAN)
        self.assertEqual((code, err), (0, ""))
        self.assertIn("mcp-fixer score: 100/100", out)

    def test_json_format(self):
        code, out, _ = run("score", "--tools-json", MESSY, "--format", "json")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["schemaVersion"], 1)
        self.assertEqual(data["source"]["kind"], "file")
        rules = {f["rule"] for f in data["findings"]}
        self.assertTrue({"D001", "D002", "N001", "P001", "P002", "P003", "N002"} <= rules, rules)

    def test_the_messy_file_scores_70_by_hand(self):
        # run: D002 + N001 + P003 + P001 + P002 (10 each) + P005 (4) = -54 -> 46
        # searchItems: D001 (-25) -> 75; list_items: clean -> 100
        # mean 73.67, minus 4 for mixed naming styles (N002) = 69.67 -> 70
        _, out, _ = run("score", "--tools-json", MESSY, "--format", "json")
        self.assertEqual(json.loads(out)["score"], 70)

    def test_a_bare_array_and_an_object_with_tools_both_work(self):
        tools = json.loads(Path(CLEAN).read_text(encoding="utf-8"))["tools"]
        bare = self.write("bare.json", json.dumps(tools))
        self.assertEqual(run("score", "--tools-json", bare)[0], 0)

    def test_a_bom_is_tolerated(self):
        path = self.dir / "bom.json"
        path.write_bytes(b"\xef\xbb\xbf" + Path(CLEAN).read_bytes())
        self.assertEqual(run("score", "--tools-json", str(path))[0], 0)

    def test_the_same_file_gives_byte_identical_json(self):
        first = run("score", "--tools-json", MESSY, "--format", "json")[1]
        second = run("score", "--tools-json", MESSY, "--format", "json")[1]
        self.assertEqual(first, second)

    def test_non_ascii_text_report_does_not_crash(self):
        path = self.write("na.json", json.dumps([{"name": "recuperer", "description": "", "inputSchema": {"type": "object", "properties": {}}, "title": "\u65e5\u672c\u8a9e"}], ensure_ascii=False))
        code, out, err = run("score", "--tools-json", path)
        self.assertEqual((code, err), (0, ""))


class MinScoreAndOutTests(CliCase):
    def test_min_score_passes_at_the_boundary_and_fails_below(self):
        _, out, _ = run("score", "--tools-json", MESSY, "--format", "json")
        score = json.loads(out)["score"]
        self.assertEqual(run("score", "--tools-json", MESSY, "--min-score", str(score))[0], 0)
        code, text, err = run("score", "--tools-json", MESSY, "--min-score", str(score + 1))
        self.assertEqual((code, err), (1, ""))
        self.assertIn("mcp-fixer score:", text)  # the report is still printed

    def test_out_writes_the_report_to_the_file_instead_of_stdout(self):
        target = self.dir / "report.json"
        code, out, err = run("score", "--tools-json", MESSY, "--format", "json", "--out", str(target))
        self.assertEqual((code, out, err), (0, "", ""))
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["schemaVersion"], 1)
        self.assertNotIn("\r", target.read_bytes().decode("utf-8"))

    def test_an_unwritable_out_is_a_usage_error(self):
        self.assert_usage_error(
            "score", "--tools-json", CLEAN, "--out", str(self.dir / "no-such-dir" / "r.json"),
            fragment="cannot write",
        )


class UsageErrorTests(CliCase):
    def test_neither_input_mode(self):
        self.assert_usage_error("score", fragment="--tools-json")

    def test_both_input_modes(self):
        self.assert_usage_error("score", "--tools-json", CLEAN, "--", sys.executable, "-V", fragment="not both")

    def test_a_missing_file(self):
        self.assert_usage_error("score", "--tools-json", str(self.dir / "nope.json"), fragment="cannot read")

    def test_a_file_that_is_not_json(self):
        self.assert_usage_error("score", "--tools-json", self.write("bad.json", "{not json"), fragment="not valid JSON")

    def test_a_file_that_is_not_utf8(self):
        path = self.dir / "latin.json"
        path.write_bytes(b"\x80\x81\x82")
        self.assert_usage_error("score", "--tools-json", str(path), fragment="UTF-8")

    def test_a_file_with_the_wrong_shape(self):
        for text in ('{"foo": []}', '"just a string"', "5", '{"tools": "x"}'):
            with self.subTest(text):
                self.assert_usage_error("score", "--tools-json", self.write("shape.json", text), fragment="must be a JSON array")

    def test_a_bad_env_pair(self):
        for pair in ("NOEQUALS", "=value"):
            with self.subTest(pair):
                self.assert_usage_error("score", "--env", pair, "--", sys.executable, "-V", fragment="KEY=VALUE")

    def test_bad_numbers(self):
        for flag, value in (("--timeout", "0"), ("--timeout", "-3"), ("--timeout", "nan"), ("--timeout", "inf"),
                            ("--min-score", "nan"), ("--min-score", "inf")):
            with self.subTest((flag, value)):
                self.assert_usage_error("score", "--tools-json", CLEAN, flag, value)


class ServerModeTests(CliCase):
    def server_args(self, mode="normal", *extra):
        return ["--", sys.executable, str(support.FAKE_SERVER), "--mode", mode, "--tools", CLEAN_TOOLS, *extra]

    def test_a_stdio_server_is_scored(self):
        code, out, err = run("score", "--format", "json", "--timeout", "10", *self.server_args("normal"))
        self.assertEqual((code, err), (0, ""))
        data = json.loads(out)
        self.assertEqual(data["source"], {"kind": "stdio", "protocolVersion": "2025-06-18", "serverName": "fake-server", "serverVersion": "1.2.3"})
        self.assertEqual(data["score"], 100)
        self.assertEqual(data["metrics"]["toolCount"], 2)

    def test_the_server_command_keeps_its_own_dashes(self):
        code, out, _ = run("score", "--timeout", "10", *self.server_args("normal", "--page-size", "1"))
        self.assertEqual(code, 0)
        self.assertIn("server: fake-server 1.2.3", out)

    def test_a_server_that_hangs_is_a_clean_error(self):
        self.assert_usage_error("score", "--timeout", "0.8", *self.server_args("hang"), fragment="timed out")

    def test_a_server_that_exits_is_a_clean_error(self):
        self.assert_usage_error("score", "--timeout", "5", *self.server_args("exit"), fragment="exited with code 4")

    def test_a_missing_server_command_is_a_clean_error(self):
        self.assert_usage_error("score", "--", "definitely-not-a-real-command-xyz", fragment="cannot find the server command")

    def test_env_values_reach_the_server(self):
        script = self.write("echo_env.py", (
            "import json, os, sys\n"
            "for line in sys.stdin:\n"
            "    m = json.loads(line)\n"
            "    if m.get('method') == 'initialize':\n"
            "        print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': {'protocolVersion': '2025-06-18', 'serverInfo': {'name': os.environ.get('GREETING', 'unset'), 'version': '1'}}}), flush=True)\n"
            "    elif m.get('method') == 'tools/list':\n"
            "        print(json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': {'tools': []}}), flush=True)\n"
        ))
        code, out, _ = run("score", "--format", "json", "--env", "GREETING=hello", "--timeout", "10", "--", sys.executable, script)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["source"]["serverName"], "hello")


# A tools file for the fake server (a bare array, as the fake server expects).
_TOOLS_DIR = tempfile.TemporaryDirectory()
CLEAN_TOOLS = str(Path(_TOOLS_DIR.name) / "tools.json")
Path(CLEAN_TOOLS).write_text(json.dumps(json.loads(Path(CLEAN).read_text(encoding="utf-8"))["tools"]), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_cli.py" 2>&1 | tail -4`
Expected: ERROR, `ImportError: cannot import name 'cli' from 'mcp_fixer'`.

- [ ] **Step 4: Write the CLI**

`servers/mcp-fixer/src/mcp_fixer/cli.py`:

```python
"""Command line: mcp-fixer score."""
import argparse
import json
import math
import sys
from pathlib import Path

from . import __version__
from .report import render_json, render_text
from .score import FILE_SOURCE, score_tools
from .stdio_client import ClientError, list_tools_stdio


class UsageError(Exception):
    """A problem with the command line or an input file, reported as `error: ...` with exit 2."""


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mcp-fixer",
        description="Score an MCP server's tool definitions with deterministic lint rules.",
    )
    parser.add_argument("--version", action="version", version=f"mcp-fixer {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    score = sub.add_parser(
        "score",
        usage="mcp-fixer score [options] (--tools-json FILE | -- SERVER_COMMAND [ARGS...])",
        description=(
            "Read a server's tool list and print a lint score from 0 to 100. Give either a saved "
            "tools/list result (--tools-json) or, after --, the command that starts a stdio MCP "
            "server. Only initialize and tools/list are ever sent; no tool is called."
        ),
    )
    score.add_argument("--tools-json", metavar="FILE", help="a saved tools/list result (a JSON array or an object with a tools array)")
    score.add_argument("--env", action="append", default=[], metavar="KEY=VALUE", help="environment variable for the server (repeatable)")
    score.add_argument("--timeout", type=float, default=30.0, metavar="SECONDS", help="per-request timeout (default 30)")
    score.add_argument("--format", choices=("text", "json"), default="text", help="output format (default text)")
    score.add_argument("--out", metavar="FILE", help="write the report to FILE instead of stdout")
    score.add_argument("--min-score", type=float, metavar="N", help="exit with code 1 when the score is below N")
    return parser


def load_tools_file(path):
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise UsageError(f"cannot read {path}: {exc.strerror or exc}") from None
    except UnicodeDecodeError:
        raise UsageError(f"{path} is not UTF-8 text") from None
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise UsageError(f"{path} is not valid JSON ({exc})") from None
    if isinstance(data, dict) and isinstance(data.get("tools"), list):
        return data["tools"]
    if isinstance(data, list):
        return data
    raise UsageError(f'{path} must be a JSON array or an object with a "tools" array')


def parse_env(pairs):
    env = {}
    for pair in pairs:
        key, separator, value = pair.partition("=")
        if not separator or not key:
            raise UsageError(f"--env needs KEY=VALUE, got {pair!r}")
        env[key] = value
    return env


def emit(text):
    stream = sys.stdout
    if hasattr(stream, "reconfigure"):
        # A legacy console encoding must not crash the report; unknown characters become "?".
        stream.reconfigure(encoding="utf-8", errors="replace")
    stream.write(text)


def run_score(args, command):
    if args.tools_json and command:
        raise UsageError("give either --tools-json or a server command after --, not both")
    if not args.tools_json and not command:
        raise UsageError("give --tools-json FILE, or a server command after --")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise UsageError("--timeout must be a finite number greater than 0")
    if args.min_score is not None and not math.isfinite(args.min_score):
        raise UsageError("--min-score must be a finite number")
    env = parse_env(args.env)
    if args.tools_json:
        tools = load_tools_file(args.tools_json)
        source = dict(FILE_SOURCE)
    else:
        tools, info = list_tools_stdio(command, env, args.timeout)
        source = {"kind": "stdio", **info}
    result = score_tools(tools, source)
    text = render_json(result) if args.format == "json" else render_text(result)
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
        except OSError as exc:
            raise UsageError(f"cannot write {args.out}: {exc.strerror or exc}") from None
    else:
        emit(text)
    if args.min_score is not None and result["score"] < args.min_score:
        return 1
    return 0


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    command = []
    if "--" in args:
        split = args.index("--")
        command, args = args[split + 1:], args[:split]
    parsed = build_parser().parse_args(args)
    try:
        return run_score(parsed, command)
    except (UsageError, ClientError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
```

`servers/mcp-fixer/src/mcp_fixer/__main__.py`:

```python
import sys

from .cli import main

sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_cli.py" -v 2>&1 | tail -30`
Expected: every test PASSES. Then try the real entry point once by hand: `python -m mcp_fixer score --tools-json servers/mcp-fixer/tests/fixtures/messy_tools.json` from `servers/mcp-fixer/src` (set `PYTHONPATH=servers/mcp-fixer/src` from the repo root) and read the report; it should print the score, the table and the findings.

- [ ] **Step 6: Run everything and commit**

```bash
python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -3
python -m unittest discover -s tests 2>&1 | tail -2
python scripts/validate.py
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer score command line

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: README and final checks

**Files:**
- Modify: `servers/mcp-fixer/README.md`

**Interfaces:**
- Consumes: the shipped behavior of Tasks 2 to 6.

- [ ] **Step 1: Write the README**

Overwrite `servers/mcp-fixer/README.md`:

````markdown
# mcp-fixer: score an MCP server's tool definitions

> Scores an MCP server's tool definitions with deterministic lint rules, so you can see what makes agents pick the wrong tool or waste tokens.

Part of [Naren's Claude Toolkit](https://github.com/NarenDawar/narens-claude-toolkit). This is the first of three planned parts: **score** (this), then a patcher and wrapper that apply the fixes, then a benchmark that shows tool selection did not get worse.

## What it does

`mcp-fixer score` reads a server's tool list and prints a score from 0 to 100 with a finding for every problem it can see in the definitions: descriptions that are missing, too short or so long they waste tokens, tools whose descriptions are near-duplicates, parameters with no description or type, values listed in prose that should be an enum, generic or inconsistent tool names, and servers with too many tools or too large a definition.

It is read-only. It sends only `initialize` and `tools/list` to a server and never calls a tool, so scoring cannot change anything. It needs no model and no network, uses only the Python standard library, and gives the same answer every time.

## Use it

Python 3.9 or newer. From this folder, with the package on the path:

```text
python -m mcp_fixer score -- npx -y some-mcp-server
python -m mcp_fixer score --tools-json tools.json
```

- Give either the server command after `--` (a stdio server), or `--tools-json FILE`: a saved `tools/list` result, either `{"tools": [...]}` or a bare array. The file mode is how you score a remote server: export its tool list and score the file.
- `--env KEY=VALUE` (repeatable) passes an environment variable such as an API key to a spawned server. The server inherits only a small base environment (`PATH` and a few system variables) plus what you pass.
- `--timeout SECONDS` (default 30) limits each request; the whole connection is capped at four times that.
- `--format text|json` (default text), `--out FILE` to write the report to a file.
- `--min-score N` exits with code 1 when the score is below N, so a CI job can fail a build. Exit code 2 means a usage or connection error, with a one-line message.

```text
$ python -m mcp_fixer score --tools-json tests/fixtures/messy_tools.json
mcp-fixer score: 70/100
...
```

You are running whatever command you give it, exactly as when you add a server to Claude: only score servers you trust.

## The rules

| Rule | Severity | Fires when |
| --- | --- | --- |
| D001 | high | a tool has no description |
| D002 | medium | a description is shorter than 20 characters |
| D003 | medium | a description is longer than 500 characters |
| D004 | medium | two tools have near-identical descriptions (80% or more of their words shared) |
| P001 | medium | a parameter has no description |
| P002 | medium | a parameter has no type |
| P003 | medium | a string parameter's description lists the allowed values but it has no `enum` |
| P004 | high | the input schema is missing or is not an object schema |
| P005 | low | two or more parameters and no `required` list |
| P006 | low | the schema is nested more than 3 levels deep |
| N001 | medium | a tool has a generic name such as `run` or `execute` |
| N002 | low | tool names mix naming styles |
| T001 | medium | more than 40 tools |
| T002 | medium / high | definitions take more than about 8,000 / 20,000 tokens |
| M001 | high | a tool entry is malformed |

Each tool starts at 100 and loses 25, 10 or 4 points per high, medium or low finding. The server score is the mean of the tool scores minus the server-level penalties (T001 5, T002 5 or 15, N002 4, each M001 25). Token sizes are an estimate (the length of each tool's JSON divided by 4), not a real tokenizer.

## How to read the score

It is a lint score. It tells you the definitions have the kinds of problems that make tool choice harder and requests bigger; it does not measure how well an agent actually uses the server, and the weights are a starting point, not calibrated against any outside benchmark. Treat a low score as a to-do list, not a verdict.

## Report format

`--format json` gives a stable report with `schemaVersion: 1` (source, score, metrics, findings with fix hints, notes) for other tools to consume. The planned patcher reads it.

## Not in this version

Calling tools (so no check that errors are consistent), remote HTTP or OAuth connections (use `--tools-json` for those), any model or accuracy benchmark, and writing patches.

## Tests

```text
python -m unittest discover -s servers/mcp-fixer/tests
```

They run in the repository's CI on Python 3.9 and 3.12 against a small fake MCP server.

---

Made by [Naren](https://github.com/NarenDawar). If this helped, star the repo.
````

- [ ] **Step 2: Check the README's example against the real output**

Run: `PYTHONPATH=servers/mcp-fixer/src python -m mcp_fixer score --tools-json servers/mcp-fixer/tests/fixtures/messy_tools.json | head -3`
Expected: the first line is `mcp-fixer score: N/100`. Confirm it reads `mcp-fixer score: 70/100` (46 for `run`, 75 for `searchItems`, 100 for `list_items`, minus 4 for mixed names). If it differs, recompute by hand before changing either the README or the test.

- [ ] **Step 3: Run the full set of checks**

```bash
python scripts/build_catalog.py --check && echo catalog-current
python -m unittest discover -s tests 2>&1 | tail -3
python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -3
python scripts/validate.py
git diff --stat main -- docs/superpowers | tail -4
git status --short | wc -l
```

Expected: `catalog-current`; both suites PASS; `OK: all plugins valid`; the `docs/superpowers` diff lists only the new spec, this plan and nothing older; a clean tree after the commit below.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
docs: mcp-fixer README

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

## Handoff after the merge (not tasks)

1. Merge `mcp-fixer-scorer` into `main` locally (the finishing step). Pushing is a separate confirmed step.
2. **Live check, yours:** from the repo root run `PYTHONPATH=servers/mcp-fixer/src python -m mcp_fixer score -- npx -y @modelcontextprotocol/server-everything` (or any stdio server you use) and read the score and findings. If it hangs or errors on Windows, the launcher resolution is the first suspect.
3. Next sub-projects, each with its own spec: the patcher and wrapper (turn the findings' fix hints into a patch and run a proxy server), then the accuracy proof.

## Self-review notes

- **Spec coverage:** interface, input modes and exit codes (Task 6); read-only client, handshake, pagination, ping, shutdown, timeouts, bounded stderr (Task 5); every rule and threshold (Tasks 2 and 3); score formula, rounding and clamping, malformed and empty cases (Task 4); the pinned JSON shape and text report (Task 4); structure, CI job, catalog, `.gitignore`, CHANGELOG (Task 1); README and the owner's live check (Task 7 and the handoff); out-of-scope items are Global Constraints.
- **Spec edits made in Task 1:** the base environment list, the per-request plus overall timeout, and the `notes` array and per-tool `findings` count in the report.
- **Type consistency:** the finding dict keys, `check_duplicates` returning `(index, finding)` pairs, the report shape, `list_tools_stdio` returning `(tools, info)` and `child_environment`/`resolve_command` are defined once and used with the same names in the tests and the CLI.
- **Known unknowns the executor settles by running the tests:** Windows process-tree handling of `.cmd` launchers, exact error wording in `test_stdio_client.py` assertions that match message fragments, and the real N in the README example.
