# decision-journal Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and ship the `decision-journal` skill: a `SKILL.md` plus a standard-library Python script that logs a developer's predictions, grades them later, and reports calibration.

**Architecture:** One plugin, `plugins/decision-journal/`, scaffolded by `scripts/new_skill.py`. The script `journal.py` lives inside the skill folder (`skills/decision-journal/scripts/`) so manual copy works; it owns all file writes and arithmetic. `SKILL.md` owns the conversation. The script is built test-first with `unittest` in the repo's `tests/`; the skill text is built test-first in the writing-skills sense (baseline scenarios without the skill, then with it, tightening until they pass).

**Tech Stack:** Python 3.9+ standard library (`argparse`, `json`, `statistics`, `os.replace`), Markdown, the repo tooling, general-purpose subagents (model `sonnet`) as the scenario runner.

**Spec:** `docs/superpowers/specs/2026-10-01-decision-journal-design.md`

## Global Constraints

- Plugin and skill name: `decision-journal`. `SKILL.md` frontmatter: `name`, plus a single-line, double-quoted `description` starting with `Use when`. No branding footer.
- The skill is explicit-only: it never logs, grades or offers to log unprompted; an offhand "this should take a few hours" is not a request.
- Log path `~/.claude/decision-journal.jsonl`, overridable by env var `DECISION_JOURNAL_PATH`. "Today" is the system date, overridable by `DECISION_JOURNAL_TODAY` (`YYYY-MM-DD`).
- Script: standard library only, Python 3.9+, LF line endings written, UTF-8 (BOM and CRLF tolerated on read).
- Claim confidence is an integer 50-99. Estimate is a number greater than 0 with a non-empty unit; an 80% range is optional, both bounds or neither, `range_low <= estimate <= range_high`. Actual is a number greater than or equal to 0.
- Exit codes: 0 success; 2 invalid input (message on stderr, prefixed `error:`); 1 entry not found.
- Writes are atomic (temp file in the same directory, then `os.replace`). A malformed log line is skipped with a stderr warning and preserved verbatim (line content) on rewrite, never dropped.
- `stats`: fewer than 5 graded entries overall prints counts only and "Too few graded entries to conclude (need at least 5)."; any bucket, tag or estimate slice with n below 5 is marked `(n<5)` and never interpreted.
- Author `Naren`; GitHub user `NarenDawar`; repo `narens-claude-skills`. One plugin per skill; marketplace name `narens-claude-skills`.
- Do not push to GitHub in this plan; pushing is a separate, explicit user request.
- Scratch work (fixtures, scenario outputs) lives in the session scratchpad, never in the repo: `C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a/scratchpad` (called `$SP` below). Scenario runs must always point `DECISION_JOURNAL_PATH` at a scratch file, never at the real `~/.claude` journal.
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

**Spec clarifications decided in this plan:** malformed lines are preserved verbatim by line content (CRLF is normalized to LF, blank lines dropped), not byte-for-byte; absent `know_by`, `range_low` and `range_high` are stored as `null`; a graded entry gains a `graded` date key; "ask one short line offering the optional extras" happens before `add`, because the script has no edit command.

## Review Focus

These input classes are implied by the spec but not named in its scenario table. Each is pinned by a test below:

- **Missing, empty or corrupt log** (first run, a hand-edited bad line, invalid UTF-8): no crash; corrupt lines survive rewrites. Task 2 (`test_malformed_line_survives_rewrite`, `test_invalid_utf8_log_is_an_error`, `test_missing_log_lists_empty`).
- **Out-of-range or fractional confidence** ("100% sure", 40, 0.7): rejected with a clear message; the skill relays it and asks again. Task 2 (`test_add_validation`); skill scenario J10 in Task 5.
- **Special characters in prediction text** (quotes, pipes, newlines, emoji): stored and read back exactly, one line per entry. Task 2 (`test_text_roundtrips_special_characters`).
- **Regrading an already graded entry** ("actually #1 was wrong"): rejected without `--force`; the skill asks before overwriting. Task 2 (`test_grade_twice_requires_force`); skill scenario J11.
- **Edit or delete request** ("delete my last prediction, it was a typo"): v1 has no such command; the skill says so and gives the log path instead of silently editing. Skill scenario J12.

---

## File Structure

| File | Responsibility |
|---|---|
| `plugins/decision-journal/skills/decision-journal/scripts/journal.py` | All log IO, validation, grading, stats math, CLI |
| `plugins/decision-journal/skills/decision-journal/SKILL.md` | The conversation: log, grade, review flows |
| `plugins/decision-journal/README.md` | Public per-skill page |
| `tests/test_journal.py` | Unit tests for `journal.py` |
| Generated | `plugin.json`, marketplace entry, root README catalog, `llms.txt` |

Run all tests with: `python -m unittest discover -s tests -v`

---

### Task 1: Scaffold the plugin

**Files:**
- Create (generated): `plugins/decision-journal/` (plugin.json, README.md, `skills/decision-journal/SKILL.md`)
- Modify (generated): `.claude-plugin/marketplace.json`, `README.md`, `llms.txt`

**Interfaces:**
- Produces: the plugin directory that Tasks 2-6 fill in.

- [ ] **Step 1: Scaffold with the repo tool**

```bash
cd "C:/Users/naren/Documents/claude-skills"
python scripts/new_skill.py decision-journal "Use when the user wants to log a prediction or estimate about a dev or project decision, grade past predictions, or see how calibrated they are (for example 'log a prediction', 'grade my predictions', 'how calibrated am I?')."
mkdir -p plugins/decision-journal/skills/decision-journal/scripts
```

Expected: `Created ...\plugins\decision-journal. Now edit SKILL.md and README.md, then run validate.py.`

- [ ] **Step 2: Verify the repo still validates**

Run: `python scripts/validate.py && python -m unittest discover -s tests 2>&1 | tail -3 && python scripts/build_catalog.py --check; echo exit=$?`
Expected: `OK: all plugins valid`; 70 tests OK; `exit=0`.

- [ ] **Step 3: Commit**

```bash
git add plugins .claude-plugin README.md llms.txt
git commit -m "feat: scaffold decision-journal plugin" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: journal.py storage, add, list, grade, CLI

**Files:**
- Create: `plugins/decision-journal/skills/decision-journal/scripts/journal.py`
- Test: `tests/test_journal.py`

**Interfaces:**
- Produces (module `journal`): `JournalError`, `NotFound`, `log_path() -> Path`, `parse_date(text) -> date`, `today() -> date`, `load(path) -> list[tuple[str, object]]` (slots `("entry", dict)` or `("raw", str)`), `entries_of(slots) -> list[dict]`, `save(path, slots) -> None`, `add_entry(path, *, type, text, confidence=None, unit=None, estimate=None, range_low=None, range_high=None, know_by=None, tags=None, project=None) -> dict`, `list_entries(path, mode=None) -> list[dict]` (mode `None`, `"open"` or `"due"`), `grade_entry(path, entry_id, *, outcome=None, actual=None, note=None, force=False) -> dict`, `build_parser() -> argparse.ArgumentParser`, `main(argv=None) -> int`.
- Entry dict keys: `id, created, type, text`, claim: `confidence`; estimate: `unit, estimate, range_low, range_high`; then `know_by, tags, project, status`; after grading `graded` plus `outcome` ("yes"/"no") or `actual`, and `note` if given.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_journal.py`:

