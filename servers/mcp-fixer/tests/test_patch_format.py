import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from mcp_fixer import patch_format
from mcp_fixer.patch_format import PatchError

BASE = "a" * 64


def tool():
    return {
        "name": "run",
        "description": "Runs it",
        "inputSchema": {
            "type": "object",
            "properties": {"order": {"type": "string", "description": "Sort order"}, "q": {}},
            "required": ["q"],
        },
    }


def patch(tools=None, **top):
    data = {"patchVersion": 1, "tools": {} if tools is None else tools}
    data.update(top)
    return data


class FingerprintTests(unittest.TestCase):
    def test_is_64_lowercase_hex(self):
        self.assertRegex(patch_format.fingerprint(tool()), r"^[0-9a-f]{64}$")

    def test_key_order_does_not_matter(self):
        a = {"name": "x", "description": "d"}
        b = {"description": "d", "name": "x"}
        self.assertEqual(patch_format.fingerprint(a), patch_format.fingerprint(b))

    def test_any_change_changes_it(self):
        changed = tool()
        changed["inputSchema"]["properties"]["q"] = {"type": "string"}
        self.assertNotEqual(patch_format.fingerprint(tool()), patch_format.fingerprint(changed))

    def test_non_ascii_and_a_lone_surrogate_do_not_crash(self):
        patch_format.fingerprint({"name": "résumé 日本語"})
        patch_format.fingerprint(json.loads('{"name": "\\ud800"}'))

    def test_value_is_the_sha256_of_the_canonical_json(self):
        expected = hashlib.sha256(b'{"description":"d","name":"a"}').hexdigest()
        self.assertEqual(patch_format.fingerprint({"name": "a", "description": "d"}), expected)


