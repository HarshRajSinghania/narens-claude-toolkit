# mcp-fixer benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build sub-project 3 of mcp-fixer: `mcp-fixer tasks` generates a reviewable tasks file from a server's original tools using a model, and `mcp-fixer bench` runs every task against the original and the patched tool list and reports both accuracies, a paired comparison, token sizes and a sample-size-aware verdict (`worse`, `no drop detected`, `inconclusive`).

**Architecture:** Four new modules in `servers/mcp-fixer/src/mcp_fixer/`: `bench_prompts.py` (prompts and lenient reply parsing; pure), `bench_stats.py` (Wilson interval, seeded paired bootstrap, verdict; pure), `runners.py` (`ClaudeRunner`, `ApiRunner`, `FakeRunner` behind one `complete(prompt)` interface) and `bench.py` (tasks-file format, patched view built with the wrapper's own `Router`, trial orchestration, report building and rendering). `cli.py` gains `tasks` and `bench`. No test calls a real model: runners are tested against a stand-in executable and a local HTTP server, orchestration against `FakeRunner`.

**Tech Stack:** Python 3.9+ standard library (`json`, `math`, `random`, `re`, `urllib`, `http.server`, `subprocess`, `threading`, `argparse`, `unittest`), Markdown.

**Spec:** `docs/superpowers/specs/2026-10-05-mcp-fixer-bench-design.md`

## Global Constraints

- Python 3.9+ standard library only; LF line endings; code must run on Python 3.9 (no `match`, no `X | Y` annotations, no parenthesized context managers).
- No test calls a real model or the real Anthropic API. The runners give the model no tools; nothing a model says is executed.
- The API key is never printed, logged, put in an error message, or written to a report; error text from the API is redacted with the key before it is shown.
- The task file, the patch and every model reply are untrusted text: anything from them that reaches the terminal goes through `report._safe` (control characters become visible escapes) and is truncated (notes to 300 characters).
- A trial outcome is exactly one of `correct`, `wrong`, `invalid`, `errored`. `invalid` (unparseable reply, or a name that was not in the shown list) counts as wrong in accuracy; `errored` (the runner failed twice) is excluded from accuracy and counted separately. Accuracy = correct / (correct + wrong + invalid).
- Both sides of a comparison see the same tasks in the same shuffled tool order (seeded by `--seed`, the task id and the repeat number), and the patched side's reply is mapped back to the original name before scoring.
- The patched tool list is built with `wrap.Router` (so it is exactly what `wrap` serves); a stale entry is not applied and is counted.
- Verdict rules (exact): `worse` when the upper bound of the 95% paired-difference interval is below 0; else `no drop detected` when there are at least 30 usable tasks and the lower bound is above minus the tolerance; else `inconclusive`. `bench` exit codes: 0 for `no drop detected` and `inconclusive`, 1 for `worse`, 2 for usage and runner errors. The report always ends with: "This measures whether a drop could be detected on these generated tasks; it does not show the patch improves tool selection."
- Model calls: `tasks x repeats x 2` for `bench`. Above 200 calls `bench` refuses without `--yes`. `tasks --out` refuses to overwrite (no `--force`) before any model call is spent.
- Do not push, merge, rename or change GitHub settings in this plan.
- Work on branch `mcp-fixer-bench` (already created, holds the spec commit).
- Repo rules: the README catalog is generated, existing files under `docs/superpowers/` are untouched.
- Scratch files live in the session scratchpad: `C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/4ec2fd29-f30d-4793-83a9-f979fbae59a4/scratchpad` (called `$SP`). **Write every file that contains backslashes (tests, scripts) with the Write tool or Edit tool, never with a shell heredoc or `python - <<EOF`: the shell layer collapses backslashes and a failed in-place write can truncate a file.**
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

**Clarifications decided in this plan** (spec details the plan makes precise):

- `valid_tools(tools)` keeps the first dict with a non-empty string `name` for each name; the tools fingerprint is `patch_format.fingerprint(valid_tools(tools))`, used identically by `tasks` (writing) and `bench` (checking).
- A request is dropped from generated tasks when `mentions_name(request, tool_name)` is true (the tool name, or the name with `_` or `-` as spaces, as a whole word, case-insensitive). A name like `run` therefore filters requests containing the word "run"; that is accepted.
- `mcp-fixer tasks` and `bench` read the server with `--timeout` (as `score` and `patch`); the model calls use a fixed 120-second per-call timeout.
- The API runner's default model is `claude-sonnet-5-5`; the `claude` runner's default is whatever the CLI uses.
- `--env` is for the server only; `ANTHROPIC_API_KEY` is read from the process environment.
- The version bump to 0.3.0 is in the last task (the existing package test compares `__init__.py` with `pyproject.toml`).
- **Risk to check in the live run (not testable here):** on Windows `claude` may be a `.cmd` shim, and an empty argument (`--tools ""`) can be dropped when a shim is launched through the shell. The stand-in test proves the runner passes the empty argument to a real executable; whether the real `claude` shim keeps it is the owner's live check, and the README says so.

## Review Focus

Failure modes the spec implies but a first pass is likely to skip. Each has a test in the task that owns the code:

1. Verdict honesty: 29 versus 30 tasks, exactly the tolerance, `worse` with very few tasks, an interval that is too wide (the reason and the number of extra tasks needed), a difference already beyond the tolerance (no extra-tasks promise). (Task 2)
2. Fair comparison: identical shuffled order on both sides; renamed tools mapped back; a stale patch entry not applied; `errored` never counted as wrong; `invalid` always counted as wrong; a task that has no scored repeat dropped and counted. (Task 4)
3. Reply parsing: JSON inside prose or fences, several objects (first object with a string `tool` wins), a name that was never shown, a non-string `tool`, an unterminated object, a 5,000-bracket reply, a megabyte of `{`. (Task 1)
4. Runner safety: the key absent from every error, timeouts stop the process tree, huge output is capped, a missing executable is a clear error, a missing API key fails before any call, only one retry. (Tasks 3 and 4)
5. Untrusted text: control characters in task requests, tool names and replies escaped in the report; typos and wrong types in the tasks file give one-line errors; an `expected` that is not a tool; duplicate tool names; an empty tool list. (Tasks 4 and 5)
6. Cost guard and file safety: the call count, `--yes`, `tasks --out` refusing to overwrite before spending any call, `--per-tool` bounds. (Task 5)

---

### Task 1: Prompts and reply parsing

**Files:**
- Create: `servers/mcp-fixer/src/mcp_fixer/bench_prompts.py`, `servers/mcp-fixer/tests/test_bench_prompts.py`

**Interfaces:**
- Produces: `render_tools(tools) -> str`; `trial_prompt(tools, request) -> str`; `tasks_prompt(tools, target, per_tool) -> str`; `parse_choice(text, names) -> str | None`; `parse_task_list(text) -> list[str] | None`; `mentions_name(request, name) -> bool`; `MAX_REPLY_CHARS = 20000`. Used by Tasks 4 and 5.

- [ ] **Step 1: Write the failing tests**

`servers/mcp-fixer/tests/test_bench_prompts.py`:

```python
import time
import unittest

import support  # noqa: F401
from mcp_fixer import bench_prompts as bp

TOOLS = [
    {
        "name": "search_items",
        "description": "Search the\n  catalog by keyword.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "Keyword"},
                "order": {"type": "string", "enum": ["asc", "desc"]},
            },
            "required": ["q"],
        },
    },
    {"name": "get_item", "description": "Fetch one item."},
    "junk",
    {"name": ""},
    {"description": "no name"},
]
NAMES = {"search_items", "get_item"}


class RenderTests(unittest.TestCase):
    def test_tools_are_rendered_compactly(self):
        text = bp.render_tools(TOOLS)
        self.assertIn("- search_items: Search the catalog by keyword.", text)
        self.assertIn("    - q (string; required): Keyword", text)
        self.assertIn("    - order (string; one of asc, desc)", text)
        self.assertIn("- get_item: Fetch one item.", text)
        self.assertNotIn("junk", text)
        self.assertNotIn("no name", text)

    def test_odd_schemas_do_not_crash(self):
        odd = [
            {"name": "a", "description": 5, "inputSchema": {"properties": {"x": {"type": ["string", "null"]}, "y": 5}, "required": [["x"], "y"]}},
            {"name": "b", "inputSchema": {"properties": "nope"}},
            {"name": "c", "inputSchema": []},
        ]
        text = bp.render_tools(odd)
        self.assertIn("- a", text)
        self.assertIn("x (string|null)", text)
        self.assertIn("y (required)", text)

    def test_the_trial_prompt_has_the_tools_the_request_and_the_format(self):
        prompt = bp.trial_prompt(TOOLS, "find me stuff {with} braces")
        for name in NAMES:
            self.assertIn(name, prompt)
        self.assertIn("User request: find me stuff {with} braces", prompt)
        self.assertIn('{"tool": "<tool name>"}', prompt)

    def test_the_tasks_prompt_names_the_target_and_the_count(self):
        prompt = bp.tasks_prompt(TOOLS, "get_item", 3)
        self.assertIn('need the tool "get_item"', prompt)
        self.assertIn("3 different requests", prompt)
        self.assertIn("search_items", prompt)


class ParseChoiceTests(unittest.TestCase):
    def test_accepted_replies(self):
        cases = [
            ('{"tool": "get_item"}', "get_item"),
            ('```json\n{"tool": "get_item"}\n```', "get_item"),
            ('I would pick this one: {"tool": "search_items"} because it fits.', "search_items"),
            ('{"tool": "get_item"} {"tool": "search_items"}', "get_item"),
            ('{"other": 1} {"tool": "get_item"}', "get_item"),
        ]
        for text, expected in cases:
            with self.subTest(text):
                self.assertEqual(bp.parse_choice(text, NAMES), expected)

    def test_rejected_replies_are_none(self):
        cases = [
            '{"tool": "ghost"}',
            '{"tool": 5}',
            '{"tool": ["get_item"]}',
            '{"tool": " get_item "}',
            '[{"tool": "get_item"}]',
            "",
            "no json here",
            '{"tool": "get_item"',
        ]
        for text in cases:
            with self.subTest(text):
                self.assertIsNone(bp.parse_choice(text, NAMES))

    def test_pathological_replies_are_fast_and_none(self):
        started = time.monotonic()
        self.assertIsNone(bp.parse_choice("[" * 5000, NAMES))
        self.assertIsNone(bp.parse_choice("{" * 1000000, NAMES))
        self.assertLess(time.monotonic() - started, 20)

    def test_a_valid_answer_after_the_cap_is_ignored(self):
        text = " " * (bp.MAX_REPLY_CHARS + 10) + '{"tool": "get_item"}'
        self.assertIsNone(bp.parse_choice(text, NAMES))


class ParseTaskListTests(unittest.TestCase):
    def test_lists(self):
        self.assertEqual(bp.parse_task_list('["a b", "c d"]'), ["a b", "c d"])
        self.assertEqual(bp.parse_task_list('```json\n["a b"]\n```'), ["a b"])
        self.assertEqual(bp.parse_task_list('Here you go: ["a b"] enjoy'), ["a b"])
        self.assertEqual(bp.parse_task_list('["a", 5, "", "  ", " b "]'), ["a", "b"])
        self.assertEqual(bp.parse_task_list('["x"] ["y"]'), ["x"])
        self.assertEqual(bp.parse_task_list("[1, 2]"), [])

    def test_no_list_is_none(self):
        for text in ("no", "", '{"a": 1}', '["unterminated'):
            with self.subTest(text):
                self.assertIsNone(bp.parse_task_list(text))


class MentionsNameTests(unittest.TestCase):
    def test_whole_word_matches_with_name_variants(self):
        self.assertTrue(bp.mentions_name("please get item 5", "get_item"))
        self.assertTrue(bp.mentions_name("use GET_ITEM now", "get_item"))
        self.assertTrue(bp.mentions_name("use get-item now", "get-item"))
        self.assertTrue(bp.mentions_name("run it", "run"))
        self.assertFalse(bp.mentions_name("show me the running totals", "run"))
        self.assertFalse(bp.mentions_name("find stuff", "get_item"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_bench_prompts.py" 2>&1 | tail -4`
Expected: ERROR, `ImportError: cannot import name 'bench_prompts' from 'mcp_fixer'`.

- [ ] **Step 3: Write the implementation**

`servers/mcp-fixer/src/mcp_fixer/bench_prompts.py`:

```python
"""Prompts and reply parsing for the benchmark. Pure; standard library only."""
import json
import re

MAX_REPLY_CHARS = 20000


def _oneline(value):
    return " ".join(value.split()) if isinstance(value, str) else ""


def _is_tool(tool):
    return isinstance(tool, dict) and isinstance(tool.get("name"), str) and bool(tool["name"])


def render_tools(tools):
    """Each tool as a name and description line, then one line per parameter."""
    lines = []
    for tool in tools:
        if not _is_tool(tool):
            continue
        description = _oneline(tool.get("description"))
        lines.append(f"- {tool['name']}: {description}" if description else f"- {tool['name']}")
        schema = tool.get("inputSchema")
        props = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(props, dict):
            continue
        required = schema.get("required")
        required = {r for r in required if isinstance(r, str)} if isinstance(required, list) else set()
        for pname, prop in props.items():
            prop = prop if isinstance(prop, dict) else {}
            bits = []
            kind = prop.get("type")
            if isinstance(kind, str):
                bits.append(kind)
            elif isinstance(kind, list):
                bits.append("|".join(str(k) for k in kind))
            if pname in required:
                bits.append("required")
            values = prop.get("enum")
            if isinstance(values, list) and values:
                bits.append("one of " + ", ".join(str(v) for v in values))
            head = f"    - {pname}" + (f" ({'; '.join(bits)})" if bits else "")
            text = _oneline(prop.get("description"))
            lines.append(f"{head}: {text}" if text else head)
    return "\n".join(lines)


def trial_prompt(tools, request):
    return (
        "You are choosing a tool for a user request. These are the available tools:\n\n"
        + render_tools(tools)
        + "\n\nUser request: "
        + request
        + "\n\nChoose the single best tool for this request. Reply with exactly one JSON object "
        'and nothing else, in the form {"tool": "<tool name>"}.'
    )


def tasks_prompt(tools, target, per_tool):
    return (
        "These are the tools of an MCP server:\n\n"
        + render_tools(tools)
        + f"\n\nWrite {per_tool} different requests that a person might type to an assistant when they "
        f'need the tool "{target}" and not any other tool above. Write each one as the person would say it, '
        "in plain words about their goal. Do not mention the tool's name and do not copy phrases from its "
        f"description. Reply with exactly one JSON array of {per_tool} strings and nothing else."
    )


def _json_values(text):
    """Every top-level JSON object or array found in `text`, in order."""
    decoder = json.JSONDecoder()
    index = 0
    while index < len(text):
        if text[index] in "{[":
            try:
                value, end = decoder.raw_decode(text, index)
            except (ValueError, RecursionError):
                index += 1
                continue
            yield value
            index = end
        else:
            index += 1


def parse_choice(text, names):
    """The tool name a reply picked, or None when the reply is unusable.

    The first JSON object with a string "tool" decides; its value must be exactly one of `names`.
    """
    for value in _json_values(text[:MAX_REPLY_CHARS]):
        if isinstance(value, dict) and isinstance(value.get("tool"), str):
            return value["tool"] if value["tool"] in names else None
    return None


def parse_task_list(text):
    """The strings of the first JSON array in a reply (empty ones dropped), or None."""
    for value in _json_values(text[:MAX_REPLY_CHARS]):
        if isinstance(value, list):
            return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return None


def mentions_name(request, name):
    """True when `request` contains the tool's name (or the name with _ or - as spaces) as a word."""
    variants = {name, re.sub(r"[_-]", " ", name)}
    for variant in variants:
        if variant and re.search(
            r"(?<![A-Za-z0-9])" + re.escape(variant) + r"(?![A-Za-z0-9])", request, re.IGNORECASE
        ):
            return True
    return False
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -4`
Expected: all PASS (254 existing plus this task's). If `test_pathological_replies_are_fast_and_none` is slow (over 20 s), the per-start `raw_decode` on `[`*5000 is the cause: lower `MAX_REPLY_CHARS` effects nothing here, so cap the scan by stopping after 200 failed starts instead of fixing the test.

- [ ] **Step 5: Commit**

```bash
python -m unittest discover -s tests 2>&1 | tail -2
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer benchmark prompts and reply parsing

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Statistics and the verdict

**Files:**
- Create: `servers/mcp-fixer/src/mcp_fixer/bench_stats.py`, `servers/mcp-fixer/tests/test_bench_stats.py`

**Interfaces:**
- Produces: `wilson(correct, total) -> (low, high)`; `paired_bootstrap(diffs, seed=0, resamples=2000) -> (mean, low, high)`; `tasks_needed(n, mean, low, high, tolerance) -> int | None`; `verdict(n, mean, low, high, tolerance, min_tasks=30) -> {"verdict", "reason", "tasksNeeded"}`; `MIN_TASKS = 30`. Used by Task 4.

- [ ] **Step 1: Write the failing tests**

`servers/mcp-fixer/tests/test_bench_stats.py`:

```python
import unittest

import support  # noqa: F401
from mcp_fixer import bench_stats as st


class WilsonTests(unittest.TestCase):
    def test_known_values(self):
        low, high = st.wilson(5, 10)
        self.assertAlmostEqual(low, 0.2366, places=3)
        self.assertAlmostEqual(high, 0.7634, places=3)
        low, high = st.wilson(0, 10)
        self.assertAlmostEqual(low, 0.0, places=3)
        self.assertAlmostEqual(high, 0.2775, places=3)
        low, high = st.wilson(10, 10)
        self.assertAlmostEqual(low, 0.7225, places=3)
        self.assertAlmostEqual(high, 1.0, places=3)

    def test_no_data_means_no_information(self):
        self.assertEqual(st.wilson(0, 0), (0.0, 1.0))

    def test_always_within_zero_and_one(self):
        for total in (1, 2, 7, 50):
            for correct in range(total + 1):
                low, high = st.wilson(correct, total)
                self.assertTrue(0.0 <= low <= high <= 1.0)


class BootstrapTests(unittest.TestCase):
    def test_the_same_seed_gives_the_same_answer(self):
        diffs = [0.0, 1.0, -1.0, 0.5, 0.0, -0.5, 0.25]
        self.assertEqual(st.paired_bootstrap(diffs, seed=3), st.paired_bootstrap(diffs, seed=3))

    def test_different_seeds_can_differ(self):
        diffs = [0.0, 1.0, -1.0, 0.5, 0.0, -0.5, 0.25, 0.1, -0.2]
        self.assertNotEqual(st.paired_bootstrap(diffs, seed=1), st.paired_bootstrap(diffs, seed=2))

    def test_constant_differences_have_a_point_interval(self):
        self.assertEqual(st.paired_bootstrap([0.0] * 10), (0.0, 0.0, 0.0))
        self.assertEqual(st.paired_bootstrap([-1.0] * 10), (-1.0, -1.0, -1.0))

    def test_no_tasks_means_no_information(self):
        self.assertEqual(st.paired_bootstrap([]), (0.0, -1.0, 1.0))

    def test_a_hand_computed_case(self):
        # Means of resamples of [1, -1] are -1, 0 or 1 (25%, 50%, 25%): the 2.5th percentile is -1
        # and the 97.5th is 1.
        self.assertEqual(st.paired_bootstrap([1.0, -1.0]), (0.0, -1.0, 1.0))

    def test_the_interval_contains_the_mean_for_a_typical_sample(self):
        diffs = [0.1, -0.1, 0.0, 0.2, -0.2, 0.05, 0.0, 0.0] * 5
        mean, low, high = st.paired_bootstrap(diffs)
        self.assertTrue(low <= mean <= high)


class VerdictTests(unittest.TestCase):
    def test_29_tasks_are_not_enough_but_30_are(self):
        short = st.verdict(29, 0.0, 0.0, 0.0, 0.05)
        self.assertEqual(short["verdict"], "inconclusive")
        self.assertIn("29", short["reason"])
        self.assertIn("30", short["reason"])
        self.assertEqual(st.verdict(30, 0.0, 0.0, 0.0, 0.05)["verdict"], "no drop detected")

    def test_the_tolerance_edge_is_exclusive(self):
        self.assertEqual(st.verdict(30, -0.01, -0.05, 0.02, 0.05)["verdict"], "inconclusive")
        self.assertEqual(st.verdict(30, -0.01, -0.049, 0.02, 0.05)["verdict"], "no drop detected")

    def test_worse_needs_only_an_upper_bound_below_zero(self):
        self.assertEqual(st.verdict(3, -1.0, -1.0, -0.2, 0.05)["verdict"], "worse")
        self.assertEqual(st.verdict(100, -0.1, -0.2, -0.001, 0.05)["verdict"], "worse")
        self.assertNotEqual(st.verdict(100, -0.1, -0.2, 0.0, 0.05)["verdict"], "worse")

    def test_a_wide_interval_says_how_many_tasks_would_help(self):
        result = st.verdict(40, -0.01, -0.1, 0.08, 0.05)
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertEqual(result["tasksNeeded"], 203)
        self.assertIn("203", result["reason"])

    def test_a_difference_beyond_the_tolerance_promises_nothing(self):
        result = st.verdict(40, -0.08, -0.15, 0.01, 0.05)
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertIsNone(result["tasksNeeded"])
        self.assertIn("beyond", result["reason"])

    def test_no_tasks_is_inconclusive(self):
        result = st.verdict(0, 0.0, -1.0, 1.0, 0.05)
        self.assertEqual(result["verdict"], "inconclusive")

    def test_tasks_needed_is_always_more_than_now(self):
        self.assertEqual(st.tasks_needed(40, 0.0, -0.05, 0.05, 0.05), 41)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_bench_stats.py" 2>&1 | tail -4`
Expected: ERROR, `ImportError: cannot import name 'bench_stats'`.

- [ ] **Step 3: Write the implementation**

`servers/mcp-fixer/src/mcp_fixer/bench_stats.py`:

```python
"""Statistics and the verdict for the benchmark. Pure; standard library only."""
import math
import random

Z = 1.959963984540054  # 95% two-sided
MIN_TASKS = 30


def wilson(correct, total):
    """The 95% Wilson score interval for `correct` out of `total`; (0, 1) when there is no data."""
    if total <= 0:
        return (0.0, 1.0)
    p = correct / total
    denominator = 1 + Z * Z / total
    centre = (p + Z * Z / (2 * total)) / denominator
    half = Z * math.sqrt(p * (1 - p) / total + Z * Z / (4 * total * total)) / denominator
    return (max(0.0, centre - half), min(1.0, centre + half))


def paired_bootstrap(diffs, seed=0, resamples=2000):
    """(mean, low, high): the mean of `diffs` and a 95% percentile interval from a seeded bootstrap."""
    n = len(diffs)
    if n == 0:
        return (0.0, -1.0, 1.0)
    mean = sum(diffs) / n
    rng = random.Random(seed)
    means = sorted(
        sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(resamples)
    )
    low_index = int(0.025 * resamples)
    high_index = max(low_index, int(0.975 * resamples) - 1)
    return (mean, means[low_index], means[high_index])


def tasks_needed(n, mean, low, high, tolerance):
    """About how many tasks it would take for the interval's lower bound to clear the tolerance.

    None when the observed difference is itself at or beyond the tolerance (more tasks would not
    help) or the interval has no width to scale.
    """
    margin = mean + tolerance
    half = (high - low) / 2
    if margin <= 0 or half <= 0:
        return None
    return max(math.ceil(n * (half / margin) ** 2), n + 1)


def verdict(n, mean, low, high, tolerance, min_tasks=MIN_TASKS):
    """{"verdict", "reason", "tasksNeeded"} for a paired comparison over `n` tasks."""
    if n > 0 and high < 0:
        return {
            "verdict": "worse",
            "reason": "the patched list picked the right tool less often: the whole interval is below zero",
            "tasksNeeded": None,
        }
    if n >= min_tasks and low > -tolerance:
        return {
            "verdict": "no drop detected",
            "reason": f"the interval's lower bound ({low:+.3f}) is within the {tolerance} tolerance",
            "tasksNeeded": None,
        }
    if n < min_tasks:
        return {
            "verdict": "inconclusive",
            "reason": f"only {n} usable tasks; at least {min_tasks} are needed (add at least {min_tasks - n} more)",
            "tasksNeeded": None,
        }
    needed = tasks_needed(n, mean, low, high, tolerance)
    if needed is None:
        reason = (
            f"the observed difference ({mean:+.3f}) is already at or beyond the {tolerance} tolerance, "
            "and more tasks would not change that"
        )
    else:
        reason = (
            f"the interval ({low:+.3f} to {high:+.3f}) is too wide to rule out a drop of {tolerance}; "
            f"about {needed} tasks would be needed at this spread"
        )
    return {"verdict": "inconclusive", "reason": reason, "tasksNeeded": needed}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -4`
Expected: all PASS. If `test_the_tolerance_edge_is_exclusive` fails on `-0.05 > -0.05`, the arithmetic is exact in binary floating point for this pair (both are the same literal); investigate rather than changing the comparison.

- [ ] **Step 5: Commit**

```bash
python -m unittest discover -s tests 2>&1 | tail -2
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer benchmark statistics and verdict

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: The runners

**Files:**
- Create: `servers/mcp-fixer/src/mcp_fixer/runners.py`, `servers/mcp-fixer/tests/fake_claude.py`, `servers/mcp-fixer/tests/test_runners.py`

**Interfaces:**
- Consumes: `stdio_client.resolve_command`, `_spawn`, `_kill_tree`, `child_environment`, `ClientError` (existing).
- Produces: `RunnerError`; `FakeRunner(function, label="fake")`; `ClaudeRunner(model=None, timeout=120, command=("claude",))`; `ApiRunner(model, api_key, timeout=120, max_tokens=64, url=ApiRunner.URL)`; `make_runner(name, model=None, env=None, timeout=120, max_tokens=64)`; all with `complete(prompt) -> str` and `describe() -> str`. Used by Tasks 4 and 5.

- [ ] **Step 1: Write the stand-in executable**

`servers/mcp-fixer/tests/fake_claude.py`:

```python
"""A stand-in for `claude -p` in the runner tests. The behavior is chosen with --mode; every
other argument is recorded (they are what the runner passed) together with stdin."""
import argparse
import json
import os
import sys
import time

parser = argparse.ArgumentParser(allow_abbrev=False)
parser.add_argument("--mode", default="ok")
parser.add_argument("--record")
parser.add_argument("--pid-file")
args, rest = parser.parse_known_args()

prompt = sys.stdin.buffer.read().decode("utf-8")
if args.record:
    with open(args.record, "w", encoding="utf-8") as handle:
        json.dump({"argv": rest, "stdin": prompt}, handle)
if args.pid_file:
    with open(args.pid_file, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))

if args.mode == "fail":
    sys.stderr.write("boom happened\nsecond line\n")
    sys.exit(3)
if args.mode == "hang":
    time.sleep(60)
if args.mode == "huge":
    sys.stdout.write("x" * 1000000)
    sys.exit(0)
if args.mode == "badbytes":
    sys.stdout.buffer.write(b'{"tool": "get_item"} \xff\xfe')
    sys.exit(0)
sys.stdout.write('{"tool": "get_item"}\n')
```

- [ ] **Step 2: Write the failing tests**

`servers/mcp-fixer/tests/test_runners.py`:

```python
import http.server
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import support
from mcp_fixer import runners
from mcp_fixer.runners import RunnerError

FAKE_CLAUDE = Path(support.TESTS) / "fake_claude.py"
KEY = "sk-test-secret-key-123"


class FakeRunnerTests(unittest.TestCase):
    def test_it_calls_the_function(self):
        runner = runners.FakeRunner(lambda prompt: prompt.upper(), "label")
        self.assertEqual(runner.complete("abc"), "ABC")
        self.assertEqual(runner.describe(), "label")


class ClaudeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def runner(self, mode="ok", *extra, model=None, timeout=30):
        command = (sys.executable, str(FAKE_CLAUDE), "--mode", mode, *extra)
        return runners.ClaudeRunner(model=model, timeout=timeout, command=command)

    def test_it_passes_the_flags_and_the_prompt_on_stdin(self):
        record = self.dir / "rec.json"
        reply = self.runner("ok", "--record", str(record)).complete("pick one \u00e9\u65e5")
        self.assertIn("get_item", reply)
        seen = json.loads(record.read_text(encoding="utf-8"))
        self.assertEqual(seen["argv"], ["-p", "--tools", "", "--no-session-persistence"])
        self.assertEqual(seen["stdin"], "pick one \u00e9\u65e5")

    def test_a_model_is_passed_through(self):
        record = self.dir / "rec.json"
        self.runner("ok", "--record", str(record), model="some-model").complete("x")
        argv = json.loads(record.read_text(encoding="utf-8"))["argv"]
        self.assertEqual(argv[-2:], ["--model", "some-model"])

    def test_a_failing_run_is_a_one_line_error_with_the_first_stderr_line(self):
        with self.assertRaises(RunnerError) as ctx:
            self.runner("fail").complete("x")
        message = str(ctx.exception)
        self.assertIn("code 3", message)
        self.assertIn("boom happened", message)
        self.assertNotIn("second line", message)
        self.assertNotIn("\n", message)

    def test_a_hanging_run_times_out_and_the_process_is_stopped(self):
        pid_file = self.dir / "pid"
        started = time.monotonic()
        with self.assertRaises(RunnerError) as ctx:
            self.runner("hang", "--pid-file", str(pid_file), timeout=1).complete("x")
        self.assertIn("timed out", str(ctx.exception))
        self.assertLess(time.monotonic() - started, 20)
        self.assertTrue(support.wait_until_gone(int(pid_file.read_text())))

    def test_huge_output_is_capped(self):
        self.assertLessEqual(len(self.runner("huge").complete("x")), 200000)

    def test_bytes_that_are_not_utf8_do_not_crash(self):
        self.assertIn("get_item", self.runner("badbytes").complete("x"))

    def test_a_missing_executable_is_a_clear_error(self):
        runner = runners.ClaudeRunner(command=("definitely-not-a-real-command-xyz",))
        with self.assertRaises(RunnerError) as ctx:
            runner.complete("x")
        self.assertIn("cannot find", str(ctx.exception))

    def test_describe_names_the_model(self):
        self.assertIn("some-model", runners.ClaudeRunner(model="some-model").describe())
        self.assertIn("claude", runners.ClaudeRunner().describe())


class _Handler(http.server.BaseHTTPRequestHandler):
    log = []

    def log_message(self, *args):
        pass

    def _send(self, status, body):
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        _Handler.log.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
        if self.path == "/ok":
            self._send(200, {"content": [{"type": "text", "text": '{"tool": '}, {"type": "text", "text": '"get_item"}'}]})
        elif self.path == "/401":
            self._send(401, {"error": {"type": "authentication_error", "message": "invalid x-api-key: " + KEY}})
        elif self.path == "/500":
            self._send(500, {"error": {"message": "overloaded"}})
        elif self.path == "/badbody":
            self._send(200, b"not json at all")
        elif self.path == "/shape":
            self._send(200, {"content": "nope"})
        elif self.path == "/slow":
            time.sleep(3)
            self._send(200, {"content": [{"type": "text", "text": "late"}]})


class ApiRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def runner(self, path, timeout=10, max_tokens=64):
        return runners.ApiRunner("some-model", KEY, timeout, max_tokens, url=f"http://127.0.0.1:{self.port}{path}")

    def test_a_good_reply_is_the_joined_text_blocks(self):
        self.assertEqual(self.runner("/ok").complete("pick"), '{"tool": "get_item"}')

    def test_the_request_is_deterministic_and_has_no_tools(self):
        _Handler.log.clear()
        self.runner("/ok", max_tokens=1024).complete("pick one")
        path, headers, body = _Handler.log[-1]
        self.assertEqual(headers["x-api-key"], KEY)
        self.assertIn("anthropic-version", headers)
        self.assertEqual(body["model"], "some-model")
        self.assertEqual(body["temperature"], 0)
        self.assertEqual(body["max_tokens"], 1024)
        self.assertEqual(body["messages"], [{"role": "user", "content": "pick one"}])
        self.assertNotIn("tools", body)

    def test_errors_are_one_line_and_never_contain_the_key(self):
        cases = {"/401": "401", "/500": "500", "/badbody": "unexpected", "/shape": "unexpected"}
        for path, fragment in cases.items():
            with self.subTest(path):
                with self.assertRaises(RunnerError) as ctx:
                    self.runner(path).complete("x")
                message = str(ctx.exception)
                self.assertIn(fragment, message)
                self.assertNotIn(KEY, message)
                self.assertNotIn("\n", message)

    def test_a_slow_server_times_out(self):
        with self.assertRaises(RunnerError) as ctx:
            self.runner("/slow", timeout=0.5).complete("x")
        self.assertIn("timed out", str(ctx.exception))

    def test_a_connection_refusal_is_a_runner_error_without_the_key(self):
        runner = runners.ApiRunner("m", KEY, 2, url="http://127.0.0.1:1/ok")
        with self.assertRaises(RunnerError) as ctx:
            runner.complete("x")
        self.assertNotIn(KEY, str(ctx.exception))

    def test_describe_never_includes_the_key(self):
        self.assertNotIn(KEY, self.runner("/ok").describe())
        self.assertIn("some-model", self.runner("/ok").describe())


class MakeRunnerTests(unittest.TestCase):
    def test_the_claude_runner_needs_no_key(self):
        runner = runners.make_runner("claude", "m")
        self.assertIsInstance(runner, runners.ClaudeRunner)

    def test_the_api_runner_needs_the_key_before_any_call(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with self.assertRaises(RunnerError) as ctx:
                runners.make_runner("api", None)
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))

    def test_the_api_runner_reads_the_key_and_has_a_default_model(self):
        runner = runners.make_runner("api", None, env={"ANTHROPIC_API_KEY": KEY}, max_tokens=1024)
        self.assertIsInstance(runner, runners.ApiRunner)
        self.assertIn("claude-sonnet-5-5", runner.describe())

    def test_an_unknown_runner_is_an_error(self):
        with self.assertRaises(RunnerError):
            runners.make_runner("nope", None)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_runners.py" 2>&1 | tail -4`
