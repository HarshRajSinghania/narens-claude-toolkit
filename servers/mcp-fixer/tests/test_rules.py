import unittest

import support  # noqa: F401  (puts src/ on sys.path)
from mcp_fixer import rules


def tool(name="get_item", description="Fetch a single item by its identifier.", **extra):
    base = {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {"item_id": {"type": "string", "description": "Identifier of the item"}},
            "required": ["item_id"],
        },
    }
    base.update(extra)
    return base


def ids(findings):
    return [f["rule"] for f in findings]


def big_tool(count):
    """A tool with `count` described, typed properties: about 63 characters of JSON each."""
    properties = {
        f"p{i:04d}": {"type": "string", "description": "Parameter number one"} for i in range(count)
    }
    return {
        "name": "big_tool",
        "description": "A tool with a very large input schema.",
        "inputSchema": {"type": "object", "properties": properties, "required": ["p0000"]},
    }


class EstimateTokensTests(unittest.TestCase):
    def test_canonical_json_length_over_four_rounded_up(self):
        self.assertEqual(rules.estimate_tokens({"name": "a"}), 3)  # {"name":"a"} is 12 characters
        self.assertEqual(rules.estimate_tokens({"name": "abc"}), 4)  # 14 characters -> 3.5 -> 4

    def test_non_ascii_counts_characters_not_escapes(self):
        self.assertEqual(rules.estimate_tokens({"name": "é"}), 3)

    def test_key_order_does_not_matter(self):
        self.assertEqual(
            rules.estimate_tokens({"name": "a", "description": "b"}),
            rules.estimate_tokens({"description": "b", "name": "a"}),
        )


class DescriptionTests(unittest.TestCase):
    def test_a_good_description_is_clean(self):
        self.assertEqual(rules.check_description(tool()), [])

    def test_d001_missing_empty_blank_or_non_string(self):
        for value in (None, "", "   \n", 5, ["x"]):
            with self.subTest(value):
                t = tool()
                t["description"] = value
                self.assertEqual(ids(rules.check_description(t)), ["D001"])
        t = tool()
        del t["description"]
        self.assertEqual(ids(rules.check_description(t)), ["D001"])

    def test_d001_is_high_and_names_the_tool(self):
        found = rules.check_description(tool(description=""))[0]
        self.assertEqual((found["severity"], found["tool"]), ("high", "get_item"))
        self.assertEqual(found["data"], {"action": "add-description"})

    def test_d002_short_description_boundary(self):
        self.assertEqual(ids(rules.check_description(tool(description="x" * 19))), ["D002"])
        self.assertEqual(rules.check_description(tool(description="x" * 20)), [])
        self.assertEqual(ids(rules.check_description(tool(description="Runs it"))), ["D002"])

    def test_d002_ignores_surrounding_whitespace(self):
        self.assertEqual(ids(rules.check_description(tool(description="   short   "))), ["D002"])

    def test_d003_long_description_boundary(self):
        self.assertEqual(rules.check_description(tool(description="x" * 500)), [])
        found = rules.check_description(tool(description="x" * 501))
        self.assertEqual(ids(found), ["D003"])
        self.assertEqual(found[0]["data"], {"action": "shorten-description", "maxChars": 500})


class DuplicateTests(unittest.TestCase):
    def test_identical_descriptions_flag_both_tools(self):
        tools = [tool("a_tool", "Search the catalog for products."), tool("b_tool", "Search the catalog for products.")]
        found = rules.check_duplicates(tools)
        self.assertEqual([(i, f["rule"], f["tool"]) for i, f in found], [(0, "D004", "a_tool"), (1, "D004", "b_tool")])
        self.assertEqual(found[0][1]["data"], {"other": "b_tool", "overlap": 1.0})

    def test_overlap_of_exactly_point_eight_fires(self):
        tools = [tool("a_tool", "alpha beta gamma delta"), tool("b_tool", "alpha beta gamma delta epsilon")]
        self.assertEqual(len(rules.check_duplicates(tools)), 2)  # 4 of 5 words shared

    def test_overlap_below_point_eight_does_not(self):
        tools = [tool("a_tool", "alpha beta gamma"), tool("b_tool", "alpha beta gamma delta epsilon")]
        self.assertEqual(rules.check_duplicates(tools), [])  # 3 of 5 words shared

    def test_case_and_punctuation_do_not_hide_duplicates(self):
        tools = [tool("a_tool", "Search the Catalog!"), tool("b_tool", "search the catalog")]
        self.assertEqual(len(rules.check_duplicates(tools)), 2)

    def test_empty_descriptions_are_not_duplicates(self):
        tools = [tool("a_tool", ""), tool("b_tool", "")]
        self.assertEqual(rules.check_duplicates(tools), [])

    def test_three_tools_report_each_close_pair(self):
        tools = [tool("a_tool", "one two three four"), tool("b_tool", "one two three four"), tool("c_tool", "entirely different words here")]
        found = rules.check_duplicates(tools)
        self.assertEqual(sorted(i for i, _ in found), [0, 1])


