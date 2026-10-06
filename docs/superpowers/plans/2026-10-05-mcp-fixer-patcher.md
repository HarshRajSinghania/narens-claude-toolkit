# mcp-fixer patcher and wrapper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build sub-project 2 of mcp-fixer: `mcp-fixer patch` writes a patch file from the scorer's findings, and `mcp-fixer wrap` runs a transparent stdio proxy in front of a real MCP server that shows the client the patched tool definitions (descriptions, parameter details, `required`, renames) and forwards everything else byte for byte.

**Architecture:** Three new modules in `servers/mcp-fixer/src/mcp_fixer/`: `patch_format.py` (load, validate, fingerprint and apply a patch; pure), `patch_gen.py` (build a patch from tools and findings; pure) and `wrap.py` (a pure `Router` that decides what to rewrite per message, plus `run_wrapper` with two pump threads and the shutdown logic). `cli.py` gains the `patch` and `wrap` subcommands; `stdio_client.py` gets two small options so the wrapper can reuse command resolution, spawning and process-tree stopping. Tests use `unittest` with the existing fake stdio server, extended with `tools/call`, `resources/list` and a few new modes.

**Tech Stack:** Python 3.9+ standard library (`json`, `hashlib`, `copy`, `re`, `threading`, `subprocess`, `argparse`, `unittest`), Markdown.

**Spec:** `docs/superpowers/specs/2026-10-05-mcp-fixer-patcher-design.md`

## Global Constraints

