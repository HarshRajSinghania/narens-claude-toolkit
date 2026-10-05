# subagent-meter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and ship `subagent-meter`, the toolkit's first mod: a live status line showing how much of a session's tokens go to subagents (a share of output tokens and a share of all tokens) and which agent type uses the most.

**Architecture:** One mod plugin, `plugins/subagent-meter/`. Pure logic lives in `hooks/meter.ts` (add a turn, summarize, format) and is unit-tested. `hooks/register.ts` is thin glue: it hooks `turn.complete`, `session.start` and `session.end`, keeps the counts in session state through the engine's `atom`/`read`/`update`, and writes one status line with `$.ui.status`. Tests run with `claude plugin test`; the repo's own `validate.py` checks the manifest and the module path.

**Tech Stack:** TypeScript hooks module for the Claude Code mod API (early access), the `claude plugin` CLI (`validate`, `test`), Python 3.9+ repo tooling, Markdown, JSON.

**Spec:** `docs/superpowers/specs/2026-10-04-subagent-meter-design.md`

## Global Constraints

- The meter only observes: it always passes `turn.complete` down with `next(e)` unchanged and records afterwards; it never denies, rewrites or delays an event, and an error inside its recording is caught and ignored.
- Tokens only, no prices: `output` is `output_tokens`; `all` is `input_tokens + cache_read_input_tokens + cache_creation_input_tokens + output_tokens`; a missing, negative or non-finite count is 0.
- A turn with no `agentId` is the main thread; any turn with an `agentId` is an agent (including in-process teammates, type `teammate`); nested agents count flat; a turn without `usage` adds nothing; spawns are distinct agent ids seen.
- The line is exactly `subagents 14x · 12% of output · 54% of all tokens · top Explore`: whole-percent shares, `<1%` for a share above 0 and below 1, `0%` when the total is 0, `top` is the type with the most `all` tokens (tie: the name that sorts first, plain string comparison), the type name cut at 16 characters. With no agent seen the status line is removed (`undefined`).
- Counts live in session state (survive a hot reload), reset on `session.end` with `reason: 'clear'`, and are redrawn on `session.start`. They do not persist across sessions and no transcript is read.
- Status line only: no pane, band, slash command, nudge, configuration, price table or stored-record cap.
- One hooks module per plugin (`hooks/hooks.json` names `./register.ts`); it may import other files of the plugin; every plugin file the engine loads ends in `.ts`/`.tsx`/`.jsx`/`.js`/`.mjs`/`.cjs`/`.mts`/`.cts`; no `import()` and no Node or DOM APIs.
- `plugin` and `key` of state references are literals in source: `{ plugin: 'subagent-meter', key: 'stats' } as const`.
- The mod lives in `plugins/subagent-meter/` in the repo and is never written into `~/.claude/dev-mods`; do not enable hot reloading. Live checking is the person's (`claude --plugin-dir plugins/subagent-meter`).
- Repo rules: LF line endings, author `Naren`, no old marketplace name outside history and the migration note (the guard test), generated catalog never hand-edited, `docs/superpowers/**` existing files untouched except the new subagent-meter spec edits in Task 1.
- Do not push, merge or change GitHub settings in this plan.
- Work on branch `subagent-meter` (already created, holds the spec commit).
- Scratch files live in the session scratchpad: `C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/4ec2fd29-f30d-4793-83a9-f979fbae59a4/scratchpad` (called `$SP`). Write patch scripts with the Write tool, not shell heredocs (the shell collapses backslashes).
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

**Clarifications decided in this plan** (spec details the plan makes precise):

- Concurrency uses the engine's own `update($, atom, fn)` (it reads, applies `fn`, writes with `ifVersion` and retries on a miss) instead of a hand-written retry loop. The agent type is therefore looked up before the update, and only for an id not yet in state, because `fn` must be pure.
- `meter.ts` also exports `statusLine(stats) -> string | undefined` (summarize then format), so the hooks call one function and the empty case is tested.
- Spec item (b), what `$.agent.list()` returns for an agent that has just finished, cannot be answered by the test kit (it stubs `agent.list`); it is answered in the person's live check. The code falls back to type `unknown` whenever the lookup fails or the agent is not listed.
- Repo integration (marketplace entry, catalog, `.gitignore`, README stub) is part of Task 1, so the repo's own test suite stays green from the first commit.

## Review Focus

Failure modes the spec implies but a first pass is likely to skip. Each has a test in the task that owns the code:

