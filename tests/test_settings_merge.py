import contextlib
import io
import json
import os
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


class ReviewFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / ".claude" / "settings.json"
        self.path.parent.mkdir(parents=True)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sm.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    # I1: plan must not crash on characters a narrow console encoding cannot print
    def test_plan_with_non_cp1252_text_does_not_crash(self):
        self.path.write_text(
            json.dumps({"statusLine": {"command": "echo \U0001f680 日本語"}}, ensure_ascii=False),
            encoding="utf-8",
        )
        buf = io.BytesIO()
        narrow = io.TextIOWrapper(buf, encoding="cp1252", write_through=True)
        err = io.StringIO()
        with mock.patch("sys.stdout", narrow), contextlib.redirect_stderr(err):
            code = sm.main(["plan", "--settings", str(self.path), "--launcher", "python3", "--pretool"])
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("\U0001f680".encode("utf-8"), buf.getvalue())

    # I2: the diff is against the raw file, and duplicate keys are refused rather than dropped
    def test_plan_diff_is_against_the_raw_file(self):
        self.path.write_bytes('{\r\n    "model": "x"\r\n}\r\n'.encode("utf-8"))
        code, out, _ = self.run_cli("plan", "--settings", str(self.path), "--launcher", "python3", "--pretool")
        self.assertEqual(code, 0)
        self.assertIn('-    "model": "x"', out)  # the original 4-space line is shown as removed
        self.assertIn('+  "model": "x"', out)    # and the reformatted line as added

    def test_duplicate_keys_are_refused_and_nothing_is_written(self):
        original = '{"model": "a", "model": "b"}'
        self.path.write_text(original, encoding="utf-8")
        for command in ("plan", "apply"):
            code, _, err = self.run_cli(command, "--settings", str(self.path), "--launcher", "python3", "--pretool")
            self.assertEqual(code, 2)
            self.assertIn("duplicate", err)
        self.assertEqual(self.path.read_text(encoding="utf-8"), original)

    # I3: only our own entries are removed, never other people's hooks
    def test_only_our_entries_are_removed(self):
        ours = {"type": "command", "command": "python3",
                "args": ["${CLAUDE_PROJECT_DIR}/.claude/hooks/rule_hook.py", "check"]}
        mixed = {"hooks": {
            "PreToolUse": [{"hooks": [{"type": "command", "command": "./audit.sh"}, ours]}],
            "PostToolUse": [{"matcher": "Bash", "if": "Bash(git *)", "hooks": [
                {"type": "command", "command": "python", "args": ["~/other/rule_hook.py", "--audit"]},
                {"type": "command", "command": "node ~/tools/eslint_rule_hook.py.js"}]}],
        }}
        merged = sm.merge(mixed, sm.build_groups(["python3"], True, False))
        pre = merged["hooks"]["PreToolUse"]
        self.assertIn("./audit.sh", [h["command"] for g in pre for h in g["hooks"]])
        ours_count = sum(1 for g in pre for h in g["hooks"] if ".claude/hooks/rule_hook.py" in " ".join(h.get("args", [])))
        self.assertEqual(ours_count, 1)  # only the freshly written one
        self.assertEqual(merged["hooks"]["PostToolUse"], mixed["hooks"]["PostToolUse"])

    def test_group_with_null_hooks_is_refused(self):
        with self.assertRaises(sm.SettingsError):
            sm.merge({"hooks": {"PreToolUse": [{"hooks": None}]}}, {})

    # I6: a shell-form fallback for Claude Code versions without exec-form args
    def test_shell_form_entries(self):
        hook = sm.build_groups(["python3"], True, False, shell_form=True)["PreToolUse"][0]["hooks"][0]
        self.assertEqual(hook["command"], 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/rule_hook.py" check')
        self.assertNotIn("args", hook)
        py = sm.build_groups(["py", "-3"], True, False, shell_form=True)["PreToolUse"][0]["hooks"][0]
        self.assertTrue(py["command"].startswith('py -3 "$CLAUDE_PROJECT_DIR'))

    def test_rerun_converts_between_forms_without_duplicates(self):
        exec_form = sm.merge({}, sm.build_groups(["python3"], True, False))
        shell_form = sm.merge(exec_form, sm.build_groups(["python3"], True, False, shell_form=True))
        self.assertEqual(len(shell_form["hooks"]["PreToolUse"]), 1)
        self.assertNotIn("args", shell_form["hooks"]["PreToolUse"][0]["hooks"][0])

    def test_cli_accepts_shell_form(self):
        code, _, _ = self.run_cli("apply", "--settings", str(self.path), "--launcher", "python3", "--pretool", "--shell-form")
        self.assertEqual(code, 0)
        hook = json.loads(self.path.read_text(encoding="utf-8"))["hooks"]["PreToolUse"][0]["hooks"][0]
        self.assertIn("$CLAUDE_PROJECT_DIR", hook["command"])


class DeferredMinorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / ".claude" / "settings.json"
        self.path.parent.mkdir(parents=True)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sm.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    # M1: a Windows launcher path keeps its backslashes and its quoted spaces
    def test_launcher_with_windows_path_is_split_correctly(self):
        self.assertEqual(sm.split_launcher(r'"C:\Program Files\Python312\python.exe"', windows=True),
                         [r"C:\Program Files\Python312\python.exe"])
        self.assertEqual(sm.split_launcher(r"C:\Python312\python.exe -u", windows=True),
                         [r"C:\Python312\python.exe", "-u"])
        self.assertEqual(sm.split_launcher("py -3", windows=True), ["py", "-3"])
        self.assertEqual(sm.split_launcher("'/opt/my python/bin/python3'", windows=False),
                         ["/opt/my python/bin/python3"])

    # M3: a write failure is a clean error, not a traceback
    def test_write_failure_is_a_clean_error(self):
        with mock.patch.object(sm.os, "replace", side_effect=PermissionError("locked")):
            code, _, err = self.run_cli("apply", "--settings", str(self.path), "--launcher", "python3", "--pretool")
        self.assertEqual(code, 2)
        self.assertIn("error:", err)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], [])  # no temp file left behind

    # M4: the file's permissions and a symlinked settings file survive the atomic write
    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_file_mode_is_preserved(self):
        self.path.write_text("{}", encoding="utf-8")
        os.chmod(self.path, 0o640)
        sm.apply(self.path, ["python3"], True, False)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o640)

    def test_symlinked_settings_file_is_written_through(self):
        real = Path(self.tmp.name) / "shared-settings.json"
        real.write_text("{}", encoding="utf-8")
        try:
            os.symlink(real, self.path)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create a symlink here")
        sm.apply(self.path, ["python3"], True, False)
        self.assertTrue(self.path.is_symlink())
        self.assertIn("rule_hook.py", real.read_text(encoding="utf-8"))



class StrictJsonHintTests(unittest.TestCase):
    def test_comment_in_settings_explains_that_claude_code_rejects_it_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "settings.json")
            path.write_text('{\n  // keep me\n  "model": "opus"\n}\n', encoding="utf-8")
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = sm.main(["plan", "--settings", str(path), "--launcher", "python3", "--pretool"])
            self.assertEqual(code, 2)
            self.assertIn("strict JSON", err.getvalue())
            self.assertIn("comments", err.getvalue())


if __name__ == "__main__":
    unittest.main()