- Python 3.9+ standard library only; no MCP SDK, no model, no network; LF line endings; code must run on Python 3.9 (no `match`, no `X | Y` annotations, no parenthesized context managers).
- The wrapper never changes behavior beyond names: it never enforces an enum, never alters `tools/call` arguments (only a renamed tool's `name` goes back to the original), and forwards every unpatched message as the original bytes. Streams are binary (`sys.stdin.buffer`, `sys.stdout.buffer`); stdout carries only protocol lines; diagnostics go to stderr, one line each, prefixed `mcp-fixer: `.
- A message line is parsed only to decide what to do; a line that is not a JSON object (including a batch array, a bare string or an empty line) is forwarded unchanged. A message is re-serialized (compact separators, `ensure_ascii=False`, UTF-8, trailing `\n`) only when the router changed it.
- The patch file is strict: unknown fields are errors; every validation error is one line naming the tool and field; a broken patch is `error: ...` and exit code 2 before the real server is spawned. Fingerprints are SHA-256 of canonical JSON (`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`, UTF-8 with `surrogatepass`).
- A stale tool (its fingerprint differs from `base`) is served unpatched with one warning per session unless `--allow-stale`; an entry with no `base` is always applied; a rename that would collide with another tool on the same page is skipped with a warning; each warning is printed once.
- `trim_description` always returns 500 characters or fewer.
- Wrapper lifetime: when the client closes stdin, close the real server's stdin, wait up to 5 seconds, then stop it (terminate then kill; the process group on POSIX) and exit 0; when the real server exits first, flush what it wrote and exit with its exit code (outside 0 to 255 becomes 1). No traceback ever reaches the user. On Windows a descendant that outlives its server is not found (as for the scorer).
- `patch` never overwrites an existing `--out` file without `--force` (exclusive create, no race); it never calls a tool.
- Do not push, merge, rename or change GitHub settings in this plan.
- Work on branch `mcp-fixer-patch` (already created, holds the spec commit).
- Repo rules: no old marketplace name outside history and the migration note, the README catalog is generated, existing files under `docs/superpowers/` are untouched.
- Scratch files live in the session scratchpad: `C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/4ec2fd29-f30d-4793-83a9-f979fbae59a4/scratchpad` (called `$SP`). Write patch scripts with the Write tool, not shell heredocs (the shell collapses backslashes).
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

**Clarifications decided in this plan** (spec details the plan makes precise):

- `Router(patch, allow_stale, log)` takes a `log` callable that receives each warning's text without the prefix; the default logger adds `mcp-fixer: ` and writes to stderr. `Router.finish()` logs the "in the patch but never listed" warnings.
- `run_wrapper(patch, command, allow_stale=False, stdin=None, stdout=None, log=None)` takes injectable binary streams so most lifecycle tests run in process; interactive tests (a client that waits for each response) run the real CLI as a subprocess.
- `tools/call` is only renamed back when the new name is in the **active** rename map (built from `tools/list` responses actually patched in this session); a call before any list passes through.
- A server response to `tools/list` is re-serialized only when at least one tool on the page changed; otherwise its original bytes are forwarded.
- The generator's `context` is written per tool as `{"description": <original or "">, "params": {<name>: <original description or "">}}`.
- The version bump to 0.2.0 happens in the last task (the existing test compares `__init__.py` with `pyproject.toml`, so both change together).

## Review Focus

Failure modes the spec implies but a first pass is likely to skip. Each has a test in the task that owns the code:

1. Byte-for-byte pass-through: unpatched messages keep odd whitespace, key order, `\u` escapes and `\/`; notifications; non-object lines (garbage, a batch array, an empty line); a final line with no trailing newline; and Windows newline handling (binary streams). (Tasks 3 and 4)
2. Rename-back correctness: only for renames actually applied; string ids `"1"` and number ids `1` never mix; a server request that reuses a pending id is not mistaken for a response; collisions; arguments untouched; stale tools; a call before any list. (Tasks 3 and 4)
3. Lifecycle: client EOF closes the server's stdin and the server is stopped after the grace period (exit 0, no orphan process); a server exiting or crashing propagates its exit code and its last output is flushed; a broken patch exits 2 before any server process exists; stdout holds only protocol lines; each warning appears once. (Task 4)
4. Patch validation and apply edge cases: typos (unknown fields), `True` as `patchVersion`, NaN in an enum, `params` for a parameter that does not exist, a non-object property, `required` names that do not exist, a tool with no `inputSchema`, no mutation of the input tool, a lone surrogate in a fingerprint, a deeply nested patch file. (Task 1)
5. Generator safety: trimmed descriptions are at most 500 characters at the boundaries 499, 500 and 501 and with a first sentence over the limit or no spaces at all; enums only from P003; the output is deterministic and always passes validation; duplicates and malformed entries do not crash it; `--out` never overwrites without `--force`. (Tasks 2 and 5)

---

### Task 1: The patch format

**Files:**
- Create: `servers/mcp-fixer/src/mcp_fixer/patch_format.py`, `servers/mcp-fixer/tests/test_patch_format.py`

**Interfaces:**
- Produces: `PATCH_VERSION = 1`; `PatchError`; `fingerprint(tool) -> str`; `validate_patch(data) -> data` (raises `PatchError`); `load_patch(path) -> dict` (raises `PatchError`, message prefixed with the path for validation errors); `apply_entry(tool, entry) -> (new_tool, warnings)`. Used by Tasks 2, 3, 4 and 5.

- [ ] **Step 1: Write the failing tests**

`servers/mcp-fixer/tests/test_patch_format.py`:

```python
import copy
import json
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from mcp_fixer import patch_format
from mcp_fixer.patch_format import PatchError

BASE = "a" * 64


def tool():
    return {
        "name": "run",
        "description": "Runs it",
        "inputSchema": {
            "type": "object",
            "properties": {"order": {"type": "string", "description": "Sort order"}, "q": {}},
            "required": ["q"],
        },
    }


def patch(tools=None, **top):
    data = {"patchVersion": 1, "tools": {} if tools is None else tools}
    data.update(top)
    return data


class FingerprintTests(unittest.TestCase):
    def test_is_64_lowercase_hex(self):
        value = patch_format.fingerprint(tool())
        self.assertRegex(value, r"^[0-9a-f]{64}$")

    def test_key_order_does_not_matter(self):
        a = {"name": "x", "description": "d"}
        b = {"description": "d", "name": "x"}
        self.assertEqual(patch_format.fingerprint(a), patch_format.fingerprint(b))

    def test_any_change_changes_it(self):
        base = patch_format.fingerprint(tool())
        changed = tool()
        changed["inputSchema"]["properties"]["q"] = {"type": "string"}
        self.assertNotEqual(base, patch_format.fingerprint(changed))

    def test_non_ascii_and_a_lone_surrogate_do_not_crash(self):
        patch_format.fingerprint({"name": "r\u00e9sum\u00e9 \u65e5\u672c\u8a9e"})
        patch_format.fingerprint(json.loads('{"name": "\\ud800"}'))

    def test_value_is_the_sha256_of_the_canonical_json(self):
        import hashlib
        expected = hashlib.sha256(b'{"description":"d","name":"a"}').hexdigest()
        self.assertEqual(patch_format.fingerprint({"name": "a", "description": "d"}), expected)


class ValidationTests(unittest.TestCase):
    def assert_invalid(self, data, fragment):
        with self.assertRaises(PatchError) as ctx:
            patch_format.validate_patch(data)
        self.assertIn(fragment, str(ctx.exception))
        self.assertNotIn("\n", str(ctx.exception))

    def entry_patch(self, **fields):
        return patch({"run": fields})

    def test_a_full_valid_patch_passes_and_is_returned(self):
        data = patch(
            {
                "run": {
                    "base": BASE,
                    "rename": "search_orders",
                    "description": "Search orders.",
                    "params": {"order": {"description": "d", "type": ["string", "null"], "enum": ["a", 1, True, None, 2.5], "default": "a"}},
                    "required": ["order"],
                    "review": ["check it"],
                    "todo": [{"rule": "P001", "param": "q", "hint": "describe"}, {"rule": "D001"}],
                    "context": {"description": "x", "params": {}},
                }
            },
            source={"serverName": "s", "serverVersion": None},
            notes=["a note"],
        )
        self.assertIs(patch_format.validate_patch(data), data)

    def test_an_empty_patch_is_valid(self):
        patch_format.validate_patch(patch())

    def test_top_level_problems(self):
        self.assert_invalid([], "the patch must be a JSON object")
        self.assert_invalid(patch(extra=1), "unknown field 'extra' in the patch")
        for version in (None, 0, 2, "1", True, 1.0):
            with self.subTest(version):
                data = patch()
                data["patchVersion"] = version
                self.assert_invalid(data, "patchVersion must be 1")
        data = patch()
        del data["patchVersion"]
        self.assert_invalid(data, "patchVersion must be 1")
        for tools in (None, [], "x"):
            with self.subTest(tools):
                self.assert_invalid({"patchVersion": 1, "tools": tools}, "tools must be an object")
        self.assert_invalid({"patchVersion": 1}, "tools must be an object")
        self.assert_invalid(patch(source=[]), "source must be an object")
        self.assert_invalid(patch(notes="x"), "notes must be a list of strings")
        self.assert_invalid(patch(notes=[1]), "notes must be a list of strings")

    def test_entry_problems_name_the_tool_and_the_field(self):
        cases = [
            ({"run": 5}, "tool 'run': must be an object"),
            ({"run": {"nope": 1}}, "tool 'run': unknown field 'nope'"),
            ({"run": {"base": "abc"}}, "tool 'run': base must be a 64-character lowercase hex SHA-256"),
            ({"run": {"base": "A" * 64}}, "base must be a 64-character lowercase hex"),
            ({"run": {"base": 5}}, "base must be a 64-character lowercase hex"),
            ({"run": {"rename": ""}}, "rename must be a non-empty string different from the tool's name"),
            ({"run": {"rename": 5}}, "rename must be a non-empty string different from the tool's name"),
            ({"run": {"rename": "run"}}, "rename must be a non-empty string different from the tool's name"),
            ({"run": {"description": 5}}, "description must be a string"),
            ({"run": {"params": []}}, "params must be an object"),
            ({"run": {"params": {"q": 5}}}, "params['q'] must be an object"),
            ({"run": {"params": {"q": {"x": 1}}}}, "params['q'] has unknown field 'x'"),
            ({"run": {"params": {"q": {"description": 5}}}}, "params['q'].description must be a string"),
            ({"run": {"params": {"q": {"type": 5}}}}, "params['q'].type must be a string or a list of strings"),
            ({"run": {"params": {"q": {"type": ["a", 5]}}}}, "params['q'].type must be a string or a list of strings"),
            ({"run": {"params": {"q": {"enum": []}}}}, "params['q'].enum must be a non-empty list"),
            ({"run": {"params": {"q": {"enum": "ab"}}}}, "params['q'].enum must be a non-empty list"),
            ({"run": {"params": {"q": {"enum": [["a"]]}}}}, "params['q'].enum must be a non-empty list"),
            ({"run": {"params": {"q": {"enum": [float("nan")]}}}}, "params['q'].enum must be a non-empty list"),
            ({"run": {"required": "q"}}, "required must be a list of unique strings"),
            ({"run": {"required": ["q", "q"]}}, "required must be a list of unique strings"),
            ({"run": {"required": [1]}}, "required must be a list of unique strings"),
            ({"run": {"review": "x"}}, "review must be a list of strings"),
            ({"run": {"review": [1]}}, "review must be a list of strings"),
            ({"run": {"todo": "x"}}, "todo must be a list"),
            ({"run": {"todo": ["x"]}}, "todo[0] must be an object with a string rule"),
            ({"run": {"todo": [{"hint": "h"}]}}, "todo[0] must be an object with a string rule"),
            ({"run": {"todo": [{"rule": "P001", "extra": 1}]}}, "todo[0] must be an object with a string rule"),
            ({"run": {"todo": [{"rule": "P001", "param": 5}]}}, "todo[0] must be an object with a string rule"),
            ({"run": {"context": []}}, "context must be an object"),
        ]
        for tools, fragment in cases:
            with self.subTest(fragment):
                self.assert_invalid(patch(tools), fragment)

    def test_collisions_between_renames(self):
        self.assert_invalid(
            patch({"a": {"rename": "z"}, "b": {"rename": "z"}}),
            "tools 'a' and 'b' are both renamed to 'z'",
        )
        self.assert_invalid(
            patch({"a": {"rename": "b"}, "b": {"description": "d"}}),
            "tool 'a' is renamed to 'b', which is another tool in the patch",
        )

    def test_a_swap_of_two_renames_is_still_refused(self):
        self.assert_invalid(
            patch({"a": {"rename": "b"}, "b": {"rename": "a"}}),
            "which is another tool in the patch",
        )


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, data, name="p.json"):
        path = self.dir / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return str(path)

    def test_a_valid_file_loads(self):
        path = self.write(json.dumps(patch({"run": {"description": "d"}})))
        self.assertEqual(patch_format.load_patch(path)["tools"]["run"]["description"], "d")

    def test_a_bom_is_tolerated(self):
        path = self.write(b"\xef\xbb\xbf" + json.dumps(patch()).encode("utf-8"))
        self.assertEqual(patch_format.load_patch(path)["patchVersion"], 1)

    def test_problems_are_one_line_errors_with_the_path(self):
        cases = {
            "missing": (str(self.dir / "nope.json"), "cannot read"),
            "directory": (str(self.dir), "cannot read"),
            "not utf-8": (self.write(b"\x80\x81", "bad.json"), "is not UTF-8 text"),
            "not json": (self.write("{nope", "nj.json"), "is not valid JSON"),
            "deep": (self.write("[" * 5000, "deep.json"), "nested too deeply"),
            "invalid patch": (self.write(json.dumps({"patchVersion": 2, "tools": {}}), "inv.json"), "patchVersion must be 1"),
        }
        for label, (path, fragment) in cases.items():
            with self.subTest(label):
                with self.assertRaises(PatchError) as ctx:
                    patch_format.load_patch(path)
                self.assertIn(fragment, str(ctx.exception))
                self.assertIn(Path(path).name, str(ctx.exception))
                self.assertNotIn("\n", str(ctx.exception))


class ApplyTests(unittest.TestCase):
    def test_an_empty_entry_gives_an_equal_copy_and_no_warnings(self):
        original = tool()
        new, warnings = patch_format.apply_entry(original, {})
        self.assertEqual((new, warnings), (original, []))
        self.assertIsNot(new, original)

    def test_the_input_is_never_mutated(self):
        original = tool()
        snapshot = copy.deepcopy(original)
        entry = {"rename": "r", "description": "d", "params": {"order": {"enum": ["a"]}}, "required": ["order"]}
        patch_format.apply_entry(original, entry)
        self.assertEqual(original, snapshot)

    def test_description_and_rename(self):
        new, _ = patch_format.apply_entry(tool(), {"rename": "search_orders", "description": "Search orders."})
        self.assertEqual((new["name"], new["description"]), ("search_orders", "Search orders."))

    def test_a_missing_description_is_added_at_the_end(self):
        t = tool()
        del t["description"]
        new, _ = patch_format.apply_entry(t, {"description": "d"})
        self.assertEqual(list(new), ["name", "inputSchema", "description"])

    def test_param_changes_merge_into_the_property(self):
        new, warnings = patch_format.apply_entry(
            tool(), {"params": {"order": {"enum": ["asc", "desc"], "default": "asc"}}}
        )
        order = new["inputSchema"]["properties"]["order"]
        self.assertEqual(order, {"type": "string", "description": "Sort order", "enum": ["asc", "desc"], "default": "asc"})
        self.assertEqual(warnings, [])

    def test_a_param_can_have_its_description_and_type_replaced(self):
        new, _ = patch_format.apply_entry(tool(), {"params": {"q": {"description": "Search text", "type": "string"}}})
        self.assertEqual(new["inputSchema"]["properties"]["q"], {"description": "Search text", "type": "string"})

    def test_a_property_that_is_not_an_object_becomes_one(self):
        t = tool()
        t["inputSchema"]["properties"]["q"] = "nope"
        new, _ = patch_format.apply_entry(t, {"params": {"q": {"type": "string"}}})
        self.assertEqual(new["inputSchema"]["properties"]["q"], {"type": "string"})

    def test_a_param_that_does_not_exist_is_skipped_with_a_warning(self):
        new, warnings = patch_format.apply_entry(tool(), {"params": {"ghost": {"type": "string"}}})
        self.assertEqual(new, tool())
        self.assertEqual(warnings, ["parameter 'ghost' is not in tool 'run'; skipped"])

    def test_param_values_are_copied_not_shared(self):
        entry = {"params": {"order": {"enum": ["a", "b"]}}}
        new, _ = patch_format.apply_entry(tool(), entry)
        entry["params"]["order"]["enum"].append("c")
        self.assertEqual(new["inputSchema"]["properties"]["order"]["enum"], ["a", "b"])

    def test_required_keeps_only_names_that_exist(self):
        new, warnings = patch_format.apply_entry(tool(), {"required": ["q", "ghost", "order"]})
        self.assertEqual(new["inputSchema"]["required"], ["q", "order"])
        self.assertEqual(warnings, ["required name 'ghost' is not a parameter of tool 'run'; dropped"])

    def test_no_input_schema_skips_params_and_required_with_warnings(self):
        t = {"name": "run", "description": "d"}
        new, warnings = patch_format.apply_entry(t, {"params": {"q": {"type": "string"}}, "required": ["q"], "description": "e"})
        self.assertEqual(new, {"name": "run", "description": "e"})
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all("tool 'run'" in w for w in warnings))

    def test_notes_are_ignored(self):
        entry = {"review": ["x"], "todo": [{"rule": "P001"}], "context": {"description": "d"}, "base": BASE}
        new, warnings = patch_format.apply_entry(tool(), entry)
        self.assertEqual((new, warnings), (tool(), []))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_patch_format.py" 2>&1 | tail -4`
Expected: ERROR, `ImportError: cannot import name 'patch_format' from 'mcp_fixer'`.

- [ ] **Step 3: Write the implementation**

`servers/mcp-fixer/src/mcp_fixer/patch_format.py`:

```python
"""The patch file: loading, validating and applying it. Standard library only."""
import copy
import hashlib
import json
import math
import re
from pathlib import Path

PATCH_VERSION = 1
TOP_KEYS = frozenset({"patchVersion", "source", "notes", "tools"})
ENTRY_KEYS = frozenset(
    {"base", "rename", "description", "params", "required", "review", "todo", "context"}
)
PARAM_KEYS = frozenset({"description", "type", "enum", "default"})
_BASE = re.compile(r"^[0-9a-f]{64}$")


class PatchError(Exception):
    """A problem with a patch file, reported as one line."""


def fingerprint(tool):
    """SHA-256 of the tool's canonical JSON: how a patch notices that a tool has changed."""
    text = json.dumps(tool, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8", errors="surrogatepass")).hexdigest()


def _is_strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_scalar(value):
    if isinstance(value, float):
        return math.isfinite(value)
    return value is None or isinstance(value, (str, int, bool))


def _check_params(name, params):
    where = f"tool {name!r}: "
    if not isinstance(params, dict):
        raise PatchError(where + "params must be an object")
    for pname, changes in params.items():
        label = f"params[{pname!r}]"
        if not isinstance(changes, dict):
            raise PatchError(where + f"{label} must be an object")
        for key in changes:
            if key not in PARAM_KEYS:
                raise PatchError(where + f"{label} has unknown field {key!r}")
        if "description" in changes and not isinstance(changes["description"], str):
            raise PatchError(where + f"{label}.description must be a string")
        if "type" in changes and not (
            isinstance(changes["type"], str) or _is_strings(changes["type"])
        ):
            raise PatchError(where + f"{label}.type must be a string or a list of strings")
        if "enum" in changes:
            values = changes["enum"]
            if not (isinstance(values, list) and values and all(_is_scalar(v) for v in values)):
                raise PatchError(
                    where + f"{label}.enum must be a non-empty list of strings, numbers, booleans or null"
                )


def _check_todo(where, todo):
    if not isinstance(todo, list):
        raise PatchError(where + "todo must be a list")
    for index, item in enumerate(todo):
        ok = (
            isinstance(item, dict)
            and set(item) <= {"rule", "param", "hint"}
            and isinstance(item.get("rule"), str)
            and all(isinstance(item[key], str) for key in ("param", "hint") if key in item)
        )
        if not ok:
            raise PatchError(
                where + f"todo[{index}] must be an object with a string rule, and optional string param and hint"
            )


def _check_entry(name, entry):
    where = f"tool {name!r}: "
    if not isinstance(entry, dict):
        raise PatchError(where + "must be an object")
    for key in entry:
        if key not in ENTRY_KEYS:
            raise PatchError(where + f"unknown field {key!r}")
    if "base" in entry and not (isinstance(entry["base"], str) and _BASE.match(entry["base"])):
        raise PatchError(where + "base must be a 64-character lowercase hex SHA-256")
    if "rename" in entry:
        new = entry["rename"]
        if not (isinstance(new, str) and new and new != name):
            raise PatchError(where + "rename must be a non-empty string different from the tool's name")
    if "description" in entry and not isinstance(entry["description"], str):
        raise PatchError(where + "description must be a string")
    if "params" in entry:
        _check_params(name, entry["params"])
    if "required" in entry:
        required = entry["required"]
        if not (_is_strings(required) and len(set(required)) == len(required)):
            raise PatchError(where + "required must be a list of unique strings")
    if "review" in entry and not _is_strings(entry["review"]):
        raise PatchError(where + "review must be a list of strings")
    if "todo" in entry:
        _check_todo(where, entry["todo"])
    if "context" in entry and not isinstance(entry["context"], dict):
        raise PatchError(where + "context must be an object")


def validate_patch(data):
    if not isinstance(data, dict):
        raise PatchError("the patch must be a JSON object")
    for key in data:
        if key not in TOP_KEYS:
            raise PatchError(f"unknown field {key!r} in the patch")
    version = data.get("patchVersion")
    if type(version) is not int or version != PATCH_VERSION:
        raise PatchError(f"patchVersion must be {PATCH_VERSION}")
    if "source" in data and not isinstance(data["source"], dict):
        raise PatchError("source must be an object")
    if "notes" in data and not _is_strings(data["notes"]):
        raise PatchError("notes must be a list of strings")
    tools = data.get("tools")
    if not isinstance(tools, dict):
        raise PatchError("tools must be an object")
    renames = {}
    for name, entry in tools.items():
        _check_entry(name, entry)
        new = entry.get("rename")
        if new is not None:
            if new in renames:
                raise PatchError(f"tools {renames[new]!r} and {name!r} are both renamed to {new!r}")
            renames[new] = name
    for new, name in renames.items():
        if new in tools:
            raise PatchError(f"tool {name!r} is renamed to {new!r}, which is another tool in the patch")
    return data


def load_patch(path):
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise PatchError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise PatchError(f"{path} is not UTF-8 text") from None
    try:
        data = json.loads(text)
    except RecursionError:
        raise PatchError(f"{path} is not valid JSON (nested too deeply)") from None
    except ValueError as exc:
        raise PatchError(f"{path} is not valid JSON ({exc})") from None
    try:
        return validate_patch(data)
    except PatchError as exc:
        raise PatchError(f"{path}: {exc}") from None


def apply_entry(tool, entry):
    """A modified deep copy of `tool` with `entry` applied, and the warnings it produced."""
    new = copy.deepcopy(tool)
    warnings = []
    name = tool.get("name")
    if "description" in entry:
        new["description"] = entry["description"]
    schema = new.get("inputSchema")
    props = schema.get("properties") if isinstance(schema, dict) else None
    if entry.get("params"):
        if not isinstance(props, dict):
            warnings.append(f"tool {name!r} has no input properties; skipped its parameter changes")
        else:
            for pname, changes in entry["params"].items():
                if pname not in props:
                    warnings.append(f"parameter {pname!r} is not in tool {name!r}; skipped")
                    continue
                if not isinstance(props[pname], dict):
                    props[pname] = {}
                for key, value in changes.items():
                    props[pname][key] = copy.deepcopy(value)
    if "required" in entry:
        if not isinstance(props, dict):
            warnings.append(f"tool {name!r} has no input properties; skipped its required list")
        else:
            kept = []
            for required in entry["required"]:
                if required in props:
                    kept.append(required)
                else:
                    warnings.append(
                        f"required name {required!r} is not a parameter of tool {name!r}; dropped"
                    )
            schema["required"] = kept
    if "rename" in entry:
        new["name"] = entry["rename"]
    return new, warnings
```

- [ ] **Step 4: Run the tests**

Run: `python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -4`
Expected: all tests PASS (the earlier 139 plus this task's).

- [ ] **Step 5: Commit**

```bash
python -m unittest discover -s tests 2>&1 | tail -2
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer patch file format (validate, fingerprint, apply)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The patch generator

**Files:**
- Create: `servers/mcp-fixer/src/mcp_fixer/patch_gen.py`, `servers/mcp-fixer/tests/test_patch_gen.py`

**Interfaces:**
- Consumes: `patch_format.fingerprint`, `patch_format.validate_patch` (Task 1); `score.score_tools`, `rules` (the scorer).
- Produces: `trim_description(text, limit=500) -> str`; `generate_patch(tools, source=None) -> dict` (always passes `validate_patch`); `render_patch(patch) -> str` (`json.dumps(..., indent=2, ensure_ascii=False)` plus a newline). Used by Task 5.

- [ ] **Step 1: Write the failing tests**

`servers/mcp-fixer/tests/test_patch_gen.py`:

```python
import json
import unittest
from pathlib import Path

import support
from mcp_fixer import patch_format, patch_gen

MESSY = json.loads((support.TESTS / "fixtures" / "messy_tools.json").read_text(encoding="utf-8"))
CLEAN = json.loads((support.TESTS / "fixtures" / "clean_tools.json").read_text(encoding="utf-8"))["tools"]


def sentence(n):
    return f"Sentence number {n} says something useful here."


class TrimTests(unittest.TestCase):
    def test_short_text_is_only_whitespace_collapsed(self):
        self.assertEqual(patch_gen.trim_description("  a   b \n c  "), "a b c")

    def test_whole_sentences_are_kept_while_they_fit(self):
        text = " ".join(sentence(i) for i in range(30))  # about 1,500 characters
        trimmed = patch_gen.trim_description(text)
        self.assertLessEqual(len(trimmed), 500)
        self.assertTrue(trimmed.endswith("here."))
        self.assertTrue(text.startswith(trimmed))
        self.assertGreater(len(trimmed), 400)

    def test_exactly_the_limit_is_untouched(self):
        for size in (499, 500):
            with self.subTest(size):
                text = "x" * size
                self.assertEqual(patch_gen.trim_description(text), text)

    def test_one_over_the_limit_is_cut(self):
        text = ("word " * 200).strip()  # 999 characters, no sentence end
        trimmed = patch_gen.trim_description(text)
        self.assertLessEqual(len(trimmed), 500)
        self.assertTrue(trimmed.endswith("\u2026"))
        text = "y" * 501
        trimmed = patch_gen.trim_description(text)
        self.assertEqual(len(trimmed), 500)
        self.assertTrue(trimmed.endswith("\u2026"))

    def test_a_first_sentence_over_the_limit_is_cut_at_a_word_boundary(self):
        text = "alpha " * 120 + "end. Second sentence."
        trimmed = patch_gen.trim_description(text)
        self.assertLessEqual(len(trimmed), 500)
        self.assertTrue(trimmed.endswith("alpha\u2026"))

    def test_question_and_exclamation_marks_end_sentences(self):
        text = ("Is this a question? " + "Yes it is! " + sentence(1) + " ") * 20
        trimmed = patch_gen.trim_description(text)
        self.assertLessEqual(len(trimmed), 500)
        self.assertTrue(trimmed[-1] in ".!?")

    def test_the_result_is_never_longer_than_the_limit(self):
        for size in range(480, 560):
            with self.subTest(size):
                text = ("ab " * size)[:size]
                self.assertLessEqual(len(patch_gen.trim_description(text)), 500)


class GenerateTests(unittest.TestCase):
    def test_the_messy_fixture_gives_the_expected_patch(self):
        patch = patch_gen.generate_patch(MESSY)
        self.assertEqual(patch["patchVersion"], 1)
        self.assertEqual(list(patch["tools"]), ["run", "searchItems"])  # list_items has no finding
        run = patch["tools"]["run"]
        self.assertEqual(run["base"], patch_format.fingerprint(MESSY[0]))
        self.assertEqual(run["params"], {"order": {"enum": ["asc", "desc"]}})
        self.assertEqual(
            run["review"],
            ["parameter 'order': enum inferred from its description (2 values); check the list is complete"],
        )
        todo = {(t["rule"], t.get("param")) for t in run["todo"]}
        self.assertEqual(todo, {("D002", None), ("N001", None), ("P001", "q"), ("P002", "q"), ("P005", None)})
        self.assertTrue(all(t["hint"] for t in run["todo"]))
        self.assertEqual(run["context"], {"description": "Runs it", "params": {"order": "Sort order, one of: asc, desc", "q": ""}})
        search = patch["tools"]["searchItems"]
        self.assertEqual([t["rule"] for t in search["todo"]], ["D001"])
        self.assertNotIn("rename", run)
        self.assertNotIn("description", run)
        self.assertEqual(patch["notes"], ["tool names mix naming styles"])

    def test_the_output_always_validates(self):
        for tools in (MESSY, CLEAN, [], ["oops", {"name": ""}, None]):
            with self.subTest(len(tools)):
                patch_format.validate_patch(patch_gen.generate_patch(tools))

    def test_a_clean_server_gives_an_empty_patch(self):
        patch = patch_gen.generate_patch(CLEAN)
        self.assertEqual(patch, {"patchVersion": 1, "tools": {}})

    def test_a_long_description_is_trimmed_with_a_review_note(self):
        long_text = " ".join(sentence(i) for i in range(30))
        tool = {"name": "get_item", "description": long_text,
                "inputSchema": {"type": "object", "properties": {"item_id": {"type": "string", "description": "Identifier"}}, "required": ["item_id"]}}
        entry = patch_gen.generate_patch([tool])["tools"]["get_item"]
        self.assertLessEqual(len(entry["description"]), 500)
        self.assertEqual(len(entry["review"]), 1)
        self.assertRegex(entry["review"][0], r"^description trimmed from \d+ to \d+ characters$")
        self.assertNotIn("todo", entry)

    def test_malformed_entries_become_notes(self):
        patch = patch_gen.generate_patch(["oops"] + CLEAN)
        self.assertEqual(patch["tools"], {})
        self.assertEqual(patch["notes"], ["tool entry 0 is malformed"])

    def test_duplicate_names_get_one_entry_and_a_note(self):
        tool = {"name": "dup_tool", "description": "", "inputSchema": {"type": "object", "properties": {}}}
        patch = patch_gen.generate_patch([tool, dict(tool)])
        self.assertEqual(list(patch["tools"]), ["dup_tool"])
        self.assertIn("duplicate tool names cannot be patched separately: dup_tool", patch["notes"])

    def test_a_duplicate_pair_note_does_not_hide_the_duplicate_description_todo(self):
        a = {"name": "alpha_tool", "description": "Search the catalog for products.", "inputSchema": {"type": "object", "properties": {}}}
        b = dict(a, name="beta_tool")
        patch = patch_gen.generate_patch([a, b])
        hint = patch["tools"]["alpha_tool"]["todo"][0]["hint"]
        self.assertIn("beta_tool", hint)

    def test_source_is_recorded_for_a_stdio_server_only(self):
        stdio = {"kind": "stdio", "protocolVersion": "2025-06-18", "serverName": "s", "serverVersion": "1"}
        self.assertEqual(patch_gen.generate_patch([], stdio)["source"], {"serverName": "s", "serverVersion": "1"})
        self.assertNotIn("source", patch_gen.generate_patch([]))

    def test_the_output_is_deterministic(self):
        first = patch_gen.render_patch(patch_gen.generate_patch(MESSY))
        second = patch_gen.render_patch(patch_gen.generate_patch(MESSY))
        self.assertEqual(first, second)
        self.assertTrue(first.endswith("}\n"))

    def test_the_input_tools_are_not_modified(self):
        before = json.dumps(MESSY, sort_keys=True)
        patch_gen.generate_patch(MESSY)
        self.assertEqual(json.dumps(MESSY, sort_keys=True), before)

    def test_non_ascii_text_is_written_readably(self):
        tool = {"name": "recuperer", "description": "", "inputSchema": {"type": "object", "properties": {}}}
        text = patch_gen.render_patch(patch_gen.generate_patch([dict(tool, title="\u65e5\u672c\u8a9e")]))
        self.assertIsInstance(text, str)
        self.assertNotIn("\\u", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_patch_gen.py" 2>&1 | tail -4`
Expected: ERROR, `ImportError: cannot import name 'patch_gen' from 'mcp_fixer'`.

- [ ] **Step 3: Write the implementation**

`servers/mcp-fixer/src/mcp_fixer/patch_gen.py`:

```python
"""Build a patch from a tool list and its lint findings. Pure; standard library only."""
import json
import re

from . import patch_format, rules, score as score_module

LIMIT = rules.THRESHOLDS["description_max_chars"]
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
_ELLIPSIS = "\u2026"


def trim_description(text, limit=LIMIT):
    """`text` with whitespace collapsed and cut to at most `limit` characters.

    Whole sentences are kept while they fit; when even the first does not, the text is cut at a
    word boundary and ends with an ellipsis.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    kept = ""
    for sentence in _SENTENCE_BREAK.split(collapsed):
        candidate = sentence if not kept else kept + " " + sentence
        if len(candidate) > limit:
            break
        kept = candidate
    if kept:
        return kept
    cut = collapsed[: limit - 1]
    space = cut.rfind(" ")
    if space > 0:
        cut = cut[:space]
    return cut.rstrip() + _ELLIPSIS


def _context(tool):
    description = tool.get("description")
    schema = tool.get("inputSchema")
    props = schema.get("properties") if isinstance(schema, dict) else None
    params = {}
    if isinstance(props, dict):
        for name, prop in props.items():
            text = prop.get("description") if isinstance(prop, dict) else None
            params[name] = text if isinstance(text, str) else ""
    return {"description": description if isinstance(description, str) else "", "params": params}


def _build_entry(tool, findings):
    params = {}
    review = []
    todo = []
    description = None
    for found in findings:
        rule = found["rule"]
        if rule == "P003":
            values = found["data"]["values"]
            params.setdefault(found["param"], {})["enum"] = values
            review.append(
                f"parameter '{found['param']}': enum inferred from its description "
                f"({len(values)} values); check the list is complete"
            )
        elif rule == "D003":
            original = tool["description"]
            description = trim_description(original)
            review.append(f"description trimmed from {len(original)} to {len(description)} characters")
        else:
            item = {"rule": rule}
            if found["param"]:
                item["param"] = found["param"]
            hint = found["fix"]
            if rule == "D004":
                hint = f"{found['message']}: {found['fix']}"
            item["hint"] = hint
            todo.append(item)
    if description is None and not (params or review or todo):
        return None
    entry = {"base": patch_format.fingerprint(tool)}
    if description is not None:
        entry["description"] = description
    if params:
        entry["params"] = params
    if review:
        entry["review"] = review
    if todo:
        entry["todo"] = todo
    entry["context"] = _context(tool)
    return entry


def generate_patch(tools, source=None):
    report = score_module.score_tools(tools, source)
    first = {}
    duplicates = []
    for tool in tools:
        if isinstance(tool, dict) and isinstance(tool.get("name"), str) and tool["name"]:
            if tool["name"] in first:
                if tool["name"] not in duplicates:
                    duplicates.append(tool["name"])
            else:
                first[tool["name"]] = tool
    by_tool = {}
    notes = []
    for found in report["findings"]:
        if found["tool"] is None:
            notes.append(found["message"])
        else:
            by_tool.setdefault(found["tool"], []).append(found)
    if duplicates:
        notes.append("duplicate tool names cannot be patched separately: " + ", ".join(sorted(duplicates)))
    entries = {}
    for name, tool in first.items():
        entry = _build_entry(tool, by_tool.get(name, []))
        if entry is not None:
            entries[name] = entry
    patch = {"patchVersion": patch_format.PATCH_VERSION}
    if source and source.get("kind") == "stdio":
        patch["source"] = {
            "serverName": source.get("serverName"),
            "serverVersion": source.get("serverVersion"),
        }
    if notes:
        patch["notes"] = notes
    patch["tools"] = entries
    return patch


def render_patch(patch):
    return json.dumps(patch, indent=2, ensure_ascii=False) + "\n"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -4`
Expected: all tests PASS. If `test_the_messy_fixture_gives_the_expected_patch` disagrees about the todo set or the `notes`, re-derive the findings by hand from `rules.py` first (print `score_tools(MESSY)["findings"]`); the generator must follow the findings, and the spec's rule list decides which become a `todo`.

- [ ] **Step 5: Commit**

```bash
python -m unittest discover -s tests 2>&1 | tail -2
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer patch generator (enums, trimming, todo entries)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The router

**Files:**
- Create: `servers/mcp-fixer/src/mcp_fixer/wrap.py` (the `Router` only; Task 4 adds `run_wrapper`), `servers/mcp-fixer/tests/test_wrap_router.py`

**Interfaces:**
- Consumes: `patch_format.fingerprint`, `patch_format.apply_entry` (Task 1).
- Produces: `wrap.Router(patch, allow_stale=False, log=None)` with `client_line(raw: bytes) -> bytes`, `server_line(raw: bytes) -> bytes`, `finish()`; attributes `rename_back` (dict) and `pending` (set). `log` is a callable taking one string (a warning without the prefix). Task 4 uses all of it.

- [ ] **Step 1: Write the failing tests**

`servers/mcp-fixer/tests/test_wrap_router.py`:

```python
import json
import unittest

import support  # noqa: F401
from mcp_fixer import patch_format
from mcp_fixer.wrap import Router


def tool(name="run", description="Runs it"):
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": {"order": {"type": "string"}, "q": {"type": "string"}}}}


def line(message):
    return (json.dumps(message) + "\n").encode("utf-8")


def parse(raw):
    return json.loads(raw.decode("utf-8"))


def list_request(request_id=1):
    return line({"jsonrpc": "2.0", "id": request_id, "method": "tools/list"})


def list_response(tools, request_id=1, **extra):
    result = {"tools": tools}
    result.update(extra)
    return line({"jsonrpc": "2.0", "id": request_id, "result": result})


def make(entries, allow_stale=False):
    warnings = []
    patch = {"patchVersion": 1, "tools": entries}
    return Router(patch, allow_stale, warnings.append), warnings


RUN_ENTRY = {
    "base": patch_format.fingerprint(tool()),
    "rename": "search_orders",
    "description": "Search orders by status.",
    "params": {"order": {"enum": ["asc", "desc"]}},
}


class PassThroughTests(unittest.TestCase):
    def test_unpatched_client_and_server_lines_are_the_same_bytes(self):
        router, warnings = make({"run": RUN_ENTRY})
        for raw in (
            b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n',
            b' { "b" : 1 ,   "a" : "caf\\u00e9 \\/" }\n',
            b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n',
        ):
            with self.subTest(raw):
                self.assertIs(router.client_line(raw), raw)
                self.assertIs(router.server_line(raw), raw)
        self.assertEqual(warnings, [])

    def test_lines_that_are_not_json_objects_are_forwarded_unchanged(self):
        router, _ = make({"run": RUN_ENTRY})
        for raw in (b"garbage\n", b"[1, 2, 3]\n", b'"just a string"\n', b"42\n", b"\n", b"", b"{not json\n",
                    b"[" * 5000 + b"\n", b"\xff\xfe\n"):
            with self.subTest(raw[:20]):
                self.assertIs(router.client_line(raw), raw)
                self.assertIs(router.server_line(raw), raw)

    def test_a_final_line_with_no_newline_is_forwarded_as_is(self):
        router, _ = make({})
        raw = b'{"jsonrpc":"2.0","id":9,"result":{}}'
        self.assertIs(router.server_line(raw), raw)


class ToolsListTests(unittest.TestCase):
    def test_a_tools_list_response_is_patched(self):
        router, warnings = make({"run": RUN_ENTRY})
        router.client_line(list_request())
        out = parse(router.server_line(list_response([tool(), tool("list_items", "Lists items in the store")], nextCursor="c2")))
        self.assertEqual(out["id"], 1)
        self.assertEqual(out["jsonrpc"], "2.0")
        self.assertEqual(out["result"]["nextCursor"], "c2")
        first, second = out["result"]["tools"]
        self.assertEqual(first["name"], "search_orders")
        self.assertEqual(first["description"], "Search orders by status.")
        self.assertEqual(first["inputSchema"]["properties"]["order"], {"type": "string", "enum": ["asc", "desc"]})
        self.assertEqual(second, tool("list_items", "Lists items in the store"))
        self.assertEqual(warnings, [])

    def test_a_response_nobody_asked_for_is_not_patched(self):
        router, _ = make({"run": RUN_ENTRY})
        raw = list_response([tool()])
        self.assertIs(router.server_line(raw), raw)

    def test_string_and_number_ids_never_mix(self):
        router, _ = make({"run": RUN_ENTRY})
        router.client_line(list_request("1"))
        raw = list_response([tool()], request_id=1)
        self.assertIs(router.server_line(raw), raw)
        self.assertNotEqual(parse(router.server_line(list_response([tool()], request_id="1")))["result"]["tools"][0]["name"], "run")

    def test_a_response_is_patched_once_per_request(self):
        router, _ = make({"run": RUN_ENTRY})
        router.client_line(list_request())
        router.server_line(list_response([tool()]))
        raw = list_response([tool()])
        self.assertIs(router.server_line(raw), raw)

    def test_an_error_response_is_untouched_and_forgotten(self):
        router, _ = make({"run": RUN_ENTRY})
        router.client_line(list_request())
        raw = line({"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "no"}})
        self.assertIs(router.server_line(raw), raw)
        self.assertEqual(router.pending, set())

    def test_a_server_request_that_reuses_the_id_is_not_a_response(self):
        router, _ = make({"run": RUN_ENTRY})
        router.client_line(list_request())
        raw = line({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        self.assertIs(router.server_line(raw), raw)
        self.assertEqual(router.pending, {"1"})

    def test_a_tools_list_notification_without_an_id_is_ignored(self):
        router, _ = make({"run": RUN_ENTRY})
        router.client_line(line({"jsonrpc": "2.0", "method": "tools/list"}))
        self.assertEqual(router.pending, set())

    def test_a_page_where_nothing_changes_keeps_the_original_bytes(self):
        router, _ = make({"run": {"review": ["only a note"]}})
        router.client_line(list_request())
        raw = list_response([tool()])
        self.assertIs(router.server_line(raw), raw)

    def test_two_pages_are_each_patched(self):
        router, _ = make({"run": RUN_ENTRY, "list_items": {"description": "Lists every item in the store."}})
        router.client_line(list_request(1))
        router.client_line(list_request(2))
        one = parse(router.server_line(list_response([tool()], 1)))
        two = parse(router.server_line(list_response([tool("list_items", "x")], 2)))
        self.assertEqual(one["result"]["tools"][0]["name"], "search_orders")
        self.assertEqual(two["result"]["tools"][0]["description"], "Lists every item in the store.")

    def test_entries_that_are_not_tools_are_left_alone(self):
        router, _ = make({"run": RUN_ENTRY})
        router.client_line(list_request())
        out = parse(router.server_line(list_response(["oops", 5, {"no": "name"}, tool()])))
        self.assertEqual(out["result"]["tools"][:3], ["oops", 5, {"no": "name"}])
        self.assertEqual(out["result"]["tools"][3]["name"], "search_orders")


class RenameBackTests(unittest.TestCase):
    def listed(self, entries=None, allow_stale=False, tools=None):
        router, warnings = make(entries or {"run": RUN_ENTRY}, allow_stale)
        router.client_line(list_request())
        router.server_line(list_response(tools or [tool()]))
        return router, warnings

    def call(self, name, request_id=7, arguments=None):
        return line({"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                     "params": {"name": name, "arguments": arguments if arguments is not None else {"q": "x"}, "_meta": {"k": 1}}})

    def test_a_renamed_tool_is_called_by_its_original_name(self):
        router, _ = self.listed()
        out = parse(router.client_line(self.call("search_orders")))
        self.assertEqual(out["params"]["name"], "run")
        self.assertEqual(out["params"]["arguments"], {"q": "x"})
        self.assertEqual(out["params"]["_meta"], {"k": 1})
        self.assertEqual((out["id"], out["method"]), (7, "tools/call"))

    def test_an_unrenamed_or_unknown_call_is_the_same_bytes(self):
        router, _ = self.listed()
        for name in ("run", "list_items", "ghost"):
            with self.subTest(name):
                raw = self.call(name)
                self.assertIs(router.client_line(raw), raw)

    def test_a_call_before_any_list_passes_through(self):
        router, _ = make({"run": RUN_ENTRY})
        raw = self.call("search_orders")
        self.assertIs(router.client_line(raw), raw)

    def test_a_call_with_odd_params_passes_through(self):
        router, _ = self.listed()
        for message in ({"method": "tools/call", "id": 1}, {"method": "tools/call", "id": 1, "params": []},
                        {"method": "tools/call", "id": 1, "params": {"name": 5}}):
            with self.subTest(message):
                raw = line(message)
                self.assertIs(router.client_line(raw), raw)

    def test_other_methods_naming_the_patched_name_are_untouched(self):
        router, _ = self.listed()
        raw = line({"method": "prompts/get", "id": 1, "params": {"name": "search_orders"}})
        self.assertIs(router.client_line(raw), raw)

    def test_a_rename_that_collides_with_another_tool_on_the_page_is_skipped(self):
        entries = {"run": {"rename": "list_items", "description": "Search orders by status."}}
        router, warnings = self.listed(entries, tools=[tool(), tool("list_items", "Lists items")])
        self.assertEqual(router.rename_back, {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("rename of tool 'run' to 'list_items' skipped", warnings[0])

    def test_a_skipped_rename_still_applies_the_other_changes(self):
        entries = {"run": {"rename": "list_items", "description": "Search orders by status."}}
        router, _ = make(entries)
        router.client_line(list_request())
        out = parse(router.server_line(list_response([tool(), tool("list_items", "Lists items")])))
        self.assertEqual([t["name"] for t in out["result"]["tools"]], ["run", "list_items"])
        self.assertEqual(out["result"]["tools"][0]["description"], "Search orders by status.")

    def test_a_second_list_keeps_the_map(self):
        router, _ = self.listed()
        router.client_line(list_request(2))
        router.server_line(list_response([tool("other_tool", "Does something else entirely")], 2))
        out = parse(router.client_line(self.call("search_orders")))
        self.assertEqual(out["params"]["name"], "run")


class StaleTests(unittest.TestCase):
    CHANGED = tool("run", "The server changed this text")

    def test_a_stale_tool_is_served_unpatched_with_one_warning_per_session(self):
        router, warnings = make({"run": RUN_ENTRY})
        for request_id in (1, 2):
            router.client_line(list_request(request_id))
            raw = list_response([self.CHANGED], request_id)
            self.assertIs(router.server_line(raw), raw)
        self.assertEqual(len(warnings), 1)
        self.assertIn("tool 'run' changed since the patch was made; serving it unpatched", warnings[0])
        self.assertIn("--allow-stale", warnings[0])
        self.assertEqual(router.rename_back, {})

    def test_allow_stale_applies_the_entry_anyway(self):
        router, warnings = make({"run": RUN_ENTRY}, allow_stale=True)
        router.client_line(list_request())
        out = parse(router.server_line(list_response([self.CHANGED])))
        self.assertEqual(out["result"]["tools"][0]["name"], "search_orders")
        self.assertEqual(warnings, [])

    def test_an_entry_without_a_base_is_always_applied(self):
        router, _ = make({"run": {"description": "Search orders by status."}})
        router.client_line(list_request())
        out = parse(router.server_line(list_response([self.CHANGED])))
        self.assertEqual(out["result"]["tools"][0]["description"], "Search orders by status.")


class WarningTests(unittest.TestCase):
    def test_apply_warnings_are_logged_once(self):
        router, warnings = make({"run": {"params": {"ghost": {"type": "string"}}}})
        for request_id in (1, 2):
            router.client_line(list_request(request_id))
            router.server_line(list_response([tool()], request_id))
        self.assertEqual(warnings, ["parameter 'ghost' is not in tool 'run'; skipped"])

    def test_finish_warns_about_patched_tools_the_server_never_listed(self):
        router, warnings = make({"run": RUN_ENTRY, "ghost": {"description": "x"}})
        router.client_line(list_request())
        router.server_line(list_response([tool()]))
        router.finish()
        router.finish()
        self.assertEqual(warnings, ["tool 'ghost' is in the patch but the server never listed it"])

    def test_the_default_logger_prefixes_and_writes_to_stderr(self):
        import contextlib
        import io
        router = Router({"patchVersion": 1, "tools": {"ghost": {"description": "x"}}})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            router.finish()
        self.assertEqual(err.getvalue(), "mcp-fixer: tool 'ghost' is in the patch but the server never listed it\n")


if __name__ == "__main__":
    unittest.main()
```


- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_wrap_router.py" 2>&1 | tail -4`
Expected: ERROR, `ImportError: cannot import name 'Router' from 'mcp_fixer.wrap'` (or no module `wrap`).

- [ ] **Step 3: Write the router**

`servers/mcp-fixer/src/mcp_fixer/wrap.py`:

```python
"""The wrapper: a transparent stdio proxy that patches tool definitions.

`Router` decides, line by line, what to rewrite; everything else is forwarded as the original
bytes. Standard library only.
"""
import json
import sys

from . import patch_format


def _stderr_log(text):
    print(f"mcp-fixer: {text}", file=sys.stderr, flush=True)


def _parse(raw):
    """The JSON object on this line, or None (not JSON, not an object, or too deeply nested)."""
    try:
        message = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    return message if isinstance(message, dict) else None


def _dump(message):
    return (json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _id_key(value):
    """Ids are keyed by their JSON text, so the string "1" and the number 1 stay different."""
    return json.dumps(value, sort_keys=True)


class Router:
    def __init__(self, patch, allow_stale=False, log=None):
        self.entries = patch["tools"]
        self.allow_stale = allow_stale
        self.log = log or _stderr_log
        self.pending = set()  # ids (as keys) of client tools/list requests awaiting a response
        self.rename_back = {}  # patched name -> original name, for renames applied this session
        self.seen = set()  # original names the server has listed
        self._warned = set()

    def _warn(self, key, text):
        if key not in self._warned:
            self._warned.add(key)
            self.log(text)

    # --- client to server -------------------------------------------------------------------
    def client_line(self, raw):
        message = _parse(raw)
        if message is None:
            return raw
        method = message.get("method")
        if method == "tools/list" and "id" in message:
            self.pending.add(_id_key(message["id"]))
            return raw
        if method == "tools/call":
            params = message.get("params")
            if (
                isinstance(params, dict)
                and isinstance(params.get("name"), str)
                and params["name"] in self.rename_back
            ):
                renamed = dict(message)
                renamed["params"] = dict(params, name=self.rename_back[params["name"]])
                return _dump(renamed)
        return raw

    # --- server to client -------------------------------------------------------------------
    def server_line(self, raw):
        message = _parse(raw)
        if message is None or "method" in message or "id" not in message:
            return raw
        key = _id_key(message["id"])
        if key not in self.pending:
            return raw
        self.pending.discard(key)
        result = message.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            return raw
        tools, changed = self._patch_page(result["tools"])
        if not changed:
            return raw
        patched = dict(message)
        patched["result"] = dict(result, tools=tools)
        return _dump(patched)

    def _patch_page(self, tools):
        names_on_page = {
            t["name"] for t in tools if isinstance(t, dict) and isinstance(t.get("name"), str)
        }
        out = []
        changed = False
        for tool in tools:
            if not (isinstance(tool, dict) and isinstance(tool.get("name"), str)):
                out.append(tool)
                continue
            name = tool["name"]
            self.seen.add(name)
            entry = self.entries.get(name)
            if entry is None:
                out.append(tool)
                continue
            base = entry.get("base")
            if base is not None and base != patch_format.fingerprint(tool) and not self.allow_stale:
                self._warn(
                    ("stale", name),
                    f"tool {name!r} changed since the patch was made; serving it unpatched "
                    "(use --allow-stale to apply anyway)",
                )
                out.append(tool)
                continue
            new, warnings = patch_format.apply_entry(tool, entry)
            for text in warnings:
                self._warn(("apply", name, text), text)
            new_name = new["name"]
            if new_name != name:
                if new_name in names_on_page:
                    self._warn(
                        ("collision", name),
                        f"rename of tool {name!r} to {new_name!r} skipped: "
                        "another tool on the page has that name",
                    )
                    new["name"] = name
                else:
                    self.rename_back[new_name] = name
            if new != tool:
                changed = True
            out.append(new)
        return out, changed

    def finish(self):
        for name in sorted(self.entries):
            if name not in self.seen:
                self._warn(("missing", name), f"tool {name!r} is in the patch but the server never listed it")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -4`
Expected: all tests PASS. `test_a_page_where_nothing_changes_keeps_the_original_bytes` must pass: `apply_entry` with only `review` returns an equal tool, so `new != tool` is false and the original bytes are forwarded.

- [ ] **Step 5: Commit**

```bash
python -m unittest discover -s tests 2>&1 | tail -2
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer wrapper router (patch tools/list, rename back tools/call)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: The proxy and the fake server

**Files:**
- Modify: `servers/mcp-fixer/src/mcp_fixer/wrap.py` (add `run_wrapper`), `servers/mcp-fixer/src/mcp_fixer/stdio_client.py` (two options), `servers/mcp-fixer/tests/fake_server.py`
- Create: `servers/mcp-fixer/tests/wrapclient.py`, `servers/mcp-fixer/tests/test_wrap.py`

**Interfaces:**
- Consumes: `Router` (Task 3); `stdio_client.resolve_command`, `_spawn`, `_kill_tree`, `child_environment`, `ClientError`.
- Produces: `wrap.run_wrapper(patch, command, allow_stale=False, stdin=None, stdout=None, log=None) -> int`; `wrap.SHUTDOWN_GRACE_SECONDS = 5.0`; `stdio_client.child_environment(extra=None, inherit=False)`; `stdio_client._spawn(argv, env, stderr=subprocess.PIPE)`; test helpers `wrapclient.WrapClient`. Task 5's CLI calls `run_wrapper`.

- [ ] **Step 1: Extend the fake server**

Write this script to `$SP/fake_wrap.py` and run `python $SP/fake_wrap.py` from the repo root:

```python
from pathlib import Path

p = Path("servers/mcp-fixer/tests/fake_server.py")
s = p.read_text(encoding="utf-8")


def swap(old, new):
    global s
    assert old in s, old[:70]
    s = s.replace(old, new, 1)


# tools/call, resources/list and an odd-bytes mode, added after the tools/list branch
swap(
    '''        send({"jsonrpc": "2.0", "id": mid, "result": tools_page(message.get("params"))})
''',
    '''        send({"jsonrpc": "2.0", "id": mid, "result": tools_page(message.get("params"))})
    elif method == "tools/call":
        params = message.get("params") or {}
        name = params.get("name")
        if name not in {t.get("name") for t in TOOLS if isinstance(t, dict)}:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool: {name}"}})
        else:
            shown = json.dumps(params.get("arguments", {}), sort_keys=True)
            send({"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": f"called {name} with {shown}"}], "isError": False}})
    elif method == "resources/list" and args.mode == "odd-bytes":
        sys.stdout.write(' { "jsonrpc" : "2.0" , "result" : {"b":1,"a":"caf\\\\u00e9 \\\\/ \\\\ud83d\\\\ude00"},   "id" : ' + json.dumps(mid) + " }\\n")
        sys.stdout.flush()
    elif method == "resources/list":
        send({"jsonrpc": "2.0", "id": mid, "result": {"resources": []}})
''',
)

# an oddly formatted notification right after initialized (odd-bytes mode)
swap(
    '''        if args.mode == "ping-flood":''',
    '''        if args.mode == "odd-bytes":
            sys.stdout.write('{"method":"notifications/message",   "params":{"level":"info","data":"caf\\\\u00e9"},"jsonrpc":"2.0"}\\n')
            sys.stdout.flush()
        if args.mode == "ping-flood":''',
)

# a server that ignores end of input
s = s.rstrip("\\n") + '''

if args.mode == "hang-on-eof":
    time.sleep(60)
'''
with open(p, "w", encoding="utf-8", newline="\\n") as f:
    f.write(s)
print("ok")
```

Expected output: `ok`. Run the existing server tests (`python -m unittest discover -s servers/mcp-fixer/tests`): all still PASS.

- [ ] **Step 2: Small options in `stdio_client.py`**

Replace the `child_environment` function and the `_spawn` function in `servers/mcp-fixer/src/mcp_fixer/stdio_client.py`:

```python
def child_environment(extra=None, inherit=False):
    """The environment for a spawned server: the whole of ours, or only the base variables."""
    if inherit:
        env = dict(os.environ)
    else:
        env = {key: os.environ[key] for key in BASE_ENV_KEYS if key in os.environ}
    env.update(extra or {})
    return env
```

```python
def _spawn(argv, env, stderr=subprocess.PIPE):
    kwargs = {}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            env=env,
            **kwargs,
        )
    except OSError as exc:
        raise ClientError(f"cannot start the server: {exc.strerror or exc}") from None
```

Run the whole server suite again: expected PASS (the scorer calls both with its old arguments).

- [ ] **Step 3: Write the test client helper**

`servers/mcp-fixer/tests/wrapclient.py`:

```python
"""A tiny MCP client for the wrapper tests: it runs `mcp-fixer wrap` as a subprocess and talks to
it line by line, waiting for each response before it sends the next message."""
import json
import os
import queue
import subprocess
import sys
import threading

import support


class WrapClient:
    def __init__(self, patch_path, server_args, allow_stale=False, extra_args=()):
        command = [sys.executable, "-m", "mcp_fixer", "wrap", "--patch", str(patch_path), *extra_args]
        if allow_stale:
            command.append("--allow-stale")
        command += ["--", sys.executable, str(support.FAKE_SERVER), *server_args]
        env = dict(os.environ, PYTHONPATH=str(support.SRC))
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
        )
        self.lines = queue.Queue()
        self.stderr = []
        self._threads = [
            threading.Thread(target=self._read_stdout, daemon=True),
            threading.Thread(target=self._read_stderr, daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def _read_stdout(self):
        for raw in self.proc.stdout:
            self.lines.put(raw)
        self.lines.put(None)

    def _read_stderr(self):
        for raw in self.proc.stderr:
            self.stderr.append(raw.decode("utf-8", errors="replace"))

    def send(self, message):
        data = message if isinstance(message, bytes) else (json.dumps(message) + "\\n").encode("utf-8")
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def recv_raw(self, timeout=15):
        return self.lines.get(timeout=timeout)

    def request(self, message, timeout=15):
        self.send(message)
        raw = self.recv_raw(timeout)
        assert raw is not None, "the wrapper closed its output"
        return json.loads(raw.decode("utf-8"))

    def handshake(self):
        self.request({"jsonrpc": "2.0", "id": 100, "method": "initialize", "params": {}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def finish(self, timeout=20):
        """Close stdin, wait for the wrapper, and return its exit code."""
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        code = self.proc.wait(timeout=timeout)
        for thread in self._threads:
            thread.join(timeout=5)
        for pipe in (self.proc.stdout, self.proc.stderr):
            pipe.close()
        return code

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=5)

    @property
    def stderr_text(self):
        return "".join(self.stderr)
```

(The `"\\n"` above is a literal backslash-n inside the Python source of the helper: write the file with a real `\n` escape, i.e. `"\n"`.)

- [ ] **Step 4: Write the failing tests**

`servers/mcp-fixer/tests/test_wrap.py`:

```python
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import support
from mcp_fixer import patch_format, wrap
from wrapclient import WrapClient

TOOLS = [
    {"name": "run", "description": "Runs it",
     "inputSchema": {"type": "object", "properties": {"order": {"type": "string", "description": "Sort order, one of: asc, desc"}, "q": {}}}},
    {"name": "list_items", "description": "List the items in the store.",
     "inputSchema": {"type": "object", "properties": {}}},
]
PATCH = {
    "patchVersion": 1,
    "tools": {
        "run": {
            "base": patch_format.fingerprint(TOOLS[0]),
            "rename": "search_orders",
            "description": "Search orders by status.",
            "params": {"order": {"enum": ["asc", "desc"]}},
        }
    },
}


class WrapCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.tools_file = self.dir / "tools.json"
        self.tools_file.write_text(json.dumps(TOOLS), encoding="utf-8")

    def patch_file(self, patch=PATCH, name="p.json"):
        path = self.dir / name
        path.write_text(json.dumps(patch), encoding="utf-8")
        return path

    def server_args(self, mode="normal", *extra):
        return ["--mode", mode, "--tools", str(self.tools_file), *extra]

    def client(self, patch=PATCH, mode="normal", *extra, **kw):
        client = WrapClient(self.patch_file(patch), self.server_args(mode, *extra), **kw)
        self.addCleanup(client.kill)
        return client

    def command(self, mode="normal", *extra):
        return [sys.executable, str(support.FAKE_SERVER), *self.server_args(mode, *extra)]


class InteractiveTests(WrapCase):
    def test_the_client_sees_the_patched_tool_list(self):
        c = self.client()
        c.handshake()
        listing = c.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        first, second = listing["result"]["tools"]
        self.assertEqual(first["name"], "search_orders")
        self.assertEqual(first["description"], "Search orders by status.")
        self.assertEqual(first["inputSchema"]["properties"]["order"]["enum"], ["asc", "desc"])
        self.assertEqual(second, TOOLS[1])
        self.assertEqual(c.finish(), 0)

    def test_a_renamed_tool_is_called_by_its_original_name(self):
        c = self.client()
        c.handshake()
        c.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        reply = c.request({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": "search_orders", "arguments": {"q": "x", "n": 3}}})
        self.assertEqual(reply["result"]["content"][0]["text"], 'called run with {"n": 3, "q": "x"}')
        unknown = c.request({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "run", "arguments": {}}})
        self.assertEqual(unknown["result"]["content"][0]["text"], "called run with {}")  # the original name still works
        ghost = c.request({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "ghost", "arguments": {}}})
        self.assertEqual(ghost["error"]["message"], "Unknown tool: ghost")
        self.assertEqual(c.finish(), 0)

    def test_string_ids_are_echoed_unchanged(self):
        c = self.client()
        c.handshake()
        listing = c.request({"jsonrpc": "2.0", "id": "req-1", "method": "tools/list"})
        self.assertEqual(listing["id"], "req-1")
        self.assertEqual(listing["result"]["tools"][0]["name"], "search_orders")
        c.finish()

    def test_pagination_patches_every_page(self):
        c = self.client(PATCH, "normal", "--page-size", "1")
        c.handshake()
        one = c.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        two = c.request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"cursor": one["result"]["nextCursor"]}})
        self.assertEqual(one["result"]["tools"][0]["name"], "search_orders")
        self.assertEqual(two["result"]["tools"][0]["name"], "list_items")
        c.finish()

    def test_unpatched_messages_are_forwarded_byte_for_byte(self):
        c = self.client(PATCH, "odd-bytes")
        c.request({"jsonrpc": "2.0", "id": 100, "method": "initialize", "params": {}})
        c.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        note = c.recv_raw()
        self.assertEqual(
            note,
            b'{"method":"notifications/message",   "params":{"level":"info","data":"caf\\u00e9"},"jsonrpc":"2.0"}\n',
        )
        c.send({"jsonrpc": "2.0", "id": 7, "method": "resources/list"})
        odd = c.recv_raw()
        self.assertEqual(
            odd,
            b' { "jsonrpc" : "2.0" , "result" : {"b":1,"a":"caf\\u00e9 \\/ \\ud83d\\ude00"},   "id" : 7 }\n',
        )
        c.finish()

    def test_stdout_carries_only_protocol_lines(self):
        c = self.client(dict(PATCH, tools={"ghost": {"description": "x"}}))
        c.handshake()
        c.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        c.send({"jsonrpc": "2.0", "id": 2, "method": "resources/list"})
        c.recv_raw()
        c.proc.stdin.close()
        rest = []
        while True:
            raw = c.recv_raw()
            if raw is None:
                break
            rest.append(raw)
        for raw in rest:
            self.assertIsInstance(json.loads(raw.decode("utf-8")), dict)
        c.proc.wait(timeout=20)

    def test_a_stale_patch_serves_the_tool_unpatched_and_warns_once(self):
        changed = [dict(TOOLS[0], description="The server changed this"), TOOLS[1]]
        self.tools_file.write_text(json.dumps(changed), encoding="utf-8")
        c = self.client()
        c.handshake()
        for request_id in (1, 2):
            listing = c.request({"jsonrpc": "2.0", "id": request_id, "method": "tools/list"})
            self.assertEqual(listing["result"]["tools"][0]["name"], "run")
        self.assertEqual(c.finish(), 0)
        self.assertEqual(c.stderr_text.count("changed since the patch was made"), 1)
        self.assertTrue(c.stderr_text.startswith("mcp-fixer: tool 'run' changed since the patch was made"))

    def test_allow_stale_applies_the_patch_anyway(self):
        changed = [dict(TOOLS[0], description="The server changed this"), TOOLS[1]]
        self.tools_file.write_text(json.dumps(changed), encoding="utf-8")
        c = self.client(allow_stale=True)
        c.handshake()
        listing = c.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(listing["result"]["tools"][0]["name"], "search_orders")
        c.finish()
        self.assertEqual(c.stderr_text, "")

    def test_a_patched_tool_the_server_never_lists_is_warned_about_once(self):
        c = self.client(dict(PATCH, tools={"ghost": {"description": "x"}}))
        c.handshake()
        c.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        c.finish()
        self.assertEqual(c.stderr_text.count("tool 'ghost' is in the patch but the server never listed it"), 1)


class LifecycleTests(WrapCase):
    def run_in_process(self, lines, mode="normal", *extra, patch=PATCH, allow_stale=False):
        stdin = io.BytesIO(b"".join(lines))
        stdout = io.BytesIO()
        logs = []
        code = wrap.run_wrapper(patch, self.command(mode, *extra), allow_stale, stdin, stdout, logs.append)
        return code, [raw for raw in stdout.getvalue().split(b"\n") if raw], logs

    INIT = (json.dumps({"jsonrpc": "2.0", "id": 100, "method": "initialize", "params": {}}) + "\n").encode()
    INITIALIZED = (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode()
    LIST = (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n").encode()

    def test_end_of_input_ends_the_session_and_everything_is_flushed(self):
        code, lines, _ = self.run_in_process([self.INIT, self.INITIALIZED, self.LIST])
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["result"]["tools"][0]["name"], "search_orders")

    def test_a_server_that_ignores_end_of_input_is_stopped_after_the_grace_period(self):
        pid_file = self.dir / "pid"
        original = wrap.SHUTDOWN_GRACE_SECONDS
        wrap.SHUTDOWN_GRACE_SECONDS = 0.5
        self.addCleanup(setattr, wrap, "SHUTDOWN_GRACE_SECONDS", original)
        started = time.monotonic()
        code, _, _ = self.run_in_process([self.INIT], "hang-on-eof", "--pid-file", str(pid_file))
        self.assertEqual(code, 0)
        self.assertLess(time.monotonic() - started, 10)
        self.assertTrue(support.wait_until_gone(int(pid_file.read_text())))

    def test_a_server_that_crashes_propagates_its_exit_code_after_its_last_output(self):
        code, lines, _ = self.run_in_process([self.INIT, self.INITIALIZED, self.LIST], "crash")
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(lines[0])["id"], 100)  # the response it wrote before dying

    def test_a_server_that_exits_at_once_propagates_its_exit_code(self):
        code, lines, _ = self.run_in_process([self.INIT], "exit")
        self.assertEqual((code, lines), (4, []))

    def test_a_command_that_does_not_exist_is_a_client_error(self):
        from mcp_fixer.stdio_client import ClientError
        with self.assertRaises(ClientError):
            wrap.run_wrapper(PATCH, ["definitely-not-a-real-command-xyz"], False, io.BytesIO(), io.BytesIO(), lambda text: None)

    def test_warnings_go_to_the_log_once(self):
        patch = dict(PATCH, tools={"ghost": {"description": "x"}})
        _, _, logs = self.run_in_process([self.INIT, self.INITIALIZED, self.LIST, self.LIST], patch=patch)
        self.assertEqual(logs, ["tool 'ghost' is in the patch but the server never listed it"])

    def test_the_server_process_is_gone_after_a_normal_session(self):
        pid_file = self.dir / "pid"
        self.run_in_process([self.INIT], "normal", "--pid-file", str(pid_file))
        self.assertTrue(support.wait_until_gone(int(pid_file.read_text())))


class BrokenPatchTests(WrapCase):
    def run_cli(self, patch_text):
        path = self.dir / "bad.json"
        path.write_text(patch_text, encoding="utf-8")
        pid_file = self.dir / "pid"
        done = subprocess.run(
            [sys.executable, "-m", "mcp_fixer", "wrap", "--patch", str(path), "--",
             sys.executable, str(support.FAKE_SERVER), "--mode", "normal", "--tools", str(self.tools_file), "--pid-file", str(pid_file)],
            capture_output=True, env=dict(__import__("os").environ, PYTHONPATH=str(support.SRC)), timeout=60,
        )
        return done, pid_file

    def test_a_broken_patch_exits_2_before_the_server_is_spawned(self):
        for text in ("{not json", json.dumps({"patchVersion": 2, "tools": {}}),
                     json.dumps({"patchVersion": 1, "tools": {"a": {"rename": "z"}, "b": {"rename": "z"}}})):
            with self.subTest(text[:30]):
                done, pid_file = self.run_cli(text)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertEqual(done.stdout, b"")
                err = done.stderr.decode("utf-8")
                self.assertTrue(err.startswith("error: "), err)
                self.assertEqual(err.count("\n"), 1)
                self.assertFalse(pid_file.exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_wrap.py" 2>&1 | tail -4`
Expected: ERROR, `AttributeError: module 'mcp_fixer.wrap' has no attribute 'run_wrapper'` for the lifecycle tests, and the interactive and broken-patch tests fail because the `wrap` subcommand does not exist yet (Task 5 adds it; they pass after Task 5). Only `LifecycleTests` can pass by the end of this task.

- [ ] **Step 6: Write `run_wrapper`**

Append to `servers/mcp-fixer/src/mcp_fixer/wrap.py` (and add the imports `import subprocess` and `import threading` and `from .stdio_client import _kill_tree, _spawn, child_environment, resolve_command` at the top):

```python
SHUTDOWN_GRACE_SECONDS = 5.0
_OUTPUT_JOIN_SECONDS = 2.0


def _exit_code(returncode):
    return returncode if returncode is not None and 0 <= returncode <= 255 else 1


def run_wrapper(patch, command, allow_stale=False, stdin=None, stdout=None, log=None):
    """Run `command` behind the patch: client on `stdin`/`stdout`, real server on pipes.

    Returns the exit code for the wrapper process. Raises ClientError when the server cannot be
    started.
    """
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    router = Router(patch, allow_stale, log)
    proc = _spawn(resolve_command(command), child_environment(inherit=True), stderr=None)
    done = threading.Event()
    out_lock = threading.Lock()

    def server_to_client():
        try:
            for raw in proc.stdout:
                data = router.server_line(raw)
                with out_lock:
                    stdout.write(data)
                    stdout.flush()
        except (OSError, ValueError):
            pass
        finally:
            done.set()

    def client_to_server():
        try:
            for raw in stdin:
                proc.stdin.write(router.client_line(raw))
                proc.stdin.flush()
        except (OSError, ValueError):
            pass
        finally:
            try:
                proc.stdin.close()
            except (OSError, ValueError):
                pass
            done.set()

    output_thread = threading.Thread(target=server_to_client, daemon=True)
    input_thread = threading.Thread(target=client_to_server, daemon=True)
    output_thread.start()
    input_thread.start()
    done.wait()

    stopped = False
    try:
        proc.wait(timeout=SHUTDOWN_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        stopped = True
        _kill_tree(proc, graceful=True)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _kill_tree(proc, graceful=False)
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
    output_thread.join(timeout=_OUTPUT_JOIN_SECONDS)  # let the server's last words reach the client
    _kill_tree(proc, graceful=False)  # POSIX: stop descendants the server left behind
    if not output_thread.is_alive():
        try:
            proc.stdout.close()
        except (OSError, ValueError):
            pass
    router.finish()
    return 0 if stopped else _exit_code(proc.returncode)
```

- [ ] **Step 7: Run the lifecycle tests**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_wrap.py" -k Lifecycle -v 2>&1 | tail -14`
Expected: all `LifecycleTests` PASS. If a lifecycle test hangs, the shutdown logic is wrong: check that the client-EOF path closes the server's stdin and that `done` is set; do not loosen the timeouts.

- [ ] **Step 8: Commit**

```bash
python -m unittest discover -s tests 2>&1 | tail -2
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer wrapper proxy with shutdown handling and a test client

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

(The interactive and broken-patch tests in `test_wrap.py` still fail until Task 5 adds the `wrap` subcommand; that is expected here, and the commit message above does not claim otherwise. If a green commit is required at every step, add `@unittest.skip("needs the wrap subcommand (Task 5)")` to `InteractiveTests` and `BrokenPatchTests` now and remove the two decorators in Task 5 Step 3.)

---

### Task 5: The command line

**Files:**
- Modify: `servers/mcp-fixer/src/mcp_fixer/cli.py` (replace the file), `servers/mcp-fixer/tests/test_cli.py` (append two classes), `servers/mcp-fixer/tests/test_wrap.py` (remove the skip decorators if added)

**Interfaces:**
- Consumes: `patch_gen.generate_patch`/`render_patch` (Task 2), `patch_format.load_patch`/`PatchError` (Task 1), `wrap.run_wrapper` (Task 4), the existing `score` pieces.
- Produces: `mcp-fixer patch` and `mcp-fixer wrap`; `cli.main` still returns an `int`.

- [ ] **Step 1: Write the failing tests**

Append to `servers/mcp-fixer/tests/test_cli.py` before the `if __name__` line (the file already imports `contextlib`, `io`, `json`, `os`, `subprocess`, `sys`, `tempfile`, `unittest`, `Path`, `support` and `cli`, and defines `run`, `CliCase`, `MESSY`, `CLEAN` and `CLEAN_TOOLS`):

```python
class PatchCommandTests(CliCase):
    def test_a_patch_is_written_to_stdout_and_validates(self):
        code, out, err = run("patch", "--tools-json", MESSY)
        self.assertEqual((code, err), (0, ""))
        from mcp_fixer import patch_format
        patch = patch_format.validate_patch(json.loads(out))
        self.assertEqual(list(patch["tools"]), ["run", "searchItems"])

    def test_the_same_input_gives_byte_identical_output(self):
        self.assertEqual(run("patch", "--tools-json", MESSY)[1], run("patch", "--tools-json", MESSY)[1])

    def test_out_writes_a_new_file_and_prints_nothing(self):
        target = self.dir / "p.json"
        code, out, err = run("patch", "--tools-json", MESSY, "--out", str(target))
        self.assertEqual((code, out, err), (0, "", ""))
        self.assertEqual(target.read_text(encoding="utf-8"), run("patch", "--tools-json", MESSY)[1])
        self.assertNotIn("\r", target.read_bytes().decode("utf-8"))

    def test_an_existing_out_file_is_never_overwritten_without_force(self):
        target = self.dir / "p.json"
        target.write_text("my edits", encoding="utf-8")
        self.assert_usage_error("patch", "--tools-json", MESSY, "--out", str(target), fragment="exists; use --force")
        self.assertEqual(target.read_text(encoding="utf-8"), "my edits")

    def test_force_overwrites(self):
        target = self.dir / "p.json"
        target.write_text("my edits", encoding="utf-8")
        code, _, _ = run("patch", "--tools-json", MESSY, "--out", str(target), "--force")
        self.assertEqual(code, 0)
        self.assertIn('"patchVersion"', target.read_text(encoding="utf-8"))

    def test_an_unwritable_out_is_a_usage_error(self):
        self.assert_usage_error("patch", "--tools-json", CLEAN, "--out", str(self.dir / "no-dir" / "p.json"), fragment="cannot write")

    def test_the_same_input_errors_as_score(self):
        self.assert_usage_error("patch", fragment="--tools-json")
        self.assert_usage_error("patch", "--tools-json", CLEAN, "--", sys.executable, "-V", fragment="not both")
        self.assert_usage_error("patch", "--tools-json", str(self.dir / "nope.json"), fragment="cannot read")
        self.assert_usage_error("patch", "--tools-json", self.write("bad.json", "{nope"), fragment="not valid JSON")
        self.assert_usage_error("patch", "--tools-json", CLEAN, "--timeout", "nan")

    def test_a_stdio_server_gives_a_patch_with_its_source(self):
        args = ["--", sys.executable, str(support.FAKE_SERVER), "--mode", "normal", "--tools", CLEAN_TOOLS]
        code, out, err = run("patch", "--timeout", "10", *args)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["source"], {"serverName": "fake-server", "serverVersion": "1.2.3"})

    def test_a_schema_nested_very_deeply_never_gives_a_traceback(self):
        schema = '{"type":"object","properties":{"x":' * 900 + '{"type":"string"}' + "}}" * 900
        text = '[{"name":"deep_tool","description":"A deeply nested tool schema here.","inputSchema":' + schema + "}]"
        code, out, err = run("patch", "--tools-json", self.write("deep.json", text))
        self.assertIn(code, (0, 2))
        self.assertNotIn("Traceback", err)


class WrapCommandTests(CliCase):
    def test_a_missing_command_is_a_usage_error(self):
        patch = self.write("p.json", json.dumps({"patchVersion": 1, "tools": {}}))
        self.assert_usage_error("wrap", "--patch", patch, fragment="server command")

    def test_a_missing_patch_file_is_a_usage_error(self):
        self.assert_usage_error("wrap", "--patch", str(self.dir / "nope.json"), "--", sys.executable, "-V", fragment="cannot read")

    def test_an_invalid_patch_is_a_usage_error_naming_the_tool(self):
        patch = self.write("p.json", json.dumps({"patchVersion": 1, "tools": {"run": {"rename": ""}}}))
        self.assert_usage_error("wrap", "--patch", patch, "--", sys.executable, "-V", fragment="tool 'run': rename must be")

    def test_a_server_command_that_does_not_exist_is_a_usage_error(self):
        patch = self.write("p.json", json.dumps({"patchVersion": 1, "tools": {}}))
        self.assert_usage_error("wrap", "--patch", patch, "--", "definitely-not-a-real-command-xyz", fragment="cannot find the server command")

    def test_the_patch_option_is_required(self):
        code, out, err = run("wrap", "--", sys.executable, "-V")
        self.assertEqual(code, 2)
        self.assertIn("--patch", err)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_cli.py" -k PatchCommand -k WrapCommand 2>&1 | tail -4`
Expected: failures: argparse rejects the unknown `patch` and `wrap` commands (exit 2 with an argparse usage message, not the expected output).

- [ ] **Step 3: Replace `cli.py`**

Overwrite `servers/mcp-fixer/src/mcp_fixer/cli.py`:

```python
"""Command line: mcp-fixer score, patch and wrap."""
import argparse
import json
import math
import sys
from pathlib import Path

from . import __version__
from .patch_format import PatchError, load_patch
from .patch_gen import generate_patch, render_patch
from .report import render_json, render_text
from .score import FILE_SOURCE, score_tools
from .stdio_client import ClientError, list_tools_stdio
from .wrap import run_wrapper


class UsageError(Exception):
    """A problem with the command line or an input file, reported as `error: ...` with exit 2."""


def _add_input_options(parser):
    parser.add_argument("--tools-json", metavar="FILE", help="a saved tools/list result (a JSON array or an object with a tools array)")
    parser.add_argument("--env", action="append", default=[], metavar="KEY=VALUE", help="environment variable for the server (repeatable)")
    parser.add_argument("--timeout", type=float, default=30.0, metavar="SECONDS", help="per-request timeout (default 30)")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="mcp-fixer",
        description="Score an MCP server's tool definitions, write a patch for them, and run a wrapper that applies it.",
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
    _add_input_options(score)
    score.add_argument("--format", choices=("text", "json"), default="text", help="output format (default text)")
    score.add_argument("--out", metavar="FILE", help="write the report to FILE instead of stdout")
    score.add_argument("--min-score", type=float, metavar="N", help="exit with code 1 when the score is below N")

    patch = sub.add_parser(
        "patch",
        usage="mcp-fixer patch [options] (--tools-json FILE | -- SERVER_COMMAND [ARGS...])",
        description=(
            "Write a patch file for a server's tool definitions from the lint findings: enums and "
            "trimmed descriptions are filled in (listed under review), everything else becomes a "
            "todo entry. Read-only like score."
        ),
    )
    _add_input_options(patch)
    patch.add_argument("--out", metavar="FILE", help="write the patch to FILE instead of stdout (never overwrites without --force)")
    patch.add_argument("--force", action="store_true", help="overwrite an existing --out file")

    wrap = sub.add_parser(
        "wrap",
        usage="mcp-fixer wrap --patch FILE [--allow-stale] -- SERVER_COMMAND [ARGS...]",
        description=(
            "Run a stdio MCP server behind a patch: the client sees the patched tool definitions and "
            "every other message passes through unchanged. Use this command where the client config "
            "would have the real server's command."
        ),
    )
    wrap.add_argument("--patch", required=True, metavar="FILE", help="the patch file (see mcp-fixer patch)")
    wrap.add_argument("--allow-stale", action="store_true", help="apply a patch entry even when the server's tool has changed since the patch was made")
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
    except RecursionError:
        raise UsageError(f"{path} is not valid JSON (nested too deeply)") from None
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


def read_tools(args, command):
    """The tool list and its source description, from --tools-json or a spawned server."""
    if args.tools_json and command:
        raise UsageError("give either --tools-json or a server command after --, not both")
    if not args.tools_json and not command:
        raise UsageError("give --tools-json FILE, or a server command after --")
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        raise UsageError("--timeout must be a finite number greater than 0")
    env = parse_env(args.env)
    if args.tools_json:
        return load_tools_file(args.tools_json), dict(FILE_SOURCE)
    tools, info = list_tools_stdio(command, env, args.timeout)
    return tools, {"kind": "stdio", **info}


def write_file(path, text, overwrite):
    try:
        with open(path, "w" if overwrite else "x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except FileExistsError:
        raise UsageError(f"{path} exists; use --force to overwrite") from None
    except OSError as exc:
        raise UsageError(f"cannot write {path}: {exc.strerror or exc}") from None


def run_score(args, command):
    if args.min_score is not None and not math.isfinite(args.min_score):
        raise UsageError("--min-score must be a finite number")
    tools, source = read_tools(args, command)
    try:
        result = score_tools(tools, source)
    except RecursionError:
        raise UsageError("the tool list is nested too deeply to score") from None
    text = render_json(result) if args.format == "json" else render_text(result)
    if args.out:
        write_file(args.out, text, overwrite=True)
    else:
        emit(text)
    if args.min_score is not None and result["score"] < args.min_score:
        return 1
    return 0


def run_patch(args, command):
    tools, source = read_tools(args, command)
    try:
        text = render_patch(generate_patch(tools, source))
    except RecursionError:
        raise UsageError("the tool list is nested too deeply to patch") from None
    if args.out:
        write_file(args.out, text, overwrite=args.force)
    else:
        emit(text)
    return 0


def run_wrap(args, command):
    patch = load_patch(args.patch)
    if not command:
        raise UsageError("give the real server command after --")
    return run_wrapper(patch, command, args.allow_stale)


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    command = []
    if "--" in args:
        split = args.index("--")
        command, args = args[split + 1:], args[:split]
    parsed = build_parser().parse_args(args)
    handlers = {"score": run_score, "patch": run_patch, "wrap": run_wrap}
    try:
        return handlers[parsed.command](parsed, command)
    except (UsageError, ClientError, PatchError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
```

If Task 4 added the two `@unittest.skip` decorators in `test_wrap.py`, remove them now.

- [ ] **Step 4: Run all the tests**

Run: `python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -6`
Expected: all PASS, including `InteractiveTests` and `BrokenPatchTests` from Task 4. The order of checks in `run_wrap` matters for `test_a_missing_command_is_a_usage_error`: the patch loads first, then the missing command is reported; both tests above give a valid patch where they expect the command error. If `test_the_patch_option_is_required` sees an argparse message, that is expected: it asserts only exit code 2 and that `--patch` is named.

- [ ] **Step 5: Smoke the real commands by hand**

```bash
export PYTHONPATH=servers/mcp-fixer/src
python -m mcp_fixer patch --tools-json servers/mcp-fixer/tests/fixtures/messy_tools.json | head -30
python -m mcp_fixer patch --tools-json servers/mcp-fixer/tests/fixtures/messy_tools.json > /tmp/msg.json; python -m mcp_fixer wrap --patch /tmp/msg.json -- python servers/mcp-fixer/tests/fake_server.py --tools servers/mcp-fixer/tests/fixtures/messy_tools.json < /dev/null; echo "exit $?"
```

Expected: the first prints a patch with `run` and `searchItems` entries; the second exits 0 with no output (stdin was empty) and no traceback.

- [ ] **Step 6: Commit**

```bash
python -m unittest discover -s tests 2>&1 | tail -2
python scripts/validate.py
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer patch and wrap commands

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: README, version and final checks

**Files:**
- Modify: `servers/mcp-fixer/README.md`, `servers/mcp-fixer/pyproject.toml`, `servers/mcp-fixer/src/mcp_fixer/__init__.py`, `CHANGELOG.md`

**Interfaces:**
- Consumes: the shipped behavior of Tasks 1 to 5.

- [ ] **Step 1: Bump the version in both places**

In `servers/mcp-fixer/pyproject.toml` change `version = "0.1.0"` to `version = "0.2.0"`, and in `servers/mcp-fixer/src/mcp_fixer/__init__.py` change `__version__ = "0.1.0"` to `__version__ = "0.2.0"`. Run `python -m unittest discover -s servers/mcp-fixer/tests -p "test_package.py"`: PASS (it compares the two).

- [ ] **Step 2: Update the README**

Write this script to `$SP/readme_patch.py` and run it from the repo root:

```python
from pathlib import Path

p = Path("servers/mcp-fixer/README.md")
s = p.read_text(encoding="utf-8")


def swap(old, new):
    global s
    assert old in s, old[:70]
    s = s.replace(old, new, 1)


swap(
    "Part of [Naren's Claude Toolkit](https://github.com/NarenDawar/narens-claude-toolkit). This is the first of three planned parts: **score** (this), then a patcher and wrapper that apply the fixes, then a benchmark that shows tool selection did not get worse.",
    "Part of [Naren's Claude Toolkit](https://github.com/NarenDawar/narens-claude-toolkit). Three planned parts: **score** (finds the problems), **patch and wrap** (applies fixes without changing the server) and a benchmark that shows tool selection did not get worse. The first two exist; the benchmark does not, so this tool makes no claim that a patch improves tool selection.",
)

PATCH_WRAP = """## Fix it: patch and wrap

`mcp-fixer patch` turns the findings into a patch file, and `mcp-fixer wrap` runs a proxy in front of the real server that shows the client the patched tool definitions. The real server is not changed.

```text
PYTHONPATH=servers/mcp-fixer/src python -m mcp_fixer patch -- npx -y some-mcp-server --out orders.patch.json
# edit orders.patch.json: fill in the todo entries, check the review ones
PYTHONPATH=servers/mcp-fixer/src python -m mcp_fixer wrap --patch orders.patch.json -- npx -y some-mcp-server
```

**What the generator fills in.** Enums that a parameter's description lists in prose, and descriptions over 500 characters trimmed to whole sentences. Each is noted under `review`, because an inferred enum may be incomplete and a trim loses text. **Everything else is a `todo`:** missing or short descriptions, undescribed or untyped parameters, generic names, a missing `required` list, near-duplicate descriptions. Those need real writing, by you or by Claude; the tool calls no model. `patch --out` never overwrites an existing file without `--force`.

**The patch file** is plain JSON, keyed by each tool's original name:

```json
{
  "patchVersion": 1,
  "tools": {
    "run": {
      "base": "<fingerprint of the original tool; filled in by patch>",
      "rename": "search_orders",
      "description": "Search orders by status or customer.",
      "params": {"order": {"description": "Sort order", "type": "string", "enum": ["asc", "desc"]}},
      "required": ["order"]
    }
  }
}
```

Every field is optional. A parameter entry may set `description`, `type`, `enum` and `default`. `review`, `todo`, `context` and `notes` are for people and are ignored by the wrapper. Unknown fields are an error, so typos are caught. A broken patch is a one-line error and exit code 2 before the real server starts.

**What the wrapper does.** It forwards every message as the original bytes, except: it patches the tool list the server sends, and it turns a renamed tool's name back to the original on `tools/call`. It never enforces an enum and never changes call arguments or results. If a tool has changed since the patch was made (its fingerprint no longer matches `base`), that tool is served unpatched with one warning on stderr; `--allow-stale` applies the patch anyway. Put it where the real server's command goes in your MCP client's config, for example:

```json
{
  "mcpServers": {
    "orders": {
      "command": "python",
      "args": ["-m", "mcp_fixer", "wrap", "--patch", "orders.patch.json", "--", "npx", "-y", "orders-server"],
      "env": {"PYTHONPATH": "/path/to/servers/mcp-fixer/src"}
    }
  }
}
```

That configuration has not been tried in a real client yet; it is the standard `mcpServers` shape. Unlike `score`, the wrapper passes your whole environment to the real server, because it stands in for that server.

"""
swap("## The rules\\n", PATCH_WRAP + "## The rules\\n")

swap(
    "- A server that floods the client with requests is cut off after 50 of them.\\n",
    "- A server that floods the client with requests is cut off after 50 of them.\\n- The wrapper does not rewrite errors or results (error normalization is not included), and a patch cannot target tools with duplicate names separately.\\n",
)
swap(
    "Calling tools (so no check that errors are consistent), remote HTTP or OAuth connections (use `--tools-json` for those), any model or accuracy benchmark, and writing patches.",
    "Calling tools (so no check that errors are consistent), remote HTTP or OAuth connections (use `--tools-json` for those), any model, error normalization, and the accuracy benchmark.",
)
with open(p, "w", encoding="utf-8", newline="\\n") as f:
    f.write(s)
print("ok")
```

(Inside that script the sequences written as `\\n` are literal backslash-n characters; write them as `\n` in the file.)

- [ ] **Step 3: Add the changelog entry**

In `CHANGELOG.md`, under `## [Unreleased]` / `### Added`, add as the first bullet:

```
- `mcp-fixer patch` and `mcp-fixer wrap` (second of three parts): `patch` writes an editable patch file from the lint findings (enums found in descriptions and trimmed long descriptions are filled in and flagged for review; everything else becomes a todo), and `wrap` runs a stdio proxy in front of a real MCP server that shows the client the patched tool definitions, renames included, while forwarding every other message byte for byte. It never enforces an enum or changes calls, serves a tool unpatched when the server has changed it, and makes no claim yet that a patch improves tool selection.
```

- [ ] **Step 4: Run the full set of checks**

```bash
python scripts/build_catalog.py --check && echo catalog-current
python -m unittest discover -s tests 2>&1 | tail -3
python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -3
python scripts/validate.py
git diff --stat main -- docs/superpowers | tail -4
git status --short | head
ls -d %* 2>/dev/null | wc -l
```

Expected: `catalog-current`; both suites PASS; `OK: all plugins valid`; the `docs/superpowers` diff lists only the new spec and this plan; a clean tree after the commit below; no stray `%SystemDrive%` folder (the last command prints `0`).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
docs: mcp-fixer patch and wrap README, changelog and version 0.2.0

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

## Handoff after the merge (not tasks)

1. Merge `mcp-fixer-patch` into `main` locally (the finishing step). Pushing is a separate confirmed step.
2. **Live check, yours:** run `mcp-fixer patch` against a real stdio server, edit the patch, and put `wrap` in front of it in a real MCP client (for example Claude Code's `claude mcp add`), then compare the tool list the client shows. The client configuration in the README is the standard shape but untested.
3. Next sub-project: the tool-selection benchmark (sub-project 3), which needs a decision on how it reaches a model (an API key, or driving `claude -p`).

## Self-review notes

- **Spec coverage:** patch format, strict validation and apply semantics (Task 1); generator, trimming, review and todo entries, notes, duplicates, determinism (Task 2); router rules, stale handling, renames, collisions, warnings (Task 3); proxy lifetime, environment, exit codes, stderr (Task 4); CLI, `--force`, exit codes (Task 5); README, CHANGELOG, version 0.2.0 (Task 6); CI is unchanged because the existing job already runs this folder's tests.
- **Spec details made precise here:** `Router(log)` and the default logger's prefix, injectable streams for `run_wrapper`, the active rename map, re-serialize only when a page changed, the exact `context` shape.
- **Type consistency:** `fingerprint`, `validate_patch`, `load_patch`, `apply_entry`, `trim_description`, `generate_patch`, `render_patch`, `Router`, `run_wrapper` and `child_environment(extra, inherit)` are defined once and used with the same names and signatures in the tests and the CLI.
- **Known unknowns the executor settles by running the tests:** exact wording of messages in the CLI tests, Windows pipe timing in the interactive tests, and the todo set for the messy fixture (derived from the scorer's findings).
