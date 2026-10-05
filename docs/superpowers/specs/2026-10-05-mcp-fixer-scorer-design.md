# mcp-fixer: the scorer (sub-project 1 of 3)

Date: 2026-10-05

## Purpose

`mcp-fixer` is a tool for improving MCP servers so agents choose and call their tools correctly and spend fewer tokens on tool definitions. The whole project has three independent sub-projects, each with its own spec, plan and review:

1. **Score (this spec):** connect to an MCP server (or read a saved tool list) and produce a deterministic lint score with findings.
2. **Patch and wrap:** turn findings into a patch and run a proxy MCP server that forwards to the real server with the patch applied (shorter descriptions, enum constraints, normalized errors).
3. **Prove:** a before/after tool-selection benchmark showing the patch did not hurt accuracy. This needs a model and an API-key decision and is designed later.

This spec covers only sub-project 1. It is useful on its own, needs no model, and its rules become the patcher's to-do list.

## Success criteria

1. `python -m mcp_fixer score -- <server command>` connects to a stdio MCP server, lists its tools without calling any, and prints a score from 0 to 100 with per-tool scores and findings.
2. `--tools-json FILE` scores a saved `tools/list` result with no process started.
3. The same input always gives the same score and the same findings (deterministic, no model, no network).
4. The JSON report is stable and versioned so the patcher can consume it.
5. A failing, hanging or misbehaving server produces a one-line error and exit code 2, never a hang or a traceback.
6. The server's own tests pass on Python 3.9 and 3.12 in CI, and the project is listed under MCP servers in the catalog.

## Decisions already made

- **Decomposition:** score, then patch and wrap, then prove, in that order.
- **Standard library only, Python 3.9+.** No MCP SDK dependency. The client implements only the slice of the protocol the scorer needs.
- **Two input modes:** spawn a stdio server, or read a saved tool-list JSON file. Remote HTTP and OAuth transports are out of scope; a remote server can be scored through the offline file.
- **Read-only:** only `initialize` and `tools/list` are ever sent. No tool is ever called.
- **Lives in `servers/mcp-fixer/`** under the toolkit's MCP server layout. It is not a plugin and is not listed in `marketplace.json`.

## Constraints and assumptions

- Protocol facts were checked against the official MCP specification, revision 2025-06-18:
  - stdio messages are individual JSON-RPC messages delimited by newlines, with no embedded newlines; the server may log on stderr and must not write anything but MCP messages to stdout.
  - The client must send `initialize` first with `protocolVersion`, `capabilities` and `clientInfo` (`name`, `version`, optional `title`), wait for the response, then send the `notifications/initialized` notification. The server answers with the same version if it supports it, otherwise another version it supports.
  - `tools/list` takes optional `params.cursor` and answers `result.tools` plus an optional `result.nextCursor`. A tool has `name`, optional `title`, `description`, `inputSchema` (JSON Schema), optional `outputSchema` and `annotations`.
  - Shutdown for stdio: close the server's stdin, wait, then terminate, then kill.
  - Implementations should enforce timeouts on requests.
- Real servers do not always follow the spec: some print banners to stdout. The client ignores stdout lines that are not JSON.
- The client accepts whatever protocol version the server answers with and records it in the report; the tool-list shape is stable across versions.
- The client declares no capabilities, so a server has no reason to send requests other than `ping`; the client answers a `ping` request with an empty result.
- The score is a lint score, not a measure of agent accuracy, and its weights are not calibrated against any outside benchmark. The pitch that motivated the project cites an average scanner score of 16.2 out of 100 and tool definitions costing tens of thousands of tokens; those figures are the project owner's research and are not verified here.
- Scoring a server that needs credentials (an API key in its environment) works through `--env`; no secrets are read from the caller's environment unless passed.
- Windows launches many servers through `npx.cmd`; the client must resolve the command with `shutil.which`.

## Interface

`python -m mcp_fixer score [options] (--tools-json FILE | -- COMMAND [ARGS...])`

- Exactly one input mode: `--tools-json FILE` (the file is either `{"tools": [...]}` or a bare array) or the server command after `--`.
- `--env KEY=VALUE` (repeatable): environment passed to the server in addition to a minimal base (`PATH`, `PATHEXT`, `COMSPEC`, `LANG`, the temp folders, the home and profile variables, and the Windows system variables such as `SYSTEMROOT`, `SYSTEMDRIVE`, `PROGRAMDATA` and `PROGRAMFILES`; without the Windows ones a component started through `cmd.exe` cannot expand `%SystemDrive%` and creates a folder with that literal name in the working directory).
- `--timeout SECONDS` (default 30): per-request timeout; the whole connection is also capped at four times the timeout.
- `--format text|json` (default `text`), `--out FILE` (when given, the report is written to FILE instead of stdout; errors still go to stderr).
- `--min-score N`: exit code 1 when the score is below N.
- Exit codes: 0 success, 1 score below `--min-score`, 2 usage or connection error with a one-line `error:` message on stderr.

