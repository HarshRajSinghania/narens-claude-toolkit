# subagent-meter: design

Date: 2026-10-04

## Purpose

The first mod in narens-claude-toolkit: a live status line that shows how much of a session's token use goes to subagents, and which agent type uses the most. It is a companion to the `subagent-tax-auditor` skill. The auditor explains cost after the fact from transcripts; the meter makes the same effect visible while you work, so you notice a runaway fan-out as it happens.

## Success criteria

1. After a subagent finishes its first turn, a status line appears and updates after each later turn.
2. Its numbers match hand-computed fixtures (tokens added up the way this spec defines).
3. The meter never changes, delays or breaks a turn, even if its own code fails.
4. The counts survive a hot reload of the mod and reset on `/clear`.
5. `claude plugin validate`, the mod's tests and the repo's `validate.py` all pass, and the mod is listed under Mods in the catalog.

## Decisions already made

- **Tokens only, no prices.** The line shows token shares, never dollars, so it needs no price table and stays accurate when prices change.
- **Both shares side by side:** the share of output tokens and the share of all tokens. When "all" is far above "output", the gap is the subagent context tax.
- **Status line only.** No pane, band, slash command, nudge or configuration in this version.
- **Teammates count.** In-process teammates carry an `agentId` like subagents, so they count as agents of type `teammate`.
- **Session scope.** It measures the current session from live events; it does not read old transcripts (that is the auditor's job) and does not persist across sessions.

## Constraints and assumptions

- The mod API is early access and this build's declaration file is the authority (`claude-code` types written by the engine). The facts this design rests on were read there: `turn.complete` fires for the main loop and for each subagent turn; its input carries `agentId` (absent on the main loop) and `usage` (`input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, plus `model`); `$.agent.list()` maps an agent id to its type and status; `$.ui.status(text)` pins one status line per plugin and `undefined` clears it; `$.state.get`/`$.state.set` hold plain data that survives a hot reload and support `ifVersion` for safe concurrent writes.
- A plugin has exactly one hooks module (`claude plugin validate` refuses a second), named in `hooks/hooks.json`. That module may import other files of the plugin, so the logic lives in a second file.
- `usage` is absent on a turn that was interrupted or failed with an API error; such a turn adds nothing.
- The repo's CI runs on a runner without the Claude CLI, so the mod's own tests (`claude plugin test`) run locally and are not part of CI yet.
- Two behaviors are verified first in the implementation plan, before the rest is built: (a) that the test kit can raise a `turn.complete` event with an `agentId` and `usage`; (b) what `$.agent.list()` returns for an agent that has just finished its turn. If (a) fails, the hook is covered by pure-function tests only and the README says which part is untested. If (b) shows the agent absent, its type is `unknown`.

## Behavior

### What it observes

The mod hooks `turn.complete`. It always passes the event down with `next(e)` unchanged, and records afterwards. It never denies, rewrites or delays an event. Any error inside the recording is caught and ignored, so the turn is unaffected.

### How it counts

For each `turn.complete` that has `usage`:

- `output` is `output_tokens`.
- `all` is `input_tokens + cache_read_input_tokens + cache_creation_input_tokens + output_tokens`.
- A missing or non-finite number counts as 0; a negative number counts as 0.
- A turn with no `agentId` adds to the main thread.
- A turn with an `agentId` adds to that agent. The agent's type comes from `$.agent.list()`, looked up the first time its id is seen and stored with it; if it is not listed the type is `unknown`. Nested subagents are counted flat, like any other agent.
- Spawns are the number of distinct agent ids seen. An agent counts once it has finished a turn with usage.

### What it shows

One status line, refreshed after every counted turn:

`subagents 14x · 12% of output · 54% of all tokens · top Explore`

- A share is agent-side tokens divided by main plus agent-side tokens, rounded to a whole percent. A share above 0 and below 1 shows as `<1%`. When the total is 0 the share is `0%`.
- `top` is the agent type with the most `all` tokens; a tie goes to the name that sorts first; the name is cut at 16 characters.
- When no agent has been seen the line is removed (`undefined`), so quiet sessions show nothing.

### Lifetime

- Counts live in session state, so a hot reload keeps them; `session.start` redraws the line from saved state.
- `session.end` with `reason: 'clear'` resets the counts and removes the line.
- Counts do not persist across sessions.

## Structure

All in `plugins/subagent-meter/`:

```
.claude-plugin/plugin.json   name, version 0.1.0, description, author Naren, homepage and repository, license, keywords, "types": "./types/index.d.ts"
hooks/hooks.json             {"modules": ["./register.ts"]}
hooks/register.ts            glue: the hooks, the agent-type lookup, state reads and writes, the status line
hooks/meter.ts               pure logic (no engine calls)
hooks/meter.test.ts          unit tests for the pure logic
hooks/register.test.ts       hook tests using the mod test kit
types/index.d.ts             the PluginState contract for the saved counts
README.md
```

### Pure logic (`meter.ts`)

- `Stats = { main: { output, all }, agents: { [id]: { type, output, all } } }` and `emptyStats()`.
- `tokensOf(usage) -> { output, all }` as defined above.
- `addTurn(stats, { agentId?, type?, usage }) -> Stats`: returns a new value; a turn without `usage` returns the input unchanged.
- `summarize(stats) -> { spawns, outputShare, allShare, topType } | undefined`: `undefined` when no agent has been seen.
- `formatLine(summary) -> string`: exactly the line above.
- `statusLine(stats) -> string | undefined`: `summarize` then `formatLine`, `undefined` when no agent has been seen; the hooks call this one function.

### State and concurrency (`register.ts`)

- One state value, `{ plugin: 'subagent-meter', key: 'stats' }`, of type `Stats`. `plugin` and `key` are literals in source, as the engine requires.
- Every update goes through the engine's `update($, atom, fn)`, which reads, applies the pure `addTurn`, writes with `ifVersion` and retries on a miss, so concurrent subagent turns never lose tokens. The agent type is looked up before the update (only for an id not yet in state), because the function passed to `update` must be pure.
- State grows by roughly 100 bytes per distinct agent id. A session with thousands of agents stays well within limits; a cap is out of scope for this version.

### Hooks

- `turn.complete`: `next(e)`, then record (type lookup for an unseen id, update state, redraw the line).
- `session.start`: redraw from saved state.
- `session.end` with `reason: 'clear'`: reset state and clear the line.

## Repo integration

- `.claude-plugin/marketplace.json` gets an entry (`source: ./plugins/subagent-meter`); the README and `llms.txt` catalog list it under Mods (regenerate with `build_catalog.py`).
- `CHANGELOG.md`: an `Added` entry.
- `.gitignore`: `plugins/*/.claude-plugin/types/`, the declaration files the engine writes beside a loaded plugin.
- `plugin.json` `description` states what it does in one sentence; mods do not need the skills' "Use when" form.
- The README says what it shows, how to try it (`claude --plugin-dir plugins/subagent-meter`), how to read the two shares, how it differs from the auditor, and that its tests run locally.

## Testing and checks

- `meter.test.ts`: table-driven cases for `tokensOf` (each field, missing and negative values), `addTurn` (main turn, agent turn, repeated turns of one agent, unknown type, no usage), `summarize` (no agents, one agent, several types, ties, zero total), `formatLine` (whole percents, `<1%`, `0%`, long type name cut at 16, singular `1x`).
- `register.test.ts`: raising `turn.complete` for main and subagent turns updates the status line; the event passes through unchanged; a failing lookup or write does not break the event; two near-simultaneous turns both count; `session.end` with `clear` removes the line; `session.start` redraws from saved state.
- `claude plugin validate plugins/subagent-meter` passes, and the repo's `python scripts/validate.py` and unit tests pass.
- A live check is yours: run `claude --plugin-dir plugins/subagent-meter`, spawn a few subagents, and read the line.

## Out of scope

- Prices or dollar figures, a per-type table or pane, a slash command, nudges, configuration options.
- Reading transcripts or any history beyond the live session.
- A CI job that runs `claude plugin test`.
- A cap on stored agent records.
