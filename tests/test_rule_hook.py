import contextlib
import io
import json
import os
import sys
import tempfile
import time
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


def fixture_text(name, project):
    """A captured payload with {PROJECT} filled in.

    The captures came from Windows, so the path after the placeholder uses an escaped backslash;
    on POSIX that separator becomes a slash (a backslash is just a filename character there).
    """
    text = (FIXTURES / name).read_text(encoding="utf-8")
    if os.sep == "/":
        text = text.replace("{PROJECT}\\\\", "{PROJECT}/")
    return text.replace("{PROJECT}", project.replace("\\", "\\\\"))


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
        with mock.patch.object(rule_hook, "_CI", True):
            rule_hook.glob_to_regex.cache_clear()
            self.assertTrue(rule_hook.glob_match(["**/migrations/**"], "App/Migrations/x.py"))
        with mock.patch.object(rule_hook, "_CI", False):
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
        return json.loads(fixture_text(name, self.project))

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
            "Rule no-migration-edits: Create a new migration instead. (from CLAUDE.md:14) [path: app/migrations/9.py]",
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
        code, out, _ = self.run_main(["check"], fixture_text("PreToolUse-Write.json", self.project))
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


class EngineReviewTests(RuleCase):
    # --- I-1: the stop_check timeout must hold even when a grandchild keeps running ----------
    def test_stop_timeout_is_honoured_with_a_hung_grandchild(self):
        rule = make_rule("stop_check", command=py("import time; time.sleep(15)"), timeout_seconds=1)
        err = io.StringIO()
        started = time.monotonic()
        with contextlib.redirect_stderr(err):
            self.assertIsNone(self.hit(rule, stop()))
        self.assertLess(time.monotonic() - started, 6)
        self.assertIn("timed out", err.getvalue())

    # --- I-2 and I-3: git status parsing -------------------------------------------------------
    def git(self, *args, cwd=None):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
                       cwd=cwd or self.project, check=True, capture_output=True)

    @unittest.skipUnless(shutil.which("git"), "git not available")
    def test_when_changed_globs_in_a_project_below_the_repo_root(self):
        self.git("init", "-q")
        web = Path(self.project, "packages", "web")
        (web / "src").mkdir(parents=True)
        Path(self.project, "other").mkdir()
        Path(self.project, "other", "b.py").write_text("x")  # a change outside the project: ignored
        rule = make_rule("stop_check", command=py("import sys; sys.exit(1)"), when_changed_globs=["src/**"])
        self.assertIsNone(rule_hook.check_rule(rule, stop(), str(web)))
        (web / "src" / "a.py").write_text("x")
        self.assertIsNotNone(rule_hook.check_rule(rule, stop(), str(web)))

    @unittest.skipUnless(shutil.which("git"), "git not available")
    def test_when_changed_globs_with_unicode_names_and_renames(self):
        self.git("init", "-q")
        (Path(self.project) / "src").mkdir()
        Path(self.project, "src", "a.py").write_text("x")
        self.git("add", "-A")
        self.git("commit", "-qm", "base")
        failing = py("import sys; sys.exit(1)")
        rule = make_rule("stop_check", command=failing, when_changed_globs=["src/**"])
        self.assertIsNone(self.hit(rule, stop()))  # clean tree
        self.git("mv", "src/a.py", "moved.py")  # the rename's ORIGINAL path was under src/
        self.assertIsNotNone(self.hit(rule, stop()))
        self.git("reset", "-q", "--hard")
        Path(self.project, "src", "café.py").write_text("x")  # git C-quotes non-ASCII names
        self.assertIsNotNone(self.hit(make_rule("stop_check", command=failing, when_changed_globs=["src/*.py"]), stop()))

    # --- I-5: path aliases ---------------------------------------------------------------------
    def test_symlink_or_junction_does_not_hide_a_protected_path(self):
        real = Path(self.project, "app", "migrations")
        real.mkdir(parents=True)
        link = Path(self.project, "m")
        try:
            if os.name == "nt":
                subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(real)], check=True, capture_output=True)
            else:
                os.symlink(real, link, target_is_directory=True)
        except (OSError, subprocess.SubprocessError):
            self.skipTest("cannot create a link here")
        rule = make_rule("protected_path", globs=["**/migrations/**"])
        self.assertIsNotNone(self.hit(rule, pre("Write", file_path=str(link / "0002.py"), content="x")))

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_ntfs_stream_suffix_and_extended_prefix(self):
        rule = make_rule("protected_path", globs=["**/.env"])
        self.assertIsNotNone(self.hit(rule, pre("Write", file_path=self.path(".env::$DATA"), content="x")))
        self.assertIsNotNone(self.hit(rule, pre("Write", file_path="\\\\?\\" + self.path(".env"), content="x")))

    @unittest.skipUnless(os.name == "nt", "Windows only")
    def test_short_names_are_resolved(self):
        import ctypes
        directory = Path(self.project, "longdirectoryname")
        directory.mkdir()
        buf = ctypes.create_unicode_buffer(260)
        length = ctypes.windll.kernel32.GetShortPathNameW(str(directory), buf, 260)
        if not length or buf.value.lower() == str(directory).lower():
            self.skipTest("8.3 short names are disabled on this volume")
        rule = make_rule("protected_path", globs=["longdirectoryname/**"])
        self.assertIsNotNone(self.hit(rule, pre("Write", file_path=os.path.join(buf.value, "a.txt"), content="x")))

    # --- I-6 and I-9 ---------------------------------------------------------------------------
    def test_line_continuation_does_not_hide_a_command(self):
        rule = make_rule("blocked_command", patterns=[r"\bgit\s+push\b.*(?:--force\b|\s-f\b)"])
        command = "git push \\\n  --force origin main"
        self.assertEqual(len(rule_hook.split_segments(command)), 1)
        self.assertIsNotNone(self.hit(rule, pre("Bash", command=command)))

    def test_banned_content_anchors_work_on_multiline_text(self):
        rule = make_rule("banned_content", patterns=[r"^import os$"])
        self.assertIsNotNone(self.hit(rule, pre("Write", file_path="a.py", content="import sys\nimport os\n")))
        self.assertIsNone(self.hit(rule, pre("Write", file_path="a.py", content="import sys\nimport osx\n")))


