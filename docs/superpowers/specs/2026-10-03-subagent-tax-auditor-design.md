# subagent-tax-auditor: Skill Design

Date: 2026-10-03

## Goal

A Claude Code skill that shows which subagent types used up the user's quota and helps cut that cost. It parses the local session transcripts, splits usage between the main thread and each subagent type, explains the biggest spenders with the numbers behind each claim, proposes changes to the agents' `model` (and `effort`, where the field exists), applies them only after confirmation, and later measures whether the change helped.

Audience: Claude Code users who hit usage limits and suspect subagents.
Success: the user gets a per-type cost split that matches their real transcripts, a recommendation for each expensive type that cites measured numbers, an edit that changes only what was approved, and a before/after comparison that says plainly when there is too little data to conclude anything.

Gap: the cost-reporting tools found (ccusage, per its listing) report per model and per project, and Token Optimizer audits CLAUDE.md, memory, skills and MCP servers. No tool found attributes cost per subagent type and then edits the agents. Developers hand-roll transcript parsers for this. (Search-based, not exhaustive.)

## Decisions (agreed)

- **Name:** `subagent-tax-auditor` (plugin and skill). Free and MIT like the rest of the repo; no paid tier is assumed.
- **Trigger:** explicit only ("why is my quota disappearing", "which subagents cost the most", "audit my subagents", "make my agents cheaper"). It never runs or edits on its own.
- **Approach:** a standard-library Python parser does all measuring and arithmetic; Claude explains and decides what to propose; a second script edits agent frontmatter. Claude never does the arithmetic.
- **What "fix" means:** edit `model` (and `effort` if valid) in frontmatter of custom agents only. Built-in types (`general-purpose`, `Explore`, `Plan`, and so on) have no file; for those the skill reports the numbers and recommends setting `model` where the agent is spawned. It does not create override agents and does not write CLAUDE.md routing text (advice, not enforcement).
- **Re-measure:** compare real usage before and after the edit (per-spawn medians with the sample size). No controlled reruns in v1.
- **Out of scope for v1:** controlled A/B reruns, override agents for built-in types, a paid tier, a dashboard or charts, real-time monitoring, anything that reads or sends data off the machine, per-prompt cost attribution, predicting a subscription plan's quota (only a cost-equivalent proxy is shown).

## Transcript facts the design relies on (verified on a real install, Claude Code 2.1.284; re-verified by capture at implementation time)

- Transcripts live in `<projects dir>/<project-slug>/<session-id>.jsonl` (default `~/.claude/projects`). Each line is a JSON object with `type` (`user`, `assistant`, `attachment`) and `sessionId`.
- Each subagent has its own file `<project-slug>/<session-id>/subagents/agent-<id>.jsonl` and a sidecar `agent-<id>.meta.json` with `agentType`, `model`, `description`, `toolUseId`, `spawnDepth`.
- Assistant lines carry `message.id`, `message.model` and `message.usage`: `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`, and `cache_creation.ephemeral_5m_input_tokens` / `ephemeral_1h_input_tokens`. A message id may appear on more than one line (streamed updates), so usage is counted once per id; the implementation confirms by capture whether duplicates occur and which line holds the final usage.
- `<synthetic>` models carry no usage and are ignored.
- Observed in one real session: 95 subagents of one type used about 2.6M cache-creation and 21M cache-read tokens against about 57K output tokens, which is the pattern the pitch describes.

If any of these shapes differ in a newer version, the parser skips what it cannot read, counts it, and says so in the report.

## Files

```
plugins/subagent-tax-auditor/
  .claude-plugin/plugin.json
  README.md
  skills/subagent-tax-auditor/
    SKILL.md
    rates.json
    scripts/audit.py
    scripts/agent_edit.py
tests/test_audit.py
tests/test_agent_edit.py
tests/fixtures/audit/        (structure-only transcripts, no real text)
```

## audit.py

Read-only. No network. Standard library only, Python 3.9+. Streams files line by line.

