import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import support
from mcp_fixer import patch_format, wrap
from wrapclient import WrapClient

TOOLS = [
    {"name": "run", "description": "Runs it",
     "inputSchema": {"type": "object", "properties": {"order": {"type": "string", "description": "Sort order, one of: asc, desc"}, "q": {}}}},
    {"name": "list_items", "description": "List the items in the store.",
     "inputSchema": {"type": "object", "properties": {}}},
]
PATCH = {
    "patchVersion": 1,
    "tools": {
        "run": {
            "base": patch_format.fingerprint(TOOLS[0]),
            "rename": "search_orders",
            "description": "Search orders by status.",
            "params": {"order": {"enum": ["asc", "desc"]}},
        }
    },
}


class WrapCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.tools_file = self.dir / "tools.json"
        self.tools_file.write_text(json.dumps(TOOLS), encoding="utf-8")

    def patch_file(self, patch=PATCH, name="p.json"):
        path = self.dir / name
        path.write_text(json.dumps(patch), encoding="utf-8")
        return path

    def server_args(self, mode="normal", *extra):
        return ["--mode", mode, "--tools", str(self.tools_file), *extra]

    def client(self, patch=PATCH, mode="normal", *extra, **kw):
        client = WrapClient(self.patch_file(patch), self.server_args(mode, *extra), **kw)
        self.addCleanup(client.kill)
        return client

    def command(self, mode="normal", *extra):
        return [sys.executable, str(support.FAKE_SERVER), *self.server_args(mode, *extra)]


