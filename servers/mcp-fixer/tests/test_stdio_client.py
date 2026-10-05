import gc
import json
import os
import sys
import tempfile
import time
import unittest
import warnings
from pathlib import Path

import support
from mcp_fixer import stdio_client
from mcp_fixer.stdio_client import ClientError, list_tools_stdio

TOOLS = [
    {"name": f"tool_{i}", "description": f"Describe topic t{i:03d} thoroughly",
     "inputSchema": {"type": "object", "properties": {}}}
    for i in range(5)
]


class ClientCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.tools_file = self.dir / "tools.json"
        self.tools_file.write_text(json.dumps(TOOLS), encoding="utf-8")

    def command(self, mode="normal", *extra, pid_file=None):
        argv = [sys.executable, str(support.FAKE_SERVER), "--mode", mode, "--tools", str(self.tools_file), *extra]
        if pid_file:
            argv += ["--pid-file", str(pid_file)]
        return argv

    def assert_error(self, mode, fragment, timeout=5, *extra):
        started = time.monotonic()
        with self.assertRaises(ClientError) as ctx:
            list_tools_stdio(self.command(mode, *extra), timeout=timeout)
        self.assertIn(fragment, str(ctx.exception))
        self.assertNotIn("\n", str(ctx.exception))
        return time.monotonic() - started