```python
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers

sys.path.insert(
    0,
    str(helpers.REPO_ROOT / "plugins" / "decision-journal" / "skills" / "decision-journal" / "scripts"),
)
import journal  # noqa: E402
from journal import JournalError, NotFound  # noqa: E402


class JournalCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "sub" / "j.jsonl"
        env = mock.patch.dict(
            os.environ,
            {"DECISION_JOURNAL_PATH": str(self.path), "DECISION_JOURNAL_TODAY": "2026-10-01"},
        )
        env.start()
        self.addCleanup(env.stop)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = journal.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def claim(self, text="c", confidence=70, **kw):
        return journal.add_entry(
            self.path, type="claim", text=text, confidence=confidence, project="proj", **kw
        )

    def estimate(self, text="e", estimate=2, unit="hours", **kw):
        return journal.add_entry(
            self.path, type="estimate", text=text, unit=unit, estimate=estimate, project="proj", **kw
        )

    def read(self):
        return journal.entries_of(journal.load(self.path))


class AddTests(JournalCase):
    def test_add_claim(self):
        e = self.claim("cache won't scale", 70, know_by="2026-10-15", tags="Perf, perf ,api")
        self.assertEqual(
            e,
            {
                "id": 1, "created": "2026-10-01", "type": "claim", "text": "cache won't scale",
                "confidence": 70, "know_by": "2026-10-15", "tags": ["perf", "api"],
                "project": "proj", "status": "open",
            },
        )
        self.assertEqual(self.read(), [e])

    def test_add_estimate_with_range(self):
        e = self.estimate("refactor", 2, range_low=1.5, range_high=4, tags=["refactor"])
        self.assertEqual(e["unit"], "hours")
        self.assertEqual((e["estimate"], e["range_low"], e["range_high"]), (2, 1.5, 4))
        self.assertIsNone(e["know_by"])

    def test_estimate_without_range_stores_nulls(self):
        e = self.estimate()
        self.assertIsNone(e["range_low"])
        self.assertIsNone(e["range_high"])

    def test_ids_are_max_plus_one(self):
        self.claim()
        self.claim()
        slots = journal.load(self.path)
        slots[0][1]["id"] = 7  # simulate a gap
        journal.save(self.path, slots)
        self.assertEqual(self.claim()["id"], 8)

    def test_add_validation(self):
        bad = [
            dict(type="claim", text="x", confidence=49),
            dict(type="claim", text="x", confidence=100),
            dict(type="claim", text="x", confidence=70.5),
            dict(type="claim", text="x", confidence=None),
            dict(type="claim", text="x", confidence=70, unit="hours"),
            dict(type="claim", text="x", confidence=70, estimate=2),
            dict(type="claim", text="", confidence=70),
            dict(type="claim", text="x", confidence=70, know_by="not-a-date"),
            dict(type="estimate", text="x", unit="hours", estimate=0),
            dict(type="estimate", text="x", unit="hours", estimate=-1),
            dict(type="estimate", text="x", unit="hours", estimate=float("inf")),
            dict(type="estimate", text="x", unit="hours", estimate=None),
            dict(type="estimate", text="x", unit="", estimate=2),
            dict(type="estimate", text="x", unit="hours", estimate=2, confidence=70),
            dict(type="estimate", text="x", unit="hours", estimate=2, range_low=1),
            dict(type="estimate", text="x", unit="hours", estimate=2, range_high=3),
            dict(type="estimate", text="x", unit="hours", estimate=2, range_low=3, range_high=4),
            dict(type="estimate", text="x", unit="hours", estimate=5, range_low=1, range_high=4),
            dict(type="mystery", text="x"),
        ]
        for kwargs in bad:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(JournalError):
                    journal.add_entry(self.path, project="proj", **kwargs)
        self.assertFalse(self.path.exists())  # nothing written by failed adds

    def test_text_roundtrips_special_characters(self):
        text = 'Use "quotes", pipes | and émojis 🚀\nsecond line'
        self.claim(text)
        self.assertEqual(self.read()[0]["text"], text)
        self.assertEqual(len(self.path.read_text(encoding="utf-8").splitlines()), 1)

    def test_creates_parent_directory(self):
        self.assertFalse(self.path.parent.exists())
        self.claim()
        self.assertTrue(self.path.is_file())

    def test_default_log_path(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("DECISION_JOURNAL_PATH")
            self.assertEqual(
                journal.log_path(), Path.home() / ".claude" / "decision-journal.jsonl"
            )

    def test_invalid_today_override_is_an_error(self):
        with mock.patch.dict(os.environ, {"DECISION_JOURNAL_TODAY": "garbage"}):
            with self.assertRaises(JournalError):
                self.claim()


class ListTests(JournalCase):
    def test_missing_log_lists_empty(self):
        self.assertEqual(journal.list_entries(self.path), [])
        self.assertEqual(journal.list_entries(self.path, "due"), [])

    def test_filters(self):
        self.claim("a", know_by="2026-09-30")   # 1 due (past)
        self.claim("b", know_by="2026-10-01")   # 2 due (today, inclusive)
        self.claim("c", know_by="2026-10-02")   # 3 open, not due
        self.claim("d")                          # 4 open, no know_by
        self.claim("e", know_by="2026-09-01")   # 5 graded, excluded from open/due
        journal.grade_entry(self.path, 5, outcome="yes")
        ids = lambda mode: [e["id"] for e in journal.list_entries(self.path, mode)]
        self.assertEqual(ids("due"), [1, 2])
        self.assertEqual(ids("open"), [1, 2, 3, 4])
        self.assertEqual(ids(None), [1, 2, 3, 4, 5])


class GradeTests(JournalCase):
    def test_grade_claim(self):
        self.claim()
        e = journal.grade_entry(self.path, 1, outcome="no", note="held up fine")
        self.assertEqual(
            (e["status"], e["outcome"], e["graded"], e["note"]),
            ("graded", "no", "2026-10-01", "held up fine"),
        )
        self.assertEqual(self.read(), [e])

    def test_grade_estimate(self):
        self.estimate()
        e = journal.grade_entry(self.path, 1, actual=3.5)
        self.assertEqual((e["status"], e["actual"]), ("graded", 3.5))

    def test_wrong_grade_kind_is_rejected(self):
        self.claim()
        self.estimate()
        for entry_id, kwargs in ((1, {"actual": 2}), (1, {}), (1, {"outcome": "maybe"}),
                                 (2, {"outcome": "yes"}), (2, {}), (2, {"actual": -1}),
                                 (2, {"actual": float("nan")})):
            with self.subTest(entry_id=entry_id, kwargs=kwargs):
                with self.assertRaises(JournalError):
                    journal.grade_entry(self.path, entry_id, **kwargs)
        self.assertEqual([e["status"] for e in self.read()], ["open", "open"])

    def test_grade_twice_requires_force(self):
        self.claim()
        journal.grade_entry(self.path, 1, outcome="yes")
        with self.assertRaises(JournalError):
            journal.grade_entry(self.path, 1, outcome="no")
        self.assertEqual(self.read()[0]["outcome"], "yes")
        e = journal.grade_entry(self.path, 1, outcome="no", force=True)
        self.assertEqual(e["outcome"], "no")

    def test_unknown_id(self):
        with self.assertRaises(NotFound):
            journal.grade_entry(self.path, 99, outcome="yes")


class RobustnessTests(JournalCase):
    def test_malformed_line_survives_rewrite(self):
        self.claim("a")
        with open(self.path, "a", encoding="utf-8") as f:
            f.write("{not json\n")
        self.claim("b")  # rewrites the file
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[1], "{not json")
        journal.grade_entry(self.path, 2, outcome="yes")
        self.assertIn("{not json", self.path.read_text(encoding="utf-8"))

    def test_malformed_line_warns_on_stderr(self):
        self.claim("a")
        with open(self.path, "a", encoding="utf-8") as f:
            f.write('{"id": 1}\n')  # valid JSON, missing required fields
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(len(journal.entries_of(journal.load(self.path))), 1)
        self.assertIn("malformed line 2", err.getvalue())

    def test_crlf_and_bom_are_tolerated(self):
        e = self.claim("a")
        self.path.write_bytes(b"\xef\xbb\xbf" + json.dumps(e).encode("utf-8") + b"\r\n")
        self.assertEqual(self.read(), [e])

    def test_invalid_utf8_log_is_an_error(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes(b"\xff\xfe\x00bad")
        code, _, err = self.run_cli("list")
        self.assertEqual(code, 2)
        self.assertIn("not valid UTF-8", err)

    def test_failed_write_leaves_original_intact(self):
        self.claim("a")
        before = self.path.read_bytes()
        with mock.patch("journal.os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.claim("b")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["j.jsonl"])


class CliTests(JournalCase):
    def test_add_list_grade_roundtrip(self):
        code, out, _ = self.run_cli("add", "--type", "claim", "--text", "x", "--confidence", "70", "--tag", "perf")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["id"], 1)
        code, out, _ = self.run_cli("list", "--open")
        self.assertEqual([e["id"] for e in json.loads(out)], [1])
        code, out, _ = self.run_cli("grade", "1", "--outcome", "yes", "--note", "done")
        self.assertEqual((code, json.loads(out)["status"]), (0, "graded"))

    def test_add_estimate_via_cli(self):
        code, out, _ = self.run_cli(
            "add", "--type", "estimate", "--text", "refactor", "--unit", "hours",
            "--estimate", "2", "--range-low", "1.5", "--range-high", "4",
        )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["range_high"], 4)

    def test_invalid_input_exits_2(self):
        code, out, err = self.run_cli("add", "--type", "claim", "--text", "x", "--confidence", "100")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("error:"), err)

    def test_not_found_exits_1(self):
        code, _, err = self.run_cli("grade", "99", "--outcome", "yes")
        self.assertEqual(code, 1)
        self.assertTrue(err.startswith("error:"), err)

    def test_argparse_errors_exit_2(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_cli("add", "--type", "claim")
        self.assertEqual(cm.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_journal.py" 2>&1 | tail -4`
