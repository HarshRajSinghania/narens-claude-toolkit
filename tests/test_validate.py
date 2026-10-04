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
        self.assertHasError("needs skills/ or hooks/hooks.json")

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

    # --- review fix pass ---------------------------------------------
    def _write_marketplace_raw(self, plugins):
        import json
        (self.root / ".claude-plugin/marketplace.json").write_text(json.dumps({
            "name": "narens-claude-toolkit", "owner": {"name": "Naren"}, "plugins": plugins}))

    def test_plugins_not_a_list(self):
        import json
        helpers.make_valid_repo(self.root, ["alpha"])
        for bad in (5, None, {"a": 1}):
            (self.root / ".claude-plugin/marketplace.json").write_text(json.dumps({
                "name": "narens-claude-toolkit", "owner": {"name": "Naren"}, "plugins": bad}))
            self.assertHasError("'plugins' must be an array")

    def test_non_string_description_is_an_error_not_a_crash(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.edit_plugin_json(self.root, "alpha", lambda d: d.update(description=5))
        self.assertHasError("'description' must be a non-empty string")

    def test_unreadable_readme_is_an_error_not_a_crash(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "README.md").write_bytes(b"\x80abc <!-- CATALOG:START -->")
        self.assertHasError("README.md: unreadable")

    def test_source_must_be_canonical(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        for src in ("plugins/alpha", "./template", "../x"):
            self._write_marketplace_raw([{"name": "alpha", "source": src}])
            self.assertHasError("source %r must be './plugins/alpha'" % src)

    def test_duplicate_marketplace_entries(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        e = {"name": "alpha", "source": "./plugins/alpha"}
        self._write_marketplace_raw([e, dict(e)])
        self.assertHasError("duplicate plugin name 'alpha'")

    def test_unquoted_description_with_colon_rejected(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/skills/alpha/SKILL.md").write_text(
            "---\nname: alpha\ndescription: Use when a: b.\n---\n")
        self.assertHasError("wrap it in double quotes")

    def test_unquoted_description_with_hash_rejected(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/skills/alpha/SKILL.md").write_text(
            "---\nname: alpha\ndescription: Use when foo #tag bar\n---\n")
        self.assertHasError("wrap it in double quotes")

    def test_quoted_description_with_colon_is_valid(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        (self.root / "plugins/alpha/skills/alpha/SKILL.md").write_text(
            '---\nname: alpha\ndescription: "Use when a: b #c."\n---\n')
        self.assertEqual(self.errors(), [])


class ModTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def errors(self):
        return validate.validate(self.root)

    def assertHasError(self, fragment):
        errs = self.errors()
        self.assertTrue(any(fragment in e for e in errs), errs)

    def repo_with_mod(self, **kw):
        helpers.make_valid_repo(self.root, [])
        plugin = helpers.write_mod(self.root, "alpha-mod", **kw)
        helpers.write_marketplace(self.root, ["alpha-mod"])
        import build_catalog
        build_catalog.build(self.root)
        return plugin

    def test_valid_mod(self):
        helpers.make_valid_repo(self.root, [], mods=["alpha-mod"])
        self.assertEqual(self.errors(), [])

    def test_plugin_with_neither_skills_nor_hooks(self):
        helpers.make_valid_repo(self.root, [], mods=["alpha-mod"])
        shutil.rmtree(self.root / "plugins/alpha-mod/hooks")
        self.assertHasError("plugins/alpha-mod: needs skills/ or hooks/hooks.json")

    def test_skills_folder_holding_only_a_file_is_not_a_skill(self):
        helpers.make_valid_repo(self.root, [], mods=["alpha-mod"])
        shutil.rmtree(self.root / "plugins/alpha-mod/hooks")
        (self.root / "plugins/alpha-mod/skills").mkdir()
        (self.root / "plugins/alpha-mod/skills/notes.txt").write_text("x")
        self.assertHasError("needs skills/ or hooks/hooks.json")

    def test_hooks_folder_without_hooks_json_is_not_a_mod(self):
        helpers.make_valid_repo(self.root, [], mods=["alpha-mod"])
        (self.root / "plugins/alpha-mod/hooks/hooks.json").unlink()
        self.assertHasError("needs skills/ or hooks/hooks.json")

    def test_invalid_hooks_json(self):
        self.repo_with_mod(hooks_json="{not json")
        self.assertHasError("plugins/alpha-mod/hooks/hooks.json: invalid JSON")

    def test_hooks_json_must_be_an_object(self):
        self.repo_with_mod(hooks_json='["./register.ts"]')
        self.assertHasError("hooks.json: must be a JSON object")

    def test_modules_must_be_a_non_empty_list_of_non_empty_strings(self):
        for bad in ('{}', '{"modules": "./register.ts"}', '{"modules": []}',
                    '{"modules": [5]}', '{"modules": [""]}', '{"modules": ["./a.ts", null]}'):
            with self.subTest(bad):
                shutil.rmtree(self.root, ignore_errors=True)
                self.root.mkdir(exist_ok=True)
                self.repo_with_mod(hooks_json=bad)
                self.assertHasError("'modules' must be a non-empty list of file paths")

    def test_missing_module_file(self):
        plugin = self.repo_with_mod()
        (plugin / "hooks/register.ts").unlink()
        self.assertHasError("hooks.json: module './register.ts' does not exist")

    def test_module_path_that_is_a_directory_is_missing(self):
        plugin = self.repo_with_mod()
        (plugin / "hooks/register.ts").unlink()
        (plugin / "hooks/register.ts").mkdir()
        self.assertHasError("module './register.ts' does not exist")

    def test_bom_and_crlf_hooks_json_is_valid(self):
        plugin = self.repo_with_mod()
        (plugin / "hooks/hooks.json").write_bytes(
            b'\xef\xbb\xbf{\r\n  "modules": ["./register.ts"]\r\n}\r\n'
        )
        self.assertEqual(self.errors(), [])

    def test_plugin_that_is_both_validates_both_halves(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.add_mod_files(self.root / "plugins/alpha")
        import build_catalog
        build_catalog.build(self.root)
        self.assertEqual(self.errors(), [])

    def test_errors_from_both_halves_are_reported(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.add_mod_files(self.root / "plugins/alpha", hooks_json="{oops")
        (self.root / "plugins/alpha/skills/alpha/SKILL.md").unlink()
        self.assertHasError("skills/alpha/SKILL.md: missing")
        self.assertHasError("hooks/hooks.json: invalid JSON")


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def errors(self):
        return validate.validate(self.root)

    def assertHasError(self, fragment):
        errs = self.errors()
        self.assertTrue(any(fragment in e for e in errs), errs)

    def test_valid_server_needs_no_marketplace_entry(self):
        helpers.make_valid_repo(self.root, [], servers=["beta-srv"])
        self.assertEqual(self.errors(), [])
        data = common.load_json(self.root / ".claude-plugin/marketplace.json")
        self.assertEqual(data["plugins"], [])

    def test_pyproject_is_an_accepted_manifest(self):
        helpers.write_server(self.root, "beta-srv", manifest="pyproject.toml")
        self.assertEqual(validate.check_server(self.root / "servers/beta-srv"), [])

    def test_missing_readme(self):
        helpers.make_valid_repo(self.root, [], servers=["beta-srv"])
        (self.root / "servers/beta-srv/README.md").unlink()
        self.assertHasError("servers/beta-srv/README.md: missing")

    def test_readme_without_a_description_line(self):
        helpers.make_valid_repo(self.root, [], servers=["beta-srv"])
        (self.root / "servers/beta-srv/README.md").write_text("# beta\n\n>no space\n")
        self.assertHasError("needs a first line starting with '> '")

    def test_empty_marker_line_is_skipped_for_a_real_one(self):
        helpers.write_server(self.root, "beta-srv", readme="# beta\n\n> \n\n> Real description.\n")
        self.assertEqual(validate.check_server(self.root / "servers/beta-srv"), [])
        self.assertEqual(common.server_description(self.root / "servers/beta-srv"), "Real description.")

    def test_crlf_and_bom_readme_is_valid(self):
        sdir = helpers.write_server(self.root, "beta-srv")
        (sdir / "README.md").write_bytes(b"\xef\xbb\xbf# beta\r\n\r\n> Does beta.\r\n")
        self.assertEqual(validate.check_server(sdir), [])
        self.assertEqual(common.server_description(sdir), "Does beta.")

    def test_no_manifest(self):
        helpers.make_valid_repo(self.root, [], servers=["beta-srv"])
        (self.root / "servers/beta-srv/package.json").unlink()
        self.assertHasError("servers/beta-srv: needs package.json or pyproject.toml")

    def test_bad_name(self):
        helpers.write_server(self.root, "Bad_Name")
        errs = validate.check_server(self.root / "servers/Bad_Name")
        self.assertTrue(any("directory name must be kebab-case" in e for e in errs), errs)

    def test_files_in_servers_folder_are_ignored(self):
        helpers.make_valid_repo(self.root, [], servers=["beta-srv"])
        (self.root / "servers/.gitkeep").write_text("")
        self.assertEqual(self.errors(), [])


if __name__ == "__main__":
    unittest.main()
