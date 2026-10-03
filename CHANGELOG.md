# Changelog

All notable changes are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `subagent-tax-auditor` skill: reads your local session transcripts, shows which subagent types used up your quota (per type and model, with fixed context per spawn), recommends cheaper models, edits custom agents' `model` after confirmation with a backup and undo, and compares usage before and after.
- `rule-promoter` skill: turns the enforceable rules in CLAUDE.md into hooks (protected paths, blocked commands, banned content, must-pass-before-stopping), proves each rule blocks a violation, and installs them into `.claude/settings.json` after confirmation.

### Fixed
- `rule-promoter` 0.1.1: a deny message names the matched path or command; rules with a non-boolean `enabled`, globs that could never match (`[ab]`, `{a,b}`, leading `./` or `/`) or a `timeout_seconds` above 280 are refused instead of silently misbehaving; very deeply nested tool input is still checked; the settings helper keeps Windows launcher paths intact, keeps file permissions, writes through a symlinked `settings.json`, and reports a write failure as a clean error; the force-push example also catches `-fu` and `+main`.

## [0.1.2] - 2026-10-01

### Fixed
- `decision-journal` 0.1.2: `--confidence 1` explains it was read as 100%; `stats --tag` matches entries logged by 0.1.0 (tags are casefolded when compared); the OS error names the file that actually failed; an estimate given `--confidence` reports the real mistake; a missing subcommand lists the commands; `grade`'s `result` line is documented as success-only; `grade`'s result line prints whole numbers from older logs as `3`, not `3.0`.

## [0.1.1] - 2026-10-01

### Fixed
- `comprehension-check` 0.1.1: grades only the current question when you answer ahead, gives a summary and stops when you say stop, drops a question your own fix already answered, re-asks flagged topics on a retake, scales the question count for medium changes; README example, line range and slash form corrected.
- `decision-journal` 0.1.1: unreadable or unwritable logs give a clean error, concurrent sessions can no longer lose entries (lock file), duplicate ids are reported by line, `70%` and `0.7` are accepted as confidence, `grade` prints a computed result line, tiny or odd numbers are handled, small estimate slices carry no verdict, symlinked and drive-root paths work, README example now shows the real report.

## [0.1.0] - 2026-10-01

### Added
- Repo scaffolding: plugin marketplace, skill template, validator, catalog generator, CI.
- `comprehension-check` skill: quizzes you on the code Claude wrote this session and flags the parts you could not maintain.
- `decision-journal` skill: log predictions about dev decisions, grade them later, and see where you are overconfident (JSONL log plus a standard-library calibration script).
