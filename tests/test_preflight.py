import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import helpers

sys.path.insert(
    0,
    str(helpers.REPO_ROOT / "plugins" / "schedule-doctor" / "skills" / "schedule-doctor" / "scripts"),
)
import preflight  # noqa: E402


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = preflight.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def tool_names(text):
    return [t["tool"] for t in preflight.analyze(text)["tools"]]


def tool(text, name):
    return next(t for t in preflight.analyze(text)["tools"] if t["tool"] == name)


class ToolTests(unittest.TestCase):
    def test_each_kind_of_tool_is_detected(self):
        cases = {
            "Run npm test and report failures.": "Bash",
            "Then git push the branch.": "Bash(git push)",
            "Use mcp__github__create_issue to file it.": "mcp__github__create_issue",
            "Fetch https://example.com/feed and summarise.": "WebFetch/WebSearch",
            "Save the summary to notes.md": "Write/Edit",
            "Deploy the site when tests pass.": "External send or deploy",
            "Delete the old files.": "Bash(destructive)",
        }
        for text, expected in cases.items():
            with self.subTest(text):
                self.assertIn(expected, tool_names(text))

    def test_advice_pre_approve_versus_approve_once(self):
        self.assertEqual(tool("Run npm test.", "Bash")["advice"], preflight.PRE_APPROVE)
        self.assertEqual(
            tool("git push the branch", "Bash(git push)")["advice"], preflight.APPROVE_ONCE
        )
        self.assertEqual(
            tool("Delete the old files.", "Bash(destructive)")["advice"], preflight.APPROVE_ONCE
        )

    def test_plain_prompt_needs_no_tools(self):
        self.assertEqual(tool_names("Summarise what I should focus on."), [])

    def test_the_verb_make_is_not_the_make_command(self):
        self.assertEqual(tool_names("Make a short summary of my notes."), [])
        self.assertIn("Bash", tool_names("Then make build and check the output."))

    def test_matched_snippets_are_capped_and_not_repeated(self):
        found = tool("npm npm\nNPM pip pytest\ndocker npm", "Bash")
        self.assertEqual(len(found["matched"]), 3)
        self.assertEqual(len({m.lower() for m in found["matched"]}), 3)

    def test_lines_are_reported_once_each(self):
        found = tool("Intro\nrun npm test\nthen npm run build", "Bash")
        self.assertEqual(found["lines"], [2, 3])

    def test_a_long_url_is_cut_to_a_short_snippet(self):
        found = tool("Fetch https://example.com/" + "a" * 200, "WebFetch/WebSearch")
        self.assertTrue(all(len(m) <= preflight.MAX_SNIPPET for m in found["matched"]))


class GuardTests(unittest.TestCase):
    def guard(self, text, hours=2.0):
        return preflight.analyze(text, hours)["time_guard"]

    def test_existing_guards_are_recognised(self):
        cases = [
            "If it's after 5pm, skip this run.",
            "Skip this run if more than 2 hours late.",
            "Only run if it is before noon.",
            "Do nothing when it is too late to matter.",
        ]
        for text in cases:
            with self.subTest(text):
                guard = self.guard(text)
                self.assertTrue(guard["present"])
                self.assertIsNone(guard["snippet"])
                self.assertEqual(guard["line"], 1)

    def test_a_bare_skip_is_not_a_guard(self):
        guard = self.guard("Skip the intro and summarise the news.")
        self.assertFalse(guard["present"])
        self.assertIn("compare the current time", guard["snippet"])

    def test_snippet_uses_the_hours_given(self):
        self.assertIn("more than 3 hours", self.guard("Summarise it.", 3)["snippet"])
        self.assertIn("more than 1.5 hours", self.guard("Summarise it.", 1.5)["snippet"])

    def test_guard_on_a_later_line_reports_that_line(self):
        self.assertEqual(self.guard("Summarise.\n\nIf it's after 5pm, skip.")["line"], 3)


class StalenessTests(unittest.TestCase):
    def test_time_relative_phrases_are_listed_with_lines(self):
        hints = preflight.analyze(
            "Summarise today's news and yesterday's mail.\nGet the latest build."
        )["staleness_hints"]
        found = {h["phrase"]: h["lines"] for h in hints}
        self.assertEqual(found, {"today's": [1], "yesterday's": [1], "latest": [2]})

    def test_no_phrases_no_hints(self):
        self.assertEqual(preflight.analyze("Summarise the repo.")["staleness_hints"], [])


class InputTests(unittest.TestCase):
    def write(self, data):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "prompt.txt"
        path.write_bytes(data)
        return str(path)

    def test_empty_or_blank_prompt_is_an_error(self):
        for text in ("", "  \n\n"):
            with self.subTest(repr(text)):
                with self.assertRaises(preflight.PreflightError):
                    preflight.analyze(text)

    def test_oversized_prompt_is_an_error(self):
        with self.assertRaises(preflight.PreflightError) as ctx:
            preflight.analyze("a" * (preflight.MAX_PROMPT_CHARS + 1))
        self.assertIn("20000", str(ctx.exception))

    def test_non_positive_guard_hours_is_an_error(self):
        for hours in (0, -1):
            with self.subTest(hours):
                with self.assertRaises(preflight.PreflightError):
                    preflight.analyze("Summarise.", hours)

    def test_crlf_and_bom_do_not_disturb_line_numbers(self):
        path = self.write(b"\xef\xbb\xbfIntro\r\nrun npm test\r\nIf it is after 5pm, skip.\r\n")
        code, out, _ = run_main("--prompt-file", path, "--json")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["tools"][0]["lines"], [2])
        self.assertEqual(data["time_guard"]["line"], 3)

    def test_missing_file_is_a_clean_error(self):
        code, _, err = run_main("--prompt-file", "no-such-file.txt")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("error: cannot read"))
        self.assertNotIn("Traceback", err)

    def test_empty_file_is_a_clean_error(self):
        code, _, err = run_main("--prompt-file", self.write(b""))
        self.assertEqual((code, err), (2, "error: the prompt is empty\n"))


class OutputTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "prompt.txt"
        self.path.write_text("Run npm test, then git push.\nSummarise today's results.\n", encoding="utf-8")

    def test_text_report_has_the_three_sections(self):
        code, out, _ = run_main("--prompt-file", str(self.path), "--guard-hours", "4")
        self.assertEqual(code, 0)
        self.assertIn("likely needs", out)
        self.assertIn("Bash: pre-approve", out)
        self.assertIn("Bash(git push): approve once with Run now", out)
        self.assertIn("time guard: missing", out)
        self.assertIn("more than 4 hours", out)
        self.assertIn("today's", out)
        out.encode("ascii")

    def test_json_report_parses(self):
        code, out, _ = run_main("--prompt-file", str(self.path), "--json")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(set(data), {"tools", "time_guard", "staleness_hints"})
        self.assertEqual(data["time_guard"]["hours"], 2.0)


if __name__ == "__main__":
    unittest.main()
