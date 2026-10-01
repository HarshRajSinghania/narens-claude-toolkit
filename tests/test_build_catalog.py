import tempfile
import unittest
from pathlib import Path

import helpers
import build_catalog
import common


class RenderTable(unittest.TestCase):
    def test_empty_catalog_placeholder(self):
        out = build_catalog.render_table([])
        self.assertNotIn("| Skill |", out)
        self.assertIn("on the way", out)

    def test_table_rows(self):
        out = build_catalog.render_table([{"name": "alpha", "description": "Does alpha."}])
        self.assertIn("| Skill | What it does | Install |", out)
        self.assertIn(
            "| [`alpha`](plugins/alpha/README.md) | Does alpha. | "
            "`/plugin install alpha@narens-claude-skills` |",
            out,
        )

    def test_pipe_in_description_is_escaped(self):
        out = build_catalog.render_table([{"name": "alpha", "description": "a | b\nc"}])
        self.assertIn("a \\| b c", out)
        row = [l for l in out.splitlines() if "alpha" in l][0]
        # 3 columns => 4 unescaped pipes
        self.assertEqual(row.replace("\\|", "").count("|"), 4)


class RenderLlms(unittest.TestCase):
    def test_empty(self):
        out = build_catalog.render_llms([])
        self.assertTrue(out.startswith("# Naren's Claude Skills"))
        self.assertIn("Coming soon", out)
        self.assertTrue(out.endswith("\n"))

    def test_with_skills(self):
        out = build_catalog.render_llms([{"name": "alpha", "description": "Does alpha."}])
        self.assertIn(
            "- [alpha](https://github.com/NarenDawar/narens-claude-skills/blob/main/"
            "plugins/alpha/README.md): Does alpha.",
            out,
        )


class ReplaceBetween(unittest.TestCase):
    def test_replaces_content(self):
        text = "a\n<!-- CATALOG:START -->\nold\n<!-- CATALOG:END -->\nb\n"
        self.assertEqual(
            build_catalog.replace_between(text, "NEW"),
            "a\n<!-- CATALOG:START -->\nNEW\n<!-- CATALOG:END -->\nb\n",
        )

    def test_is_idempotent(self):
        text = "a\n<!-- CATALOG:START -->\nold\n<!-- CATALOG:END -->\nb\n"
        once = build_catalog.replace_between(text, "NEW")
        self.assertEqual(build_catalog.replace_between(once, "NEW"), once)

    def test_missing_markers(self):
        with self.assertRaises(ValueError):
            build_catalog.replace_between("no markers here", "NEW")


class BuildAndCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_build_then_check_clean(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        self.assertEqual(build_catalog.check_outputs(self.root), [])
        readme = common.read_text(self.root / "README.md")
        self.assertIn("`alpha`", readme)
        self.assertTrue((self.root / "llms.txt").is_file())

    def test_check_detects_stale_readme(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.write_plugin(self.root, "beta")
        errs = build_catalog.check_outputs(self.root)
        self.assertTrue(any("README.md" in e and "out of date" in e for e in errs), errs)
        self.assertTrue(any("llms.txt" in e for e in errs), errs)

    def test_check_reports_missing_markers(self):
        helpers.make_valid_repo(self.root, [])
        common.write_text(self.root / "README.md", "# no markers\n")
        errs = build_catalog.check_outputs(self.root)
        self.assertTrue(any("CATALOG" in e for e in errs), errs)

    def test_main_check_exit_codes(self):
        import contextlib
        import io

        helpers.make_valid_repo(self.root, ["alpha"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_catalog.main(["--check", str(self.root)]), 0)
            helpers.write_plugin(self.root, "beta")
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(build_catalog.main(["--check", str(self.root)]), 1)
            self.assertEqual(build_catalog.main([str(self.root)]), 0)
            self.assertEqual(build_catalog.main(["--check", str(self.root)]), 0)


if __name__ == "__main__":
    unittest.main()
