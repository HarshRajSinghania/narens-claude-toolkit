# mcp-fixer: score an MCP server's tool definitions

> Scores an MCP server's tool definitions with deterministic lint rules, so you can see what makes agents pick the wrong tool or waste tokens.

Part of [Naren's Claude Toolkit](https://github.com/NarenDawar/narens-claude-toolkit). This is the first of three planned parts: **score** (this), then a patcher and wrapper that apply the fixes, then a benchmark that shows tool selection did not get worse.

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

`--format json` gives a stable report with `schemaVersion: 1` (source, score, metrics, findings with fix hints, notes) for other tools to consume. The planned patcher reads it.

## Limits

- On Linux and macOS the whole process group of a spawned server is stopped when scoring ends. On Windows a process the server started that outlives the server itself is not found and keeps running; the tool still finishes on time.
- A server that floods the client with requests is cut off after 50 of them.

## Not in this version

Calling tools (so no check that errors are consistent), remote HTTP or OAuth connections (use `--tools-json` for those), any model or accuracy benchmark, and writing patches.

## Tests

```text
python -m unittest discover -s servers/mcp-fixer/tests
```

They run in the repository's CI on Python 3.9 and 3.12 against a small fake MCP server.

---

Made by [Naren](https://github.com/NarenDawar). If this helped, star the repo.
