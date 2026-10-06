import http.server
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import support
from mcp_fixer import runners
from mcp_fixer.runners import RunnerError

FAKE_CLAUDE = Path(support.TESTS) / "fake_claude.py"
KEY = "sk-test-secret-key-123"


class FakeRunnerTests(unittest.TestCase):
    def test_it_calls_the_function(self):
        runner = runners.FakeRunner(lambda prompt: prompt.upper(), "label")
        self.assertEqual(runner.complete("abc"), "ABC")
        self.assertEqual(runner.describe(), "label")


class ClaudeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def runner(self, mode="ok", *extra, model=None, timeout=30):
        command = (sys.executable, str(FAKE_CLAUDE), "--mode", mode, *extra)
        return runners.ClaudeRunner(model=model, timeout=timeout, command=command)

    def test_it_passes_the_flags_and_the_prompt_on_stdin(self):
        record = self.dir / "rec.json"
        reply = self.runner("ok", "--record", str(record)).complete("pick one é日")
        self.assertIn("get_item", reply)
        seen = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(seen["argv"], ["-p", "--tools", "", "--no-session-persistence"])
        self.assertEqual(seen["stdin"], "pick one é日")

    def test_a_model_is_passed_through(self):
        record = self.dir / "rec.json"
        self.runner("ok", "--record", str(record), model="some-model").complete("x")
        argv = json.loads(record.read_text(encoding="utf-8"))["argv"]
        self.assertEqual(argv[-2:], ["--model", "some-model"])

    def test_a_failing_run_is_a_one_line_error_with_the_first_stderr_line(self):
        with self.assertRaises(RunnerError) as ctx:
            self.runner("fail").complete("x")
        message = str(ctx.exception)
        self.assertIn("code 3", message)
        self.assertIn("boom happened", message)
        self.assertNotIn("second line", message)
        self.assertNotIn("\n", message)

    def test_a_hanging_run_times_out_and_the_process_is_stopped(self):
        pid_file = self.dir / "pid"
        started = time.monotonic()
        with self.assertRaises(RunnerError) as ctx:
            self.runner("hang", "--pid-file", str(pid_file), timeout=1).complete("x")
        self.assertIn("timed out", str(ctx.exception))
        self.assertLess(time.monotonic() - started, 20)
        self.assertTrue(support.wait_until_gone(int(pid_file.read_text())))

    def test_huge_output_is_capped(self):
        self.assertLessEqual(len(self.runner("huge").complete("x")), 200000)

    def test_bytes_that_are_not_utf8_do_not_crash(self):
        self.assertIn("get_item", self.runner("badbytes").complete("x"))

    def test_a_missing_executable_is_a_clear_error(self):
        runner = runners.ClaudeRunner(command=("definitely-not-a-real-command-xyz",))
        with self.assertRaises(RunnerError) as ctx:
            runner.complete("x")
        self.assertIn("cannot find", str(ctx.exception))

    def test_describe_names_the_model(self):
        self.assertIn("some-model", runners.ClaudeRunner(model="some-model").describe())
        self.assertIn("claude", runners.ClaudeRunner().describe())


class _Handler(http.server.BaseHTTPRequestHandler):
    log = []

    def log_message(self, *args):
        pass

    def _send(self, status, body):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        _Handler.log.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
        if self.path == "/ok":
            self._send(200, {"content": [{"type": "text", "text": '{"tool": '}, {"type": "text", "text": '"get_item"}'}]})
        elif self.path == "/401":
            self._send(401, {"error": {"type": "authentication_error", "message": "invalid x-api-key: " + KEY}})
        elif self.path == "/500":
            self._send(500, {"error": {"message": "overloaded"}})
        elif self.path == "/badbody":
            self._send(200, b"not json at all")
        elif self.path == "/shape":
            self._send(200, {"content": "nope"})
        elif self.path == "/slow":
            time.sleep(3)
            self._send(200, {"content": [{"type": "text", "text": "late"}]})


class ApiRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def runner(self, path, timeout=10, max_tokens=64):
        return runners.ApiRunner("some-model", KEY, timeout, max_tokens, url=f"http://127.0.0.1:{self.port}{path}")

    def test_a_good_reply_is_the_joined_text_blocks(self):
        self.assertEqual(self.runner("/ok").complete("pick"), '{"tool": "get_item"}')

    def test_the_request_is_deterministic_and_has_no_tools(self):
        _Handler.log.clear()
        self.runner("/ok", max_tokens=1024).complete("pick one")
        path, headers, body = _Handler.log[-1]
        self.assertEqual(headers["x-api-key"], KEY)
        self.assertIn("anthropic-version", headers)
        self.assertEqual(body["model"], "some-model")
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["max_tokens"], 1024)
        self.assertEqual(body["messages"], [{"role": "user", "content": "pick one"}])
        self.assertNotIn("tools", body)

    def test_errors_are_one_line_and_never_contain_the_key(self):
        cases = {"/401": "401", "/500": "500", "/badbody": "unexpected", "/shape": "unexpected"}
        for path, fragment in cases.items():
            with self.subTest(path):
                with self.assertRaises(RunnerError) as ctx:
                    self.runner(path).complete("x")
                message = str(ctx.exception)
                self.assertIn(fragment, message)
                self.assertNotIn(KEY, message)
                self.assertNotIn("\n", message)

    def test_a_slow_server_times_out(self):
        with self.assertRaises(RunnerError) as ctx:
            self.runner("/slow", timeout=0.5).complete("x")
        self.assertIn("timed out", str(ctx.exception))

    def test_a_connection_refusal_is_a_runner_error_without_the_key(self):
        runner = runners.ApiRunner("m", KEY, 2, url="http://127.0.0.1:1/ok")
        with self.assertRaises(RunnerError) as ctx:
            runner.complete("x")
        self.assertNotIn(KEY, str(ctx.exception))

    def test_describe_never_includes_the_key(self):
        self.assertNotIn(KEY, self.runner("/ok").describe())
        self.assertIn("some-model", self.runner("/ok").describe())


class MakeRunnerTests(unittest.TestCase):
    def test_the_claude_runner_needs_no_key(self):
        runner = runners.make_runner("claude", "m")
        self.assertIsInstance(runner, runners.ClaudeRunner)

    def test_the_api_runner_needs_the_key_before_any_call(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with self.assertRaises(RunnerError) as ctx:
                runners.make_runner("api", None)
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))

    def test_the_api_runner_reads_the_key_and_has_a_default_model(self):
        runner = runners.make_runner("api", None, env={"ANTHROPIC_API_KEY": KEY}, max_tokens=1024)
        self.assertIsInstance(runner, runners.ApiRunner)
        self.assertIn("claude-sonnet-5-5", runner.describe())

    def test_an_unknown_runner_is_an_error(self):
        with self.assertRaises(RunnerError):
            runners.make_runner("nope", None)


if __name__ == "__main__":
    unittest.main()
