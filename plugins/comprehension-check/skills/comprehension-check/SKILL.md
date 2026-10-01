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
