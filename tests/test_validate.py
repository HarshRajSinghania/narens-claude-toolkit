import contextlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
import common
import validate


class ValidateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def errors(self):
        return validate.validate(self.root)

    def assertHasError(self, fragment):
        errs = self.errors()
        self.assertTrue(any(fragment in e for e in errs), errs)

    # --- happy paths -------------------------------------------------
    def test_valid_repo(self):
        helpers.make_valid_repo(self.root, ["alpha", "beta-tool"])
        self.assertEqual(self.errors(), [])

    def test_empty_repo_is_valid(self):
        helpers.make_valid_repo(self.root, [])
        self.assertEqual(self.errors(), [])

    def test_crlf_and_bom_files_are_valid(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        skill = self.root / "plugins/alpha/skills/alpha/SKILL.md"
        skill.write_bytes(
            b"\xef\xbb\xbf---\r\nname: alpha\r\ndescription: Use when testing things.\r\n---\r\n\r\n# alpha\r\n"
        )
        pj = self.root / "plugins/alpha/.claude-plugin/plugin.json"
        pj.write_bytes(b"\xef\xbb\xbf" + pj.read_bytes())
        self.assertEqual(self.errors(), [])

    # --- plugin.json -------------------------------------------------
    def test_plugin_name_mismatch(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.edit_plugin_json(self.root, "alpha", lambda d: d.update(name="other"))
        self.assertHasError("must equal directory name")

    def test_wrong_author(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.edit_plugin_json(self.root, "alpha", lambda d: d.update(author={"name": "Someone"}))
        self.assertHasError("author.name must be 'Naren'")

    def test_missing_description(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.edit_plugin_json(self.root, "alpha", lambda d: d.pop("description"))
        self.assertHasError("missing 'description'")

    def test_missing_version(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.edit_plugin_json(self.root, "alpha", lambda d: d.pop("version"))
        self.assertHasError("missing 'version'")

    def test_malformed_plugin_json(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/.claude-plugin/plugin.json").write_text("{not json")
        self.assertHasError("plugin.json: invalid JSON")

    def test_missing_plugin_json(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/.claude-plugin/plugin.json").unlink()
        self.assertHasError("plugin.json: missing")

    # --- plugin layout -----------------------------------------------
    def test_non_kebab_plugin_dir(self):
        helpers.make_valid_repo(self.root, ["BadName"])
        self.assertHasError("plugins/BadName: directory name must be kebab-case")

    def test_missing_plugin_readme(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/README.md").unlink()
        self.assertHasError("plugins/alpha/README.md: missing")

    def test_no_skills(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        shutil.rmtree(self.root / "plugins/alpha/skills")
        self.assertHasError("needs at least one skill directory")

    # --- SKILL.md ----------------------------------------------------
    def test_skill_name_mismatch(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/skills/alpha/SKILL.md").write_text(
            "---\nname: other\ndescription: Use when x.\n---\n"
        )
        self.assertHasError("must equal directory name")

    def test_missing_skill_md(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/skills/alpha/SKILL.md").unlink()
        self.assertHasError("skills/alpha/SKILL.md: missing")

    def test_missing_frontmatter_description(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/skills/alpha/SKILL.md").write_text("---\nname: alpha\n---\n")
        self.assertHasError("frontmatter 'description' missing")

    def test_description_must_start_with_use_when(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/skills/alpha/SKILL.md").write_text(
            "---\nname: alpha\ndescription: A cool tool.\n---\n"
        )
        self.assertHasError("starting with 'Use when'")

    def test_multiline_description_rejected(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/skills/alpha/SKILL.md").write_text(
            "---\nname: alpha\ndescription: >\n  Use when folded.\n---\n"
        )
        self.assertHasError("single line starting with 'Use when'")

    # --- marketplace.json --------------------------------------------
    def test_plugin_not_listed(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.write_marketplace(self.root, [])
        self.assertHasError("plugin 'alpha' is not listed")

    def test_listed_plugin_missing_on_disk(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.write_marketplace(self.root, ["alpha", "ghost"])
        self.assertHasError("'ghost' source './plugins/ghost' does not exist")

    def test_marketplace_wrong_owner(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.write_marketplace(self.root, ["alpha"], owner="Someone")
        self.assertHasError("owner.name must be 'Naren'")

    def test_malformed_marketplace_json(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / ".claude-plugin/marketplace.json").write_text("[oops")
        self.assertHasError("marketplace.json: invalid JSON")

    def test_missing_marketplace(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / ".claude-plugin/marketplace.json").unlink()
        self.assertHasError("marketplace.json: missing")

    # --- catalog freshness -------------------------------------------
    def test_stale_catalog(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.write_plugin(self.root, "gamma")
        helpers.write_marketplace(self.root, ["alpha", "gamma"])
        self.assertHasError("out of date")

    # --- CLI ---------------------------------------------------------
    def test_main_exit_codes(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(validate.main([str(self.root)]), 0)
        (self.root / "plugins/alpha/README.md").unlink()
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(validate.main([str(self.root)]), 1)
        self.assertIn("ERROR plugins/alpha/README.md: missing", err.getvalue())


if __name__ == "__main__":
    unittest.main()
