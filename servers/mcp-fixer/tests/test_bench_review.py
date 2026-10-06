"""Regression tests from the final review of the benchmark branch."""
import json
import os
import unittest
from unittest import mock

import support  # noqa: F401
from mcp_fixer import bench, cli, runners
from mcp_fixer.runners import FakeRunner, RunnerError
from test_bench import PATCH, TOOLS, make_tasks, right_answer
from test_cli_bench import BENCH_TOOLS, FakeFactory, TasksCommandTests, bench_patch, bench_tasks, prompt_answer
from test_cli import CliCase, run

KEY = "sk-test-secret-key-123"


class ApiKeyHygieneTests(unittest.TestCase):
    def test_a_key_with_a_trailing_newline_or_cr_is_trimmed(self):
        for suffix in ("\n", "\r\n", "  "):
            with self.subTest(repr(suffix)):
                runner = runners.make_runner("api", None, env={"ANTHROPIC_API_KEY": KEY + suffix})
                self.assertEqual(runner._key, KEY)

    def test_a_key_with_inner_whitespace_or_control_characters_is_refused_without_echoing_it(self):
        for bad in ("sk-test secret", "sk-test\nsecret", "sk-te\x00st"):
            with self.subTest(repr(bad)):
                with self.assertRaises(RunnerError) as ctx:
                    runners.make_runner("api", None, env={"ANTHROPIC_API_KEY": bad})
                self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))
                self.assertNotIn("secret", str(ctx.exception))

    def test_a_runner_built_directly_with_a_bad_key_never_puts_it_in_an_error(self):
        for bad in (KEY + "\n", KEY + "\r", KEY + " x"):
            with self.subTest(repr(bad)):
                runner = runners.ApiRunner("m", bad, 2, url="http://127.0.0.1:1/ok")
                with self.assertRaises(RunnerError) as ctx:
                    runner.complete("x")
                message = str(ctx.exception)
                self.assertNotIn(KEY, message)
                self.assertNotIn("secret", message)
                self.assertNotIn("\n", message)

    def test_the_tasks_command_never_prints_a_whitespace_key(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools.json"
            tools.write_text(json.dumps(BENCH_TOOLS), encoding="utf-8")
            with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-secret\nrest"}):
                code, out, err = run("tasks", "--tools-json", str(tools), "--runner", "api")
        self.assertEqual(code, 2)
        self.assertIn("ANTHROPIC_API_KEY", err)
        self.assertNotIn("secret", err)


class ClaudeRunnerMcpTests(unittest.TestCase):
    def test_the_user_s_own_mcp_servers_are_not_loaded(self):
        import sys
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp) / "rec.json"
            command = (sys.executable, str(support.TESTS / "fake_claude.py"), "--record", str(record))
            runners.ClaudeRunner(command=command).complete("x")
            argv = json.loads(record.read_text(encoding="utf-8"))["argv"]
        self.assertIn("--strict-mcp-config", argv)


class BrokenRunnerTests(unittest.TestCase):
    def test_a_runner_that_always_fails_stops_early_and_says_why(self):
        calls = []

        def answer(prompt):
            calls.append(1)
            raise RunnerError("claude exited with code 7: not logged in")

        with self.assertRaises(bench.BenchError) as ctx:
            bench.run_bench(make_tasks(), TOOLS, PATCH, FakeRunner(answer), 3, 0, 0.05)
        message = str(ctx.exception)
        self.assertIn("not logged in", message)
        self.assertNotIn("\n", message)
        self.assertLessEqual(len(calls), 12)

    def test_a_run_where_no_call_ever_succeeds_is_an_error_even_when_short(self):
        def answer(prompt):
            raise RunnerError("boom")

        with self.assertRaises(bench.BenchError):
            bench.run_bench(make_tasks(1), TOOLS, PATCH, FakeRunner(answer), 1, 0, 0.05)

    def test_scattered_failures_do_not_stop_the_run(self):
        seen = {"n": 0}

        def answer(prompt):
            seen["n"] += 1
            if seen["n"] % 4 == 0:
                raise RunnerError("flaky")
            return right_answer(prompt)

        report = bench.run_bench(make_tasks(), TOOLS, PATCH, FakeRunner(answer), 1, 0, 0.05)
        self.assertEqual(report["tasks"], 30)


