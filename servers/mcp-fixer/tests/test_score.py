import unittest

import support  # noqa: F401
from mcp_fixer import score


def clean(name="get_item", description="Fetch a single item by its identifier."):
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": {"item_id": {"type": "string", "description": "Identifier of the item"}},
            "required": ["item_id"],
        },
    }


def rule_ids(report):
    return [f["rule"] for f in report["findings"]]


class ScoreTests(unittest.TestCase):
    def test_a_clean_server_scores_100(self):
        report = score.score_tools([clean("get_item", "Fetch a single item by its identifier."),
                                    clean("list_orders", "List the orders placed by one customer.")])
        self.assertEqual(report["score"], 100)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["notes"], [])
        self.assertEqual(report["schemaVersion"], 1)

    def test_findings_take_points_off_the_tool(self):
        # "run" is generic (N001, -10) and "Runs it" is 7 characters (D002, -10): 80.
        report = score.score_tools([clean("run", "Runs it")])
        self.assertEqual(report["score"], 80)
        self.assertEqual(rule_ids(report), ["D002", "N001"])
        self.assertEqual(report["metrics"]["perTool"]["run"]["score"], 80)
        self.assertEqual(report["metrics"]["perTool"]["run"]["findings"], 2)

    def test_the_server_score_is_the_mean_rounded_half_up(self):
        # tool scores 75 (D001, high -25) and 100: mean 87.5 -> 88
        broken = clean("alpha_tool", "")
        report = score.score_tools([broken, clean("beta_tool", "Fetch a single item by its identifier.")])
        self.assertEqual(report["score"], 88)

    def test_half_up_is_not_bankers_rounding(self):
        # tool scores 75 (D001, -25) and 90 (P001, -10): mean 82.5, half-up 83 (round() gives 82)
        undescribed = clean("alpha_tool", "")
        quiet = clean("beta_tool", "Fetch a single item by its identifier.")
        quiet["inputSchema"]["properties"]["item_id"].pop("description")
        report = score.score_tools([undescribed, quiet])
        self.assertEqual(sorted(v["score"] for v in report["metrics"]["perTool"].values()), [75, 90])
        self.assertEqual(report["score"], 83)

    def test_a_tool_never_scores_below_zero(self):
        props = {f"p{i}": {} for i in range(10)}  # each: P001 + P002 = -20, ten of them
        tool = {"name": "messy_tool", "description": "A tool with plenty of problems in it.",
                "inputSchema": {"type": "object", "properties": props}}
        report = score.score_tools([tool])
        self.assertEqual(report["metrics"]["perTool"]["messy_tool"]["score"], 0)
        self.assertEqual(report["score"], 0)

    def test_t001_takes_five_points_off_the_server(self):
        tools = [clean(f"tool_{i}", f"Describe topic t{i:03d} thoroughly") for i in range(41)]
        report = score.score_tools(tools)
        self.assertEqual(rule_ids(report), ["T001"])
        self.assertEqual(report["score"], 95)

    def test_t002_takes_five_or_fifteen_points_off(self):
        def big(count):
            props = {f"p{i:04d}": {"type": "string", "description": "Parameter number one"} for i in range(count)}
            return {"name": "big_tool", "description": "A tool with a very large input schema.",
                    "inputSchema": {"type": "object", "properties": props, "required": ["p0000"]}}
        medium = score.score_tools([big(800)])
        self.assertEqual((rule_ids(medium), medium["score"]), (["T002"], 95))
        high = score.score_tools([big(2000)])
        self.assertEqual((rule_ids(high), high["score"]), (["T002"], 85))

    def test_n002_takes_four_points_off(self):
        report = score.score_tools([clean("get_item", "Fetch a single item by its identifier."),
                                    clean("listItems", "List the orders placed by one customer.")])
        self.assertEqual((rule_ids(report), report["score"]), (["N002"], 96))

    def test_penalties_stack_and_the_score_is_clamped(self):
        tools = [clean(f"tool_{i}", f"Describe topic t{i:03d} thoroughly") for i in range(41)]
        tools[0]["name"] = "listItems"  # N002 (-4) on top of T001 (-5)
        report = score.score_tools(tools)
        self.assertEqual(report["score"], 91)
        report = score.score_tools([{"name": f"t{i}"} for i in range(200)] + ["bad"] * 20)
        self.assertEqual(report["score"], 0)

    def test_a_malformed_entry_costs_25_and_is_skipped(self):
        report = score.score_tools([clean(), "oops"])
        self.assertEqual(rule_ids(report), ["M001"])
        self.assertEqual(report["score"], 75)
        self.assertEqual(report["metrics"]["toolCount"], 1)
        self.assertEqual(list(report["metrics"]["perTool"]), ["get_item"])

    def test_an_empty_list_scores_100_with_a_note(self):
        report = score.score_tools([])
        self.assertEqual((report["score"], report["findings"]), (100, []))
        self.assertEqual(report["notes"], ["no tools listed"])
        self.assertEqual(report["metrics"]["toolCount"], 0)

    def test_duplicate_names_are_scored_as_separate_entries(self):
        report = score.score_tools([clean(), clean()])
        self.assertEqual(list(report["metrics"]["perTool"]), ["get_item", "get_item#2"])
        self.assertEqual(rule_ids(report), ["D004", "D004"])
        self.assertEqual(report["score"], 90)

    def test_pair_findings_count_against_both_tools(self):
        a = clean("alpha_tool", "Search the catalog for products.")
        b = clean("beta_tool", "Search the catalog for products.")
        report = score.score_tools([a, b])
        self.assertEqual([report["metrics"]["perTool"][k]["score"] for k in ("alpha_tool", "beta_tool")], [90, 90])

    def test_metrics_count_tokens(self):
        report = score.score_tools([clean(), clean("list_orders", "List the orders placed by one customer.")])
        per = report["metrics"]["perTool"]
        self.assertEqual(report["metrics"]["estimatedTokens"], sum(v["estimatedTokens"] for v in per.values()))
        self.assertGreater(report["metrics"]["estimatedTokens"], 0)

    def test_source_defaults_to_a_file_with_unknown_server_details(self):
        self.assertEqual(score.score_tools([])["source"],
                         {"kind": "file", "protocolVersion": None, "serverName": None, "serverVersion": None})
        given = {"kind": "stdio", "protocolVersion": "2025-06-18", "serverName": "x", "serverVersion": "1"}
        self.assertEqual(score.score_tools([], given)["source"], given)

    def test_findings_are_sorted_and_stable(self):
        tools = [clean("zeta_tool", ""), clean("alpha_tool", "")]
        first = score.score_tools(tools)
        self.assertEqual([f["tool"] for f in first["findings"]], ["alpha_tool", "zeta_tool"])
        self.assertEqual(first, score.score_tools(tools))

    def test_non_ascii_text_is_fine(self):
        report = score.score_tools([clean("recuperer", "Récupère l'élément — 日本語 is supported")])
        self.assertEqual(report["findings"], [])


if __name__ == "__main__":
    unittest.main()