1. Two subagent turns finishing at the same moment must both be counted (no lost update). (Task 3)
2. A failure in the meter (the agent lookup throwing or returning nothing) must not change the turn's result, and the turn's tokens must still be counted with type `unknown`. (Task 3)
3. Bad numbers: missing, negative, `NaN` and `Infinity` counts, zero totals (no divide by zero), a share between 0 and 1 percent, and a type name longer than 16 characters. (Task 2)
4. A turn that has no `usage` (interrupted or errored) adds nothing and shows nothing; a session with only main-thread turns shows no line; an agent that finished a turn with zero tokens still counts as a spawn. (Tasks 2 and 3)
5. `/clear` resets the counts and removes the line, and an agent id seen before the clear does not leak into the count afterwards; `session.start` redraws the same line from saved state. (Task 3)

---

### Task 1: Scaffold the mod, integrate it in the repo, and spike the test kit

**Files:**
- Create: `plugins/subagent-meter/.claude-plugin/plugin.json`, `plugins/subagent-meter/hooks/hooks.json`, `plugins/subagent-meter/hooks/register.ts`, `plugins/subagent-meter/hooks/register.test.ts`, `plugins/subagent-meter/types/index.d.ts`, `plugins/subagent-meter/README.md` (stub)
- Modify: `.claude-plugin/marketplace.json`, `.gitignore`, `README.md` and `llms.txt` (regenerated), `docs/superpowers/specs/2026-10-04-subagent-meter-design.md`

**Interfaces:**
- Produces: the plugin folder every later task adds to; the state contract `PluginState['subagent-meter'] = { stats: MeterStats }` with `MeterStats = { main: { output: number; all: number }; agents: Record<string, { type: string; output: number; all: number }> }`, exported from `types/index.d.ts` (Tasks 2 and 3 import it as `import type { MeterStats } from '../types'`); a verified way to raise `turn.complete` and observe the status line in a test.

- [ ] **Step 1: Load the authoring skill (read-only here)**

Invoke the `plugin-authoring` skill. It starts a watch on the dev-mods folder, but this plan never writes there, so nothing is asked of the person. Its type declarations are at `C:/Users/naren/AppData/Local/Temp/claude/bundled-skills/2.1.288/8798925ac8eaea4076fcee004a76e685/plugin-authoring/types/claude-code.d.ts` (grep it for any name used below that does not compile).

- [ ] **Step 2: Write the manifest, hooks file, contract and a hooks-less module**

`plugins/subagent-meter/.claude-plugin/plugin.json`:

```json
{
  "name": "subagent-meter",
  "version": "0.1.0",
  "description": "A live status line showing how much of your session's tokens go to subagents, and which agent type uses the most.",
  "author": {
    "name": "Naren",
    "url": "https://github.com/NarenDawar"
  },
  "homepage": "https://github.com/NarenDawar/narens-claude-toolkit/tree/main/plugins/subagent-meter",
  "repository": "https://github.com/NarenDawar/narens-claude-toolkit",
  "license": "MIT",
  "keywords": ["claude-code", "claude-mods", "status-line", "subagents"],
  "types": "./types/index.d.ts"
}
```

`plugins/subagent-meter/hooks/hooks.json`:

```json
{ "modules": ["./register.ts"] }
```

`plugins/subagent-meter/types/index.d.ts`:

```ts
export type MeterAgent = { type: string; output: number; all: number }

export type MeterStats = {
  main: { output: number; all: number }
  agents: Record<string, MeterAgent>
}

declare module 'claude-code' {
  interface PluginState {
    'subagent-meter': { stats: MeterStats }
  }
}
```

`plugins/subagent-meter/hooks/register.ts` (empty on purpose, so the spike test below can fail first):

```ts
import type { Register } from 'claude-code'

export const register: Register = () => {}
```

`plugins/subagent-meter/README.md` (a stub, completed in Task 4):

```markdown
# subagent-meter: a Claude Code mod by Naren

> A live status line showing how much of your session's tokens go to subagents, and which agent type uses the most.
```

- [ ] **Step 3: Write the failing spike test**

`plugins/subagent-meter/hooks/register.test.ts`:

```ts
import { describe, expect, test } from 'claude-code/testing'

const turn = (over: Record<string, unknown> = {}) => ({
  answer: '',
  durationMs: 1,
  isAborted: false,
  turnId: 't1',
  reason: 'answer' as const,
  ...over,
})

describe('harness spike', () => {
  test('a subagent turn.complete reaches the plugin and its status line is observable', async ($, on) => {
    const lines: (string | undefined)[] = []
    on('ui.status', (_, e) => {
      lines.push(e.text)
    })
    on('turn.complete', () => ({ text: 'answered' }))
    on('agent.list', () => [{ id: 'a1', description: 'scan', type: 'Explore', status: 'running' }])

    const result = await $.turn.complete(
      turn({
        agentId: 'a1',
        usage: {
          model: 'm',
          input_tokens: 1,
          output_tokens: 2,
          cache_read_input_tokens: 3,
          cache_creation_input_tokens: 4,
        },
      }),
    )

    expect(result).toEqual({ text: 'answered' })
    expect(lines).toEqual(['agent a1'])
  })
})
```

