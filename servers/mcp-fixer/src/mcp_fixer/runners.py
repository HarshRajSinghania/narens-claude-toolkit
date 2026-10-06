"""Ways to ask a model a question: `claude -p`, the Anthropic API, and a test double."""
import http.client
import json
import os
import subprocess
import urllib.error
import urllib.request

from .stdio_client import ClientError, _kill_tree, _spawn, child_environment, resolve_command

MAX_OUTPUT_CHARS = 200000
DEFAULT_API_MODEL = "claude-sonnet-5-5"


class RunnerError(Exception):
    """A model call failed; the message is one line and never contains a secret."""


def _one_line(text, limit=200):
    return " ".join(str(text).split())[:limit]


def _check_key(key):
    """Refuse a key that cannot be a header value, without ever echoing it.

    http.client would reject it and quote it in its own error text, which our redaction (which
    looks for the raw key) would not recognise.
    """
    if not key or any(not 0x21 <= ord(char) <= 0x7E for char in key):
        raise RunnerError("the API key contains spaces or control characters; check ANTHROPIC_API_KEY")


class FakeRunner:
    """Calls a function instead of a model (for tests)."""

    def __init__(self, function, label="fake"):
        self.function = function
        self.label = label

    def complete(self, prompt):
        return self.function(prompt)

    def describe(self):
        return self.label


class ClaudeRunner:
    """Runs `claude -p` with no tools and no saved session; the prompt goes on stdin."""

    def __init__(self, model=None, timeout=120, command=("claude",)):
        self.model = model
        self.timeout = timeout
        self.command = tuple(command)

    def describe(self):
        return f"claude -p ({self.model or 'default model'})"

    def complete(self, prompt):
        # --strict-mcp-config: without it the user's own MCP servers (including the one being
        # benchmarked) would still load, bias the model and could even be called.
        argv = list(self.command) + ["-p", "--tools", "", "--no-session-persistence", "--strict-mcp-config"]
        if self.model:
            argv += ["--model", self.model]
        try:
            proc = _spawn(resolve_command(argv), child_environment(inherit=True))
        except ClientError as exc:
            raise RunnerError(str(exc)) from None
        try:
            out, err = proc.communicate(prompt.encode("utf-8"), timeout=self.timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc, graceful=False)
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            raise RunnerError(f"claude timed out after {self.timeout} seconds") from None
        except OSError as exc:
            _kill_tree(proc, graceful=False)
            raise RunnerError(f"claude failed: {exc.strerror or exc}") from None
        if proc.returncode != 0:
            lines = err.decode("utf-8", errors="replace").strip().splitlines()
            detail = f": {_one_line(lines[0])}" if lines else ""
            raise RunnerError(f"claude exited with code {proc.returncode}{detail}")
        return out.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]


class ApiRunner:
    """One POST to the Messages API per call, with the standard library only."""

    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, model, api_key, timeout=120, max_tokens=64, url=URL):
        self.model = model
        self._key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.url = url

    def describe(self):
        return f"Anthropic API ({self.model})"

    def _redact(self, text):
        return _one_line(str(text).replace(self._key, "[key]")) if self._key else _one_line(text)

    def complete(self, prompt):
        _check_key(self._key)
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={
                "x-api-key": self._key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(2000000)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                parsed = json.loads(exc.read(4000).decode("utf-8", errors="replace"))
                detail = parsed["error"]["message"]
            except (ValueError, KeyError, TypeError, OSError):
                detail = exc.reason
            raise RunnerError(f"API error {exc.code}: {self._redact(detail)}") from None
        except TimeoutError:
            raise RunnerError(f"the API call timed out after {self.timeout} seconds") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as exc:
            reason = getattr(exc, "reason", exc)
            if "timed out" in str(reason):
                raise RunnerError(f"the API call timed out after {self.timeout} seconds") from None
            raise RunnerError(f"network error: {self._redact(reason)}") from None
        try:
            blocks = json.loads(raw.decode("utf-8"))["content"]
            texts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        except (ValueError, KeyError, TypeError):
            raise RunnerError("unexpected API response") from None
        if not texts:
            raise RunnerError("unexpected API response")
        return "".join(texts)[:MAX_OUTPUT_CHARS]


def make_runner(name, model=None, env=None, timeout=120, max_tokens=64):
    """The runner called `name` ("claude" or "api"). The api runner needs ANTHROPIC_API_KEY."""
    if name == "claude":
        return ClaudeRunner(model=model, timeout=timeout)
    if name == "api":
        key = (env if env is not None else os.environ).get("ANTHROPIC_API_KEY")
        key = (key or "").strip()  # a key read from a file often carries a trailing newline
        if not key:
            raise RunnerError("ANTHROPIC_API_KEY is not set; the api runner needs it")
        _check_key(key)
        return ApiRunner(model or DEFAULT_API_MODEL, key, timeout, max_tokens)
    raise RunnerError(f"unknown runner {name!r}")
