import contextlib
import io
import json
import unittest

import support  # noqa: F401
from mcp_fixer import patch_format
from mcp_fixer.wrap import Router


def tool(name="run", description="Runs it"):
    return {
        "name": name,
        "description": description,
        "inputSchema": {"type": "object", "properties": {"order": {"type": "string"}, "q": {"type": "string"}}},
    }


def line(message):
    return (json.dumps(message) + "\n").encode("utf-8")


def parse(raw):
    return json.loads(raw.decode("utf-8"))


def list_request(request_id=1):
    return line({"jsonrpc": "2.0", "id": request_id, "method": "tools/list"})


def list_response(tools, request_id=1, **extra):
    result = {"tools": tools}
    result.update(extra)
    return line({"jsonrpc": "2.0", "id": request_id, "result": result})


def make(entries, allow_stale=False):
    warnings = []
    patch = {"patchVersion": 1, "tools": entries}
    return Router(patch, allow_stale, warnings.append), warnings


RUN_ENTRY = {
    "base": patch_format.fingerprint(tool()),
    "rename": "search_orders",
    "description": "Search orders by status.",
    "params": {"order": {"enum": ["asc", "desc"]}},
}


class PassThroughTests(unittest.TestCase):
    def test_unpatched_client_and_server_lines_are_the_same_bytes(self):
        router, warnings = make({"run": RUN_ENTRY})
        for raw in (
            b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n',
            b' { "b" : 1 ,   "a" : "caf\\u00e9 \\/" }\n',
            b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n',
        ):
            with self.subTest(raw):
                self.assertIs(router.client_line(raw), raw)
                self.assertIs(router.server_line(raw), raw)
        self.assertEqual(warnings, [])

    def test_lines_that_are_not_json_objects_are_forwarded_unchanged(self):
        router, _ = make({"run": RUN_ENTRY})
        for raw in (
            b"garbage\n", b"[1, 2, 3]\n", b'"just a string"\n', b"42\n", b"\n", b"", b"{not json\n",
            b"[" * 5000 + b"\n", b"\xff\xfe\n",
        ):
            with self.subTest(raw[:20]):
                self.assertIs(router.client_line(raw), raw)
                self.assertIs(router.server_line(raw), raw)

    def test_a_final_line_with_no_newline_is_forwarded_as_is(self):
        router, _ = make({})
        raw = b'{"jsonrpc":"2.0","id":9,"result":{}}'
        self.assertIs(router.server_line(raw), raw)


