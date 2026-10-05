import tempfile
import unittest
from pathlib import Path

import helpers
import common
import validate


class RealRepo(unittest.TestCase):
    def test_repo_passes_validation(self):
        self.assertEqual(validate.validate(helpers.REPO_ROOT), [])

    def test_required_root_files_exist(self):
        for name in (
            "README.md", "LICENSE", "CONTRIBUTING.md", "CODE_OF_CONDUCT.md",
            "CHANGELOG.md", "llms.txt", ".gitignore", ".gitattributes",
            ".claude-plugin/marketplace.json",
        ):
            self.assertTrue((helpers.REPO_ROOT / name).is_file(), name)

    def test_branding_present(self):
        readme = common.read_text(helpers.REPO_ROOT / "README.md")
        self.assertTrue(readme.startswith("# Naren's Claude Toolkit"))
        self.assertIn("NarenDawar/narens-claude-toolkit", readme)
        self.assertIn("Moving from narens-claude-skills", readme)
        self.assertIn("Made by [Naren]", readme)
        self.assertIn("alt=", readme)  # banner has alt text

    def test_old_name_survives_only_in_history_and_the_migration_note(self):
        self.assertEqual(helpers.find_old_name(helpers.REPO_ROOT), [])

    def test_github_and_docs_files_exist(self):
        for name in (
            ".github/workflows/validate.yml",
            ".github/PULL_REQUEST_TEMPLATE.md",
            ".github/ISSUE_TEMPLATE/bug_report.md",
            ".github/ISSUE_TEMPLATE/skill_idea.md",
            "docs/conventions.md",
            "docs/launch-checklist.md",
            "assets/logo.svg",
            "assets/banner.svg",
            "assets/social-preview.svg",
            "assets/social-preview.png",
        ):
            self.assertTrue((helpers.REPO_ROOT / name).is_file(), name)


class OldNameGuardTests(unittest.TestCase):
    OLD = "narens-claude-skills"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def put(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def names(self):
        return [f.split(":")[0] for f in helpers.find_old_name(self.root)]

    def test_stragglers_in_any_text_file_are_found(self):
        planted = {
            "servers.toml": f'repo = "{self.OLD}"\n',
            "plugins/x/hooks/x.ts": f"// {self.OLD}\n",
            ".github/stray.yaml": f"name: {self.OLD}\n",
            "LICENSE": f"{self.OLD}\n",
            "docs/stray.md": "Naren's Claude skills\n",
            "README.md": f"# t\n\n[stars](https://github.com/NarenDawar/{self.OLD}/stargazers)\n",
        }
        for rel, text in planted.items():
            self.put(rel, text)
        self.assertEqual(sorted(self.names()), sorted(planted))

    def test_history_and_the_migration_notes_are_allowed(self):
        self.put("docs/superpowers/plans/old.md", f"{self.OLD}\n")
        self.put(
            "README.md",
            f"# t\n\n## Moving from {self.OLD}\n\nremove {self.OLD}\n\n## Next\n\nfine\n",
        )
        self.put(
            "CHANGELOG.md",
            f"## [Unreleased]\n\n### Changed\n- was `{self.OLD}`\n\n### Fixed\n- ok\n",
        )
        self.put("node_modules/pkg/readme.md", f"{self.OLD}\n")
        self.assertEqual(helpers.find_old_name(self.root), [])

    def test_a_straggler_after_the_migration_section_is_found(self):
        self.put(
            "README.md",
            f"# t\n\n## Moving from {self.OLD}\n\nremove it\n\n## Install\n\n/plugin install a@{self.OLD}\n",
        )
        self.assertEqual(self.names(), ["README.md"])

    def test_a_straggler_outside_the_changelog_changed_entry_is_found(self):
        self.put(
            "CHANGELOG.md",
            f"## [Unreleased]\n\n### Changed\n- was {self.OLD}\n\n### Fixed\n- still {self.OLD}\n",
        )
        self.assertEqual(self.names(), ["CHANGELOG.md"])

    def test_matching_ignores_case(self):
        self.put("docs/a.md", "NAREN'S CLAUDE SKILLS\n")
        self.assertEqual(self.names(), ["docs/a.md"])

    def test_undecodable_files_are_skipped(self):
        (self.root / "logo.bin").write_bytes(b"\x80\x81" + self.OLD.encode())
        self.assertEqual(helpers.find_old_name(self.root), [])


if __name__ == "__main__":
    unittest.main()