## Report

JSON, `schemaVersion: 1`:

```
{
  "schemaVersion": 1,
  "source": {"kind": "stdio" | "file", "protocolVersion": "...", "serverName": "...", "serverVersion": "..."},
  "score": 0..100,
  "metrics": {"toolCount": n, "estimatedTokens": n, "perTool": {"<name>": {"estimatedTokens": n, "score": n}}},
  "findings": [{"rule": "P003", "severity": "high|medium|low", "tool": "<name>|null", "param": "<name>|null",
                "message": "...", "evidence": "...", "fix": "...", "data": {...}}]
}
```

`serverName`, `serverVersion` and `protocolVersion` are null for the file mode. The report also has a `notes` array of plain strings (for example `no tools listed`), and each `perTool` entry also carries `findings`, the number of findings about that tool. `data` holds machine-readable fix hints for the patcher (for example `{"action": "add-enum", "values": ["a", "b"]}`). The text format shows the same content for people: the score, a per-tool table, findings grouped by tool, and the metrics.

## Rules

Every rule is a deterministic function over the tool JSON. Thresholds and weights live in one table in `rules.py`.

| Id | Severity | Fires when |
| --- | --- | --- |
| D001 | high | a tool has no description (missing, empty or whitespace) |
| D002 | medium | a description is shorter than 20 characters |
| D003 | medium | a description is longer than 500 characters |
| D004 | medium | two tools have near-identical descriptions: the Jaccard overlap of their lower-cased word sets is 0.8 or more (reported once per pair, on both tools) |
| P001 | medium | a parameter has no description |
| P002 | medium | a parameter has no `type` and no `enum`, `oneOf`, `anyOf`, `allOf`, `const` or `$ref` (older Pydantic emits `allOf` with a `$ref` for enum-typed fields) |
| P003 | medium | a string parameter's description lists allowed values ("one of a, b, c", "either X or Y", "must be a, b or c", "can be ...", "options: ...", or three or more quoted values) and the parameter has no `enum`; the extracted values are the fix hint; values after an example marker (`e.g.`, `for example`, `for instance`, `such as`, `like`, `examples`) are examples, not allowed values, and are ignored |
| P004 | high | `inputSchema` is missing or its `type` is not `object` |
| P005 | low | a tool has two or more parameters and no `required` list |
| P006 | low | a schema is nested more than 3 levels deep |
| N001 | medium | a tool name is generic: `run`, `execute`, `call`, `do`, `action`, `tool`, `query` (case-insensitive, whole name) |
| N002 | low | tool names mix naming styles (snake_case, camelCase, kebab-case); reported once for the server, on no tool |
| T001 | medium | the server has more than 40 tools (server-level) |
| T002 | medium or high | estimated definition size over 8,000 tokens (medium) or 20,000 tokens (high) (server-level) |
| M001 | high | a tool entry is malformed (not an object, or no string `name`); it is reported and skipped |

Estimated tokens are the length of each tool's canonical JSON (`sort_keys`, compact separators) divided by 4, rounded up. It is a documented heuristic, not a tokenizer.

## Score

- Each tool starts at 100 and loses 25 per high, 10 per medium, 4 per low finding about it, never below 0. Findings on pair rules (D004) count against both tools.
- The server score is the mean of the tool scores, minus 5 for T001 and minus 5 for a medium or 15 for a high T002, and a further penalty of 4 for N002, clamped to 0..100 and rounded to the nearest integer (half up). A malformed entry (M001) is skipped from the mean and counted as a high finding against the server score: minus 25, clamped as above. An empty tool list scores 100 with a note and no findings.

## Edge cases

- Non-ASCII text, very long descriptions, and tools with no properties are handled; a schema that is not a JSON object is P004.
- A `properties` value that is not an object, or a property schema that is not an object, counts as a property with no type (P002).
- Duplicate tool names are reported by the client as received; the scorer scores each entry (the patcher will decide what to do).
- A `--tools-json` file that is not JSON, or has neither `tools` nor an array, is a usage error (exit 2).