- [ ] **Step 4: Run it to verify it fails for the right reason**

Run: `claude plugin test plugins/subagent-meter`
Expected: the test FAILS on `expect(lines).toEqual(['agent a1'])` (the received array is empty), not on a type or load error. If it fails earlier (the kit rejects `$.turn.complete` input, `on('agent.list', ...)` or `on('ui.status', ...)` does not type or load), fix the test's shape against the declarations until the failure is the empty `lines`; each correction is a ledger ruling, and the corrected shapes are what Tasks 2 and 3 use.

- [ ] **Step 5: Write the minimal hook**

Replace `plugins/subagent-meter/hooks/register.ts` with:

```ts
import type { Register } from 'claude-code'

export const register: Register = on => {
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    $.ui.status(e.agentId === undefined ? 'main turn' : `agent ${e.agentId}`)
    return result
  })
}
```

- [ ] **Step 6: Run the test to verify it passes, then validate the plugin**

Run: `claude plugin test plugins/subagent-meter`
Expected: 1 test PASSES.

Run: `claude plugin validate plugins/subagent-meter`
Expected: `Validation passed` (a warning about missing author details is acceptable if the manifest is read without `author`; the manifest above has one). The hooks section lists `turn.complete` as hooked and `ui.status` as called.

Record in the ledger what the spike showed: that `$.turn.complete`, `on('ui.status')` and `on('agent.list')` work as written (or the corrected forms), and that spec item (b) is left to the live check.

- [ ] **Step 7: Integrate the plugin in the repo**

Write this script to `$SP/integrate.py` and run `python $SP/integrate.py` from the repo root:

```python
import json
from pathlib import Path


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


mp = Path(".claude-plugin/marketplace.json")
data = json.loads(mp.read_text(encoding="utf-8"))
meta = json.loads(Path("plugins/subagent-meter/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
assert all(p["name"] != "subagent-meter" for p in data["plugins"])
data["plugins"].append(
    {"name": "subagent-meter", "source": "./plugins/subagent-meter", "description": meta["description"]}
)
data["plugins"].sort(key=lambda p: p["name"])
write(mp, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

gi = Path(".gitignore")
text = gi.read_text(encoding="utf-8")
line = "plugins/*/.claude-plugin/types/"
if line not in text:
    write(gi, text.rstrip("\n") + "\n" + line + "\n")

spec = Path("docs/superpowers/specs/2026-10-04-subagent-meter-design.md")
s = spec.read_text(encoding="utf-8")
old = "- Every update is a read, `addTurn`, then a write with `ifVersion`; if the write reports it lost the race, it re-reads and retries (at most 5 times). Concurrent subagent turns therefore never lose tokens."
new = "- Every update goes through the engine's `update($, atom, fn)`, which reads, applies the pure `addTurn`, writes with `ifVersion` and retries on a miss, so concurrent subagent turns never lose tokens. The agent type is looked up before the update (only for an id not yet in state), because the function passed to `update` must be pure."
assert old in s
s = s.replace(old, new, 1)
old = "- `formatLine(summary) -> string`: exactly the line above."
new = old + "\n- `statusLine(stats) -> string | undefined`: `summarize` then `formatLine`, `undefined` when no agent has been seen; the hooks call this one function."
assert old in s
s = s.replace(old, new, 1)
write(spec, s)
print("ok")
```

Expected output: `ok`. Check that the marketplace file's key order and indentation still match the existing style: run `git diff .claude-plugin/marketplace.json` and confirm the diff is only the new entry (if the whole file reformatted, restore it with `git checkout .claude-plugin/marketplace.json` and insert the entry by hand in the same two-space style).

- [ ] **Step 8: Regenerate the catalog and run the repo checks**

```bash
python scripts/build_catalog.py
python -m unittest discover -s tests
python scripts/validate.py
git status --short
```

Expected: `Catalog and llms.txt updated`; all tests PASS; `OK: all plugins valid`; `git status` lists only this task's files (no `plugins/subagent-meter/.claude-plugin/types/` directory; if the engine wrote one during Steps 4 and 6 it is ignored by `.gitignore` and does not appear). The README catalog now shows `subagent-meter` under Mods.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat: scaffold subagent-meter and prove the mod test kit

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: The pure logic

**Files:**
- Create: `plugins/subagent-meter/hooks/meter.ts`, `plugins/subagent-meter/hooks/meter.test.ts`

**Interfaces:**
- Consumes: `MeterStats` from `types/index.d.ts` (Task 1).
- Produces (used by Task 3): `Usage` (all four counts optional numbers), `Turn = { agentId?: string; type?: string; usage?: Usage }`, `Summary = { spawns: number; outputShare: number; allShare: number; topType: string }`, `emptyStats(): MeterStats`, `tokensOf(usage: Usage): { output: number; all: number }`, `addTurn(stats: MeterStats, turn: Turn): MeterStats`, `summarize(stats: MeterStats): Summary | undefined`, `formatLine(summary: Summary): string`, `statusLine(stats: MeterStats): string | undefined`.

