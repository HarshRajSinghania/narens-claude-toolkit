import re
import unittest

import support
import mcp_fixer


class PackageTests(unittest.TestCase):
    def test_version_matches_pyproject(self):
        text = (support.ROOT / "pyproject.toml").read_text(encoding="utf-8")
        declared = re.search(r'^version = "([^"]+)"', text, re.MULTILINE).group(1)
        self.assertEqual(mcp_fixer.__version__, declared)

    def test_package_has_no_third_party_dependencies(self):
        text = (support.ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("dependencies = []", text)
        self.assertIn('requires-python = ">=3.9"', text)


if __name__ == "__main__":
    unittest.main()
