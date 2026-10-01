# rule-promoter Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and ship the `rule-promoter` skill: it reads a project's `CLAUDE.md`, classifies the enforceable rules, writes them into a `rules.json` enforced by a tested stdlib hook engine, proves each rule blocks a violation, and installs the hooks into `.claude/settings.json` after confirmation.

**Architecture:** One plugin, `plugins/rule-promoter/`, scaffolded by `scripts/new_skill.py`. Two stdlib scripts live in the skill folder: `rule_hook.py` (the engine, copied into a user's `.claude/hooks/`) and `settings_merge.py` (a deterministic helper the skill uses to pick a Python launcher and to merge hook entries into `settings.json`). `SKILL.md` owns the judgment: reading, classifying, reviewing, installing, verifying. Both scripts are built test-first with `unittest`; real hook payloads are captured from Claude Code and used as fixtures; the skill text is verified with baseline and with-skill scenario runs plus a real headless end-to-end block.

**Tech Stack:** Python 3.9+ standard library, Markdown, JSON, the repo tooling, general-purpose subagents (model `sonnet`) as the scenario runner, a real headless Claude Code session for the end-to-end check.

**Spec:** `docs/superpowers/specs/2026-10-01-rule-promoter-design.md`

## Global Constraints

- Plugin and skill name `rule-promoter`; `SKILL.md` frontmatter has `name` and a single-line, double-quoted `description` starting with `Use when`; no branding footer in `SKILL.md`.
- Engine and helper are Python 3.9+ standard library only; files written with LF line endings; UTF-8 read with BOM tolerance.
- Rule types in v1 are exactly `protected_path`, `blocked_command`, `banned_content`, `stop_check`. The skill never invents another.
- Engine blocking contract: a `PreToolUse` violation prints `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"Rule <id>: <message> (from <source>)"}}` and exits 0. A `Stop` violation prints `{"decision":"block","reason":...}` and exits 0. An allow prints nothing and exits 0. `stop_hook_active` true always allows.
- Fail open: an internal error, malformed payload, or missing or invalid rules file prints `[rule_hook] <reason>` on stderr and exits 1 (a non-blocking error). An uncovered tool is allowed silently.
- `PreToolUse` handling makes no subprocess calls. `stop_check` timeouts allow the stop with a stderr warning.
- Hooks are guardrails, not a security boundary; the skill says so.
- The skill never writes `rules.json`, hook files or `settings.json` before the user has reviewed the rule table, and never writes `settings.json` before showing the diff and getting a yes.
- Settings entries are identified by `rule_hook.py` in the hook's args; re-running replaces only them. Invalid existing `settings.json` stops the install.
- Author `Naren`; GitHub user `NarenDawar`; repo `narens-claude-skills`; marketplace `narens-claude-skills`. Free and MIT: no pricing work.
- Do not push to GitHub in this plan; pushing is a separate, explicit user request.
- Scratch work (captures, scenario projects, outputs) lives in the session scratchpad, never in the repo: `C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a/scratchpad` (called `$SP` below). Scenario runs never touch the repo or the real `~/.claude`.
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

**Spec clarifications decided in this plan:**
- `scripts/settings_merge.py` is a second skill-folder script (not copied into projects). The skill, not the engine, writes `settings.json`, by running `settings_merge.py plan` (shows a diff) and then `apply` after confirmation. This keeps the merge deterministic.
- Proof payloads for `stop_check` rules carry `simulate_exit` (0 or 1), which only `selftest` honors, so selftest proves the block and allow wiring without running the real command. The real command is exercised in the end-to-end session.
- In `selftest` and `check`, the project directory is `CLAUDE_PROJECT_DIR`, else the payload `cwd`, else the current directory.
- A glob matches the whole project-relative path; use `**/name` to match at any depth.

## Review Focus

Input classes the spec implies but its test list does not spell out. Each is pinned by a test below:

- **Compound and quoted shell commands:** `cd x && git push --force` is caught through segment splitting; `echo "a && git push --force"` stays one segment (and over-blocks, which is documented). Task 3 (`test_compound_command_is_caught`, `test_quoted_operators_do_not_split`).
- **Windows paths, case and drives:** backslashes, case-insensitive matching on Windows, absolute paths inside and outside the project. Task 2 (`RelativePathTests`, `test_globs_are_case_insensitive_on_windows`).
- **Payload shape drift across tools and Claude Code versions:** missing keys, nested `edits[]`, `NotebookEdit`, non-dict `tool_input`, and the real captured payloads. Task 2 (`CollectTests`, `RealPayloadTests`).
- **Stop-hook hazards:** `stop_hook_active` loop guard, a hanging command, huge command output. Task 4.
- **`settings.json` merge hazards:** unrelated hooks preserved, repeat installs idempotent, invalid JSON refused, BOM and CRLF in the existing file. Task 6.

---

## File Structure

| File | Responsibility |
|---|---|
| `plugins/rule-promoter/skills/rule-promoter/scripts/rule_hook.py` | The engine: path and glob matching, rule validation, four rule types, `check`, `selftest` |
| `plugins/rule-promoter/skills/rule-promoter/scripts/settings_merge.py` | Launcher picking and idempotent `settings.json` merge (`launcher`, `plan`, `apply`) |
| `plugins/rule-promoter/skills/rule-promoter/SKILL.md` | The conversation and the classification guide |
| `plugins/rule-promoter/README.md` | Public per-skill page |
| `tests/test_rule_hook.py`, `tests/test_settings_merge.py` | Unit tests |
| `tests/fixtures/rule_hook/*.json` | Real hook payloads captured from Claude Code (`{PROJECT}` placeholders) |
| `tests/fixtures/rule_promoter/claude_md/*.md` + `expected.json` | Sample `CLAUDE.md` files with expected classifications |

Run all tests with: `python -m unittest discover -s tests -v`

---

### Task 1: Scaffold the plugin and capture real hook payloads

**Files:**
- Create (generated): `plugins/rule-promoter/` (plugin.json, README.md, `skills/rule-promoter/SKILL.md`), marketplace/catalog entries
- Create: `plugins/rule-promoter/skills/rule-promoter/scripts/` (empty directory for now)
- Create: `tests/fixtures/rule_hook/PreToolUse-Write.json`, `PreToolUse-Edit.json`, `PreToolUse-Bash.json`, `Stop.json` (and `PreToolUse-MultiEdit.json` if that tool exists)
- Create (scratch, not committed): `$SP/capture/` (project, capture hook, raw captures)

**Interfaces:**
- Produces: the plugin skeleton and real payload fixtures with `{PROJECT}` placeholders. Fixture file names start with `PreToolUse-<Tool>` or `Stop`. The Write capture's content contains `hello capture`; the Edit capture's `new_string` contains `hello edited`; the Bash capture's command is `echo done`.

- [ ] **Step 1: Scaffold with the repo tool**

```bash
cd "C:/Users/naren/Documents/claude-skills"
python scripts/new_skill.py rule-promoter "Use when the user wants rules in CLAUDE.md enforced with hooks, says Claude keeps ignoring a CLAUDE.md rule, or asks to turn CLAUDE.md rules into hooks (for example 'promote my CLAUDE.md rules to hooks' or 'make Claude stop editing migrations')."
mkdir -p plugins/rule-promoter/skills/rule-promoter/scripts tests/fixtures/rule_hook
python scripts/validate.py && python -m unittest discover -s tests 2>&1 | tail -3 && python scripts/build_catalog.py --check; echo exit=$?
```

Expected: `Created ...\plugins\rule-promoter`; `OK: all plugins valid`; tests OK; `exit=0`.

- [ ] **Step 2: Build the capture project**

```bash
SP="C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a/scratchpad"
CAP="$SP/capture"; rm -rf "$CAP"; mkdir -p "$CAP/proj/.claude" "$CAP/out"
cat > "$CAP/capture_hook.py" <<'EOF'
import json, os, sys, time

data = sys.stdin.buffer.read().decode("utf-8-sig")
payload = json.loads(data)
name = payload.get("hook_event_name", "event") + "-" + (payload.get("tool_name") or "none")
out = os.environ["CAPTURE_DIR"]
os.makedirs(out, exist_ok=True)
with open(os.path.join(out, f"{name}-{int(time.time() * 1000)}.json"), "w", encoding="utf-8") as f:
    f.write(data)
EOF
cat > "$CAP/settings.json" <<EOF
{"hooks": {
  "PreToolUse": [{"matcher": ".*", "hooks": [{"type": "command", "command": "python \"$CAP/capture_hook.py\"", "timeout": 10}]}],
  "Stop": [{"hooks": [{"type": "command", "command": "python \"$CAP/capture_hook.py\"", "timeout": 10}]}]
}}
EOF
cp "$CAP/settings.json" "$CAP/proj/.claude/settings.json"
echo "# capture project" > "$CAP/proj/README.md"; cat "$CAP/settings.json" | head -3
```

- [ ] **Step 3: Run a real headless session that exercises Write, Edit and Bash**

```bash
cd "$CAP/proj"
export CAPTURE_DIR="$CAP/out"
claude -p "Do exactly these steps with your tools, then stop. 1) Write a file notes.txt containing exactly: hello capture. 2) Edit notes.txt, replacing 'hello capture' with 'hello edited'. 3) Run the Bash command: echo done. 4) If a MultiEdit tool is available, use it on notes.txt to replace 'hello' with 'hi' and 'edited' with 'changed'; otherwise skip this step." --allowedTools "Write" "Edit" "MultiEdit" "Bash(echo:*)" --max-turns 12 --no-session-persistence > "$CAP/session.txt" 2>&1; tail -5 "$CAP/session.txt"
ls "$CAP/out"
```

Expected: `ls` lists files starting `PreToolUse-Write-`, `PreToolUse-Edit-`, `PreToolUse-Bash-` and `Stop-none-`. If `out/` is empty, the project hooks were not trusted in headless mode: rerun the same `claude -p ...` command adding `--settings "$CAP/settings.json"` (loads the hooks from a settings file instead). If it is still empty, stop and report to the user; the fixtures cannot be captured and the engine's payload assumptions would be unverified.

- [ ] **Step 4: Sanitize into fixtures**

```bash
python - "$CAP" <<'PYEOF'
import glob, json, os, re, sys

cap = sys.argv[1]
proj_variants = {os.path.join(cap, "proj"), os.path.join(cap, "proj").replace("/", "\\"), os.path.realpath(os.path.join(cap, "proj"))}
dest = "tests/fixtures/rule_hook"
seen = {}
for path in sorted(glob.glob(os.path.join(cap, "out", "*.json"))):
    base = os.path.basename(path)
    key = re.match(r"(PreToolUse-[A-Za-z]+|Stop)", base).group(1)
    if key in seen:
        continue  # keep the first capture of each kind
    text = open(path, encoding="utf-8").read()
    data = json.loads(text)
    flat = json.dumps(data)
    for variant in proj_variants:
        flat = flat.replace(json.dumps(variant)[1:-1], "{PROJECT}")
    data = json.loads(flat)
    for volatile in ("session_id", "transcript_path", "scratchpad_dir", "prompt_id", "tool_use_id"):
        if volatile in data:
            data[volatile] = "<" + volatile + ">"
    out_name = "Stop.json" if key == "Stop" else key + ".json"
    with open(os.path.join(dest, out_name), "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    seen[key] = out_name
print(sorted(seen.values()))
PYEOF
ls tests/fixtures/rule_hook; grep -l "hello capture" tests/fixtures/rule_hook/*.json; grep -l "hello edited" tests/fixtures/rule_hook/*.json; grep -c "{PROJECT}" tests/fixtures/rule_hook/*.json
```

Expected: `PreToolUse-Write.json`, `PreToolUse-Edit.json`, `PreToolUse-Bash.json`, `Stop.json` exist; the Write fixture contains `hello capture`, the Edit fixture contains `hello edited`; the `{PROJECT}` placeholder appears in the Write and Edit fixtures (their `file_path`) and in `cwd`. Open the Write and Edit fixtures and record in `$SP/capture/notes.md` the exact `tool_input` field names (for example `file_path`, `content`, `old_string`, `new_string`). If the Edit field names are not among `file_path` and one of the engine's `TEXT_KEYS` (`content`, `file_content`, `new_string`, `new_content`, `new_source`), add the actual text key to `TEXT_KEYS` in Task 2 and say so in the ledger.

- [ ] **Step 5: Verify and commit**

```bash
python scripts/validate.py && python -m unittest discover -s tests 2>&1 | tail -3
git add plugins .claude-plugin README.md llms.txt tests/fixtures
git commit -m "feat: scaffold rule-promoter plugin and add captured hook payload fixtures" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Engine core: paths, globs, validation, protected_path, banned_content

**Files:**
- Create: `plugins/rule-promoter/skills/rule-promoter/scripts/rule_hook.py`
- Test: `tests/test_rule_hook.py`

**Interfaces:**
- Produces (`rule_hook`): `RULE_TYPES`, `PATH_TOOLS`, `PATH_KEYS`, `TEXT_KEYS`, `RulesError`, `glob_to_regex(glob) -> re.Pattern` (cached), `glob_match(globs, rel) -> bool`, `relative_path(path_text, project) -> str`, `collect_paths(tool_input) -> list[str]`, `collect_text(tool_input) -> list[str]`, `validate_rules(data) -> list[str]`, `check_rule(rule, payload, project, simulate=False) -> str | None` (violation detail, or `None` to allow), `_NT` (True on Windows).
- Rule dict keys: `id`, `type`, `message`, `enabled`, `source`, `proof`, plus type fields (see spec).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rule_hook.py`:

```python
import contextlib
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import helpers

sys.path.insert(
    0,
    str(helpers.REPO_ROOT / "plugins" / "rule-promoter" / "skills" / "rule-promoter" / "scripts"),
)
import rule_hook  # noqa: E402

FIXTURES = helpers.REPO_ROOT / "tests" / "fixtures" / "rule_hook"


def pre(tool, **tool_input):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input}


def stop(**extra):
    return {"hook_event_name": "Stop", **extra}


def make_rule(rule_type, **fields):
    rule = {"id": "r1", "type": rule_type, "message": "not allowed",
            "proof": {"violation": {}, "pass": {}}}
    rule.update(fields)
    return rule


class RuleCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = os.path.realpath(self.tmp.name)
        env = mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": self.project})
        env.start()
        self.addCleanup(env.stop)

    def hit(self, rule, payload, **kw):
        return rule_hook.check_rule(rule, payload, self.project, **kw)

    def path(self, *parts):
        return os.path.join(self.project, *parts)


class GlobTests(unittest.TestCase):
    def setUp(self):
        rule_hook.glob_to_regex.cache_clear()
        self.addCleanup(rule_hook.glob_to_regex.cache_clear)

    def test_double_star_matches_any_depth(self):
        for rel in ("app/migrations/0001.py", "migrations/x.py", "a/b/migrations/c/d.py"):
            self.assertTrue(rule_hook.glob_match(["**/migrations/**"], rel), rel)
        for rel in ("app/migration/x.py", "app/migrations", "app/my_migrations/x.py"):
            self.assertFalse(rule_hook.glob_match(["**/migrations/**"], rel), rel)

    def test_single_star_stays_in_one_segment(self):
        self.assertTrue(rule_hook.glob_match(["*.env"], ".env"))
        self.assertTrue(rule_hook.glob_match(["*.env"], "prod.env"))
        self.assertFalse(rule_hook.glob_match(["*.env"], "dir/.env"))
        self.assertTrue(rule_hook.glob_match(["**/.env"], "dir/.env"))
        self.assertTrue(rule_hook.glob_match(["**/.env"], ".env"))

    def test_mixed_patterns(self):
        self.assertTrue(rule_hook.glob_match(["src/**/*.py"], "src/a.py"))
        self.assertTrue(rule_hook.glob_match(["src/**/*.py"], "src/x/y/a.py"))
        self.assertFalse(rule_hook.glob_match(["src/**/*.py"], "lib/a.py"))
        self.assertTrue(rule_hook.glob_match(["docs/?.md"], "docs/a.md"))
        self.assertFalse(rule_hook.glob_match(["docs/?.md"], "docs/ab.md"))

    def test_globs_are_case_insensitive_on_windows(self):
        with mock.patch.object(rule_hook, "_NT", True):
            rule_hook.glob_to_regex.cache_clear()
            self.assertTrue(rule_hook.glob_match(["**/migrations/**"], "App/Migrations/x.py"))
        with mock.patch.object(rule_hook, "_NT", False):
            rule_hook.glob_to_regex.cache_clear()
            self.assertFalse(rule_hook.glob_match(["**/migrations/**"], "App/Migrations/x.py"))

    def test_backslashes_in_globs_are_normalised(self):
        self.assertTrue(rule_hook.glob_match(["app\\migrations\\**"], "app/migrations/x.py"))


class RelativePathTests(RuleCase):
    def test_absolute_inside_project(self):
        self.assertEqual(rule_hook.relative_path(self.path("app", "models.py"), self.project), "app/models.py")

    def test_relative_stays_relative(self):
        self.assertEqual(rule_hook.relative_path("app/models.py", self.project), "app/models.py")
        self.assertEqual(rule_hook.relative_path("./app/../app/models.py", self.project), "app/models.py")

    def test_backslash_separators_are_normalised(self):
        self.assertEqual(
            rule_hook.relative_path(os.path.join("app", "models.py"), self.project), "app/models.py"
        )

    def test_project_itself(self):
        self.assertEqual(rule_hook.relative_path(self.project, self.project), ".")

    def test_outside_project_uses_the_absolute_path(self):
        outside = os.path.join(os.path.dirname(self.project), "elsewhere", ".env")
        rel = rule_hook.relative_path(outside, self.project)
        self.assertFalse(rel.startswith(".."))
        self.assertTrue(rel.endswith("elsewhere/.env"))
        self.assertTrue(rule_hook.glob_match(["**/.env"], rel))


class CollectTests(unittest.TestCase):
    def test_paths(self):
        self.assertEqual(rule_hook.collect_paths({"file_path": "a.py", "content": "x"}), ["a.py"])
        self.assertEqual(rule_hook.collect_paths({"notebook_path": "n.ipynb"}), ["n.ipynb"])
        self.assertEqual(
            rule_hook.collect_paths({"edits": [{"file_path": "a.py"}, {"file_path": "b.py"}]}),
            ["a.py", "b.py"],
        )
        self.assertEqual(rule_hook.collect_paths({}), [])
        self.assertEqual(rule_hook.collect_paths({"file_path": 5}), [])

    def test_text_collects_only_new_text(self):
        got = rule_hook.collect_text({"file_path": "a", "content": "C", "old_string": "OLD", "new_string": "NEW"})
        self.assertEqual(sorted(got), ["C", "NEW"])
        nested = {"edits": [{"old_string": "x", "new_string": "N1"}, {"new_string": "N2"}]}
        self.assertEqual(rule_hook.collect_text(nested), ["N1", "N2"])
        self.assertEqual(rule_hook.collect_text({"new_source": ["line1", "line2"]}), ["line1", "line2"])
        self.assertEqual(rule_hook.collect_text({"file_content": "F"}), ["F"])
        self.assertEqual(rule_hook.collect_text({"content": 5}), [])


class ValidateTests(unittest.TestCase):
    def good(self, **fields):
        rule = make_rule("protected_path", globs=["**/x/**"])
        rule["proof"] = {"violation": {"a": 1}, "pass": {"b": 2}}
        rule.update(fields)
        return {"version": 1, "rules": [rule]}

    def test_valid(self):
        self.assertEqual(rule_hook.validate_rules(self.good()), [])

    def test_errors(self):
        cases = {
            "bad version": ({"version": 2, "rules": []}, "version"),
            "rules not a list": ({"version": 1, "rules": {}}, "list"),
            "bad id": (self.good(id="Bad Id"), "kebab-case"),
            "unknown type": (self.good(type="mystery"), "type must be one of"),
            "no message": (self.good(message=""), "message is required"),
            "no proof": (self.good(proof={}), "proof needs"),
            "empty globs": (self.good(globs=[]), "globs must not be empty"),
            "globs not strings": (self.good(globs=[1]), "globs must be a list of non-empty strings"),
            "missing globs": (self.good(globs=None), "globs"),
        }
        for name, (data, fragment) in cases.items():
            with self.subTest(name):
                if name == "missing globs":
                    data["rules"][0].pop("globs")
                errors = rule_hook.validate_rules(data)
                self.assertTrue(any(fragment in e for e in errors), (name, errors))

    def test_duplicate_ids(self):
        data = self.good()
        data["rules"].append(dict(data["rules"][0]))
        self.assertTrue(any("duplicate id" in e for e in rule_hook.validate_rules(data)))

    def test_regex_and_stop_check_fields(self):
        bad_regex = {"version": 1, "rules": [make_rule("blocked_command", patterns=["["],
                     proof={"violation": {"a": 1}, "pass": {"b": 2}})]}
        self.assertTrue(any("invalid regular expression" in e for e in rule_hook.validate_rules(bad_regex)))
        stop_rule = make_rule("stop_check", proof={"violation": {"a": 1}, "pass": {"b": 2}})
        self.assertTrue(any("command is required" in e for e in rule_hook.validate_rules({"version": 1, "rules": [stop_rule]})))
        stop_rule.update(command="true", timeout_seconds=-1)
        self.assertTrue(any("timeout_seconds" in e for e in rule_hook.validate_rules({"version": 1, "rules": [stop_rule]})))

    def test_disabled_rules_need_no_proof(self):
        data = self.good(enabled=False, proof={})
        self.assertEqual(rule_hook.validate_rules(data), [])


class ProtectedPathTests(RuleCase):
    def rule(self, **fields):
        return make_rule("protected_path", globs=["**/migrations/**"], **fields)

    def test_blocks_edit_and_write_by_absolute_and_relative_path(self):
        for tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            for p in (self.path("app", "migrations", "0001.py"), "app/migrations/0001.py"):
                with self.subTest(tool=tool, path=p):
                    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
                    self.assertIn("migrations", self.hit(self.rule(), pre(tool, **{key: p})))

    def test_multiedit_nested_paths(self):
        payload = pre("MultiEdit", edits=[{"file_path": "app/models.py"}, {"file_path": "app/migrations/1.py"}])
        self.assertIsNotNone(self.hit(self.rule(), payload))

    def test_allows_other_files_and_tools(self):
        self.assertIsNone(self.hit(self.rule(), pre("Edit", file_path="app/models.py")))
        self.assertIsNone(self.hit(self.rule(), pre("Bash", command="cat app/migrations/1.py")))
        self.assertIsNone(self.hit(self.rule(), pre("Read", file_path="app/migrations/1.py")))
        self.assertIsNone(self.hit(self.rule(), stop()))

    def test_allow_globs_carve_out_exceptions(self):
        rule = self.rule(allow_globs=["**/migrations/__init__.py"])
        self.assertIsNone(self.hit(rule, pre("Edit", file_path="app/migrations/__init__.py")))
        self.assertIsNotNone(self.hit(rule, pre("Edit", file_path="app/migrations/0001.py")))

    def test_odd_payloads_are_allowed(self):
        rule = self.rule()
        for payload in (pre("Edit"), {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": "x"},
                        {"hook_event_name": "PreToolUse", "tool_name": "Edit"}, {}):
            with self.subTest(payload=payload):
                self.assertIsNone(self.hit(rule, payload))

    def test_outside_project_absolute_path(self):
        rule = make_rule("protected_path", globs=["**/.env"])
        outside = os.path.join(os.path.dirname(self.project), "other", ".env")
        self.assertIsNotNone(self.hit(rule, pre("Write", file_path=outside)))


class BannedContentTests(RuleCase):
    def rule(self, **fields):
        return make_rule("banned_content", patterns=[r"console\.log\("], **fields)

    def test_blocks_new_text(self):
        self.assertIsNotNone(self.hit(self.rule(), pre("Write", file_path="a.js", content="x\nconsole.log(1)\n")))
        self.assertIsNotNone(self.hit(self.rule(), pre("Edit", file_path="a.js", old_string="y", new_string="console.log(2)")))
        nested = pre("MultiEdit", edits=[{"file_path": "a.js", "old_string": "a", "new_string": "console.log(3)"}])
        self.assertIsNotNone(self.hit(self.rule(), nested))

    def test_old_text_is_ignored(self):
        payload = pre("Edit", file_path="a.js", old_string="console.log(1)", new_string="logger.info(1)")
        self.assertIsNone(self.hit(self.rule(), payload))

    def test_globs_restrict_which_files_are_covered(self):
        rule = self.rule(globs=["src/**/*.js"])
        self.assertIsNotNone(self.hit(rule, pre("Write", file_path="src/a.js", content="console.log(1)")))
        self.assertIsNone(self.hit(rule, pre("Write", file_path="tests/a.js", content="console.log(1)")))
        self.assertIsNone(self.hit(rule, pre("Write", content="console.log(1)")))  # no path: not covered

    def test_no_globs_covers_every_file(self):
        self.assertIsNotNone(self.hit(self.rule(), pre("Write", file_path="anything.txt", content="console.log(1)")))

    def test_bash_is_not_inspected(self):
        self.assertIsNone(self.hit(self.rule(), pre("Bash", command="echo 'console.log(1)'")))


class RealPayloadTests(RuleCase):
    """The fixtures are real payloads captured from Claude Code (see Task 1)."""

    def load(self, name):
        text = (FIXTURES / name).read_text(encoding="utf-8").replace(
            "{PROJECT}", self.project.replace("\\", "\\\\")
        )
        return json.loads(text)

    def test_write_fixture(self):
        payload = self.load("PreToolUse-Write.json")
        paths = rule_hook.collect_paths(payload["tool_input"])
        self.assertEqual([rule_hook.relative_path(p, self.project) for p in paths], ["notes.txt"])
        self.assertTrue(any("hello capture" in t for t in rule_hook.collect_text(payload["tool_input"])))
        rule = make_rule("protected_path", globs=["notes.txt"])
        self.assertIsNotNone(self.hit(rule, payload))
        self.assertIsNone(self.hit(make_rule("protected_path", globs=["other.txt"]), payload))

    def test_edit_fixture(self):
        payload = self.load("PreToolUse-Edit.json")
        self.assertEqual(
            [rule_hook.relative_path(p, self.project) for p in rule_hook.collect_paths(payload["tool_input"])],
            ["notes.txt"],
        )
        self.assertTrue(any("hello edited" in t for t in rule_hook.collect_text(payload["tool_input"])))
        banned = make_rule("banned_content", patterns=["hello edited"])
        self.assertIsNotNone(self.hit(banned, payload))

    def test_bash_fixture_has_a_command_string(self):
        payload = self.load("PreToolUse-Bash.json")
        self.assertEqual(payload["tool_input"]["command"], "echo done")
        self.assertEqual(payload["hook_event_name"], "PreToolUse")

    def test_stop_fixture(self):
        payload = self.load("Stop.json")
        self.assertEqual(payload["hook_event_name"], "Stop")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_rule_hook.py" 2>&1 | tail -4`
Expected: ERROR `ModuleNotFoundError: No module named 'rule_hook'`.

- [ ] **Step 3: Write the implementation**

Create `plugins/rule-promoter/skills/rule-promoter/scripts/rule_hook.py`:

```python
#!/usr/bin/env python3
"""rule_hook: enforce typed rules from .claude/rules.json as Claude Code hooks.

    python rule_hook.py check                   # hook entry point (hook payload on stdin)
    python rule_hook.py selftest [--rules PATH] # prove every rule blocks its violation and allows its pass

Standard library only. Hooks are guardrails, not a security boundary.
"""
import functools
import json
import os
import re
import subprocess
import sys
from pathlib import Path

RULE_TYPES = ("protected_path", "blocked_command", "banned_content", "stop_check")
PATH_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
PATH_KEYS = ("file_path", "notebook_path")
TEXT_KEYS = ("content", "file_content", "new_string", "new_content", "new_source")
_ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_NT = os.name == "nt"


class RulesError(Exception):
    """The rules file is missing or invalid."""


# --- paths and globs -----------------------------------------------------------------------

@functools.lru_cache(maxsize=512)
def glob_to_regex(glob):
    g = glob.replace("\\", "/")
    out, i = [], 0
    while i < len(g):
        if g.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif g.startswith("**", i):
            out.append(".*")
            i += 2
        elif g[i] == "*":
            out.append("[^/]*")
            i += 1
        elif g[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(g[i]))
            i += 1
    return re.compile("^" + "".join(out) + "$", re.IGNORECASE if _NT else 0)


def glob_match(globs, rel):
    return any(glob_to_regex(g).match(rel) for g in globs)


def relative_path(path_text, project):
    """Project-relative path with forward slashes; the absolute path when outside the project."""
    full = os.path.normpath(os.path.join(project, path_text))
    try:
        rel = os.path.relpath(full, project)
    except ValueError:  # a different drive on Windows
        rel = full
    rel = rel.replace("\\", "/")
    if rel == ".." or rel.startswith("../"):
        rel = full.replace("\\", "/")
    return rel


def _collect(obj, keys):
    found = []

    def visit(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in keys and isinstance(value, str):
                    found.append(value)
                elif key in keys and isinstance(value, list):
                    found.extend(v for v in value if isinstance(v, str))
                else:
                    visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(obj)
    return found


def collect_paths(tool_input):
    return _collect(tool_input, PATH_KEYS)


def collect_text(tool_input):
    """Only the new text being written (never old_string or what is on disk)."""
    return _collect(tool_input, TEXT_KEYS)


# --- validation ----------------------------------------------------------------------------

def _str_list(rule, key, required):
    value = rule.get(key)
    if value is None:
        return "is required" if required else None
    if not (isinstance(value, list) and all(isinstance(v, str) and v for v in value)):
        return "must be a list of non-empty strings"
    if required and not value:
        return "must not be empty"
    return None


_FIELDS = {
    "protected_path": (("globs", True), ("allow_globs", False)),
    "blocked_command": (("patterns", True), ("except_patterns", False)),
    "banned_content": (("patterns", True), ("globs", False)),
    "stop_check": (("when_changed_globs", False),),
}


def _validate_fields(label, rule, kind):
    errors = []
    for key, required in _FIELDS[kind]:
        problem = _str_list(rule, key, required)
        if problem:
            errors.append(f"{label}: {key} {problem}")
    if not errors:
        for key in ("patterns", "except_patterns"):
            for pattern in rule.get(key) or []:
                try:
                    re.compile(pattern)
                except re.error as exc:
                    errors.append(f"{label}: {key} has an invalid regular expression {pattern!r} ({exc})")
    if kind == "stop_check":
        if not (isinstance(rule.get("command"), str) and rule["command"].strip()):
            errors.append(f"{label}: command is required")
        timeout = rule.get("timeout_seconds")
        if timeout is not None and not (
            isinstance(timeout, (int, float)) and not isinstance(timeout, bool) and timeout > 0
        ):
            errors.append(f"{label}: timeout_seconds must be a positive number")
    return errors


def validate_rules(data):
    if not isinstance(data, dict) or data.get("version") != 1:
        return ['rules.json must be an object with "version": 1']
    rules = data.get("rules")
    if not isinstance(rules, list):
        return ['"rules" must be a list']
    errors, seen = [], set()
    for number, rule in enumerate(rules, 1):
        label = f"rule {number}"
        if not isinstance(rule, dict):
            errors.append(f"{label}: must be an object")
            continue
        rule_id = rule.get("id")
        if isinstance(rule_id, str):
            label = f"rule {rule_id!r}"
        if not (isinstance(rule_id, str) and _ID.match(rule_id)):
            errors.append(f"{label}: id must be kebab-case")
        elif rule_id in seen:
            errors.append(f"{label}: duplicate id")
        else:
            seen.add(rule_id)
        kind = rule.get("type")
        if kind not in RULE_TYPES:
            errors.append(f"{label}: type must be one of {', '.join(RULE_TYPES)}")
            continue
        if not (isinstance(rule.get("message"), str) and rule["message"].strip()):
            errors.append(f"{label}: message is required")
        errors += _validate_fields(label, rule, kind)
        if rule.get("enabled", True):
            proof = rule.get("proof")
            if not (isinstance(proof, dict) and isinstance(proof.get("violation"), dict)
                    and isinstance(proof.get("pass"), dict)):
                errors.append(f"{label}: proof needs a violation and a pass payload")
    return errors


# --- rule checks ---------------------------------------------------------------------------

def _matches_any(patterns, text):
    return any(re.search(p, text) for p in patterns)


def check_rule(rule, payload, project, simulate=False):
    """Return a short violation detail, or None when the payload is allowed."""
    event = payload.get("hook_event_name")
    kind = rule["type"]
    if kind == "stop_check":
        return _stop_check(rule, payload, project, simulate) if event == "Stop" else None
    if event != "PreToolUse":
        return None
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    if kind == "blocked_command":
        return _blocked_command(rule, tool, tool_input)
    if tool not in PATH_TOOLS:
        return None
    paths = [relative_path(p, project) for p in collect_paths(tool_input)]
    if kind == "protected_path":
        for rel in paths:
            if glob_match(rule["globs"], rel) and not glob_match(rule.get("allow_globs", []), rel):
                return f"path: {rel}"
        return None
    if kind == "banned_content":
        globs = rule.get("globs")
        if globs and not any(glob_match(globs, rel) for rel in paths):
            return None
        for text in collect_text(tool_input):
            if _matches_any(rule["patterns"], text):
                return "the new text matches a banned pattern"
    return None


def _blocked_command(rule, tool, tool_input):
    return None  # implemented in Task 3


def _stop_check(rule, payload, project, simulate):
    return None  # implemented in Task 4
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v 2>&1 | tail -4`
Expected: `OK`; the existing repo tests plus every test in `test_rule_hook.py` pass. If `test_edit_fixture` fails because the captured Edit payload uses different text key names, add the actual key to `TEXT_KEYS` (and note the ruling in the ledger) before continuing.

- [ ] **Step 5: Commit**

```bash
python scripts/validate.py
git add plugins/rule-promoter tests/test_rule_hook.py
git commit -m "feat: add rule-promoter engine core (paths, globs, validation, path and content rules)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: blocked_command

**Files:**
- Modify: `plugins/rule-promoter/skills/rule-promoter/scripts/rule_hook.py`
- Test: `tests/test_rule_hook.py`

**Interfaces:**
- Consumes: `_matches_any`, `check_rule` (Task 2).
- Produces: `split_segments(command) -> list[str]`; a real `_blocked_command(rule, tool, tool_input)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rule_hook.py` (before the `if __name__` block):

```python
class SplitSegmentsTests(unittest.TestCase):
    def test_splits_on_operators(self):
        self.assertEqual(rule_hook.split_segments("a && b || c; d | e & f\ng"), ["a", "b", "c", "d", "e", "f", "g"])

    def test_quoted_operators_do_not_split(self):
        self.assertEqual(rule_hook.split_segments('echo "a && b" && ls'), ['echo "a && b"', "ls"])
        self.assertEqual(rule_hook.split_segments("echo 'x; y'"), ["echo 'x; y'"])
        self.assertEqual(rule_hook.split_segments('echo "say \\"hi; there\\""'), ['echo "say \\"hi; there\\""'])

    def test_escaped_operator_does_not_split(self):
        self.assertEqual(rule_hook.split_segments("echo a\\;b"), ["echo a\\;b"])

    def test_blank_and_whitespace(self):
        self.assertEqual(rule_hook.split_segments("  "), [])
        self.assertEqual(rule_hook.split_segments(" a ;; b "), ["a", "b"])


class BlockedCommandTests(RuleCase):
    FORCE = r"\bgit\s+push\b.*(?:--force\b|\s-f\b)"

    def rule(self, **fields):
        return make_rule("blocked_command", patterns=[self.FORCE],
                         except_patterns=["--force-with-lease"], **fields)

    def test_blocks_force_push_variants(self):
        for command in ("git push --force origin main", "git push -f", "git push origin main --force"):
            with self.subTest(command=command):
                self.assertIsNotNone(self.hit(self.rule(), pre("Bash", command=command)))

    def test_compound_command_is_caught(self):
        self.assertIn("git push -f", self.hit(self.rule(), pre("Bash", command="cd app && git push -f")))
        self.assertIsNotNone(self.hit(self.rule(), pre("Bash", command="make test; git push --force")))

    def test_quoted_operators_do_not_split(self):
        command = 'echo "a && git push --force"'
        self.assertEqual(len(rule_hook.split_segments(command)), 1)
        # documented over-block: the pattern is searched inside the quoted segment
        self.assertIsNotNone(self.hit(self.rule(), pre("Bash", command=command)))
        self.assertIsNotNone(self.hit(self.rule(), pre("Bash", command='bash -c "git push --force"')))

    def test_except_patterns_allow(self):
        self.assertIsNone(self.hit(self.rule(), pre("Bash", command="git push --force-with-lease")))

    def test_safe_commands_pass(self):
        for command in ("git status", "git push origin feature", "echo done", "git pull --force-with-lease"):
            with self.subTest(command=command):
                self.assertIsNone(self.hit(self.rule(), pre("Bash", command=command)))

    def test_push_to_main_rule(self):
        rule = make_rule("blocked_command", patterns=[r"\bgit\s+push\b.*\b(?:main|master)\b"])
        self.assertIsNotNone(self.hit(rule, pre("Bash", command="git push origin main")))
        # documented false positive: the word-boundary pattern also matches a branch named main-menu
        self.assertIsNotNone(self.hit(rule, pre("Bash", command="git push origin feature/main-menu")))
        self.assertIsNone(self.hit(rule, pre("Bash", command="git push origin feature")))

    def test_only_bash_and_only_strings(self):
        self.assertIsNone(self.hit(self.rule(), pre("Edit", file_path="a", new_string="git push --force")))
        self.assertIsNone(self.hit(self.rule(), pre("Bash", command=["git", "push", "--force"])))
        self.assertIsNone(self.hit(self.rule(), pre("Bash")))
        self.assertIsNone(self.hit(self.rule(), stop()))
```

Note on `test_push_to_main_rule`: it pins the documented false positive (the word-boundary pattern also matches a branch named `main-menu`); the skill must state this risk and add an `except_patterns` entry when it matters.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_rule_hook.py" 2>&1 | grep -E "AttributeError|^Ran|^FAILED" | sort | uniq -c`
Expected: failures (`split_segments` missing, blocked_command stub returns None).

- [ ] **Step 3: Implement**

In `rule_hook.py`, replace the stub `_blocked_command` with:

```python
def split_segments(command):
    """Split a shell command into segments on &&, ||, ;, |, & and newlines (quotes respected)."""
    segments, buf, quote, i = [], [], None, 0
    while i < len(command):
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and quote == '"' and i + 1 < len(command):
                buf.append(command[i + 1])
                i += 1
            elif ch == quote:
                quote = None
        elif ch == "\\" and i + 1 < len(command):
            buf.append(ch)
            buf.append(command[i + 1])
            i += 1
        elif ch in "\"'":
            quote = ch
            buf.append(ch)
        elif command.startswith(("&&", "||"), i):
            segments.append("".join(buf))
            buf = []
            i += 1
        elif ch in ";|&\n":
            segments.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
        i += 1
    segments.append("".join(buf))
    return [s.strip() for s in segments if s.strip()]


def _blocked_command(rule, tool, tool_input):
    if tool != "Bash":
        return None
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    for segment in split_segments(command):
        if _matches_any(rule["patterns"], segment) and not _matches_any(rule.get("except_patterns", []), segment):
            return f"command: {segment}"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v 2>&1 | tail -4`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
python scripts/validate.py
git add plugins/rule-promoter tests/test_rule_hook.py
git commit -m "feat: add blocked_command rule type to the rule-promoter engine" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: stop_check

**Files:**
- Modify: `plugins/rule-promoter/skills/rule-promoter/scripts/rule_hook.py`
- Test: `tests/test_rule_hook.py`

**Interfaces:**
- Consumes: `check_rule`, `glob_match`.
- Produces: a real `_stop_check(rule, payload, project, simulate)` and `_changed_paths(project) -> list[str] | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rule_hook.py`:

```python
import shutil
import subprocess


def py(code):
    return f'"{sys.executable}" -c "{code}"'


class StopCheckTests(RuleCase):
    def rule(self, command, **fields):
        return make_rule("stop_check", command=command, **fields)

    def test_failing_command_blocks_with_output_tail(self):
        detail = self.hit(self.rule(py("print('boom here'); import sys; sys.exit(3)")), stop())
        self.assertIn("exited 3", detail)
        self.assertIn("boom here", detail)

    def test_passing_command_allows(self):
        self.assertIsNone(self.hit(self.rule(py("pass")), stop()))

    def test_stop_hook_active_always_allows(self):
        self.assertIsNone(self.hit(self.rule(py("import sys; sys.exit(1)")), stop(stop_hook_active=True)))

    def test_only_the_stop_event(self):
        self.assertIsNone(self.hit(self.rule(py("import sys; sys.exit(1)")), pre("Bash", command="ls")))

    def test_timeout_allows_and_warns(self):
        err = io.StringIO()
        rule = self.rule(py("import time; time.sleep(5)"), timeout_seconds=0.3)
        with contextlib.redirect_stderr(err):
            self.assertIsNone(self.hit(rule, stop()))
        self.assertIn("timed out", err.getvalue())

    def test_huge_output_is_trimmed_to_the_last_lines(self):
        rule = self.rule(py("[print('line', i) for i in range(1, 201)]; import sys; sys.exit(1)"))
        detail = self.hit(rule, stop())
        self.assertIn("line 200", detail)
        self.assertNotIn("line 100\n", detail)
        self.assertLessEqual(len(detail), 2300)

    def test_command_runs_in_the_project_directory(self):
        Path(self.project, "marker.txt").write_text("x")
        self.assertIsNone(self.hit(self.rule(py("import os, sys; sys.exit(0 if os.path.exists('marker.txt') else 1)")), stop()))

    def test_simulate_exit_only_when_simulating(self):
        rule = self.rule(py("pass"))
        self.assertIsNotNone(self.hit(rule, stop(simulate_exit=1), simulate=True))
        self.assertIsNone(self.hit(rule, stop(simulate_exit=0), simulate=True))
        # a real check ignores simulate_exit and runs the command
        self.assertIsNone(self.hit(rule, stop(simulate_exit=1)))

    @unittest.skipUnless(shutil.which("git"), "git not available")
    def test_when_changed_globs(self):
        subprocess.run(["git", "init", "-q"], cwd=self.project, check=True)
        failing = py("import sys; sys.exit(1)")
        rule = self.rule(failing, when_changed_globs=["src/**"])
        self.assertIsNone(self.hit(rule, stop()))  # clean tree: nothing changed
        Path(self.project, "README.md").write_text("x")
        self.assertIsNone(self.hit(rule, stop()))  # changed, but outside the globs
        Path(self.project, "src").mkdir()
        Path(self.project, "src", "a.py").write_text("x")
        self.assertIsNotNone(self.hit(rule, stop()))  # changed inside the globs

    def test_not_a_git_repo_always_runs(self):
        rule = self.rule(py("import sys; sys.exit(1)"), when_changed_globs=["src/**"])
        with mock.patch.object(rule_hook, "_changed_paths", return_value=None):
            self.assertIsNotNone(self.hit(rule, stop()))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_rule_hook.py" 2>&1 | grep -E "^Ran|^FAILED|AttributeError" | sort | uniq -c`
Expected: failures (stub returns None; `_changed_paths` missing).

- [ ] **Step 3: Implement**

In `rule_hook.py`, replace the stub `_stop_check` with:

```python
def _changed_paths(project):
    """Changed paths from `git status --porcelain`, or None when git cannot tell."""
    try:
        done = subprocess.run(
            ["git", "status", "--porcelain", "-uall"], cwd=project, capture_output=True,
            encoding="utf-8", errors="replace", timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    paths = []
    for line in done.stdout.splitlines():
        entry = line[3:]
        if " -> " in entry:
            entry = entry.split(" -> ")[-1]
        paths.append(entry.strip().strip('"').replace("\\", "/"))
    return paths


def _stop_check(rule, payload, project, simulate):
    if payload.get("stop_hook_active"):
        return None
    if simulate and "simulate_exit" in payload:
        return "the check failed (simulated)" if payload["simulate_exit"] else None
    globs = rule.get("when_changed_globs")
    if globs:
        changed = _changed_paths(project)
        if changed is not None and not any(glob_match(globs, p) for p in changed):
            return None
    command = rule["command"]
    try:
        done = subprocess.run(
            command, shell=True, cwd=project, capture_output=True, encoding="utf-8",
            errors="replace", timeout=rule.get("timeout_seconds", 120),
        )
    except subprocess.TimeoutExpired:
        print(f"[rule_hook] stop check {rule['id']} timed out; allowing the stop", file=sys.stderr)
        return None
    if done.returncode == 0:
        return None
    tail = "\n".join((done.stdout + done.stderr).splitlines()[-20:])[-2000:]
    return f"`{command}` exited {done.returncode}:\n{tail}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v 2>&1 | tail -4`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
python scripts/validate.py
git add plugins/rule-promoter tests/test_rule_hook.py
git commit -m "feat: add stop_check rule type to the rule-promoter engine" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 5: check and selftest commands, decisions, fail-open

**Files:**
- Modify: `plugins/rule-promoter/skills/rule-promoter/scripts/rule_hook.py`
- Test: `tests/test_rule_hook.py`

**Interfaces:**
- Consumes: everything from Tasks 2-4.
- Produces: `project_dir(payload) -> str`, `load_rules(path) -> list[dict]` (raises `RulesError`), `evaluate(payload, rules, project, simulate=False) -> (rule, detail) | None`, `decision(payload, rule, detail) -> dict`, `run_check(stream) -> int`, `run_selftest(rules_path=None) -> int`, `main(argv=None) -> int`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rule_hook.py`:

```python
class MainCase(RuleCase):
    def write_rules(self, rules):
        path = Path(self.project, ".claude", "rules.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"version": 1, "rules": rules}), encoding="utf-8")
        return path

    def run_main(self, argv, stdin_text=""):
        out, err = io.StringIO(), io.StringIO()
        fake_stdin = types.SimpleNamespace(buffer=io.BytesIO(stdin_text.encode("utf-8")))
        with mock.patch("sys.stdin", fake_stdin), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rule_hook.main(argv)
        return code, out.getvalue(), err.getvalue()

    def migration_rule(self, **fields):
        rule = make_rule(
            "protected_path", id="no-migration-edits", source="CLAUDE.md:14",
            message="Create a new migration instead.", globs=["**/migrations/**"],
            proof={"violation": pre("Edit", file_path="app/migrations/0001.py"),
                   "pass": pre("Edit", file_path="app/models.py")},
        )
        rule.update(fields)
        return rule


class CheckTests(MainCase):
    def test_allow_prints_nothing(self):
        self.write_rules([self.migration_rule()])
        code, out, err = self.run_main(["check"], json.dumps(pre("Edit", file_path="app/models.py")))
        self.assertEqual((code, out, err), (0, "", ""))

    def test_pretool_violation_denies_with_the_rule_reason(self):
        self.write_rules([self.migration_rule()])
        code, out, _ = self.run_main(["check"], json.dumps(pre("Write", file_path="app/migrations/9.py", content="x")))
        self.assertEqual(code, 0)
        body = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(body["hookEventName"], "PreToolUse")
        self.assertEqual(body["permissionDecision"], "deny")
        self.assertEqual(
            body["permissionDecisionReason"],
            "Rule no-migration-edits: Create a new migration instead. (from CLAUDE.md:14)",
        )

    def test_stop_violation_blocks(self):
        rule = make_rule("stop_check", id="tests-pass", message="Fix the tests first.",
                         command=py("import sys; sys.exit(1)"),
                         proof={"violation": stop(simulate_exit=1), "pass": stop(simulate_exit=0)})
        self.write_rules([rule])
        code, out, _ = self.run_main(["check"], json.dumps(stop()))
        body = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(body["decision"], "block")
        self.assertIn("Rule tests-pass: Fix the tests first.", body["reason"])
        # the loop guard
        self.assertEqual(self.run_main(["check"], json.dumps(stop(stop_hook_active=True)))[1], "")

    def test_first_violated_rule_wins_and_disabled_rules_are_ignored(self):
        second = self.migration_rule(id="second-rule", message="second")
        disabled = self.migration_rule(id="disabled-rule", message="disabled", enabled=False)
        self.write_rules([disabled, self.migration_rule(), second])
        _, out, _ = self.run_main(["check"], json.dumps(pre("Edit", file_path="app/migrations/1.py")))
        self.assertIn("no-migration-edits", out)
        self.assertNotIn("second-rule", out)
        self.assertNotIn("disabled-rule", out)

    def test_unknown_tools_and_events_are_allowed_silently(self):
        self.write_rules([self.migration_rule()])
        for payload in (pre("Read", file_path="app/migrations/1.py"), {"hook_event_name": "SessionStart"}):
            self.assertEqual(self.run_main(["check"], json.dumps(payload))[:2], (0, ""))

    def test_fail_open_on_bad_input_or_rules(self):
        self.write_rules([self.migration_rule()])
        for bad in ("not json", "[1, 2]", ""):
            with self.subTest(stdin=bad):
                code, out, err = self.run_main(["check"], bad)
                self.assertEqual((code, out), (1, ""))
                self.assertTrue(err.startswith("[rule_hook]"), err)
        Path(self.project, ".claude", "rules.json").write_text("{broken", encoding="utf-8")
        code, out, err = self.run_main(["check"], json.dumps(pre("Edit", file_path="a")))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("[rule_hook]", err)

    def test_missing_rules_file_warns_and_allows(self):
        code, out, err = self.run_main(["check"], json.dumps(pre("Edit", file_path="a")))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("rules.json", err)

    def test_invalid_rules_are_a_warning_not_a_block(self):
        self.write_rules([make_rule("protected_path", globs=[])])
        code, out, err = self.run_main(["check"], json.dumps(pre("Edit", file_path="a")))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("globs", err)

    def test_real_captured_write_payload_is_denied(self):
        rule = self.migration_rule(id="no-notes", globs=["notes.txt"], source="CLAUDE.md:3", message="Not notes.txt")
        self.write_rules([rule])
        text = (FIXTURES / "PreToolUse-Write.json").read_text(encoding="utf-8").replace(
            "{PROJECT}", self.project.replace("\\", "\\\\"))
        code, out, _ = self.run_main(["check"], text)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")


class SelftestTests(MainCase):
    def test_all_proofs_pass(self):
        self.write_rules([self.migration_rule()])
        code, out, _ = self.run_main(["selftest"])
        self.assertEqual(code, 0)
        self.assertIn("PASS  no-migration-edits", out)

    def test_a_failing_proof_fails_the_selftest(self):
        wrong = self.migration_rule(proof={"violation": pre("Edit", file_path="app/models.py"),
                                           "pass": pre("Edit", file_path="app/models.py")})
        self.write_rules([wrong])
        code, out, _ = self.run_main(["selftest"])
        self.assertEqual(code, 1)
        self.assertIn("FAIL  no-migration-edits", out)
        self.assertIn("NOT blocked", out)

    def test_a_pass_payload_that_blocks_also_fails(self):
        wrong = self.migration_rule(proof={"violation": pre("Edit", file_path="app/migrations/1.py"),
                                           "pass": pre("Edit", file_path="app/migrations/2.py")})
        self.write_rules([wrong])
        code, out, _ = self.run_main(["selftest"])
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED", out)

    def test_disabled_rules_are_skipped(self):
        self.write_rules([self.migration_rule(enabled=False, proof={})])
        code, out, _ = self.run_main(["selftest"])
        self.assertEqual(code, 0)
        self.assertIn("SKIP  no-migration-edits", out)

    def test_invalid_rules_list_every_error(self):
        self.write_rules([make_rule("protected_path", globs=[]), make_rule("mystery", id="other")])
        code, out, _ = self.run_main(["selftest"])
        self.assertEqual(code, 1)
        self.assertIn("globs", out)
        self.assertIn("type must be one of", out)

    def test_rules_path_override_and_missing_file(self):
        other = Path(self.project, "elsewhere.json")
        other.write_text(json.dumps({"version": 1, "rules": [self.migration_rule()]}), encoding="utf-8")
        self.assertEqual(self.run_main(["selftest", "--rules", str(other)])[0], 0)
        code, out, _ = self.run_main(["selftest", "--rules", str(Path(self.project, "nope.json"))])
        self.assertEqual(code, 1)
        self.assertIn("not found", out)

    def test_stop_check_proof_uses_simulate_exit(self):
        rule = make_rule("stop_check", id="tests-pass", message="Fix tests.", command="exit 99",
                         proof={"violation": stop(simulate_exit=1), "pass": stop(simulate_exit=0)})
        self.write_rules([rule])
        self.assertEqual(self.run_main(["selftest"])[0], 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_rule_hook.py" 2>&1 | grep -E "AttributeError|^Ran|^FAILED" | sort | uniq -c`
Expected: failures (`main`, `evaluate` and the rest are missing).

- [ ] **Step 3: Implement**

Append to `rule_hook.py`:

```python
# --- evaluation, output, CLI ---------------------------------------------------------------

def project_dir(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def load_rules(path):
    path = Path(path)
    if not path.is_file():
        raise RulesError(f"rules file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise RulesError(f"{path} is not valid JSON ({exc})") from None
    errors = validate_rules(data)
    if errors:
        raise RulesError("; ".join(errors))
    return data["rules"]


def evaluate(payload, rules, project, simulate=False):
    """The first enabled rule that the payload violates, as (rule, detail), else None."""
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        detail = check_rule(rule, payload, project, simulate)
        if detail is not None:
            return rule, detail
    return None


def decision(payload, rule, detail):
    source = f" (from {rule['source']})" if rule.get("source") else ""
    reason = f"Rule {rule['id']}: {rule['message']}{source}"
    if payload.get("hook_event_name") == "Stop":
        return {"decision": "block", "reason": f"{reason}\n{detail}"}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def run_check(stream):
    raw = stream.read()
    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("the hook payload must be a JSON object")
    project = project_dir(payload)
    rules = load_rules(Path(project) / ".claude" / "rules.json")
    hit = evaluate(payload, rules, project)
    if hit:
        print(json.dumps(decision(payload, *hit)))
    return 0


def run_selftest(rules_path=None):
    project = project_dir({})
    path = Path(rules_path) if rules_path else Path(project) / ".claude" / "rules.json"
    try:
        rules = load_rules(path)
    except RulesError as exc:
        for problem in str(exc).split("; "):
            print(f"INVALID  {problem}")
        return 1
    failed = 0
    for rule in rules:
        if not rule.get("enabled", True):
            print(f"SKIP  {rule['id']} (disabled)")
            continue
        proof = rule["proof"]
        blocked = evaluate(proof["violation"], [rule], project, simulate=True)
        allowed = evaluate(proof["pass"], [rule], project, simulate=True) is None
        if blocked is not None and allowed:
            print(f"PASS  {rule['id']}")
        else:
            failed += 1
            print(
                f"FAIL  {rule['id']} (violation {'blocked' if blocked else 'NOT blocked'}, "
                f"pass {'allowed' if allowed else 'BLOCKED'})"
            )
    return 1 if failed else 0


def main(argv=None):
    import argparse

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="rule_hook.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="hook entry point (payload on stdin)")
    selftest = sub.add_parser("selftest", help="prove every rule blocks its violation and allows its pass")
    selftest.add_argument("--rules", help="path to rules.json (default: <project>/.claude/rules.json)")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "check":
            return run_check(sys.stdin.buffer)
        return run_selftest(args.rules)
    except Exception as exc:  # noqa: BLE001 - fail open: a broken engine must not block every tool call
        print(f"[rule_hook] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v 2>&1 | tail -4`
Expected: `OK`.

- [ ] **Step 5: Real-process smoke test**

```bash
SP="C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a/scratchpad"
mkdir -p "$SP/smoke/.claude" && cd "$SP/smoke"
cat > .claude/rules.json <<'EOF'
{"version": 1, "rules": [{"id": "no-env", "type": "protected_path", "globs": ["**/.env"], "message": "Do not edit .env",
 "source": "CLAUDE.md:1", "proof": {"violation": {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {"file_path": ".env"}},
 "pass": {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {"file_path": "app.py"}}}}]}
EOF
export CLAUDE_PROJECT_DIR="$SP/smoke"; R="C:/Users/naren/Documents/claude-skills/plugins/rule-promoter/skills/rule-promoter/scripts/rule_hook.py"
python "$R" selftest; echo "selftest exit=$?"
echo '{"hook_event_name":"PreToolUse","tool_name":"Write","tool_input":{"file_path":".env","content":"x"}}' | python "$R" check; echo "check exit=$?"
echo '{"hook_event_name":"PreToolUse","tool_name":"Write","tool_input":{"file_path":"app.py","content":"x"}}' | python "$R" check; echo "allow exit=$?"
unset CLAUDE_PROJECT_DIR; cd "C:/Users/naren/Documents/claude-skills"
```

Expected: `PASS  no-env` and `selftest exit=0`; the second command prints a JSON `deny` whose reason is `Rule no-env: Do not edit .env (from CLAUDE.md:1)` and `check exit=0`; the third prints nothing and `allow exit=0`.

- [ ] **Step 6: Commit**

```bash
python scripts/validate.py
git add plugins/rule-promoter tests/test_rule_hook.py
git commit -m "feat: add rule-promoter check and selftest commands with fail-open behavior" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: settings_merge.py (launcher picking and idempotent settings merge)

**Files:**
- Create: `plugins/rule-promoter/skills/rule-promoter/scripts/settings_merge.py`
- Test: `tests/test_settings_merge.py`

**Interfaces:**
- Produces (`settings_merge`): `MARKER = "rule_hook.py"`, `SCRIPT_ARG = "${CLAUDE_PROJECT_DIR}/.claude/hooks/rule_hook.py"`, `SettingsError`, `build_groups(launcher, pretool, stop) -> dict`, `merge(settings, groups) -> dict`, `load_settings(path) -> dict`, `render(data) -> str`, `plan(path, launcher, pretool, stop) -> str` (unified diff, or the no-change message), `apply(path, launcher, pretool, stop) -> bool` (True if the file changed), `find_launcher(script, rules=None) -> str | None`, `main(argv=None) -> int`.
- `launcher` is a list such as `["python3"]` or `["py", "-3"]`. CLI: `settings_merge.py launcher --script PATH [--rules PATH]`, `plan|apply --settings PATH --launcher "python3" [--pretool] [--stop]`. Exit codes: 0 ok, 1 no launcher found, 2 invalid settings or arguments.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_settings_merge.py`:

```python
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers

sys.path.insert(
    0,
    str(helpers.REPO_ROOT / "plugins" / "rule-promoter" / "skills" / "rule-promoter" / "scripts"),
)
import settings_merge as sm  # noqa: E402

OTHER_HOOK = {"matcher": "Bash", "hooks": [{"type": "command", "command": "other-tool", "timeout": 3}]}


class MergeTests(unittest.TestCase):
    def test_build_groups_shapes(self):
        groups = sm.build_groups(["python3"], pretool=True, stop=True)
        pre = groups["PreToolUse"][0]
        self.assertEqual(pre["matcher"], "Edit|Write|MultiEdit|NotebookEdit|Bash")
        self.assertEqual(pre["hooks"], [{
            "type": "command", "command": "python3",
            "args": ["${CLAUDE_PROJECT_DIR}/.claude/hooks/rule_hook.py", "check"], "timeout": 5}])
        stop = groups["Stop"][0]
        self.assertNotIn("matcher", stop)
        self.assertEqual(stop["hooks"][0]["timeout"], 300)
        self.assertEqual(sm.build_groups(["python3"], pretool=True, stop=False).keys(), {"PreToolUse"})
        self.assertEqual(sm.build_groups(["python3"], pretool=False, stop=True).keys(), {"Stop"})

    def test_launcher_with_arguments_is_split(self):
        hook = sm.build_groups(["py", "-3"], True, False)["PreToolUse"][0]["hooks"][0]
        self.assertEqual(hook["command"], "py")
        self.assertEqual(hook["args"][:2], ["-3", "${CLAUDE_PROJECT_DIR}/.claude/hooks/rule_hook.py"])

    def test_merge_preserves_everything_else(self):
        settings = {"permissions": {"allow": ["Bash(ls)"]}, "hooks": {"PreToolUse": [OTHER_HOOK],
                    "Notification": [{"hooks": [{"type": "command", "command": "notify"}]}]}}
        merged = sm.merge(settings, sm.build_groups(["python3"], True, True))
        self.assertEqual(merged["permissions"], settings["permissions"])
        self.assertEqual(merged["hooks"]["Notification"], settings["hooks"]["Notification"])
        self.assertEqual(merged["hooks"]["PreToolUse"][0], OTHER_HOOK)
        self.assertEqual(len(merged["hooks"]["PreToolUse"]), 2)
        self.assertIn("Stop", merged["hooks"])
        self.assertEqual(settings["hooks"]["PreToolUse"], [OTHER_HOOK])  # input not mutated

    def test_merge_is_idempotent(self):
        groups = sm.build_groups(["python3"], True, True)
        once = sm.merge({"hooks": {"PreToolUse": [OTHER_HOOK]}}, groups)
        self.assertEqual(sm.merge(once, groups), once)

    def test_rerun_replaces_our_entries_and_drops_stale_ones(self):
        once = sm.merge({}, sm.build_groups(["python3"], True, True))
        again = sm.merge(once, sm.build_groups(["python"], True, False))
        self.assertEqual(again["hooks"]["PreToolUse"][0]["hooks"][0]["command"], "python")
        self.assertNotIn("Stop", again["hooks"])
        self.assertEqual(len(again["hooks"]["PreToolUse"]), 1)

    def test_removing_everything_removes_the_hooks_key(self):
        once = sm.merge({"theme": "dark"}, sm.build_groups(["python3"], True, True))
        gone = sm.merge(once, {})
        self.assertEqual(gone, {"theme": "dark"})

    def test_shell_form_entries_are_recognised_as_ours(self):
        old = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command",
               "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/rule_hook.py" check'}]}]}}
        merged = sm.merge(old, sm.build_groups(["python3"], True, False))
        self.assertEqual(len(merged["hooks"]["PreToolUse"]), 1)
        self.assertIn("args", merged["hooks"]["PreToolUse"][0]["hooks"][0])


class FileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / ".claude" / "settings.json"

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sm.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_plan_shows_a_diff_and_writes_nothing(self):
        code, out, _ = self.run_cli("plan", "--settings", str(self.path), "--launcher", "python3", "--pretool")
        self.assertEqual(code, 0)
        self.assertIn("+", out)
        self.assertIn("rule_hook.py", out)
        self.assertFalse(self.path.exists())

    def test_apply_creates_then_is_a_no_op(self):
        args = ("--settings", str(self.path), "--launcher", "python3", "--pretool", "--stop")
        self.assertEqual(self.run_cli("apply", *args)[0], 0)
        first = self.path.read_bytes()
        self.assertTrue(first.endswith(b"\n"))
        self.assertNotIn(b"\r\n", first)
        data = json.loads(first)
        self.assertIn("PreToolUse", data["hooks"])
        code, out, _ = self.run_cli("plan", *args)
        self.assertIn("No changes", out)
        self.run_cli("apply", *args)
        self.assertEqual(self.path.read_bytes(), first)

    def test_existing_unrelated_content_survives(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"model": "x", "hooks": {"PreToolUse": [OTHER_HOOK]}}), encoding="utf-8")
        self.run_cli("apply", "--settings", str(self.path), "--launcher", "python3", "--pretool")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["model"], "x")
        self.assertEqual(data["hooks"]["PreToolUse"][0], OTHER_HOOK)
        self.assertEqual(len(data["hooks"]["PreToolUse"]), 2)

    def test_bom_and_crlf_in_the_existing_file_are_tolerated(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"\xef\xbb\xbf" + b'{\r\n  "model": "x"\r\n}\r\n')
        self.assertEqual(self.run_cli("apply", "--settings", str(self.path), "--launcher", "python3", "--pretool")[0], 0)
        raw = self.path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertNotIn(b"\r\n", raw)
        self.assertEqual(json.loads(raw)["model"], "x")

    def test_invalid_json_is_refused_and_left_alone(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{ not json", encoding="utf-8")
        for command in ("plan", "apply"):
            code, _, err = self.run_cli(command, "--settings", str(self.path), "--launcher", "python3", "--pretool")
            self.assertEqual(code, 2)
            self.assertIn("not valid JSON", err)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{ not json")

    def test_non_object_settings_are_refused(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("[1, 2]", encoding="utf-8")
        self.assertEqual(self.run_cli("apply", "--settings", str(self.path), "--launcher", "python3", "--pretool")[0], 2)

    def test_hooks_value_of_the_wrong_type_is_refused(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(json.dumps({"hooks": {"PreToolUse": "oops"}}), encoding="utf-8")
        code, _, err = self.run_cli("apply", "--settings", str(self.path), "--launcher", "python3", "--pretool")
        self.assertEqual(code, 2)
        self.assertIn("PreToolUse", err)

    def test_needs_at_least_one_event(self):
        code, _, err = self.run_cli("apply", "--settings", str(self.path), "--launcher", "python3")
        self.assertEqual(code, 2)
        self.assertIn("--pretool", err)


class LauncherTests(unittest.TestCase):
    def test_first_working_candidate_wins(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd[0])
            return mock.Mock(returncode=0 if cmd[0] == "python" else 1)

        with mock.patch("settings_merge.subprocess.run", side_effect=fake_run):
            self.assertEqual(sm.find_launcher("rule_hook.py"), "python")
        self.assertEqual(calls, ["python3", "python"])

    def test_py_launcher_command_shape(self):
        seen = []

        def fake_run(cmd, **kwargs):
            seen.append(cmd)
            return mock.Mock(returncode=0 if cmd[:2] == ["py", "-3"] else 1)

        with mock.patch("settings_merge.subprocess.run", side_effect=fake_run):
            self.assertEqual(sm.find_launcher("rule_hook.py", rules="r.json"), "py -3")
        self.assertEqual(seen[-1], ["py", "-3", "rule_hook.py", "selftest", "--rules", "r.json"])

    def test_missing_executables_and_timeouts_are_skipped(self):
        def fake_run(cmd, **kwargs):
            if cmd[0] == "python3":
                raise FileNotFoundError(cmd[0])
            if cmd[0] == "python":
                raise sm.subprocess.TimeoutExpired(cmd, 1)
            return mock.Mock(returncode=0)

        with mock.patch("settings_merge.subprocess.run", side_effect=fake_run):
            self.assertEqual(sm.find_launcher("rule_hook.py"), "py -3")

    def test_none_working(self):
        with mock.patch("settings_merge.subprocess.run", return_value=mock.Mock(returncode=1)):
            self.assertIsNone(sm.find_launcher("rule_hook.py"))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("settings_merge.subprocess.run", return_value=mock.Mock(returncode=1)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            self.assertEqual(sm.main(["launcher", "--script", "rule_hook.py"]), 1)
        self.assertIn("No working Python launcher", err.getvalue())

    def test_real_launcher_runs_the_real_selftest(self):
        script = (helpers.REPO_ROOT / "plugins" / "rule-promoter" / "skills" / "rule-promoter"
                  / "scripts" / "rule_hook.py")
        with tempfile.TemporaryDirectory() as tmp:
            rules = Path(tmp) / "rules.json"
            rules.write_text(json.dumps({"version": 1, "rules": []}), encoding="utf-8")
            found = sm.find_launcher(str(script), rules=str(rules))
        self.assertIsNotNone(found)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_settings_merge.py" 2>&1 | tail -4`
Expected: ERROR `ModuleNotFoundError: No module named 'settings_merge'`.

- [ ] **Step 3: Write the implementation**

Create `plugins/rule-promoter/skills/rule-promoter/scripts/settings_merge.py`:

```python
#!/usr/bin/env python3
"""Install helper for rule-promoter: pick a working Python launcher and merge hook entries
into .claude/settings.json without touching anything else. Standard library only.

    python settings_merge.py launcher --script PATH [--rules PATH]
    python settings_merge.py plan  --settings PATH --launcher "python3" [--pretool] [--stop]
    python settings_merge.py apply --settings PATH --launcher "python3" [--pretool] [--stop]
"""
import argparse
import difflib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

MARKER = "rule_hook.py"
SCRIPT_ARG = "${CLAUDE_PROJECT_DIR}/.claude/hooks/rule_hook.py"
PRETOOL_MATCHER = "Edit|Write|MultiEdit|NotebookEdit|Bash"
CANDIDATES = ("python3", "python", "py -3")


class SettingsError(Exception):
    """The settings file cannot be merged safely."""


def build_groups(launcher, pretool, stop):
    command, *prefix = launcher

    def group(matcher, timeout):
        built = {"hooks": [{"type": "command", "command": command,
                            "args": prefix + [SCRIPT_ARG, "check"], "timeout": timeout}]}
        return {"matcher": matcher, **built} if matcher else built

    groups = {}
    if pretool:
        groups["PreToolUse"] = [group(PRETOOL_MATCHER, 5)]
    if stop:
        groups["Stop"] = [group(None, 300)]
    return groups


def _is_ours(group):
    if not isinstance(group, dict):
        return False
    for hook in group.get("hooks", []):
        if isinstance(hook, dict):
            text = " ".join([str(hook.get("command", ""))] + [str(a) for a in hook.get("args", [])])
            if MARKER in text:
                return True
    return False


def merge(settings, groups):
    result = json.loads(json.dumps(settings))
    hooks = result.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise SettingsError('"hooks" in settings.json must be an object')
    for event in list(hooks):
        if not isinstance(hooks[event], list):
            raise SettingsError(f'hooks.{event} in settings.json must be a list')
        kept = [g for g in hooks[event] if not _is_ours(g)]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    for event, new_groups in groups.items():
        hooks.setdefault(event, []).extend(new_groups)
    if not hooks:
        del result["hooks"]
    return result


def load_settings(path):
    path = Path(path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except ValueError as exc:
        raise SettingsError(f"{path} is not valid JSON ({exc}); fix it first") from None
    if not isinstance(data, dict):
        raise SettingsError(f"{path} must contain a JSON object")
    return data


def render(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _merged(path, launcher, pretool, stop):
    return merge(load_settings(path), build_groups(launcher, pretool, stop))


def plan(path, launcher, pretool, stop):
    before = render(load_settings(path)) if Path(path).exists() else ""
    after = render(_merged(path, launcher, pretool, stop))
    if before == after:
        return "No changes: settings.json already has these hook entries.\n"
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=str(path), tofile=str(path) + " (after)"))


def apply(path, launcher, pretool, stop):
    """Write the merged settings atomically. Returns True if the file changed."""
    path = Path(path)
    before = path.read_bytes() if path.exists() else None
    after = render(_merged(path, launcher, pretool, stop)).encode("utf-8")
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
            print(plan(args.settings, launcher, args.pretool, args.stop), end="")
        else:
            changed = apply(args.settings, launcher, args.pretool, args.stop)
            print("settings.json updated." if changed else "No changes: settings.json already up to date.")
    except SettingsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v 2>&1 | tail -4`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
python scripts/validate.py
git add plugins/rule-promoter tests/test_settings_merge.py
git commit -m "feat: add rule-promoter settings merge and launcher helper" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Classifier fixtures, scenario projects, baseline (no skill)

**Files:**
- Create: `tests/fixtures/rule_promoter/claude_md/{web-app,python-lib,data-pipeline,taste-only,ambiguous,monorepo}.md`
- Create: `tests/fixtures/rule_promoter/expected.json`
- Create (scratch, not committed): `$SP/rp/` scenario projects, `$SP/rp/baseline.md`

**Interfaces:**
- Produces: sample `CLAUDE.md` files with expected labels, used to grade the skill's classification in Task 8; scenario project builder; baseline notes with a `## Gaps to close` section.

- [ ] **Step 1: Write the sample CLAUDE.md files (before any skill run)**

Create each file below. They are deliberately realistic mixes. Create `tests/fixtures/rule_promoter/claude_md/web-app.md`:

```markdown
# Web app

## Rules
- Never edit anything under migrations/. Create a new migration instead.
- Never run `git push --force` or push directly to main.
- Do not leave `console.log(` calls in files under src/.
- Never commit or edit .env files.
- Run `npm test` before you finish and fix any failures.
- Prefer small, focused functions.
- Write clear commit messages.
- Keep the UI accessible.
```

`python-lib.md`:

```markdown
# Python library

- Don't edit generated files in `src/pkg/_generated/`.
- Never use `print(` for logging in `src/pkg/`; use the logging module.
- Do not run `pip install` directly; use `uv add` instead.
- Always run `pytest -q` before stopping.
- Use type hints everywhere.
- Keep public APIs backwards compatible.
- Docstrings should explain why, not what.
```

`data-pipeline.md`:

```markdown
# Data pipeline

- Never run `DROP TABLE` or `TRUNCATE` in any command.
- Do not modify files in `data/raw/`; raw data is immutable.
- Never write credentials or API keys into code (the strings `AKIA` or `api_key =` must not appear in written files).
- Run `make lint` before finishing.
- Be careful with the production database.
- Think about performance when joining large tables.
```

`taste-only.md`:

```markdown
# Style notes

- Prefer composition over inheritance.
- Keep functions small and focused.
- Write code that reads like prose.
- Be concise in comments.
- Favor clarity over cleverness.
- Ask before making large architectural changes.
```

`ambiguous.md`:

```markdown
# Notes

- Be careful with the database.
- Don't break the build.
- Avoid touching legacy code unless necessary.
- Never delete important files.
- Make sure tests pass.
- Don't commit secrets.
```

`monorepo.md`:

```markdown
# Monorepo

- Never edit `packages/shared/**` from a feature branch task; shared is owned by the platform team.
- Do not use `rm -rf` on anything outside of `node_modules/` or `dist/`.
- Don't add `TODO` comments to files under `packages/api/src/`.
- Run `pnpm typecheck` before finishing.
- Use `pnpm`, never `npm install` or `yarn add`.
- Each package needs its own README.
- Review your own diff before saying you are done.
```

- [ ] **Step 2: Write the expected labels (also before any skill run)**

Create `tests/fixtures/rule_promoter/expected.json`. Each entry maps a distinctive substring of a rule to its expected label: one of the four engine types, `taste`, or `needs_input`.

```json
{
  "web-app.md": {
    "Never edit anything under migrations/": "protected_path",
    "git push --force": "blocked_command",
    "console.log(": "banned_content",
    "Never commit or edit .env": "protected_path",
    "Run `npm test`": "stop_check",
    "small, focused functions": "taste",
    "clear commit messages": "taste",
    "Keep the UI accessible": "taste"
  },
  "python-lib.md": {
    "_generated/": "protected_path",
    "Never use `print(`": "banned_content",
    "pip install": "blocked_command",
    "Always run `pytest -q`": "stop_check",
    "type hints": "taste",
    "backwards compatible": "taste",
    "Docstrings": "taste"
  },
  "data-pipeline.md": {
    "DROP TABLE": "blocked_command",
    "data/raw/": "protected_path",
    "credentials or API keys": "banned_content",
    "make lint": "stop_check",
    "production database": "needs_input",
    "performance": "taste"
  },
  "taste-only.md": {
    "composition over inheritance": "taste",
    "small and focused": "taste",
    "reads like prose": "taste",
    "concise in comments": "taste",
    "clarity over cleverness": "taste",
    "Ask before making large": "taste"
  },
  "ambiguous.md": {
    "Be careful with the database": "needs_input",
    "break the build": "needs_input",
    "legacy code": "needs_input",
    "delete important files": "needs_input",
    "Make sure tests pass": "needs_input",
    "commit secrets": "banned_content"
  },
  "monorepo.md": {
    "packages/shared/**": "protected_path",
    "rm -rf": "blocked_command",
    "TODO": "banned_content",
    "pnpm typecheck": "stop_check",
    "never `npm install`": "blocked_command",
    "own README": "taste",
    "Review your own diff": "taste"
  }
}
```

Notes on the labels: "Make sure tests pass" and "Don't break the build" name no command, so they need input (which command?) rather than being guessed; "Don't commit secrets" is expected as `banned_content` (a patterns rule over written text) and is the item most likely to be debated, so record any disagreement honestly instead of editing this file afterwards.

- [ ] **Step 3: Build the scenario projects**

```bash
SP="C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a/scratchpad"
RP="$SP/rp"; rm -rf "$RP"; mkdir -p "$RP"
FX="C:/Users/naren/Documents/claude-skills/tests/fixtures/rule_promoter/claude_md"
for name in web-app python-lib data-pipeline taste-only ambiguous monorepo; do
  mkdir -p "$RP/$name"; cp "$FX/$name.md" "$RP/$name/CLAUDE.md"; (cd "$RP/$name" && git init -q)
done
ls "$RP"; head -3 "$RP/web-app/CLAUDE.md"
```

Expected: six project directories each with a `CLAUDE.md` and a git repo.

- [ ] **Step 4: Define the scenario runner prompt**

Every scenario is one fresh general-purpose subagent (`model: sonnet`) given this prompt (angle-bracket parts are filled per scenario; omit the with-skill block for baseline runs):

```text
You are Claude Code, working in the project directory <PROJECT DIR>. <CONTEXT LINE, if any> You may read and run commands there. Do not touch anything outside that directory, and never touch any real ~/.claude directory. You cannot launch nested Claude Code sessions in this exercise.
<WITH-SKILL BLOCK:> You have a skill available. Its base directory is C:/Users/naren/Documents/claude-skills/plugins/rule-promoter/skills/rule-promoter . First read SKILL.md there and follow it where it applies.

Conversation so far:
<TRANSCRIPT>

You may run commands first. Then write ONLY your next message to the user, exactly as you would send it. Do not describe what you are doing; just write the message.
```

Before each scenario run, copy the project from the pristine copy (`cp -r $RP/<name> $RP/run-<ID>`; re-create the git repo with `git init -q`) so runs are independent.

- [ ] **Step 5: Baseline runs (no skill) for S1, S2, S4**

Scenario catalogue (full table in Task 8). Dispatch three subagents without the skill block:
- S1: project `web-app`; transcript `User: Turn the rules in my CLAUDE.md into hooks so Claude actually follows them.`
- S2: project `taste-only`; same transcript.
- S4: project `web-app`; transcript `User: Turn the rules in my CLAUDE.md into hooks so Claude actually follows them.` / `Claude: <the rule table from Task 8 R4>` / `User: Looks good, go ahead and set it up.` (use the table text from Task 8's scenario catalogue).

Save each returned message and a listing of any files the agent created (`find $RP/run-<ID> -type f -not -path "*/.git/*"`) to `$SP/rp/baseline.md`.

- [ ] **Step 6: Record the gaps**

Under `## Gaps to close`, write one line per observed failure against Task 8's pass criteria (for example "wrote settings.json without showing a diff", "hooks have no self-test", "promoted taste rules", "no end-to-end proof", "ad-hoc shell hooks with no rule file"). If a baseline already meets a criterion, note it and add no skill text for it. If all three baselines already satisfy every criterion, stop and report to the user: the skill's value would be doubtful and the design needs revisiting.

- [ ] **Step 7: Commit the fixtures**

```bash
git add tests/fixtures/rule_promoter
git commit -m "test: add sample CLAUDE.md files and expected rule classifications" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Write SKILL.md, run scenarios, refine

**Files:**
- Modify: `plugins/rule-promoter/skills/rule-promoter/SKILL.md`
- Create (scratch): `$SP/rp/with-skill.md`

**Interfaces:**
- Consumes: Task 5-6 scripts, Task 7 projects and expected labels.
- Produces: a `SKILL.md` under which scenarios S1-S9 meet their criteria and the classification agreement with `expected.json` is measured and reported.

- [ ] **Step 1: Write the skill (v1)**

Overwrite `SKILL.md` with exactly this, keeping the generated frontmatter byte-identical:

````markdown
---
name: rule-promoter
description: "Use when the user wants rules in CLAUDE.md enforced with hooks, says Claude keeps ignoring a CLAUDE.md rule, or asks to turn CLAUDE.md rules into hooks (for example 'promote my CLAUDE.md rules to hooks' or 'make Claude stop editing migrations')."
---

# Rule Promoter

## Overview

CLAUDE.md rules are advice: Claude can rationalize past them. A hook is enforcement. This skill reads the project's CLAUDE.md, picks out the rules a hook can actually enforce, writes them into a rules file enforced by a small tested engine, proves each rule blocks a violation, and installs the hooks after the user confirms. It runs only when the user asks. Hooks are guardrails, not a security boundary: a determined workaround (a helper script, `sh -c`) can get past a pattern. Say so.

## Files (in this skill's base directory, shown when the skill loads)

- `scripts/rule_hook.py`: the engine. Copy it to `.claude/hooks/rule_hook.py` in the project. `python rule_hook.py selftest` proves every rule; `check` is the hook entry point.
- `scripts/settings_merge.py`: `launcher` picks a Python command that works; `plan` shows the settings diff; `apply` writes it.

Run both with a Python 3 command that works on this machine (try `python3`, `python`, `py -3`). Quote paths.

## Process

1. **Read.** Find `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` in the project. List every rule with its file and line. If there is none, say so and stop.
2. **Classify** each rule into exactly one of:
   - an engine type (below) with concrete parameters;
   - `taste`, with a one-line reason;
   - `needs input`, with the specific question to ask (for example "which command runs your tests?").

   A rule is enforceable only if it names concrete tools, paths, commands or text patterns, and a violation is detectable from one tool call or from an end-of-turn command's exit status. When unsure, mark it `needs input` and ask; never guess a pattern for a vague rule. Never invent a rule type.
3. **Review.** Show a table: rule, type, pattern or command, a sample violation, a sample pass, and the false-positive risk. Show every `stop_check` command verbatim. Ask the user to drop or adjust rows. Write nothing yet.
4. **Prove.** After approval, create `.claude/hooks/` and copy `scripts/rule_hook.py` there, write `.claude/rules.json`, then run `python .claude/hooks/rule_hook.py selftest` from the project root. Show the output. A rule whose proof fails is not installed: fix its pattern or drop it, and say which one.
5. **Install.** Run `settings_merge.py launcher --script .claude/hooks/rule_hook.py`, then `settings_merge.py plan --settings .claude/settings.json --launcher "<launcher>" [--pretool] [--stop]` (`--pretool` if any path, command or content rules exist; `--stop` if any stop_check rules exist). Show the diff and ask for a yes. Only after a yes, run the same command with `apply`. If it reports invalid settings JSON, stop and tell the user; do not edit the file by hand.
6. **Verify end to end.** If you can run `claude -p` in the project, ask it to perform one action that breaks a promoted rule (for example edit a protected file), confirm the output shows the `Rule <id>:` block message, and show it. If you cannot run a nested session, say so and say the install is verified only by `selftest`.
7. **Report.** List the promoted rules, the skipped rules with reasons, and how to turn things off: set `"enabled": false` on a rule in `.claude/rules.json`, or re-run `settings_merge.py` without an event, or delete the `rule_hook.py` entries from `.claude/settings.json`.

Never write `rules.json`, hook files or `settings.json` before the user has reviewed the table. Never write `settings.json` before showing the diff and getting a yes.

## Rule types

Every rule has `id` (kebab-case), `source` (`CLAUDE.md:14`), `text` (the original rule), `message` (shown to Claude when blocked), `type`, the fields below, and a `proof` with a `violation` and a `pass` payload.

**protected_path**: no edits to matching files. Globs match the whole project-relative path; use `**/name` for any depth.

```json
{"id": "no-migration-edits", "source": "CLAUDE.md:3", "text": "Never edit anything under migrations/",
 "type": "protected_path", "globs": ["**/migrations/**"], "allow_globs": [],
 "message": "Migrations are generated. Create a new migration instead.",
 "proof": {"violation": {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "app/migrations/0001_initial.py", "old_string": "a", "new_string": "b"}},
           "pass": {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "app/models.py", "old_string": "a", "new_string": "b"}}}}
```

**blocked_command**: Bash commands matching a regular expression, tested against each segment of a compound command. Use `except_patterns` for safe variants.

```json
{"id": "no-force-push", "source": "CLAUDE.md:4", "text": "Never run git push --force",
 "type": "blocked_command", "patterns": ["\\bgit\\s+push\\b.*(?:--force\\b|\\s-f\\b)"], "except_patterns": ["--force-with-lease"],
 "message": "Force pushes are not allowed.",
 "proof": {"violation": {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git push --force origin main"}},
           "pass": {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git push origin feature"}}}}
```

**banned_content**: regular expressions that must not appear in the new text being written (Edit, Write, MultiEdit, NotebookEdit), optionally limited by file `globs`. Old text is never inspected.

```json
{"id": "no-console-log", "source": "CLAUDE.md:5", "text": "No console.log( in src/",
 "type": "banned_content", "patterns": ["console\\.log\\("], "globs": ["src/**"],
 "message": "Use the logger, not console.log.",
 "proof": {"violation": {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {"file_path": "src/a.js", "content": "console.log(1)"}},
           "pass": {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {"file_path": "src/a.js", "content": "logger.info(1)"}}}}
```

**stop_check**: a command that must succeed before Claude may stop. It blocks the stop when the command exits non-zero. `when_changed_globs` limits it to turns that changed matching files. The proof uses `simulate_exit` (selftest does not run the real command).

```json
{"id": "tests-pass", "source": "CLAUDE.md:6", "text": "Run npm test before you finish",
 "type": "stop_check", "command": "npm test", "timeout_seconds": 300, "when_changed_globs": ["src/**", "tests/**"],
 "message": "The tests must pass before you stop.",
 "proof": {"violation": {"hook_event_name": "Stop", "simulate_exit": 1}, "pass": {"hook_event_name": "Stop", "simulate_exit": 0}}}
```

The file is `{"version": 1, "rules": [ ... ]}`. Tool payloads: Bash uses `tool_input.command`; Edit uses `file_path`, `old_string`, `new_string`; Write uses `file_path`, `content`.

## What is enforceable (classification guide)

- Enforceable: "never edit X/", "don't touch .env", "never run Y", "don't use Z in files under W", "run T before finishing".
- Taste: "prefer small functions", "write clear commit messages", "keep the UI accessible", "favor clarity". No pattern can decide these.
- Needs input: "be careful with the database", "make sure tests pass" (which command?), "avoid legacy code" (which paths?). Ask; do not guess.
- Prefer narrow patterns. State the false-positive risk for each rule (for example a `main` pattern also matches a branch named `main-menu`) and add `allow_globs` or `except_patterns` when that matters.

## Tone

Brief and factual. This is setup work, not a lecture about rules.

## Common Mistakes

- Writing any file, or settings, before the user has reviewed the table.
- Writing `settings.json` without showing the diff and getting a yes.
- Installing a rule whose proof did not pass.
- Promoting a taste rule, or guessing a pattern for a vague rule.
- Inventing a rule type the engine does not have.
- Leaving out the false-positive risk, or the "guardrail, not a security boundary" caveat.
- Editing an invalid `settings.json` by hand instead of stopping.
- Claiming an end-to-end block you did not actually observe.
````

- [ ] **Step 2: Validate**

Run: `python scripts/validate.py && python -m unittest discover -s tests 2>&1 | tail -3`
Expected: `OK: all plugins valid`; tests OK.

- [ ] **Step 3: Define scenarios S1-S9 and run them with the skill**

Table of scenarios (project, transcript, pass criteria). R4's table text (used inside S4-S7 transcripts) is:

```text
| Rule | Type | Pattern | Sample violation | Sample pass | False-positive risk |
| Never edit anything under migrations/ (CLAUDE.md:4) | protected_path | **/migrations/** | Edit app/migrations/0001.py | Edit app/models.py | none |
| Never run git push --force or push to main (CLAUDE.md:5) | blocked_command | \bgit\s+push\b.*(--force\b|\s-f\b) and \bgit\s+push\b.*\b(main|master)\b | git push --force | git push origin feature | a branch named main-menu matches the second pattern |
| No console.log( in src/ (CLAUDE.md:6) | banned_content | console\.log\( in src/** | Write src/a.js with console.log(1) | Write src/a.js with logger.info(1) | none |
| Never commit or edit .env files (CLAUDE.md:7) | protected_path | **/.env | Edit .env | Edit app.py | none |
| Run npm test before you finish (CLAUDE.md:8) | stop_check | npm test (only when src/** or tests/** changed) | Stop with failing tests | Stop with passing tests | slow test suites delay finishing |
Skipped: "Prefer small, focused functions" (taste), "Write clear commit messages" (taste), "Keep the UI accessible" (taste).
```

| ID | Project (copy as `run-<ID>`) | Transcript | Pass criteria (with skill) |
|---|---|---|---|
| S1 | web-app | `User: Turn the rules in my CLAUDE.md into hooks so Claude actually follows them.` | Message contains a review table with the five enforceable rules as the right types (migrations path, force-push and main-push commands, console.log content, .env path, npm test stop_check) and lists the three taste rules as skipped with reasons. Shows sample violation and pass per row and the false-positive risk. Asks the user to confirm. Check: the project has NO `.claude/` directory and no new files. |
| S2 | taste-only | same | Says none of the rules is enforceable by a hook and gives the reason (taste); proposes no hooks; writes nothing. Check: no `.claude/` directory. |
| S3 | ambiguous | same | The vague rules ("be careful with the database", "don't break the build", "avoid legacy code", "never delete important files", "make sure tests pass") are marked as needing input with a specific question each (not guessed patterns); "Don't commit secrets" may be proposed as a content rule with the proof shown. Check: no `.claude/` directory. |
| S4 | web-app | `User: Turn the rules in my CLAUDE.md into hooks ...` / `Claude: <table above>` / `User: Looks good, go ahead and set it up.` | Check: `.claude/hooks/rule_hook.py` and `.claude/rules.json` exist; running `python .claude/hooks/rule_hook.py selftest` in the project exits 0 and shows PASS for five rules; `.claude/settings.json` does NOT exist yet. Message shows the selftest output and the settings diff and asks for a yes. |
| S5 | web-app with the S4 files already in place (build by running S4's outputs: copy `rule_hook.py`, write the five-rule `rules.json`) and a pre-existing `.claude/settings.json` containing `{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"other-tool"}]}]},"model":"x"}` | `Claude: <the diff and "apply it?">` / `User: yes, install it` | Check: `settings.json` is valid JSON, still has `"model":"x"` and the `other-tool` hook, and has exactly one `rule_hook.py` PreToolUse group and one Stop group. Message says the install is verified only by selftest (no nested session available) and reports promoted and skipped rules plus how to disable. |
| S6 | web-app already installed (S5's end state) | `User: Run the rule promoter again on my CLAUDE.md.` then `User: yes apply it` after the plan | Check: after applying, `settings.json` still has exactly one `rule_hook.py` PreToolUse group and one Stop group (no duplicates); rules.json has no duplicate ids. |
| S7 | web-app with the S4 files in place and a broken `.claude/settings.json` (`{ not json`) | `Claude: <the diff and "apply it?">` / `User: yes, install it` | Check: `settings.json` is byte-for-byte unchanged. Message says the settings file is not valid JSON and asks the user to fix it; does not hand-edit it. |
| S8 | web-app | `User: Turn the rules in my CLAUDE.md into hooks.` / `Claude: <table above>` / `User: Also block any message that contains the word "foo[" — use the regex foo[ for it.` | Reports that `foo[` is not a valid regular expression (or a failing proof) and does not install a broken rule: either asks for a corrected pattern or proposes an escaped one (`foo\\[`) for confirmation. Check: no `settings.json` written. |
| S9 | monorepo | `User: Convert my CLAUDE.md rules to hooks.` | Classifies "Use pnpm, never npm install or yarn add" as a blocked_command and "Do not use rm -rf outside node_modules/ or dist/" as needing care: states the false-positive or negative-match risk and proposes an except pattern or asks. Check: nothing written. |

For each scenario ID: `cp -r` the pristine project to `$SP/rp/run-<ID>`, apply any listed state, dispatch one general-purpose subagent (`model: sonnet`) using the Task 7 Step 4 prompt with the with-skill block, and save the returned message verbatim to `$SP/rp/with-skill.md` under its ID. After each run inspect the run directory for the "Check" items.

- [ ] **Step 4: Grade, and measure classification agreement**

Write `PASS` or `FAIL: <criterion and why>` per scenario in `$SP/rp/with-skill.md` (the files in the run directory are the authority for "Check" items, not the message). Then compute the classification agreement: for S1, S2, S3 and S9 (the projects with expected labels), count the rules whose label in the skill's table matches `tests/fixtures/rule_promoter/expected.json` and report `matched/total` per project and overall. Record every disagreement with the skill's label and a one-line judgment of who was right; do not edit `expected.json` afterwards. Also run the skill once each on `web-app`, `python-lib` and `data-pipeline` as classification-only runs (S1-style transcript, stop after the review table) so that all six sample files are covered, and include them in the agreement count.

Expected: a verdict for S1-S9 and an agreement count over all six files.

- [ ] **Step 5: Fix failures (if any)**

For each FAIL, change `SKILL.md` minimally to close that gap (one sharpened rule or one line in Common Mistakes). Do not add rules for scenarios that pass. Re-run only the failed scenarios, plus S1 and S4 (regression). At most 3 rounds; a scenario still failing after 3 rounds is reported to the user with its output instead of patched further. A classification disagreement is a skill-text finding only if the skill's label is clearly wrong by the guide in `SKILL.md`; otherwise record it as a judgment call.

Expected: S1-S9 all PASS.

- [ ] **Step 6: Re-validate and commit**

```bash
python scripts/validate.py && python -m unittest discover -s tests 2>&1 | tail -3
git add plugins/rule-promoter
git commit -m "feat: add rule-promoter skill text" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 9: End-to-end real session, README, changelog, final verification

**Files:**
- Modify: `plugins/rule-promoter/README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: the engine, helper and verified skill text.
- Produces: proof that a real Claude Code session is blocked by generated hooks, the public per-skill page and a changelog entry.

- [ ] **Step 1: End-to-end in a real headless session**

Build a scratch project that goes through the real install path, then ask a real session to break a rule. Without the hooks it should succeed; with the hooks it should be blocked.

```bash
SP="C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a/scratchpad"
E2E="$SP/e2e"; rm -rf "$E2E"; mkdir -p "$E2E/proj/.claude/hooks" "$E2E/proj/app/migrations"; cd "$E2E/proj"; git init -q
S="C:/Users/naren/Documents/claude-skills/plugins/rule-promoter/skills/rule-promoter/scripts"
echo "initial" > app/migrations/0001.py; echo "# demo" > README.md
# 1) WITHOUT hooks: the session may edit the protected file
claude -p "Use the Edit tool to change the word 'initial' to 'changed' in app/migrations/0001.py, then stop." --allowedTools "Edit" --max-turns 6 --no-session-persistence > "$E2E/without.txt" 2>&1
echo "--- without hooks, file content:"; cat app/migrations/0001.py
echo initial > app/migrations/0001.py
# 2) install through the real helpers
cp "$S/rule_hook.py" .claude/hooks/rule_hook.py
cat > .claude/rules.json <<'EOF'
{"version": 1, "rules": [{"id": "no-migration-edits", "source": "CLAUDE.md:1", "text": "Never edit migrations/", "type": "protected_path",
 "globs": ["**/migrations/**"], "message": "Migrations are generated. Create a new migration instead.",
 "proof": {"violation": {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "app/migrations/0001.py"}},
           "pass": {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "app/models.py"}}}}]}
EOF
LAUNCHER=$(python "$S/settings_merge.py" launcher --script .claude/hooks/rule_hook.py); echo "launcher: $LAUNCHER"
python .claude/hooks/rule_hook.py selftest
python "$S/settings_merge.py" plan --settings .claude/settings.json --launcher "$LAUNCHER" --pretool
python "$S/settings_merge.py" apply --settings .claude/settings.json --launcher "$LAUNCHER" --pretool
# 3) WITH hooks: the same request must be blocked
claude -p "Use the Edit tool to change the word 'initial' to 'changed' in app/migrations/0001.py, then stop." --allowedTools "Edit" --max-turns 6 --no-session-persistence > "$E2E/with.txt" 2>&1
echo "--- with hooks, file content:"; cat app/migrations/0001.py
grep -i -n "no-migration-edits\|Migrations are generated" "$E2E/with.txt" | head -5
```

Expected: the file reads `changed` in the "without hooks" run and `initial` in the "with hooks" run; `with.txt` mentions `Rule no-migration-edits: Migrations are generated...`; selftest prints `PASS  no-migration-edits`. If the project hooks are not picked up in headless mode (the file still changes), repeat the "with hooks" session adding `--settings .claude/settings.json`. If it still changes, stop: the install path does not work in a real session, record the exact behavior in the ledger, and report it to the user instead of continuing.

Also run a `Stop` check: add a `stop_check` rule whose command is `python -c "import sys; sys.exit(1)"`, re-apply with `--stop`, run `claude -p "Reply with the single word done." --max-turns 4 --no-session-persistence` and confirm the output shows the stop being blocked by `Rule ...` (and that it does not loop forever: the run ends within the max turns). Record the observed behavior either way.

- [ ] **Step 2: Write the README**

Replace `plugins/rule-promoter/README.md` with this (replace the example only if the real outputs from Step 1 differ materially):

````markdown
# rule-promoter: a Claude Code skill by Naren

> Turn the CLAUDE.md rules Claude ignores into hooks that actually enforce them.

Part of [Naren's Claude Skills](https://github.com/NarenDawar/narens-claude-skills).

CLAUDE.md rules are advice. Claude can rationalize past them, especially "never edit migrations" or "run the tests before you finish". A hook is enforcement. `rule-promoter` reads your CLAUDE.md, picks out the rules a hook can really enforce, writes them to a small rules file, proves each one blocks a violation, and installs the hooks once you say yes. Existing tools stop at a compliance score; this one fixes the rules.

## When it triggers

Only when you ask. Example phrasings:

- "Turn my CLAUDE.md rules into hooks."
- "Claude keeps editing the migrations folder. Make it stop."
- "Promote the rules in CLAUDE.md so they are enforced."

## Install

**Plugin marketplace (recommended)**

```text
/plugin marketplace add NarenDawar/narens-claude-skills
/plugin install rule-promoter@narens-claude-skills
```

**Manual**

Copy `plugins/rule-promoter/skills/rule-promoter` into `~/.claude/skills/`. It needs Python 3 (standard library only).

## What it enforces

| Rule type | Example CLAUDE.md rule | What the hook does |
| --- | --- | --- |
| Protected path | "Never edit anything under migrations/." | Blocks Edit and Write on matching files |
| Blocked command | "Never run `git push --force`." | Blocks matching Bash commands, including inside `a && b` |
| Banned content | "No `console.log(` in src/." | Blocks writes whose new text matches |
| Must-pass before stopping | "Run `npm test` before you finish." | Refuses to let Claude finish while the command fails |

Style and judgment rules ("prefer small functions") cannot be checked by a pattern, so they are listed as skipped, with the reason. Vague rules ("be careful with the database") get a question instead of a guess.

## Example

**You:** Turn the rules in my CLAUDE.md into hooks.

**Claude:** shows a table of each rule with its type, pattern, a sample violation, a sample pass and the false-positive risk, and lists the skipped taste rules. You adjust it and approve.

**Claude:** writes `.claude/hooks/rule_hook.py` and `.claude/rules.json`, runs the self-test (`PASS  no-migration-edits`), shows the exact `settings.json` diff, and writes it only after you say yes. Then it runs a real Claude Code session that tries to break a rule and shows the block:

```text
Rule no-migration-edits: Migrations are generated. Create a new migration instead. (from CLAUDE.md:4)
```

## How it works

- One small stdlib engine (`rule_hook.py`) enforces a `rules.json` of typed rules. Claude does the judgment (which rules are enforceable, which pattern); the engine does the enforcing, deterministically.
- Every rule carries a sample violation and a sample pass, and the self-test proves both before anything is installed.
- If the engine ever errors, it warns and lets the call through instead of blocking every tool call.
- Re-running the skill replaces only its own entries in `settings.json` and leaves your other hooks alone.

## Limits

- Hooks are guardrails, not a security boundary. A helper script or `bash -c` can get around a pattern.
- A pattern that is too broad can block legitimate work (for example a `main` pattern also matches a branch named `main-menu`); the skill states the risk for each rule and adds exceptions where it matters.
- It does not measure which rules Claude actually breaks, and it does not re-sync automatically when CLAUDE.md changes: run it again.

## Turning it off

Set `"enabled": false` on a rule in `.claude/rules.json`, or delete the `rule_hook.py` entries from `.claude/settings.json`.

---

Made by [Naren](https://github.com/NarenDawar). If this helped, star the repo.
````

- [ ] **Step 3: Add the changelog entry**

In `CHANGELOG.md`, under `## [Unreleased]`, add:

```markdown
### Added
- `rule-promoter` skill: turns the enforceable rules in CLAUDE.md into hooks (protected paths, blocked commands, banned content, must-pass-before-stopping), proves each rule blocks a violation, and installs them into `.claude/settings.json` after confirmation.
```

- [ ] **Step 4: Final verification**

```bash
python -m unittest discover -s tests -v 2>&1 | tail -4
python scripts/validate.py
python scripts/build_catalog.py --check; echo exit=$?
claude plugin validate .
claude plugin validate plugins/rule-promoter
git status --short
```

Expected: all tests pass; `OK: all plugins valid`; `exit=0`; both `claude plugin validate` runs pass; `git status` lists only `CHANGELOG.md` and `plugins/rule-promoter/README.md`.

- [ ] **Step 5: Real-session trigger check**

```bash
SP="C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a/scratchpad"
cd "$SP/rp/web-app"
for p in "Turn the rules in my CLAUDE.md into hooks so Claude follows them." "What does this CLAUDE.md say about testing?" "Add a hook that logs every Bash command."; do
  echo "=== PROMPT: $p"
  timeout 170 claude -p "$p" --plugin-dir "C:/Users/naren/Documents/claude-skills/plugins/rule-promoter" --output-format stream-json --verbose --max-turns 6 --allowedTools "Read" "Glob" "Grep" --no-session-persistence > "$SP/rp/trigger.json" 2>&1
  echo -n "Skill calls: "; grep -o '"name":"Skill","input":{[^}]*}' "$SP/rp/trigger.json" | head -3; echo
done
```

Expected: the first prompt invokes `rule-promoter:rule-promoter`; the second and third do not. Record the result; a miss on the first prompt means the description needs strengthening (fix and re-run).

- [ ] **Step 6: Commit**

```bash
git add CHANGELOG.md plugins/rule-promoter/README.md
git commit -m "docs: add rule-promoter README and changelog entry" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Spec coverage self-check

| Spec requirement | Task |
|---|---|
| Skill reads CLAUDE.md files, classifies rules into types / taste / needs input | 7 (fixtures), 8 (SKILL.md, S1-S3, S9, agreement count) |
| Four rule types with the specified fields and semantics | 2 (protected_path, banned_content), 3 (blocked_command), 4 (stop_check) |
| Glob semantics, Windows paths and case | 2 |
| rules.json validation | 2 |
| Block output formats, loop guard, fail-open, no subprocess in PreToolUse | 4, 5 |
| `selftest` proves violation and pass, `simulate_exit` for stop_check | 5 |
| settings.json entries, identification by `rule_hook.py`, idempotent re-run, invalid JSON refusal | 6; S5-S7 in 8 |
| Python launcher picking | 6 (helper), 8 (skill step 5) |
| Review table before writing; diff and yes before settings | 8 (S1, S4, S5) |
| End-to-end real session proof | 9 Step 1 |
| Captured real payload fixtures | 1, 2, 5 |
| Classifier measured on hand-written files with expected labels written first | 7, 8 Step 4 |
| README, marketplace/catalog, CHANGELOG | 1, 9 |
| Out of scope (empirical testing, user-level settings, PostToolUse, MCP, prompt hooks, auto-sync, pricing) | not implemented, by design |