```
audit.py report  [--project PATH | --all] [--since YYYY-MM-DD] [--until YYYY-MM-DD]
                 [--projects-dir DIR] [--rates FILE] [--json] [--show-descriptions]
audit.py snapshot --out FILE [same selectors]       # saves the per-type numbers at a moment in time
audit.py compare  --snapshot FILE [same selectors]  # per-type usage per spawn before vs after
```

- **Projects dir:** `--projects-dir`, else `$CLAUDE_CONFIG_DIR/projects`, else `~/.claude/projects`. `--project PATH` maps a working directory to its slug using the same rule Claude Code uses; the default is the current directory's project; `--all` covers every project.
- **Attribution:** every counted assistant message belongs to "main" (the session file) or to a subagent type (a file under `subagents/`, typed by its meta file). A subagent with no readable meta file is typed `unknown`. Nested subagents count under their own type; `spawnDepth` is shown but does not change attribution.
- **Per row (main, then each type and model):** spawns, messages, tokens by kind (input, cache write, cache read, output), cost-equivalent, share of total cost, share of output tokens, and fixed context per spawn (median of the first message's cache-creation plus cache-read tokens across that type's spawns).
- **Cost-equivalent:** tokens by kind times the per-million rate for the model in `rates.json`. Cache writes use the 5-minute or 1-hour rate according to the usage breakdown. The report labels this a cost-equivalent proxy and says a subscription's quota is not measured in dollars. A model with no rate keeps its token counts, shows `no rate`, and is excluded from cost totals, with a count of how many tokens that is.
- **rates.json:** `{"as_of": "YYYY-MM-DD", "unit": "usd_per_million_tokens", "models": {"<model id or prefix>": {"input": n, "output": n, "cache_write_5m": n, "cache_write_1h": n, "cache_read": n}}}`. The shipped values are filled in from Anthropic's published pricing at implementation time and dated; the report warns when `as_of` is older than 90 days. `--rates` overrides the file.
- **Output:** a plain-text table sorted by cost, then totals, then a "data quality" footer (lines skipped as malformed, subagents without meta, models without a rate, date range covered, number of sessions read). `--json` prints the same data for the skill to read.
- **Privacy:** prompts, responses and file contents are never printed. Task descriptions appear only with `--show-descriptions`.
- **Errors:** an unreadable file, a non-JSON line or a line missing `usage` is skipped and counted. A missing projects dir is `error: ...` with exit 2. No transcripts found is a clear message and exit 0.

### snapshot and compare

`snapshot` writes JSON: the selectors used, a timestamp, the rates date, and per type and model the spawns, median fixed context per spawn, median total tokens per spawn and median cost-equivalent per spawn. `compare` re-reads the transcripts, takes only sessions that started after the snapshot's timestamp, and prints before and after side by side per type with the sample size of each. A type with fewer than 5 spawns on either side shows no verdict and says so (the same small-sample rule `decision-journal` uses). It never claims a saving it cannot show: when the model of a type did not change, it says the type is unchanged.

## agent_edit.py

Edits frontmatter of custom agent files only. Atomic writes, permission bits kept, symlinks written through, a clean `error:` line and exit 2 on any failure (patterns from `settings_merge.py`).

```
agent_edit.py list  [--agents-dir DIR ...]                   # custom agents found, with current model and effort
agent_edit.py plan  --agent NAME --model MODEL [--effort LEVEL] [--agents-dir DIR ...]
agent_edit.py apply --agent NAME --model MODEL [--effort LEVEL] [--agents-dir DIR ...] [--backup-dir DIR]
agent_edit.py undo  --agent NAME [--backup-dir DIR]
```