Expected: ERROR, `ImportError: cannot import name 'runners' from 'mcp_fixer'`.

- [ ] **Step 4: Write the implementation**

`servers/mcp-fixer/src/mcp_fixer/runners.py`:

```python
"""Ways to ask a model a question: `claude -p`, the Anthropic API, and a test double."""
import http.client
import json
import os
import subprocess
import urllib.error
import urllib.request

from .stdio_client import ClientError, _kill_tree, _spawn, child_environment, resolve_command

MAX_OUTPUT_CHARS = 200000
DEFAULT_API_MODEL = "claude-sonnet-5-5"


class RunnerError(Exception):
    """A model call failed; the message is one line and never contains a secret."""


def _one_line(text, limit=200):
    return " ".join(str(text).split())[:limit]


class FakeRunner:
    """Calls a function instead of a model (for tests)."""

    def __init__(self, function, label="fake"):
        self.function = function
        self.label = label

    def complete(self, prompt):
        return self.function(prompt)

    def describe(self):
        return self.label


class ClaudeRunner:
    """Runs `claude -p` with no tools and no saved session; the prompt goes on stdin."""

    def __init__(self, model=None, timeout=120, command=("claude",)):
        self.model = model
        self.timeout = timeout
        self.command = tuple(command)

    def describe(self):
        return f"claude -p ({self.model or 'default model'})"

    def complete(self, prompt):
        argv = list(self.command) + ["-p", "--tools", "", "--no-session-persistence"]
        if self.model:
            argv += ["--model", self.model]
        try:
            proc = _spawn(resolve_command(argv), child_environment(inherit=True))
        except ClientError as exc:
            raise RunnerError(str(exc)) from None
        try:
            out, err = proc.communicate(prompt.encode("utf-8"), timeout=self.timeout)
        except subprocess.TimeoutExpired:
            _kill_tree(proc, graceful=False)
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            raise RunnerError(f"claude timed out after {self.timeout} seconds") from None
        except OSError as exc:
            _kill_tree(proc, graceful=False)
            raise RunnerError(f"claude failed: {exc.strerror or exc}") from None
        if proc.returncode != 0:
            lines = err.decode("utf-8", errors="replace").strip().splitlines()
            detail = f": {_one_line(lines[0])}" if lines else ""
            raise RunnerError(f"claude exited with code {proc.returncode}{detail}")
        return out.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]


class ApiRunner:
    """One POST to the Messages API per call, with the standard library only."""

    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self, model, api_key, timeout=120, max_tokens=64, url=URL):
        self.model = model
        self._key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.url = url

    def describe(self):
        return f"Anthropic API ({self.model})"

    def _redact(self, text):
        return _one_line(str(text).replace(self._key, "[key]")) if self._key else _one_line(text)

    def complete(self, prompt):
        body = json.dumps(
            {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={
                "x-api-key": self._key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(2000000)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                parsed = json.loads(exc.read(4000).decode("utf-8", errors="replace"))
                detail = parsed["error"]["message"]
            except (ValueError, KeyError, TypeError, OSError):
                detail = exc.reason
            raise RunnerError(f"API error {exc.code}: {self._redact(detail)}") from None
        except TimeoutError:
            raise RunnerError(f"the API call timed out after {self.timeout} seconds") from None
        except (urllib.error.URLError, OSError, http.client.HTTPException, ValueError) as exc:
            reason = getattr(exc, "reason", exc)
            if "timed out" in str(reason):
                raise RunnerError(f"the API call timed out after {self.timeout} seconds") from None
            raise RunnerError(f"network error: {self._redact(reason)}") from None
        try:
            blocks = json.loads(raw.decode("utf-8"))["content"]
            texts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        except (ValueError, KeyError, TypeError):
            raise RunnerError("unexpected API response") from None
        if not texts:
            raise RunnerError("unexpected API response")
        return "".join(texts)[:MAX_OUTPUT_CHARS]


def make_runner(name, model=None, env=None, timeout=120, max_tokens=64):
    """The runner called `name` ("claude" or "api"). The api runner needs ANTHROPIC_API_KEY."""
    if name == "claude":
        return ClaudeRunner(model=model, timeout=timeout)
    if name == "api":
        key = (env if env is not None else os.environ).get("ANTHROPIC_API_KEY")
        if not key:
            raise RunnerError("ANTHROPIC_API_KEY is not set; the api runner needs it")
        return ApiRunner(model or DEFAULT_API_MODEL, key, timeout, max_tokens)
    raise RunnerError(f"unknown runner {name!r}")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_runners.py" -v 2>&1 | tail -30`