## Structure

```
servers/mcp-fixer/
  pyproject.toml              name mcp-fixer, version 0.1.0, Python >=3.9, console script mcp-fixer, no dependencies
  README.md                   first "> " line is the catalog description
  src/mcp_fixer/__init__.py
  src/mcp_fixer/__main__.py   python -m mcp_fixer
  src/mcp_fixer/cli.py        arguments, exit codes, output
  src/mcp_fixer/stdio_client.py   minimal MCP stdio client
  src/mcp_fixer/rules.py      rule functions and the weights/thresholds table
  src/mcp_fixer/score.py      pure scoring
  src/mcp_fixer/report.py     text rendering
  tests/                      unittest, fixtures/, fake_server.py
```

Seams the patcher will reuse: `score_tools(tools) -> report dict` (pure) and `list_tools_stdio(command, env, timeout) -> (tools, server_info)`.

### The stdio client

- Launches the command with `subprocess.Popen` (resolved with `shutil.which`; no shell), a minimal environment plus `--env` values, pipes for stdin and stdout, and stderr captured to a bounded buffer (last 8 KiB) used in error messages.
- Reads stdout line by line on a reader thread; a line that is not a JSON object is ignored; a JSON-RPC response is matched by id; a request from the server named `ping` is answered with `{}`; other server requests are answered with a method-not-found error; notifications are ignored.
- Sends `initialize` with the latest protocol version it knows (2025-06-18), empty capabilities and `clientInfo` of `mcp-fixer`, waits for the response, sends `notifications/initialized`, then pages `tools/list` until there is no `nextCursor` (capped at 200 pages as a loop guard).
- Any timeout, early exit, JSON-RPC error response or closed stdout raises a client error with a one-line message that includes the server's last stderr line when there is one.
- Always shuts down: close stdin, wait briefly, terminate, then kill. Kills the whole process tree on timeout. On POSIX the server leads its own process group, so descendants are stopped even after the server has exited; on Windows a descendant that outlives its server is not found (the tool still finishes on time, and the README says so). Pipes are closed only when no reader thread is still blocked on them.
- At most 50 requests from the server are answered (a real server sends a ping or two); more is a flood and an error, because replies to a server that never reads would otherwise block the client's writes. Error messages are collapsed to one line of at most 200 characters.

## Testing

Written first, with `unittest` (the repo's runner), in `servers/mcp-fixer/tests/`:

- **Rules:** every rule has a firing case and a non-firing case on fixture tool lists (a clean server, a bad one, edge cases), including the P003 phrasings and the D004 threshold boundary.
- **Score:** arithmetic checked against hand-computed fixtures, including floors, T001/T002/N002 penalties, M001, the empty list, and rounding.
- **Report:** the JSON shape is pinned; the text rendering contains the score, each tool and each finding.
- **CLI:** exit codes 0, 1 and 2; `--min-score`; `--out`; bad or missing files; neither or both input modes.
- **stdio client** against `fake_server.py`, a plain-Python stdio MCP server: a normal handshake; paginated `tools/list`; a stray non-JSON line on stdout; a server that sends `ping`; a server that never answers (timeout, process killed); a server that crashes after `initialize`; a server that exits immediately; a server that answers with an error; and a command that does not exist.
- **Windows:** command resolution of a `.cmd` shim is covered by a test that uses a small `.cmd` or `.bat` file on Windows and is skipped elsewhere.
- Determinism: the same fixture scored twice gives byte-identical JSON.

## Repo integration

- The README catalog lists it under MCP servers via its README's first `> ` line (the generator reads it). It is not added to `marketplace.json`.
- `.github/workflows/validate.yml` gains a job that runs `python -m unittest discover -s servers/mcp-fixer/tests` on Python 3.9 and 3.12; the existing job is unchanged.
- `CHANGELOG.md` gets an `Added` entry.
- `.gitignore` covers `servers/*/.venv/`, `servers/*/build/`, `servers/*/dist/` and `*.egg-info/`.
- The repo's `validate.py` already checks a server folder (kebab-case name, README with a `> ` line, a `pyproject.toml`).
- A live check is the owner's: run it against a real server (for example an official example server through `npx`) and read the score. It is not part of the tests.

## Out of scope for this sub-project

- Calling tools, and therefore checking that errors are consistent.
- HTTP, SSE and OAuth transports.
- Any model, accuracy benchmark or token-exact counting.
- Generating or applying patches, or running a wrapper.
- A skill or plugin wrapper around the tool.
- Publishing to PyPI.
