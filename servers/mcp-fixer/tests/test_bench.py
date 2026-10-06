import json
import re
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from mcp_fixer import bench, patch_format
from mcp_fixer.runners import FakeRunner, RunnerError

TOOLS = [
    {"name": "run", "description": "Runs it", "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}}},
    {"name": "search_items", "description": "Search the item catalog by keyword", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_item", "description": "Fetch one item by id", "inputSchema": {"type": "object", "properties": {}}},
]
MARK = "PATCHED-DESC"
PATCH = {
    "patchVersion": 1,
    "tools": {
        "run": {
            "base": patch_format.fingerprint(TOOLS[0]),
            "rename": "search_orders",
            "description": "Search orders by status " + MARK,
        }
    },
}
NAMES = [t["name"] for t in TOOLS]


def make_tasks(count=30):
    tasks = [
        {"id": f"t{i:03d}", "request": f"need-{i}", "expected": NAMES[i % 3]}
        for i in range(count)
    ]
    return {"tasksVersion": 1, "tasks": tasks}


def expected_for(prompt):
    request = re.search(r"User request: (need-\d+)", prompt).group(1)
    index = int(request.split("-")[1])
    return NAMES[index % 3]


def shown_names(prompt):
    return re.findall(r"^- (\S+?)(?::|$)", prompt, re.MULTILINE)


def right_answer(prompt):
    """The correct tool, under whatever name this prompt shows for it."""
    expected = expected_for(prompt)
    shown = shown_names(prompt)
    if expected not in shown and expected == "run":
        expected = "search_orders"
    return json.dumps({"tool": expected})


class ValidateTasksTests(unittest.TestCase):
    def assert_invalid(self, data, fragment):
        with self.assertRaises(bench.TasksError) as ctx:
            bench.validate_tasks(data)
        self.assertIn(fragment, str(ctx.exception))
        self.assertNotIn("\n", str(ctx.exception))

    def test_a_valid_file_passes(self):
        data = make_tasks(2)
        data["source"] = {"serverName": "s"}
        self.assertIs(bench.validate_tasks(data), data)

    def test_problems(self):
        good = make_tasks(1)["tasks"][0]
        cases = [
            ([], "must be a JSON object"),
            ({"tasksVersion": 1, "tasks": [good], "x": 1}, "unknown field 'x'"),
            ({"tasksVersion": 2, "tasks": [good]}, "tasksVersion must be 1"),
            ({"tasksVersion": True, "tasks": [good]}, "tasksVersion must be 1"),
            ({"tasksVersion": 1, "tasks": []}, "tasks must be a non-empty list"),
            ({"tasksVersion": 1}, "tasks must be a non-empty list"),
            ({"tasksVersion": 1, "tasks": [good], "source": []}, "source must be an object"),
            ({"tasksVersion": 1, "tasks": ["x"]}, "task 0: must be an object"),
            ({"tasksVersion": 1, "tasks": [dict(good, extra=1)]}, "task 0: unknown field 'extra'"),
            ({"tasksVersion": 1, "tasks": [dict(good, request="  ")]}, "task 0: request must be a non-empty string"),
            ({"tasksVersion": 1, "tasks": [dict(good, id=5)]}, "task 0: id must be a non-empty string"),
            ({"tasksVersion": 1, "tasks": [dict(good, expected="")]}, "task 0: expected must be a non-empty string"),
            ({"tasksVersion": 1, "tasks": [good, good]}, "task 1: duplicate id"),
        ]
        for data, fragment in cases:
            with self.subTest(fragment):
                self.assert_invalid(data, fragment)

    def test_load_tasks_gives_one_line_errors_with_the_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.json").write_text("{nope", encoding="utf-8")
            (root / "deep.json").write_text("[" * 5000, encoding="utf-8")
            (root / "bytes.json").write_bytes(b"\x80\x81")
            (root / "ok.json").write_text(json.dumps(make_tasks(1)), encoding="utf-8")
            cases = {"nope.json": "cannot read", "bad.json": "not valid JSON", "deep.json": "nested too deeply", "bytes.json": "not UTF-8"}
            for name, fragment in cases.items():
                with self.subTest(name):
                    with self.assertRaises(bench.TasksError) as ctx:
                        bench.load_tasks(str(root / name))
                    self.assertIn(fragment, str(ctx.exception))
                    self.assertIn(name, str(ctx.exception))
                    self.assertNotIn("\n", str(ctx.exception))
            self.assertEqual(len(bench.load_tasks(str(root / "ok.json"))["tasks"]), 1)


class ToolsTests(unittest.TestCase):
    def test_valid_tools_keeps_the_first_of_each_name(self):
        tools = ["junk", {"name": ""}, {"name": "a", "description": "first"}, {"name": "a", "description": "second"}, {"name": "b"}]
        self.assertEqual(bench.valid_tools(tools), [{"name": "a", "description": "first"}, {"name": "b"}])

    def test_the_fingerprint_ignores_junk_and_duplicates(self):
        self.assertEqual(
            bench.tools_fingerprint(TOOLS),
            bench.tools_fingerprint(["junk"] + TOOLS + [dict(TOOLS[0], description="dup")]),
        )

    def test_check_tasks(self):
        self.assertEqual(bench.check_tasks(make_tasks(3), TOOLS), [])
        data = make_tasks(2)
        data["source"] = {"toolsFingerprint": "0" * 64}
        warnings = bench.check_tasks(data, TOOLS)
        self.assertEqual(len(warnings), 1)
        self.assertIn("different tools", warnings[0])
        data = make_tasks(2)
        data["tasks"][1]["expected"] = "ghost"
        with self.assertRaises(bench.BenchError) as ctx:
            bench.check_tasks(data, TOOLS)
        self.assertIn("'t001' expects 'ghost'", str(ctx.exception))
        with self.assertRaises(bench.BenchError):
            bench.check_tasks(make_tasks(1), ["junk"])

    def test_control_characters_in_error_messages_are_escaped(self):
        data = make_tasks(1)
        data["tasks"][0]["expected"] = "ghost\x1b[2J"
        with self.assertRaises(bench.BenchError) as ctx:
            bench.check_tasks(data, TOOLS)
        self.assertNotIn("\x1b", str(ctx.exception))


class PatchedViewTests(unittest.TestCase):
    def test_the_patch_is_applied_the_way_wrap_does(self):
        patched, back, warnings = bench.patched_view(TOOLS, PATCH)
        self.assertEqual([t["name"] for t in patched], ["search_orders", "search_items", "get_item"])
        self.assertIn(MARK, patched[0]["description"])
        self.assertEqual(back, {"search_orders": "run"})
        self.assertEqual(warnings, [])

    def test_a_stale_entry_is_not_applied(self):
        stale = json.loads(json.dumps(PATCH))
        stale["tools"]["run"]["base"] = "0" * 64
        patched, back, warnings = bench.patched_view(TOOLS, stale)
        self.assertEqual(patched, TOOLS)
        self.assertEqual(back, {})
        self.assertEqual(len(warnings), 1)

    def test_an_empty_patch_changes_nothing(self):
        patched, back, _ = bench.patched_view(TOOLS, {"patchVersion": 1, "tools": {}})
        self.assertEqual((patched, back), (TOOLS, {}))


class RunBenchTests(unittest.TestCase):
    def run_bench(self, function, tasks=None, patch=PATCH, repeats=1, seed=0, tolerance=0.05):
        runner = FakeRunner(function, "fake")
        return bench.run_bench(tasks or make_tasks(), TOOLS, patch, runner, repeats, seed, tolerance)

    def test_a_runner_that_is_always_right_shows_no_drop(self):
        report = self.run_bench(right_answer)
        self.assertEqual(report["original"]["accuracy"], 1.0)
        self.assertEqual(report["patched"]["accuracy"], 1.0)
        self.assertEqual(report["verdict"]["verdict"], "no drop detected")
        self.assertEqual(report["paired"]["mean"], 0.0)
        self.assertEqual(report["modelCalls"], 60)
        self.assertEqual(report["patch"], {"entries": 1, "applied": 1, "stale": 0, "missing": 0})

    def test_the_renamed_tool_answer_is_mapped_back(self):
        # Every third task expects `run`; the patched side names it search_orders.
        report = self.run_bench(right_answer)
        self.assertEqual(report["patched"]["wrong"], 0)

    def test_a_runner_that_fails_on_the_patched_list_is_worse(self):
        def answer(prompt):
            return '{"tool": "get_item"}' if MARK in prompt and expected_for(prompt) != "get_item" else right_answer(prompt)

        report = self.run_bench(answer)
        self.assertEqual(report["verdict"]["verdict"], "worse")
        self.assertLess(report["patched"]["accuracy"], report["original"]["accuracy"])
        self.assertLess(report["paired"]["high"], 0)

    def test_a_stale_patch_is_counted_and_not_applied(self):
        stale = json.loads(json.dumps(PATCH))
        stale["tools"]["run"]["base"] = "0" * 64
        prompts = []
        report = self.run_bench(lambda p: (prompts.append(p), right_answer(p))[1], patch=stale)
        self.assertEqual(report["patch"]["stale"], 1)
        self.assertEqual(report["patch"]["applied"], 0)
        self.assertFalse(any(MARK in p for p in prompts))

    def test_both_sides_see_the_same_order_and_it_is_seeded(self):
        def collect(seed):
            prompts = []
            self.run_bench(lambda p: (prompts.append(p), right_answer(p))[1], seed=seed, repeats=2)
            return prompts

        first = collect(0)
        self.assertEqual(first, collect(0))
        self.assertNotEqual(first, collect(1))
        for original, patched in zip(first[0::2], first[1::2]):
            order = [("run" if n == "search_orders" else n) for n in shown_names(patched)]
            self.assertEqual(order, shown_names(original))

    def test_invalid_replies_count_as_wrong_and_errored_are_excluded(self):
        def answer(prompt):
            if re.search(r"User request: need-0\b", prompt):
                return "I refuse to answer"
            if re.search(r"User request: need-1\b", prompt):
                raise RunnerError("boom")
            return right_answer(prompt)

        report = self.run_bench(answer)
        # need-0 invalid on both sides; need-1 errored on both sides (after the retry).
        self.assertEqual(report["original"]["invalid"], 1)
        self.assertEqual(report["original"]["errored"], 1)
        self.assertEqual(report["patched"]["invalid"], 1)
        self.assertEqual(report["patched"]["errored"], 1)
        scored = 30 - 1
        self.assertAlmostEqual(report["original"]["accuracy"], (scored - 1) / scored)
        self.assertEqual(report["usableTasks"], 29)
        self.assertEqual(report["droppedTasks"], 1)
        self.assertEqual(report["verdict"]["verdict"], "inconclusive")  # 29 usable tasks
        self.assertTrue(any("errored" in note for note in report["notes"]))
        # Each errored trial was tried twice: 60 trials + 2 retries.
        self.assertEqual(report["modelCalls"], 62)

    def test_a_failure_that_succeeds_on_the_retry_is_not_errored(self):
        seen = set()

        def answer(prompt):
            if prompt not in seen:
                seen.add(prompt)
                raise RunnerError("flaky")
            return right_answer(prompt)

        report = self.run_bench(answer)
        self.assertEqual(report["original"]["errored"], 0)
        self.assertEqual(report["modelCalls"], 120)

    def test_the_report_is_json_serializable_and_complete(self):
        report = self.run_bench(right_answer)
        data = json.loads(bench.render_bench_json(report))
        self.assertEqual(data["schemaVersion"], 1)
        for key in ("runner", "seed", "repeats", "tolerance", "tasks", "usableTasks", "original", "patched", "paired", "tokens", "patch", "verdict", "notes", "disclaimer"):
            self.assertIn(key, data)
        self.assertEqual(data["disclaimer"], bench.DISCLAIMER)
        self.assertIn("original", data["tokens"])

    def test_the_text_report_has_the_verdict_the_numbers_and_the_disclaimer(self):
        text = bench.render_bench_text(self.run_bench(right_answer))
        self.assertTrue(text.startswith("mcp-fixer bench: no drop detected"))
        self.assertIn("original", text)
        self.assertIn("patched", text)
        self.assertIn("paired difference", text)
        self.assertTrue(text.rstrip().endswith(bench.DISCLAIMER))

    def test_untrusted_text_is_escaped_in_the_text_report(self):
        evil = "evil\x1b[2J"
        tools = TOOLS + [{"name": evil, "description": "d", "inputSchema": {"type": "object", "properties": {}}}]
        patch = {"patchVersion": 1, "tools": {evil: {"params": {"ghost": {"type": "string"}}}}}
        runner = FakeRunner(right_answer)
        report = bench.run_bench(make_tasks(3), tools, patch, runner, 1, 0, 0.05)
        text = bench.render_bench_text(report)
        self.assertNotIn("\x1b", text)
        self.assertIn("evil", text)

    def test_estimates(self):
        self.assertEqual(bench.estimate_calls(make_tasks(10), 3), 60)
        self.assertGreater(bench.estimate_input_tokens(make_tasks(10), TOOLS, PATCH, 3), 0)


class GenerateTasksTests(unittest.TestCase):
    WORDS = {"search_items": "alpha", "get_item": "beta", "run": "gamma"}

    def reply(self, prompt):
        target = re.search(r'need the tool "([^"]+)"', prompt).group(1)
        word = self.WORDS[target]
        return json.dumps([f"{word} thing one", f"{word} thing two", f"{word} thing one"])

    def test_tasks_are_generated_per_tool_in_order(self):
        logs = []
        data = bench.generate_tasks(TOOLS, FakeRunner(self.reply), 3, None, logs.append)
        bench.validate_tasks(data)
        ids = [t["id"] for t in data["tasks"]]
        self.assertEqual(ids, [f"t{i:03d}" for i in range(1, 7)])
        self.assertEqual([t["expected"] for t in data["tasks"]], ["run", "run", "search_items", "search_items", "get_item", "get_item"])
        self.assertEqual(data["source"]["toolsFingerprint"], bench.tools_fingerprint(TOOLS))
        self.assertEqual(logs, [])

    def test_requests_that_name_the_tool_are_dropped(self):
        def reply(prompt):
            return json.dumps(["please use get item now", "find the beta thing"])

        data = bench.generate_tasks([TOOLS[2]], FakeRunner(reply), 3, None, lambda t: None)
        self.assertEqual([t["request"] for t in data["tasks"]], ["find the beta thing"])

    def test_a_tool_with_an_unusable_reply_is_skipped_with_a_warning(self):
        def reply(prompt):
            return "nonsense" if 'need the tool "get_item"' in prompt else self.reply(prompt)

        logs = []
        data = bench.generate_tasks(TOOLS, FakeRunner(reply), 3, None, logs.append)
        self.assertNotIn("get_item", [t["expected"] for t in data["tasks"]])
        self.assertEqual(len(logs), 1)
        self.assertIn("get_item", logs[0])

    def test_a_runner_failure_is_retried_once_then_the_tool_is_skipped(self):
        attempts = []

        def reply(prompt):
            if 'need the tool "run"' in prompt:
                attempts.append(1)
                raise RunnerError("boom")
            return self.reply(prompt)

        logs = []
        data = bench.generate_tasks(TOOLS, FakeRunner(reply), 3, None, logs.append)
        self.assertEqual(len(attempts), 2)
        self.assertNotIn("run", [t["expected"] for t in data["tasks"]])
        self.assertTrue(any("run" in line and "boom" in line for line in logs))

    def test_no_tasks_at_all_is_an_error(self):
        with self.assertRaises(bench.TasksError):
            bench.generate_tasks(TOOLS, FakeRunner(lambda p: "nonsense"), 3, None, lambda t: None)
        with self.assertRaises(bench.TasksError):
            bench.generate_tasks(["junk"], FakeRunner(self.reply), 3, None, lambda t: None)

    def test_only_the_per_tool_count_is_kept(self):
        data = bench.generate_tasks([TOOLS[1]], FakeRunner(self.reply), 1, None, lambda t: None)
        self.assertEqual(len(data["tasks"]), 1)

    def test_a_stdio_source_is_recorded(self):
        source = {"kind": "stdio", "serverName": "s", "serverVersion": "1"}
        data = bench.generate_tasks(TOOLS, FakeRunner(self.reply), 2, source, lambda t: None)
        self.assertEqual(data["source"]["serverName"], "s")
        self.assertEqual(data["source"]["serverVersion"], "1")

    def test_output_is_deterministic(self):
        a = bench.render_tasks(bench.generate_tasks(TOOLS, FakeRunner(self.reply), 2, None, lambda t: None))
        b = bench.render_tasks(bench.generate_tasks(TOOLS, FakeRunner(self.reply), 2, None, lambda t: None))
        self.assertEqual(a, b)
        self.assertTrue(a.endswith("}\n"))


if __name__ == "__main__":
    unittest.main()