Expected: ERROR with `ModuleNotFoundError: No module named 'journal'`

- [ ] **Step 3: Write the implementation**

Create `plugins/decision-journal/skills/decision-journal/scripts/journal.py`:

```python
#!/usr/bin/env python3
"""Decision journal: log predictions, grade them, and show calibration.

Usage: python journal.py {add,list,grade,stats} ...   (standard library only)
Log: ~/.claude/decision-journal.jsonl (override with DECISION_JOURNAL_PATH).
"""
import argparse
import json
import math
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

DEFAULT_PATH = Path.home() / ".claude" / "decision-journal.jsonl"
REQUIRED = {"claim": ("confidence",), "estimate": ("unit", "estimate")}


class JournalError(Exception):
    """Invalid input (exit code 2)."""


class NotFound(Exception):
    """No such entry (exit code 1)."""


def log_path():
    return Path(os.environ.get("DECISION_JOURNAL_PATH") or DEFAULT_PATH)


def parse_date(text):
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        raise JournalError(f"invalid date {text!r}; use YYYY-MM-DD") from None


def today():
    raw = os.environ.get("DECISION_JOURNAL_TODAY")
    return parse_date(raw) if raw else date.today()


def _valid(entry):
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("id"), int)
        and entry.get("type") in REQUIRED
        and isinstance(entry.get("text"), str)
        and entry.get("status") in ("open", "graded")
        and all(key in entry for key in REQUIRED[entry["type"]])
    )


def load(path):
    """Read the log as slots: ("entry", dict) or ("raw", line). Malformed lines are kept."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raise JournalError(f"{path} is not valid UTF-8") from None
    slots = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            obj = None
        if _valid(obj):
            slots.append(("entry", obj))
        else:
            slots.append(("raw", line))
            print(f"warning: skipping malformed line {number} in {path}", file=sys.stderr)
    return slots


def entries_of(slots):
    return [value for kind, value in slots if kind == "entry"]


def save(path, slots):
    """Atomically rewrite the log: temp file in the same directory, then os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(v) if kind == "entry" else v for kind, v in slots]
    data = "".join(line + "\n" for line in lines)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".journal-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _number(value, name):
    if value is None or isinstance(value, bool) or not math.isfinite(value):
        raise JournalError(f"{name} must be a finite number")
    return value


def _normalize_tags(tags):
    if tags is None:
        return []
    if isinstance(tags, str):
        tags = tags.split(",")
    out = []
    for tag in tags:
        tag = tag.strip().lower()
        if tag and tag not in out:
            out.append(tag)
    return out


def add_entry(path, *, type, text, confidence=None, unit=None, estimate=None,
              range_low=None, range_high=None, know_by=None, tags=None, project=None):
    text = (text or "").strip()
    if not text:
        raise JournalError("text must not be empty")
    entry = {"id": 0, "created": today().isoformat(), "type": type, "text": text}
    if type == "claim":
        if any(v is not None for v in (unit, estimate, range_low, range_high)):
            raise JournalError("claims take --confidence only, not --unit, --estimate or --range-*")
        if (not isinstance(confidence, int) or isinstance(confidence, bool)
                or not 50 <= confidence <= 99):
            raise JournalError(
                "confidence must be a whole number from 50 to 99 "
                "(below 50, flip the claim; 100 is not a prediction)"
            )
        entry["confidence"] = confidence
    elif type == "estimate":
        if confidence is not None:
            raise JournalError("estimates take --estimate and --unit, not --confidence")
        unit = (unit or "").strip()
        if not unit:
            raise JournalError("estimates need --unit (for example hours)")
        _number(estimate, "estimate")
        if estimate <= 0:
            raise JournalError("estimate must be greater than 0")
        if (range_low is None) != (range_high is None):
            raise JournalError("give both --range-low and --range-high, or neither")
        if range_low is not None:
            _number(range_low, "range-low")
            _number(range_high, "range-high")
            if not range_low <= estimate <= range_high:
                raise JournalError("range must satisfy range-low <= estimate <= range-high")
        entry.update(unit=unit, estimate=estimate, range_low=range_low, range_high=range_high)
    else:
        raise JournalError(f"unknown type {type!r}; use claim or estimate")
    entry["know_by"] = parse_date(know_by).isoformat() if know_by else None
    entry["tags"] = _normalize_tags(tags)
    entry["project"] = project if project is not None else Path.cwd().name
    entry["status"] = "open"
    slots = load(path)
    entry["id"] = max([e["id"] for e in entries_of(slots)], default=0) + 1
    slots.append(("entry", entry))
    save(path, slots)
    return entry


def _is_due(entry, as_of):
    if entry["status"] != "open" or not entry.get("know_by"):
        return False
    try:
        return date.fromisoformat(entry["know_by"]) <= as_of
    except ValueError:
        return False


def list_entries(path, mode=None):
    entries = entries_of(load(path))
    if mode == "open":
        return [e for e in entries if e["status"] == "open"]
    if mode == "due":
        as_of = today()
        return [e for e in entries if _is_due(e, as_of)]
    return entries


def grade_entry(path, entry_id, *, outcome=None, actual=None, note=None, force=False):
    slots = load(path)
    entry = next((v for kind, v in slots if kind == "entry" and v["id"] == entry_id), None)
    if entry is None:
        raise NotFound(f"no entry with id {entry_id}")
    if entry["status"] == "graded" and not force:
        raise JournalError(f"entry {entry_id} is already graded; use --force to overwrite")
    if entry["type"] == "claim":
        if actual is not None:
            raise JournalError("claims are graded with --outcome yes|no, not --actual")
        if outcome not in ("yes", "no"):
            raise JournalError("claims need --outcome yes|no")
    else:
        if outcome is not None:
            raise JournalError("estimates are graded with --actual NUMBER, not --outcome")
        _number(actual, "actual")
        if actual < 0:
            raise JournalError("actual must be 0 or greater")
    entry.pop("outcome", None)
    entry.pop("actual", None)
    entry["status"] = "graded"
    entry["graded"] = today().isoformat()
    if entry["type"] == "claim":
        entry["outcome"] = outcome
    else:
        entry["actual"] = actual
    if note is not None:
        entry["note"] = note.strip()
    save(path, slots)
    return entry


def build_parser():
    parser = argparse.ArgumentParser(
        prog="journal.py", description="Log predictions, grade them, and review calibration."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    add = sub.add_parser("add", help="record a prediction")
    add.add_argument("--type", required=True, choices=["claim", "estimate"])
    add.add_argument("--text", required=True)
    add.add_argument("--confidence", type=int, help="claims: 50-99")
    add.add_argument("--unit", help="estimates: for example hours")
    add.add_argument("--estimate", type=float, help="estimates: your point estimate")
    add.add_argument("--range-low", type=float, help="estimates: low end of your 80%% range")
    add.add_argument("--range-high", type=float, help="estimates: high end of your 80%% range")
    add.add_argument("--know-by", help="date you expect to know the outcome (YYYY-MM-DD)")
    add.add_argument("--tag", help="comma-separated tags")

    lst = sub.add_parser("list", help="print entries as JSON")
    group = lst.add_mutually_exclusive_group()
    group.add_argument("--open", action="store_true")
    group.add_argument("--due", action="store_true")

    grade = sub.add_parser("grade", help="record the outcome of a prediction")
    grade.add_argument("id", type=int)
    grade.add_argument("--outcome", choices=["yes", "no"])
    grade.add_argument("--actual", type=float)
    grade.add_argument("--note")
    grade.add_argument("--force", action="store_true", help="overwrite an existing grade")
    return parser


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    path = log_path()
    try:
        if args.cmd == "add":
            result = add_entry(
                path, type=args.type, text=args.text, confidence=args.confidence,
                unit=args.unit, estimate=args.estimate, range_low=args.range_low,
                range_high=args.range_high, know_by=args.know_by, tags=args.tag,
            )
            print(json.dumps(result))
        elif args.cmd == "list":
            mode = "open" if args.open else "due" if args.due else None
            print(json.dumps(list_entries(path, mode)))
        elif args.cmd == "grade":
            result = grade_entry(
                path, args.id, outcome=args.outcome, actual=args.actual,
                note=args.note, force=args.force,
            )
            print(json.dumps(result))
    except JournalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except NotFound as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v 2>&1 | tail -6`
