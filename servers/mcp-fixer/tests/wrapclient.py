"""A tiny MCP client for the wrapper tests: it runs `mcp-fixer wrap` as a subprocess and talks to
it line by line, waiting for each response before it sends the next message."""
import json
import os
import queue
import subprocess
import sys
import threading

import support


class WrapClient:
    def __init__(self, patch_path, server_args, allow_stale=False, extra_args=()):
        command = [sys.executable, "-m", "mcp_fixer", "wrap", "--patch", str(patch_path), *extra_args]
        if allow_stale:
            command.append("--allow-stale")
        command += ["--", sys.executable, str(support.FAKE_SERVER), *server_args]
        env = dict(os.environ, PYTHONPATH=str(support.SRC))
        self.proc = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env
        )
        self.lines = queue.Queue()
        self.stderr = []
        self._threads = [
            threading.Thread(target=self._read_stdout, daemon=True),
            threading.Thread(target=self._read_stderr, daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    def _read_stdout(self):
        for raw in self.proc.stdout:
            self.lines.put(raw)
        self.lines.put(None)

    def _read_stderr(self):
        for raw in self.proc.stderr:
            self.stderr.append(raw.decode("utf-8", errors="replace"))

    def send(self, message):
        data = message if isinstance(message, bytes) else (json.dumps(message) + "\n").encode("utf-8")
        self.proc.stdin.write(data)
        self.proc.stdin.flush()

    def recv_raw(self, timeout=15):
        return self.lines.get(timeout=timeout)

    def request(self, message, timeout=15):
        self.send(message)
        raw = self.recv_raw(timeout)
        assert raw is not None, "the wrapper closed its output"
        return json.loads(raw.decode("utf-8"))

    def handshake(self):
        self.request({"jsonrpc": "2.0", "id": 100, "method": "initialize", "params": {}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def finish(self, timeout=20):
        """Close stdin, wait for the wrapper, and return its exit code."""
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        code = self.proc.wait(timeout=timeout)
        for thread in self._threads:
            thread.join(timeout=5)
        for pipe in (self.proc.stdout, self.proc.stderr):
            pipe.close()
        return code

    def kill(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=5)

    @property
    def stderr_text(self):
        return "".join(self.stderr)
