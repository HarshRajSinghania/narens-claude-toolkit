"""Regression tests from the final review: surrogates, deep nesting and rename safety."""
import json
import unittest

import support  # noqa: F401
from test_wrap_router import RUN_ENTRY, line, list_request, list_response, make, parse, tool


class SurrogateTests(unittest.TestCase):
    """Servers written in JavaScript can emit a lone surrogate escape; it must not kill a session."""

    def test_a_lone_surrogate_on_a_patched_page_does_not_drop_the_response(self):
        router, _ = make({"run": RUN_ENTRY})
        router.client_line(list_request())
        raw = (
            b'{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"other","description":"cut \\ud83d here",'
            b'"inputSchema":{"type":"object"}},'
            + json.dumps(tool()).encode("utf-8")
            + b"]}}\n"
        )
        out = router.server_line(raw)
        message = json.loads(out.decode("utf-8"))
        self.assertEqual([t["name"] for t in message["result"]["tools"]], ["other", "search_orders"])
        self.assertEqual(message["result"]["tools"][0]["description"], "cut \ud83d here")

    def test_a_lone_surrogate_in_a_renamed_call_is_forwarded(self):
        router, _ = make({"run": RUN_ENTRY})
        router.client_line(list_request())
        router.server_line(list_response([tool()]))
        raw = (
            b'{"jsonrpc":"2.0","id":7,"method":"tools/call","params":{"name":"search_orders",'
            b'"arguments":{"q":"a \\ud83d b"}}}\n'
        )
        message = json.loads(router.client_line(raw).decode("utf-8"))
        self.assertEqual(message["params"]["name"], "run")
        self.assertEqual(message["params"]["arguments"]["q"], "a \ud83d b")

    def test_a_tool_too_deeply_nested_to_copy_is_forwarded_as_it_came(self):
        router, _ = make({"run": {"description": "d"}})
        router.client_line(list_request())
        depth = 450
        schema = '{"type":"object","properties":{"x":' * depth + '{"type":"string"}' + "}}" * depth
        raw = (
            '{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"run","description":"Runs it","inputSchema":'
            + schema
            + "}]}}\n"
        ).encode("utf-8")
        self.assertIs(router.server_line(raw), raw)


class RenameSafetyTests(unittest.TestCase):
    def call(self, name):
        return line({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": {}}})

    def test_a_real_tool_on_a_later_page_keeps_its_own_name(self):
        router, warnings = make({"run": {"rename": "b2"}})
        router.client_line(list_request(1))
        router.client_line(list_request(2))
        first = parse(router.server_line(list_response([tool()], 1)))
        self.assertEqual(first["result"]["tools"][0]["name"], "b2")
        router.server_line(list_response([tool("b2", "A real tool called b2")], 2))
        raw = self.call("b2")
        self.assertIs(router.client_line(raw), raw)  # reaches the real b2, not run
        self.assertTrue(any("b2" in text for text in warnings))

    def test_a_real_tool_that_appears_after_a_relist_keeps_its_own_name(self):
        router, _ = make({"run": {"rename": "b2"}})
        router.client_line(list_request(1))
        router.server_line(list_response([tool()], 1))
        router.client_line(list_request(2))
        router.server_line(list_response([tool(), tool("b2", "A real tool called b2")], 2))
        raw = self.call("b2")
        self.assertIs(router.client_line(raw), raw)

    def test_a_rename_onto_a_name_listed_on_an_earlier_page_is_skipped(self):
        router, warnings = make({"run": {"rename": "list_items"}})
        router.client_line(list_request(1))
        router.client_line(list_request(2))
        router.server_line(list_response([tool("list_items", "Lists items")], 1))
        second = parse(router.server_line(list_response([tool()], 2)))
        self.assertEqual(second["result"]["tools"][0]["name"], "run")
        self.assertEqual(router.rename_back, {})
        self.assertEqual(len(warnings), 1)


if __name__ == "__main__":
    unittest.main()
