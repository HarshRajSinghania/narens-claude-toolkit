# comprehension-check Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and ship the `comprehension-check` skill, which quizzes the user on code Claude wrote this session, using the repo's scaffolding.

**Architecture:** One plugin (`plugins/comprehension-check/`) containing a single `SKILL.md` (no scripts), a per-skill README, and generated marketplace/catalog entries. The skill is developed test-first in the writing-skills sense: scenarios run against fixture repos WITHOUT the skill (baseline), then WITH it, and the skill text is tightened until the scenarios pass.

**Tech Stack:** Markdown (`SKILL.md`), the repo's Python tooling (`scripts/new_skill.py`, `validate.py`, `build_catalog.py`, `unittest`), git fixtures, general-purpose subagents (model `sonnet`) as the scenario runner.

**Spec:** `docs/superpowers/specs/2026-09-30-comprehension-check-design.md`

## Global Constraints

- Plugin and skill name: `comprehension-check` (kebab-case; skill dir name equals frontmatter `name`).
- `SKILL.md` frontmatter has `name` and a single-line, double-quoted `description` starting with `Use when`. No branding footer in `SKILL.md`.
- Trigger is manual only: the skill must never start or offer a quiz unprompted.
- Delivery: one question at a time; wait for the answer; grade; then continue. Summary at the end.
- 3-5 questions for a large change, fewer for a small one, never more than 5.
- Before grading any answer, read the relevant code in the current tree; never reveal an answer before the user responds; "I don't know" is a valid answer and counts as a flag, with no lecture.
- Questions are risk-first "what if" failure-mode questions tied to `file:line`; never "what does this function do?".
- Author is `Naren`; GitHub user `NarenDawar`; repo `narens-claude-skills`.
- One `SKILL.md`, no scripts, no score persistence.
- Do not push to GitHub in this plan; pushing is a separate, explicit user request.
- Scratch work (fixtures, baseline and run outputs) lives in the session scratchpad, never in the repo: `C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a/scratchpad` (referred to below as `$SP`).
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

The spec's scenario table covers the main flows. These input classes are implied but not named; each is a scenario below (S7-S11):

- **Not a git repo** (changes known only from the conversation): the skill still scopes to files Claude wrote. Scenario S7.
- **Mixed edits** (the user's own uncommitted changes sit next to Claude's): quiz only Claude's changes. Scenario S8.
- **Huge diff** (dozens of files): still at most 5 questions, ranked by risk. Scenario S9.
- **Docs/config-only change**: say there is nothing meaningful to quiz instead of inventing code questions. Scenario S10.
- **User changes the subject mid-quiz** ("actually, fix the bug first"): pause, handle it, offer to resume; no penalty. Scenario S11.

---

## Execution notes

- **Fixture ruling (Task 1):** the planned race (re-appended job lost because workers exit) does not reproduce: the failing worker re-appends and then pops the job itself (0 lost in 400 runs). Replaced with a timer-scheduled retry that fires after `run()` has returned (100/100 runs lose the job). Scenario text and README example updated to match.

## Scenario catalogue (used by Tasks 1 and 3)

Every scenario is one prompt to a fresh general-purpose subagent (`model: sonnet`). The prompt is built from this template; "SKILL" is the full text of `SKILL.md` for with-skill runs and is omitted for baseline runs.

```text
You are Claude Code, working in the repository at <FIXTURE PATH>. You may read any files there and run read-only git commands. Do not modify anything.
<If with-skill:> You have this skill available. Follow it where it applies:
<SKILL>
<end>

Conversation so far:
<TRANSCRIPT>

Write ONLY your next message to the user, exactly as you would send it. Do not describe what you are doing; just write the message.
```

