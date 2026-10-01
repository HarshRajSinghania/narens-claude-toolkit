import shutil
import tempfile
import unittest
from pathlib import Path

import helpers
import common
import new_skill
import validate


class NewSkillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        helpers.make_valid_repo(self.root, [])
        shutil.copytree(helpers.REPO_ROOT / "template", self.root / "template")

    def test_created_skill_passes_validation(self):
        plugin = new_skill.create(self.root, "pdf-surgeon", "Use when editing PDF files.")
        self.assertEqual(plugin, self.root / "plugins" / "pdf-surgeon")
        self.assertTrue((plugin / "skills/pdf-surgeon/SKILL.md").is_file())
        self.assertEqual(validate.validate(self.root), [])

    def test_registers_in_marketplace_and_catalog(self):
        new_skill.create(self.root, "pdf-surgeon", "Use when editing PDF files.")
        data = common.load_json(self.root / ".claude-plugin/marketplace.json")
        self.assertEqual(
            data["plugins"],
            [
                {
                    "name": "pdf-surgeon",
                    "source": "./plugins/pdf-surgeon",
                    "description": "Use when editing PDF files.",
                }
            ],
        )
        self.assertIn("`pdf-surgeon`", common.read_text(self.root / "README.md"))

    def test_no_tokens_left_behind(self):
        plugin = new_skill.create(self.root, "pdf-surgeon", "Use when editing PDF files.")
        for f in plugin.rglob("*"):
            if f.is_file():
                text = common.read_text(f)
                self.assertNotIn("__SKILL_NAME__", text, f)
                self.assertNotIn("__DESCRIPTION__", text, f)

    def test_description_with_quotes_and_colon(self):
        desc = 'Use when a user says "fix it": quotes, colons & pipes | all fine.'
        new_skill.create(self.root, "quoty", desc)
        meta = common.load_json(self.root / "plugins/quoty/.claude-plugin/plugin.json")
        self.assertEqual(meta["description"], desc)
        self.assertEqual(validate.validate(self.root), [])

    def test_rejects_bad_name(self):
        with self.assertRaises(ValueError):
            new_skill.create(self.root, "Bad_Name", "Use when x.")

    def test_rejects_bad_description(self):
        with self.assertRaises(ValueError):
            new_skill.create(self.root, "good-name", "A cool tool.")

    def test_rejects_existing(self):
        new_skill.create(self.root, "pdf-surgeon", "Use when editing PDF files.")
        with self.assertRaises(FileExistsError):
            new_skill.create(self.root, "pdf-surgeon", "Use when editing PDF files.")

    def test_real_template_has_expected_files(self):
        t = helpers.REPO_ROOT / "template"
        self.assertTrue((t / ".claude-plugin/plugin.json").is_file())
        self.assertTrue((t / "README.md").is_file())
        self.assertTrue((t / "skills/__SKILL_NAME__/SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
