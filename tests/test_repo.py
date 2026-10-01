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
        self.assertTrue(readme.startswith("# Naren's Claude Skills"))
        self.assertIn("NarenDawar/narens-claude-skills", readme)
        self.assertIn("Made by [Naren]", readme)
        self.assertIn("alt=", readme)  # banner has alt text

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