| ID | Fixture | Transcript | Pass criteria (with skill) |
|---|---|---|---|
| S1 | `fx-queue` | `User: Please quiz me on the code you just wrote.` | Asks exactly ONE question, about a failure mode (concurrency, retry, lost job, unlocked append), citing `queue.py` plus a line number. Does not reveal an answer. Does not list further questions. |
| S2 | `fx-tiny` | `User: Quiz me on that change.` | One question at most, or says the change is too small to quiz. Not 3-5 questions. |
| S3 | `fx-clean` | `User: Quiz me on what you changed.` | Says nothing changed this session (or nothing meaningful) and stops. No questions. |
| S4 | `fx-queue` | `User: quiz me` / `Claude: <Q1 about what state a job is in if the handler fails on its last attempt while other workers have already exited>` / `User: idk` | Treats it as a valid answer, states the actual behavior with a `queue.py` line pointer, marks the topic as a gap. No lecture beyond that, no scolding. May then ask the next question or the summary. |
| S5 | `fx-queue` | `User: quiz me` / `Claude: <Q1 as in S4>` / `User: just give me the answers` | Asks for one attempt first (or offers a hint). Does NOT dump the full answer in this message. |
| S6 | `fx-queue` | `User: quiz me` / `Claude: <Q1 as in S4>` / `User: It retries up to 3 times and if it still fails the job goes into self.dead.` | Reads the code, then says the answer is partly right but MISSES that a failed job can be silently lost: its retry is scheduled by a `threading.Timer` and only appended after the workers have exited, so when `run()` returns it is neither retried nor in `dead`. Cites `queue.py`. |
| S7 | `fx-nogit` | `User: Quiz me on the code you wrote today. (Claude created queue.py this session; there is no git repo.)` | Still scopes to `queue.py`, asks one failure-mode question. Does not refuse because git is missing. |
| S8 | `fx-mixed` | `User: Quiz me on your changes. (Claude edited only queue.py this session. The user edited README.md themselves.)` | Question is about `queue.py`, not README.md. |
| S9 | `fx-huge` | `User: Quiz me on that big change.` | Asks ONE question now (one at a time), about `queue.py` risk, and does not announce more than 5 total. Does not walk the 60 trivial files. |
| S10 | `fx-docs` | `User: Quiz me on that change.` | Says there is nothing meaningful to quiz (docs-only), or at most one question about the docs claim. No invented code-internals questions. |
| S11 | `fx-queue` | `User: quiz me` / `Claude: <Q1 as in S4>` / `User: Actually, can you fix that lost-job bug first?` | Pauses the quiz, acknowledges, and offers to resume afterwards. Does not penalize or lecture. Does not start fixing silently without saying the quiz is paused. |

Baseline runs (no skill) are executed for S1, S2, S4 and S5 only.

---

### Task 1: Fixtures and baseline

**Files:**
- Create (scratch, not committed): `$SP/fixtures/fx-queue`, `fx-tiny`, `fx-clean`, `fx-nogit`, `fx-mixed`, `fx-huge`, `fx-docs`
- Create (scratch, not committed): `$SP/baseline.md`

**Interfaces:**
- Produces: fixture directories used by every scenario in Task 3, and `$SP/baseline.md` listing, for S1, S2, S4, S5, what the no-skill runs did and the gaps the skill text must close.

- [ ] **Step 1: Build the fixtures**

Run this script (Git Bash). It creates seven small fixtures. `fx-queue` has a committed initial `queue.py` plus an uncommitted "session change" that adds worker threads with a deliberate lost-job race (a failed job can be re-appended after every other worker has exited) and two unlocked list appends.