- [ ] **Step 1: Write the failing tests**

`plugins/subagent-meter/hooks/meter.test.ts`:

```ts
import { describe, expect, test } from 'claude-code/testing'

import type { MeterStats } from '../types'
import { addTurn, emptyStats, formatLine, statusLine, summarize, tokensOf } from './meter'

const usage = (input: number, output: number, read: number, write: number) => ({
  input_tokens: input,
  output_tokens: output,
  cache_read_input_tokens: read,
  cache_creation_input_tokens: write,
})

const SESSION: MeterStats = {
  main: { output: 880, all: 2100 },
  agents: {
    a1: { type: 'Explore', output: 60, all: 1500 },
    a2: { type: 'Explore', output: 60, all: 1000 },
  },
}

describe('tokensOf', () => {
  test('output is output_tokens; all is the four counts added', () => {
    expect(tokensOf(usage(1, 2, 3, 4))).toEqual({ output: 2, all: 10 })
  })

  test('a missing count is 0', () => {
    expect(tokensOf({ output_tokens: 5 })).toEqual({ output: 5, all: 5 })
  })

  test('negative and non-finite counts are 0', () => {
    expect(
      tokensOf({
        input_tokens: -3,
        output_tokens: Number.NaN,
        cache_read_input_tokens: Number.POSITIVE_INFINITY,
        cache_creation_input_tokens: 7,
      }),
    ).toEqual({ output: 0, all: 7 })
  })
})

describe('addTurn', () => {
  test('a main-thread turn adds to main', () => {
    const next = addTurn(emptyStats(), { usage: usage(1, 2, 3, 4) })
    expect(next.main).toEqual({ output: 2, all: 10 })
    expect(next.agents).toEqual({})
  })

  test('an agent turn adds to that agent and records its type', () => {
    const next = addTurn(emptyStats(), { agentId: 'a1', type: 'Explore', usage: usage(1, 2, 3, 4) })
    expect(next.agents).toEqual({ a1: { type: 'Explore', output: 2, all: 10 } })
    expect(next.main).toEqual({ output: 0, all: 0 })
  })

  test('repeated turns of one agent add up and keep the first type', () => {
    const first = addTurn(emptyStats(), { agentId: 'a1', type: 'Explore', usage: usage(1, 2, 3, 4) })
    const second = addTurn(first, { agentId: 'a1', type: 'Plan', usage: usage(10, 20, 30, 40) })
    expect(second.agents.a1).toEqual({ type: 'Explore', output: 22, all: 110 })
  })

  test('an agent with no type is unknown', () => {
    const next = addTurn(emptyStats(), { agentId: 'a1', usage: usage(0, 1, 0, 0) })
    expect(next.agents.a1.type).toBe('unknown')
  })

  test('a turn without usage returns the same stats', () => {
    const stats = emptyStats()
    expect(addTurn(stats, { agentId: 'a1', type: 'Explore' })).toBe(stats)
  })

  test('an agent turn with zero tokens still counts as an agent', () => {
    const next = addTurn(emptyStats(), { agentId: 'a1', type: 'Explore', usage: usage(0, 0, 0, 0) })
    expect(Object.keys(next.agents)).toEqual(['a1'])
  })

  test('it does not change its input', () => {
    const stats = emptyStats()
    addTurn(stats, { agentId: 'a1', type: 'Explore', usage: usage(1, 2, 3, 4) })
    addTurn(stats, { usage: usage(1, 2, 3, 4) })
    expect(stats).toEqual(emptyStats())
  })
})

describe('summarize', () => {
  test('no agent seen is undefined', () => {
    expect(summarize(emptyStats())).toBeUndefined()
    expect(summarize(addTurn(emptyStats(), { usage: usage(1, 2, 3, 4) }))).toBeUndefined()
  })

  test('shares are agent-side tokens over main plus agent-side', () => {
    expect(summarize(SESSION)).toEqual({
      spawns: 2,
      outputShare: 120 / 1000,
      allShare: 2500 / 4600,
      topType: 'Explore',
    })
  })

  test('the top type is the one with the most all tokens, summed over its agents', () => {
    const stats: MeterStats = {
      main: { output: 0, all: 0 },
      agents: {
        a1: { type: 'a', output: 1, all: 60 },
        a2: { type: 'a', output: 1, all: 60 },
        b1: { type: 'b', output: 1, all: 100 },
      },
    }
    expect(summarize(stats)?.topType).toBe('a')
  })

  test('a tie goes to the name that sorts first', () => {
    const stats: MeterStats = {
      main: { output: 0, all: 0 },
      agents: {
        y: { type: 'b', output: 1, all: 100 },
        x: { type: 'a', output: 1, all: 100 },
      },
    }
    expect(summarize(stats)?.topType).toBe('a')
  })

  test('a zero total gives shares of 0, not NaN', () => {
    const stats: MeterStats = {
      main: { output: 0, all: 0 },
      agents: { a1: { type: 'x', output: 0, all: 0 } },
    }
    expect(summarize(stats)).toEqual({ spawns: 1, outputShare: 0, allShare: 0, topType: 'x' })
  })
})

describe('formatLine', () => {
  test('the line, with whole percents', () => {
    expect(formatLine({ spawns: 14, outputShare: 0.12, allShare: 0.54, topType: 'Explore' })).toBe(
      'subagents 14x · 12% of output · 54% of all tokens · top Explore',
    )
  })

  test('a share above 0 and below 1 percent is <1%; an exact 0 is 0%', () => {
    expect(formatLine({ spawns: 1, outputShare: 0.004, allShare: 0, topType: 'Explore' })).toBe(
      'subagents 1x · <1% of output · 0% of all tokens · top Explore',
    )
  })

  test('all of it is 100%', () => {
    expect(formatLine({ spawns: 3, outputShare: 1, allShare: 1, topType: 'Plan' })).toBe(
      'subagents 3x · 100% of output · 100% of all tokens · top Plan',
    )
  })

  test('a long type name is cut at 16 characters', () => {
    expect(formatLine({ spawns: 1, outputShare: 0.5, allShare: 0.5, topType: 'general-purpose-extra-long' })).toBe(
      'subagents 1x · 50% of output · 50% of all tokens · top general-purpose-',
    )
  })
})

describe('statusLine', () => {
  test('the session in the spec reads as the spec says', () => {
    expect(statusLine(SESSION)).toBe('subagents 2x · 12% of output · 54% of all tokens · top Explore')
  })

  test('no agents is undefined, so the line is removed', () => {
    expect(statusLine(emptyStats())).toBeUndefined()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `claude plugin test plugins/subagent-meter`
Expected: `meter.test.ts` fails to load or every test FAILS because `./meter` does not exist; `register.test.ts` still passes.

- [ ] **Step 3: Write the implementation**

`plugins/subagent-meter/hooks/meter.ts`:

```ts
import type { MeterStats } from '../types'