- **Where agents live:** the project's `.claude/agents/` and the user's `~/.claude/agents/` (project wins on a name clash, and both are listed). The skill passes explicit directories.
- **Frontmatter:** only the `model` and `effort` lines are changed or added, inside the leading `---` block. Everything else is untouched: other fields, comments, field order, line endings (LF or CRLF), a BOM, the body. A file with no frontmatter, an unterminated block, a duplicate key, or a multi-line `model` value is refused with a message; nothing is written.
- **Values:** `--model` accepts what Claude Code accepts for agents (an alias such as `sonnet`, `opus`, `haiku`, `inherit`, or a full model id). `--effort` is validated against the levels in the current docs. Before the skill proposes any `effort` change, it checks the current Claude Code docs that agent frontmatter supports an `effort` field; if it does not, only `model` is proposed and the report says why. This is a verification step in SKILL.md, not an assumption.
- **plan:** prints a unified diff against the raw file and changes nothing. **apply:** writes the change and saves the original file under the backup dir (default `.claude/agent-edit-backups/`, one timestamped copy per apply) and prints the path. **undo:** restores the most recent backup for that agent, refusing if the file changed since the apply (it never overwrites later edits silently).

## Skill flow (SKILL.md)

1. **Measure.** Run `audit.py report --json` for the project (offer `--all`). If there are no subagent transcripts, say so and stop.
2. **Explain.** Lead with the largest cost and the share of output it produced. Show the per-type table, the fixed-context-per-spawn figure, and the data-quality footer. State the proxy caveat once.
3. **Recommend,** by these rules, each citing the numbers it used:
   - high fixed context per spawn plus low output share: a cheaper `model` for that type;
   - many spawns of one type: spawn fewer, or batch the work, because each spawn pays the fixed context again;
   - a type with healthy output share: leave it alone, and say so;
   - built-in type: report only, with the "set `model` where it is spawned" advice;
   - too few spawns (under 5): no recommendation.
4. **Propose edits** only for custom agents: show the `agent_edit.py plan` diff and wait for an explicit yes. Never edit before that. Run `audit.py snapshot` before applying so the comparison has a baseline.
5. **Apply** and show the backup path and how to undo.
6. **Re-measure later.** When the user comes back, run `audit.py compare`, report the per-spawn before and after with sample sizes, and say plainly when the answer is "not enough data yet".

Rules: never print or paraphrase prompt content; never edit a file the user did not approve in this conversation; never claim a saving the comparison does not show; do the arithmetic only through the scripts; if the report and the user's expectation disagree, show the data-quality footer before drawing conclusions.

## Verification

- **Parser, test-first with `unittest`:** de-duplication by message id; main vs subagent attribution; missing meta file; `<synthetic>` ignored; unknown model; 5-minute vs 1-hour cache rates; date filters; nested subagents; malformed and truncated lines; non-UTF-8 and BOM; CRLF; empty projects dir; a missing projects dir; the median fixed-context calculation; the small-sample rule; compare when the model did not change; JSON output matches the text table.
- **Edit tool, test-first:** a model line changed in place; a model line added; `effort` added; CRLF and BOM kept; comments and field order kept; refused cases (no frontmatter, unterminated, duplicate key, multi-line value); backup and undo; undo refused after a later edit; symlink and permission bits (skipped where the OS cannot test them); a write failure is a clean error.
- **Fixtures:** a structure-only transcript tree derived from a real capture with all text replaced, so field names are not guessed.
- **Real-data check:** run the report on the author's own transcripts and confirm the split reproduces the "fixed context dominates" pattern; record the result honestly, including if it does not.
- **Scenario runs, baseline vs with-skill (Sonnet subagents):** "why is my quota disappearing", "which subagent should I make cheaper", "apply the recommendation", a project with only built-in agents (must report and refuse to edit), a project with too few spawns (must decline to recommend), a transcript tree with malformed lines (must surface the data-quality footer), and a prompt asking it to quote what the subagents were doing (must not print prompt content).
- **Cross-platform:** run the full suite on Windows and in a Linux container; CI runs on Linux.
- **Repo checks:** `python scripts/validate.py`, `python scripts/build_catalog.py --check`, `claude plugin validate`, and an install check from the marketplace.

## Out of scope / known limits (to state in the README)

- The cost figure is a proxy at published API rates, not a measure of subscription quota.
- Before/after compares different tasks, so it shows a trend with a sample size, not proof.
- Only transcripts still on disk are counted; deleted or expired sessions are invisible.
- Built-in agent types cannot be edited by this skill.
- Anthropic may add a built-in usage breakdown; the rates file and the parser will need updates when pricing or the transcript format changes.
