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