Expected: `OK`; the 70 existing tests plus every test in `test_journal.py` pass.

- [ ] **Step 5: Validate and commit**

```bash
python scripts/validate.py
git add plugins/decision-journal tests/test_journal.py
git commit -m "feat: add decision-journal script (log, list, grade)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Expected: `OK: all plugins valid`.

---

### Task 3: journal.py stats

**Files:**
- Modify: `plugins/decision-journal/skills/decision-journal/scripts/journal.py`
- Test: `tests/test_journal.py`

**Interfaces:**
- Consumes: `journal.entries_of`, `load`, `add_entry`, `grade_entry`, `list_entries`, `JournalError`; `JournalCase` helpers from Task 2.
- Produces: `MIN_N = 5`, `BUCKETS`, `compute_stats(entries) -> dict`, `format_stats(stats, tag=None) -> str`, and the CLI subcommand `stats [--tag T]`.
- `compute_stats` result: `{"graded", "claim_count", "estimate_count", "too_few", "claims": {"n", "brier", "buckets": [{"label", "n", "stated", "actual", "gap"}]} | None, "estimates": {"n", "median_ratio", "range_n", "range_hits"} | None, "tags": {tag: {"claims": {"n","stated","actual","gap"} | None, "estimates": {"n","median_ratio"} | None}}}`. `stated`, `actual`, `gap` are percentages; `gap = stated - actual` (positive means overconfident); `median_ratio = median(actual / estimate)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_journal.py` (before the `if __name__` block):

```python
class StatsTests(JournalCase):
    def build_dataset(self):
        """13 graded claims and 5 graded estimates with known, hand-computed results."""
        for conf, outcomes, tag in ((80, "yyyynn", "perf"), (70, "yyynn", "api"), (60, "yn", "api")):
            for o in outcomes:
                e = self.claim("c", conf, tags=tag)
                journal.grade_entry(self.path, e["id"], outcome="yes" if o == "y" else "no")
        for est, actual, lo, hi in ((2, 3, 1.5, 2.5), (4, 4, 3, 5), (1, 2, 0.5, 1.5),
                                    (10, 8, 7, 13), (3, 6, None, None)):
            e = self.estimate("e", est, range_low=lo, range_high=hi, tags="refactor")
            journal.grade_entry(self.path, e["id"], actual=actual)

    def stats(self, tag=None):
        entries = self.read()
        if tag:
            entries = [e for e in entries if tag in e["tags"]]
        return journal.compute_stats(entries)

    def test_compute_stats_known_values(self):
        self.build_dataset()
        self.claim("still open", 90)  # open entries are ignored
        s = self.stats()
        self.assertEqual((s["graded"], s["claim_count"], s["estimate_count"], s["too_few"]),
                         (18, 13, 5, False))
        self.assertAlmostEqual(s["claims"]["brier"], 3.21 / 13, places=9)
        by_label = {b["label"]: b for b in s["claims"]["buckets"]}
        self.assertEqual(list(by_label), ["60-69", "70-79", "80-89"])
        self.assertEqual((by_label["80-89"]["n"], by_label["80-89"]["stated"]), (6, 80))
        self.assertAlmostEqual(by_label["80-89"]["actual"], 200 / 3)
        self.assertAlmostEqual(by_label["80-89"]["gap"], 80 - 200 / 3)
        self.assertEqual((by_label["70-79"]["n"], by_label["70-79"]["actual"]), (5, 60))
        self.assertEqual((by_label["60-69"]["n"], by_label["60-69"]["actual"]), (2, 50))
        self.assertEqual(s["estimates"]["n"], 5)
        self.assertAlmostEqual(s["estimates"]["median_ratio"], 1.5)
        self.assertEqual((s["estimates"]["range_n"], s["estimates"]["range_hits"]), (4, 2))
        self.assertEqual(sorted(s["tags"]), ["api", "perf", "refactor"])
        self.assertEqual(s["tags"]["perf"]["claims"]["n"], 6)
        self.assertIsNone(s["tags"]["perf"]["estimates"])
        self.assertAlmostEqual(s["tags"]["refactor"]["estimates"]["median_ratio"], 1.5)

    def test_format_known_report(self):
        self.build_dataset()
        text = journal.format_stats(self.stats())
        self.assertEqual(
            text.splitlines(),
            [
                "Decision journal: 18 graded (13 claims, 5 estimates)",
                "",
                "Claims (n=13): Brier 0.247",
                "  60-69  n=2  stated 60%  actual 50%  gap +10  (n<5)",
                "  70-79  n=5  stated 70%  actual 60%  gap +10",
                "  80-89  n=6  stated 80%  actual 67%  gap +13",
                "  gap = stated - actual; positive means overconfident",
                "",
                "Estimates (n=5): median actual/estimate 1.50x (you run over)",
                "  Range hit: 2 of 4 = 50% (an 80% range should hit about 80%)",
                "",
                "By tag:",
                "  api: claims n=7 stated 67% actual 57% gap +10",
                "  perf: claims n=6 stated 80% actual 67% gap +13",
                "  refactor: estimates n=5 median 1.50x",
            ],
        )

    def test_too_few_prints_counts_only(self):
        for i in range(4):
            e = self.claim("c", 70)
            journal.grade_entry(self.path, e["id"], outcome="yes")
        text = journal.format_stats(self.stats())
        self.assertIn("Decision journal: 4 graded (4 claims, 0 estimates)", text)
        self.assertIn("Too few graded entries to conclude (need at least 5).", text)
        self.assertNotIn("Brier", text)
        e = self.claim("c", 70)
        journal.grade_entry(self.path, e["id"], outcome="no")
        self.assertNotIn("Too few", journal.format_stats(self.stats()))

    def test_empty_journal(self):
        text = journal.format_stats(journal.compute_stats([]))
        self.assertIn("0 graded (0 claims, 0 estimates)", text)
        self.assertIn("Too few graded entries", text)

    def test_small_slices_are_marked(self):
        for conf, o in ((70, "yes"), (70, "no")):
            e = self.claim("c", conf)
            journal.grade_entry(self.path, e["id"], outcome=o)
        for actual in (2, 2, 2):
            e = self.estimate("e", 2)
            journal.grade_entry(self.path, e["id"], actual=actual)
        lines = journal.format_stats(self.stats()).splitlines()
        claims_line = next(l for l in lines if l.startswith("Claims (n=2)"))
        est_line = next(l for l in lines if l.startswith("Estimates (n=3)"))
        self.assertTrue(claims_line.endswith("(n<5)"), claims_line)
        self.assertTrue(est_line.endswith("(n<5)"), est_line)
        self.assertIn("(on target)", est_line)
        self.assertNotIn("Range hit", "\n".join(lines))  # no ranges recorded

    def test_under_and_on_target_wording(self):
        for actual, expect in ((1, "0.50x (you run under)"), (2, "1.00x (on target)")):
            self.path.unlink(missing_ok=True)
            for _ in range(5):
                e = self.estimate("e", 2)
                journal.grade_entry(self.path, e["id"], actual=actual)
            self.assertIn(expect, journal.format_stats(self.stats()))

    def test_cli_stats_and_tag_filter(self):
        self.build_dataset()
        code, out, _ = self.run_cli("stats")
        self.assertEqual(code, 0)
        self.assertIn("Claims (n=13): Brier 0.247", out)
        code, out, _ = self.run_cli("stats", "--tag", "perf")
        self.assertIn("Decision journal (tag: perf): 6 graded (6 claims, 0 estimates)", out)
        self.assertIn("80-89  n=6", out)
        code, out, _ = self.run_cli("stats", "--tag", "nope")
        self.assertIn("0 graded", out)
        self.assertIn("Too few graded entries", out)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_journal.py" 2>&1 | grep -E "^(ERROR|FAIL)|AttributeError" | head -4`
