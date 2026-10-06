"""Regression tests from the final review: a lingering descendant and the installed entry point."""
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import support
from test_wrap import PATCH, TOOLS, WrapCase
from wrapclient import WrapClient


class LingeringDescendantTests(WrapCase):
    def test_the_wrapper_ends_when_the_server_exits_even_if_a_descendant_holds_its_output(self):
        child_pid_file = self.dir / "child.pid"
        c = self.client(PATCH, "grandchild-exit", "--child-pid-file", str(child_pid_file))

        def stop_child():
            try:
                os.kill(int(child_pid_file.read_text()), signal.SIGTERM)
            except (OSError, ValueError):
                pass

        self.addCleanup(stop_child)
        started = time.monotonic()
        code = c.proc.wait(timeout=15)  # the client never closes stdin
        self.assertEqual(code, 4)
        self.assertLess(time.monotonic() - started, 12)


class ConsoleScriptTests(unittest.TestCase):
    def test_the_declared_console_script_runs_the_same_exit_path(self):
        text = (support.ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('mcp-fixer = "mcp_fixer.cli:run"', text)

    def test_run_propagates_a_crashed_servers_exit_code_without_a_shutdown_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp) / "tools.json"
            tools.write_text(json.dumps(TOOLS), encoding="utf-8")
            patch = Path(tmp) / "p.json"
            patch.write_text(json.dumps({"patchVersion": 1, "tools": {}}), encoding="utf-8")
            script = (
                "import sys; sys.argv = ['mcp-fixer', 'wrap', '--patch', sys.argv[1], '--', sys.executable, "
                "sys.argv[2], '--mode', 'crash', '--tools', sys.argv[3]]; "
                "from mcp_fixer.cli import run; run()"
            )
            proc = subprocess.Popen(
                [sys.executable, "-c", script, str(patch), str(support.FAKE_SERVER), str(tools)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=dict(os.environ, PYTHONPATH=str(support.SRC)),
            )
            try:
                proc.stdin.write(b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n')
                proc.stdin.flush()
                out = proc.stdout.readline()
                self.assertIn(b'"id": 1', out)
                code = proc.wait(timeout=20)  # stdin stays open: the wrapper must leave by itself
                err = proc.stderr.read()
            finally:
                if proc.poll() is None:
                    proc.kill()
                for pipe in (proc.stdin, proc.stdout, proc.stderr):
                    pipe.close()
            self.assertEqual(code, 3, err)
            self.assertNotIn(b"Fatal Python error", err)


if __name__ == "__main__":
    unittest.main()