class InteractiveTests(WrapCase):
    def test_the_client_sees_the_patched_tool_list(self):
        c = self.client()
        c.handshake()
        listing = c.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        first, second = listing["result"]["tools"]
        self.assertEqual(first["name"], "search_orders")
        self.assertEqual(first["description"], "Search orders by status.")
        self.assertEqual(first["inputSchema"]["properties"]["order"]["enum"], ["asc", "desc"])
        self.assertEqual(second, TOOLS[1])
        self.assertEqual(c.finish(), 0)

    def test_a_renamed_tool_is_called_by_its_original_name(self):
        c = self.client()
        c.handshake()
        c.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        reply = c.request({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                           "params": {"name": "search_orders", "arguments": {"q": "x", "n": 3}}})
        self.assertEqual(reply["result"]["content"][0]["text"], 'called run with {"n": 3, "q": "x"}')
        original = c.request({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "run", "arguments": {}}})
        self.assertEqual(original["result"]["content"][0]["text"], "called run with {}")
        ghost = c.request({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "ghost", "arguments": {}}})
        self.assertEqual(ghost["error"]["message"], "Unknown tool: ghost")
        self.assertEqual(c.finish(), 0)

    def test_string_ids_are_echoed_unchanged(self):
        c = self.client()
        c.handshake()
        listing = c.request({"jsonrpc": "2.0", "id": "req-1", "method": "tools/list"})
        self.assertEqual(listing["id"], "req-1")
        self.assertEqual(listing["result"]["tools"][0]["name"], "search_orders")
        c.finish()

    def test_pagination_patches_every_page(self):
        c = self.client(PATCH, "normal", "--page-size", "1")
        c.handshake()
        one = c.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        two = c.request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {"cursor": one["result"]["nextCursor"]}})
        self.assertEqual(one["result"]["tools"][0]["name"], "search_orders")
        self.assertEqual(two["result"]["tools"][0]["name"], "list_items")
        c.finish()

    def test_unpatched_messages_are_forwarded_byte_for_byte(self):
        c = self.client(PATCH, "odd-bytes")
        c.request({"jsonrpc": "2.0", "id": 100, "method": "initialize", "params": {}})
        c.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        note = c.recv_raw()
        self.assertEqual(
            note,
            b'{"method":"notifications/message",   "params":{"level":"info","data":"caf\\u00e9"},"jsonrpc":"2.0"}\n',
        )
        c.send({"jsonrpc": "2.0", "id": 7, "method": "resources/list"})
        odd = c.recv_raw()
        self.assertEqual(
            odd,
            b' { "jsonrpc" : "2.0" , "result" : {"b":1,"a":"caf\\u00e9 \\/ \\ud83d\\ude00"},   "id" : 7 }\n',
        )
        c.finish()

    def test_stdout_carries_only_protocol_lines(self):
        c = self.client(dict(PATCH, tools={"ghost": {"description": "x"}}))
        c.handshake()
        c.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        c.proc.stdin.close()
        rest = []
        while True:
            raw = c.recv_raw()
            if raw is None:
                break
            rest.append(raw)
        for raw in rest:
            self.assertIsInstance(json.loads(raw.decode("utf-8")), dict)
        c.proc.wait(timeout=20)
        self.assertIn("never listed it", c.stderr_text)  # warnings stay on stderr

    def test_a_stale_patch_serves_the_tool_unpatched_and_warns_once(self):
        changed = [dict(TOOLS[0], description="The server changed this"), TOOLS[1]]
        self.tools_file.write_text(json.dumps(changed), encoding="utf-8")
        c = self.client()
        c.handshake()
        for request_id in (1, 2):
            listing = c.request({"jsonrpc": "2.0", "id": request_id, "method": "tools/list"})
            self.assertEqual(listing["result"]["tools"][0]["name"], "run")
        self.assertEqual(c.finish(), 0)
        self.assertEqual(c.stderr_text.count("changed since the patch was made"), 1)
        self.assertTrue(c.stderr_text.startswith("mcp-fixer: tool 'run' changed since the patch was made"))

    def test_allow_stale_applies_the_patch_anyway(self):
        changed = [dict(TOOLS[0], description="The server changed this"), TOOLS[1]]
        self.tools_file.write_text(json.dumps(changed), encoding="utf-8")
        c = self.client(allow_stale=True)
        c.handshake()
        listing = c.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(listing["result"]["tools"][0]["name"], "search_orders")
        c.finish()
        self.assertEqual(c.stderr_text, "")

    def test_a_patched_tool_the_server_never_lists_is_warned_about_once(self):
        c = self.client(dict(PATCH, tools={"ghost": {"description": "x"}}))
        c.handshake()
        c.request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        c.finish()
        self.assertEqual(c.stderr_text.count("tool 'ghost' is in the patch but the server never listed it"), 1)

    def test_a_server_that_crashes_ends_the_wrapper_with_its_exit_code(self):
        c = self.client(PATCH, "crash")
        reply = c.request({"jsonrpc": "2.0", "id": 100, "method": "initialize", "params": {}})
        self.assertEqual(reply["id"], 100)
        self.assertEqual(c.proc.wait(timeout=20), 3)  # without the client closing stdin
        self.assertNotIn("Traceback", c.stderr_text)