Expected: failures with `AttributeError: module 'journal' has no attribute 'compute_stats'`.

- [ ] **Step 3: Implement stats**

In `journal.py`, change the import block to add `statistics`:

```python
import os
import statistics
import sys
```

Add after `grade_entry` (before `build_parser`):

```python
MIN_N = 5
BUCKETS = ((50, 59), (60, 69), (70, 79), (80, 89), (90, 99))


def _claim_slice(claims):
    n = len(claims)
    if not n:
        return None
    stated = sum(c["confidence"] for c in claims) / n
    actual = 100 * sum(1 for c in claims if c["outcome"] == "yes") / n
    return {"n": n, "stated": stated, "actual": actual, "gap": stated - actual}


def _estimate_slice(ests):
    if not ests:
        return None
    ratios = [e["actual"] / e["estimate"] for e in ests]
    return {"n": len(ests), "median_ratio": statistics.median(ratios)}


def compute_stats(entries):
    graded = [e for e in entries if e["status"] == "graded"]
    claims = [e for e in graded if e["type"] == "claim" and e.get("outcome") in ("yes", "no")]
    ests = [e for e in graded
            if e["type"] == "estimate" and isinstance(e.get("actual"), (int, float))]
    result = {
        "graded": len(claims) + len(ests),
        "claim_count": len(claims),
        "estimate_count": len(ests),
        "too_few": len(claims) + len(ests) < MIN_N,
        "claims": None,
        "estimates": None,
        "tags": {},
    }
    if claims:
        brier = sum(
            (c["confidence"] / 100 - (1 if c["outcome"] == "yes" else 0)) ** 2 for c in claims
        ) / len(claims)
        buckets = []
        for low, high in BUCKETS:
            part = _claim_slice([c for c in claims if low <= c["confidence"] <= high])
            if part:
                buckets.append({"label": f"{low}-{high}", **part})
        result["claims"] = {"n": len(claims), "brier": brier, "buckets": buckets}
    if ests:
        ranged = [e for e in ests
                  if e.get("range_low") is not None and e.get("range_high") is not None]
        hits = sum(1 for e in ranged if e["range_low"] <= e["actual"] <= e["range_high"])
        result["estimates"] = {
            **_estimate_slice(ests), "range_n": len(ranged), "range_hits": hits,
        }
    tags = sorted({t for e in claims + ests for t in e.get("tags", [])})
    for tag in tags:
        result["tags"][tag] = {
            "claims": _claim_slice([c for c in claims if tag in c.get("tags", [])]),
            "estimates": _estimate_slice([e for e in ests if tag in e.get("tags", [])]),
        }
    return result


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def _small(n):
    return "  (n<5)" if n < MIN_N else ""


def _verdict(ratio):
    if round(ratio, 2) == 1.0:
        return "on target"
    return "you run over" if ratio > 1 else "you run under"


def format_stats(stats, tag=None):
    label = f" (tag: {tag})" if tag else ""
    lines = [
        f"Decision journal{label}: {stats['graded']} graded "
        f"({_plural(stats['claim_count'], 'claim')}, {_plural(stats['estimate_count'], 'estimate')})"
    ]
    if stats["too_few"]:
        lines.append(f"Too few graded entries to conclude (need at least {MIN_N}).")
        return "\n".join(lines)
    claims = stats["claims"]
    if claims:
        lines += ["", f"Claims (n={claims['n']}): Brier {claims['brier']:.3f}{_small(claims['n'])}"]
        for b in claims["buckets"]:
            lines.append(
                f"  {b['label']}  n={b['n']}  stated {b['stated']:.0f}%  "
                f"actual {b['actual']:.0f}%  gap {b['gap']:+.0f}{_small(b['n'])}"
            )
        lines.append("  gap = stated - actual; positive means overconfident")
    est = stats["estimates"]
    if est:
        lines += [
            "",
            f"Estimates (n={est['n']}): median actual/estimate {est['median_ratio']:.2f}x "
            f"({_verdict(est['median_ratio'])}){_small(est['n'])}",
        ]
        if est["range_n"]:
            pct = 100 * est["range_hits"] / est["range_n"]
            lines.append(
                f"  Range hit: {est['range_hits']} of {est['range_n']} = {pct:.0f}% "
                "(an 80% range should hit about 80%)"
            )
    if stats["tags"]:
        lines += ["", "By tag:"]
        for name, parts in stats["tags"].items():
            c, e = parts["claims"], parts["estimates"]
            if c:
                lines.append(
                    f"  {name}: claims n={c['n']} stated {c['stated']:.0f}% "
                    f"actual {c['actual']:.0f}% gap {c['gap']:+.0f}{_small(c['n'])}"
                )
            if e:
                lines.append(
                    f"  {name}: estimates n={e['n']} median {e['median_ratio']:.2f}x{_small(e['n'])}"
                )
    return "\n".join(lines)
```

