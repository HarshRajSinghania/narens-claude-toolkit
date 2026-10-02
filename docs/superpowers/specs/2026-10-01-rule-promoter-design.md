# rule-promoter: Skill Design

Date: 2026-10-01

## Goal

A Claude Code skill that turns the enforceable rules in a project's `CLAUDE.md` into hooks, and proves each hook blocks a violation. Existing tools only score compliance; this one fixes the rules. The model reads the rules and classifies them; a small tested engine enforces them.

Audience: Claude Code users whose `CLAUDE.md` rules get ignored ("never edit migrations", "no force push", "run the tests before you finish").
Success: the user ends with hooks whose self-test passes, an installed `.claude/settings.json` entry (after explicit confirmation), a real Claude Code session that was actually blocked from breaking a rule, and a plain list of the rules that could not be enforced and why.

## Decisions (agreed)

- **Name:** `rule-promoter` (plugin and skill). Free and MIT like the rest of the repo; the pricing idea in the original note is not part of this work.
- **Scope of v1:** classify the rules, write a hook for every mechanically checkable one, prove each blocks a violation. No empirical testing of which rules Claude breaks (hooks are cheap and harmless when a rule is already followed).
- **Install:** hook files in `.claude/hooks/`, rules in `.claude/rules.json`, entries in the project's `.claude/settings.json`. The skill shows the exact settings diff and writes it only after the user says yes.
- **Architecture:** one generic stdlib engine, `rule_hook.py`, plus a `rules.json` of typed rules. Not one script per rule, and not free-form generated hook code.
- **Out of scope:** measuring which rules Claude breaks, user-level or local settings, `PostToolUse`, MCP tool rules, prompt and agent hooks, auto-syncing when `CLAUDE.md` changes (re-run the skill), rule versioning.

## Hook facts the design relies on (from the current Claude Code docs; payload shapes are re-verified by capture at implementation time)

- Settings: `hooks.<Event>[] = {matcher, hooks:[{type:"command", command, args?, timeout}]}`. Project hooks live in `.claude/settings.json`; `${CLAUDE_PROJECT_DIR}` is available; exec form (`command` plus `args`) avoids quoting problems.
- `PreToolUse` receives JSON on stdin with `hook_event_name`, `cwd`, `tool_name`, `tool_input`. It blocks with exit code 2 (stderr goes to Claude) or by printing `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":...}}` and exiting 0. A timed-out `PreToolUse` hook does not block.
- `Stop` receives `stop_hook_active`; it blocks by printing `{"decision":"block","reason":...}`. When `stop_hook_active` is true the hook must allow, to avoid loops.
- A non-zero exit other than 2 is a non-blocking error shown to the user.
- Hooks run with the user's full permissions and are not a security boundary.

## Flow (what the skill does when invoked)

1. **Read.** Find `CLAUDE.md`, `.claude/CLAUDE.md` and `CLAUDE.local.md` in the project and list candidate rules with their file and line.
2. **Classify.** For each rule, assign exactly one of: an engine rule type with concrete parameters; `taste` with a one-line reason; or `needs input` with the question to ask. A rule is enforceable only if it names concrete tools, paths, commands or text patterns, and a violation is detectable from a single tool call or from an end-of-turn command's exit status. The skill never invents a rule type outside the four below.
3. **Review.** Show a table: rule, type, pattern or command, one sample violation, one sample pass, and the false-positive risk. The user can drop or adjust rows. Every `stop_check` command is shown verbatim.
4. **Prove.** Write `rule_hook.py` and `rules.json`, then run `selftest`. Every rule's sample violation must block and its sample pass must allow. A rule whose proof fails is not installed.
5. **Install.** Pick a working Python launcher (try `python3`, `python`, `py -3` against `selftest`). Show the exact `settings.json` diff and write it only after confirmation.
6. **Verify end to end.** Run a headless Claude Code session in the project, ask it to break one promoted rule, and show that it was blocked. If a session cannot be run, say so and mark the install as verified only by `selftest`.
7. **Report.** List promoted rules, skipped rules with reasons, and how to disable (`"enabled": false`, or remove the `rule_hook.py` entries).

## Files

- `plugins/rule-promoter/skills/rule-promoter/SKILL.md`: the conversation (read, classify, review, prove, install, verify, report).
- `plugins/rule-promoter/skills/rule-promoter/scripts/rule_hook.py`: the engine, copied to `.claude/hooks/rule_hook.py` in the user's project.
- `plugins/rule-promoter/README.md`, marketplace and catalog entries, `CHANGELOG.md` entry.
- `tests/test_rule_hook.py` and captured payload fixtures under `tests/fixtures/rule_hook/`.

## rules.json

```json
{
  "version": 1,
  "rules": [
    {
      "id": "no-migration-edits",
      "enabled": true,
      "source": "CLAUDE.md:14",
      "text": "Never edit files in migrations/",
      "type": "protected_path",
      "globs": ["**/migrations/**"],
      "allow_globs": [],
      "message": "Migrations are generated. Create a new migration instead of editing one.",
      "proof": {
        "violation": {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "app/migrations/0001_initial.py"}},
        "pass": {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {"file_path": "app/models.py"}}
      }
    }
  ]
}
```

Fields on every rule: `id` (kebab-case, unique), `enabled` (default true), `source`, `text`, `type`, `message` (shown to Claude when blocked), `proof` with `violation` and `pass` payloads. Type-specific fields:

- `protected_path`: `globs`, optional `allow_globs`. Applies to Edit, Write, MultiEdit and NotebookEdit. Paths are made relative to the project directory, use forward slashes, and are case-insensitive on Windows. `**` matches any depth, `*` matches within one path segment.
- `blocked_command`: `patterns` (regular expressions), optional `except_patterns`. Applies to Bash. The command is split into segments on `&&`, `||`, `;`, `|` and newlines, and a rule fires if any segment matches a pattern and no except pattern.
- `banned_content`: `patterns`, optional `globs` (which files the rule covers). Applies to Edit, Write, MultiEdit and NotebookEdit. Only the new text being written is inspected (values under keys such as `content`, `file_content`, `new_string`, `new_content`, `new_source`, collected recursively), never the old text or what is already on disk.
- `stop_check`: `command` (run with a shell in the project directory), `timeout_seconds` (default 120), optional `when_changed_globs`. Applies to `Stop`. If `when_changed_globs` is set, the command runs only when `git status --porcelain` lists a changed path matching one of them (if git is unavailable, it always runs). A non-zero exit blocks the stop, with the last 20 lines of output (at most 2000 characters) in the reason. A timeout allows the stop and prints a warning, so a slow command cannot wedge the session.

## Engine (rule_hook.py)

Standard library only, Python 3.9+. Subcommands:

- `check`: reads the hook payload from stdin; `hook_event_name` selects `PreToolUse` or `Stop` handling. On a violation of a `PreToolUse` rule it prints the JSON `deny` decision with the reason `Rule <id>: <message> (from <source>)` and exits 0. On a `Stop` violation it prints `{"decision":"block","reason":...}` and exits 0; if `stop_hook_active` is true it allows. On allow it prints nothing and exits 0. The first violated rule wins and is the only one reported.
- `selftest [--rules PATH]`: runs every enabled rule's `proof.violation` (must block) and `proof.pass` (must allow) through the same code path as `check`, prints one line per rule, and exits 0 only if all pass; it also validates the rules file (known types, required fields, valid regular expressions and globs, unique ids).
- Project directory: `CLAUDE_PROJECT_DIR` if set, else the payload `cwd`, else the current directory. Rules are read from `<project>/.claude/rules.json`, overridable with `--rules` for tests.
- Failure behavior: an internal error, malformed JSON, or a missing or invalid rules file prints `[rule_hook] <reason>` on stderr and exits 1 (a non-blocking error), so a broken engine never blocks every tool call. A payload for a tool the rules do not cover is allowed silently.
- Speed: regular expressions are compiled once per run; `PreToolUse` handling makes no subprocess calls.

## settings.json entries

Written by the skill (never by the engine), merged into any existing file without touching unrelated content:

```json
{"hooks": {
  "PreToolUse": [{"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash",
                  "hooks": [{"type": "command", "command": "python3",
                             "args": ["${CLAUDE_PROJECT_DIR}/.claude/hooks/rule_hook.py", "check"], "timeout": 5}]}],
  "Stop": [{"hooks": [{"type": "command", "command": "python3",
                       "args": ["${CLAUDE_PROJECT_DIR}/.claude/hooks/rule_hook.py", "check"], "timeout": 300}]}]
}}
```

`command` is the launcher chosen in step 5. The skill's entries are identified by `rule_hook.py` in `args`, so re-running the skill replaces its own entries and leaves everything else alone. The `PreToolUse` entry exists only if there are `PreToolUse` rules, the `Stop` entry only if there are `stop_check` rules. If `settings.json` is not valid JSON the skill stops and says so; if it does not exist the skill creates it.

## Skill behavior rules (SKILL.md)

- Never write `settings.json`, `rules.json` or hook files before the user has reviewed the table; never write `settings.json` before showing the diff and getting a yes.
- Prefer narrow patterns and state the false-positive risk for each rule; when a rule could block legitimate work, add an `allow_globs` or `except_patterns` entry or ask.
- Do not promote a rule whose proof fails; say which proof failed.
- State plainly that hooks are guardrails and not a security boundary.
- Skipped rules are listed with the reason ("taste", "needs a judgment the hook cannot make", "no concrete pattern").
- Tone: brief and factual.

## Verification

- **Engine, test-first with `unittest`:** each rule type, compound commands and quoting, Windows and POSIX paths, `allow_globs`, banned content only in new text, `stop_check` pass, fail, timeout, `when_changed_globs`, the `stop_hook_active` loop guard, malformed payloads, an unknown tool, a missing or invalid rules file, `selftest` output and exit codes, and the fail-open behavior. Fixtures are real payloads captured from Claude Code (Bash, Write, Edit, MultiEdit, Stop), so field names are not guessed.
- **Classifier:** at least six hand-written, realistic `CLAUDE.md` files with expected labels (enforceable type, taste, needs input) written before running the skill; report the agreement rate honestly. No claim is made about public files that were not read.
- **Skill behavior, baseline and with-skill scenarios:** taste rules are skipped with a reason; a rule without a concrete pattern is not promoted; nothing is written before review and confirmation; a failing proof blocks installation; re-running the skill does not duplicate settings entries; existing unrelated hooks in `settings.json` survive.
- **End to end:** a real headless Claude Code session in a scratch project with the generated hooks installed, asked to break a rule, confirming that it was blocked; and the same task without the hooks, to show the difference.
- The repo checks pass: `validate.py`, `claude plugin validate`, the full test suite.

## Out of scope

See Decisions. Pushing to GitHub is a separate, explicit step.