export type Usage = {
  input_tokens?: number
  output_tokens?: number
  cache_read_input_tokens?: number
  cache_creation_input_tokens?: number
}

export type Turn = { agentId?: string; type?: string; usage?: Usage }

export type Summary = {
  spawns: number
  outputShare: number
  allShare: number
  topType: string
}

const MAX_TYPE_LENGTH = 16

const count = (n: unknown): number =>
  typeof n === 'number' && Number.isFinite(n) && n > 0 ? n : 0

const share = (part: number, whole: number): number => (whole > 0 ? part / whole : 0)

const compare = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0)

const percent = (ratio: number): string => {
  const value = ratio * 100
  return value > 0 && value < 1 ? '<1%' : `${Math.round(value)}%`
}

export const emptyStats = (): MeterStats => ({ main: { output: 0, all: 0 }, agents: {} })

export const tokensOf = (usage: Usage): { output: number; all: number } => {
  const output = count(usage.output_tokens)
  const all =
    count(usage.input_tokens) +
    count(usage.cache_read_input_tokens) +
    count(usage.cache_creation_input_tokens) +
    output
  return { output, all }
}

export const addTurn = (stats: MeterStats, turn: Turn): MeterStats => {
  if (turn.usage === undefined) {
    return stats
  }
  const { output, all } = tokensOf(turn.usage)
  if (turn.agentId === undefined) {
    return {
      ...stats,
      main: { output: stats.main.output + output, all: stats.main.all + all },
    }
  }
  const held = stats.agents[turn.agentId] ?? { type: turn.type ?? 'unknown', output: 0, all: 0 }
  return {
    ...stats,
    agents: {
      ...stats.agents,
      [turn.agentId]: { type: held.type, output: held.output + output, all: held.all + all },
    },
  }
}

export const summarize = (stats: MeterStats): Summary | undefined => {
  const agents = Object.values(stats.agents)
  if (agents.length === 0) {
    return undefined
  }
  const sum = agents.reduce(
    (total, agent) => ({ output: total.output + agent.output, all: total.all + agent.all }),
    { output: 0, all: 0 },
  )
  const perType = new Map<string, number>()
  for (const agent of agents) {
    perType.set(agent.type, (perType.get(agent.type) ?? 0) + agent.all)
  }
  const [topType] = [...perType.entries()].sort(
    (a, b) => b[1] - a[1] || compare(a[0], b[0]),
  )[0]
  return {
    spawns: agents.length,
    outputShare: share(sum.output, sum.output + stats.main.output),
    allShare: share(sum.all, sum.all + stats.main.all),
    topType,
  }
}

