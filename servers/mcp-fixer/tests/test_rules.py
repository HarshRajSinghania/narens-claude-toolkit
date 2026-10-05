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


def with_params(**props):
    """A tool whose input schema has exactly these properties (and a required list)."""
    return {
        "name": "get_item",
        "description": "Fetch a single item by its identifier.",
        "inputSchema": {"type": "object", "properties": props, "required": list(props)},
    }


def str_param(description):
    return {"type": "string", "description": description}


class EnumExtractionTests(unittest.TestCase):
    def test_values_listed_in_prose_are_found(self):
        cases = {
            "Sort order, one of: asc, desc": ["asc", "desc"],
            "Either 'json' or 'csv'.": ["json", "csv"],
            "Output format. Options: json, csv, or xml": ["json", "csv", "xml"],
            "Allowed values are a, b, c": ["a", "b", "c"],
            "One of the following: low, medium, high": ["low", "medium", "high"],
            "Status: 'open', 'closed', or 'merged'": ["open", "closed", "merged"],
            "Valid values: red | green | blue": ["red", "green", "blue"],
            "The kind. Can be file or folder.": ["file", "folder"],
        }
        for text, expected in cases.items():
            with self.subTest(text):
                self.assertEqual(rules.extract_enum_values(text), expected)

    def test_prose_that_is_not_a_value_list_is_ignored(self):
        for text in (
            "Can be used to filter by name",
            "Must be a valid path or URL",
            "One of the supported formats",
            "Path to a file or URL",
            "Number of items to return",
            "Additional options for the request",
            "Name like 'foo' or 'bar'",
            "",
            None,
            5,
        ):
            with self.subTest(text):
                self.assertEqual(rules.extract_enum_values(text), [])

    def test_examples_are_not_allowed_values(self):
        for text in (
            "Comma-separated list of labels, e.g. 'bug', 'enhancement', 'docs'",
            "Timezone, e.g. 'UTC', 'America/New_York', 'Europe/London'",
            "Glob pattern such as '*.py', '**/*.ts', 'src/*'",
            "Supports operators like 'AND', 'OR', 'NOT'",
            "Language code such as 'en', 'fr' or 'de'",
            "For example one of: a, b",
            "Examples: 'x', 'y', 'z'",
            "Region, for instance 'eu', 'us' or 'ap'",
        ):
            with self.subTest(text):
                self.assertEqual(rules.extract_enum_values(text), [])

    def test_a_real_list_before_an_example_is_still_found(self):
        self.assertEqual(rules.extract_enum_values("One of: asc, desc (e.g. asc)"), ["asc", "desc"])

    def test_words_that_merely_contain_a_marker_do_not_cut_the_text(self):
        self.assertEqual(rules.extract_enum_values("Unlikely to change. One of: a, b"), ["a", "b"])

    def test_at_most_twenty_values(self):
        text = "One of: " + ", ".join(f"v{i}" for i in range(30))
        self.assertEqual(len(rules.extract_enum_values(text)), 20)

    def test_quoted_values_repeat_once(self):
        self.assertEqual(rules.extract_enum_values("'a' then 'b' then 'a' then 'c'"), ["a", "b", "c"])


class SchemaDepthTests(unittest.TestCase):
    def test_depth_counts_levels_of_nested_schemas(self):
        self.assertEqual(rules.schema_depth({"type": "string"}), 0)
        self.assertEqual(rules.schema_depth({"type": "object", "properties": {"a": {"type": "string"}}}), 1)
        nested = {"type": "object", "properties": {"a": {"type": "object", "properties": {"b": {"type": "string"}}}}}
        self.assertEqual(rules.schema_depth(nested), 2)

    def test_depth_follows_items_and_combinators(self):
        arr = {"type": "array", "items": {"type": "object", "properties": {"x": {"type": "string"}}}}
        self.assertEqual(rules.schema_depth(arr), 2)
        self.assertEqual(rules.schema_depth({"anyOf": [{"type": "object", "properties": {"x": {}}}]}), 2)
        self.assertEqual(rules.schema_depth({"items": [{"type": "string"}]}), 1)

    def test_garbage_and_runaway_nesting_are_safe(self):
        self.assertEqual(rules.schema_depth("nope"), 0)
        self.assertEqual(rules.schema_depth({"properties": {"a": 5}}), 1)
        deep = {"type": "string"}
        for _ in range(500):
            deep = {"type": "object", "properties": {"x": deep}}
        self.assertGreater(rules.schema_depth(deep), 3)  # capped, no RecursionError