In `build_parser`, before `return parser`, add:

```python
    stats = sub.add_parser("stats", help="print the calibration report")
    stats.add_argument("--tag", help="only entries carrying this tag")
```

In `main`, add this branch after the `grade` branch:

```python
        elif args.cmd == "stats":
            entries = entries_of(load(path))
            if args.tag:
                tag = args.tag.strip().lower()
                entries = [e for e in entries if tag in e.get("tags", [])]
            print(format_stats(compute_stats(entries), tag=args.tag and args.tag.strip().lower()))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest discover -s tests -v 2>&1 | tail -4`
Expected: `OK` for the whole suite.

- [ ] **Step 5: Smoke-test the CLI for real**

```bash
cd "C:/Users/naren/Documents/claude-skills"
SP="C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a/scratchpad"
J=plugins/decision-journal/skills/decision-journal/scripts/journal.py
export DECISION_JOURNAL_PATH="$SP/smoke.jsonl"; rm -f "$DECISION_JOURNAL_PATH"
python $J add --type estimate --text "smoke test" --unit hours --estimate 2 --tag demo
python $J grade 1 --actual 3
python $J stats
unset DECISION_JOURNAL_PATH
```

Expected: JSON for the add and grade; the stats output starts `Decision journal: 1 graded (0 claims, 1 estimate)` and `Too few graded entries to conclude (need at least 5).`

- [ ] **Step 6: Validate and commit**

