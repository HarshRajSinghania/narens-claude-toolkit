"""The wrapper: a transparent stdio proxy that patches tool definitions.

`Router` decides, line by line, what to rewrite; everything else is forwarded as the original
bytes. Standard library only.
"""
import json
import subprocess
import sys
import threading

from . import patch_format
from .stdio_client import _kill_tree, _spawn, child_environment, resolve_command


def _stderr_log(text):
    print(f"mcp-fixer: {text}", file=sys.stderr, flush=True)


def _parse(raw):
    """The JSON object on this line, or None (not JSON, not an object, or too deeply nested)."""
    try:
        message = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return None
    return message if isinstance(message, dict) else None


def _dump(message):
    return (json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def _id_key(value):
    """Ids are keyed by their JSON text, so the string "1" and the number 1 stay different."""
    return json.dumps(value, sort_keys=True)


class Router:
    def __init__(self, patch, allow_stale=False, log=None):
        self.entries = patch["tools"]
        self.allow_stale = allow_stale
        self.log = log or _stderr_log
        self.pending = set()  # ids (as keys) of client tools/list requests awaiting a response
        self.rename_back = {}  # patched name -> original name, for renames applied this session
        self.seen = set()  # original names the server has listed
        self._warned = set()

    def _warn(self, key, text):
        if key not in self._warned:
            self._warned.add(key)
            self.log(text)

    # --- client to server -------------------------------------------------------------------
    def client_line(self, raw):
        message = _parse(raw)
        if message is None:
            return raw
        method = message.get("method")
        if method == "tools/list" and "id" in message:
            self.pending.add(_id_key(message["id"]))
            return raw
        if method == "tools/call":
            params = message.get("params")
            if (
                isinstance(params, dict)
                and isinstance(params.get("name"), str)
                and params["name"] in self.rename_back
            ):
                renamed = dict(message)
                renamed["params"] = dict(params, name=self.rename_back[params["name"]])
                return _dump(renamed)
        return raw

    # --- server to client -------------------------------------------------------------------
    def server_line(self, raw):
        message = _parse(raw)
        if message is None or "method" in message or "id" not in message:
            return raw
        key = _id_key(message["id"])
        if key not in self.pending:
            return raw
        self.pending.discard(key)
        result = message.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            return raw
        tools, changed = self._patch_page(result["tools"])
        if not changed:
            return raw
        patched = dict(message)
        patched["result"] = dict(result, tools=tools)
        return _dump(patched)

    def _patch_page(self, tools):
        names_on_page = {
            t["name"] for t in tools if isinstance(t, dict) and isinstance(t.get("name"), str)
        }
        out = []
        changed = False
        for tool in tools:
            if not (isinstance(tool, dict) and isinstance(tool.get("name"), str)):
                out.append(tool)
                continue
            name = tool["name"]
            self.seen.add(name)
            entry = self.entries.get(name)
            if entry is None:
                out.append(tool)
                continue
            base = entry.get("base")
            if base is not None and base != patch_format.fingerprint(tool) and not self.allow_stale:
                self._warn(
                    ("stale", name),
                    f"tool {name!r} changed since the patch was made; serving it unpatched "
                    "(use --allow-stale to apply anyway)",
                )
                out.append(tool)
                continue
            new, warnings = patch_format.apply_entry(tool, entry)
            for text in warnings:
                self._warn(("apply", name, text), text)
            new_name = new["name"]
            if new_name != name:
                if new_name in names_on_page:
                    self._warn(
                        ("collision", name),
                        f"rename of tool {name!r} to {new_name!r} skipped: "
                        "another tool on the page has that name",
                    )
                    new["name"] = name
                else:
                    self.rename_back[new_name] = name
            if new != tool:
                changed = True
            out.append(new)
        return out, changed

    def finish(self):
        for name in sorted(self.entries):
            if name not in self.seen:
                self._warn(("missing", name), f"tool {name!r} is in the patch but the server never listed it")


SHUTDOWN_GRACE_SECONDS = 5.0
_OUTPUT_JOIN_SECONDS = 2.0


def _exit_code(returncode):
    return returncode if returncode is not None and 0 <= returncode <= 255 else 1


def run_wrapper(patch, command, allow_stale=False, stdin=None, stdout=None, log=None):
    """Run `command` behind the patch: client on `stdin`/`stdout`, real server on pipes.

    Returns the exit code for the wrapper process. Raises ClientError when the server cannot be
    started.
    """
    stdin = stdin if stdin is not None else sys.stdin.buffer
    stdout = stdout if stdout is not None else sys.stdout.buffer
    router = Router(patch, allow_stale, log)
    proc = _spawn(resolve_command(command), child_environment(inherit=True), stderr=None)
    done = threading.Event()
    out_lock = threading.Lock()

    def server_to_client():
        try:
            for raw in proc.stdout:
                data = router.server_line(raw)
                with out_lock:
                    stdout.write(data)
                    stdout.flush()
        except (OSError, ValueError):
            pass
        finally:
            done.set()

    def client_to_server():
        try:
            for raw in stdin:
                proc.stdin.write(router.client_line(raw))
                proc.stdin.flush()
        except (OSError, ValueError):
            pass
        finally:
            try:
                proc.stdin.close()
            except (OSError, ValueError):
                pass
            done.set()

    output_thread = threading.Thread(target=server_to_client, daemon=True)
    input_thread = threading.Thread(target=client_to_server, daemon=True)
    output_thread.start()
    input_thread.start()
    done.wait()

    stopped = False
    try:
        proc.wait(timeout=SHUTDOWN_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        stopped = True
        _kill_tree(proc, graceful=True)
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            _kill_tree(proc, graceful=False)
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
    output_thread.join(timeout=_OUTPUT_JOIN_SECONDS)  # let the server's last words reach the client
    _kill_tree(proc, graceful=False)  # POSIX: stop descendants the server left behind
    if not output_thread.is_alive():
        try:
            proc.stdout.close()
        except (OSError, ValueError):
            pass
    router.finish()
    return 0 if stopped else _exit_code(proc.returncode)