class SanityFloorTests(unittest.TestCase):
    def test_all_invalid_replies_never_look_like_no_drop(self):
        report = bench.run_bench(make_tasks(), TOOLS, PATCH, FakeRunner(lambda p: "I cannot help with that"), 1, 0, 0.05)
        self.assertEqual(report["original"]["correct"], 0)
        self.assertEqual(report["verdict"]["verdict"], "inconclusive")
        self.assertIn("never picked the right tool", report["verdict"]["reason"])

    def test_mostly_invalid_replies_are_inconclusive(self):
        import re

        def answer(prompt):
            number = int(re.search(r"User request: need-(\d+)", prompt).group(1))
            return right_answer(prompt) if number % 4 == 0 else "no idea"

        report = bench.run_bench(make_tasks(), TOOLS, PATCH, FakeRunner(answer), 1, 0, 0.05)
        self.assertEqual(report["verdict"]["verdict"], "inconclusive")
        self.assertIn("not a valid choice", report["verdict"]["reason"])

    def test_a_healthy_run_is_still_no_drop(self):
        report = bench.run_bench(make_tasks(), TOOLS, PATCH, FakeRunner(right_answer), 1, 0, 0.05)
        self.assertEqual(report["verdict"]["verdict"], "no drop detected")

    def test_a_patched_side_that_got_worse_is_still_worse(self):
        def answer(prompt):
            return "no idea" if "PATCHED-DESC" in prompt else right_answer(prompt)

        report = bench.run_bench(make_tasks(), TOOLS, PATCH, FakeRunner(answer), 1, 0, 0.05)
        self.assertEqual(report["verdict"]["verdict"], "worse")


class OutputPathTests(CliCase):
    def tools_file(self):
        return self.write("tools.json", json.dumps(BENCH_TOOLS))

    def test_tasks_with_an_unwritable_out_makes_no_model_call(self):
        factory = FakeFactory(TasksCommandTests.reply.__get__(TasksCommandTests()))
        with mock.patch.object(cli, "make_runner", factory):
            self.assert_usage_error("tasks", "--tools-json", self.tools_file(), "--out", str(self.dir / "nodir" / "t.json"), fragment="cannot write")
        self.assertEqual(factory.calls, 0)

    def test_bench_with_an_unwritable_out_makes_no_model_call(self):
        tasks = self.write("tasks.json", json.dumps(bench_tasks(4)))
        patch = self.write("patch.json", json.dumps(bench_patch()))
        factory = FakeFactory(prompt_answer)
        with mock.patch.object(cli, "make_runner", factory):
            code, out, err = run("bench", "--tasks", tasks, "--patch", patch, "--tools-json", self.tools_file(), "--out", str(self.dir / "nodir" / "r.json"))
        self.assertEqual(code, 2)
        self.assertIn("cannot write", err)
        self.assertEqual(factory.calls, 0)

    def test_an_out_that_is_a_folder_is_refused(self):
        tasks = self.write("tasks.json", json.dumps(bench_tasks(4)))
        patch = self.write("patch.json", json.dumps(bench_patch()))
        with mock.patch.object(cli, "make_runner", FakeFactory(prompt_answer)):
            code, out, err = run("bench", "--tasks", tasks, "--patch", patch, "--tools-json", self.tools_file(), "--out", str(self.dir))
        self.assertEqual(code, 2)
        self.assertIn("cannot write", err)

    def test_a_write_that_fails_after_the_calls_still_shows_the_result(self):
        tasks = self.write("tasks.json", json.dumps(bench_tasks(4)))
        patch = self.write("patch.json", json.dumps(bench_patch()))
        out_file = str(self.dir / "r.json")
        with mock.patch.object(cli, "make_runner", FakeFactory(prompt_answer)), mock.patch.object(
            cli, "write_file", side_effect=cli.UsageError("cannot write r.json: disk full")
        ):
            code, out, err = run("bench", "--tasks", tasks, "--patch", patch, "--tools-json", self.tools_file(), "--out", out_file)
        self.assertEqual(code, 2)
        self.assertIn("disk full", err)
        self.assertTrue(out.startswith("mcp-fixer bench:"))


if __name__ == "__main__":
    unittest.main()