export const formatLine = (summary: Summary): string =>
  `subagents ${summary.spawns}x · ${percent(summary.outputShare)} of output · ` +
  `${percent(summary.allShare)} of all tokens · top ${summary.topType.slice(0, MAX_TYPE_LENGTH)}`

export const statusLine = (stats: MeterStats): string | undefined => {
  const summary = summarize(stats)
  return summary === undefined ? undefined : formatLine(summary)
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `claude plugin test plugins/subagent-meter`
Expected: all `meter.test.ts` tests PASS and the spike test still passes. If a test fails because of floating-point (`120 / 1000` versus a computed share), fix the implementation to compute the share the same way the test does, not the test.

- [ ] **Step 5: Validate and commit**

```bash
claude plugin validate plugins/subagent-meter
python -m unittest discover -s tests 2>&1 | tail -3
python scripts/validate.py
git add -A
git commit -m "$(cat <<'EOF'
feat: subagent-meter token counting, shares and status line text

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

Expected: validation passes; the repo suite and `validate.py` stay green.

---

### Task 3: The hooks

**Files:**
- Modify: `plugins/subagent-meter/hooks/register.ts`, `plugins/subagent-meter/hooks/register.test.ts`

**Interfaces:**
- Consumes: `emptyStats`, `addTurn`, `statusLine` from `./meter` (Task 2); `MeterStats` (Task 1); the harness shapes confirmed in Task 1 Step 4 (if Task 1 corrected any, use the corrected forms below).
- Produces: the shipped module `register`.

- [ ] **Step 1: Replace the spike with the real tests**

Overwrite `plugins/subagent-meter/hooks/register.test.ts`:

```ts
import type { On } from 'claude-code'
import { describe, expect, test } from 'claude-code/testing'

const turn = (over: Record<string, unknown> = {}) => ({
  answer: '',
  durationMs: 1,
  isAborted: false,
  turnId: 't1',
  reason: 'answer' as const,
  ...over,
})

const usage = (input: number, output: number, read: number, write: number) => ({
  model: 'm',
  input_tokens: input,
  output_tokens: output,
  cache_read_input_tokens: read,
  cache_creation_input_tokens: write,
})

const MAIN = usage(1000, 880, 200, 20) // output 880, all 2100
const A1 = usage(500, 60, 900, 40) // output 60, all 1500
const A2 = usage(300, 60, 600, 40) // output 60, all 1000

const EXPLORE = [
  { id: 'a1', description: 'scan', type: 'Explore', status: 'running' },
  { id: 'a2', description: 'scan', type: 'Explore', status: 'running' },
]

const LINE = 'subagents 2x · 12% of output · 54% of all tokens · top Explore'

// The engine's own answers beneath the plugin, and a recorder for the status line.
const beneath = (on: On, agents: unknown = EXPLORE) => {
  const lines: (string | undefined)[] = []
  on('ui.status', (_, e) => {
    lines.push(e.text)
  })
  on('turn.complete', () => ({ text: 'answered' }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.end', (_, e) => ({ sessionId: e.sessionId }))
  on('agent.list', () => (typeof agents === 'function' ? agents() : agents) as never)
  return {
    lines,
    shown: () => lines.filter((line): line is string => line !== undefined),
    last: () => lines[lines.length - 1],
  }
}

const END = { reason: 'clear', sessionId: 's1', resume: { id: 's1' } } as const
const START = { cwd: '/', surface: null, isInteractive: true } as const

describe('subagent-meter hooks', () => {
  test('a session with only main-thread turns shows no line', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ usage: MAIN }))
    expect(seen.shown()).toEqual([])
  })

  test('main and subagent turns produce the line', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ usage: MAIN }))
    await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    await $.turn.complete(turn({ agentId: 'a2', usage: A2 }))
    expect(seen.last()).toBe(LINE)
  })

  test('the turn passes through unchanged', async ($, on) => {
    beneath(on)
    const result = await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    expect(result).toEqual({ text: 'answered' })
  })

  test('a turn without usage adds nothing and shows nothing', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ agentId: 'a1', reason: 'aborted', isAborted: true }))
    expect(seen.shown()).toEqual([])
  })

  test('an agent with zero tokens still counts as a spawn', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ agentId: 'a1', usage: usage(0, 0, 0, 0) }))
    expect(seen.last()).toBe('subagents 1x · 0% of output · 0% of all tokens · top Explore')
  })

  test('a failing agent lookup still counts the turn, as unknown, and does not break it', async ($, on) => {
    const seen = beneath(on, () => {
      throw new Error('no list')
    })
    const result = await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    expect(result).toEqual({ text: 'answered' })
    expect(seen.last()).toMatch(/top unknown$/)
  })

  test('an agent that is not listed is unknown', async ($, on) => {
    const seen = beneath(on, [])
    await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    expect(seen.last()).toMatch(/top unknown$/)
  })

  test('two turns finishing at the same moment are both counted', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ usage: MAIN }))
    await Promise.all([
      $.turn.complete(turn({ agentId: 'a1', usage: A1 })),
      $.turn.complete(turn({ agentId: 'a2', usage: A2 })),
    ])
    expect(seen.last()).toBe(LINE)
  })

  test('session.end with clear removes the line and resets the counts', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    await $.session.end(END)
    expect(seen.last()).toBeUndefined()
    await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    expect(seen.last()).toMatch(/^subagents 1x /)
  })

  test('another session.end reason leaves the counts alone', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    const before = seen.lines.length
    await $.session.end({ ...END, reason: 'other' })
    expect(seen.lines.length).toBe(before)
  })

  test('session.start redraws the line from saved state', async ($, on) => {
    const seen = beneath(on)
    await $.turn.complete(turn({ usage: MAIN }))
    await $.turn.complete(turn({ agentId: 'a1', usage: A1 }))
    await $.turn.complete(turn({ agentId: 'a2', usage: A2 }))
    await $.session.start(START)
    expect(seen.last()).toBe(LINE)
  })

  test('session.start with nothing counted draws no line', async ($, on) => {
    const seen = beneath(on)
    await $.session.start(START)
    expect(seen.shown()).toEqual([])
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `claude plugin test plugins/subagent-meter`
Expected: the new `register.test.ts` tests FAIL because the spike hook only draws `main turn` / `agent a1`, and there is no `session.start` or `session.end` hook; the `meter.test.ts` tests still pass. If a test fails on a harness shape instead (the `session.end` `reason: 'other'` is not a valid reason, an `on('session.start', ...)` answer must carry other fields, `agents as never` does not typecheck), correct the test's shape against the declarations first, ledger the correction, and rerun until the failures are about behavior.

- [ ] **Step 3: Write the hooks**

Overwrite `plugins/subagent-meter/hooks/register.ts`:

```ts
import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

import { addTurn, emptyStats, statusLine } from './meter'

const stats = atom({ plugin: 'subagent-meter', key: 'stats' } as const, emptyStats())

export const register: Register = on => {
  on('turn.complete', async ($, e, next) => {
    const result = await next(e)

    try {
      const { usage, agentId } = e
      if (usage !== undefined) {
        let type: string | undefined
        if (agentId !== undefined && (await read($, stats)).agents[agentId] === undefined) {
          try {
            type = (await $.agent.list()).find(agent => agent.id === agentId)?.type
          } catch {
            type = undefined
          }
        }
        await update($, stats, held => addTurn(held, { agentId, type, usage }))
        $.ui.status(statusLine(await read($, stats)))
      }
    } catch {
      // The meter only watches; a failure here must never reach the turn.
    }

    return result
  })

  on('session.start', async ($, e, next) => {
    const result = await next(e)

    try {
      $.ui.status(statusLine(await read($, stats)))
    } catch {
      // Same rule: never break the session.
    }

    return result
  })

  on('session.end', { reason: 'clear' }, async ($, e, next) => {
    try {
      await update($, stats, () => emptyStats())
      $.ui.status(undefined)
    } catch {
      // Same rule: never break the session.
    }

    return next(e)
  })
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `claude plugin test plugins/subagent-meter`
Expected: every test in `meter.test.ts` and `register.test.ts` PASSES. If the concurrent-turns test fails (a lost update, `2x` shows `1x`), do not loosen the test: the `update` call is the engine's safe write, so check that the type lookup happens before it and that the function passed to `update` is the pure `addTurn` call, then fix the code.

- [ ] **Step 5: Validate and commit**

```bash
claude plugin validate plugins/subagent-meter
python -m unittest discover -s tests 2>&1 | tail -3
python scripts/validate.py
git add -A
git commit -m "$(cat <<'EOF'
feat: subagent-meter hooks draw the live status line

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

Expected: `claude plugin validate` lists `turn.complete`, `session.start` and `session.end` as hooked, `ui.status` and `agent.list` as called, and the state key `subagent-meter` / `stats` as read and written; the repo checks stay green.

---

### Task 4: README, changelog and final checks

**Files:**
- Modify: `plugins/subagent-meter/README.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: the shipped behavior from Tasks 2 and 3.
- Produces: the user-facing documentation and the live-check recipe.

- [ ] **Step 1: Write the README**

Overwrite `plugins/subagent-meter/README.md`:

````markdown
# subagent-meter: a Claude Code mod by Naren

> A live status line showing how much of your session's tokens go to subagents, and which agent type uses the most.

Part of [Naren's Claude Toolkit](https://github.com/NarenDawar/narens-claude-toolkit).

## What it shows

One line under the prompt, refreshed after every turn once a subagent has run:

```text
subagents 14x · 12% of output · 54% of all tokens · top Explore
```

- **`14x`**: how many subagents (and in-process teammates) have finished a turn this session.
- **`12% of output`**: the share of output tokens that subagents produced, out of main thread plus subagents.
- **`54% of all tokens`**: the same share counting every token processed (fresh input, cache reads, cache writes and output).
- **`top Explore`**: the agent type that used the most tokens.

Read the two shares together. When "all tokens" is far above "output", the subagents are mostly re-reading context, not producing work: that gap is the context tax. The line disappears when no subagent has run, and resets on `/clear`.

## What it does not do

It is tokens only: no prices, no history, and it never reads old transcripts. For cost after the fact, per agent type, with suggestions for cheaper models, use the [`subagent-tax-auditor`](../subagent-tax-auditor/README.md) skill. The mod only watches: it never changes, delays or blocks a turn.

## Try it

This is a mod, so it loads from a folder rather than from the skills directory:

```text
claude --plugin-dir plugins/subagent-meter
```

Then ask Claude to run a few subagents (for example "use three Explore agents to look at three folders") and watch the line appear. The counts live in session state, so they survive a reload of the mod.

Marketplace install:

```text
/plugin marketplace add NarenDawar/narens-claude-toolkit
/plugin install subagent-meter@narens-claude-toolkit
```

## Tests

The logic is unit-tested and the hooks are tested with the mod test kit:

```text
claude plugin test plugins/subagent-meter
claude plugin validate plugins/subagent-meter
```

These run locally. The repository's CI runs on a runner without the Claude CLI, so it checks the manifest and the module path but does not run these tests yet.

## Known limits

- It measures the current session only and does not persist across sessions.
- An agent's type is looked up the first time the agent is seen; if the engine does not list it yet, it counts as `unknown`.
- It stores a small record per agent (about 100 bytes); there is no cap, which only matters for sessions with thousands of agents.

---

Made by [Naren](https://github.com/NarenDawar). If this helped, star the repo.
````

- [ ] **Step 2: Add the changelog entry**

In `CHANGELOG.md`, under `## [Unreleased]` / `### Added`, add as the first bullet:

```
- `subagent-meter` mod: a live status line showing how much of your session's tokens go to subagents (a share of output tokens and a share of all tokens, side by side) and which agent type uses the most. Tokens only, session scope, never changes a turn. The toolkit's first mod.
```

- [ ] **Step 3: Run the full set of checks**

```bash
python scripts/build_catalog.py --check && echo catalog-current
python -m unittest discover -s tests 2>&1 | tail -3
python scripts/validate.py
claude plugin test plugins/subagent-meter
claude plugin validate plugins/subagent-meter
git diff --stat main -- docs/superpowers | tail -4
git status --short | wc -l
```

Expected: `catalog-current`; all repo tests PASS; `OK: all plugins valid`; every mod test PASSES; plugin validation passes; the `docs/superpowers` diff lists only the new spec, this plan and the spec edits from Task 1 (no older plan or spec); a clean tree after the commit below.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
docs: subagent-meter README and changelog entry

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

## Handoff after the merge (not tasks)

1. Merge `subagent-meter` into `main` locally (the finishing step). Pushing is a separate confirmed step.
2. **Live check, yours:** from the repo root run `claude --plugin-dir plugins/subagent-meter`, ask Claude to run a few subagents, and confirm the line appears, the type names are real (this is the open question (b): if every type reads `unknown`, tell me and we will look at what `$.agent.list()` returns for a finished agent), and `/clear` removes it.
3. Optional follow-ups the spec left out: a per-type table on demand, a nudge that points to the auditor, and a CI job that runs `claude plugin test`.

## Self-review notes

- **Spec coverage:** counting rules and line format (Task 2 tests and `meter.ts`); lifetime, redraw and reset (Task 3 hooks and tests); state through `atom`/`update` (Task 3); manifest, `hooks.json`, contract (Task 1); catalog, `.gitignore`, marketplace entry, changelog, README (Tasks 1 and 4); spec items (a) (Task 1 spike) and (b) (live check, in the handoff); out-of-scope items are Global Constraints.
- **Spec edits made in Task 1:** the concurrency statement (engine `update` instead of a hand-written retry) and `statusLine` added to the pure-logic list.
- **Type consistency:** `MeterStats`, `Usage`, `Turn`, `Summary` and the six exported functions have the same names and shapes in the contract, `meter.ts`, both test files and `register.ts`.
- **Known unknowns the executor settles with the declarations and records as rulings:** the exact input shapes the test kit accepts for `$.turn.complete`, `$.session.start` and `$.session.end`, and whether a throwing `agent.list` hook rejects the call or is skipped (the code is correct either way).