class HappyPathTests(ClientCase):
    def test_normal_handshake_returns_the_tools_and_server_info(self):
        tools, info = list_tools_stdio(self.command("normal"), timeout=10)
        self.assertEqual(tools, TOOLS)
        self.assertEqual(info, {"protocolVersion": "2025-06-18", "serverName": "fake-server", "serverVersion": "1.2.3"})

    def test_paginated_tools_list_is_followed_to_the_end(self):
        tools, _ = list_tools_stdio(self.command("normal", "--page-size", "2"), timeout=10)
        self.assertEqual(tools, TOOLS)

    def test_junk_on_stdout_is_ignored(self):
        tools, _ = list_tools_stdio(self.command("noisy"), timeout=10)
        self.assertEqual(tools, TOOLS)

    def test_a_ping_request_from_the_server_is_answered(self):
        # The fake server holds back tools/list until its ping has been answered.
        tools, _ = list_tools_stdio(self.command("ping"), timeout=10)
        self.assertEqual(tools, TOOLS)

    def test_a_slow_but_in_time_server_works(self):
        tools, _ = list_tools_stdio(self.command("slow"), timeout=10)
        self.assertEqual(tools, TOOLS)

    def test_the_server_process_is_gone_afterwards(self):
        pid_file = self.dir / "pid"
        list_tools_stdio(self.command("normal", pid_file=pid_file), timeout=10)
        self.assertTrue(support.wait_until_gone(int(pid_file.read_text())))

    def test_no_pipe_is_left_open_after_a_run(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            list_tools_stdio(self.command("normal"), timeout=10)
            gc.collect()
        leaks = [str(w.message) for w in caught if issubclass(w.category, ResourceWarning)]
        self.assertEqual(leaks, [])

    def test_the_server_only_sees_the_base_environment_and_what_is_passed(self):
        os.environ["MCP_FIXER_SECRET_FOR_TEST"] = "do-not-leak"
        self.addCleanup(os.environ.pop, "MCP_FIXER_SECRET_FOR_TEST", None)
        env = stdio_client.child_environment({"API_KEY": "abc"})
        self.assertNotIn("MCP_FIXER_SECRET_FOR_TEST", env)
        self.assertEqual(env["API_KEY"], "abc")
        self.assertIn("PATH", env)


class MisbehavingServerTests(ClientCase):
    def test_a_server_that_never_answers_initialize_times_out_and_is_killed(self):
        pid_file = self.dir / "pid"
        started = time.monotonic()
        with self.assertRaises(ClientError) as ctx:
            list_tools_stdio(self.command("hang", pid_file=pid_file), timeout=0.8)
        self.assertIn("timed out", str(ctx.exception))
        self.assertLess(time.monotonic() - started, 8)
        self.assertTrue(support.wait_until_gone(int(pid_file.read_text())))

    def test_a_server_that_never_answers_tools_list_times_out_and_is_killed(self):
        pid_file = self.dir / "pid"
        with self.assertRaises(ClientError) as ctx:
            list_tools_stdio(self.command("hang-list", pid_file=pid_file), timeout=0.8)
        self.assertIn("timed out", str(ctx.exception))
        self.assertTrue(support.wait_until_gone(int(pid_file.read_text())))

    def test_a_crash_after_initialize(self):
        self.assert_error("crash", "the server")

    def test_a_server_that_exits_at_once(self):
        self.assert_error("exit", "exited with code 4")

    def test_an_error_response_to_initialize(self):
        self.assert_error("error", "Unsupported protocol version")

    def test_a_bad_tools_value(self):
        self.assert_error("badresult", "tools array")

    def test_endless_paging_stops(self):
        started = time.monotonic()
        self.assert_error("forever", "pages", timeout=20)
        self.assertLess(time.monotonic() - started, 20)

    def test_the_whole_connection_is_capped(self):
        # Every page comes back in time, but there are too many of them for the overall cap.
        big = [{"name": f"t{i}", "description": "x" * 25, "inputSchema": {"type": "object"}} for i in range(100)]
        self.tools_file.write_text(json.dumps(big), encoding="utf-8")
        started = time.monotonic()
        with self.assertRaises(ClientError) as ctx:
            list_tools_stdio(self.command("slow", "--page-size", "1"), timeout=0.5)
        self.assertIn("timed out", str(ctx.exception))
        self.assertLess(time.monotonic() - started, 10)

    def test_a_descendant_holding_the_pipes_does_not_hang_the_tool(self):
        child_pid_file = self.dir / "child-pid"
        self.addCleanup(self.kill_child, child_pid_file)
        started = time.monotonic()
        tools, _ = list_tools_stdio(
            self.command("grandchild", "--child-pid-file", str(child_pid_file)), timeout=10
        )
        self.assertEqual(tools, TOOLS)
        self.assertLess(time.monotonic() - started, 12)  # the descendant sleeps 20 s
        if os.name != "nt":  # on POSIX the whole process group is stopped
            self.assertTrue(support.wait_until_gone(int(child_pid_file.read_text())))

    def test_a_dead_server_whose_descendant_holds_stdout_is_reported_as_exited(self):
        child_pid_file = self.dir / "child-pid"
        self.addCleanup(self.kill_child, child_pid_file)
        started = time.monotonic()
        with self.assertRaises(ClientError) as ctx:
            list_tools_stdio(self.command("grandchild-exit", "--child-pid-file", str(child_pid_file)), timeout=10)
        self.assertIn("exited with code 4", str(ctx.exception))
        self.assertLess(time.monotonic() - started, 9)

    def test_a_multiline_error_is_one_short_line(self):
        with self.assertRaises(ClientError) as ctx:
            list_tools_stdio(self.command("multiline-error"), timeout=5)
        message = str(ctx.exception)
        self.assertNotIn("\n", message)
        self.assertLess(len(message), 300)
        self.assertIn("first line second line", message)

    def test_an_error_without_a_message_names_its_code(self):
        with self.assertRaises(ClientError) as ctx:
            list_tools_stdio(self.command("no-message-error"), timeout=5)
        self.assertIn("-32001", str(ctx.exception))
        self.assertNotIn("None", str(ctx.exception))

    def test_a_server_flooding_us_with_requests_is_cut_off(self):
        started = time.monotonic()
        with self.assertRaises(ClientError) as ctx:
            list_tools_stdio(self.command("ping-flood"), timeout=3)
        self.assertIn("too many requests", str(ctx.exception))
        self.assertLess(time.monotonic() - started, 8)

    def test_a_line_too_deeply_nested_for_the_json_parser_is_ignored(self):
        tools, _ = list_tools_stdio(self.command("deep"), timeout=10)
        self.assertEqual(tools, TOOLS)

    def test_the_stderr_tail_is_capped_and_keeps_the_end(self):
        proc = stdio_client._spawn(
            [sys.executable, "-c", "import sys\nfor i in range(100000): sys.stderr.write('line %d\\n' % i)"],
            stdio_client.child_environment(),
        )
        session = stdio_client._Session(proc, 10)
        proc.wait(timeout=30)
        session.close()
        self.assertLessEqual(len(session.stderr_tail), stdio_client.STDERR_TAIL_BYTES)
        self.assertIn(b"line 99999", session.stderr_tail)

    def kill_child(self, pid_file):
        if not pid_file.exists():
            return
        pid = int(pid_file.read_text())
        if os.name == "nt":
            import subprocess
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        else:
            try:
                os.kill(pid, 9)
            except OSError:
                pass

    def test_a_command_that_does_not_exist(self):
        with self.assertRaises(ClientError) as ctx:
            list_tools_stdio(["definitely-not-a-real-command-xyz"], timeout=5)
        self.assertIn("cannot find the server command", str(ctx.exception))

    def test_an_empty_command(self):
        with self.assertRaises(ClientError):
            list_tools_stdio([], timeout=5)

    def test_a_server_that_is_not_an_mcp_server_at_all(self):
        with self.assertRaises(ClientError):
            list_tools_stdio([sys.executable, "-c", "print('hello'); import sys; sys.stdin.read()"], timeout=1.5)


@unittest.skipUnless(os.name == "nt", "a .cmd launcher only exists on Windows")
class WindowsLauncherTests(ClientCase):
    def test_a_cmd_shim_is_resolved_and_run(self):
        shim = self.dir / "launcher.cmd"
        shim.write_text(
            f'@echo off\r\n"{sys.executable}" "{support.FAKE_SERVER}" --mode normal --tools "{self.tools_file}"\r\n',
            encoding="utf-8",
        )
        tools, _ = list_tools_stdio([str(shim)], timeout=10)
        self.assertEqual(tools, TOOLS)

    def test_a_cmd_shim_leaves_no_stray_directories_in_the_working_directory(self):
        # With too small an environment Windows cannot expand %SystemDrive% and friends, and a
        # component cmd.exe starts creates a folder literally named "%SystemDrive%" in the cwd.
        shim = self.dir / "launcher.cmd"
        shim.write_text(
            f'@echo off\r\n"{sys.executable}" "{support.FAKE_SERVER}" --mode normal --tools "{self.tools_file}"\r\n',
            encoding="utf-8",
        )
        previous = os.getcwd()
        os.chdir(self.dir)
        self.addCleanup(os.chdir, previous)
        list_tools_stdio([str(shim)], timeout=10)
        self.assertEqual([entry.name for entry in self.dir.iterdir() if "%" in entry.name], [])


class ResolveCommandTests(unittest.TestCase):
    def test_a_real_program_resolves_to_a_path(self):
        argv = stdio_client.resolve_command([sys.executable, "-V"])
        self.assertEqual(argv[1:], ["-V"])
        self.assertTrue(os.path.exists(argv[0]))

    def test_a_missing_program_is_a_client_error(self):
        with self.assertRaises(ClientError):
            stdio_client.resolve_command(["definitely-not-a-real-command-xyz"])


if __name__ == "__main__":
    unittest.main()
