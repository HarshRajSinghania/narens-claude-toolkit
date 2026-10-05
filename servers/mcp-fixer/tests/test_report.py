import json
import unittest

import support  # noqa: F401
from mcp_fixer import report as report_module
from mcp_fixer import score


def sample_tools():
    good = {"name": "beta_tool", "description": "Fetch a single item by its identifier.",
            "inputSchema": {"type": "object", "properties": {"item_id": {"type": "string", "description": "Identifier of the item"}}, "required": ["item_id"]}}
    broken = dict(good, name="alpha_tool", description="")
    return [broken, good]


class JsonTests(unittest.TestCase):
    def test_json_parses_and_keeps_the_pinned_shape(self):
        data = json.loads(report_module.render_json(score.score_tools(sample_tools())))
        self.assertEqual(list(data), ["schemaVersion", "source", "score", "metrics", "findings", "notes"])
        self.assertEqual(data["score"], 88)
        self.assertEqual(list(data["metrics"]), ["toolCount", "estimatedTokens", "perTool"])
        self.assertEqual(
            list(data["findings"][0]),
            ["rule", "severity", "tool", "param", "message", "evidence", "fix", "data"],
        )

    def test_json_is_byte_identical_on_a_repeat_run(self):
        first = report_module.render_json(score.score_tools(sample_tools()))
        second = report_module.render_json(score.score_tools(sample_tools()))
        self.assertEqual(first, second)
        self.assertTrue(first.endswith("\n"))

    def test_json_keeps_non_ascii_text_readable(self):
        tool = {"name": "recuperer", "description": "Récupère l'élément — 日本語",
                "inputSchema": {"type": "object", "properties": {}}}
        text = report_module.render_json(score.score_tools([tool]))
        self.assertNotIn("\\u", text)


class TextTests(unittest.TestCase):
    def setUp(self):
        self.text = report_module.render_text(score.score_tools(sample_tools()))

    def test_headline_and_metrics(self):
        self.assertIn("mcp-fixer score: 88/100", self.text)
        self.assertIn("source: tool list file", self.text)
        self.assertRegex(self.text, r"tools: 2, estimated definition size: [\d,]+ tokens")

    def test_per_tool_table_and_findings(self):
        self.assertIn("alpha_tool", self.text)
        self.assertIn("beta_tool", self.text)
        self.assertIn("[high] D001 alpha_tool: no description", self.text)
        self.assertIn("fix:", self.text)

    def test_server_findings_are_labelled_server(self):
        tools = sample_tools()
        tools.append(dict(tools[1], name="listItems", description="List the orders placed by one customer."))
        text = report_module.render_text(score.score_tools(tools))
        self.assertIn("N002 server: tool names mix naming styles", text)

    def test_param_findings_name_the_parameter(self):
        tool = {"name": "get_item", "description": "Fetch a single item by its identifier.",
                "inputSchema": {"type": "object", "properties": {"q": {}}, "required": ["q"]}}
        text = report_module.render_text(score.score_tools([tool]))
        self.assertIn("P001 get_item.q:", text)

    def test_stdio_source_shows_the_server(self):
        source = {"kind": "stdio", "protocolVersion": "2025-06-18", "serverName": "fake-server", "serverVersion": "1.2.3"}
        text = report_module.render_text(score.score_tools(sample_tools(), source))
        self.assertIn("server: fake-server 1.2.3 (protocol 2025-06-18)", text)

    def test_an_empty_list_shows_the_note(self):
        text = report_module.render_text(score.score_tools([]))
        self.assertIn("mcp-fixer score: 100/100", text)
        self.assertIn("note: no tools listed", text)

    def test_non_ascii_text_renders(self):
        tool = {"name": "recuperer", "description": "", "inputSchema": {"type": "object", "properties": {}}}
        text = report_module.render_text(score.score_tools([tool]))
        self.assertIsInstance(text, str)


if __name__ == "__main__":
    unittest.main()