```bash
SP="C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a/scratchpad"
FX="$SP/fixtures"; rm -rf "$FX"; mkdir -p "$FX"
G='git -c user.name=t -c user.email=t@t -c commit.gpgsign=false'

cat > /tmp/queue_v1.py <<'EOF'
class RetryQueue:
    def __init__(self, max_retries=3):
        self.items = []
        self.max_retries = max_retries

    def put(self, job):
        self.items.append((job, 0))

    def run(self, handler):
        while self.items:
            job, attempts = self.items.pop(0)
            try:
                handler(job)
            except Exception:
                if attempts + 1 < self.max_retries:
                    self.items.append((job, attempts + 1))
EOF

cat > /tmp/queue_v2.py <<'EOF'
import threading


class RetryQueue:
    def __init__(self, max_retries=3, workers=4):
        self.items = []
        self.max_retries = max_retries
        self.workers = workers
        self.lock = threading.Lock()
        self.dead = []

    def put(self, job):
        with self.lock:
            self.items.append((job, 0))

    def _pop(self):
        with self.lock:
            return self.items.pop(0) if self.items else None

    def _worker(self, handler):
        while True:
            entry = self._pop()
            if entry is None:
                return
            job, attempts = entry
            try:
                handler(job)
            except Exception:
                if attempts + 1 < self.max_retries:
                    self.items.append((job, attempts + 1))
                else:
                    self.dead.append(job)

    def run(self, handler):
        threads = [
            threading.Thread(target=self._worker, args=(handler,))
            for _ in range(self.workers)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
EOF

mk() { mkdir -p "$FX/$1" && cd "$FX/$1" && git init -q && echo "# $1" > README.md; }

# fx-queue: committed v1, uncommitted v2
mk fx-queue; cp /tmp/queue_v1.py queue.py; git add -A; $G commit -q -m "initial"; cp /tmp/queue_v2.py queue.py

# fx-tiny: committed v1, uncommitted one-line change
mk fx-tiny; cp /tmp/queue_v1.py queue.py; git add -A; $G commit -q -m "initial"; sed -i 's/max_retries=3/max_retries=5/' queue.py

# fx-clean: committed, clean tree
mk fx-clean; cp /tmp/queue_v1.py queue.py; git add -A; $G commit -q -m "initial"

# fx-nogit: no git repo, queue.py exists
mkdir -p "$FX/fx-nogit"; cp /tmp/queue_v2.py "$FX/fx-nogit/queue.py"

# fx-mixed: Claude's queue change plus the user's own README edit
mk fx-mixed; cp /tmp/queue_v1.py queue.py; git add -A; $G commit -q -m "initial"; cp /tmp/queue_v2.py queue.py; echo "Notes I wrote by hand about deployment." >> README.md

# fx-huge: queue change plus 60 trivial file changes
mk fx-huge; cp /tmp/queue_v1.py queue.py; mkdir pkg; for i in $(seq 1 60); do echo "VALUE = $i" > pkg/mod$i.py; done
git add -A; $G commit -q -m "initial"; cp /tmp/queue_v2.py queue.py; for i in $(seq 1 60); do echo "VALUE = $((i+1))" > pkg/mod$i.py; done

# fx-docs: committed, then README-only edit
mk fx-docs; cp /tmp/queue_v1.py queue.py; git add -A; $G commit -q -m "initial"; printf '\nThe queue retries failed jobs up to 3 times.\n' >> README.md

for d in "$FX"/*/; do echo "== $d"; (cd "$d" && (git status --short 2>/dev/null || ls)); done
```

Expected: every directory prints; `fx-queue` shows ` M queue.py`, `fx-tiny` shows ` M queue.py`, `fx-clean` prints nothing, `fx-nogit` lists `queue.py`, `fx-mixed` shows ` M README.md` and ` M queue.py`, `fx-huge` shows 61 modified files, `fx-docs` shows ` M README.md`.

- [ ] **Step 2: Confirm the fixture bug is real**

```bash
cd "$FX/fx-queue" && python - <<'EOF'
import threading, time
from queue import RetryQueue  # local queue.py shadows the stdlib module

lost = 0
for _ in range(200):
    q = RetryQueue(max_retries=3, workers=4)
    calls = []
    def handler(job):
        calls.append(job)
        if job == "flaky":
            time.sleep(0.001)
            raise RuntimeError("boom")
    for j in ("a", "b", "c", "flaky"):
        q.put(j)
    q.run(handler)
    if "flaky" not in q.dead and calls.count("flaky") < 3:
        lost += 1
print("runs where flaky was neither retried 3 times nor dead:", lost)
EOF
```

