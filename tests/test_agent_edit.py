import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers

sys.path.insert(
    0,
    str(helpers.REPO_ROOT / "plugins" / "subagent-tax-auditor" / "skills" / "subagent-tax-auditor" / "scripts"),
)
import agent_edit as ae  # noqa: E402

AGENT = "---\nname: reviewer\ndescription: Reviews code\nmodel: opus\ntools: Read, Grep\n---\nYou review code.\nmodel: not-frontmatter\n"


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ae.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class EditTextTests(unittest.TestCase):
    def test_existing_model_is_replaced_and_nothing_else_changes(self):
        after = ae.edit_text(AGENT, model="sonnet")
        self.assertEqual(after, AGENT.replace("model: opus", "model: sonnet"))
        self.assertIn("model: not-frontmatter", after)  # the body is untouched

    def test_missing_model_is_added_before_the_closing_marker(self):
        text = "---\nname: a\ndescription: d\n---\nbody\n"
        self.assertEqual(ae.edit_text(text, model="haiku"), "---\nname: a\ndescription: d\nmodel: haiku\n---\nbody\n")

    def test_effort_is_added(self):
        level = ae.EFFORT_LEVELS[0]
        after = ae.edit_text(AGENT, effort=level)
        self.assertIn(f"effort: {level}\n---", after)
        self.assertIn("model: opus", after)

    def test_crlf_is_preserved_everywhere(self):
        text = AGENT.replace("\n", "\r\n")
        after = ae.edit_text(text, model="sonnet")
        self.assertNotIn("\n", after.replace("\r\n", ""))
        self.assertIn("model: sonnet\r\n", after)
        added = ae.edit_text("---\r\nname: a\r\n---\r\nbody\r\n", model="haiku")
        self.assertEqual(added, "---\r\nname: a\r\nmodel: haiku\r\n---\r\nbody\r\n")

    def test_bom_is_preserved(self):
        after = ae.edit_text("\ufeff" + AGENT, model="sonnet")
        self.assertTrue(after.startswith("\ufeff---\n"))

    def test_trailing_comment_and_quotes(self):
        self.assertIn("model: sonnet # pricey\n", ae.edit_text(AGENT.replace("model: opus", "model: opus # pricey"), model="sonnet"))
        self.assertIn("model: sonnet\n", ae.edit_text(AGENT.replace("model: opus", 'model: "opus"'), model="sonnet"))

    def test_unicode_is_preserved(self):
        text = "---\nname: a\ndescription: Überprüft Code ✓\n---\nCafé\n"
        self.assertIn("Überprüft Code ✓", ae.edit_text(text, model="sonnet"))
        self.assertTrue(ae.edit_text(text, model="sonnet").endswith("Café\n"))

    def test_refused_files(self):
        cases = {
            "no frontmatter": "just text\n",
            "unterminated": "---\nname: a\nbody never closes\n",
            "duplicate key": "---\nname: a\nmodel: opus\nmodel: haiku\n---\nx\n",
            "empty value": "---\nname: a\nmodel:\n  - opus\n---\nx\n",
            "block scalar": "---\nname: a\nmodel: |\n  opus\n---\nx\n",
        }
        for label, text in cases.items():
            with self.assertRaises(ae.AgentError, msg=label):
                ae.edit_text(text, model="sonnet")

    def test_values_are_validated(self):
        for ok in ("sonnet", "opus", "haiku", "fable", "inherit", "claude-sonnet-5-5", "claude-haiku-4-5-20251001"):
            self.assertEqual(ae.validate_model(ok), ok)
        for bad in ("gpt-4", "", "Sonnet 5", "opus\nmodel: x", "claude-"):
            with self.assertRaises(ae.AgentError, msg=bad):
                ae.validate_model(bad)
        with self.assertRaises(ae.AgentError):
            ae.validate_effort("ludicrous")

    def test_current_values(self):
        self.assertEqual(ae.current_values(AGENT), {"name": "reviewer", "model": "opus", "effort": None})


class FindAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name, "project")
        self.user = Path(self.tmp.name, "user")
        for d in (self.project, self.user):
            d.mkdir()
        (self.project / "reviewer.md").write_text(AGENT, encoding="utf-8")
        (self.user / "reviewer.md").write_text(AGENT.replace("opus", "haiku"), encoding="utf-8")
        (self.user / "file-name.md").write_text("---\nname: pretty-name\ndescription: d\n---\nx\n", encoding="utf-8")

    def test_project_dir_wins_on_a_name_clash(self):
        self.assertEqual(ae.find_agent("reviewer", [self.project, self.user]), self.project / "reviewer.md")

    def test_found_by_frontmatter_name_or_file_stem(self):
        self.assertEqual(ae.find_agent("pretty-name", [self.user]), self.user / "file-name.md")
        self.assertEqual(ae.find_agent("file-name", [self.user]), self.user / "file-name.md")

    def test_unknown_agent_lists_the_known_ones(self):
        with self.assertRaises(ae.AgentError) as caught:
            ae.find_agent("nope", [self.project, self.user])
        self.assertIn("reviewer", str(caught.exception))

    def test_list_agents_reports_unreadable_ones(self):
        (self.project / "broken.md").write_text("no frontmatter\n", encoding="utf-8")
        rows = {row["name"]: row for row in ae.list_agents([self.project])}
        self.assertEqual(rows["reviewer"]["model"], "opus")
        self.assertIn("problem", rows["broken"])


class ApplyUndoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agents = Path(self.tmp.name, "agents")
        self.agents.mkdir()
        self.backups = Path(self.tmp.name, "backups")
        self.path = self.agents / "reviewer.md"
        self.path.write_bytes(AGENT.encode("utf-8"))

    def apply(self, model):
        return ae.apply_edit(self.path, ae.edit_text(self.path.read_text(encoding="utf-8"), model=model), self.backups, "reviewer")

    def test_apply_writes_and_backs_up(self):
        backup = self.apply("sonnet")
        self.assertIn("model: sonnet", self.path.read_text(encoding="utf-8"))
        self.assertEqual(backup.read_text(encoding="utf-8"), AGENT)

    def test_apply_with_no_change_does_nothing(self):
        self.assertIsNone(self.apply("opus"))
        self.assertFalse(self.backups.exists())

    def test_undo_restores_the_original(self):
        self.apply("sonnet")
        restored = ae.undo("reviewer", self.backups)
        self.assertEqual(restored, self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), AGENT)

    def test_undo_is_refused_after_a_later_edit(self):
        self.apply("sonnet")
        self.path.write_text(self.path.read_text(encoding="utf-8") + "\nmore body\n", encoding="utf-8")
        with self.assertRaises(ae.AgentError) as caught:
            ae.undo("reviewer", self.backups)
        self.assertIn("changed since", str(caught.exception))
        self.assertIn("more body", self.path.read_text(encoding="utf-8"))

    def test_two_applies_undo_in_reverse_order(self):
        self.apply("sonnet")
        self.apply("haiku")
        ae.undo("reviewer", self.backups)
        self.assertIn("model: sonnet", self.path.read_text(encoding="utf-8"))
        ae.undo("reviewer", self.backups)
        self.assertEqual(self.path.read_text(encoding="utf-8"), AGENT)
        with self.assertRaises(ae.AgentError):
            ae.undo("reviewer", self.backups)

    def test_undo_without_a_backup_is_an_error(self):
        with self.assertRaises(ae.AgentError):
            ae.undo("reviewer", self.backups)

    def test_agent_names_cannot_escape_the_backup_dir(self):
        with self.assertRaises(ae.AgentError):
            ae.apply_edit(self.path, AGENT + "x", self.backups, "../evil")

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_file_mode_is_preserved(self):
        os.chmod(self.path, 0o640)
        self.apply("sonnet")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o640)

    def test_symlinked_agent_file_is_written_through(self):
        real = Path(self.tmp.name, "shared.md")
        real.write_bytes(AGENT.encode("utf-8"))
        link = self.agents / "linked.md"
        try:
            os.symlink(real, link)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create a symlink here")
        ae.apply_edit(link, ae.edit_text(AGENT, model="sonnet"), self.backups, "linked")
        self.assertTrue(link.is_symlink())
        self.assertIn("model: sonnet", real.read_text(encoding="utf-8"))

    def test_a_failed_write_leaves_the_file_and_no_backup(self):
        with mock.patch.object(ae.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                self.apply("sonnet")
        self.assertEqual(self.path.read_text(encoding="utf-8"), AGENT)
        self.assertEqual([p.name for p in self.agents.iterdir()], ["reviewer.md"])
        self.assertEqual(list(self.backups.glob("*")) if self.backups.exists() else [], [])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agents = Path(self.tmp.name, "agents")
        self.agents.mkdir()
        self.backups = str(Path(self.tmp.name, "backups"))
        self.path = self.agents / "reviewer.md"
        self.path.write_bytes(AGENT.encode("utf-8"))

    def common(self):
        return ["--agents-dir", str(self.agents)]

    def test_list(self):
        code, out, _ = run_cli("list", *self.common())
        self.assertEqual(code, 0)
        self.assertIn("reviewer", out)
        self.assertIn("opus", out)

    def test_plan_shows_a_diff_and_changes_nothing(self):
        code, out, _ = run_cli("plan", "--agent", "reviewer", "--model", "sonnet", *self.common())
        self.assertEqual(code, 0)
        self.assertIn("-model: opus", out)
        self.assertIn("+model: sonnet", out)
        self.assertEqual(self.path.read_text(encoding="utf-8"), AGENT)

    def test_plan_with_no_change(self):
        code, out, _ = run_cli("plan", "--agent", "reviewer", "--model", "opus", *self.common())
        self.assertEqual(code, 0)
        self.assertIn("No changes", out)

    def test_apply_then_undo(self):
        code, out, _ = run_cli("apply", "--agent", "reviewer", "--model", "haiku", "--backup-dir", self.backups, *self.common())
        self.assertEqual(code, 0)
        self.assertIn("Backup:", out)
        self.assertIn("model: haiku", self.path.read_text(encoding="utf-8"))
        code, out, _ = run_cli("undo", "--agent", "reviewer", "--backup-dir", self.backups)
        self.assertEqual(code, 0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), AGENT)

    def test_apply_prints_an_undo_command_that_works_from_anywhere(self):
        code, out, _ = run_cli("apply", "--agent", "reviewer", "--model", "haiku", "--backup-dir", self.backups, *self.common())
        self.assertEqual(code, 0)
        line = next(l for l in out.splitlines() if l.startswith("To undo:"))
        self.assertIn("--backup-dir", line)
        self.assertIn(self.backups, line)
        self.assertNotIn("--agents-dir", line)  # undo does not take it

    def test_errors_are_clean(self):
        for argv in (
            ["plan", "--agent", "nope", "--model", "sonnet", *self.common()],
            ["plan", "--agent", "reviewer", "--model", "gpt-4", *self.common()],
            ["plan", "--agent", "reviewer", *self.common()],
            ["undo", "--agent", "reviewer", "--backup-dir", self.backups],
        ):
            code, _, err = run_cli(*argv)
            self.assertEqual(code, 2, argv)
            self.assertTrue(err.startswith("error:"), (argv, err))

    def test_write_failure_is_a_clean_error(self):
        with mock.patch.object(ae.os, "replace", side_effect=PermissionError("locked")):
            code, _, err = run_cli("apply", "--agent", "reviewer", "--model", "haiku", "--backup-dir", self.backups, *self.common())
        self.assertEqual(code, 2)
        self.assertIn("error:", err)


if __name__ == "__main__":
    unittest.main()
