import tempfile
import unittest
from pathlib import Path

import helpers  # noqa: F401  (sets sys.path)
import common


class ParseFrontmatter(unittest.TestCase):
    def test_basic(self):
        text = "---\nname: demo\ndescription: Use when testing.\n---\nbody"
        self.assertEqual(
            common.parse_frontmatter(text),
            {"name": "demo", "description": "Use when testing."},
        )

    def test_crlf(self):
        text = "---\r\nname: demo\r\ndescription: Use when x.\r\n---\r\nbody\r\n"
        self.assertEqual(
            common.parse_frontmatter(text),
            {"name": "demo", "description": "Use when x."},
        )

    def test_quoted_value_with_colon(self):
        text = '---\nname: demo\ndescription: "Use when a: b."\n---\n'
        self.assertEqual(common.parse_frontmatter(text)["description"], "Use when a: b.")

    def test_no_frontmatter(self):
        self.assertEqual(common.parse_frontmatter("# just a heading\n"), {})

    def test_unterminated_frontmatter(self):
        self.assertEqual(common.parse_frontmatter("---\nname: demo\n"), {})


class FileIO(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_read_text_strips_bom(self):
        p = self.root / "SKILL.md"
        p.write_bytes(b"\xef\xbb\xbf---\nname: x\n---\n")
        self.assertEqual(common.parse_frontmatter(common.read_text(p)), {"name": "x"})

    def test_write_text_uses_lf(self):
        p = self.root / "out.txt"
        common.write_text(p, "a\nb\n")
        self.assertEqual(p.read_bytes(), b"a\nb\n")

    def test_load_json_tolerates_bom(self):
        p = self.root / "x.json"
        p.write_bytes(b'\xef\xbb\xbf{"a": 1}')
        self.assertEqual(common.load_json(p), {"a": 1})


class Discovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_no_plugins_dir(self):
        self.assertEqual(common.list_plugin_dirs(self.root), [])

    def test_sorted_directories_only(self):
        (self.root / "plugins" / "beta").mkdir(parents=True)
        (self.root / "plugins" / "alpha").mkdir()
        (self.root / "plugins" / "notes.txt").write_text("x")
        names = [p.name for p in common.list_plugin_dirs(self.root)]
        self.assertEqual(names, ["alpha", "beta"])


class KebabCase(unittest.TestCase):
    def test_valid(self):
        for name in ("pdf-surgeon", "a", "tool2", "a-b-c"):
            self.assertTrue(common.KEBAB.match(name), name)

    def test_invalid(self):
        for name in ("Pdf", "a_b", "-a", "a-", "a--b", "", "a b"):
            self.assertFalse(common.KEBAB.match(name), name)


if __name__ == "__main__":
    unittest.main()