Expected: all PASS. Likely snags: (a) the timeout test hangs on Windows when the stand-in's pipes stay open: `_kill_tree` uses `taskkill /T`, which stops the whole tree, so `communicate(timeout=5)` returns; (b) `test_a_slow_server_times_out`: on some Python builds the timeout surfaces as `URLError(timeout('timed out'))`, which the second except clause maps to the same message, so both paths give "timed out".

- [ ] **Step 6: Commit**

```bash
python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -3
python -m unittest discover -s tests 2>&1 | tail -2
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer benchmark runners (claude -p, Anthropic API, test double)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Tasks file, patched view and the benchmark

**Files:**
- Create: `servers/mcp-fixer/src/mcp_fixer/bench.py`, `servers/mcp-fixer/tests/test_bench.py`

**Interfaces:**
- Consumes: `bench_prompts` (Task 1), `bench_stats` (Task 2), `runners.RunnerError`/`FakeRunner` (Task 3), `wrap.Router`, `patch_format.fingerprint`, `score.score_tools`, `report._safe`.
- Produces:
  - `BenchError`, `TasksError(BenchError)`.
  - `valid_tools(tools) -> list`; `tools_fingerprint(tools) -> str`.
  - `validate_tasks(data) -> data`; `load_tasks(path) -> dict`; `render_tasks(data) -> str`; `generate_tasks(tools, runner, per_tool, source=None, log=None) -> dict`.
  - `check_tasks(data, tools) -> [warning, ...]` (raises `BenchError`); `estimate_calls(data, repeats) -> int`; `estimate_input_tokens(data, tools, patch, repeats) -> int`.
  - `patched_view(original, patch) -> (patched_tools, rename_back, warnings)`.
  - `run_bench(tasks_data, tools, patch, runner, repeats=3, seed=0, tolerance=0.05) -> report dict`.
  - `render_bench_text(report) -> str`; `render_bench_json(report) -> str`; `DISCLAIMER`.
  Used by Task 5.

- [ ] **Step 1: Write the failing tests**

`servers/mcp-fixer/tests/test_bench.py`:

```python
import json
import re
import tempfile
import unittest
from pathlib import Path