Expected: a number greater than 0, which proves the lost-job race exists. If it prints `0`, increase the `time.sleep` to `0.01` and rerun until it is greater than 0 (the point is only to confirm the bug is real, so S6's pass criterion is truthful). Record the number in `$SP/baseline.md`.

- [ ] **Step 3: Run the baseline scenarios (no skill)**

For each of S1, S2, S4, S5, dispatch one general-purpose subagent with `model: sonnet`, using the template in the scenario catalogue with the skill block omitted, the fixture path from the table (`$FX/<fixture>`), and the transcript from the table. For S4 and S5 the Claude question in the transcript is:

`Claude: If handler(job) raises on a job's first attempt while the other three workers have already returned because the queue looked empty, what state is that job in when run() returns?`

Save each agent's returned message verbatim under its scenario ID in `$SP/baseline.md`.

- [ ] **Step 4: Record the gaps**

Read the four outputs. In `$SP/baseline.md`, under a `## Gaps to close` heading, write one line per observed failure against the pass criteria (for example "asked all 5 questions at once", "revealed answers inside the question", "lectured after idk", "dumped answers when asked", "questions were 'what does X do?'"). If a baseline already meets a criterion, note that and do not add skill text for it.

Expected: `$SP/baseline.md` has four dated run outputs and a non-empty `## Gaps to close` section. If the baselines already pass every criterion, stop and report to the user: the skill's value would be doubtful and the design needs revisiting.

- [ ] **Step 5: No commit**

This task produces scratch artifacts only. Confirm `git status --short` in the repo is empty.

---

### Task 2: Scaffold the plugin and write SKILL.md (v1)

**Files:**
- Create (generated): `plugins/comprehension-check/.claude-plugin/plugin.json`, `plugins/comprehension-check/README.md`, `plugins/comprehension-check/skills/comprehension-check/SKILL.md`
- Modify (generated): `.claude-plugin/marketplace.json`, `README.md`, `llms.txt`
- Modify: `plugins/comprehension-check/skills/comprehension-check/SKILL.md` (replace body)

**Interfaces:**
- Consumes: `python scripts/new_skill.py <name> "<description>"` (creates plugin from `template/`, registers it, rebuilds catalog); `python scripts/validate.py`.
- Produces: a validating plugin whose `SKILL.md` is the text the Task 3 scenarios load.

- [ ] **Step 1: Scaffold with the repo tool**

```bash
cd "C:/Users/naren/Documents/claude-skills"
python scripts/new_skill.py comprehension-check "Use when the user asks to be quizzed on, or to check their understanding of, code Claude wrote this session (for example 'quiz me on that' or 'do I actually understand this change?')."
```

Expected: `Created ...\plugins\comprehension-check. Now edit SKILL.md and README.md, then run validate.py.`

- [ ] **Step 2: Write the skill body (v1)**

Overwrite `plugins/comprehension-check/skills/comprehension-check/SKILL.md` with exactly this, keeping the frontmatter that the tool generated (the first block between `---` lines must stay byte-identical to the generated one):

```markdown
---
name: comprehension-check
description: "Use when the user asks to be quizzed on, or to check their understanding of, code Claude wrote this session (for example 'quiz me on that' or 'do I actually understand this change?')."
---

# Comprehension Check

## Overview

The user owns what ships. This skill tests whether they could maintain the code Claude wrote this session by asking how it fails, not what it says. It runs only when the user asks. Never start a quiz or offer one unprompted.

## When to Use

- The user asks to be quizzed on, or to check their understanding of, a change Claude made.

Do not use it for study topics or for code Claude did not change this session. Do not start it on your own after finishing work.

## Process

1. **Scope.** Find what Claude changed this session: `git diff`, `git diff --cached`, recent `git log`, and the conversation. Quiz only on Claude's changes, never the user's own edits; if you cannot tell whose change something is, ask. A file or commit the user names overrides this. With no git repo, use the conversation and the files Claude wrote. If nothing meaningful changed (clean tree, docs- or config-only, formatting), say so in a sentence or two and stop.
2. **Rank.** Pick the spots where a misunderstanding would hurt most: concurrency, error and retry paths, state and ordering, security boundaries, non-obvious logic. Ask one question for a tiny change and 3-5 for a large one. Never more than 5, however big the diff. Read the code for each spot before writing its question, so you know the true answer.
3. **Ask one question, then stop.** Tie it to a `file:line`. Do not list the other questions. Do not put the answer or a hint in the question.
4. **Grade the answer.** First read the relevant code in the current tree. Then say what the user got right, what they missed, and the actual behavior, with a `file:line` pointer. Do not grade from memory. Then ask the next question.
5. **Summarize.** After the last question, give a table: topic, verdict (solid / shaky / couldn't maintain), `file:line`. List the flagged parts and one next step for each, such as "ask me to explain X" or "add a test for Y".

## Writing Questions

Ask about failure modes and behavior, not about what code says.

- Good: "If `handler(job)` raises on its first attempt while the other workers have already returned, what state is that job in when `run()` returns? (`queue.py:35`)"
- Good: "What happens if `put()` is called while `run()` is draining the queue?"
- Bad: "What does `run()` do?" (recitation)
- Bad: "Isn't it risky that the append is unlocked?" (leaks the answer)

## Handling Answers

- "I don't know" is a valid answer. State the actual behavior with the pointer, mark the topic as a gap, and move on. No lecture, no scolding.
- If the user asks for the answers without trying, ask for one attempt first (or offer a hint). Explain fully only after an attempt or a second request, and mark the topic as a gap.
- If the user changes the subject or asks you to do something else, pause the quiz, handle the request, and offer to resume. Do not penalize the pause.
- A partly right answer is graded as partly right. Name the missing piece.

## Tone

Direct and respectful. This is a check, not a grade. Do not pad with praise.

## Common Mistakes

- Asking trivia or recitation questions.
- Asking more than 5 questions, or all questions at once.
- Leaking the answer inside the question.
- Quizzing on code that was not changed this session, or on the user's own edits.
- Grading an answer without reading the code first.
- Starting or offering a quiz unprompted.
```

- [ ] **Step 3: Validate**

Run: `python scripts/validate.py` then `python -m unittest discover -s tests`
Expected: `OK: all plugins valid`; all tests pass.

- [ ] **Step 4: Confirm the catalog picked it up**

Run: `python scripts/build_catalog.py --check; echo exit=$?`
Expected: `exit=0`, and `README.md` contains a table row with `comprehension-check`.

- [ ] **Step 5: Commit**

```bash
git add plugins .claude-plugin README.md llms.txt
git commit -m "feat: add comprehension-check skill (v1)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Run the scenarios with the skill and refine

**Files:**
- Modify: `plugins/comprehension-check/skills/comprehension-check/SKILL.md` (only if a scenario fails)
- Create (scratch): `$SP/with-skill.md`

**Interfaces:**
- Consumes: fixtures and the scenario catalogue from Task 1, the `SKILL.md` from Task 2.
- Produces: a skill text under which S1-S11 all meet their pass criteria, plus `$SP/with-skill.md` recording the final passing outputs.

- [ ] **Step 1: Run S1-S11 with the skill**

For each scenario ID, dispatch one general-purpose subagent (`model: sonnet`) using the template, with the current full text of `SKILL.md` inserted as `<SKILL>`, the fixture path from the table, and the transcript from the table (the Claude question in S4, S5, S6, S11 is the one given in Task 1 Step 3). Save each returned message verbatim in `$SP/with-skill.md` under its ID.

- [ ] **Step 2: Grade each output against its pass criteria**

For every scenario write `PASS` or `FAIL: <which criterion and why>` in `$SP/with-skill.md`. Check S6 against the real behavior from Task 1 Step 2, not against your own reading of the output alone: the correct grading must identify the lost-job case.

Expected: a verdict line for all 11 scenarios.

- [ ] **Step 3: Fix failures (if any)**

For each FAIL, change `SKILL.md` minimally to close that specific gap: add or sharpen one rule, or add a line to Common Mistakes. Do not add rules for scenarios that already pass. Re-run only the failed scenarios, plus S1 and S2 (to catch regressions). Repeat this step at most 3 times. If a scenario still fails after 3 rounds, stop and report it to the user with the output instead of continuing to patch.

Expected: all 11 scenarios PASS in `$SP/with-skill.md`.

- [ ] **Step 4: Re-validate**

Run: `python scripts/validate.py` then `python -m unittest discover -s tests`
Expected: `OK: all plugins valid`; all tests pass.

- [ ] **Step 5: Commit (only if SKILL.md changed)**

```bash
git add plugins/comprehension-check/skills/comprehension-check/SKILL.md
git commit -m "fix: tighten comprehension-check after scenario runs" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Plugin README, changelog, final verification

**Files:**
- Modify: `plugins/comprehension-check/README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: the generated `plugins/comprehension-check/README.md` (from the template) and the verified skill behavior.
- Produces: the public per-skill page and a changelog entry.

- [ ] **Step 1: Write the plugin README**

Replace `plugins/comprehension-check/README.md` with exactly this:

````markdown
# comprehension-check: a Claude Code skill by Naren

> Quiz yourself on the code Claude just wrote, and find the parts you could not maintain.

Part of [Naren's Claude Skills](https://github.com/NarenDawar/narens-claude-skills).

AI-written code is easy to accept and hard to own. `comprehension-check` asks you a few pointed questions about the change Claude made in your session, grades your answers against the actual code, and tells you which parts you could not maintain yourself.

Other tutor and quiz skills cover study material and general topics. This one quizzes you on **your own session's code**.

## When it triggers

Only when you ask. Example phrasings:

- "Quiz me on that change."
- "Do I actually understand what you just wrote?"
- "Check my understanding of the retry logic."

It never starts on its own.

## Install

**Plugin marketplace (recommended)**

```text
/plugin marketplace add NarenDawar/narens-claude-skills
/plugin install comprehension-check@narens-claude-skills
```

**Manual**

Copy `plugins/comprehension-check/skills/comprehension-check` into `~/.claude/skills/`.

## Example

After Claude adds worker threads to a retry queue, you say: "Quiz me on that."

**Claude:** If `handler(job)` raises on a job's first attempt while the other workers have already returned, what state is that job in when `run()` returns? (`queue.py:35`)

**You:** It retries 3 times, then goes to `dead`.

**Claude:** Partly right. It does go to `dead` after 3 failures, if it gets that far. What you missed: the retry is scheduled by a `threading.Timer` that fires after the workers have exited, so when `run()` returns the job is neither retried nor in `dead` (`queue.py:30-38`). Next question...

At the end you get a summary:

| Topic | Verdict | Where |
| --- | --- | --- |
| Retry and lost-job path | couldn't maintain | `queue.py:30-38` |
| Lock usage on `put` / `_pop` | solid | `queue.py:14-21` |

with a suggested next step for each flagged part, such as "add a test for a job that fails on its first attempt".

## How it works

1. Finds what Claude changed this session (git diff and conversation), ignoring your own edits.
2. Picks the riskiest spots: concurrency, error paths, state and ordering, security boundaries, non-obvious logic.
3. Asks one question at a time, tied to a `file:line`, and never gives the answer away.
4. Reads the code before grading, so its feedback matches what the code really does.
5. Ends with a summary of what is solid, shaky, or beyond your ability to maintain today.

---

Made by [Naren](https://github.com/NarenDawar). If this helped, star the repo.
````

- [ ] **Step 2: Add the changelog entry**

In `CHANGELOG.md`, under `### Added` of `## [Unreleased]`, add the line:

```markdown
- `comprehension-check` skill: quizzes you on the code Claude wrote this session and flags the parts you could not maintain.
```

- [ ] **Step 3: Final verification**

Run:

```bash
python -m unittest discover -s tests -v 2>&1 | tail -4
python scripts/validate.py
python scripts/build_catalog.py --check; echo exit=$?
git status --short
```

Expected: all tests pass (70/70); `OK: all plugins valid`; `exit=0`; `git status` lists only `CHANGELOG.md` and `plugins/comprehension-check/README.md`.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md plugins/comprehension-check/README.md
git commit -m "docs: add comprehension-check README and changelog entry" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Spec coverage self-check

| Spec requirement | Task |
|---|---|
| Name, one SKILL.md, no scripts | 2 |
| Manual-only trigger, never offers or auto-fires | 2 (rules), 3 (S1-S3 verify no unprompted behavior) |
| Risk-first failure-mode questions tied to `file:line` | 2, 3 (S1, S7) |
| One at a time, graded as you go, summary with verdicts and next steps | 2 (Process), 3 (S4-S6) |
| Scope: session changes, ranked by risk; named file/commit overrides | 2; 3 (S7-S9) |
| Count scales with change size, max 5 | 2; 3 (S2, S9) |
| Read code before grading; no early answers; idk is a flag | 2; 3 (S4, S6) |
| "Just give me the answers" handling | 2; 3 (S5) |
| Plugin README with SEO H1 and before/after | 4 |
| Marketplace entry, catalog, llms.txt | 2 |
| CHANGELOG entry | 4 |
| Scenario table (concurrency, one-line, no changes, idk, answers, grading accuracy) | 3 (S1-S6) |
| `validate.py` and unit tests pass | 2, 3, 4 |
| Out of scope: persistence, auto-trigger, pushing | not implemented, by design |
