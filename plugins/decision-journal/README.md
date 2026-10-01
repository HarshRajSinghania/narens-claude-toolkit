# decision-journal: a Claude Code skill by Naren

> Log your predictions about dev decisions, grade them when the outcome is in, and see where you are overconfident.

Part of [Naren's Claude Skills](https://github.com/NarenDawar/narens-claude-skills).

"This refactor takes 2 hours." "This approach won't scale." Developers make predictions like these all day and almost never check them. `decision-journal` keeps a private log of your predictions, asks you for the outcome later, and turns the results into a plain calibration report: how often your 80%-sure calls come true, and how far your time estimates run over.

Existing prediction journals are built for trading and prediction markets. This one is for software and project decisions.

## When it triggers

Only when you ask. Example phrasings:

- "Log a prediction: this migration takes 3 hours."
- "I predict the cache layer won't scale past 10k users."
- "Grade my predictions."
- "How calibrated am I?"

It never logs, grades or nags on its own, and an offhand "this should take a few hours" is not a request.

## Install

**Plugin marketplace (recommended)**

```text
/plugin marketplace add NarenDawar/narens-claude-skills
/plugin install decision-journal@narens-claude-skills
```

**Manual**

Copy `plugins/decision-journal/skills/decision-journal` into `~/.claude/skills/`. It needs Python 3 (standard library only).

## Example

**You:** Log a prediction: refactoring the auth module takes 2 hours.

**Claude:** Add an 80% range, a know-by date or a tag? Or say "log it".

**You:** Range 1.5 to 4 hours, tag refactor.

**Claude:** Logged as #4.

Weeks later:

**You:** Grade my predictions.

**Claude:** #4: "refactoring the auth module takes 2 hours". What was the actual time?

**You:** About 3.5 hours.

**Claude:** 2 hours estimated, 3.5 actual: 1.75x.

And once you have enough graded entries:

```text
Claims (n=13): Brier 0.247
  70-79  n=5  stated 70%  actual 60%  gap +10
  80-89  n=6  stated 80%  actual 67%  gap +13
Estimates (n=5): median actual/estimate 1.50x (you run over)
  Range hit: 2 of 4 = 50% (an 80% range should hit about 80%)
```

With fewer than 5 graded entries, or a slice smaller than 5, it says there is not enough data instead of inventing a pattern.

## How it works

- A small Python script (`scripts/journal.py`, standard library only) does all writing and arithmetic, so the numbers are always right. Claude handles the conversation.
- Two kinds of prediction: **claims** (yes/no, with 50-99% confidence) and **estimates** (a number, with an optional 80% range).
- You grade each one yourself; Claude only records outcomes you confirm.

## Where your data lives

One private file: `~/.claude/decision-journal.jsonl`, one JSON entry per line, shared across all your projects and never committed to a repo. To reset, delete the file. To fix a typo, ask Claude (it will show which entry it means and ask you to confirm before changing anything) or edit the file by hand; there is no edit or delete command yet. Set `DECISION_JOURNAL_PATH` to use a different file.

---

Made by [Naren](https://github.com/NarenDawar). If this helped, star the repo.