class LifecycleTests(WrapCase):
    INIT = (json.dumps({"jsonrpc": "2.0", "id": 100, "method": "initialize", "params": {}}) + "\n").encode()
    INITIALIZED = (json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n").encode()
    LIST = (json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n").encode()

    def run_in_process(self, lines, mode="normal", *extra, patch=PATCH, allow_stale=False):
        stdin = io.BytesIO(b"".join(lines))
        stdout = io.BytesIO()
        logs = []
        code = wrap.run_wrapper(patch, self.command(mode, *extra), allow_stale, stdin, stdout, logs.append)
        return code, [raw for raw in stdout.getvalue().split(b"\n") if raw], logs

    def test_end_of_input_ends_the_session_and_everything_is_flushed(self):
        code, lines, _ = self.run_in_process([self.INIT, self.INITIALIZED, self.LIST])
        self.assertEqual(code, 0)
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[1])["result"]["tools"][0]["name"], "search_orders")

    def test_a_server_that_ignores_end_of_input_is_stopped_after_the_grace_period(self):
        pid_file = self.dir / "pid"
        original = wrap.SHUTDOWN_GRACE_SECONDS
        wrap.SHUTDOWN_GRACE_SECONDS = 0.5
        self.addCleanup(setattr, wrap, "SHUTDOWN_GRACE_SECONDS", original)
        started = time.monotonic()
        code, _, _ = self.run_in_process([self.INIT], "hang-on-eof", "--pid-file", str(pid_file))
        self.assertEqual(code, 0)
        self.assertLess(time.monotonic() - started, 10)
        self.assertTrue(support.wait_until_gone(int(pid_file.read_text())))

    def test_a_server_that_crashes_propagates_its_exit_code_after_its_last_output(self):
        code, lines, _ = self.run_in_process([self.INIT, self.INITIALIZED, self.LIST], "crash")
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(lines[0])["id"], 100)  # the response it wrote before dying

    def test_a_server_that_exits_at_once_propagates_its_exit_code(self):
        code, lines, _ = self.run_in_process([self.INIT], "exit")
        self.assertEqual((code, lines), (4, []))

    def test_a_command_that_does_not_exist_is_a_client_error(self):
        from mcp_fixer.stdio_client import ClientError
        with self.assertRaises(ClientError):
            wrap.run_wrapper(PATCH, ["definitely-not-a-real-command-xyz"], False, io.BytesIO(), io.BytesIO(), lambda text: None)

    def test_warnings_go_to_the_log_once(self):
        patch = dict(PATCH, tools={"ghost": {"description": "x"}})
        _, _, logs = self.run_in_process([self.INIT, self.INITIALIZED, self.LIST, self.LIST], patch=patch)
        self.assertEqual(logs, ["tool 'ghost' is in the patch but the server never listed it"])

    def test_the_server_process_is_gone_after_a_normal_session(self):
        pid_file = self.dir / "pid"
        self.run_in_process([self.INIT], "normal", "--pid-file", str(pid_file))
        self.assertTrue(support.wait_until_gone(int(pid_file.read_text())))

    def test_the_server_gets_the_whole_environment(self):
        os.environ["MCP_FIXER_TEST_MARKER"] = "present"
        self.addCleanup(os.environ.pop, "MCP_FIXER_TEST_MARKER", None)
        from mcp_fixer.stdio_client import child_environment
        self.assertEqual(child_environment(inherit=True)["MCP_FIXER_TEST_MARKER"], "present")
        self.assertNotIn("MCP_FIXER_TEST_MARKER", child_environment())


class BrokenPatchTests(WrapCase):
    def run_cli(self, patch_text):
        path = self.dir / "bad.json"
        path.write_text(patch_text, encoding="utf-8")
        pid_file = self.dir / "pid"
        done = subprocess.run(
            [sys.executable, "-m", "mcp_fixer", "wrap", "--patch", str(path), "--",
             sys.executable, str(support.FAKE_SERVER), "--mode", "normal", "--tools", str(self.tools_file), "--pid-file", str(pid_file)],
            capture_output=True, env=dict(os.environ, PYTHONPATH=str(support.SRC)), timeout=60,
        )
        return done, pid_file

    def test_a_broken_patch_exits_2_before_the_server_is_spawned(self):
        for text in (
            "{not json",
            json.dumps({"patchVersion": 2, "tools": {}}),
            json.dumps({"patchVersion": 1, "tools": {"a": {"rename": "z"}, "b": {"rename": "z"}}}),
        ):
            with self.subTest(text[:30]):
                done, pid_file = self.run_cli(text)
                self.assertEqual(done.returncode, 2, done.stderr)
                self.assertEqual(done.stdout, b"")
                err = done.stderr.decode("utf-8")
                self.assertTrue(err.startswith("error: "), err)
                self.assertEqual(err.count("\n"), 1)
                self.assertFalse(pid_file.exists())


if __name__ == "__main__":
    unittest.main()
