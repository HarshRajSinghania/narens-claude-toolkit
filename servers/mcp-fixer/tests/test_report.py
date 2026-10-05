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


class UntrustedTextTests(unittest.TestCase):
    """Tool lists from remote servers are untrusted: nothing may steer the terminal."""

    def render(self, **fields):
        tool = {"name": "evil\x1b]0;pwned\x07\nfake line", "description": "bad\x1b[2Jtext",
                "inputSchema": {"type": "object", "properties": {"p\x1b[31m": {}}}}
        tool.update(fields)
        source = {"kind": "stdio", "protocolVersion": "2025\x1b[0m", "serverName": "srv\x07", "serverVersion": "1\n2"}
        return report_module.render_text(score.score_tools([tool], source))

    def test_no_control_character_reaches_the_text_report(self):
        text = self.render()
        for char in text:
            self.assertTrue(char == "\n" or ord(char) >= 32, repr(char))
        self.assertNotIn("\x7f", text)

    def test_escapes_are_shown_so_the_reader_can_see_what_was_there(self):
        text = self.render()
        self.assertIn("\\x1b", text)
        self.assertIn("\\x07", text)
        self.assertIn("\\n", text)

    def test_a_newline_in_a_name_cannot_forge_a_line(self):
        for line in self.render().splitlines():
            self.assertFalse(line.startswith("fake line"), line)

    def test_ordinary_non_ascii_text_is_left_alone(self):
        tool = {"name": "recuperer", "description": "", "inputSchema": {"type": "object", "properties": {}}}
        tool["description"] = ""
        text = report_module.render_text(score.score_tools([dict(tool, name="日本語_tool")]))
        self.assertIn("日本語_tool", text)


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