import support  # noqa: F401
from mcp_fixer import bench, patch_format
from mcp_fixer.runners import FakeRunner, RunnerError

TOOLS = [
    {"name": "run", "description": "Runs it", "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}}},
    {"name": "search_items", "description": "Search the item catalog by keyword", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_item", "description": "Fetch one item by id", "inputSchema": {"type": "object", "properties": {}}},
]
MARK = "PATCHED-DESC"
PATCH = {
    "patchVersion": 1,
    "tools": {
        "run": {
            "base": patch_format.fingerprint(TOOLS[0]),
            "rename": "search_orders",
            "description": "Search orders by status " + MARK,
        }
    },
}
NAMES = [t["name"] for t in TOOLS]


def make_tasks(count=30):
    tasks = [
        {"id": f"t{i:03d}", "request": f"need-{i}", "expected": NAMES[i % 3]}
        for i in range(count)
    ]
    return {"tasksVersion": 1, "tasks": tasks}


def expected_for(prompt):
    request = re.search(r"User request: (need-\d+)", prompt).group(1)
    index = int(request.split("-")[1])
    return NAMES[index % 3]


def shown_names(prompt):
    return re.findall(r"^- (\S+?)(?::|$)", prompt, re.MULTILINE)


def right_answer(prompt):
    """The correct tool, under whatever name this prompt shows for it."""
    expected = expected_for(prompt)
    shown = shown_names(prompt)
    if expected not in shown and expected == "run":
        expected = "search_orders"
    return json.dumps({"tool": expected})


class ValidateTasksTests(unittest.TestCase):
    def assert_invalid(self, data, fragment):
        with self.assertRaises(bench.TasksError) as ctx:
            bench.validate_tasks(data)
        self.assertIn(fragment, str(ctx.exception))
        self.assertNotIn("\n", str(ctx.exception))

    def test_a_valid_file_passes(self):
        data = make_tasks(2)
        data["source"] = {"serverName": "s"}
        self.assertIs(bench.validate_tasks(data), data)

    def test_problems(self):
        good = make_tasks(1)["tasks"][0]
        cases = [
            ([], "must be a JSON object"),
            ({"tasksVersion": 1, "tasks": [good], "x": 1}, "unknown field 'x'"),
            ({"tasksVersion": 2, "tasks": [good]}, "tasksVersion must be 1"),
            ({"tasksVersion": True, "tasks": [good]}, "tasksVersion must be 1"),
            ({"tasksVersion": 1, "tasks": []}, "tasks must be a non-empty list"),
            ({"tasksVersion": 1}, "tasks must be a non-empty list"),
            ({"tasksVersion": 1, "tasks": [good], "source": []}, "source must be an object"),
            ({"tasksVersion": 1, "tasks": ["x"]}, "task 0: must be an object"),
            ({"tasksVersion": 1, "tasks": [dict(good, extra=1)]}, "task 0: unknown field 'extra'"),
            ({"tasksVersion": 1, "tasks": [dict(good, request="  ")]}, "task 0: request must be a non-empty string"),
            ({"tasksVersion": 1, "tasks": [dict(good, id=5)]}, "task 0: id must be a non-empty string"),
            ({"tasksVersion": 1, "tasks": [dict(good, expected="")]}, "task 0: expected must be a non-empty string"),
            ({"tasksVersion": 1, "tasks": [good, good]}, "task 1: duplicate id"),
        ]
        for data, fragment in cases:
            with self.subTest(fragment):
                self.assert_invalid(data, fragment)

    def test_load_tasks_gives_one_line_errors_with_the_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "bad.json").write_text("{nope", encoding="utf-8")
            (root / "deep.json").write_text("[" * 5000, encoding="utf-8")
            (root / "bytes.json").write_bytes(b"\x80\x81")
            (root / "ok.json").write_text(json.dumps(make_tasks(1)), encoding="utf-8")
            cases = {"nope.json": "cannot read", "bad.json": "not valid JSON", "deep.json": "nested too deeply", "bytes.json": "not UTF-8"}
            for name, fragment in cases.items():
                with self.subTest(name):
                    with self.assertRaises(bench.TasksError) as ctx:
                        bench.load_tasks(str(root / name))
                    self.assertIn(fragment, str(ctx.exception))
                    self.assertIn(name, str(ctx.exception))
                    self.assertNotIn("\n", str(ctx.exception))
            self.assertEqual(len(bench.load_tasks(str(root / "ok.json"))["tasks"]), 1)


class ToolsTests(unittest.TestCase):
    def test_valid_tools_keeps_the_first_of_each_name(self):
        tools = ["junk", {"name": ""}, {"name": "a", "description": "first"}, {"name": "a", "description": "second"}, {"name": "b"}]
        self.assertEqual(bench.valid_tools(tools), [{"name": "a", "description": "first"}, {"name": "b"}])

    def test_the_fingerprint_ignores_junk_and_duplicates(self):
        self.assertEqual(
            bench.tools_fingerprint(TOOLS),
            bench.tools_fingerprint(["junk"] + TOOLS + [dict(TOOLS[0], description="dup")]),
        )

    def test_check_tasks(self):
        self.assertEqual(bench.check_tasks(make_tasks(3), TOOLS), [])
        data = make_tasks(2)
        data["source"] = {"toolsFingerprint": "0" * 64}
        warnings = bench.check_tasks(data, TOOLS)
        self.assertEqual(len(warnings), 1)
        self.assertIn("different tools", warnings[0])
        data = make_tasks(2)
        data["tasks"][1]["expected"] = "ghost"
        with self.assertRaises(bench.BenchError) as ctx:
            bench.check_tasks(data, TOOLS)
        self.assertIn("'t001' expects 'ghost'", str(ctx.exception))
        with self.assertRaises(bench.BenchError):
            bench.check_tasks(make_tasks(1), ["junk"])

    def test_control_characters_in_error_messages_are_escaped(self):
        data = make_tasks(1)
        data["tasks"][0]["expected"] = "ghost\x1b[2J"
        with self.assertRaises(bench.BenchError) as ctx:
            bench.check_tasks(data, TOOLS)
        self.assertNotIn("\x1b", str(ctx.exception))


class PatchedViewTests(unittest.TestCase):
    def test_the_patch_is_applied_the_way_wrap_does(self):
        patched, back, warnings = bench.patched_view(TOOLS, PATCH)
        self.assertEqual([t["name"] for t in patched], ["search_orders", "search_items", "get_item"])
        self.assertIn(MARK, patched[0]["description"])
        self.assertEqual(back, {"search_orders": "run"})
        self.assertEqual(warnings, [])

    def test_a_stale_entry_is_not_applied(self):
        stale = json.loads(json.dumps(PATCH))
        stale["tools"]["run"]["base"] = "0" * 64
        patched, back, warnings = bench.patched_view(TOOLS, stale)
        self.assertEqual(patched, TOOLS)
        self.assertEqual(back, {})
        self.assertEqual(len(warnings), 1)

    def test_an_empty_patch_changes_nothing(self):
        patched, back, _ = bench.patched_view(TOOLS, {"patchVersion": 1, "tools": {}})
        self.assertEqual((patched, back), (TOOLS, {}))


class RunBenchTests(unittest.TestCase):
    def run_bench(self, function, tasks=None, patch=PATCH, repeats=1, seed=0, tolerance=0.05):
        runner = FakeRunner(function, "fake")
        return bench.run_bench(tasks or make_tasks(), TOOLS, patch, runner, repeats, seed, tolerance)

    def test_a_runner_that_is_always_right_shows_no_drop(self):
        report = self.run_bench(right_answer)
        self.assertEqual(report["original"]["accuracy"], 1.0)
        self.assertEqual(report["patched"]["accuracy"], 1.0)
        self.assertEqual(report["verdict"]["verdict"], "no drop detected")
        self.assertEqual(report["paired"]["mean"], 0.0)
        self.assertEqual(report["modelCalls"], 60)
        self.assertEqual(report["patch"], {"entries": 1, "applied": 1, "stale": 0, "missing": 0})

    def test_the_renamed_tool_answer_is_mapped_back(self):
        # Every third task expects `run`; the patched side names it search_orders.
        report = self.run_bench(right_answer)
        self.assertEqual(report["patched"]["wrong"], 0)

    def test_a_runner_that_fails_on_the_patched_list_is_worse(self):
        def answer(prompt):
            return '{"tool": "get_item"}' if MARK in prompt and expected_for(prompt) != "get_item" else right_answer(prompt)

        report = self.run_bench(answer)
        self.assertEqual(report["verdict"]["verdict"], "worse")
        self.assertLess(report["patched"]["accuracy"], report["original"]["accuracy"])
        self.assertLess(report["paired"]["high"], 0)

    def test_a_stale_patch_is_counted_and_not_applied(self):
        stale = json.loads(json.dumps(PATCH))
        stale["tools"]["run"]["base"] = "0" * 64
        prompts = []
        report = self.run_bench(lambda p: (prompts.append(p), right_answer(p))[1], patch=stale)
        self.assertEqual(report["patch"]["stale"], 1)
        self.assertEqual(report["patch"]["applied"], 0)
        self.assertFalse(any(MARK in p for p in prompts))

    def test_both_sides_see_the_same_order_and_it_is_seeded(self):
        def collect(seed):
            prompts = []
            self.run_bench(lambda p: (prompts.append(p), right_answer(p))[1], seed=seed, repeats=2)
            return prompts

        first = collect(0)
        self.assertEqual(first, collect(0))
        self.assertNotEqual(first, collect(1))
        for original, patched in zip(first[0::2], first[1::2]):
            order = [("run" if n == "search_orders" else n) for n in shown_names(patched)]
            self.assertEqual(order, shown_names(original))

    def test_invalid_replies_count_as_wrong_and_errored_are_excluded(self):
        calls = {"n": 0}

        def answer(prompt):
            if re.search(r"User request: need-0\b", prompt):
                return "I refuse to answer"
            if re.search(r"User request: need-1\b", prompt):
                raise RunnerError("boom")
            return right_answer(prompt)

        report = self.run_bench(answer)
        # need-0 invalid on both sides; need-1 errored on both sides (after the retry).
        self.assertEqual(report["original"]["invalid"], 1)
        self.assertEqual(report["original"]["errored"], 1)
        self.assertEqual(report["patched"]["invalid"], 1)
        self.assertEqual(report["patched"]["errored"], 1)
        scored = 30 - 1
        self.assertAlmostEqual(report["original"]["accuracy"], (scored - 1) / scored)
        self.assertEqual(report["usableTasks"], 29)
        self.assertEqual(report["droppedTasks"], 1)
        self.assertEqual(report["verdict"]["verdict"], "inconclusive")  # 29 usable tasks
        self.assertTrue(any("errored" in note for note in report["notes"]))
        # Each errored trial was tried twice: 60 trials + 2 retries.
        self.assertEqual(report["modelCalls"], 62)

    def test_a_failure_that_succeeds_on_the_retry_is_not_errored(self):
        seen = set()

        def answer(prompt):
            if prompt not in seen:
                seen.add(prompt)
                raise RunnerError("flaky")
            return right_answer(prompt)

        report = self.run_bench(answer)
        self.assertEqual(report["original"]["errored"], 0)
        self.assertEqual(report["modelCalls"], 120)

    def test_the_report_is_json_serializable_and_complete(self):
        report = self.run_bench(right_answer)
        data = json.loads(bench.render_bench_json(report))
        self.assertEqual(data["schemaVersion"], 1)
        for key in ("runner", "seed", "repeats", "tolerance", "tasks", "usableTasks", "original", "patched", "paired", "tokens", "patch", "verdict", "notes", "disclaimer"):
            self.assertIn(key, data)
        self.assertEqual(data["disclaimer"], bench.DISCLAIMER)
        self.assertIn("original", data["tokens"])

    def test_the_text_report_has_the_verdict_the_numbers_and_the_disclaimer(self):
        text = bench.render_bench_text(self.run_bench(right_answer))
        self.assertTrue(text.startswith("mcp-fixer bench: no drop detected"))
        self.assertIn("original", text)
        self.assertIn("patched", text)
        self.assertIn("paired difference", text)
        self.assertTrue(text.rstrip().endswith(bench.DISCLAIMER))

    def test_untrusted_text_is_escaped_in_the_text_report(self):
        evil = "evil\x1b[2J"
        tools = TOOLS + [{"name": evil, "description": "d", "inputSchema": {"type": "object", "properties": {}}}]
        patch = {"patchVersion": 1, "tools": {evil: {"params": {"ghost": {"type": "string"}}}}}
        runner = FakeRunner(right_answer)
        report = bench.run_bench(make_tasks(3), tools, patch, runner, 1, 0, 0.05)
        text = bench.render_bench_text(report)
        self.assertNotIn("\x1b", text)
        self.assertIn("evil", text)

    def test_estimates(self):
        self.assertEqual(bench.estimate_calls(make_tasks(10), 3), 60)
        self.assertGreater(bench.estimate_input_tokens(make_tasks(10), TOOLS, PATCH, 3), 0)


class GenerateTasksTests(unittest.TestCase):
    WORDS = {"search_items": "alpha", "get_item": "beta", "run": "gamma"}

    def reply(self, prompt):
        target = re.search(r'need the tool "([^"]+)"', prompt).group(1)
        word = self.WORDS[target]
        return json.dumps([f"{word} thing one", f"{word} thing two", f"{word} thing one"])

    def test_tasks_are_generated_per_tool_in_order(self):
        logs = []
        data = bench.generate_tasks(TOOLS, FakeRunner(self.reply), 3, None, logs.append)
        bench.validate_tasks(data)
        ids = [t["id"] for t in data["tasks"]]
        self.assertEqual(ids, [f"t{i:03d}" for i in range(1, 7)])
        self.assertEqual([t["expected"] for t in data["tasks"]], ["run", "run", "search_items", "search_items", "get_item", "get_item"])
        self.assertEqual(data["source"]["toolsFingerprint"], bench.tools_fingerprint(TOOLS))
        self.assertEqual(logs, [])

    def test_requests_that_name_the_tool_are_dropped(self):
        def reply(prompt):
            return json.dumps(["please use get item now", "find the beta thing"])

        data = bench.generate_tasks([TOOLS[2]], FakeRunner(reply), 3, None, lambda t: None)
        self.assertEqual([t["request"] for t in data["tasks"]], ["find the beta thing"])

    def test_a_tool_with_an_unusable_reply_is_skipped_with_a_warning(self):
        def reply(prompt):
            return "nonsense" if 'need the tool "get_item"' in prompt else self.reply(prompt)

        logs = []
        data = bench.generate_tasks(TOOLS, FakeRunner(reply), 3, None, logs.append)
        self.assertNotIn("get_item", [t["expected"] for t in data["tasks"]])
        self.assertEqual(len(logs), 1)
        self.assertIn("get_item", logs[0])

    def test_a_runner_failure_is_retried_once_then_the_tool_is_skipped(self):
        attempts = []

        def reply(prompt):
            if 'need the tool "run"' in prompt:
                attempts.append(1)
                raise RunnerError("boom")
            return self.reply(prompt)

        logs = []
        data = bench.generate_tasks(TOOLS, FakeRunner(reply), 3, None, logs.append)
        self.assertEqual(len(attempts), 2)
        self.assertNotIn("run", [t["expected"] for t in data["tasks"]])
        self.assertTrue(any("run" in line and "boom" in line for line in logs))

    def test_no_tasks_at_all_is_an_error(self):
        with self.assertRaises(bench.TasksError):
            bench.generate_tasks(TOOLS, FakeRunner(lambda p: "nonsense"), 3, None, lambda t: None)
        with self.assertRaises(bench.TasksError):
            bench.generate_tasks(["junk"], FakeRunner(self.reply), 3, None, lambda t: None)

    def test_only_the_per_tool_count_is_kept(self):
        data = bench.generate_tasks([TOOLS[1]], FakeRunner(self.reply), 1, None, lambda t: None)
        self.assertEqual(len(data["tasks"]), 1)

    def test_a_stdio_source_is_recorded(self):
        source = {"kind": "stdio", "serverName": "s", "serverVersion": "1"}
        data = bench.generate_tasks(TOOLS, FakeRunner(self.reply), 2, source, lambda t: None)
        self.assertEqual(data["source"]["serverName"], "s")
        self.assertEqual(data["source"]["serverVersion"], "1")

    def test_output_is_deterministic(self):
        a = bench.render_tasks(bench.generate_tasks(TOOLS, FakeRunner(self.reply), 2, None, lambda t: None))
        b = bench.render_tasks(bench.generate_tasks(TOOLS, FakeRunner(self.reply), 2, None, lambda t: None))
        self.assertEqual(a, b)
        self.assertTrue(a.endswith("}\n"))


if __name__ == "__main__":
    unittest.main()
```

Notes for the executor on the tests above: `test_both_sides_see_the_same_order_and_it_is_seeded` compares the shown order of each original-side prompt (even index) with the next prompt (patched side), mapping the renamed tool back. `shown_names` reads `- name:` lines from the prompt; parameter lines are indented so they do not match. `right_answer` replies `search_orders` when the prompt shows the renamed tool.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_bench.py" 2>&1 | tail -4`
Expected: ERROR, `ImportError: cannot import name 'bench' from 'mcp_fixer'`.

- [ ] **Step 3: Write the implementation**

`servers/mcp-fixer/src/mcp_fixer/bench.py`:

```python
"""The benchmark: tasks file, patched view, trials and the report. Standard library only."""
import json
import math
import random
from pathlib import Path

from . import bench_prompts, bench_stats, patch_format
from .report import _safe
from .runners import RunnerError
from .score import score_tools
from .wrap import Router

TASKS_VERSION = 1
DISCLAIMER = (
    "This measures whether a drop could be detected on these generated tasks; "
    "it does not show the patch improves tool selection."
)
_MAX_NOTE = 300


class BenchError(Exception):
    """A problem with the benchmark's inputs, reported as one line."""


class TasksError(BenchError):
    """A problem with the tasks file or with generating it."""


def _clip(text):
    text = _safe(text)
    return text if len(text) <= _MAX_NOTE else text[: _MAX_NOTE - 1] + "\u2026"


# --- tools -------------------------------------------------------------------------------------
def valid_tools(tools):
    """The first tool dict with a non-empty string name for each name."""
    seen = set()
    out = []
    for tool in tools:
        if isinstance(tool, dict) and isinstance(tool.get("name"), str) and tool["name"]:
            if tool["name"] not in seen:
                seen.add(tool["name"])
                out.append(tool)
    return out


def tools_fingerprint(tools):
    return patch_format.fingerprint(valid_tools(tools))


# --- the tasks file ----------------------------------------------------------------------------
def validate_tasks(data):
    if not isinstance(data, dict):
        raise TasksError("the tasks file must be a JSON object")
    for key in data:
        if key not in ("tasksVersion", "source", "tasks"):
            raise TasksError(f"unknown field {_clip(repr(key))} in the tasks file")
    if type(data.get("tasksVersion")) is not int or data["tasksVersion"] != TASKS_VERSION:
        raise TasksError(f"tasksVersion must be {TASKS_VERSION}")
    if "source" in data and not isinstance(data["source"], dict):
        raise TasksError("source must be an object")
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise TasksError("tasks must be a non-empty list")
    seen = set()
    for index, task in enumerate(tasks):
        where = f"task {index}"
        if not isinstance(task, dict):
            raise TasksError(f"{where}: must be an object")
        for key in task:
            if key not in ("id", "request", "expected"):
                raise TasksError(f"{where}: unknown field {_clip(repr(key))}")
        for key in ("id", "request", "expected"):
            if not (isinstance(task.get(key), str) and task[key].strip()):
                raise TasksError(f"{where}: {key} must be a non-empty string")
        if task["id"] in seen:
            raise TasksError(f"{where}: duplicate id {_clip(repr(task['id']))}")
        seen.add(task["id"])
    return data


def load_tasks(path):
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise TasksError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise TasksError(f"{path} is not UTF-8 text") from None
    try:
        data = json.loads(text)
    except RecursionError:
        raise TasksError(f"{path} is not valid JSON (nested too deeply)") from None
    except ValueError as exc:
        raise TasksError(f"{path} is not valid JSON ({exc})") from None
    try:
        return validate_tasks(data)
    except TasksError as exc:
        raise TasksError(f"{path}: {exc}") from None


def render_tasks(data):
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def check_tasks(data, tools):
    """Warnings about the tasks file; raises BenchError when a task cannot be scored."""
    names = {t["name"] for t in valid_tools(tools)}
    if not names:
        raise BenchError("the tool list has no usable tools")
    for task in data["tasks"]:
        if task["expected"] not in names:
            raise BenchError(
                f"task {_clip(repr(task['id']))} expects {_clip(repr(task['expected']))}, "
                "which is not a tool in the original list"
            )
    warnings = []
    wanted = data.get("source", {}).get("toolsFingerprint")
    if wanted is not None and wanted != tools_fingerprint(tools):
        warnings.append("the tasks were written for different tools than the ones being benchmarked")
    return warnings


def call_with_retry(runner, prompt):
    """(text, error, attempts): one retry after a RunnerError, then give up."""
    attempts = 0
    error = None
    for _ in range(2):
        attempts += 1
        try:
            return runner.complete(prompt), None, attempts
        except RunnerError as exc:
            error = str(exc)
    return None, error, attempts


def generate_tasks(tools, runner, per_tool, source=None, log=None):
    log = log or (lambda text: None)
    tools = valid_tools(tools)
    if not tools:
        raise TasksError("the tool list has no usable tools")
    tasks = []
    for tool in tools:
        name = tool["name"]
        text, error, _ = call_with_retry(runner, bench_prompts.tasks_prompt(tools, name, per_tool))
        if error is not None:
            log(f"tool {_clip(repr(name))}: the model call failed ({_clip(error)}); no tasks for it")
            continue
        requests = bench_prompts.parse_task_list(text)
        if requests is None:
            log(f"tool {_clip(repr(name))}: the reply had no list of requests; no tasks for it")
            continue
        kept = []
        for request in requests:
            if request not in kept and not bench_prompts.mentions_name(request, name):
                kept.append(request)
        if not kept:
            log(f"tool {_clip(repr(name))}: no usable requests (empty, repeated, or naming the tool)")
        for request in kept[:per_tool]:
            tasks.append({"id": f"t{len(tasks) + 1:03d}", "request": request, "expected": name})
    if not tasks:
        raise TasksError("no tasks could be generated")
    info = {"toolsFingerprint": tools_fingerprint(tools)}
    if source and source.get("kind") == "stdio":
        info = {
            "serverName": source.get("serverName"),
            "serverVersion": source.get("serverVersion"),
            **info,
        }
    return {"tasksVersion": TASKS_VERSION, "source": info, "tasks": tasks}


# --- the patched view --------------------------------------------------------------------------
def patched_view(original, patch):
    """(patched tools, rename map, warnings): the tool list as `wrap` would serve it."""
    warnings = []
    router = Router(patch, False, warnings.append)
    router.client_line(b'{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n')
    try:
        raw = (json.dumps({"jsonrpc": "2.0", "id": 1, "result": {"tools": original}}) + "\n").encode("ascii")
        out = router.server_line(raw)
        patched = json.loads(out.decode("utf-8"))["result"]["tools"]
    except (RecursionError, ValueError):
        raise BenchError("a tool is nested too deeply to benchmark") from None
    return patched, dict(router.rename_back), warnings


def _patch_info(original, patch):
    by_name = {t["name"]: t for t in original}
    stale = missing = 0
    for name, entry in patch["tools"].items():
        tool = by_name.get(name)
        if tool is None:
            missing += 1
        elif entry.get("base") is not None and entry["base"] != patch_format.fingerprint(tool):
            stale += 1
    entries = len(patch["tools"])
    return {"entries": entries, "applied": entries - stale - missing, "stale": stale, "missing": missing}


# --- estimates ---------------------------------------------------------------------------------
def estimate_calls(data, repeats):
    return len(data["tasks"]) * repeats * 2


def estimate_input_tokens(data, tools, patch, repeats):
    original = valid_tools(tools)
    patched, _, _ = patched_view(original, patch)
    total = 0
    for task in data["tasks"]:
        for listing in (original, patched):
            total += math.ceil(len(bench_prompts.trial_prompt(listing, task["request"])) / 4)
    return total * repeats


# --- trials ------------------------------------------------------------------------------------
def _order(count, seed, task_id, repeat):
    rng = random.Random(f"{seed}:{task_id}:{repeat}")
    order = list(range(count))
    rng.shuffle(order)
    return order


def _accuracy(outcomes):
    scored = [o for o in outcomes if o != "errored"]
    return None if not scored else sum(1 for o in scored if o == "correct") / len(scored)


def _side_summary(per_task):
    counts = {"correct": 0, "wrong": 0, "invalid": 0, "errored": 0}
    for outcomes in per_task.values():
        for outcome in outcomes:
            counts[outcome] += 1
    scored = counts["correct"] + counts["wrong"] + counts["invalid"]
    low, high = bench_stats.wilson(counts["correct"], scored)
    return {
        **counts,
        "accuracy": counts["correct"] / scored if scored else None,
        "interval": [low, high],
        "invalidRate": counts["invalid"] / scored if scored else None,
    }


def run_bench(tasks_data, tools, patch, runner, repeats=3, seed=0, tolerance=0.05):
    original = valid_tools(tools)
    patched, rename_back, patch_warnings = patched_view(original, patch)
    tasks = tasks_data["tasks"]
    per_task = {"original": {}, "patched": {}}
    calls = 0
    for task in tasks:
        for repeat in range(repeats):
            order = _order(len(original), seed, task["id"], repeat)
            for side, listing in (("original", original), ("patched", patched)):
                shown = [listing[i] for i in order]
                names = {t["name"] for t in shown}
                text, error, attempts = call_with_retry(
                    runner, bench_prompts.trial_prompt(shown, task["request"])
                )
                calls += attempts
                if error is not None:
                    outcome = "errored"
                else:
                    choice = bench_prompts.parse_choice(text, names)
                    if choice is None:
                        outcome = "invalid"
                    else:
                        if side == "patched":
                            choice = rename_back.get(choice, choice)
                        outcome = "correct" if choice == task["expected"] else "wrong"
                per_task[side].setdefault(task["id"], []).append(outcome)
    diffs = []
    for task in tasks:
        a_original = _accuracy(per_task["original"][task["id"]])
        a_patched = _accuracy(per_task["patched"][task["id"]])
        if a_original is not None and a_patched is not None:
            diffs.append(a_patched - a_original)
    mean, low, high = bench_stats.paired_bootstrap(diffs, seed)
    original_summary = _side_summary(per_task["original"])
    patched_summary = _side_summary(per_task["patched"])
    notes = [_clip(text) for text in patch_warnings]
    errored = original_summary["errored"] + patched_summary["errored"]
    if errored:
        notes.append(f"{errored} trials errored (the model call failed twice) and were excluded from accuracy")
    if len(diffs) < len(tasks):
        notes.append(f"{len(tasks) - len(diffs)} tasks had no scored repeat on one side and were dropped")
    return {
        "schemaVersion": 1,
        "runner": _clip(runner.describe()),
        "seed": seed,
        "repeats": repeats,
        "tolerance": tolerance,
        "tasks": len(tasks),
        "usableTasks": len(diffs),
        "droppedTasks": len(tasks) - len(diffs),
        "modelCalls": calls,
        "original": original_summary,
        "patched": patched_summary,
        "paired": {"mean": mean, "low": low, "high": high},
        "tokens": {
            "original": score_tools(original)["metrics"]["estimatedTokens"],
            "patched": score_tools(patched)["metrics"]["estimatedTokens"],
        },
        "patch": _patch_info(original, patch),
        "verdict": bench_stats.verdict(len(diffs), mean, low, high, tolerance),
        "notes": notes,
        "disclaimer": DISCLAIMER,
    }


# --- rendering ---------------------------------------------------------------------------------
def render_bench_json(report):
    return json.dumps(report, indent=2, ensure_ascii=True) + "\n"


def _pct(value):
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _row(label, side):
    low, high = side["interval"]
    return (
        f"{label:<10}{side['correct']:>8}{side['wrong']:>7}{side['invalid']:>9}{side['errored']:>9}"
        f"{_pct(side['accuracy']):>10}   [{_pct(low)}, {_pct(high)}]"
    )


def render_bench_text(report):
    verdict = report["verdict"]
    paired = report["paired"]
    tokens = report["tokens"]
    patch = report["patch"]
    lines = [
        f"mcp-fixer bench: {verdict['verdict']}",
        f"runner: {_clip(report['runner'])}, seed {report['seed']}, {report['repeats']} repeats, "
        f"tolerance {report['tolerance']}",
        f"tasks: {report['usableTasks']} usable of {report['tasks']} ({report['droppedTasks']} dropped); "
        f"model calls {report['modelCalls']}",
        "",
        f"{'':<10}{'correct':>8}{'wrong':>7}{'invalid':>9}{'errored':>9}{'accuracy':>10}   95% interval",
        _row("original", report["original"]),
        _row("patched", report["patched"]),
        "",
        f"paired difference (patched - original): {paired['mean'] * 100:+.1f} points, "
        f"95% interval [{paired['low'] * 100:+.1f}, {paired['high'] * 100:+.1f}]",
        f"tokens: original {tokens['original']} -> patched {tokens['patched']} "
        f"({tokens['patched'] - tokens['original']:+d})",
        f"patch: {patch['entries']} entries, {patch['applied']} applied, "
        f"{patch['stale']} stale, {patch['missing']} missing",
        "",
        f"verdict: {verdict['verdict']} - {_clip(verdict['reason'])}",
    ]
    for note in report["notes"]:
        lines.append(f"note: {_clip(note)}")
    lines += ["", report["disclaimer"]]
    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_bench.py" 2>&1 | tail -20`
Expected: all PASS. If `test_invalid_replies_count_as_wrong_and_errored_are_excluded` disagrees on call counts: `need-1` raises on both attempts for both sides, so each errored trial costs 2 calls (60 trials + 2 retries = 62), and `need-0`/`need-1` prompts also match `need-10`..`need-19` by substring; if the test's substring match catches `need-10` and friends, tighten the test to the regex used in `expected_for` (match `need-0\b`) rather than changing the implementation.

- [ ] **Step 5: Commit**

```bash
python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -3
python -m unittest discover -s tests 2>&1 | tail -2
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer benchmark core (tasks file, patched view, trials, report)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: The command line

**Files:**
- Modify: `servers/mcp-fixer/src/mcp_fixer/cli.py`, `servers/mcp-fixer/tests/test_cli.py` (append two classes)

**Interfaces:**
- Consumes: Task 4's `bench` functions, Task 3's `runners.make_runner`/`RunnerError`, the existing `read_tools`, `write_file`, `emit`, `UsageError`.
- Produces: `mcp-fixer tasks` and `mcp-fixer bench`.

- [ ] **Step 1: Write the failing tests**

Append to `servers/mcp-fixer/tests/test_cli.py` (before the `# A tools file for the fake server` marker; use the Edit tool). It already imports `contextlib, io, json, os, subprocess, sys, tempfile, unittest, Path, support, cli` and defines `run`, `CliCase`, `MESSY`, `CLEAN`, `CLEAN_TOOLS`. Add at the top of the file's imports: `import re` and `from unittest import mock`, and `from mcp_fixer import patch_format` and `from mcp_fixer.runners import FakeRunner, RunnerError` (skip any already present).

```python
BENCH_TOOLS = [
    {"name": "search_items", "description": "Search the item catalog by keyword", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_item", "description": "Fetch one item by id", "inputSchema": {"type": "object", "properties": {}}},
]
BENCH_MARK = "PATCHED-DESC"


def bench_patch():
    return {
        "patchVersion": 1,
        "tools": {"get_item": {"base": patch_format.fingerprint(BENCH_TOOLS[1]), "description": "Fetch one item " + BENCH_MARK}},
    }


def bench_tasks(count):
    return {
        "tasksVersion": 1,
        "tasks": [
            {"id": f"t{i:03d}", "request": f"need {BENCH_TOOLS[i % 2]['name']} {i}", "expected": BENCH_TOOLS[i % 2]["name"]}
            for i in range(count)
        ],
    }


def prompt_answer(prompt, break_patched=False):
    expected = re.search(r"User request: need (\S+) \d+", prompt).group(1)
    if break_patched and BENCH_MARK in prompt:
        return '{"tool": "nope"}'
    return json.dumps({"tool": expected})


class FakeFactory:
    """Stands in for runners.make_runner; counts the model calls."""

    def __init__(self, function):
        self.function = function
        self.calls = 0

    def __call__(self, name, model=None, env=None, timeout=120, max_tokens=64):
        def counted(prompt):
            self.calls += 1
            return self.function(prompt)

        return FakeRunner(counted, f"fake:{name}")


class TasksCommandTests(CliCase):
    WORDS = {"search_items": "alpha", "get_item": "beta"}

    def reply(self, prompt):
        target = re.search(r'need the tool "([^"]+)"', prompt).group(1)
        return json.dumps([f"{self.WORDS[target]} thing one", f"{self.WORDS[target]} thing two"])

    def tools_file(self):
        return self.write("tools.json", json.dumps(BENCH_TOOLS))

    def test_tasks_are_written_to_stdout_and_validate(self):
        factory = FakeFactory(self.reply)
        with mock.patch.object(cli, "make_runner", factory):
            code, out, err = run("tasks", "--tools-json", self.tools_file())
        self.assertEqual((code, err), (0, ""))
        from mcp_fixer import bench
        data = bench.validate_tasks(json.loads(out))
        self.assertEqual(len(data["tasks"]), 4)
        self.assertEqual(factory.calls, 2)

    def test_out_writes_a_file_and_an_existing_file_is_refused_before_any_call(self):
        target = self.dir / "tasks.json"
        target.write_text("my edits", encoding="utf-8")
        factory = FakeFactory(self.reply)
        with mock.patch.object(cli, "make_runner", factory):
            self.assert_usage_error("tasks", "--tools-json", self.tools_file(), "--out", str(target), fragment="exists; use --force")
        self.assertEqual(factory.calls, 0)
        self.assertEqual(target.read_text(encoding="utf-8"), "my edits")
        with mock.patch.object(cli, "make_runner", factory):
            code, out, _ = run("tasks", "--tools-json", self.tools_file(), "--out", str(target), "--force")
        self.assertEqual((code, out), (0, ""))
        self.assertIn('"tasksVersion"', target.read_text(encoding="utf-8"))

    def test_per_tool_bounds(self):
        for value in ("0", "11", "-1"):
            with self.subTest(value):
                self.assert_usage_error("tasks", "--tools-json", self.tools_file(), "--per-tool", value, fragment="--per-tool")

    def test_a_failed_tool_is_a_warning_and_no_tasks_is_an_error(self):
        def reply(prompt):
            return "nonsense" if 'need the tool "get_item"' in prompt else self.reply(prompt)

        with mock.patch.object(cli, "make_runner", FakeFactory(reply)):
            code, out, err = run("tasks", "--tools-json", self.tools_file())
        self.assertEqual(code, 0)
        self.assertEqual(err.count("get_item"), 1)
        with mock.patch.object(cli, "make_runner", FakeFactory(lambda p: "nonsense")):
            self.assert_usage_error("tasks", "--tools-json", self.tools_file(), fragment="no tasks could be generated")

    def test_a_missing_api_key_fails_before_any_call(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            self.assert_usage_error("tasks", "--tools-json", self.tools_file(), "--runner", "api", fragment="ANTHROPIC_API_KEY")

    def test_the_same_input_errors_as_patch(self):
        self.assert_usage_error("tasks", fragment="--tools-json")
        self.assert_usage_error("tasks", "--tools-json", str(self.dir / "nope.json"), fragment="cannot read")


class BenchCommandTests(CliCase):
    def files(self, tasks=None, patch=None, tools=None):
        return (
            self.write("tools.json", json.dumps(tools if tools is not None else BENCH_TOOLS)),
            self.write("patch.json", json.dumps(patch if patch is not None else bench_patch())),
            self.write("tasks.json", json.dumps(tasks if tasks is not None else bench_tasks(30))),
        )

    def bench(self, factory, *extra, **files):
        tools, patch, tasks = self.files(**files)
        with mock.patch.object(cli, "make_runner", factory):
            return run("bench", "--tasks", tasks, "--patch", patch, "--tools-json", tools, "--repeats", "1", *extra)

    def test_no_drop_is_exit_0_and_the_text_report(self):
        factory = FakeFactory(prompt_answer)
        code, out, err = self.bench(factory)
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("mcp-fixer bench: no drop detected"))
        self.assertEqual(factory.calls, 60)
        self.assertIn("60 model calls", err)

    def test_worse_is_exit_1(self):
        code, out, err = self.bench(FakeFactory(lambda p: prompt_answer(p, break_patched=True)))
        self.assertEqual(code, 1, err)
        self.assertTrue(out.startswith("mcp-fixer bench: worse"))

    def test_too_few_tasks_is_inconclusive_exit_0(self):
        code, out, _ = self.bench(FakeFactory(prompt_answer), tasks=bench_tasks(4))
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("mcp-fixer bench: inconclusive"))

    def test_json_format_and_out(self):
        target = self.dir / "report.json"
        code, out, _ = self.bench(FakeFactory(prompt_answer), "--format", "json", "--out", str(target))
        self.assertEqual((code, out), (0, ""))
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["schemaVersion"], 1)

    def test_more_than_200_calls_need_yes_and_no_call_is_made_without_it(self):
        factory = FakeFactory(prompt_answer)
        self.assert_usage_error_with(factory, tasks=bench_tasks(101))
        self.assertEqual(factory.calls, 0)
        factory = FakeFactory(prompt_answer)
        code, _, err = self.bench(factory, "--yes", tasks=bench_tasks(101))
        self.assertEqual(code, 0, err)
        self.assertEqual(factory.calls, 202)

    def assert_usage_error_with(self, factory, **files):
        code, out, err = self.bench(factory, **files)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("--yes", err)
        self.assertNotIn("Traceback", err)

    def test_an_expected_tool_that_does_not_exist_is_one_line(self):
        tasks = bench_tasks(3)
        tasks["tasks"][1]["expected"] = "ghost"
        factory = FakeFactory(prompt_answer)
        code, out, err = self.bench(factory, tasks=tasks)
        self.assertEqual(code, 2)
        self.assertIn("'t001' expects 'ghost'", err)
        self.assertEqual(factory.calls, 0)

    def test_tasks_for_different_tools_only_warn(self):
        tasks = bench_tasks(30)
        tasks["source"] = {"toolsFingerprint": "0" * 64}
        code, out, err = self.bench(FakeFactory(prompt_answer), tasks=tasks)
        self.assertEqual(code, 0)
        self.assertEqual(err.count("different tools"), 1)

    def test_bad_inputs_are_usage_errors(self):
        tools, patch, tasks = self.files()
        bad = self.write("bad.json", "{nope")
        factory = FakeFactory(prompt_answer)
        with mock.patch.object(cli, "make_runner", factory):
            for argv, fragment in (
                (("bench", "--patch", patch, "--tools-json", tools), "--tasks"),
                (("bench", "--tasks", tasks, "--tools-json", tools), "--patch"),
                (("bench", "--tasks", bad, "--patch", patch, "--tools-json", tools), "not valid JSON"),
                (("bench", "--tasks", tasks, "--patch", bad, "--tools-json", tools), "not valid JSON"),
                (("bench", "--tasks", tasks, "--patch", patch, "--tools-json", tools, "--repeats", "0"), "--repeats"),
                (("bench", "--tasks", tasks, "--patch", patch, "--tools-json", tools, "--tolerance", "nan"), "--tolerance"),
                (("bench", "--tasks", tasks, "--patch", patch, "--tools-json", tools, "--tolerance", "-1"), "--tolerance"),
                (("bench", "--tasks", tasks, "--patch", patch), "--tools-json"),
            ):
                with self.subTest(fragment):
                    code, out, err = run(*argv)
                    self.assertEqual(code, 2, (out, err))
                    self.assertIn(fragment, err)
                    self.assertNotIn("Traceback", err)
        self.assertEqual(factory.calls, 0)

    def test_a_missing_api_key_fails_before_any_call(self):
        tools, patch, tasks = self.files()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            code, out, err = run("bench", "--tasks", tasks, "--patch", patch, "--tools-json", tools, "--runner", "api")
        self.assertEqual(code, 2)
        self.assertIn("ANTHROPIC_API_KEY", err)

    def test_control_characters_never_reach_the_terminal(self):
        tasks = bench_tasks(30)
        tools = [dict(BENCH_TOOLS[0]), dict(BENCH_TOOLS[1]), {"name": "evil\x1b[2J", "description": "d", "inputSchema": {"type": "object", "properties": {}}}]
        patch = {"patchVersion": 1, "tools": {"evil\x1b[2J": {"params": {"ghost": {"type": "string"}}}}}
        code, out, err = self.bench(FakeFactory(prompt_answer), tasks=tasks, tools=tools, patch=patch)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\x1b", err)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s servers/mcp-fixer/tests -p "test_cli.py" -k TasksCommand -k BenchCommand 2>&1 | tail -4`
Expected: failures: argparse rejects the unknown `tasks` and `bench` commands.

- [ ] **Step 3: Edit `cli.py`**

With the Edit tool (the file already imports `argparse, json, math, os, sys, Path` and defines `UsageError`, `_add_input_options`, `read_tools`, `write_file`, `emit`, `run_score`, `run_patch`, `run_wrap`, `main`, `run`):

(a) Add imports below `from .wrap import run_wrapper`:

```python
from . import bench as benchmark
from .runners import RunnerError, make_runner
```

(b) In `build_parser`, before `return parser`, add the two subcommands:

```python
    def add_runner_options(sub_parser):
        sub_parser.add_argument("--runner", choices=("claude", "api"), default="claude", help="how to reach a model: claude -p (default) or the Anthropic API (needs ANTHROPIC_API_KEY)")
        sub_parser.add_argument("--model", metavar="M", help="the model to use (the api runner defaults to claude-sonnet-5-5)")

    tasks = sub.add_parser(
        "tasks",
        usage="mcp-fixer tasks [options] (--tools-json FILE | -- SERVER_COMMAND [ARGS...])",
        description=(
            "Ask a model to write test requests for each of a server's tools and save them to a "
            "tasks file you can review and edit. Read-only for the server; calls a model."
        ),
    )
    _add_input_options(tasks)
    add_runner_options(tasks)
    tasks.add_argument("--per-tool", type=int, default=3, metavar="N", help="requests per tool, 1 to 10 (default 3)")
    tasks.add_argument("--out", metavar="FILE", help="write the tasks to FILE instead of stdout (never overwrites without --force)")
    tasks.add_argument("--force", action="store_true", help="overwrite an existing --out file")

    bench = sub.add_parser(
        "bench",
        usage="mcp-fixer bench --tasks FILE --patch FILE [options] (--tools-json FILE | -- SERVER_COMMAND [ARGS...])",
        description=(
            "Run every task against the original tool list and the patched one (as wrap serves it) "
            "and report both accuracies with a sample-size-aware verdict: worse, no drop detected "
            "or inconclusive. Calls a model tasks x repeats x 2 times."
        ),
    )
    _add_input_options(bench)
    add_runner_options(bench)
    bench.add_argument("--tasks", required=True, metavar="FILE", help="the tasks file (see mcp-fixer tasks)")
    bench.add_argument("--patch", required=True, metavar="FILE", help="the patch file (see mcp-fixer patch)")
    bench.add_argument("--repeats", type=int, default=3, metavar="R", help="runs per task and side (default 3)")
    bench.add_argument("--tolerance", type=float, default=0.05, metavar="T", help="the drop that still counts as no drop (default 0.05)")
    bench.add_argument("--seed", type=int, default=0, metavar="S", help="seed for the tool order and the bootstrap (default 0)")
    bench.add_argument("--format", choices=("text", "json"), default="text", help="output format (default text)")
    bench.add_argument("--out", metavar="FILE", help="write the report to FILE instead of stdout")
    bench.add_argument("--yes", action="store_true", help="allow more than 200 model calls")
```

(c) Add the two handlers before `def main`:

```python
CALL_LIMIT = 200


def _warn(text):
    print(f"mcp-fixer: {text}", file=sys.stderr)


def run_tasks(args, command):
    if not 1 <= args.per_tool <= 10:
        raise UsageError("--per-tool must be between 1 and 10")
    if args.out and not args.force and os.path.exists(args.out):
        raise UsageError(f"{args.out} exists; use --force to overwrite")
    tools, source = read_tools(args, command)
    runner = make_runner(args.runner, args.model, max_tokens=1024)
    data = benchmark.generate_tasks(tools, runner, args.per_tool, source, _warn)
    text = benchmark.render_tasks(data)
    if args.out:
        write_file(args.out, text, overwrite=args.force)
    else:
        emit(text)
    return 0


def run_bench(args, command):
    if args.repeats < 1:
        raise UsageError("--repeats must be at least 1")
    if not math.isfinite(args.tolerance) or args.tolerance < 0:
        raise UsageError("--tolerance must be a finite number, 0 or more")
    patch = load_patch(args.patch)
    tasks = benchmark.load_tasks(args.tasks)
    tools, _source = read_tools(args, command)
    runner = make_runner(args.runner, args.model, max_tokens=64)
    for warning in benchmark.check_tasks(tasks, tools):
        _warn(warning)
    calls = benchmark.estimate_calls(tasks, args.repeats)
    note = f"{calls} model calls"
    if args.runner == "api":
        note += f", about {benchmark.estimate_input_tokens(tasks, tools, patch, args.repeats)} input tokens"
    _warn(note)
    if calls > CALL_LIMIT and not args.yes:
        raise UsageError(f"this run makes {calls} model calls; pass --yes to continue")
    report = benchmark.run_bench(tasks, tools, patch, runner, args.repeats, args.seed, args.tolerance)
    text = (
        benchmark.render_bench_json(report)
        if args.format == "json"
        else benchmark.render_bench_text(report)
    )
    if args.out:
        write_file(args.out, text, overwrite=True)
    else:
        emit(text)
    return 1 if report["verdict"]["verdict"] == "worse" else 0
```

(d) In `main`, replace the `handlers` dict and the except clause:

```python
    handlers = {"score": run_score, "patch": run_patch, "wrap": run_wrap, "tasks": run_tasks, "bench": run_bench}
    try:
        return handlers[parsed.command](parsed, command)
    except (UsageError, ClientError, PatchError, benchmark.BenchError, RunnerError) as exc:
```

- [ ] **Step 4: Run all the tests**

Run: `python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -6`
Expected: all PASS. Snags: (a) the `--tools-json` error for `bench` without it is the shared `read_tools` message ("give --tools-json FILE, or a server command after --"), which contains `--tools-json`; (b) `test_a_missing_api_key_fails_before_any_call` passes because `make_runner` runs before any model call and raises `RunnerError`, which `main` reports as `error: ...` with exit 2.

- [ ] **Step 5: Smoke the commands by hand with the fake runner path** (no real model): run `python -m mcp_fixer bench --help | head -5` and `python -m mcp_fixer tasks --tools-json servers/mcp-fixer/tests/fixtures/clean_tools.json --runner api` (with no key set).
Expected: help text prints; the second prints `error: ANTHROPIC_API_KEY is not set; the api runner needs it` and exits 2, with no traceback.

- [ ] **Step 6: Commit**

```bash
python -m unittest discover -s tests 2>&1 | tail -2
python scripts/validate.py
git add servers/mcp-fixer
git commit -m "$(cat <<'EOF'
feat: mcp-fixer tasks and bench commands

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: README, version and final checks

**Files:**
- Modify: `servers/mcp-fixer/README.md`, `servers/mcp-fixer/pyproject.toml`, `servers/mcp-fixer/src/mcp_fixer/__init__.py`, `CHANGELOG.md`

**Interfaces:**
- Consumes: the shipped behavior of Tasks 1 to 5.

- [ ] **Step 1: Bump the version in both places**

In `servers/mcp-fixer/pyproject.toml` change `version = "0.2.0"` to `version = "0.3.0"`, and in `servers/mcp-fixer/src/mcp_fixer/__init__.py` change `__version__ = "0.2.0"` to `__version__ = "0.3.0"`. Run `python -m unittest discover -s servers/mcp-fixer/tests -p "test_package.py"`: PASS.

- [ ] **Step 2: Update the README**

Write the following script to `$SP/readme_bench.py` with the Write tool (it has no backslashes), then run it from the repo root with `python $SP/readme_bench.py`:

```python
from pathlib import Path

p = Path("servers/mcp-fixer/README.md")
s = p.read_text(encoding="utf-8")


def swap(old, new):
    global s
    assert s.count(old) == 1, old[:70]
    s = s.replace(old, new)


swap(
    "# mcp-fixer: score and patch an MCP server's tool definitions",
    "# mcp-fixer: score, patch and benchmark an MCP server's tool definitions",
)
swap(
    "Three planned parts: **score** (finds the problems), **patch and wrap** (applies fixes without changing the server) and a benchmark that shows tool selection did not get worse. The first two exist; the benchmark does not, so this tool makes no claim that a patch improves tool selection.",
    "Three parts: **score** (finds the problems), **patch and wrap** (applies fixes without changing the server) and **bench** (checks whether tool selection got worse). Bench can detect a drop; it cannot show that a patch improves anything, and it says so.",
)

BENCH = """## Check it: tasks and bench

`mcp-fixer tasks` asks a model to write test requests for each of a server's tools and saves them to a file you can edit. `mcp-fixer bench` then runs every request against the original tool list and the patched one, exactly as `wrap` would serve it, and asks the model which tool it would choose. Nothing is ever called: the model only names a tool.

```text
PYTHONPATH=servers/mcp-fixer/src python -m mcp_fixer tasks --out tasks.json -- npx -y some-mcp-server
# review and edit tasks.json: fix any request whose expected tool is wrong
PYTHONPATH=servers/mcp-fixer/src python -m mcp_fixer bench --tasks tasks.json --patch orders.patch.json -- npx -y some-mcp-server
```

**Runners.** `--runner claude` (the default) runs `claude -p --tools "" --no-session-persistence` with your existing login, so it needs no API key; it runs inside your own Claude Code configuration (CLAUDE.md, hooks, skills), which can influence replies, and on Windows a `claude` shim may drop the empty `--tools` argument (not checked in a live run). `--runner api` calls the Anthropic Messages API directly with temperature 0 and needs `ANTHROPIC_API_KEY` in the environment; the key is never printed or written anywhere. Use `--model` to pick the model.

**The tasks** are generated from the original tool list only, each request written without the tool's name; requests that still contain the name are dropped. They are a starting point: the answer key is only as good as the file, so read it.

**What bench does.** For every task and repeat (default 3) it shows the model the same tools in the same shuffled order, once as the server defines them and once patched, and scores the reply. A reply that is not a valid choice counts as wrong; a failed model call is retried once and then excluded and counted. A renamed tool's answer is mapped back to its original name. It makes `tasks x repeats x 2` model calls, prints that number first, and asks for `--yes` above 200.

**The verdict** accounts for how much data there is:

| Verdict | When | Exit code |
| --- | --- | --- |
| `worse` | the 95% interval of (patched minus original accuracy, paired by task) is entirely below zero | 1 |
| `no drop detected` | at least 30 usable tasks and the interval's lower bound is above minus `--tolerance` (default 0.05) | 0 |
| `inconclusive` | anything else: too few tasks, or an interval too wide to rule out a drop (the report says which, and about how many tasks it would take) | 0 |

The report also shows each side's accuracy with a 95% Wilson interval, the invalid rate, and the token sizes before and after. It always ends with: "This measures whether a drop could be detected on these generated tasks; it does not show the patch improves tool selection."

**Honest limits.** The tasks are written by a model, so they share its blind spots; one model is used per run, and one run is one sample. `no drop detected` is not evidence of an improvement. Nothing here has been run against a real server yet: a live run is yours to do.

"""
swap("## The rules\n", BENCH + "## The rules\n")
swap(
    "any model, error normalization, and the accuracy benchmark.",
    "error normalization, and anything beyond choosing a tool: bench does not call tools, check arguments or test multi-step flows.",
)
with open(p, "w", encoding="utf-8", newline="\n") as f:
    f.write(s)

c = Path("CHANGELOG.md")
t = c.read_text(encoding="utf-8")
anchor = "### Added\n"
entry = (
    "- `mcp-fixer tasks` and `mcp-fixer bench` (third of three parts): `tasks` has a model write test requests for each tool into an editable file, "
    "and `bench` runs them against the original and the patched tool list (as `wrap` serves it) through `claude -p` or the Anthropic API, then reports "
    "both accuracies with 95% intervals, a paired comparison, token sizes and a sample-size-aware verdict (`worse`, `no drop detected` or `inconclusive`). "
    "It can detect a drop but does not show a patch improves tool selection, and it has not been run against a real server yet.\n"
)
assert t.count(anchor) >= 1
c.write_text(t.replace(anchor, anchor + entry, 1), encoding="utf-8", newline="\n")

for path, old, new in (
    ("servers/mcp-fixer/pyproject.toml", 'version = "0.2.0"', 'version = "0.3.0"'),
    ("servers/mcp-fixer/src/mcp_fixer/__init__.py", '__version__ = "0.2.0"', '__version__ = "0.3.0"'),
):
    f = Path(path)
    x = f.read_text(encoding="utf-8")
    if old in x:
        f.write_text(x.replace(old, new), encoding="utf-8", newline="\n")
print("ok")
```

The script's version-bump lines are skipped when Step 1 already changed them.

- [ ] **Step 3: Run the full set of checks**

```bash
python scripts/build_catalog.py --check && echo catalog-current
python -m unittest discover -s tests 2>&1 | tail -3
python -m unittest discover -s servers/mcp-fixer/tests 2>&1 | tail -3
python scripts/validate.py
git diff --stat main -- docs/superpowers | tail -4
ls -d %* 2>/dev/null | wc -l
```

Expected: `catalog-current`; both suites PASS; `OK: all plugins valid`; the `docs/superpowers` diff lists only the new spec and this plan; no stray `%SystemDrive%` folder (`0`). If `build_catalog.py --check` complains, the server's first README line changed: leave the `> ` description line untouched (this plan does not edit it).

- [ ] **Step 4: Commit**

```bash
git add -A servers CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs: mcp-fixer tasks and bench README, changelog and version 0.3.0

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

## Handoff after the merge (not tasks)

1. Merge `mcp-fixer-bench` into `main` locally (the finishing step); pushing is a separate confirmed step.
2. **Live check, yours:** run `mcp-fixer tasks` and `mcp-fixer bench` against a real server and patch with `--runner claude` (and, if you have a key, `--runner api`), read the generated tasks, and confirm that the `claude` shim keeps the empty `--tools ""` argument on Windows.
3. This completes the three-part mcp-fixer pitch; the deferred minors from the scorer and patcher reviews are still unfiled.

## Self-review notes

- **Spec coverage:** commands and flow (Tasks 4 and 5); trial prompt and strict scoring (Tasks 1 and 4); runners with retry and cost guard (Tasks 3 to 5); Wilson, paired bootstrap and the verdict with exact boundaries (Task 2); the tasks file format and its checks (Task 4); safety (key redaction in Task 3, escaping in Tasks 4 and 5); README, CHANGELOG and 0.3.0 (Task 6); CI is unchanged because the existing job runs this folder's tests.
- **Spec details made precise here:** `valid_tools` and the shared fingerprint, the `mentions_name` rule, the fixed model-call timeout, the API default model, `call_with_retry` returning attempt counts, and the Windows `--tools ""` risk.
- **Type consistency:** `render_tools`, `trial_prompt`, `tasks_prompt`, `parse_choice`, `parse_task_list`, `mentions_name`, `wilson`, `paired_bootstrap`, `tasks_needed`, `verdict`, `make_runner(name, model, env, timeout, max_tokens)`, `valid_tools`, `tools_fingerprint`, `generate_tasks`, `check_tasks`, `patched_view`, `run_bench`, `render_bench_text`, `render_bench_json` are defined once and used with the same names and signatures in the tests and the CLI.
- **Known unknowns the executor settles by running the tests:** timing of the pathological-reply test, Windows pipe behavior in the timeout test.