class ValidationTests(unittest.TestCase):
    def assert_invalid(self, data, fragment):
        with self.assertRaises(PatchError) as ctx:
            patch_format.validate_patch(data)
        self.assertIn(fragment, str(ctx.exception))
        self.assertNotIn("\n", str(ctx.exception))

    def test_a_full_valid_patch_passes_and_is_returned(self):
        data = patch(
            {
                "run": {
                    "base": BASE,
                    "rename": "search_orders",
                    "description": "Search orders.",
                    "params": {"order": {"description": "d", "type": ["string", "null"], "enum": ["a", 1, True, None, 2.5], "default": "a"}},
                    "required": ["order"],
                    "review": ["check it"],
                    "todo": [{"rule": "P001", "param": "q", "hint": "describe"}, {"rule": "D001"}],
                    "context": {"description": "x", "params": {}},
                }
            },
            source={"serverName": "s", "serverVersion": None},
            notes=["a note"],
        )
        self.assertIs(patch_format.validate_patch(data), data)

    def test_an_empty_patch_is_valid(self):
        patch_format.validate_patch(patch())

    def test_top_level_problems(self):
        self.assert_invalid([], "the patch must be a JSON object")
        self.assert_invalid(patch(extra=1), "unknown field 'extra' in the patch")
        for version in (None, 0, 2, "1", True, 1.0):
            with self.subTest(version):
                data = patch()
                data["patchVersion"] = version
                self.assert_invalid(data, "patchVersion must be 1")
        data = patch()
        del data["patchVersion"]
        self.assert_invalid(data, "patchVersion must be 1")
        for tools in (None, [], "x"):
            with self.subTest(tools):
                self.assert_invalid({"patchVersion": 1, "tools": tools}, "tools must be an object")
        self.assert_invalid({"patchVersion": 1}, "tools must be an object")
        self.assert_invalid(patch(source=[]), "source must be an object")
        self.assert_invalid(patch(notes="x"), "notes must be a list of strings")
        self.assert_invalid(patch(notes=[1]), "notes must be a list of strings")

    def test_entry_problems_name_the_tool_and_the_field(self):
        cases = [
            ({"run": 5}, "tool 'run': must be an object"),
            ({"run": {"nope": 1}}, "tool 'run': unknown field 'nope'"),
            ({"run": {"base": "abc"}}, "tool 'run': base must be a 64-character lowercase hex SHA-256"),
            ({"run": {"base": "A" * 64}}, "base must be a 64-character lowercase hex"),
            ({"run": {"base": 5}}, "base must be a 64-character lowercase hex"),
            ({"run": {"rename": ""}}, "rename must be a non-empty string different from the tool's name"),
            ({"run": {"rename": 5}}, "rename must be a non-empty string different from the tool's name"),
            ({"run": {"rename": "run"}}, "rename must be a non-empty string different from the tool's name"),
            ({"run": {"description": 5}}, "description must be a string"),
            ({"run": {"params": []}}, "params must be an object"),
            ({"run": {"params": {"q": 5}}}, "params['q'] must be an object"),
            ({"run": {"params": {"q": {"x": 1}}}}, "params['q'] has unknown field 'x'"),
            ({"run": {"params": {"q": {"description": 5}}}}, "params['q'].description must be a string"),
            ({"run": {"params": {"q": {"type": 5}}}}, "params['q'].type must be a string or a list of strings"),
            ({"run": {"params": {"q": {"type": ["a", 5]}}}}, "params['q'].type must be a string or a list of strings"),
            ({"run": {"params": {"q": {"enum": []}}}}, "params['q'].enum must be a non-empty list"),
            ({"run": {"params": {"q": {"enum": "ab"}}}}, "params['q'].enum must be a non-empty list"),
            ({"run": {"params": {"q": {"enum": [["a"]]}}}}, "params['q'].enum must be a non-empty list"),
            ({"run": {"params": {"q": {"enum": [float("nan")]}}}}, "params['q'].enum must be a non-empty list"),
            ({"run": {"required": "q"}}, "required must be a list of unique strings"),
            ({"run": {"required": ["q", "q"]}}, "required must be a list of unique strings"),
            ({"run": {"required": [1]}}, "required must be a list of unique strings"),
            ({"run": {"review": "x"}}, "review must be a list of strings"),
            ({"run": {"review": [1]}}, "review must be a list of strings"),
            ({"run": {"todo": "x"}}, "todo must be a list"),
            ({"run": {"todo": ["x"]}}, "todo[0] must be an object with a string rule"),
            ({"run": {"todo": [{"hint": "h"}]}}, "todo[0] must be an object with a string rule"),
            ({"run": {"todo": [{"rule": "P001", "extra": 1}]}}, "todo[0] must be an object with a string rule"),
            ({"run": {"todo": [{"rule": "P001", "param": 5}]}}, "todo[0] must be an object with a string rule"),
            ({"run": {"context": []}}, "context must be an object"),
        ]
        for tools, fragment in cases:
            with self.subTest(fragment):
                self.assert_invalid(patch(tools), fragment)

    def test_collisions_between_renames(self):
        self.assert_invalid(
            patch({"a": {"rename": "z"}, "b": {"rename": "z"}}),
            "tools 'a' and 'b' are both renamed to 'z'",
        )
        self.assert_invalid(
            patch({"a": {"rename": "b"}, "b": {"description": "d"}}),
            "tool 'a' is renamed to 'b', which is another tool in the patch",
        )

    def test_a_swap_of_two_renames_is_still_refused(self):
        self.assert_invalid(
            patch({"a": {"rename": "b"}, "b": {"rename": "a"}}),
            "which is another tool in the patch",
        )


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, data, name="p.json"):
        path = self.dir / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return str(path)

    def test_a_valid_file_loads(self):
        path = self.write(json.dumps(patch({"run": {"description": "d"}})))
        self.assertEqual(patch_format.load_patch(path)["tools"]["run"]["description"], "d")

    def test_a_bom_is_tolerated(self):
        path = self.write(b"\xef\xbb\xbf" + json.dumps(patch()).encode("utf-8"))
        self.assertEqual(patch_format.load_patch(path)["patchVersion"], 1)

    def test_problems_are_one_line_errors_with_the_path(self):
        cases = {
            "missing": (str(self.dir / "nope.json"), "cannot read"),
            "directory": (str(self.dir), "cannot read"),
            "not utf-8": (self.write(b"\x80\x81", "bad.json"), "is not UTF-8 text"),
            "not json": (self.write("{nope", "nj.json"), "is not valid JSON"),
            # Python 3.12 reports an unterminated deep array as a plain parse error, 3.11 and 3.13
            # as "nested too deeply"; both are one line starting "is not valid JSON".
            "deep": (self.write("[" * 5000, "deep.json"), "is not valid JSON"),
            "invalid patch": (self.write(json.dumps({"patchVersion": 2, "tools": {}}), "inv.json"), "patchVersion must be 1"),
        }
        for label, (path, fragment) in cases.items():
            with self.subTest(label):
                with self.assertRaises(PatchError) as ctx:
                    patch_format.load_patch(path)
                self.assertIn(fragment, str(ctx.exception))
                self.assertIn(Path(path).name, str(ctx.exception))
                self.assertNotIn("\n", str(ctx.exception))


