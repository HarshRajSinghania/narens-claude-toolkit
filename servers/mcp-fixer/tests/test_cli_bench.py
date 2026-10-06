"""Command-line tests for `mcp-fixer tasks` and `mcp-fixer bench` (no real model is called)."""
import json
import os
import re
import unittest
from unittest import mock

import support  # noqa: F401
from mcp_fixer import bench, cli, patch_format
from mcp_fixer.runners import FakeRunner
from test_cli import CliCase, run

BENCH_TOOLS = [
    {"name": "search_items", "description": "Search the item catalog by keyword", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_item", "description": "Fetch one item by id", "inputSchema": {"type": "object", "properties": {}}},
]
BENCH_MARK = "PATCHED-DESC"


def bench_patch():
    return {
        "patchVersion": 1,
        "tools": {"get_item": {"base": patch_format.fingerprint(BENCH_TOOLS[1]), "description": "Fetch one item " + BENCH_MARK}},
    }


def bench_tasks(count):
    return {
        "tasksVersion": 1,
        "tasks": [
            {"id": f"t{i:03d}", "request": f"need {BENCH_TOOLS[i % 2]['name']} {i}", "expected": BENCH_TOOLS[i % 2]["name"]}
            for i in range(count)
        ],
    }


def prompt_answer(prompt, break_patched=False):
    expected = re.search(r"User request: need (\S+) \d+", prompt).group(1)
    if break_patched and BENCH_MARK in prompt:
        return '{"tool": "nope"}'
    return json.dumps({"tool": expected})


class FakeFactory:
    """Stands in for runners.make_runner; counts the model calls."""

    def __init__(self, function):
        self.function = function
        self.calls = 0

    def __call__(self, name, model=None, env=None, timeout=120, max_tokens=64):
        def counted(prompt):
            self.calls += 1
            return self.function(prompt)

        return FakeRunner(counted, f"fake:{name}")


class TasksCommandTests(CliCase):
    WORDS = {"search_items": "alpha", "get_item": "beta"}

    def reply(self, prompt):
        target = re.search(r'need the tool "([^"]+)"', prompt).group(1)
        return json.dumps([f"{self.WORDS[target]} thing one", f"{self.WORDS[target]} thing two"])

    def tools_file(self):
        return self.write("tools.json", json.dumps(BENCH_TOOLS))

    def test_tasks_are_written_to_stdout_and_validate(self):
        factory = FakeFactory(self.reply)
        with mock.patch.object(cli, "make_runner", factory):
            code, out, err = run("tasks", "--tools-json", self.tools_file())
        self.assertEqual((code, err), (0, ""))
        data = bench.validate_tasks(json.loads(out))
        self.assertEqual(len(data["tasks"]), 4)
        self.assertEqual(factory.calls, 2)

    def test_out_writes_a_file_and_an_existing_file_is_refused_before_any_call(self):
        target = self.dir / "tasks.json"
        target.write_text("my edits", encoding="utf-8")
        factory = FakeFactory(self.reply)
        with mock.patch.object(cli, "make_runner", factory):
            self.assert_usage_error("tasks", "--tools-json", self.tools_file(), "--out", str(target), fragment="exists; use --force")
        self.assertEqual(factory.calls, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), "my edits")
        with mock.patch.object(cli, "make_runner", factory):
            code, out, _ = run("tasks", "--tools-json", self.tools_file(), "--out", str(target), "--force")
        self.assertEqual((code, out), (0, ""))
        self.assertIn('"tasksVersion"', target.read_text(encoding="utf-8"))

    def test_per_tool_bounds(self):
        for value in ("0", "11", "-1"):
            with self.subTest(value):
                self.assert_usage_error("tasks", "--tools-json", self.tools_file(), "--per-tool", value, fragment="--per-tool")

    def test_a_failed_tool_is_a_warning_and_no_tasks_is_an_error(self):
        def reply(prompt):
            return "nonsense" if 'need the tool "get_item"' in prompt else self.reply(prompt)

        with mock.patch.object(cli, "make_runner", FakeFactory(reply)):
            code, out, err = run("tasks", "--tools-json", self.tools_file())
        self.assertEqual(code, 0)
        self.assertEqual(err.count("get_item"), 1)
        with mock.patch.object(cli, "make_runner", FakeFactory(lambda p: "nonsense")):
            code, out, err = run("tasks", "--tools-json", self.tools_file())
        self.assertEqual((code, out), (2, ""))
        self.assertTrue(err.endswith("error: no tasks could be generated\n"), err)
        self.assertNotIn("Traceback", err)

    def test_a_missing_api_key_fails_before_any_call(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            self.assert_usage_error("tasks", "--tools-json", self.tools_file(), "--runner", "api", fragment="ANTHROPIC_API_KEY")

    def test_the_same_input_errors_as_patch(self):
        self.assert_usage_error("tasks", fragment="--tools-json")
        self.assert_usage_error("tasks", "--tools-json", str(self.dir / "nope.json"), fragment="cannot read")


class BenchCommandTests(CliCase):
    def files(self, tasks=None, patch=None, tools=None):
        return (
            self.write("tools.json", json.dumps(tools if tools is not None else BENCH_TOOLS)),
            self.write("patch.json", json.dumps(patch if patch is not None else bench_patch())),
            self.write("tasks.json", json.dumps(tasks if tasks is not None else bench_tasks(30))),
        )

    def bench(self, factory, *extra, **files):
        tools, patch, tasks = self.files(**files)
        with mock.patch.object(cli, "make_runner", factory):
            return run("bench", "--tasks", tasks, "--patch", patch, "--tools-json", tools, "--repeats", "1", *extra)

    def test_no_drop_is_exit_0_and_the_text_report(self):
        factory = FakeFactory(prompt_answer)
        code, out, err = self.bench(factory)
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("mcp-fixer bench: no drop detected"))
        self.assertEqual(factory.calls, 60)
        self.assertIn("60 model calls", err)

    def test_worse_is_exit_1(self):
        code, out, err = self.bench(FakeFactory(lambda p: prompt_answer(p, break_patched=True)))
        self.assertEqual(code, 1, err)
        self.assertTrue(out.startswith("mcp-fixer bench: worse"))

    def test_too_few_tasks_is_inconclusive_exit_0(self):
        code, out, _ = self.bench(FakeFactory(prompt_answer), tasks=bench_tasks(4))
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("mcp-fixer bench: inconclusive"))

    def test_json_format_and_out(self):
        target = self.dir / "report.json"
        code, out, _ = self.bench(FakeFactory(prompt_answer), "--format", "json", "--out", str(target))
        self.assertEqual((code, out), (0, ""))
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["schemaVersion"], 1)

    def test_more_than_200_calls_need_yes_and_no_call_is_made_without_it(self):
        factory = FakeFactory(prompt_answer)
        code, out, err = self.bench(factory, tasks=bench_tasks(101))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("--yes", err)
        self.assertNotIn("Traceback", err)
        self.assertEqual(factory.calls, 0)
        factory = FakeFactory(prompt_answer)
        code, _, err = self.bench(factory, "--yes", tasks=bench_tasks(101))
        self.assertEqual(code, 0, err)
        self.assertEqual(factory.calls, 202)

    def test_an_expected_tool_that_does_not_exist_is_one_line(self):
        tasks = bench_tasks(3)
        tasks["tasks"][1]["expected"] = "ghost"
        factory = FakeFactory(prompt_answer)
        code, out, err = self.bench(factory, tasks=tasks)
        self.assertEqual(code, 2)
        self.assertIn("'t001' expects 'ghost'", err)
        self.assertEqual(factory.calls, 0)

    def test_tasks_for_different_tools_only_warn(self):
        tasks = bench_tasks(30)
        tasks["source"] = {"toolsFingerprint": "0" * 64}
        code, out, err = self.bench(FakeFactory(prompt_answer), tasks=tasks)
        self.assertEqual(code, 0)
        self.assertEqual(err.count("different tools"), 1)

    def test_bad_inputs_are_usage_errors(self):
        tools, patch, tasks = self.files()
        bad = self.write("bad.json", "{nope")
        factory = FakeFactory(prompt_answer)
        with mock.patch.object(cli, "make_runner", factory):
            for argv, fragment in (
                (("bench", "--patch", patch, "--tools-json", tools), "--tasks"),
                (("bench", "--tasks", tasks, "--tools-json", tools), "--patch"),
                (("bench", "--tasks", bad, "--patch", patch, "--tools-json", tools), "not valid JSON"),
                (("bench", "--tasks", tasks, "--patch", bad, "--tools-json", tools), "not valid JSON"),
                (("bench", "--tasks", tasks, "--patch", patch, "--tools-json", tools, "--repeats", "0"), "--repeats"),
                (("bench", "--tasks", tasks, "--patch", patch, "--tools-json", tools, "--tolerance", "nan"), "--tolerance"),
                (("bench", "--tasks", tasks, "--patch", patch, "--tools-json", tools, "--tolerance", "-1"), "--tolerance"),
                (("bench", "--tasks", tasks, "--patch", patch), "--tools-json"),
            ):
                with self.subTest(fragment):
                    code, out, err = run(*argv)
                    self.assertEqual(code, 2, (out, err))
                    self.assertIn(fragment, err)
                    self.assertNotIn("Traceback", err)
        self.assertEqual(factory.calls, 0)

    def test_a_missing_api_key_fails_before_any_call(self):
        tools, patch, tasks = self.files()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            code, out, err = run("bench", "--tasks", tasks, "--patch", patch, "--tools-json", tools, "--runner", "api")
        self.assertEqual(code, 2)
        self.assertIn("ANTHROPIC_API_KEY", err)

    def test_control_characters_never_reach_the_terminal(self):
        evil = "evil\x1b[2J"
        tools = [dict(BENCH_TOOLS[0]), dict(BENCH_TOOLS[1]), {"name": evil, "description": "d", "inputSchema": {"type": "object", "properties": {}}}]
        patch = {"patchVersion": 1, "tools": {evil: {"params": {"ghost": {"type": "string"}}}}}
        code, out, err = self.bench(FakeFactory(prompt_answer), tools=tools, patch=patch)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x1b", err)
        self.assertIn("evil", out)


if __name__ == "__main__":
    unittest.main()