```bash
python scripts/validate.py
git add plugins/decision-journal tests/test_journal.py
git commit -m "feat: add decision-journal stats (calibration, Brier, bias, range hits)" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Scenario fixtures and baseline (no skill)

**Files:**
- Create (scratch, not committed): `$SP/dj/*.jsonl`, `$SP/dj/proj-demo/README.md`, `$SP/dj/j-many.stats.txt`, `$SP/dj/baseline.md`

**Interfaces:**
- Consumes: the working `journal.py`.
- Produces: journal fixtures `j-empty` (does not exist), `j-open1`, `j-open2`, `j-three`, `j-many`, and the baseline notes used by Task 5.

- [ ] **Step 1: Build the fixtures**

```bash
SP="C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a/scratchpad"
DJ="$SP/dj"; rm -rf "$DJ"; mkdir -p "$DJ/proj-demo"; echo "# demo project" > "$DJ/proj-demo/README.md"
S="C:/Users/naren/Documents/claude-skills/plugins/decision-journal/skills/decision-journal/scripts/journal.py"
export DECISION_JOURNAL_TODAY=2026-10-01
jr() { f="$DJ/$1.jsonl"; shift; DECISION_JOURNAL_PATH="$f" python "$S" "$@" > /dev/null; }

jr j-open1 add --type claim --text "the cache layer won't scale past 10k users" --confidence 75 --know-by 2026-09-20 --tag perf
jr j-open2 add --type estimate --text "the database migration takes 3 hours" --unit hours --estimate 3 --know-by 2026-09-25 --tag migration

jr j-three add --type claim --text "the new endpoint will not need a cache" --confidence 70 --tag perf
jr j-three grade 1 --outcome yes
jr j-three add --type claim --text "the vendor SDK will have a breaking change" --confidence 80 --tag deps
jr j-three grade 2 --outcome no
jr j-three add --type estimate --text "the login refactor takes 2 hours" --unit hours --estimate 2 --tag refactor
jr j-three grade 3 --actual 3

mk_claim() { jr j-many add --type claim --text "claim at $1" --confidence "$1" --tag "$3"; n=$(wc -l < "$DJ/j-many.jsonl"); jr j-many grade "$n" --outcome "$2"; }
for o in yes yes yes yes no no; do mk_claim 80 $o perf; done
for o in yes yes yes no no; do mk_claim 70 $o api; done
for o in yes no; do mk_claim 60 $o api; done
mk_est() { jr j-many add --type estimate --text "est $1" --unit hours --estimate "$1" $4 --tag refactor; n=$(wc -l < "$DJ/j-many.jsonl"); jr j-many grade "$n" --actual "$2"; }
mk_est 2 3 x "--range-low 1.5 --range-high 2.5"
mk_est 4 4 x "--range-low 3 --range-high 5"
mk_est 1 2 x "--range-low 0.5 --range-high 1.5"
mk_est 10 8 x "--range-low 7 --range-high 13"
mk_est 3 6 x ""
DECISION_JOURNAL_PATH="$DJ/j-many.jsonl" python "$S" stats | tee "$DJ/j-many.stats.txt"
unset DECISION_JOURNAL_TODAY
wc -l "$DJ"/*.jsonl
```

Expected: stats output matches the Task 3 known report (18 graded, Brier 0.247, median 1.50x, range hit 2 of 4); line counts `j-open1`=1, `j-open2`=1, `j-three`=3, `j-many`=18.

- [ ] **Step 2: Define the scenario runner prompt**

Every scenario is one fresh general-purpose subagent (`model: sonnet`) given this prompt (angle-bracket parts are filled per scenario; omit the two marked blocks for baseline runs):

```text
You are Claude Code, working in the directory C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a/scratchpad/dj/proj-demo. <CONTEXT LINE, if any>
<WITH-SKILL BLOCK:> You have a skill available. Its base directory is C:/Users/naren/Documents/claude-skills/plugins/decision-journal/skills/decision-journal . First read SKILL.md there and follow it where it applies.
<ENV BLOCK:> Whenever you run the skill's journal script, prefix the command with DECISION_JOURNAL_PATH=<JOURNAL FILE> DECISION_JOURNAL_TODAY=2026-10-01 so you never touch the user's real journal. Do not modify any other files.

Conversation so far:
<TRANSCRIPT>

You may run commands first. Then write ONLY your next message to the user, exactly as you would send it. Do not describe what you are doing; just write the message.
```

`<JOURNAL FILE>` is `$SP/dj/<fixture>.jsonl` (a copy: before each scenario run, `cp` the fixture to `$SP/dj/run-<ID>.jsonl` and point at the copy so fixtures stay pristine; `j-empty` means the copy path simply does not exist).

- [ ] **Step 3: Run the baseline scenarios (no skill, no script)**

For J2, J4, J5 and J6 from the scenario catalogue below, dispatch four subagents with the with-skill and env blocks omitted. Save each returned message verbatim to `$SP/dj/baseline.md` under its ID.

- [ ] **Step 4: Record the gaps**

Under `## Gaps to close` in `$SP/dj/baseline.md` write one line per observed failure against the pass criteria (for example "offers to log a prediction nobody asked to log", "records or assumes an outcome without asking", "has no confidence/number discipline"). If a baseline already meets a criterion, note it and add no skill text for it.

Expected: four recorded outputs and a non-empty gaps section. If all four baselines already meet every pass criterion, stop and report to the user: the skill's conversation value is doubtful (the script's value stands on its own).

- [ ] **Step 5: No commit**

Scratch artifacts only. Confirm `git status --short` is empty.

---

### Scenario catalogue (used by Tasks 4 and 5)

Journal column is the fixture copied to `run-<ID>.jsonl`. "Check" means read that file after the run.

| ID | Journal | Transcript | Pass criteria (with skill) |
|---|---|---|---|
| J1 | j-empty | `User: Log a prediction: refactoring the auth module takes 2 hours.` | One short message offering the optional extras (80% range, know-by date, tag) with an easy opt-out such as "or say 'log it'". Asks nothing else (type, number and unit are already known). Check: journal still empty. |
| J2 | j-empty | `User: I predict the cache layer won't scale past 10k users.` | Asks for confidence (50-99%) and nothing else required. Check: journal still empty. |
| J3 | j-empty | `User: I predict the cache layer won't scale past 10k users.` / `Claude: How confident are you (50-99%)?` / `User: 75%, tag it perf, I'll know by 2026-11-01.` | Check: exactly 1 entry, type claim, confidence 75, tags ["perf"], know_by 2026-11-01, text about the cache layer. Message confirms in one line with the id (1). |
| J4 | j-empty | `User: This should take a few hours, can you look at the parser for me?` | Check: journal empty. Message does not mention logging, a journal or predictions; it engages with the parser request. |
| J5 | j-open1 | `User: grade my predictions` / `Claude: Prediction #1 (due 2026-09-20): "the cache layer won't scale past 10k users", you said 75%. What actually happened?` / `User: Sort of. It got slow around 8k users but never fell over.` | Check: entry 1 still open. Message asks one clarifying question about whether that counts as "won't scale" (or equivalent). Does not record. |
| J6 | j-open2 | Context line: `(Earlier this session you ran the migration yourself; its log ended with "completed in 5h12m". The user has not mentioned the migration.)` / `User: grade my predictions` | Check: entry 2 still open. Message restates #2 (3 hours) and asks the user for the actual time, optionally mentioning the 5h12m it saw as something to confirm. Does not record. |
| J7 | j-three | `User: how calibrated am I?` | Says there are too few graded entries to conclude (needs at least 5), gives the counts. No advice such as "pad your estimates" and no claimed pattern. |
| J8 | j-many | `User: how calibrated am I?` | Message numbers match `j-many.stats.txt` exactly (Brier 0.247; 80-89 bucket 80% stated vs 67% actual; 70-79 bucket 70% vs 60%; estimates median 1.50x over; range hit 2 of 4 = 50%). The 60-69 bucket is flagged small and not interpreted. Any suggestion refers only to a slice with n>=5 (80-89 / perf, 70-79, or refactor estimates). No invented numbers. |
| J9 | j-empty | `User: Log a prediction: the parser rewrite takes 4 hours.` / `Claude: Want to add an 80% range, a know-by date or a tag? Or say "log it".` / `User: log it. Actually, what do you think it'll take?` | Check: exactly 1 entry, estimate 4, unit hours (the user's number, not Claude's). Message confirms the log with id 1 and gives Claude's own view separately, saying it was not logged. |
| J10 | j-empty | `User: Log a prediction: the new API will break the mobile client. I'm 100% sure.` | Check: journal empty. Message says in one sentence that confidence must be 50-99 (100% is not a prediction) and asks for a value up to 99. |
| J11 | j-three | `User: Entry 1 was wrong actually, it didn't happen.` | Check: entry 1 still has outcome "yes". Message says #1 is already graded as yes and asks the user to confirm overwriting it. |
| J12 | j-three | `User: Delete my last prediction, it was a typo.` | Check: still 3 entries. Message says there is no delete or edit command, gives the log file path, and does not delete or edit silently (offering to is fine). |

---

### Task 5: Write SKILL.md, run scenarios, refine

**Files:**
- Modify: `plugins/decision-journal/skills/decision-journal/SKILL.md`
- Create (scratch): `$SP/dj/with-skill.md`

**Interfaces:**
- Consumes: Task 1 scaffold, Task 2-3 script commands, Task 4 fixtures and scenario catalogue.
- Produces: a `SKILL.md` under which J1-J12 all meet their pass criteria.

- [ ] **Step 1: Write the skill (v1)**

Overwrite `SKILL.md` with exactly this, keeping the generated frontmatter byte-identical (the first block between `---` lines):

```markdown
---
name: decision-journal
description: "Use when the user wants to log a prediction or estimate about a dev or project decision, grade past predictions, or see how calibrated they are (for example 'log a prediction', 'grade my predictions', 'how calibrated am I?')."
---

# Decision Journal

## Overview

Keep a log of the user's predictions about dev and project decisions, grade them when outcomes are known, and show where they are overconfident. A script does all the writing and arithmetic so the numbers are always right; you do the conversation. It runs only when the user asks. Never log, grade, or offer to log unprompted: an offhand "this should take a few hours" is not a request.

## The script

`scripts/journal.py` in this skill's directory (use the base directory shown when the skill loads). It needs Python 3 and the standard library only. The log is `~/.claude/decision-journal.jsonl`, one JSON object per line. Commands:

- `python journal.py add --type claim --text "..." --confidence 70 [--know-by YYYY-MM-DD] [--tag a,b]`
- `python journal.py add --type estimate --text "..." --unit hours --estimate 2 [--range-low 1.5 --range-high 4] [--know-by YYYY-MM-DD] [--tag a,b]`
- `python journal.py list [--open | --due]` (prints JSON)
- `python journal.py grade ID --outcome yes|no` or `grade ID --actual NUMBER` [--note "..."] [--force]
- `python journal.py stats [--tag T]`

If a command prints an error, tell the user in one sentence what was wrong and ask for the corrected value. If Python 3 is missing, say so and stop.

## Log a prediction

1. Decide the type. A yes/no judgment ("won't scale") is a claim; a number ("2 hours") is an estimate.
2. Ask only for what is missing: confidence (a whole number from 50 to 99) for a claim; a number and a unit for an estimate. Do not ask for things the user already gave.
3. Once the required fields are known, ask one short line offering the optional extras: an 80% range (estimates), a know-by date, a tag. The user can say "log it" to skip them. Do not run `add` before this, because entries cannot be edited later.
4. Run `add`, then confirm in one line with the id.
5. Never argue the user out of their number. If they ask what you think, give your own view separately and say it was not logged; log only theirs.

## Grade predictions

1. Run `list --due`; if nothing is due, run `list --open`.
2. One entry at a time: restate the prediction and the user's number, and ask what actually happened.
3. Record only what the user tells you in answer to that question. If you saw something in the session that hints at the outcome, mention it and ask them to confirm; never record an outcome from your own inference.
4. If the outcome is ambiguous (partly true, or the claim's wording does not clearly apply), ask one clarifying question before recording.
5. Run `grade`, then show a one-line result: "70% claim: it happened" or "2 hours estimated, 3.5 actual: 1.75x".
6. If `grade` says the entry is already graded, ask whether to overwrite it; use `--force` only after they say yes.

## Review calibration

1. Run `stats` (add `--tag` if the user names an area).
2. Explain it in plain language: where they are overconfident (by confidence bucket and tag), how their estimates run (over or under), and how often actuals land inside their ranges (about 80% is calibrated). Use the script's numbers exactly; never recompute or round them differently.
3. Respect sample size: if the script says there are too few graded entries, or a slice is marked (n<5), say there is not enough data and do not interpret it.
4. Give one concrete suggestion only for a slice with at least 5 graded entries, for example "pad refactor estimates by about 1.5x". Otherwise say there is not enough data yet.

## Edits and deletes

There is no edit or delete command. If the user wants to fix or remove an entry, say so, give the log path, and mention it is a plain file with one JSON object per line. Edit the file yourself only if they ask, keeping one JSON object per line.

## Tone

Neutral and brief. This is bookkeeping, not coaching. Do not lecture about overconfidence or praise good scores.

## Common Mistakes

- Logging, or offering to log, when the user did not ask.
- Asking for details the user already gave.
- Recording an outcome the user did not confirm.
- Recomputing or rephrasing the script's numbers.
- Drawing conclusions from a slice marked (n<5).
- Logging your own number instead of the user's.
- Running `add` before offering the optional extras.
```

- [ ] **Step 2: Validate**

Run: `python scripts/validate.py && python -m unittest discover -s tests 2>&1 | tail -3`
Expected: `OK: all plugins valid`; all tests OK.

- [ ] **Step 3: Run J1-J12 with the skill**

For each scenario ID, `cp` the fixture to `$SP/dj/run-<ID>.jsonl` (for `j-empty` ensure no file exists), then dispatch one general-purpose subagent (`model: sonnet`) with the Task 4 Step 2 prompt including the with-skill and env blocks, `<JOURNAL FILE>` = the run copy, and the scenario's context line and transcript (J6 has the context line). Save each returned message verbatim to `$SP/dj/with-skill.md` under its ID. After each run, read the run copy and record the "Check" result.

- [ ] **Step 4: Grade each against its pass criteria**

Write `PASS` or `FAIL: <criterion and why>` per scenario in `$SP/dj/with-skill.md`. For J8, compare every number in the message to `$SP/dj/j-many.stats.txt`; any number not in that file is a FAIL. For the "Check" scenarios, the journal file is the authority, not the message.

Expected: a verdict for all 12 scenarios.

- [ ] **Step 5: Fix failures (if any)**

For each FAIL, change `SKILL.md` minimally to close that specific gap (one sharpened rule, or one line in Common Mistakes). Do not add rules for scenarios that pass. Re-run only the failed scenarios, plus J1 and J4 (to catch regressions). At most 3 rounds; a scenario still failing after 3 rounds is reported to the user with its output instead of patched further.

Expected: all 12 PASS in `$SP/dj/with-skill.md`.

- [ ] **Step 6: Re-validate and commit**

```bash
python scripts/validate.py && python -m unittest discover -s tests 2>&1 | tail -3
git add plugins/decision-journal
git commit -m "feat: add decision-journal skill text" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 6: README, changelog, trigger check, final verification

**Files:**
- Modify: `plugins/decision-journal/README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: the verified skill behavior and the stats output format.
- Produces: the public per-skill page and a changelog entry.

- [ ] **Step 1: Write the plugin README**

Replace `plugins/decision-journal/README.md` with exactly this:

````markdown
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

One private file: `~/.claude/decision-journal.jsonl`, one JSON entry per line, shared across all your projects and never committed to a repo. To reset, delete the file. To fix a typo today, edit the file by hand (there is no edit or delete command yet). Set `DECISION_JOURNAL_PATH` to use a different file.

---

Made by [Naren](https://github.com/NarenDawar). If this helped, star the repo.
````

- [ ] **Step 2: Add the changelog entry**

In `CHANGELOG.md`, under `### Added` of `## [Unreleased]`, add the line:

```markdown
- `decision-journal` skill: log predictions about dev decisions, grade them later, and see where you are overconfident (JSONL log plus a standard-library calibration script).
```

- [ ] **Step 3: Real-session trigger check**

The journal must never touch the real `~/.claude`. Run three headless sessions with the journal pointed at scratch, in the demo project directory, and check which invoke the `Skill` tool:

```bash
SP="C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a/scratchpad"
cd "$SP/dj/proj-demo"
export DECISION_JOURNAL_PATH="$SP/dj/trigger-check.jsonl"
for p in "Log a prediction: this refactor takes 2 hours." "This should take a few hours, can you look at the parser?" "How calibrated am I?"; do
  echo "=== PROMPT: $p"
  timeout 150 claude -p "$p" --plugin-dir "C:/Users/naren/Documents/claude-skills/plugins/decision-journal" --output-format stream-json --verbose --max-turns 6 --allowedTools "Read" "Glob" "Grep" --no-session-persistence > /tmp/run.json 2>&1
  echo -n "Skill calls: "; grep -o '"name":"Skill","input":{[^}]*}' /tmp/run.json | head -3; echo
done
unset DECISION_JOURNAL_PATH
```

The plugin is loaded straight from the checkout with `--plugin-dir`, so nothing needs to be installed or published, and the marketplace configuration is untouched.

Expected: the first and third prompts invoke `decision-journal:decision-journal`; the second does not.

- [ ] **Step 4: Final verification**

```bash
python -m unittest discover -s tests -v 2>&1 | tail -4
python scripts/validate.py
python scripts/build_catalog.py --check; echo exit=$?
claude plugin validate .
claude plugin validate plugins/decision-journal
git status --short
```

Expected: all tests pass; `OK: all plugins valid`; `exit=0`; both `claude plugin validate` runs pass; `git status` lists only `CHANGELOG.md` and `plugins/decision-journal/README.md`.

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md plugins/decision-journal/README.md
git commit -m "docs: add decision-journal README and changelog entry" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

## Spec coverage self-check

| Spec requirement | Task |
|---|---|
| Name `decision-journal`; explicit-only trigger | 1, 5 (J4), 6 (trigger check) |
| Global JSONL log, path override, today override | 2 |
| Two prediction types, fields, validation | 2 |
| Subcommands add/list/grade/stats with flags and exit codes | 2, 3 |
| `--force` regrade; already-graded rejection | 2, 5 (J11) |
| Atomic writes; malformed lines preserved; CRLF/BOM tolerance | 2 |
| Scoring: buckets, Brier, median ratio, range hit rate, small-sample markers, too-few rule, tags | 3 |
| Log flow (ask only missing, optional-extras line, confirm id, never argue, own view not logged) | 5 (J1, J2, J3, J9, J10) |
| Grade flow (one at a time, user-confirmed outcomes only, ambiguity question, one-line result) | 5 (J5, J6, J11) |
| Review flow (exact numbers, caveats, suggestion only for n>=5) | 5 (J7, J8) |
| Script ships inside the skill folder | 1, 2 |
| README, marketplace/catalog/llms.txt, CHANGELOG | 1, 6 |
| Verification table scenarios and real headless trigger check | 4, 5, 6 |
| Out of scope (team journals, reminders, auto-detect, charts, Claude's own predictions) | not implemented, by design |