class ApplyTests(unittest.TestCase):
    def test_an_empty_entry_gives_an_equal_copy_and_no_warnings(self):
        original = tool()
        new, warnings = patch_format.apply_entry(original, {})
        self.assertEqual((new, warnings), (original, []))
        self.assertIsNot(new, original)

    def test_the_input_is_never_mutated(self):
        original = tool()
        snapshot = copy.deepcopy(original)
        entry = {"rename": "r", "description": "d", "params": {"order": {"enum": ["a"]}}, "required": ["order"]}
        patch_format.apply_entry(original, entry)
        self.assertEqual(original, snapshot)

    def test_description_and_rename(self):
        new, _ = patch_format.apply_entry(tool(), {"rename": "search_orders", "description": "Search orders."})
        self.assertEqual((new["name"], new["description"]), ("search_orders", "Search orders."))

    def test_a_missing_description_is_added_at_the_end(self):
        t = tool()
        del t["description"]
        new, _ = patch_format.apply_entry(t, {"description": "d"})
        self.assertEqual(list(new), ["name", "inputSchema", "description"])

    def test_param_changes_merge_into_the_property(self):
        new, warnings = patch_format.apply_entry(
            tool(), {"params": {"order": {"enum": ["asc", "desc"], "default": "asc"}}}
        )
        order = new["inputSchema"]["properties"]["order"]
        self.assertEqual(order, {"type": "string", "description": "Sort order", "enum": ["asc", "desc"], "default": "asc"})
        self.assertEqual(warnings, [])

    def test_a_param_can_have_its_description_and_type_replaced(self):
        new, _ = patch_format.apply_entry(tool(), {"params": {"q": {"description": "Search text", "type": "string"}}})
        self.assertEqual(new["inputSchema"]["properties"]["q"], {"description": "Search text", "type": "string"})

    def test_a_property_that_is_not_an_object_becomes_one(self):
        t = tool()
        t["inputSchema"]["properties"]["q"] = "nope"
        new, _ = patch_format.apply_entry(t, {"params": {"q": {"type": "string"}}})
        self.assertEqual(new["inputSchema"]["properties"]["q"], {"type": "string"})

    def test_a_param_that_does_not_exist_is_skipped_with_a_warning(self):
        new, warnings = patch_format.apply_entry(tool(), {"params": {"ghost": {"type": "string"}}})
        self.assertEqual(new, tool())
        self.assertEqual(warnings, ["parameter 'ghost' is not in tool 'run'; skipped"])

    def test_param_values_are_copied_not_shared(self):
        entry = {"params": {"order": {"enum": ["a", "b"]}}}
        new, _ = patch_format.apply_entry(tool(), entry)
        entry["params"]["order"]["enum"].append("c")
        self.assertEqual(new["inputSchema"]["properties"]["order"]["enum"], ["a", "b"])

    def test_required_keeps_only_names_that_exist(self):
        new, warnings = patch_format.apply_entry(tool(), {"required": ["q", "ghost", "order"]})
        self.assertEqual(new["inputSchema"]["required"], ["q", "order"])
        self.assertEqual(warnings, ["required name 'ghost' is not a parameter of tool 'run'; dropped"])

    def test_no_input_schema_skips_params_and_required_with_warnings(self):
        t = {"name": "run", "description": "d"}
        new, warnings = patch_format.apply_entry(t, {"params": {"q": {"type": "string"}}, "required": ["q"], "description": "e"})
        self.assertEqual(new, {"name": "run", "description": "e"})
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all("tool 'run'" in w for w in warnings))

    def test_notes_are_ignored(self):
        entry = {"review": ["x"], "todo": [{"rule": "P001"}], "context": {"description": "d"}, "base": BASE}
        new, warnings = patch_format.apply_entry(tool(), entry)
        self.assertEqual((new, warnings), (tool(), []))


if __name__ == "__main__":
    unittest.main()
