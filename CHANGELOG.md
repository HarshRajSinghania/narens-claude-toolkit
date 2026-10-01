# Changelog

All notable changes are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [0.1.2] - 2026-10-01

### Fixed
- `decision-journal` 0.1.2: `--confidence 1` explains it was read as 100%; `stats --tag` matches entries logged by 0.1.0 (tags are casefolded when compared); the OS error names the file that actually failed; an estimate given `--confidence` reports the real mistake; a missing subcommand lists the commands; `grade`'s `result` line is documented as success-only; symlinked logs are written through the link (covered by a test that only runs where symlinks are allowed); `grade`'s result line prints whole numbers from older logs as `3`, not `3.0`.

## [0.1.1] - 2026-10-01

### Fixed
- `comprehension-check` 0.1.1: grades only the current question when you answer ahead, gives a summary and stops when you say stop, drops a question your own fix already answered, re-asks flagged topics on a retake, scales the question count for medium changes; README example, line range and slash form corrected.
- `decision-journal` 0.1.1: unreadable or unwritable logs give a clean error, concurrent sessions can no longer lose entries (lock file), duplicate ids are reported by line, `70%` and `0.7` are accepted as confidence, `grade` prints a computed result line, tiny or odd numbers are handled, small estimate slices carry no verdict, symlinked and drive-root paths work, README example now shows the real report.

## [0.1.0] - 2026-10-01

### Added
- Repo scaffolding: plugin marketplace, skill template, validator, catalog generator, CI.
- `comprehension-check` skill: quizzes you on the code Claude wrote this session and flags the parts you could not maintain.
- `decision-journal` skill: log predictions about dev decisions, grade them later, and see where you are overconfident (JSONL log plus a standard-library calibration script).