class OneBadRuleTests(MainCase):
    def test_one_invalid_rule_does_not_disable_the_others(self):
        bad = make_rule("protected_path", id="bad-rule", globs=[])
        self.write_rules([bad, self.migration_rule()])
        code, out, err = self.run_main(["check"], json.dumps(pre("Edit", file_path="app/migrations/1.py")))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertIn("bad-rule", err)
        code, out, err = self.run_main(["check"], json.dumps(pre("Edit", file_path="app/models.py")))
        self.assertEqual((code, out), (1, ""))  # a visible non-blocking warning on every call
        self.assertIn("bad-rule", err)

    def test_duplicate_ids_flag_only_the_later_rule(self):
        first = self.migration_rule(id="same", message="first")
        second = self.migration_rule(id="same", message="second")
        self.write_rules([first, second])
        code, out, err = self.run_main(["check"], json.dumps(pre("Edit", file_path="app/migrations/1.py")))
        self.assertEqual(code, 0)
        self.assertIn("first", out)
        self.assertIn("duplicate id", err)

    def test_selftest_still_fails_on_any_invalid_rule(self):
        self.write_rules([make_rule("protected_path", id="bad-rule", globs=[]), self.migration_rule()])
        self.assertEqual(self.run_main(["selftest"])[0], 1)


class CompileTests(unittest.TestCase):
    def test_scripts_compile_without_warnings(self):
        import warnings
        scripts = helpers.REPO_ROOT / "plugins" / "rule-promoter" / "skills" / "rule-promoter" / "scripts"
        for name in ("rule_hook.py", "settings_merge.py"):
            source = (scripts / name).read_text(encoding="utf-8")
            with self.subTest(script=name), warnings.catch_warnings():
                warnings.simplefilter("error")
                compile(source, name, "exec")


class DeferredMinorTests(RuleCase):
    # M-1: "enabled" must be a boolean, or "false" (a truthy string) would silently enable a rule
    def test_enabled_must_be_a_boolean(self):
        rule = make_rule("protected_path", globs=["a/**"], enabled="false")
        errors = rule_hook.validate_rules({"version": 1, "rules": [rule]})
        self.assertTrue(any("enabled" in e for e in errors), errors)

    # M-3: glob syntax the matcher does not support is refused instead of silently never matching
    def test_unsupported_glob_syntax_is_refused(self):
        for glob in ("src/[ab].py", "src/{a,b}.py", "./src/**", "/src/**"):
            rule = make_rule("protected_path", globs=[glob])
            errors = rule_hook.validate_rules({"version": 1, "rules": [rule]})
            self.assertTrue(any("glob" in e for e in errors), (glob, errors))

    def test_supported_globs_still_validate(self):
        rule = make_rule("protected_path", globs=["**/migrations/**", "*.env", "docs/?.md"], allow_globs=["a/*.py"])
        self.assertEqual(rule_hook.validate_rules({"version": 1, "rules": [rule]}), [])

    # M-5: a stop check cannot be given more time than the installed Stop hook has
    def test_timeout_seconds_is_capped_below_the_hook_budget(self):
        rule = make_rule("stop_check", command="true", timeout_seconds=100000)
        errors = rule_hook.validate_rules({"version": 1, "rules": [rule]})
        self.assertTrue(any("timeout_seconds" in e for e in errors), errors)
        ok = make_rule("stop_check", command="true", timeout_seconds=rule_hook.MAX_TIMEOUT)
        self.assertEqual(rule_hook.validate_rules({"version": 1, "rules": [ok]}), [])

    # M-7: the deny reason says what matched
    def test_deny_reason_includes_the_matched_detail(self):
        rule = make_rule("protected_path", id="no-env", message="Do not edit .env.", globs=["**/.env"])
        payload = pre("Edit", file_path=".env")
        out = rule_hook.decision(payload, rule, self.hit(rule, payload))
        self.assertIn(".env", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn("path: .env", out["hookSpecificOutput"]["permissionDecisionReason"])

    # M-8: very deep nesting must not make the collectors give up (and fail open)
    def test_deeply_nested_tool_input_is_still_checked(self):
        node = {"file_path": "app/migrations/1.py"}
        for _ in range(5000):
            node = {"wrapper": node}
        found = rule_hook.collect_paths(node)
        self.assertEqual(found, ["app/migrations/1.py"])
        found_text = rule_hook.collect_text({"edits": [node and {"deep": [{"new_string": "x"}] * 3}]})
        self.assertEqual(found_text, ["x", "x", "x"])


if __name__ == "__main__":
    unittest.main()