class NameTests(unittest.TestCase):
    def test_n001_generic_names_whole_name_case_insensitive(self):
        for name in ("run", "Execute", "QUERY", "do", "action", "tool", "call"):
            with self.subTest(name):
                self.assertEqual(ids(rules.check_name(tool(name))), ["N001"])

    def test_descriptive_names_are_fine(self):
        for name in ("run_query", "search", "get_item", "executeJob"):
            with self.subTest(name):
                self.assertEqual(rules.check_name(tool(name)), [])


class ServerLevelTests(unittest.TestCase):
    def named(self, *names):
        return [{"name": n} for n in names]

    def test_n002_mixed_styles(self):
        found = rules.check_server(self.named("get_item", "list-items"))
        self.assertEqual(ids(found), ["N002"])
        self.assertIsNone(found[0]["tool"])
        self.assertEqual(found[0]["data"], {"styles": {"kebab-case": 1, "snake_case": 1}})

    def test_n002_one_style_is_fine(self):
        for names in (("get_item", "list_items"), ("getItem", "listItems"), ("get-item", "list-items")):
            with self.subTest(names):
                self.assertEqual(rules.check_server(self.named(*names)), [])

    def test_n002_single_words_have_no_style(self):
        self.assertEqual(rules.check_server(self.named("get", "list")), [])
        self.assertEqual(ids(rules.check_server(self.named("get_item", "listItems", "x"))), ["N002"])

    def test_t001_tool_count_boundary(self):
        self.assertEqual(rules.check_server(self.named(*[f"tool_{i}" for i in range(40)])), [])
        found = rules.check_server(self.named(*[f"tool_{i}" for i in range(41)]))
        self.assertEqual(ids(found), ["T001"])
        self.assertEqual(found[0]["data"], {"toolCount": 41})

    def test_t002_size_thresholds(self):
        self.assertLess(rules.estimate_tokens(big_tool(400)), 8000)
        self.assertEqual(rules.check_server([big_tool(400)]), [])
        self.assertTrue(8000 < rules.estimate_tokens(big_tool(800)) <= 20000)
        found = rules.check_server([big_tool(800)])
        self.assertEqual([(f["rule"], f["severity"]) for f in found], [("T002", "medium")])
        self.assertGreater(rules.estimate_tokens(big_tool(2000)), 20000)
        found = rules.check_server([big_tool(2000)])
        self.assertEqual([(f["rule"], f["severity"]) for f in found], [("T002", "high")])

    def test_server_findings_have_no_tool(self):
        for f in rules.check_server([big_tool(2000)]):
            self.assertIsNone(f["tool"])


class MalformedTests(unittest.TestCase):
    def test_m001_for_anything_that_is_not_a_named_object(self):
        for index, entry in enumerate(("oops", None, 5, {"description": "no name"}, {"name": ""}, {"name": 7})):
            with self.subTest(entry):
                found = rules.malformed_finding(index, entry)
                self.assertEqual((found["rule"], found["severity"], found["tool"]), ("M001", "high", None))
                self.assertIn(str(index), found["message"])


class FindingShapeTests(unittest.TestCase):
    def test_every_finding_has_the_same_keys(self):
        f = rules.finding("D001", "high", "msg")
        self.assertEqual(set(f), {"rule", "severity", "tool", "param", "message", "evidence", "fix", "data"})
        self.assertEqual((f["tool"], f["param"], f["evidence"], f["fix"], f["data"]), (None, None, "", "", {}))


if __name__ == "__main__":
    unittest.main()
