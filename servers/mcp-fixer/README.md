# mcp-fixer: score, patch and benchmark an MCP server's tool definitions

> Scores an MCP server's tool definitions with deterministic lint rules, so you can see what makes agents pick the wrong tool or waste tokens.

Part of [Naren's Claude Toolkit](https://github.com/NarenDawar/narens-claude-toolkit). Three parts: **score** (finds the problems), **patch and wrap** (applies fixes without changing the server) and **bench** (checks whether tool selection got worse). Bench can detect a drop; it cannot show that a patch improves anything, and it says so.

## What it does

`mcp-fixer score` reads a server's tool list and prints a score from 0 to 100 with a finding for every problem it can see in the definitions: descriptions that are missing, too short or so long they waste tokens, tools whose descriptions are near-duplicates, parameters with no description or type, values listed in prose that should be an enum, generic or inconsistent tool names, and servers with too many tools or too large a definition.

It is read-only. It sends only `initialize` and `tools/list` to a server and never calls a tool, so scoring cannot change anything. It needs no model and no network, uses only the Python standard library, and gives the same answer every time.

## Use it

Python 3.9 or newer. From the repository root:

```text
PYTHONPATH=servers/mcp-fixer/src python -m mcp_fixer score -- npx -y some-mcp-server
PYTHONPATH=servers/mcp-fixer/src python -m mcp_fixer score --tools-json tools.json
```

(On Windows PowerShell set the variable first: `$env:PYTHONPATH = "servers/mcp-fixer/src"`.) The folder also has a `pyproject.toml` with a `mcp-fixer` console script, but installing it with `pip` is not verified or published yet.

- Give either the server command after `--` (a stdio server), or `--tools-json FILE`: a saved `tools/list` result, either `{"tools": [...]}` or a bare array. The file mode is how you score a remote server: export its tool list and score the file.
- `--env KEY=VALUE` (repeatable) passes an environment variable such as an API key to a spawned server. The server inherits only a small base environment (`PATH` and the system variables the platform needs) plus what you pass.
- `--timeout SECONDS` (default 30) limits each request; the whole connection is capped at four times that.
- `--format text|json` (default text), `--out FILE` to write the report to a file instead of printing it.
- `--min-score N` exits with code 1 when the score is below N, so a CI job can fail a build. Exit code 2 means a usage or connection error, with a one-line message.

```text
$ PYTHONPATH=servers/mcp-fixer/src python -m mcp_fixer score --tools-json servers/mcp-fixer/tests/fixtures/messy_tools.json
mcp-fixer score: 70/100
source: tool list file
tools: 3, estimated definition size: 92 tokens

tool         score  findings  tokens
run             46         6      41
searchItems     75         1      22
list_items     100         0      29

findings
  [low] N002 server: tool names mix naming styles
...
```

You are running whatever command you give it, exactly as when you add a server to Claude: only score servers you trust.

## Fix it: patch and wrap

`mcp-fixer patch` turns the findings into a patch file, and `mcp-fixer wrap` runs a proxy in front of the real server that shows the client the patched tool definitions. The real server is not changed. Options go before the `--`; everything after it is the server's own command.

```text
PYTHONPATH=servers/mcp-fixer/src python -m mcp_fixer patch --out orders.patch.json -- npx -y some-mcp-server
# edit orders.patch.json: fill in the todo entries, check the review ones
PYTHONPATH=servers/mcp-fixer/src python -m mcp_fixer wrap --patch orders.patch.json -- npx -y some-mcp-server
```

**What the generator fills in.** Enums that a parameter's description lists in prose, and descriptions over 500 characters trimmed to whole sentences. Each is noted under `review`, because an inferred enum may be incomplete and a trim loses text. **Everything else is a `todo`:** missing or short descriptions, undescribed or untyped parameters, generic names, a missing `required` list, near-duplicate descriptions. Those need real writing, by you or by Claude; the tool calls no model. `patch --out` never overwrites an existing file without `--force`.

**The patch file** is plain JSON, keyed by each tool's original name:

```json
{
  "patchVersion": 1,
  "tools": {
    "run": {
      "base": "<fingerprint of the original tool; filled in by patch>",
      "rename": "search_orders",
      "description": "Search orders by status or customer.",
      "params": {"order": {"description": "Sort order", "type": "string", "enum": ["asc", "desc"]}},
      "required": ["order"]
    }
  }
}
```

Every field is optional. A parameter entry may set `description`, `type`, `enum` and `default`. `review`, `todo`, `context` and `notes` are for people and are ignored by the wrapper. Unknown fields are an error, so typos are caught. A broken patch is a one-line error and exit code 2 before the real server starts. Tools with duplicate names cannot be patched separately: only the first gets an entry.

**What the wrapper does.** It forwards every message as the original bytes, except: it patches the tool list the server sends, and it turns a renamed tool's name back to the original on `tools/call`. It never enforces an enum and never changes call arguments or results. If a tool has changed since the patch was made (its fingerprint no longer matches `base`), that tool is served unpatched with one warning on stderr; `--allow-stale` applies the patch anyway. Put it where the real server's command goes in your MCP client's config, for example:

```json
{
  "mcpServers": {
    "orders": {
      "command": "python",
      "args": ["-m", "mcp_fixer", "wrap", "--patch", "orders.patch.json", "--", "npx", "-y", "orders-server"],
      "env": {"PYTHONPATH": "/path/to/servers/mcp-fixer/src"}
    }
  }
}
```

That configuration has not been tried in a real client yet; it is the standard `mcpServers` shape. Unlike `score`, the wrapper passes your whole environment to the real server, because it stands in for that server.

## Check it: tasks and bench

`mcp-fixer tasks` asks a model to write test requests for each of a server's tools and saves them to a file you can edit. `mcp-fixer bench` then runs every request against the original tool list and the patched one, exactly as `wrap` would serve it, and asks the model which tool it would choose. Nothing is ever called: the model only names a tool.

```text
PYTHONPATH=servers/mcp-fixer/src python -m mcp_fixer tasks --out tasks.json -- npx -y some-mcp-server
# review and edit tasks.json: fix any request whose expected tool is wrong
PYTHONPATH=servers/mcp-fixer/src python -m mcp_fixer bench --tasks tasks.json --patch orders.patch.json -- npx -y some-mcp-server
```

**Runners.** `--runner claude` (the default) runs `claude -p --tools "" --no-session-persistence --strict-mcp-config` (no built-in tools, and none of your MCP servers) with your existing login, so it needs no API key; it runs inside your own Claude Code configuration (CLAUDE.md, hooks, skills), which can influence replies, and on Windows a `claude` shim may drop the empty `--tools` argument (not checked in a live run). `--runner api` calls the Anthropic Messages API directly with temperature 0 and needs `ANTHROPIC_API_KEY` in the environment; the key is never printed or written anywhere. Use `--model` to pick the model.

**The tasks** are generated from the original tool list only, each request written without the tool's name; requests that still contain the name are dropped. They are a starting point: the answer key is only as good as the file, so read it.

**What bench does.** For every task and repeat (default 3) it shows the model the same tools in the same shuffled order, once as the server defines them and once patched, and scores the reply. A reply that is not a valid choice counts as wrong; a failed model call is retried once and then excluded and counted. A renamed tool's answer is mapped back to its original name. It makes `tasks x repeats x 2` model calls, prints that number first, and asks for `--yes` above 200.

**The verdict** accounts for how much data there is:

| Verdict | When | Exit code |
| --- | --- | --- |
| `worse` | the 95% interval of (patched minus original accuracy, paired by task) is entirely below zero | 1 |
| `no drop detected` | at least 30 usable tasks and the interval's lower bound is above minus `--tolerance` (default 0.05) | 0 |
| `inconclusive` | anything else: too few tasks, or an interval too wide to rule out a drop (the report says which, and about how many tasks it would take) | 0 |

The report also shows each side's accuracy with a 95% Wilson interval, the invalid rate, and the token sizes before and after. It always ends with: "This measures whether a drop could be detected on these generated tasks; it does not show the patch improves tool selection."

**Honest limits.** The tasks are written by a model, so they share its blind spots; one model is used per run, and one run is one sample. `no drop detected` is not evidence of an improvement. Nothing here has been run against a real server yet: a live run is yours to do.

## The rules

| Rule | Severity | Fires when |
| --- | --- | --- |
| D001 | high | a tool has no description |
| D002 | medium | a description is shorter than 20 characters |
| D003 | medium | a description is longer than 500 characters |
| D004 | medium | two tools have near-identical descriptions (80% or more of their words shared) |
| P001 | medium | a parameter has no description |
| P002 | medium | a parameter has no type (a `$ref`, `enum`, `oneOf`, `anyOf`, `allOf` or `const` counts as one) |
| P003 | medium | a string parameter's description lists the allowed values but it has no `enum` (values after `e.g.`, `such as`, `like` or `for example` are examples and are ignored) |
| P004 | high | the input schema is missing or is not an object schema |
| P005 | low | two or more parameters and no `required` list |
| P006 | low | the schema is nested more than 3 levels deep |
| N001 | medium | a tool has a generic name such as `run` or `execute` |
| N002 | low | tool names mix naming styles |
| T001 | medium | more than 40 tools |
| T002 | medium / high | definitions take more than about 8,000 / 20,000 tokens |
| M001 | high | a tool entry is malformed |

Each tool starts at 100 and loses 25, 10 or 4 points per high, medium or low finding. The server score is the mean of the tool scores minus the server-level penalties (T001 5, T002 5 or 15, N002 4, each M001 25). Token sizes are an estimate (the length of each tool's JSON divided by 4), not a real tokenizer.

## How to read the score

It is a lint score. It tells you the definitions have the kinds of problems that make tool choice harder and requests bigger; it does not measure how well an agent actually uses the server, and the weights are a starting point, not calibrated against any outside benchmark. Treat a low score as a to-do list, not a verdict.

## Report format

`--format json` gives a stable report with `schemaVersion: 1` (source, score, metrics, findings with fix hints, notes) for other tools to consume. `patch` builds on the same findings.

## Limits

- On Linux and macOS the whole process group of a spawned server is stopped when scoring ends. On Windows a process the server started that outlives the server itself is not found and keeps running; the tool still finishes on time.
- A server that floods the client with requests is cut off after 50 of them.
- The wrapper does not rewrite errors or results (error normalization is not included), and a patch cannot target tools with duplicate names separately.

## Not in this version

Calling tools (so no check that errors are consistent), remote HTTP or OAuth connections (use `--tools-json` for those), error normalization, and anything beyond choosing a tool: bench does not call tools, check arguments or test multi-step flows.

## Tests

```text
python -m unittest discover -s servers/mcp-fixer/tests
```

They run in the repository's CI on Python 3.9 and 3.12 against a small fake MCP server.

---

Made by [Naren](https://github.com/NarenDawar). If this helped, star the repo.
