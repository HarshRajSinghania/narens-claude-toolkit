# comprehension-check: a Claude Code skill by Naren

> Quiz yourself on the code Claude just wrote, and find the parts you could not maintain.

Part of [Naren's Claude Toolkit](https://github.com/NarenDawar/narens-claude-toolkit).

AI-written code is easy to accept and hard to own. `comprehension-check` asks you a few pointed questions about the change Claude made in your session, grades your answers against the actual code, and tells you which parts you could not maintain yourself.

Other tutor and quiz skills cover study material and general topics. This one quizzes you on **your own session's code**.

## When it triggers

Only when you ask. Example phrasings:

- "Quiz me on that change."
- "Do I actually understand what you just wrote?"
- "Check my understanding of the retry logic."

You can also run it directly with `/comprehension-check:comprehension-check`. It never starts on its own.

## Install

**Plugin marketplace (recommended)**

```text
/plugin marketplace add NarenDawar/narens-claude-toolkit
/plugin install comprehension-check@narens-claude-toolkit
```

**Manual**

Copy `plugins/comprehension-check/skills/comprehension-check` into `~/.claude/skills/`.

## Example

After Claude adds worker threads to a retry queue, you say: "Quiz me on that."

**Claude:** If `handler(job)` raises on a job's first attempt, what state is that job in when `run()` returns? (`queue.py:35`)

**You:** It retries 3 times, then goes to `dead`.

**Claude:** Partly right. It does go to `dead` after 3 failures, if it gets that far. What you missed: the retry is scheduled by a `threading.Timer`, and `run()` only joins the worker threads, so it can return before the timer fires and the job is neither retried nor in `dead` (`queue.py:30-38`). Next question...

At the end you get a summary:

| Topic | Verdict | Where |
| --- | --- | --- |
| Retry and lost-job path | couldn't maintain | `queue.py:30-38` |
| Lock usage on `put` / `_pop` | solid | `queue.py:13-19` |

with a suggested next step for each flagged part, such as "add a test for a job that fails on its first attempt".

## How it works

1. Finds what Claude changed this session (git diff and conversation), ignoring your own edits.
2. Picks the riskiest spots: concurrency, error paths, state and ordering, security boundaries, non-obvious logic.
3. Asks one question at a time, tied to a `file:line`, and never gives the answer away.
4. Reads the code before grading, so its feedback matches what the code really does.
5. Ends with a summary of what is solid, shaky, or beyond your ability to maintain today.

---

Made by [Naren](https://github.com/NarenDawar). If this helped, star the repo.