class SchemaRuleTests(unittest.TestCase):
    def test_a_clean_tool_has_no_schema_findings(self):
        self.assertEqual(rules.check_schema(tool()), [])

    def test_p004_missing_or_not_an_object_schema(self):
        cases = [
            ("missing", None),
            ("empty", {}),
            ("string schema", {"type": "string"}),
            ("not a dict", "x"),
        ]
        for label, schema in cases:
            with self.subTest(label):
                t = tool()
                if schema is None:
                    del t["inputSchema"]
                else:
                    t["inputSchema"] = schema
                found = rules.check_schema(t)
                self.assertEqual(ids(found), ["P004"])
                self.assertEqual(found[0]["severity"], "high")

    def test_p001_parameter_without_a_description(self):
        for description in (None, "", "   "):
            with self.subTest(description):
                prop = {"type": "string"}
                if description is not None:
                    prop["description"] = description
                found = rules.check_schema(with_params(q=prop))
                self.assertEqual(ids(found), ["P001"])
                self.assertEqual(found[0]["param"], "q")

    def test_p002_parameter_without_a_type(self):
        found = rules.check_schema(with_params(q={"description": "A search query"}))
        self.assertEqual(ids(found), ["P002"])

    def test_p002_not_raised_when_enum_oneof_anyof_or_ref_stand_in_for_type(self):
        for extra in ({"enum": ["a", "b"]}, {"oneOf": [{"type": "string"}]}, {"anyOf": [{"type": "string"}]}, {"$ref": "#/x"}):
            with self.subTest(extra):
                prop = {"description": "A value"}
                prop.update(extra)
                self.assertEqual(rules.check_schema(with_params(q=prop)), [])

    def test_p002_not_raised_for_allof_or_const(self):
        # older Pydantic emits allOf with a $ref for an enum-typed field; const pins one value
        for extra in ({"allOf": [{"$ref": "#/definitions/Color"}]}, {"const": "fixed"}):
            with self.subTest(extra):
                prop = {"description": "A value"}
                prop.update(extra)
                self.assertEqual(rules.check_schema(with_params(q=prop)), [])

    def test_an_empty_property_schema_is_both_undescribed_and_untyped(self):
        self.assertEqual(ids(rules.check_schema(with_params(q={}))), ["P001", "P002"])
        self.assertEqual(ids(rules.check_schema(with_params(q="nope"))), ["P001", "P002"])

    def test_p003_enum_values_listed_in_prose(self):
        found = rules.check_schema(with_params(order=str_param("Sort order, one of: asc, desc")))
        self.assertEqual(ids(found), ["P003"])
        self.assertEqual(found[0]["data"], {"action": "add-enum", "values": ["asc", "desc"]})
        self.assertEqual(found[0]["evidence"], "asc, desc")
        self.assertEqual(found[0]["param"], "order")

    def test_p003_not_raised_with_an_enum_or_a_non_string_type_or_plain_prose(self):
        self.assertEqual(rules.check_schema(with_params(order={"type": "string", "description": "one of: asc, desc", "enum": ["asc", "desc"]})), [])
        self.assertEqual(rules.check_schema(with_params(order={"type": "integer", "description": "one of: 1, 2"})), [])
        self.assertEqual(rules.check_schema(with_params(path=str_param("Must be a valid path or URL"))), [])

    def test_p005_two_parameters_and_no_required_list(self):
        t = with_params(a=str_param("First value here"), b=str_param("Second value here"))
        for required in (None, []):
            with self.subTest(required):
                if required is None:
                    del t["inputSchema"]["required"]
                else:
                    t["inputSchema"]["required"] = required
                self.assertEqual(ids(rules.check_schema(t)), ["P005"])

    def test_p005_not_raised_with_a_required_list_or_a_single_parameter(self):
        self.assertEqual(rules.check_schema(with_params(a=str_param("First value here"), b=str_param("Second value here"))), [])
        t = with_params(a=str_param("First value here"))
        del t["inputSchema"]["required"]
        self.assertEqual(rules.check_schema(t), [])

    def test_p006_nesting_deeper_than_three_levels(self):
        leaf = {"type": "string", "description": "A leaf value"}
        three = {"type": "object", "description": "a", "properties": {"b": {"type": "object", "description": "b", "properties": {"c": {"type": "object", "description": "c", "properties": {"d": leaf}}}}}}
        t = with_params(a=three)
        self.assertEqual([f["rule"] for f in rules.check_schema(t) if f["rule"] == "P006"], ["P006"])
        shallow = {"type": "object", "description": "a", "properties": {"b": {"type": "object", "description": "b", "properties": {"c": leaf}}}}
        self.assertEqual([f for f in rules.check_schema(with_params(a=shallow)) if f["rule"] == "P006"], [])

    def test_only_top_level_parameters_get_p001_to_p003(self):
        inner = {"type": "object", "description": "wrapper", "properties": {"x": {}}}
        self.assertEqual(rules.check_schema(with_params(a=inner)), [])

    def test_properties_that_is_not_an_object_means_no_parameters(self):
        t = tool()
        t["inputSchema"] = {"type": "object", "properties": "nope"}
        self.assertEqual(rules.check_schema(t), [])


if __name__ == "__main__":
    unittest.main()