class ToolsListTests(unittest.TestCase):
    def test_a_tools_list_response_is_patched(self):
        router, warnings = make({"run": RUN_ENTRY})
        router.client_line(list_request())
        raw = list_response([tool(), tool("list_items", "Lists items in the store")], nextCursor="c2")
        out = parse(router.server_line(raw))
        self.assertEqual(out["id"], 1)
        self.assertEqual(out["jsonrpc"], "2.0")
        self.assertEqual(out["result"]["nextCursor"], "c2")
        first, second = out["result"]["tools"]
        self.assertEqual(first["name"], "search_orders")
        self.assertEqual(first["description"], "Search orders by status.")
        self.assertEqual(first["inputSchema"]["properties"]["order"], {"type": "string", "enum": ["asc", "desc"]})
        self.assertEqual(second, tool("list_items", "Lists items in the store"))
        self.assertEqual(warnings, [])

    def test_a_response_nobody_asked_for_is_not_patched(self):
        router, _ = make({"run": RUN_ENTRY})
        raw = list_response([tool()])
        self.assertIs(router.server_line(raw), raw)

    def test_string_and_number_ids_never_mix(self):
        router, _ = make({"run": RUN_ENTRY})
        router.client_line(list_request("1"))
        raw = list_response([tool()], request_id=1)
        self.assertIs(router.server_line(raw), raw)
        patched = parse(router.server_line(list_response([tool()], request_id="1")))
        self.assertEqual(patched["result"]["tools"][0]["name"], "search_orders")

    def test_a_response_is_patched_once_per_request(self):
        router, _ = make({"run": RUN_ENTRY})
        router.client_line(list_request())
        router.server_line(list_response([tool()]))
        raw = list_response([tool()])
        self.assertIs(router.server_line(raw), raw)

    def test_an_error_response_is_untouched_and_forgotten(self):
        router, _ = make({"run": RUN_ENTRY})
        router.client_line(list_request())
        raw = line({"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "no"}})
        self.assertIs(router.server_line(raw), raw)
        self.assertEqual(router.pending, set())

    def test_a_server_request_that_reuses_the_id_is_not_a_response(self):
        router, _ = make({"run": RUN_ENTRY})
        router.client_line(list_request())
        raw = line({"jsonrpc": "2.0", "id": 1, "method": "ping"})
        self.assertIs(router.server_line(raw), raw)
        self.assertEqual(router.pending, {"1"})

    def test_a_tools_list_notification_without_an_id_is_ignored(self):
        router, _ = make({"run": RUN_ENTRY})
        router.client_line(line({"jsonrpc": "2.0", "method": "tools/list"}))
        self.assertEqual(router.pending, set())

    def test_a_page_where_nothing_changes_keeps_the_original_bytes(self):
        router, _ = make({"run": {"review": ["only a note"]}})
        router.client_line(list_request())
        raw = list_response([tool()])
        self.assertIs(router.server_line(raw), raw)

    def test_two_pages_are_each_patched(self):
        router, _ = make({"run": RUN_ENTRY, "list_items": {"description": "Lists every item in the store."}})
        router.client_line(list_request(1))
        router.client_line(list_request(2))
        one = parse(router.server_line(list_response([tool()], 1)))
        two = parse(router.server_line(list_response([tool("list_items", "x")], 2)))
        self.assertEqual(one["result"]["tools"][0]["name"], "search_orders")
        self.assertEqual(two["result"]["tools"][0]["description"], "Lists every item in the store.")

    def test_entries_that_are_not_tools_are_left_alone(self):
        router, _ = make({"run": RUN_ENTRY})
        router.client_line(list_request())
        out = parse(router.server_line(list_response(["oops", 5, {"no": "name"}, tool()])))
        self.assertEqual(out["result"]["tools"][:3], ["oops", 5, {"no": "name"}])
        self.assertEqual(out["result"]["tools"][3]["name"], "search_orders")


class RenameBackTests(unittest.TestCase):
    def listed(self, entries=None, allow_stale=False, tools=None):
        router, warnings = make(entries or {"run": RUN_ENTRY}, allow_stale)
        router.client_line(list_request())
        router.server_line(list_response(tools or [tool()]))
        return router, warnings

    def call(self, name, request_id=7, arguments=None):
        return line({
            "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
            "params": {"name": name, "arguments": arguments if arguments is not None else {"q": "x"}, "_meta": {"k": 1}},
        })

    def test_a_renamed_tool_is_called_by_its_original_name(self):
        router, _ = self.listed()
        out = parse(router.client_line(self.call("search_orders")))
        self.assertEqual(out["params"]["name"], "run")
        self.assertEqual(out["params"]["arguments"], {"q": "x"})
        self.assertEqual(out["params"]["_meta"], {"k": 1})
        self.assertEqual((out["id"], out["method"]), (7, "tools/call"))

    def test_an_unrenamed_or_unknown_call_is_the_same_bytes(self):
        router, _ = self.listed()
        for name in ("run", "list_items", "ghost"):
            with self.subTest(name):
                raw = self.call(name)
                self.assertIs(router.client_line(raw), raw)

    def test_a_call_before_any_list_passes_through(self):
        router, _ = make({"run": RUN_ENTRY})
        raw = self.call("search_orders")
        self.assertIs(router.client_line(raw), raw)

    def test_a_call_with_odd_params_passes_through(self):
        router, _ = self.listed()
        for message in (
            {"method": "tools/call", "id": 1},
            {"method": "tools/call", "id": 1, "params": []},
            {"method": "tools/call", "id": 1, "params": {"name": 5}},
        ):
            with self.subTest(message):
                raw = line(message)
                self.assertIs(router.client_line(raw), raw)

    def test_other_methods_naming_the_patched_name_are_untouched(self):
        router, _ = self.listed()
        raw = line({"method": "prompts/get", "id": 1, "params": {"name": "search_orders"}})
        self.assertIs(router.client_line(raw), raw)

    def test_a_rename_that_collides_with_another_tool_on_the_page_is_skipped(self):
        entries = {"run": {"rename": "list_items", "description": "Search orders by status."}}
        router, warnings = self.listed(entries, tools=[tool(), tool("list_items", "Lists items")])
        self.assertEqual(router.rename_back, {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("rename of tool 'run' to 'list_items' skipped", warnings[0])

    def test_a_skipped_rename_still_applies_the_other_changes(self):
        entries = {"run": {"rename": "list_items", "description": "Search orders by status."}}
        router, _ = make(entries)
        router.client_line(list_request())
        out = parse(router.server_line(list_response([tool(), tool("list_items", "Lists items")])))
        self.assertEqual([t["name"] for t in out["result"]["tools"]], ["run", "list_items"])
        self.assertEqual(out["result"]["tools"][0]["description"], "Search orders by status.")

    def test_a_second_list_keeps_the_map(self):
        router, _ = self.listed()
        router.client_line(list_request(2))
        router.server_line(list_response([tool("other_tool", "Does something else entirely")], 2))
        out = parse(router.client_line(self.call("search_orders")))
        self.assertEqual(out["params"]["name"], "run")


class StaleTests(unittest.TestCase):
    CHANGED = tool("run", "The server changed this text")

    def test_a_stale_tool_is_served_unpatched_with_one_warning_per_session(self):
        router, warnings = make({"run": RUN_ENTRY})
        for request_id in (1, 2):
            router.client_line(list_request(request_id))
            raw = list_response([self.CHANGED], request_id)
            self.assertIs(router.server_line(raw), raw)
        self.assertEqual(len(warnings), 1)
        self.assertIn("tool 'run' changed since the patch was made; serving it unpatched", warnings[0])
        self.assertIn("--allow-stale", warnings[0])
        self.assertEqual(router.rename_back, {})

    def test_allow_stale_applies_the_entry_anyway(self):
        router, warnings = make({"run": RUN_ENTRY}, allow_stale=True)
        router.client_line(list_request())
        out = parse(router.server_line(list_response([self.CHANGED])))
        self.assertEqual(out["result"]["tools"][0]["name"], "search_orders")
        self.assertEqual(warnings, [])

    def test_an_entry_without_a_base_is_always_applied(self):
        router, _ = make({"run": {"description": "Search orders by status."}})
        router.client_line(list_request())
        out = parse(router.server_line(list_response([self.CHANGED])))
        self.assertEqual(out["result"]["tools"][0]["description"], "Search orders by status.")


class WarningTests(unittest.TestCase):
    def test_apply_warnings_are_logged_once(self):
        router, warnings = make({"run": {"params": {"ghost": {"type": "string"}}}})
        for request_id in (1, 2):
            router.client_line(list_request(request_id))
            router.server_line(list_response([tool()], request_id))
        self.assertEqual(warnings, ["parameter 'ghost' is not in tool 'run'; skipped"])

    def test_finish_warns_about_patched_tools_the_server_never_listed(self):
        router, warnings = make({"run": RUN_ENTRY, "ghost": {"description": "x"}})
        router.client_line(list_request())
        router.server_line(list_response([tool()]))
        router.finish()
        router.finish()
        self.assertEqual(warnings, ["tool 'ghost' is in the patch but the server never listed it"])

    def test_the_default_logger_prefixes_and_writes_to_stderr(self):
        router = Router({"patchVersion": 1, "tools": {"ghost": {"description": "x"}}})
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            router.finish()
        self.assertEqual(err.getvalue(), "mcp-fixer: tool 'ghost' is in the patch but the server never listed it\n")


if __name__ == "__main__":
    unittest.main()
