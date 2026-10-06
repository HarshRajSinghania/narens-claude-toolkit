# mcp-fixer: the patcher and wrapper (sub-project 2 of 3)

Date: 2026-10-05

## Purpose

Sub-project 1 (the scorer) finds what is wrong with an MCP server's tool definitions. This sub-project fixes what can be fixed without changing the server: it writes a **patch file** from the scorer's findings, and runs a **wrapper**, a transparent stdio proxy that sits in front of the real server and shows the client the patched tool definitions. The accuracy proof (does tool selection stay as good?) is sub-project 3 and is not claimed here.

## Success criteria

1. `mcp-fixer patch` writes a valid patch from a server's tool list: deterministic, with the mechanical fixes filled in and everything else left as `todo` entries; it never overwrites an existing file without `--force`.
2. `mcp-fixer wrap --patch FILE -- <real server command>` in front of a stdio server shows the client the patched `tools/list`; every other message passes through byte for byte; a call to a renamed tool reaches the real server under its original name.
3. A stale patch (the server's tool changed since the patch was made) serves that tool unpatched and warns once; a broken patch is a one-line error and exit code 2 before the real server is spawned.
4. Shutdown propagates both ways with no hang and no orphaned server process (on Windows with the same limit as the scorer: a descendant that outlives its server is not found).
5. The tests pass in CI on Python 3.9 and 3.12 and in the local Windows run.

## Decisions already made

- **Who writes the patch content:** a deterministic generator fills what is mechanical; the rest becomes `todo` entries a person (or later a Claude Code skill) fills. The tool stays model-free: no model, no API key, no network.
- **What the wrapper can apply:** metadata overrides (tool description, parameter `description`/`type`/`enum`/`default`, `required`) and tool renames. Error normalization (rewriting tool results) is out of scope: it changes live server behavior and "consistent" is not yet well defined.
- **The wrapper never changes behavior beyond names:** it never enforces an enum, never alters `tools/call` arguments (only a renamed tool's name goes back to the original), and forwards every unpatched message as the original bytes.
- **Standard library only, Python 3.9+,** in the existing package `servers/mcp-fixer/` (version 0.2.0).

## Constraints and assumptions

- stdio transport framing per the MCP specification (revision 2025-06-18): one JSON-RPC message per line, no embedded newlines; the server may log on stderr. A line that is not a JSON object (including a batch array) is forwarded unchanged.
- The wrapper is run by an MCP client as the server command, so unlike `score` it passes the caller's full environment to the real server, and the real server's stderr goes straight through to the client's stderr. The wrapper's own diagnostics go to stderr, one line each, prefixed `mcp-fixer: `.
- Streams are binary (`sys.stdin.buffer`, `sys.stdout.buffer`) so Windows newline translation cannot alter a message.
- Whether patched tool definitions improve tool selection is not known; sub-project 3 will measure it. The README says so.
- The two pump directions run on separate threads so a full pipe in one direction cannot block the other.
- Scorer limits carry over: an unbounded line is read whole; on Windows a process the server started that outlives it is not stopped.

## The patch file

JSON, UTF-8, written with two-space indentation:

```
{
  "patchVersion": 1,
  "source": {"serverName": "...", "serverVersion": "..."},
  "notes": ["..."],
  "tools": {
    "<original tool name>": {
      "base": "<sha256 hex of the original tool definition>",
      "rename": "<new name>",
      "description": "<replacement text>",
      "params": {"<parameter>": {"description": "...", "type": "string", "enum": ["a", "b"], "default": "a"}},
      "required": ["<parameter>", "..."],
      "review": ["<note>"],
      "todo": [{"rule": "P001", "param": "q", "hint": "..."}],
      "context": {"description": "<original text>", "params": {"<parameter>": "<original description>"}}
    }
  }
}
```

- `patchVersion` (must be 1) and `tools` (an object) are required. `source` (an object) and `notes` (a list of strings) are optional and ignored by the wrapper.
- A tool entry is keyed by the tool's original name. Every field is optional. Unknown fields are an error (to catch typos).
- `base` is the SHA-256 (lower-case hex) of the original tool definition as received, serialized as canonical JSON (`sort_keys`, compact separators, `ensure_ascii=False`, UTF-8).
- `rename`: a non-empty string different from the original name. `description`: a string. `params`: an object whose values are objects with only the keys `description` (string), `type` (a string or a list of strings), `enum` (a non-empty list of strings, numbers, booleans or null) and `default` (any JSON value). `required`: a list of unique strings.
- `review`, `todo` and `context` are notes for people; the wrapper ignores them. `review` is a list of strings; `todo` a list of objects with `rule` (string), optional `param` (string) and `hint` (string); `context` an object.
- Validation (all one-line errors naming the tool and field): the types above; two entries renaming to the same name; a rename equal to another entry's key.

### Applying an entry to a tool

`apply_entry(tool, entry)` returns a modified deep copy and a list of warnings:

- `rename` sets `name`; `description` sets `description`.
- For each `params` entry: if the tool's `inputSchema` has a `properties` object containing that parameter, the listed keys are set on that property (a property that is not an object becomes one); a parameter that does not exist is skipped with a warning.
- `required` sets `inputSchema.required` to the listed names that exist in `properties`; names that do not exist are dropped with a warning. When the tool has no usable `inputSchema`, `params` and `required` are skipped with a warning.
- Key order is preserved; a new key is appended.

## `mcp-fixer patch`

`mcp-fixer patch (--tools-json FILE | -- COMMAND [ARGS...]) [--env KEY=VALUE] [--timeout SECONDS] [--out FILE] [--force]`

- Reads tools exactly as `score` does (same two input modes, the same minimal child environment, the same limits and errors), scores them, and writes a patch to stdout, or to `--out`. With `--out` an existing file is an error (`error: FILE exists; use --force to overwrite`, exit 2) unless `--force` is given.
- **Filled in by the generator**, each with a `review` note:
  - P003: `params[<parameter>].enum` set to the values found in the description (note: `parameter 'x': enum inferred from its description (N values); check the list is complete`).
  - D003: `description` set to the original trimmed to at most 500 characters (note: `description trimmed from N to M characters`). Trimming collapses whitespace, then keeps whole sentences (split after `.`, `!` or `?` followed by whitespace) while they fit; when the first sentence alone is too long it is cut at a word boundary and ends with `…`. The result is always 500 characters or fewer.
- **Left as `todo` entries** (rule, optional param, and the finding's fix text as `hint`): D001, D002, D004 (the hint names the other tool), P001, P002, P004, P005, P006, N001. N001's todo suggests renaming; no rename is invented.
- Every tool with an entry gets `base` and a `context` snapshot (the original description and each parameter's original description). Tools with no actionable finding get no entry.
- Server-level findings (N002, T001, T002, M001) go in the top-level `notes` as their finding messages. Duplicate tool names cannot be patched separately: only the first gets an entry, and a note says so.
- Output is deterministic (same input, same bytes) and always passes the patch validation.
- Exit codes as `score`: 0, or 2 for usage and connection errors. It never calls a tool.

## `mcp-fixer wrap`

`mcp-fixer wrap --patch FILE [--allow-stale] -- COMMAND [ARGS...]`

### Startup

1. Load and validate the patch. Any problem is `error: ...` on stderr and exit code 2, before the real server is spawned.
2. Resolve and spawn the real server (the scorer's `resolve_command`, binary pipes for stdin and stdout, stderr inherited, the full environment, its own process group on POSIX).
3. Start two pump threads and wait.

### Message handling

- **Client to server** (`tools/call` only): when the request's `params.name` is a patched name currently in the active rename map, the line is re-serialized with the original name; nothing else in the request changes. Every other client line is forwarded as the original bytes.
- **Tracking:** a client request whose `method` is `tools/list` has its `id` recorded (the key is the JSON text of the id, so `"1"` and `1` differ). A server message without a `method` and with a recorded `id` is the response.
- **Server to client:** that `tools/list` response has each entry of `result.tools` patched, and is re-serialized compactly; its id is forgotten. Error responses and every other server line are forwarded as the original bytes.
- **Per tool on a page:**
  - no entry in the patch: unchanged;
  - an entry whose `base` is present and differs from the fingerprint of the tool as received (stale): the tool is passed unchanged and one warning for that tool is printed per session (`mcp-fixer: tool 'x' changed since the patch was made; serving it unpatched (use --allow-stale to apply anyway)`); with `--allow-stale` the entry is applied;
  - otherwise the entry is applied (an entry with no `base` is always applied).
- **Renames:** an applied rename puts `new name -> original name` in the active rename map. A rename whose new name equals the name of another tool on the same page is skipped with a warning, and the tool keeps its name. A page that renames nothing leaves the map as it is.
- **Warnings** (each printed once): a tool named in the patch that never appears in any `tools/list` response during the session (printed when the client side closes), a skipped parameter or `required` name, a skipped rename.
- **`notifications/tools/list_changed`** and everything else pass through; the client re-lists and the new page is patched the same way.
- Unparseable lines, non-object JSON (including batch arrays) and messages without the shapes above are forwarded unchanged.

### Lifetime

- **The client closes stdin:** close the real server's stdin, wait up to 5 seconds for it to exit, then stop it (the scorer's terminate-then-kill, the process group on POSIX). The wrapper exits with 0 when it had to stop the server, otherwise with the server's own exit code.
- **The real server exits first:** flush what it wrote, then exit with its exit code (an exit code outside 0 to 255 becomes 1).
- A failure to start the real server is `error: cannot start the server: ...`, exit 2.
- A write to a closed pipe on either side ends that pump quietly and starts the shutdown above; the wrapper never prints a traceback.

## Structure

New in `servers/mcp-fixer/src/mcp_fixer/` (the scorer files are unchanged except `cli.py` and `stdio_client.py`):

- `patch_format.py`: `fingerprint(tool)`, `load_patch(path)`, `validate_patch(data)`, `apply_entry(tool, entry)`, `PatchError`.
- `patch_gen.py`: `generate_patch(tools, source=None)`, `trim_description(text, limit=500)`.
- `wrap.py`: `Router` (pure message logic: `client_line(raw) -> bytes`, `server_line(raw) -> bytes`, warnings collected), `run_wrapper(patch, command, allow_stale)`.
- `cli.py`: the `patch` and `wrap` subcommands.
- `stdio_client.py`: `child_environment(extra, inherit=False)` gains an `inherit` option (pass the whole environment); `resolve_command`, `_spawn` and `_kill_tree` are reused.
- `pyproject.toml` and `__init__.py`: version 0.2.0.

## Testing

Written first, with `unittest`:

- **patch_format:** fingerprint stability and key-order independence; every invalid-patch case; each field of `apply_entry`, including missing parameters, a non-object property, no `inputSchema`, `required` names that do not exist, key order and no mutation of the input.
- **patch_gen:** the messy fixture gives an exact expected patch; enum with a review note; trimming at sentence boundaries, a first sentence over the limit, whitespace collapse, exact boundary lengths 499, 500 and 501; todo entries and `context`; server-level notes; duplicate names; determinism; the output validates; `--out` refuses to overwrite without `--force`.
- **Router (in memory):** every message rule above, including ids as strings and numbers, a response with an error, a page with several tools, a stale entry with and without `--allow-stale`, a rename collision, rename-back only for the active map, and unparseable or non-object lines forwarded unchanged.
- **Wrapper end to end,** as a subprocess between a test client and the fake server (extended with `tools/call`, `resources/list` and `tools/list_changed` modes): patched `tools/list` including pages; rename and rename-back; **byte-for-byte pass-through** of a server line with odd whitespace, key order and `\u` escapes; a broken patch exits 2 before the server starts (the fake server records whether it started); the client closing stdin stops the server and no process is left; the server crashing propagates its exit code; warnings appear once on stderr; stdout carries only protocol lines.
- **CLI:** exit codes, `--force`, `--out`, and the same input errors as `score`.

## Repo integration

- The existing CI job already runs this folder's tests on Python 3.9 and 3.12.
- `README.md` of the server gains usage for `patch` and `wrap`, the patch format, an MCP client configuration example, and the honest limits (no accuracy claim, error normalization not included).
- `CHANGELOG.md` gets an `Added` entry; the package version becomes 0.2.0.
- A live check is the owner's: put `wrap` in front of a real stdio server in an MCP client and compare the tool list.

## Out of scope for this sub-project

- Error or result normalization, and enforcing an enum.
- Merging or updating an existing patch (use `--force` and re-apply your edits).
- A model rewriting descriptions (a later skill's job).
- Remote HTTP, SSE and OAuth transports.
- The tool-selection accuracy proof (sub-project 3).
- Publishing to PyPI.
