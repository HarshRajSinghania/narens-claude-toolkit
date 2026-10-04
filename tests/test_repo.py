import unittest

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
        old_names = ("narens-claude-skills", "Naren's Claude Skills")
        allowed = {"README.md", "CHANGELOG.md", "tests/test_repo.py"}
        skip_parts = {".git", ".superpowers", "__pycache__", "superpowers"}
        suffixes = {".md", ".json", ".py", ".txt", ".svg", ".yml"}
        found = []
        for path in helpers.REPO_ROOT.rglob("*"):
            rel = path.relative_to(helpers.REPO_ROOT)
            if not path.is_file() or path.suffix not in suffixes:
                continue
            if skip_parts & set(rel.parts) or rel.as_posix() in allowed:
                continue
            try:
                text = common.read_text(path)
            except UnicodeDecodeError:
                continue
            found += [f"{rel.as_posix()}: {name}" for name in old_names if name in text]
        self.assertEqual(found, [])

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


if __name__ == "__main__":
    unittest.main()
