# decision-journal: Skill Design

Date: 2026-10-01

## Goal

A Claude Code skill that records the user's predictions about dev and project decisions (for example "this refactor takes 2 hours", "this approach won't scale"), later grades them against what actually happened, and shows where the user is overconfident. It fills a gap: the only prediction journals found are for trading and prediction markets, none for development or project decisions.

Audience: developers working with Claude Code who want to calibrate their own estimates and judgment.
Success: after about 10 graded entries the user can see a pattern in plain language (for example "my time estimates run 1.6x low" or "my 90%-confident claims come true about 60% of the time"), and the numbers are always arithmetically correct.

## Decisions (agreed)

- **Name:** `decision-journal` (plugin and skill).
- **Trigger:** explicit only ("log a prediction", "I predict this takes 2 hours", "grade my predictions", "how calibrated am I?"). It never logs, grades or nags on its own.
- **Storage:** one global JSONL file, `~/.claude/decision-journal.jsonl`, shared across all projects. Private to the user, never inside a repo.
- **Approach:** JSONL log plus one standard-library Python script, `journal.py`, which does all writing and arithmetic deterministically. Claude does the conversation; the script does the math.
- **Out of scope for v1:** team or shared journals, reminders or notifications, auto-detecting predictions, charts or exports, logging Claude's own predictions.

## Data model

Two prediction types, scored differently:

- **claim** (yes/no), such as "this approach won't scale". Fields: `text`, `confidence` (integer 50-99, percent that the claim is true). Graded with `outcome` = yes or no.
- **estimate** (a number), such as "this refactor takes 2 hours". Fields: `text`, `unit` (free text such as `hours`), `estimate` (number greater than 0), optional `range_low` and `range_high` (the user's 80% range, `range_low <= estimate <= range_high`). Graded with `actual` (number greater than or equal to 0).

Every entry: `id` (integer, max existing id + 1, starting at 1), `created` (ISO date `YYYY-MM-DD`), `type`, `text`, `know_by` (optional ISO date), `tags` (list of lowercase strings), `project` (basename of the working directory at creation), `status` (`open` or `graded`), `graded` (ISO date), `outcome` or `actual`, and `note` (optional).

## journal.py

Standard library only; Python 3.9+. Lives at `plugins/decision-journal/skills/decision-journal/scripts/journal.py` so manual copy of the skill folder works. The log path is `~/.claude/decision-journal.jsonl`, overridable with the env var `DECISION_JOURNAL_PATH`. "Today" is the system date, overridable with `DECISION_JOURNAL_TODAY` (`YYYY-MM-DD`) so tests are deterministic. The directory is created if missing.

Subcommands:

- `add --type claim --text T --confidence N [--know-by D] [--tag a,b]`, or `add --type estimate --text T --unit U --estimate X [--range-low L --range-high H] [--know-by D] [--tag a,b]`. Prints the new entry as one JSON object.
- `list [--open | --due]`. Prints a JSON array. `--open` is all entries with status `open`. `--due` is open entries whose `know_by` is on or before today. With neither flag, all entries.
- `grade ID --outcome yes|no` (claims) or `grade ID --actual X` (estimates), with optional `--note T`. Prints the updated entry as JSON. Grading an already graded entry is rejected unless `--force` is given (used for corrections).
- `stats [--tag T]`. Prints a plain-text report (see Scoring). With `--tag`, only entries carrying that tag.

Exit codes: 0 success; 2 invalid input (message on stderr); 1 entry not found.

Validation: confidence outside 50-99 is rejected (below 50 means flip the claim; 100 is not a prediction); estimate must be greater than 0; if one of `--range-low` and `--range-high` is given, both are required, and `range_low <= estimate <= range_high`; `--outcome` on an estimate or `--actual` on a claim is rejected; dates must parse as ISO; tags are lowercased and trimmed.

Safety:
- All writes are atomic: write a temp file in the same directory, then `os.replace`.
- A malformed line (invalid JSON or missing required fields) is skipped with a warning on stderr when reading, and is preserved byte-for-byte when the file is rewritten. It is never dropped.
- Reads tolerate CRLF line endings and a UTF-8 BOM.
- Known limitation: two sessions writing at the same instant are last-writer-wins.

## Scoring (`stats`)

Only graded entries count.

- **Claims:** buckets 50-59, 60-69, 70-79, 80-89, 90-99. For each non-empty bucket: n, mean stated confidence, actual hit rate. Brier score is the mean of `(p - o)^2` where `p = confidence / 100` and `o` is 1 for yes and 0 for no.
- **Estimates:** the per-entry ratio is `actual / estimate`. Report the median ratio, phrased as "run Nx over" or "run Nx under" (a median of 1.0 reads "on target"). Range hit rate is the fraction of entries that have a range with `range_low <= actual <= range_high`; the user's stated range is 80%, so about 80% is calibrated.
- **Small samples:** if fewer than 5 graded entries exist overall, the report says "too few graded entries to conclude" and prints the raw counts only. Any bucket or tag slice with n below 5 is marked `(n<5)` and gets no interpretation.
- **Tags:** the report also prints the claim hit-rate-versus-confidence gap and the estimate median ratio per tag, again marking slices with n below 5.

## Skill behavior (SKILL.md)

Three flows, all started by the user:

- **Log.** Extract the text from what the user said. Ask only for what is missing: confidence for a claim; a point estimate and unit for an estimate. Offer the optional 80% range, know-by date and tag in one short line. Call `journal.py add` and confirm in one line with the id. Never argue the user out of their number. If the user asks what Claude thinks, Claude may say so but logs only the user's number.
- **Grade.** Run `list --due`, falling back to `--open`. One entry at a time: restate the prediction and the user's number, ask what actually happened. Record only what the user confirms; never infer an outcome from memory of the conversation. If the outcome is ambiguous, ask. After grading, show a one-line result (for example "70% claim: it happened" or "2h estimate, 3.5h actual: 1.75x").
- **Review.** Run `stats`, then explain in plain language: where the user is overconfident (by bucket and tag), estimate bias, and range hit rate. State sample-size caveats. Give one concrete suggestion only for a slice with at least 5 graded entries (for example "pad refactor estimates by about 1.5x"); otherwise say there is not enough data yet.

Rules: never log, grade or offer to log unprompted; an offhand "this should take a few hours" is not a request to log. Locate the script relative to the skill directory. If Python 3 is missing, say so plainly. Relay script errors in one sentence and ask for the corrected value.

SKILL.md frontmatter: `name: decision-journal`; a single-line, double-quoted `description` starting "Use when" (the user wants to log a prediction or estimate about a dev or project decision, grade past predictions, or see how calibrated they are). No branding footer; one skill, with the script under `scripts/`.

## Repo deliverables

- `plugins/decision-journal/` generated by `scripts/new_skill.py`, then `SKILL.md` and `scripts/journal.py` added inside the skill folder.
- `plugins/decision-journal/README.md`: SEO H1 "decision-journal: a Claude Code skill by Naren", when it triggers, install, an example session, where the log lives, and how to reset it (delete the file).
- `tests/test_journal.py`: unit tests for the script.
- Marketplace entry, catalog and `llms.txt` generated by the tooling; a `CHANGELOG.md` entry.
- Repo conventions hold: `validate.py` and the whole test suite pass.

## Verification

Script, written test-first with `unittest`: add (both types), list filters, grade, stats math with known inputs and exact expected values (bucket rates, Brier score, median ratio, range hit rate, small-sample markers), every validation rule, malformed-line preservation across a rewrite, atomic write, CRLF/BOM tolerance, the path and date env overrides, and exit codes.

Skill behavior, each scenario run with and without the skill (as for comprehension-check):

| Scenario | Expected with the skill |
|---|---|
| "Log a prediction: this refactor takes 2 hours" | Asks only for what is missing (unit is known; offers range, know-by, tag), then logs |
| "I predict the cache won't scale" | Asks for confidence; logs as a claim |
| Offhand "this should take a few hours" with no request | Does not log or offer to log |
| Grade with an ambiguous outcome | Asks a clarifying question before recording |
| Grade where the conversation hints at the outcome | Asks the user to confirm; does not record from memory |
| Review with fewer than 5 graded entries | Says too few to conclude; invents no pattern |
| Review with a populated journal | Plain-language summary whose numbers match `stats` exactly |
| "What do you think it will take?" | Gives its own view, logs only the user's number |

Plus a real headless Claude Code session confirming the description triggers on a request and not on an offhand remark.

## Out of scope

See Decisions. Pushing to GitHub remains a separate, explicit step.
