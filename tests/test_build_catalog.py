import tempfile
import unittest
from pathlib import Path

import helpers
import build_catalog
import common

ALPHA = {"name": "alpha", "description": "Does alpha."}
BETA = {"name": "beta-srv", "description": "Does beta."}
EMPTY = {"skills": [], "mods": [], "servers": []}


def groups(**over):
    return {**EMPTY, **over}


def section(readme, heading):
    """The text of one '### <heading>' subsection of the generated catalog."""
    start = readme.index(f"### {heading}")
    rest = readme[start + 1:]
    nxt = rest.find("\n### ")
    end = rest.find("<!-- CATALOG:END -->")
    cut = min(x for x in (nxt, end) if x != -1)
    return readme[start:start + 1 + cut]


class RenderCatalog(unittest.TestCase):
    def test_empty_sections_say_coming_soon(self):
        out = build_catalog.render_catalog(EMPTY)
        self.assertEqual(out.count("_Coming soon._"), 3)
        self.assertNotIn("| Skill |", out)

    def test_sections_come_in_order(self):
        out = build_catalog.render_catalog(EMPTY)
        self.assertLess(out.index("### Skills"), out.index("### Mods"))
        self.assertLess(out.index("### Mods"), out.index("### MCP servers"))

    def test_skill_and_mod_rows(self):
        out = build_catalog.render_catalog(groups(skills=[ALPHA], mods=[ALPHA]))
        self.assertIn("| Skill | What it does | Install |", out)
        self.assertIn("| Mod | What it does | Install |", out)
        row = (
            "| [`alpha`](plugins/alpha/README.md) | Does alpha. | "
            f"`/plugin install alpha@{common.MARKETPLACE}` |"
        )
        self.assertEqual(out.count(row), 2)
        self.assertEqual(out.count("_Coming soon._"), 1)

    def test_server_rows_link_to_the_folder_and_have_no_install_command(self):
        out = build_catalog.render_catalog(groups(servers=[BETA]))
        self.assertIn("| Server | What it does | Folder |", out)
        self.assertIn(
            "| [`beta-srv`](servers/beta-srv/README.md) | Does beta. | "
            "[`servers/beta-srv`](servers/beta-srv) |",
            out,
        )
        self.assertNotIn("/plugin install beta-srv", out)

    def test_pipe_in_description_is_escaped(self):
        out = build_catalog.render_catalog(
            groups(skills=[{"name": "alpha", "description": "a | b\nc"}])
        )
        self.assertIn("a \\| b c", out)
        row = [l for l in out.splitlines() if "alpha" in l][0]
        self.assertEqual(row.replace("\\|", "").count("|"), 4)  # 3 columns

    def test_pipe_in_a_server_description_is_escaped(self):
        out = build_catalog.render_catalog(
            groups(servers=[{"name": "beta-srv", "description": "x | y"}])
        )
        row = [l for l in out.splitlines() if "beta-srv" in l and "|" in l][-1]
        self.assertIn("x \\| y", row)
        self.assertEqual(row.replace("\\|", "").count("|"), 4)


class RenderLlms(unittest.TestCase):
    def test_empty(self):
        out = build_catalog.render_llms(EMPTY)
        self.assertTrue(out.startswith("# Naren's Claude Toolkit"))
        for heading in ("## Skills", "## Mods", "## MCP servers"):
            self.assertIn(heading, out)
        self.assertEqual(out.count("Coming soon"), 3)
        self.assertTrue(out.endswith("\n"))

    def test_with_items(self):
        out = build_catalog.render_llms(groups(skills=[ALPHA], servers=[BETA]))
        self.assertIn(
            f"- [alpha]({common.REPO_URL}/blob/main/plugins/alpha/README.md): Does alpha.", out
        )
        self.assertIn(
            f"- [beta-srv]({common.REPO_URL}/blob/main/servers/beta-srv/README.md): Does beta.",
            out,
        )
        self.assertEqual(out.count("Coming soon"), 1)


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

    def readme(self):
        return common.read_text(self.root / "README.md")

    def test_build_then_check_clean(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        self.assertEqual(build_catalog.check_outputs(self.root), [])
        self.assertIn("`alpha`", self.readme())
        self.assertTrue((self.root / "llms.txt").is_file())

    def test_a_skill_lands_in_skills_only(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        self.assertIn("`alpha`", section(self.readme(), "Skills"))
        self.assertNotIn("`alpha`", section(self.readme(), "Mods"))

    def test_a_mod_lands_in_mods_only(self):
        helpers.make_valid_repo(self.root, [], mods=["alpha-mod"])
        self.assertIn("`alpha-mod`", section(self.readme(), "Mods"))
        self.assertNotIn("`alpha-mod`", section(self.readme(), "Skills"))

    def test_a_server_lands_in_servers_with_its_readme_description(self):
        helpers.make_valid_repo(self.root, [], servers=["beta-srv"])
        servers = section(self.readme(), "MCP servers")
        self.assertIn("`beta-srv`", servers)
        self.assertIn("Does beta-srv things.", servers)

    def test_a_plugin_that_is_both_appears_in_both_tables(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.add_mod_files(self.root / "plugins/alpha")
        build_catalog.build(self.root)
        self.assertIn("`alpha`", section(self.readme(), "Skills"))
        self.assertIn("`alpha`", section(self.readme(), "Mods"))
        self.assertEqual(build_catalog.check_outputs(self.root), [])

    def test_check_detects_stale_readme(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.write_plugin(self.root, "beta")
        errs = build_catalog.check_outputs(self.root)
        self.assertTrue(any("README.md" in e and "out of date" in e for e in errs), errs)
        self.assertTrue(any("llms.txt" in e for e in errs), errs)

    def test_check_goes_stale_when_a_mod_or_server_is_added(self):
        helpers.make_valid_repo(self.root, ["alpha"])
        helpers.write_mod(self.root, "alpha-mod")
        errs = build_catalog.check_outputs(self.root)
        self.assertTrue(any("README.md" in e and "out of date" in e for e in errs), errs)
        build_catalog.build(self.root)
        self.assertEqual(build_catalog.check_outputs(self.root), [])
        helpers.write_server(self.root, "beta-srv")
        errs = build_catalog.check_outputs(self.root)
        self.assertTrue(any("llms.txt" in e for e in errs), errs)

    def test_files_in_servers_folder_are_ignored(self):
        helpers.make_valid_repo(self.root, [], servers=["beta-srv"])
        (self.root / "servers/.gitkeep").write_text("")
        self.assertEqual(build_catalog.collect(self.root)["servers"][0]["name"], "beta-srv")
        self.assertEqual(len(build_catalog.collect(self.root)["servers"]), 1)

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
