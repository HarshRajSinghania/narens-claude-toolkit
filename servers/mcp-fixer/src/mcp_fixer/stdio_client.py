"""A minimal MCP stdio client: initialize, then page through tools/list. Read-only.

Only `initialize`, `notifications/initialized` and `tools/list` are ever sent (and the server's
`ping` is answered); no tool is ever called. Standard library only.
"""
import json
import os
import queue
import shutil
import signal
import subprocess
import threading
import time

from . import __version__

PROTOCOL_VERSION = "2025-06-18"
MAX_PAGES = 200
OVERALL_TIMEOUT_FACTOR = 4
STDERR_TAIL_BYTES = 8192
SHUTDOWN_WAIT_SECONDS = 2.0

# What a spawned server inherits from this process; everything else must be passed with --env.
BASE_ENV_KEYS = (
    "PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "HOME", "USERPROFILE",
    "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "LANG",
)


class ClientError(Exception):
    """A problem with the server connection, reported as one line."""


def resolve_command(command):
    """The argv to run: the program resolved to a full path (so Windows .cmd shims work)."""
    if not command or not command[0]:
        raise ClientError("no server command given")
    program = shutil.which(command[0])
    if program is None:
        raise ClientError(f"cannot find the server command: {command[0]}")
    return [program] + list(command[1:])


def child_environment(extra=None):
    env = {key: os.environ[key] for key in BASE_ENV_KEYS if key in os.environ}
    env.update(extra or {})
    return env


def _kill_tree(proc, graceful):
    """Stop the server and any children it started."""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10
            )
            return
        os.killpg(proc.pid, signal.SIGTERM if graceful else signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        try:
            proc.kill()
        except OSError:
            pass


class _Session:
    def __init__(self, proc, timeout):
        self.proc = proc
        self.timeout = timeout
        self.deadline = time.monotonic() + timeout * OVERALL_TIMEOUT_FACTOR
        self.next_id = 0
        self.inbox = queue.Queue()
        self.stderr_tail = b""
        self.closed = False
        for target in (self._read_stdout, self._read_stderr):
            threading.Thread(target=target, daemon=True).start()

    # --- reader threads -------------------------------------------------------------------
    def _read_stdout(self):
        try:
            for raw in self.proc.stdout:
                try:
                    message = json.loads(raw.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if isinstance(message, dict):
                    self.inbox.put(message)
        except (OSError, ValueError):
            pass
        self.inbox.put(None)

    def _read_stderr(self):
        try:
            while True:
                stream = self.proc.stderr
                chunk = stream.read1(1024) if hasattr(stream, "read1") else stream.read(1024)
                if not chunk:
                    break
                self.stderr_tail = (self.stderr_tail + chunk)[-STDERR_TAIL_BYTES:]
        except (OSError, ValueError):
            pass

    # --- helpers ---------------------------------------------------------------------------
    def hint(self):
        lines = [
            line.strip()
            for line in self.stderr_tail.decode("utf-8", errors="replace").splitlines()
            if line.strip()
        ]
        return f"; the server said: {lines[-1][:200]}" if lines else ""

    def _send(self, message):
        try:
            self.proc.stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError):
            code = self.proc.poll()
            if code is None:
                try:
                    code = self.proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    code = None
            if code is not None:
                raise ClientError(f"the server exited with code {code}" + self.hint()) from None
            raise ClientError("the server closed its input" + self.hint()) from None

    def notify(self, method, params=None):
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

    def _answer_server_request(self, message):
        if message.get("method") == "ping":
            self._send({"jsonrpc": "2.0", "id": message["id"], "result": {}})
        else:
            self._send(
                {"jsonrpc": "2.0", "id": message["id"],
                 "error": {"code": -32601, "message": "method not supported by this client"}}
            )

    def request(self, method, params=None):
        self.next_id += 1
        request_id = self.next_id
        message = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)
        limit = min(time.monotonic() + self.timeout, self.deadline)
        while True:
            remaining = limit - time.monotonic()
            if remaining <= 0:
                raise ClientError(f"timed out waiting for {method}" + self.hint())
            try:
                incoming = self.inbox.get(timeout=remaining)
            except queue.Empty:
                continue
            if incoming is None:
                try:
                    code = self.proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    code = None
                if code is None:
                    raise ClientError("the server closed its output" + self.hint())
                raise ClientError(f"the server exited with code {code} before answering {method}" + self.hint())
            if "method" in incoming and "id" in incoming:
                self._answer_server_request(incoming)
                continue
            if incoming.get("id") != request_id:
                continue
            if "error" in incoming:
                error = incoming["error"]
                text = error.get("message") if isinstance(error, dict) else error
                raise ClientError(f"{method} failed: {text}")
            result = incoming.get("result")
            return result if isinstance(result, dict) else {}

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.proc.stdin.close()
        except (OSError, ValueError):
            pass
        try:
            self.proc.wait(timeout=SHUTDOWN_WAIT_SECONDS)
            return
        except subprocess.TimeoutExpired:
            pass
        _kill_tree(self.proc, graceful=True)
        try:
            self.proc.wait(timeout=SHUTDOWN_WAIT_SECONDS)
        except subprocess.TimeoutExpired:
            _kill_tree(self.proc, graceful=False)
            try:
                self.proc.wait(timeout=SHUTDOWN_WAIT_SECONDS)
            except subprocess.TimeoutExpired:
                pass


def _spawn(argv, env):
    kwargs = {}
    if os.name != "nt":
        kwargs["start_new_session"] = True
    try:
        return subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            **kwargs,
        )
    except OSError as exc:
        raise ClientError(f"cannot start the server: {exc.strerror or exc}") from None


def list_tools_stdio(command, env=None, timeout=30.0):
    """Start a stdio MCP server, read its tools, shut it down. Returns (tools, info)."""
    argv = resolve_command(command)
    proc = _spawn(argv, child_environment(env))
    session = _Session(proc, timeout)
    try:
        init = session.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "mcp-fixer", "version": __version__},
            },
        )
        server = init.get("serverInfo") if isinstance(init.get("serverInfo"), dict) else {}
        info = {
            "protocolVersion": init.get("protocolVersion") if isinstance(init.get("protocolVersion"), str) else None,
            "serverName": server.get("name") if isinstance(server.get("name"), str) else None,
            "serverVersion": server.get("version") if isinstance(server.get("version"), str) else None,
        }
        session.notify("notifications/initialized")
        tools = []
        cursor = None
        for _ in range(MAX_PAGES):
            result = session.request("tools/list", {"cursor": cursor} if cursor else None)
            page = result.get("tools")
            if not isinstance(page, list):
                raise ClientError("tools/list did not return a tools array")
            tools.extend(page)
            cursor = result.get("nextCursor")
            if not cursor:
                return tools, info
        raise ClientError(f"tools/list kept returning pages (stopped after {MAX_PAGES} pages)")
    finally:
        session.close()
