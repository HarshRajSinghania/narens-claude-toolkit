# rule-promoter: a Claude Code skill by Naren

> Turn the CLAUDE.md rules Claude ignores into hooks that actually enforce them.

Part of [Naren's Claude Toolkit](https://github.com/NarenDawar/narens-claude-toolkit).

CLAUDE.md rules are advice. Claude can rationalize past them, especially "never edit migrations" or "run the tests before you finish". A hook is enforcement. `rule-promoter` reads your CLAUDE.md, picks out the rules a hook can really enforce, writes them to a small rules file, proves each one blocks a violation, and installs the hooks once you say yes. Existing tools stop at a compliance score; this one fixes the rules.

## When it triggers

Only when you ask. Example phrasings:

- "Turn my CLAUDE.md rules into hooks."
- "Claude keeps editing the migrations folder. Make it stop."
- "Promote the rules in CLAUDE.md so they are enforced."

## Install

**Plugin marketplace (recommended)**

```text
/plugin marketplace add NarenDawar/narens-claude-toolkit
/plugin install rule-promoter@narens-claude-toolkit
```

**Manual**

Copy `plugins/rule-promoter/skills/rule-promoter` into `~/.claude/skills/`. It needs Python 3 (standard library only).

## What it enforces

| Rule type | Example CLAUDE.md rule | What the hook does |
| --- | --- | --- |
| Protected path | "Never edit anything under migrations/." | Blocks Edit and Write on matching files |
| Blocked command | "Never run `git push --force`." | Blocks matching Bash commands, including inside `a && b` |
| Banned content | "No `console.log(` in src/." | Blocks writes whose new text matches |
| Must-pass before stopping | "Run `npm test` before you finish." | Refuses to let Claude finish while the command fails |

Style and judgment rules ("prefer small functions") cannot be checked by a pattern, so they are listed as skipped, with the reason. Vague rules ("be careful with the database") get a question instead of a guess.

## Example

**You:** Turn the rules in my CLAUDE.md into hooks.

**Claude:** shows a table of each rule with its type, pattern, a sample violation, a sample pass and the false-positive risk, and lists the skipped taste rules. You adjust it and approve.

**Claude:** writes `.claude/hooks/rule_hook.py` and `.claude/rules.json`, runs the self-test (`PASS  no-migration-edits`), shows the exact `settings.json` diff, and writes it only after you say yes. Then it runs a real Claude Code session that tries to break a rule and shows the block:

```text
Rule no-migration-edits: Migrations are generated. Create a new migration instead. (from CLAUDE.md:4)
```

## How it works

- One small stdlib engine (`rule_hook.py`) enforces a `rules.json` of typed rules. Claude does the judgment (which rules are enforceable, which pattern); the engine does the enforcing, deterministically.
- Every rule carries a sample violation and a sample pass, and the self-test proves both before anything is installed.
- If the engine ever errors, it warns and lets the call through instead of blocking every tool call.
- Re-running the skill replaces only its own entries in `settings.json` and leaves your other hooks alone.

## Limits

- Hooks are guardrails, not a security boundary. A helper script or `bash -c` can get around a pattern.
- A `must-pass before stopping` check blocks the first stop attempt and tells Claude to fix the failure. If Claude cannot fix it, a loop guard lets the second attempt through, so a failing check can delay finishing but never wedge a session.
- A pattern that is too broad can block legitimate work (for example a `main` pattern also matches a branch named `main-menu`); the skill states the risk for each rule and adds exceptions where it matters.
- Path matching is best effort: case-insensitive on Windows and macOS, and symlinks, junctions and Windows short names are resolved, but unusual aliases may still slip through.
- `when_changed_globs` only sees uncommitted changes (renames count). If Claude commits before it stops, the check is skipped, so leave the globs out when that matters.
- `except_patterns` exempt the whole command segment: matching text anywhere in the command part lets it through. Text in a shell `#` comment, or in a heredoc that is not fed to a shell or interpreter (a commit message, say), is ignored by every pattern, so it can neither trigger a rule nor excuse a command. A heredoc fed to `bash`, `sh`, `python` and the like is still scanned, because that text runs.
- `banned_content` inspects the new text of each edit, so a banned string assembled across several edits is not caught.
- Claude can still edit `.claude/rules.json`, `.claude/hooks/` and `.claude/settings.json`. Once you are happy with the setup, you can add a protect rule for those paths; it also blocks re-running this skill until you disable it.
- If one rule in `rules.json` is invalid, the engine keeps enforcing the valid ones and warns about the bad one on every tool call.
- The hook entries use exec-form `command` plus `args`. If your Claude Code version does not run them (hooks never fire although the self-test passes), the skill can write the one-line shell form instead (`--shell-form`).
- A stop check's `timeout_seconds` is capped at 280, and all stop checks in one Stop event share a 280-second budget (the installed hook allows 300). When it runs out, the remaining checks are skipped with a warning and the stop is allowed.
- A pattern with a repeated group that itself repeats, such as `(a+)+`, is refused at load time because it can hang the hook. Other slow patterns are not detected, so keep patterns simple.
- It does not measure which rules Claude actually breaks, and it does not re-sync automatically when CLAUDE.md changes: run it again.

## Turning it off

Set `"enabled": false` on a rule in `.claude/rules.json`, or delete the `rule_hook.py` entries from `.claude/settings.json`.

---

Made by [Naren](https://github.com/NarenDawar). If this helped, star the repo.
