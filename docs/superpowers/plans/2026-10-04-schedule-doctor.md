# schedule-doctor Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and ship the `schedule-doctor` skill: a pre-flight that lints a scheduled task's prompt (likely tools, time guard, staleness hints) and checks the OS sleep settings, and a post-mortem that classifies why a scheduled run did not fire or halted.

**Architecture:** One plugin, `plugins/schedule-doctor/`, scaffolded by `scripts/new_skill.py`. Three stdlib scripts live in the skill folder: `preflight.py` (prompt lint), `power_check.py` (OS sleep settings) and `diagnose.py` (classify a normalized run record). `SKILL.md` owns the judgment: how to fetch task state through each surface's tools, what to show, when to ask. Scripts never read an app's task store; they take text or a JSON record. Each script is built test-first with `unittest` on hand-made fixtures labelled synthetic (plus real `powercfg` captures from this machine where they exist).

**Tech Stack:** Python 3.9+ standard library, Markdown, JSON, the repo tooling.

**Spec:** `docs/superpowers/specs/2026-10-04-schedule-doctor-design.md`

## Global Constraints

- Plugin and skill name `schedule-doctor`; `SKILL.md` frontmatter has `name` and a single-line, double-quoted `description` starting with `Use when`; no branding footer in `SKILL.md`.
- Python 3.9+ standard library only; files written with LF line endings; UTF-8 read with BOM tolerance; no network access in any script.
- All three scripts are read-only. They never write anywhere.
- Task state is read through the scheduling tools by the agent, never by scraping an app's files from disk. No auto-editing, running or retrying of tasks.
- A timestamp without an offset is read as UTC.
- `diagnose.py` late threshold is a named constant (default 30 minutes) and is printed in the output. `slept-through` is returned only when there is sleep or lid evidence; otherwise `never-ran-unknown` ("not enough data"), never a guess.
- The tool list from `preflight.py` is a heuristic: the output says "likely needs", never "will need".
- `power_check.py` cannot see Claude Desktop's Keep computer awake toggle and says so; the agent asks the user.
- Malformed or missing JSON, an unreadable prompt file, an unparseable timestamp and an unsupported OS each print a one-line `error: ...` and exit 2, with no traceback.
- Prompts and transcripts are never printed beyond short matched snippets. Script output is ASCII only.
- Test fixtures are hand-made and labelled synthetic (a `_note` starting `SYNTHETIC` in JSON, `_synthetic` in the file name for text), except captures from this machine, labelled `_real`.
- The skill never edits a scheduled task without showing the diff and getting an explicit yes in the conversation.
- Author `Naren`; GitHub user `NarenDawar`; repo `narens-claude-skills`; marketplace `narens-claude-skills`. Free and MIT.
- Do not push to GitHub in this plan; pushing is a separate, explicit user request.
- Work on branch `schedule-doctor` (already created, holds the spec commit).
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

Failure modes the spec implies but a first pass is likely to skip. Each has a test in the task that owns the code:

1. A run the user started by hand before its scheduled time (negative delay) must read as `healthy`, not `late-catchup`. (Task 2)
2. A sleep that ended before the scheduled time (sleep then wake) is not sleep evidence; a sleep that began after it is not either. (Task 2)
3. A run that started on time but failed with an error must not read as `healthy`: it is `failed-unknown`. This is a small addition to the spec's verdict list, made in Task 1. (Task 2)
4. A prompt file with CRLF line endings, a BOM, an empty body, or a prompt that only says "skip" with no condition: line numbers stay right, the BOM is ignored, empty is an error, and a bare "skip" is not counted as a time guard. A verb such as "make a summary" is not the `make` command. (Task 3)
5. A desktop with no lid setting, a non-English or unparseable `powercfg` output, and an unsupported OS: unreadable values become "could not be read" or "no setting found", `keeps_awake` becomes unknown instead of a wrong yes, and an unsupported OS is a clean error. (Task 4)

---

### Task 1: Scaffold the plugin and align the spec

**Files:**
- Create (by script): `plugins/schedule-doctor/` (from `template/`), updates `.claude-plugin/marketplace.json`, `README.md` catalog, `llms.txt`
- Modify: `docs/superpowers/specs/2026-10-04-schedule-doctor-design.md`

**Interfaces:**
- Produces: the folder `plugins/schedule-doctor/skills/schedule-doctor/` that Tasks 2-4 put `scripts/` into, and the placeholder `SKILL.md` and `README.md` that Task 5 replaces.

- [ ] **Step 1: Run the scaffold script**

```bash
python scripts/new_skill.py schedule-doctor "Use when the user is about to schedule a Claude task, or asks why a scheduled task, /loop, cron job or routine did not run, ran late, or stopped partway (for example 'will this scheduled task actually run?', 'why didn't my 7am task fire?', 'check this before I schedule it')."
```

Expected: exits 0 and creates `plugins/schedule-doctor/`.

- [ ] **Step 2: Confirm the scaffold and that the repo still validates**

```bash
git status --short
python scripts/validate.py
python -m unittest discover -s tests
```

Expected: `plugins/schedule-doctor/**`, `.claude-plugin/marketplace.json`, `README.md` and `llms.txt` changed or added; `OK: all plugins valid`; all existing tests pass.

- [ ] **Step 3: Align the spec with decisions made while planning**

In `docs/superpowers/specs/2026-10-04-schedule-doctor-design.md`, make these edits:

(a) In the layout block replace

```
tests/
  test_schedule_doctor_*.py
  fixtures/schedule_doctor/   (synthetic, labelled)
```

with

```
tests/
  test_diagnose.py
  test_preflight.py
  test_power_check.py
  fixtures/schedule_doctor/   (records/ and power/; synthetic unless named _real)
```

(b) In the `diagnose.py` verdict table add this row after the `healthy` row:

```
| `failed-unknown` | Started on time and ended with an error text or a failed status that is not a permission halt. The error text is shown (first 200 characters). |
```

(c) In the Testing section replace "one fixture per verdict (permission halt, slept-through, late catch-up, healthy, unknown)" with "one fixture per verdict (permission halt, slept-through, late catch-up, healthy, failed-unknown, never-ran-unknown)".

(d) Under `preflight.py` add the bullet: "A prompt larger than 20,000 characters is refused with a one-line error (a scheduled prompt that size is a mistake, and the bounded patterns are only fast on small input)."

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat: scaffold schedule-doctor and align its spec

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `diagnose.py`, the post-mortem classifier

**Files:**
- Create: `plugins/schedule-doctor/skills/schedule-doctor/scripts/diagnose.py`
- Create: `tests/test_diagnose.py`
- Create: `tests/fixtures/schedule_doctor/records/{healthy,permission_halt,slept_through,late_catchup,never_ran_unknown,failed_unknown}.json`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `diagnose.classify(record: dict, late_minutes: float = 30) -> {"verdict": str, "why": str, "evidence": dict}`; `diagnose.DiagnoseError`; `diagnose.main(argv=None) -> int` (0 on any verdict, 2 on error); constants `LATE_MINUTES = 30`, `SURFACES`. Verdict strings: `permission-halt`, `slept-through`, `late-catchup`, `never-ran-unknown`, `failed-unknown`, `healthy`. Task 5's SKILL.md documents the record shape and the verdicts.

- [ ] **Step 1: Write the fixtures**

Each file starts with a `_note` so nobody mistakes it for a captured run.

`tests/fixtures/schedule_doctor/records/healthy.json`:

```json
{
  "_note": "SYNTHETIC: hand-made record, not captured from a real run.",
  "surface": "desktop",
  "scheduled_for": "2026-10-04T07:00:00+00:00",
  "started_at": "2026-10-04T07:00:05+00:00",
  "ended_at": "2026-10-04T07:03:00+00:00",
  "status": "completed",
  "last_event": "completed",
  "error_text": null,
  "permission_denied_tool": null,
  "machine_events": []
}
```

`permission_halt.json`:

```json
{
  "_note": "SYNTHETIC: hand-made record, not captured from a real run.",
  "surface": "desktop",
  "scheduled_for": "2026-10-04T07:00:00+00:00",
  "started_at": "2026-10-04T07:00:04+00:00",
  "ended_at": "2026-10-04T07:00:40+00:00",
  "status": "halted",
  "last_event": "permission-denied",
  "error_text": null,
  "permission_denied_tool": "Bash(git push)",
  "machine_events": []
}
```

`slept_through.json`:

```json
{
  "_note": "SYNTHETIC: hand-made record, not captured from a real run.",
  "surface": "desktop",
  "scheduled_for": "2026-10-04T07:00:00+00:00",
  "started_at": null,
  "ended_at": null,
  "status": "missed",
  "last_event": null,
  "error_text": null,
  "permission_denied_tool": null,
  "machine_events": [{"kind": "lid-close", "at": "2026-10-03T22:10:00+00:00"}]
}
```

`late_catchup.json`:

```json
{
  "_note": "SYNTHETIC: hand-made record, not captured from a real run.",
  "surface": "desktop",
  "scheduled_for": "2026-10-04T07:00:00+00:00",
  "started_at": "2026-10-04T10:12:30+00:00",
  "ended_at": "2026-10-04T10:15:00+00:00",
  "status": "completed",
  "last_event": "completed",
  "error_text": null,
  "permission_denied_tool": null,
  "machine_events": [
    {"kind": "lid-close", "at": "2026-10-03T22:10:00+00:00"},
    {"kind": "wake", "at": "2026-10-04T10:10:00+00:00"}
  ]
}
```

`never_ran_unknown.json`:

```json
{
  "_note": "SYNTHETIC: hand-made record, not captured from a real run.",
  "surface": "code-cron",
  "scheduled_for": "2026-10-04T07:00:00+00:00",
  "started_at": null,
  "ended_at": null,
  "status": null,
  "last_event": null,
  "error_text": null,
  "permission_denied_tool": null,
  "machine_events": []
}
```

`failed_unknown.json`:

```json
{
  "_note": "SYNTHETIC: hand-made record, not captured from a real run.",
  "surface": "routine",
  "scheduled_for": "2026-10-04T07:00:00+00:00",
  "started_at": "2026-10-04T07:00:02+00:00",
  "ended_at": "2026-10-04T07:00:09+00:00",
  "status": "failed",
  "last_event": "error",
  "error_text": "exit code 1",
  "permission_denied_tool": null,
  "machine_events": []
}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_diagnose.py`:

```python
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import helpers

sys.path.insert(
    0,
    str(helpers.REPO_ROOT / "plugins" / "schedule-doctor" / "skills" / "schedule-doctor" / "scripts"),
)
import diagnose  # noqa: E402

RECORDS = helpers.REPO_ROOT / "tests" / "fixtures" / "schedule_doctor" / "records"


def rec(**over):
    base = {
        "surface": "desktop",
        "scheduled_for": "2026-10-04T07:00:00+00:00",
        "started_at": "2026-10-04T07:00:05+00:00",
        "ended_at": "2026-10-04T07:03:00+00:00",
        "status": "completed",
        "last_event": "completed",
        "error_text": None,
        "permission_denied_tool": None,
        "machine_events": [],
    }
    base.update(over)
    return base


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = diagnose.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class ClassifyTests(unittest.TestCase):
    def verdict(self, record, **kw):
        return diagnose.classify(record, **kw)["verdict"]

    def test_on_time_clean_run_is_healthy(self):
        self.assertEqual(self.verdict(rec()), "healthy")

    def test_denied_tool_is_permission_halt(self):
        result = diagnose.classify(rec(permission_denied_tool="Bash(git push)", status="halted"))
        self.assertEqual(result["verdict"], "permission-halt")
        self.assertEqual(result["evidence"]["permission_denied_tool"], "Bash(git push)")
        self.assertIn("Bash(git push)", result["why"])

    def test_halt_event_name_alone_is_permission_halt(self):
        self.assertEqual(self.verdict(rec(last_event="Permission-Required")), "permission-halt")

    def test_halt_wins_over_lateness_and_keeps_the_delay(self):
        result = diagnose.classify(
            rec(started_at="2026-10-04T10:00:00+00:00", permission_denied_tool="Write")
        )
        self.assertEqual(result["verdict"], "permission-halt")
        self.assertEqual(result["evidence"]["delay_minutes"], 180.0)

    def test_no_start_while_asleep_is_slept_through(self):
        events = [{"kind": "lid-close", "at": "2026-10-03T22:10:00+00:00"}]
        result = diagnose.classify(rec(started_at=None, ended_at=None, machine_events=events))
        self.assertEqual(result["verdict"], "slept-through")
        self.assertTrue(result["evidence"]["asleep_at_schedule"])

    def test_no_start_without_sleep_evidence_is_unknown(self):
        result = diagnose.classify(rec(started_at=None, ended_at=None))
        self.assertEqual(result["verdict"], "never-ran-unknown")
        self.assertIn("Not enough data", result["why"])

    def test_wake_before_the_schedule_is_not_sleep_evidence(self):
        events = [
            {"kind": "sleep", "at": "2026-10-03T22:00:00+00:00"},
            {"kind": "wake", "at": "2026-10-04T06:30:00+00:00"},
        ]
        self.assertEqual(
            self.verdict(rec(started_at=None, machine_events=events)), "never-ran-unknown"
        )

    def test_sleep_after_the_schedule_is_not_evidence(self):
        events = [{"kind": "sleep", "at": "2026-10-04T07:30:00+00:00"}]
        self.assertEqual(
            self.verdict(rec(started_at=None, machine_events=events)), "never-ran-unknown"
        )

    def test_events_are_sorted_before_use(self):
        events = [
            {"kind": "wake", "at": "2026-10-04T06:30:00+00:00"},
            {"kind": "sleep", "at": "2026-10-03T22:00:00+00:00"},
        ]
        self.assertEqual(
            self.verdict(rec(started_at=None, machine_events=events)), "never-ran-unknown"
        )

    def test_late_start_over_threshold_is_late_catchup(self):
        result = diagnose.classify(rec(started_at="2026-10-04T10:07:00+00:00"))
        self.assertEqual(result["verdict"], "late-catchup")
        self.assertEqual(result["evidence"]["delay_minutes"], 187.0)
        self.assertIn("30", result["why"])

    def test_late_catchup_says_when_the_machine_was_asleep(self):
        events = [{"kind": "sleep", "at": "2026-10-03T22:00:00+00:00"}]
        result = diagnose.classify(
            rec(started_at="2026-10-04T10:07:00+00:00", machine_events=events)
        )
        self.assertEqual(result["verdict"], "late-catchup")
        self.assertIn("asleep", result["why"])

    def test_exactly_the_threshold_is_not_late(self):
        self.assertEqual(self.verdict(rec(started_at="2026-10-04T07:30:00+00:00")), "healthy")

    def test_custom_threshold(self):
        record = rec(started_at="2026-10-04T07:10:00+00:00")
        self.assertEqual(self.verdict(record), "healthy")
        self.assertEqual(self.verdict(record, late_minutes=5), "late-catchup")

    def test_run_started_by_hand_before_the_schedule_is_healthy(self):
        result = diagnose.classify(rec(started_at="2026-10-04T06:40:00+00:00"))
        self.assertEqual(result["verdict"], "healthy")
        self.assertEqual(result["evidence"]["delay_minutes"], -20.0)

    def test_error_text_on_time_is_failed_unknown(self):
        result = diagnose.classify(rec(error_text="exit code 1", status="failed"))
        self.assertEqual(result["verdict"], "failed-unknown")
        self.assertEqual(result["evidence"]["error_text"], "exit code 1")

    def test_failed_status_without_error_text_is_failed_unknown(self):
        self.assertEqual(self.verdict(rec(status="Failed")), "failed-unknown")

    def test_long_error_text_is_cut_to_200_characters(self):
        result = diagnose.classify(rec(error_text="x" * 500))
        self.assertEqual(len(result["evidence"]["error_text"]), 200)

    def test_timestamp_without_offset_is_read_as_utc(self):
        result = diagnose.classify(
            rec(scheduled_for="2026-10-04T07:00:00", started_at="2026-10-04T07:00:05Z")
        )
        self.assertEqual(result["evidence"]["delay_minutes"], 0.1)
        self.assertEqual(result["evidence"]["scheduled_for"], "2026-10-04T07:00:00")

    def test_invalid_records_raise_a_clear_error(self):
        cases = {
            "not an object": [],
            "bad surface": rec(surface="cron"),
            "missing surface": {k: v for k, v in rec().items() if k != "surface"},
            "missing scheduled_for": rec(scheduled_for=None),
            "unparseable time": rec(started_at="yesterday"),
            "non-string time": rec(started_at=12),
            "events not a list": rec(machine_events="sleep"),
            "event without kind": rec(machine_events=[{"at": "2026-10-04T01:00:00+00:00"}]),
            "event without time": rec(machine_events=[{"kind": "sleep"}]),
            "event with bad time": rec(machine_events=[{"kind": "sleep", "at": "soon"}]),
        }
        for label, record in cases.items():
            with self.subTest(label):
                with self.assertRaises(diagnose.DiagnoseError):
                    diagnose.classify(record)


class FixtureTests(unittest.TestCase):
    EXPECTED = {
        "healthy": "healthy",
        "permission_halt": "permission-halt",
        "slept_through": "slept-through",
        "late_catchup": "late-catchup",
        "never_ran_unknown": "never-ran-unknown",
        "failed_unknown": "failed-unknown",
    }

    def test_each_fixture_gets_its_verdict_through_the_cli(self):
        for name, verdict in self.EXPECTED.items():
            with self.subTest(name):
                code, out, err = run_main("--record", str(RECORDS / f"{name}.json"), "--json")
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(json.loads(out)["verdict"], verdict)

    def test_every_fixture_is_labelled_synthetic(self):
        files = sorted(RECORDS.glob("*.json"))
        self.assertEqual(len(files), len(self.EXPECTED))
        for path in files:
            with self.subTest(path.name):
                note = json.loads(path.read_text(encoding="utf-8"))["_note"]
                self.assertTrue(note.startswith("SYNTHETIC"))


class CliTests(unittest.TestCase):
    def write(self, text, encoding="utf-8"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "record.json"
        path.write_bytes(text.encode(encoding))
        return str(path)

    def test_text_output_names_the_verdict_and_evidence(self):
        code, out, _ = run_main("--record", str(RECORDS / "late_catchup.json"))
        self.assertEqual(code, 0)
        self.assertIn("verdict: late-catchup", out)
        self.assertIn("delay_minutes: 192.5", out)
        self.assertIn("late_threshold_minutes: 30", out)
        self.assertIn("asleep_at_schedule: true", out)

    def test_missing_file_is_a_clean_error(self):
        code, out, err = run_main("--record", "no-such-file.json")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("error: cannot read"))
        self.assertNotIn("Traceback", err)

    def test_invalid_json_is_a_clean_error(self):
        code, _, err = run_main("--record", self.write("{not json"))
        self.assertEqual(code, 2)
        self.assertIn("is not valid JSON", err)

    def test_byte_order_mark_is_ignored(self):
        path = self.write(json.dumps(rec()), encoding="utf-8-sig")
        code, out, _ = run_main("--record", path, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["verdict"], "healthy")

    def test_negative_threshold_is_refused(self):
        code, _, err = run_main("--record", str(RECORDS / "healthy.json"), "--late-minutes", "-1")
        self.assertEqual(code, 2)
        self.assertIn("must not be negative", err)

    def test_late_minutes_option_changes_the_verdict(self):
        path = self.write(json.dumps(rec(started_at="2026-10-04T07:10:00+00:00")))
        code, out, _ = run_main("--record", path, "--late-minutes", "5", "--json")
        self.assertEqual((code, json.loads(out)["verdict"]), (0, "late-catchup"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_diagnose.py" -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'diagnose'`.

- [ ] **Step 4: Write the implementation**

`plugins/schedule-doctor/skills/schedule-doctor/scripts/diagnose.py`:

```python
#!/usr/bin/env python3
"""diagnose: classify why a scheduled run did not fire or halted, from a normalized run record.

    python diagnose.py --record FILE [--late-minutes N] [--json]

Read-only. Standard library only. A timestamp without an offset is read as UTC. The record holds
only times, a status and short event names; prompts and transcripts are never read or printed.
Exit code 0 for any verdict, 2 when the record cannot be read.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

LATE_MINUTES = 30
SURFACES = ("desktop", "code-cron", "routine")
SLEEP_KINDS = ("sleep", "lid-close")
HALT_EVENTS = ("permission-denied", "tool-denied", "permission-required")
FAILED_STATUSES = ("failed", "error", "errored", "timed-out", "timeout")
MAX_ERROR_TEXT = 200


class DiagnoseError(Exception):
    """A problem the user can fix; reported as `error: ...` with exit 2."""


def parse_time(value, field):
    if value is None:
        return None
    if not isinstance(value, str):
        raise DiagnoseError(f"{field}: expected an ISO-8601 string, got {type(value).__name__}")
    text = value.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise DiagnoseError(f"{field}: not an ISO-8601 time: {value!r}") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def parse_events(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DiagnoseError("machine_events must be a list")
    events = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or not isinstance(item.get("kind"), str):
            raise DiagnoseError(f"machine_events[{i}]: needs a string 'kind'")
        at = parse_time(item.get("at"), f"machine_events[{i}].at")
        if at is None:
            raise DiagnoseError(f"machine_events[{i}]: needs an 'at' time")
        events.append((at, item["kind"]))
    return sorted(events, key=lambda event: event[0])


def asleep_at(events, moment):
    """True when the last sleep or lid event at or before `moment` has not been followed by a wake."""
    asleep = False
    for at, kind in events:
        if at > moment:
            break
        if kind in SLEEP_KINDS:
            asleep = True
        elif kind == "wake":
            asleep = False
    return asleep


def result(verdict, why, evidence):
    return {"verdict": verdict, "why": why, "evidence": evidence}


def classify(record, late_minutes=LATE_MINUTES):
    if not isinstance(record, dict):
        raise DiagnoseError("the record must be a JSON object")
    surface = record.get("surface")
    if surface not in SURFACES:
        raise DiagnoseError("surface must be one of: " + ", ".join(SURFACES))
    scheduled = parse_time(record.get("scheduled_for"), "scheduled_for")
    if scheduled is None:
        raise DiagnoseError("scheduled_for is required")
    started = parse_time(record.get("started_at"), "started_at")
    parse_time(record.get("ended_at"), "ended_at")  # validated, not used in the verdict
    events = parse_events(record.get("machine_events"))

    asleep = asleep_at(events, scheduled)
    delay = None if started is None else round((started - scheduled).total_seconds() / 60, 1)
    error_text = record.get("error_text")
    if isinstance(error_text, str):
        error_text = error_text[:MAX_ERROR_TEXT]
    evidence = {
        "surface": surface,
        "scheduled_for": record["scheduled_for"],
        "started_at": record.get("started_at"),
        "delay_minutes": delay,
        "late_threshold_minutes": late_minutes,
        "asleep_at_schedule": asleep,
        "error_text": error_text or None,
    }

    tool = record.get("permission_denied_tool")
    last_event = record.get("last_event")
    last = last_event.strip().lower() if isinstance(last_event, str) else ""
    if tool or last in HALT_EVENTS:
        evidence["permission_denied_tool"] = tool or None
        evidence["last_event"] = last_event
        what = f"the tool {tool}" if tool else "a tool"
        return result(
            "permission-halt",
            f"The run stopped when {what} needed a permission nobody had approved. "
            "Approve it once with Run now, or pre-approve it, then schedule again.",
            evidence,
        )
    if started is None:
        if asleep:
            return result(
                "slept-through",
                "No run started, and the machine was asleep (or the lid was closed) "
                "at the scheduled time.",
                evidence,
            )
        return result(
            "never-ran-unknown",
            "No run started and nothing shows the machine was asleep at the scheduled time. "
            "Not enough data to say why.",
            evidence,
        )
    if delay > late_minutes:
        note = " The machine was asleep at the scheduled time, so this is a catch-up run." if asleep else ""
        return result(
            "late-catchup",
            f"The run started {delay:g} minutes after its scheduled time "
            f"(threshold {late_minutes:g}).{note} Anything it read may be stale.",
            evidence,
        )
    status = record.get("status")
    failed_status = isinstance(status, str) and status.strip().lower() in FAILED_STATUSES
    if error_text or failed_status:
        return result(
            "failed-unknown",
            "The run started on time but ended with an error that is not a permission halt.",
            evidence,
        )
    return result("healthy", "The run started on time and ended without an error.", evidence)


def render(res):
    lines = [f"verdict: {res['verdict']}", f"why: {res['why']}", "evidence:"]
    for key, value in res["evidence"].items():
        lines.append(f"  {key}: {json.dumps(value)}")
    return "\n".join(lines)


def load_record(path):
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise DiagnoseError(f"cannot read {path}: {exc.strerror or exc}") from None
    try:
        return json.loads(text)
    except ValueError as exc:
        raise DiagnoseError(f"{path} is not valid JSON ({exc})") from None


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="diagnose.py", description="Classify why a scheduled run did not fire or halted."
    )
    parser.add_argument("--record", required=True, help="normalized run record (JSON file)")
    parser.add_argument(
        "--late-minutes",
        type=float,
        default=LATE_MINUTES,
        help=f"minutes after the schedule that count as a late catch-up (default {LATE_MINUTES})",
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args(argv)
    try:
        if args.late_minutes < 0:
            raise DiagnoseError("--late-minutes must not be negative")
        res = classify(load_record(args.record), args.late_minutes)
    except DiagnoseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2) if args.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m unittest discover -s tests -p "test_diagnose.py" -v`
Expected: all tests PASS. If one fails, fix the implementation or the test only where the test contradicts the Global Constraints; do not weaken a Review Focus test.

- [ ] **Step 6: Commit**

```bash
git add plugins/schedule-doctor/skills/schedule-doctor/scripts/diagnose.py tests/test_diagnose.py tests/fixtures/schedule_doctor/records
git commit -m "$(cat <<'EOF'
feat: add schedule-doctor diagnose.py (run record classifier)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `preflight.py`, the prompt lint

**Files:**
- Create: `plugins/schedule-doctor/skills/schedule-doctor/scripts/preflight.py`
- Create: `tests/test_preflight.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `preflight.analyze(text: str, guard_hours: float = 2.0) -> {"tools": [{"tool","advice","matched","lines"}], "time_guard": {"present","matched","line","hours","snippet"}, "staleness_hints": [{"phrase","lines"}]}`; `preflight.PreflightError`; `preflight.main(argv=None) -> int`; constants `PRE_APPROVE = "pre-approve"`, `APPROVE_ONCE = "approve once with Run now"`, `MAX_PROMPT_CHARS = 20000`. Task 5's SKILL.md describes the output.

- [ ] **Step 1: Write the failing tests**

`tests/test_preflight.py`:

```python
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

import helpers

sys.path.insert(
    0,
    str(helpers.REPO_ROOT / "plugins" / "schedule-doctor" / "skills" / "schedule-doctor" / "scripts"),
)
import preflight  # noqa: E402


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = preflight.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def tool_names(text):
    return [t["tool"] for t in preflight.analyze(text)["tools"]]


def tool(text, name):
    return next(t for t in preflight.analyze(text)["tools"] if t["tool"] == name)


class ToolTests(unittest.TestCase):
    def test_each_kind_of_tool_is_detected(self):
        cases = {
            "Run npm test and report failures.": "Bash",
            "Then git push the branch.": "Bash(git push)",
            "Use mcp__github__create_issue to file it.": "mcp__github__create_issue",
            "Fetch https://example.com/feed and summarise.": "WebFetch/WebSearch",
            "Save the summary to notes.md": "Write/Edit",
            "Deploy the site when tests pass.": "External send or deploy",
            "Delete the old files.": "Bash(destructive)",
        }
        for text, expected in cases.items():
            with self.subTest(text):
                self.assertIn(expected, tool_names(text))

    def test_advice_pre_approve_versus_approve_once(self):
        self.assertEqual(tool("Run npm test.", "Bash")["advice"], preflight.PRE_APPROVE)
        self.assertEqual(
            tool("git push the branch", "Bash(git push)")["advice"], preflight.APPROVE_ONCE
        )
        self.assertEqual(
            tool("Delete the old files.", "Bash(destructive)")["advice"], preflight.APPROVE_ONCE
        )

    def test_plain_prompt_needs_no_tools(self):
        self.assertEqual(tool_names("Summarise what I should focus on."), [])

    def test_the_verb_make_is_not_the_make_command(self):
        self.assertEqual(tool_names("Make a short summary of my notes."), [])
        self.assertIn("Bash", tool_names("Then make build and check the output."))

    def test_matched_snippets_are_capped_and_not_repeated(self):
        found = tool("npm npm\nNPM pip pytest\ndocker npm", "Bash")
        self.assertEqual(len(found["matched"]), 3)
        self.assertEqual(len({m.lower() for m in found["matched"]}), 3)

    def test_lines_are_reported_once_each(self):
        found = tool("Intro\nrun npm test\nthen npm run build", "Bash")
        self.assertEqual(found["lines"], [2, 3])

    def test_a_long_url_is_cut_to_a_short_snippet(self):
        found = tool("Fetch https://example.com/" + "a" * 200, "WebFetch/WebSearch")
        self.assertTrue(all(len(m) <= preflight.MAX_SNIPPET for m in found["matched"]))


class GuardTests(unittest.TestCase):
    def guard(self, text, hours=2.0):
        return preflight.analyze(text, hours)["time_guard"]

    def test_existing_guards_are_recognised(self):
        cases = [
            "If it's after 5pm, skip this run.",
            "Skip this run if more than 2 hours late.",
            "Only run if it is before noon.",
            "Do nothing when it is too late to matter.",
        ]
        for text in cases:
            with self.subTest(text):
                guard = self.guard(text)
                self.assertTrue(guard["present"])
                self.assertIsNone(guard["snippet"])
                self.assertEqual(guard["line"], 1)

    def test_a_bare_skip_is_not_a_guard(self):
        guard = self.guard("Skip the intro and summarise the news.")
        self.assertFalse(guard["present"])
        self.assertIn("compare the current time", guard["snippet"])

    def test_snippet_uses_the_hours_given(self):
        self.assertIn("more than 3 hours", self.guard("Summarise it.", 3)["snippet"])
        self.assertIn("more than 1.5 hours", self.guard("Summarise it.", 1.5)["snippet"])

    def test_guard_on_a_later_line_reports_that_line(self):
        self.assertEqual(self.guard("Summarise.\n\nIf it's after 5pm, skip.")["line"], 3)


class StalenessTests(unittest.TestCase):
    def test_time_relative_phrases_are_listed_with_lines(self):
        hints = preflight.analyze(
            "Summarise today's news and yesterday's mail.\nGet the latest build."
        )["staleness_hints"]
        found = {h["phrase"]: h["lines"] for h in hints}
        self.assertEqual(found, {"today's": [1], "yesterday's": [1], "latest": [2]})

    def test_no_phrases_no_hints(self):
        self.assertEqual(preflight.analyze("Summarise the repo.")["staleness_hints"], [])


class InputTests(unittest.TestCase):
    def write(self, data):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "prompt.txt"
        path.write_bytes(data)
        return str(path)

    def test_empty_or_blank_prompt_is_an_error(self):
        for text in ("", "  \n\n"):
            with self.subTest(repr(text)):
                with self.assertRaises(preflight.PreflightError):
                    preflight.analyze(text)

    def test_oversized_prompt_is_an_error(self):
        with self.assertRaises(preflight.PreflightError) as ctx:
            preflight.analyze("a" * (preflight.MAX_PROMPT_CHARS + 1))
        self.assertIn("20000", str(ctx.exception))

    def test_non_positive_guard_hours_is_an_error(self):
        for hours in (0, -1):
            with self.subTest(hours):
                with self.assertRaises(preflight.PreflightError):
                    preflight.analyze("Summarise.", hours)

    def test_crlf_and_bom_do_not_disturb_line_numbers(self):
        path = self.write(b"\xef\xbb\xbfIntro\r\nrun npm test\r\nIf it is after 5pm, skip.\r\n")
        code, out, _ = run_main("--prompt-file", path, "--json")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["tools"][0]["lines"], [2])
        self.assertEqual(data["time_guard"]["line"], 3)

    def test_missing_file_is_a_clean_error(self):
        code, _, err = run_main("--prompt-file", "no-such-file.txt")
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("error: cannot read"))
        self.assertNotIn("Traceback", err)

    def test_empty_file_is_a_clean_error(self):
        code, _, err = run_main("--prompt-file", self.write(b""))
        self.assertEqual((code, err), (2, "error: the prompt is empty\n"))


class OutputTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "prompt.txt"
        self.path.write_text("Run npm test, then git push.\nSummarise today's results.\n", encoding="utf-8")

    def test_text_report_has_the_three_sections(self):
        code, out, _ = run_main("--prompt-file", str(self.path), "--guard-hours", "4")
        self.assertEqual(code, 0)
        self.assertIn("likely needs", out)
        self.assertIn("Bash: pre-approve", out)
        self.assertIn("Bash(git push): approve once with Run now", out)
        self.assertIn("time guard: missing", out)
        self.assertIn("more than 4 hours", out)
        self.assertIn("today's", out)
        out.encode("ascii")

    def test_json_report_parses(self):
        code, out, _ = run_main("--prompt-file", str(self.path), "--json")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(set(data), {"tools", "time_guard", "staleness_hints"})
        self.assertEqual(data["time_guard"]["hours"], 2.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_preflight.py" -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'preflight'`.

- [ ] **Step 3: Write the implementation**

`plugins/schedule-doctor/skills/schedule-doctor/scripts/preflight.py`:

```python
#!/usr/bin/env python3
"""preflight: lint a scheduled task's prompt before it is scheduled.

    python preflight.py --prompt-file FILE [--guard-hours N] [--json]

Read-only. Standard library only. The tool list is a heuristic ("likely needs"), not a guarantee.
Only short matched snippets are printed, never the whole prompt.
Exit code 0 on success, 2 when the prompt cannot be read.
"""
import argparse
import json
import re
import sys
from pathlib import Path

MAX_PROMPT_CHARS = 20000
MAX_SNIPPET = 40
MAX_GUARD_SNIPPET = 80
MAX_SNIPPETS_PER_TOOL = 3
DEFAULT_GUARD_HOURS = 2.0
PRE_APPROVE = "pre-approve"
APPROVE_ONCE = "approve once with Run now"


class PreflightError(Exception):
    """A problem the user can fix; reported as `error: ...` with exit 2."""


def rx(pattern):
    return re.compile(pattern, re.IGNORECASE)


# (tool name or None to use the matched text, advice, pattern). Every quantifier is bounded so the
# patterns stay fast on a prompt of up to MAX_PROMPT_CHARS.
TOOL_RULES = [
    (None, PRE_APPROVE, rx(r"\bmcp__[A-Za-z0-9_\-]+")),
    (
        "Bash(git push)",
        APPROVE_ONCE,
        rx(r"\bgit\s+push\b|\bforce[- ]push\b|\bpush\s+(?:the\s+|my\s+)?(?:commits?|changes|branch)\b"),
    ),
    (
        "Bash(destructive)",
        APPROVE_ONCE,
        rx(
            r"\brm\s+-\w+|\bdrop\s+(?:table|database)\b|\breset\s+--hard\b"
            r"|\bdelete\s+(?:\w+\s+){0,2}(?:files?|folders?|directory|directories|branch(?:es)?)\b"
        ),
    ),
    (
        "External send or deploy",
        APPROVE_ONCE,
        rx(
            r"\bdeploy(?:ing)?\b"
            r"|\b(?:send|post|publish)\b[^.\n]{0,40}\b(?:email|e-mail|slack|discord|tweet|webhook|release)\b"
        ),
    ),
    (
        "Bash",
        PRE_APPROVE,
        rx(
            r"\b(?:npm|npx|pnpm|yarn|pip3?|pytest|cargo|docker|kubectl|python3?|node|bash|powershell"
            r"|curl|wget|git)\b"
            r"|\bmake\s+(?:test|build|install|all)\b"
            r"|\brun\s+(?:the\s+|a\s+|my\s+)?(?:tests?|script|command|build|migration)s?\b"
        ),
    ),
    (
        "Write/Edit",
        PRE_APPROVE,
        rx(
            r"\b(?:write|create|save|edit|update|modify|append|overwrite)\b[^.\n]{0,60}"
            r"\b(?:files?|folders?|director(?:y|ies)|reports?|notes?|logs?)\b"
            r"|\b(?:write|save)\s+(?:it\s+)?to\b"
        ),
    ),
    (
        "WebFetch/WebSearch",
        PRE_APPROVE,
        rx(r"https?://\S+|\bweb\s?search\b|\bsearch the web\b|\b(?:fetch|browse|scrape|download)\b"),
    ),
]

GUARD_PATTERNS = [
    rx(r"\bskip\b[^.\n]{0,80}\b(?:if|when|unless)\b"),
    rx(
        r"\b(?:if|when)\b[^.\n]{0,100}"
        r"\b(?:after|past|later than|more than \d+\s*(?:minutes?|hours?)|too late|late)\b[^.\n]{0,100}"
        r"\b(?:skip|stop|abort|exit|do nothing)\b"
    ),
    rx(r"\bonly\s+(?:run|act|proceed)\b[^.\n]{0,60}\b(?:if|before|between|within)\b"),
    rx(r"\btoo late\b"),
]

STALENESS = rx(
    r"\b(?:latest|newest|most recent|today(?:'s)?|yesterday(?:'s)?|this morning|tonight"
    r"|this week|last night)\b"
)


def find_tools(lines):
    found = {}
    for tool, advice, pattern in TOOL_RULES:
        for number, line in enumerate(lines, 1):
            for match in pattern.finditer(line):
                name = tool or match.group(0)
                entry = found.setdefault(
                    name, {"tool": name, "advice": advice, "matched": [], "lines": []}
                )
                snippet = match.group(0).strip()[:MAX_SNIPPET]
                known = [s.lower() for s in entry["matched"]]
                if snippet.lower() not in known and len(entry["matched"]) < MAX_SNIPPETS_PER_TOOL:
                    entry["matched"].append(snippet)
                if number not in entry["lines"]:
                    entry["lines"].append(number)
    return list(found.values())


def find_guard(lines):
    for number, line in enumerate(lines, 1):
        for pattern in GUARD_PATTERNS:
            match = pattern.search(line)
            if match:
                return match.group(0).strip()[:MAX_GUARD_SNIPPET], number
    return None, None


def find_staleness(lines):
    seen = {}
    for number, line in enumerate(lines, 1):
        for match in STALENESS.finditer(line):
            phrase = match.group(0).lower()
            entry = seen.setdefault(phrase, {"phrase": phrase, "lines": []})
            if number not in entry["lines"]:
                entry["lines"].append(number)
    return list(seen.values())


def guard_snippet(hours):
    return (
        "Before doing anything else, compare the current time with this task's scheduled time. "
        f"If this run started more than {hours:g} hours after the scheduled time, stop: "
        "do not act on any data, and report that the run was late."
    )


def analyze(text, guard_hours=DEFAULT_GUARD_HOURS):
    if guard_hours <= 0:
        raise PreflightError("--guard-hours must be greater than 0")
    if not text.strip():
        raise PreflightError("the prompt is empty")
    if len(text) > MAX_PROMPT_CHARS:
        raise PreflightError(f"the prompt is longer than {MAX_PROMPT_CHARS} characters")
    lines = text.splitlines()
    matched, number = find_guard(lines)
    return {
        "tools": find_tools(lines),
        "time_guard": {
            "present": matched is not None,
            "matched": matched,
            "line": number,
            "hours": guard_hours,
            "snippet": None if matched else guard_snippet(guard_hours),
        },
        "staleness_hints": find_staleness(lines),
    }


def render(res):
    out = ["tools (likely needs; a heuristic, not a guarantee):"]
    if not res["tools"]:
        out.append("  none detected")
    for t in res["tools"]:
        lines = ", ".join(str(n) for n in t["lines"])
        out.append(f"  {t['tool']}: {t['advice']} (matched: {', '.join(t['matched'])}; line {lines})")
    guard = res["time_guard"]
    if guard["present"]:
        out.append(f"time guard: found ({guard['matched']!r} on line {guard['line']})")
    else:
        out.append("time guard: missing")
        out.append(f"  paste this into the prompt (assumed {guard['hours']:g} hours; ask the user):")
        out.append(f"  {guard['snippet']}")
    if res["staleness_hints"]:
        out.append("staleness hints (a late run would read these against the wrong date):")
        for hint in res["staleness_hints"]:
            lines = ", ".join(str(n) for n in hint["lines"])
            out.append(f"  {hint['phrase']} (line {lines})")
    return "\n".join(out)


def read_prompt(path):
    try:
        return Path(path).read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise PreflightError(f"cannot read {path}: {exc.strerror or exc}") from None
    except UnicodeDecodeError:
        raise PreflightError(f"{path} is not UTF-8 text") from None


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="preflight.py", description="Lint a scheduled task's prompt before it is scheduled."
    )
    parser.add_argument("--prompt-file", required=True, help="the task prompt, as a text file")
    parser.add_argument(
        "--guard-hours",
        type=float,
        default=DEFAULT_GUARD_HOURS,
        help=f"hours of lateness the time guard tolerates (default {DEFAULT_GUARD_HOURS:g})",
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args(argv)
    try:
        res = analyze(read_prompt(args.prompt_file), args.guard_hours)
    except PreflightError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2) if args.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s tests -p "test_preflight.py" -v`
Expected: all tests PASS. If a pattern test fails, adjust the regex, not the test, unless the test contradicts the Global Constraints; the "bare skip" and "make" tests are Review Focus items and must stay.

- [ ] **Step 5: Commit**

```bash
git add plugins/schedule-doctor/skills/schedule-doctor/scripts/preflight.py tests/test_preflight.py
git commit -m "$(cat <<'EOF'
feat: add schedule-doctor preflight.py (prompt lint)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `power_check.py`, the OS sleep settings

**Files:**
- Create: `plugins/schedule-doctor/skills/schedule-doctor/scripts/power_check.py`
- Create: `tests/test_power_check.py`
- Create: `tests/fixtures/schedule_doctor/power/{windows_sleep_real,windows_lid_real,windows_sleep_laptop_synthetic,windows_lid_laptop_synthetic,pmset_synthetic}.txt`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `power_check.parse_powercfg_index(text) -> {"ac": int|None, "dc": int|None}` (raw index values); `power_check.parse_pmset_sleep(text) -> int|None`; `power_check.summarize(os_name, sleep_after, lid_action=None) -> {"os","sleep_after_minutes","lid_close_action","keeps_awake","findings","caveat"}`; `power_check.collect() -> dict`; `power_check.run_command(args) -> str`; `power_check.platform_name() -> "windows"|"macos"|None`; `power_check.PowerError`; `power_check.main(argv=None) -> int`. `keeps_awake` is `True`, `False` or `None` (unknown).

- [ ] **Step 1: Write the fixtures**

`windows_sleep_real.txt` is a capture from this machine (a desktop) on 2026-10-04 with `powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE`, run from PowerShell:

```
Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  GUID Alias: SCHEME_BALANCED
  Subgroup GUID: 238c9fa8-0aad-41ed-83f4-97be242c8f20  (Sleep)
    GUID Alias: SUB_SLEEP
    Power Setting GUID: 29f6c1db-86da-48c5-9fdb-f2b67b1f44da  (Sleep after)
      GUID Alias: STANDBYIDLE
      Minimum Possible Setting: 0x00000000
      Maximum Possible Setting: 0xffffffff
      Possible Settings increment: 0x00000001
      Possible Settings units: Seconds
    Current AC Power Setting Index: 0x00000000
    Current DC Power Setting Index: 0x00000000

```

`windows_lid_real.txt` is the capture from the same machine of `powercfg /query SCHEME_CURRENT SUB_BUTTONS LIDACTION`. A desktop has no lid setting, so powercfg prints only the scheme header:

```
Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  GUID Alias: SCHEME_BALANCED

```

`windows_sleep_laptop_synthetic.txt` (hand-made; 0x708 = 1800 s = 30 min, 0x384 = 900 s = 15 min):

```
Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  GUID Alias: SCHEME_BALANCED
  Subgroup GUID: 238c9fa8-0aad-41ed-83f4-97be242c8f20  (Sleep)
    GUID Alias: SUB_SLEEP
    Power Setting GUID: 29f6c1db-86da-48c5-9fdb-f2b67b1f44da  (Sleep after)
      GUID Alias: STANDBYIDLE
      Minimum Possible Setting: 0x00000000
      Maximum Possible Setting: 0xffffffff
      Possible Settings increment: 0x00000001
      Possible Settings units: Seconds
    Current AC Power Setting Index: 0x00000708
    Current DC Power Setting Index: 0x00000384

```

`windows_lid_laptop_synthetic.txt` (hand-made; AC do nothing, battery sleep):

```
Power Scheme GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (Balanced)
  GUID Alias: SCHEME_BALANCED
  Subgroup GUID: 4f971e89-eebd-4455-a8de-9e59040e7347  (Power buttons and lid)
    GUID Alias: SUB_BUTTONS
    Power Setting GUID: 5ca83367-6e45-459f-a27b-476b1d01c936  (Lid close action)
      GUID Alias: LIDACTION
      Possible Setting Index: 000
      Possible Setting Friendly Name: Do nothing
      Possible Setting Index: 001
      Possible Setting Friendly Name: Sleep
      Possible Setting Index: 002
      Possible Setting Friendly Name: Hibernate
      Possible Setting Index: 003
      Possible Setting Friendly Name: Shut down
    Current AC Power Setting Index: 0x00000000
    Current DC Power Setting Index: 0x00000001

```

`pmset_synthetic.txt` (hand-made from the usual `pmset -g` layout; not a capture):

```
System-wide power settings:
Currently in use:
 standby              1
 Sleep On Power Button 1
 autorestart          0
 hibernatemode        3
 powernap             1
 networkoversleep     0
 disksleep            10
 sleep                10 (sleep prevented by powerd)
 ttyskeepawake        1
 displaysleep         2
 lidwake              1
```

- [ ] **Step 2: Write the failing tests**

`tests/test_power_check.py`:

```python
import contextlib
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

import helpers

sys.path.insert(
    0,
    str(helpers.REPO_ROOT / "plugins" / "schedule-doctor" / "skills" / "schedule-doctor" / "scripts"),
)
import power_check  # noqa: E402

POWER = helpers.REPO_ROOT / "tests" / "fixtures" / "schedule_doctor" / "power"


def fixture(name):
    return (POWER / name).read_text(encoding="utf-8")


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = power_check.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class ParseTests(unittest.TestCase):
    def test_real_desktop_sleep_never(self):
        self.assertEqual(
            power_check.parse_powercfg_index(fixture("windows_sleep_real.txt")),
            {"ac": 0, "dc": 0},
        )

    def test_laptop_sleep_values_are_seconds(self):
        self.assertEqual(
            power_check.parse_powercfg_index(fixture("windows_sleep_laptop_synthetic.txt")),
            {"ac": 1800, "dc": 900},
        )

    def test_real_desktop_has_no_lid_setting(self):
        self.assertEqual(
            power_check.parse_powercfg_index(fixture("windows_lid_real.txt")),
            {"ac": None, "dc": None},
        )

    def test_laptop_lid_values(self):
        self.assertEqual(
            power_check.parse_powercfg_index(fixture("windows_lid_laptop_synthetic.txt")),
            {"ac": 0, "dc": 1},
        )

    def test_unparseable_text_gives_none(self):
        self.assertEqual(
            power_check.parse_powercfg_index("Parametres invalides"), {"ac": None, "dc": None}
        )

    def test_pmset_sleep_minutes(self):
        self.assertEqual(power_check.parse_pmset_sleep(fixture("pmset_synthetic.txt")), 10)

    def test_pmset_does_not_confuse_displaysleep_or_disksleep(self):
        self.assertIsNone(power_check.parse_pmset_sleep(" displaysleep 2\n disksleep 10\n"))

    def test_pmset_without_a_sleep_line(self):
        self.assertIsNone(power_check.parse_pmset_sleep("nothing useful"))


class SummarizeTests(unittest.TestCase):
    def test_desktop_that_never_sleeps_keeps_awake(self):
        res = power_check.summarize("windows", {"ac": 0.0, "dc": 0.0}, None)
        self.assertIs(res["keeps_awake"], True)
        self.assertIn("lid close: no setting found", res["findings"])

    def test_laptop_with_sleep_timeouts_does_not(self):
        res = power_check.summarize(
            "windows", {"ac": 30.0, "dc": 15.0}, {"ac": "do nothing", "dc": "sleep"}
        )
        self.assertIs(res["keeps_awake"], False)
        self.assertIn("sleep timeout on power: 30 minutes idle", res["findings"])
        self.assertIn("lid close on battery: sleep", res["findings"])

    def test_never_sleeps_but_lid_close_sleeps(self):
        res = power_check.summarize(
            "windows", {"ac": 0.0, "dc": 0.0}, {"ac": "sleep", "dc": "sleep"}
        )
        self.assertIs(res["keeps_awake"], False)

    def test_unreadable_values_make_the_answer_unknown_not_yes(self):
        res = power_check.summarize("windows", {"ac": None, "dc": 0.0}, None)
        self.assertIsNone(res["keeps_awake"])
        self.assertIn("sleep timeout on power: could not be read", res["findings"])

    def test_unreadable_lid_value_makes_the_answer_unknown(self):
        res = power_check.summarize(
            "windows", {"ac": 0.0, "dc": 0.0}, {"ac": "do nothing", "dc": None}
        )
        self.assertIsNone(res["keeps_awake"])

    def test_macos_never_sleeping_is_still_unknown_because_the_lid_is_not_readable(self):
        res = power_check.summarize("macos", {"any": 0})
        self.assertIsNone(res["keeps_awake"])
        self.assertTrue(any("MacBook" in f for f in res["findings"]))

    def test_macos_with_a_sleep_timer_does_not_keep_awake(self):
        self.assertIs(power_check.summarize("macos", {"any": 10})["keeps_awake"], False)

    def test_caveat_names_the_desktop_toggle(self):
        self.assertIn("Keep computer awake", power_check.summarize("macos", {"any": 0})["caveat"])


class MainTests(unittest.TestCase):
    def patched(self, name, outputs):
        return (
            mock.patch.object(power_check, "platform_name", return_value=name),
            mock.patch.object(power_check, "run_command", side_effect=outputs),
        )

    def test_windows_laptop_report(self):
        p1, p2 = self.patched(
            "windows",
            [fixture("windows_sleep_laptop_synthetic.txt"), fixture("windows_lid_laptop_synthetic.txt")],
        )
        with p1, p2:
            code, out, err = run_main("--json")
        data = json.loads(out)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(data["sleep_after_minutes"], {"ac": 30.0, "dc": 15.0})
        self.assertEqual(data["lid_close_action"], {"ac": "do nothing", "dc": "sleep"})
        self.assertIs(data["keeps_awake"], False)

    def test_windows_desktop_text_report(self):
        p1, p2 = self.patched(
            "windows", [fixture("windows_sleep_real.txt"), fixture("windows_lid_real.txt")]
        )
        with p1, p2:
            code, out, _ = run_main()
        self.assertEqual(code, 0)
        self.assertIn("os: windows", out)
        self.assertIn("sleep timeout on power: never", out)
        self.assertIn("keeps awake unattended: yes", out)
        self.assertIn("caveat:", out)
        out.encode("ascii")

    def test_a_failing_lid_query_is_tolerated(self):
        p1, p2 = self.patched(
            "windows", [fixture("windows_sleep_real.txt"), power_check.PowerError("no")]
        )
        with p1, p2:
            code, out, _ = run_main("--json")
        self.assertEqual(code, 0)
        self.assertIsNone(json.loads(out)["lid_close_action"])

    def test_a_failing_sleep_query_is_a_clean_error(self):
        p1, p2 = self.patched("windows", [power_check.PowerError("powercfg failed (exit 1)")])
        with p1, p2:
            code, _, err = run_main()
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("error: powercfg failed"))

    def test_macos_report(self):
        p1, p2 = self.patched("macos", [fixture("pmset_synthetic.txt")])
        with p1, p2:
            code, out, _ = run_main("--json")
        data = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(data["sleep_after_minutes"], {"any": 10})
        self.assertIs(data["keeps_awake"], False)

    def test_unsupported_os_is_a_clean_error(self):
        p1, p2 = self.patched(None, [])
        with p1, p2:
            code, _, err = run_main()
        self.assertEqual(code, 2)
        self.assertIn("unsupported OS", err)
        self.assertNotIn("Traceback", err)


class RunCommandTests(unittest.TestCase):
    def test_nonzero_exit_is_a_power_error(self):
        done = subprocess.CompletedProcess(["powercfg"], 1, stdout="", stderr="bad args")
        with mock.patch.object(subprocess, "run", return_value=done):
            with self.assertRaises(power_check.PowerError) as ctx:
                power_check.run_command(["powercfg", "/query"])
        self.assertIn("exit 1", str(ctx.exception))

    def test_missing_program_is_a_power_error(self):
        with mock.patch.object(subprocess, "run", side_effect=FileNotFoundError("powercfg")):
            with self.assertRaises(power_check.PowerError):
                power_check.run_command(["powercfg"])

    def test_success_returns_stdout(self):
        done = subprocess.CompletedProcess(["x"], 0, stdout="hello", stderr="")
        with mock.patch.object(subprocess, "run", return_value=done):
            self.assertEqual(power_check.run_command(["x"]), "hello")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_power_check.py" -v`
Expected: ERROR with `ModuleNotFoundError: No module named 'power_check'`.

- [ ] **Step 4: Write the implementation**

`plugins/schedule-doctor/skills/schedule-doctor/scripts/power_check.py`:

```python
#!/usr/bin/env python3
"""power_check: read the OS sleep settings that decide whether a scheduled task can fire.

    python power_check.py [--json]

Read-only: runs `powercfg /query` on Windows or `pmset -g` on macOS (no shell involved).
It cannot see Claude Desktop's own "Keep computer awake" setting; the agent must ask the user.
Exit code 0 on success, 2 when the settings cannot be read.
"""
import argparse
import json
import re
import subprocess
import sys

LID_ACTIONS = {0: "do nothing", 1: "sleep", 2: "hibernate", 3: "shut down"}
SOURCE_LABELS = {"ac": "on power", "dc": "on battery", "any": "currently"}
CAVEAT = (
    "Claude Desktop's own Keep computer awake setting is not visible from here; "
    "ask the user to confirm it."
)
COMMAND_TIMEOUT_SECONDS = 15


class PowerError(Exception):
    """A problem the user can fix; reported as `error: ...` with exit 2."""


def platform_name():
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return None


def run_command(args):
    try:
        done = subprocess.run(
            args, capture_output=True, text=True, errors="replace", timeout=COMMAND_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PowerError(f"could not run {args[0]}: {exc}") from None
    if done.returncode != 0:
        detail = (done.stderr or done.stdout or "").strip()[:200]
        raise PowerError(f"{args[0]} failed (exit {done.returncode}): {detail}")
    return done.stdout


def parse_powercfg_index(text):
    found = {}
    pattern = r"Current (AC|DC) Power Setting Index:\s*0x([0-9a-fA-F]+)"
    for kind, value in re.findall(pattern, text):
        found[kind.lower()] = int(value, 16)
    return {"ac": found.get("ac"), "dc": found.get("dc")}


def parse_pmset_sleep(text):
    match = re.search(r"^\s*sleep\s+(\d+)\b", text, re.MULTILINE)
    return int(match.group(1)) if match else None


def summarize(os_name, sleep_after, lid_action=None):
    findings = []
    sleeps = False
    unknown = False
    for source, minutes in sleep_after.items():
        label = SOURCE_LABELS.get(source, source)
        if minutes is None:
            unknown = True
            findings.append(f"sleep timeout {label}: could not be read")
        elif minutes == 0:
            findings.append(f"sleep timeout {label}: never")
        else:
            sleeps = True
            findings.append(f"sleep timeout {label}: {minutes:g} minutes idle")
    if lid_action is None:
        if os_name == "windows":
            findings.append("lid close: no setting found")
        else:
            findings.append(
                "lid close: not readable (a closed MacBook lid sleeps it unless it is on power "
                "with an external display)"
            )
    else:
        for source, action in lid_action.items():
            label = SOURCE_LABELS.get(source, source)
            if action is None:
                unknown = True
                findings.append(f"lid close {label}: could not be read")
            elif action == "do nothing":
                findings.append(f"lid close {label}: do nothing")
            else:
                sleeps = True
                findings.append(f"lid close {label}: {action}")
    if sleeps:
        keeps_awake = False
    elif unknown or os_name == "macos":
        keeps_awake = None
    else:
        keeps_awake = True
    return {
        "os": os_name,
        "sleep_after_minutes": sleep_after,
        "lid_close_action": lid_action,
        "keeps_awake": keeps_awake,
        "findings": findings,
        "caveat": CAVEAT,
    }


def collect():
    name = platform_name()
    if name == "windows":
        sleep_text = run_command(["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"])
        sleep_after = {
            key: None if value is None else value / 60
            for key, value in parse_powercfg_index(sleep_text).items()
        }
        try:
            lid_text = run_command(
                ["powercfg", "/query", "SCHEME_CURRENT", "SUB_BUTTONS", "LIDACTION"]
            )
        except PowerError:
            lid_text = ""
        lid = {key: LID_ACTIONS.get(value) for key, value in parse_powercfg_index(lid_text).items()}
        return summarize(name, sleep_after, None if all(v is None for v in lid.values()) else lid)
    if name == "macos":
        return summarize(name, {"any": parse_pmset_sleep(run_command(["pmset", "-g"]))})
    raise PowerError(
        f"unsupported OS ({sys.platform}): only Windows (powercfg) and macOS (pmset) are read"
    )


def render(res):
    keeps = {True: "yes", False: "no", None: "unknown"}[res["keeps_awake"]]
    lines = [f"os: {res['os']}"] + res["findings"]
    lines += [f"keeps awake unattended: {keeps}", f"caveat: {res['caveat']}"]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="power_check.py", description="Read the OS sleep settings that stop scheduled tasks."
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args(argv)
    try:
        res = collect()
    except PowerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(res, indent=2) if args.json else render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m unittest discover -s tests -p "test_power_check.py" -v`
Expected: all tests PASS.

- [ ] **Step 6: Smoke test against this machine**

Run: `python plugins/schedule-doctor/skills/schedule-doctor/scripts/power_check.py`
Expected on this desktop: `os: windows`, both sleep timeouts `never`, `lid close: no setting found`, `keeps awake unattended: yes`, then the caveat line. If it prints an error instead, fix `collect()` (note: from Git Bash a `powercfg /query` typed by hand is mangled by path conversion; the script uses a list of arguments with no shell, so it is not affected).

- [ ] **Step 7: Commit**

```bash
git add plugins/schedule-doctor/skills/schedule-doctor/scripts/power_check.py tests/test_power_check.py tests/fixtures/schedule_doctor/power
git commit -m "$(cat <<'EOF'
feat: add schedule-doctor power_check.py (OS sleep settings)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: SKILL.md, README, changelog and final verification

**Files:**
- Modify: `plugins/schedule-doctor/skills/schedule-doctor/SKILL.md` (keep the scaffolded frontmatter exactly; replace the body)
- Modify: `plugins/schedule-doctor/README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: the CLI of `preflight.py`, `power_check.py` and `diagnose.py` from Tasks 2-4, and the record shape and verdict names from Task 2.
- Produces: the shipped skill text.

- [ ] **Step 1: Replace the body of `SKILL.md`**

Keep the lines from `---` to `---` that `new_skill.py` wrote. Replace everything after them with:

````markdown
# Schedule Doctor

## Overview

Scheduled Claude tasks fail quietly: a run halts on a tool nobody pre-approved, a run is skipped because the computer slept (closing the lid still sleeps it), or one late catch-up run acts on stale data. This skill checks a task before it is scheduled, and explains afterwards why a run did not fire. Scripts do the checking and the classifying; the agent fetches task state through the scheduling tools, shows what the scripts found, and never names a cause the scripts did not.

## The scripts

In this skill's `scripts/` directory (use the base directory shown when the skill loads). Python 3 and the standard library only; use `python3`, or `python` / `py -3` if that is what works. All three are read-only.

- `preflight.py --prompt-file FILE [--guard-hours N] [--json]` lints a task prompt: the tools it likely needs (each marked `pre-approve` or `approve once with Run now`), whether it has a time guard (and a paste-ready one if not), and phrases like "today" or "latest" that a late run would read against the wrong date.
- `power_check.py [--json]` reads the OS sleep timeout and lid-close action (`powercfg` on Windows, `pmset` on macOS) and says whether the machine keeps awake unattended: yes, no or unknown.
- `diagnose.py --record FILE [--late-minutes N] [--json]` classifies one run record (shape below) into one verdict.

## Before a task is scheduled (pre-flight)

1. Get the prompt: from the user, or by reading the task through the surface's tool (table below). Save it to a scratch file outside the repo.
2. Run `preflight.py --prompt-file FILE --json`. Show the tool list as "likely needs", never "will need". Offer to pre-approve the `pre-approve` tools in the user's permission settings; for `approve once with Run now` tools (git push, deleting, sending, deploying) say they should be approved once by running the task with Run now, not left permanently allowed.
3. If `time_guard.present` is false, ask the user how many hours of lateness is acceptable, rerun with `--guard-hours`, and show the snippet. Adding it is a prompt edit: show the diff and wait for an explicit yes in this conversation first.
4. Mention the staleness hints: those phrases are where a late run goes wrong even with a guard.
5. Run `power_check.py`. If `keeps_awake` is `no` or `unknown`, say what the findings show. Then ask the user to confirm Claude Desktop's Keep computer awake setting, which the script cannot see.

## After a run did not fire (post-mortem)

1. Fetch the task and its latest run through the surface's tools (table below) and write the record to a scratch file outside the repo:

   ```json
   {
     "surface": "desktop | code-cron | routine",
     "scheduled_for": "ISO-8601",
     "started_at": "ISO-8601 or null",
     "ended_at": "ISO-8601 or null",
     "status": "string or null",
     "last_event": "string or null",
     "error_text": "string or null",
     "permission_denied_tool": "string or null",
     "machine_events": [{"kind": "sleep | wake | lid-close", "at": "ISO-8601"}]
   }
   ```

   Leave a field `null` when the surface does not give it. Never invent a value. Only diagnose a run whose scheduled time has already passed.
2. For `machine_events`, ask the user, or with their consent read sleep history around the scheduled time: on Windows the System log's Kernel-Power events 42 (entering sleep) and 107 (resume from sleep); on macOS `pmset -g log`. Show the command before running it.
3. Run `diagnose.py --record FILE --json` and report the verdict, the `why` and the evidence verbatim.
4. Act on the verdict:
   - `permission-halt`: name the tool, then use the pre-flight advice for it.
   - `slept-through`: run `power_check.py`, and point to the Keep computer awake setting and the lid-close action.
   - `late-catchup`: add or tighten the time guard, using pre-flight steps 3 and 4.
   - `failed-unknown`: show the error text; it is not a scheduling problem the skill can classify.
   - `never-ran-unknown`: say there is not enough data. Suggest the user check the machine was on and the app open at that time. Do not guess a cause.
   - `healthy`: say the run looks fine and ask what they saw.

## Fetching task state per surface

| Surface | `surface` value | Prompt and schedule | Last run |
| --- | --- | --- | --- |
| Claude Desktop scheduled task | `desktop` | the scheduled-tasks tools in this session (names contain `scheduled_task`) | the same tools' run details |
| Claude Code session cron (`/loop`, `CronCreate`) | `code-cron` | `CronList` | the session transcript and the cron's own output |
| Cloud routine (`/schedule`) | `routine` | the `schedule` skill's listing | its run history |

If this session has no tool for a surface, say so and ask the user to paste the prompt, the scheduled time, the start and end times, and any error. Do not read an app's files from disk to get task state: the layout is not stable.

## Rules

- Scripts decide. Never name a cause yourself; `never-ran-unknown` stays unknown.
- Never edit a scheduled task or its prompt before showing the diff and getting an explicit yes in this conversation.
- Never print or paraphrase prompt or transcript content beyond the short snippets the scripts print.
- Do time comparisons only through the scripts. A timestamp without an offset is read as UTC: say so if the user's times are local.
- The Desktop app changes quickly; a release may fix some of these failures. If a verdict contradicts what the user sees, show the evidence and say the app may have changed.

## Common mistakes

- Calling the tool list a guarantee. It is a heuristic over the prompt text.
- Reporting `slept-through` without sleep evidence. Without it the verdict is `never-ran-unknown`.
- Treating a run the user started by hand before its time as late. Negative delay is healthy.
- Forgetting the Keep computer awake toggle: `power_check.py` cannot see it.
````

- [ ] **Step 2: Replace the plugin README**

`plugins/schedule-doctor/README.md`:

````markdown
# schedule-doctor: a Claude Code skill by Naren

> Make Claude scheduled tasks actually run: check a task before you schedule it, and find out why one did not fire.

Part of [Naren's Claude Skills](https://github.com/NarenDawar/narens-claude-skills).

## When it triggers

Ask things like "will this scheduled task actually run?", "check this before I schedule it", "why didn't my 7am task fire?", or "my scheduled task ran hours late". It covers Claude Desktop scheduled tasks, Claude Code session crons (`/loop`), and cloud routines.

## What it does

**Before you schedule:** reads the task prompt, lists the tools it will likely need so you can pre-approve them, adds a time guard so a late catch-up run does not act on stale data, and checks whether your machine keeps awake (sleep timeout and lid-close action).

**After a run:** reads the run's outcome and tells you which of these happened: it halted on a tool nobody approved, the machine slept through it, it ran late as a catch-up, it failed with an error, or there is not enough data to say.

Small stdlib-only Python scripts do the checking and the classifying, so the answers are not guesses. Nothing is edited without your yes.

## Install

**Plugin marketplace (recommended)**

```text
/plugin marketplace add NarenDawar/narens-claude-skills
/plugin install schedule-doctor@narens-claude-skills
```

**Manual**

Copy `plugins/schedule-doctor/skills/schedule-doctor` into `~/.claude/skills/`.

## Example

**Before:** you schedule "pull the latest build and git push the result" for 7am. The laptop sleeps, Desktop runs it at 10:12, and the push waits on a permission nobody approved.

**After:** the skill flags `git push` as approve-once, notes "latest" as a staleness risk, adds "if this run started more than 2 hours late, stop and report", and shows that your machine sleeps after 15 minutes on battery.

---

Made by [Naren](https://github.com/NarenDawar). If this helped, star the repo.
````

- [ ] **Step 3: Add the changelog entry**

In `CHANGELOG.md`, under `## [Unreleased]` / `### Added`, add as the first bullet:

```
- `schedule-doctor` skill: before you schedule a Claude task it lints the prompt (likely tools to pre-approve, a time guard against stale catch-up runs, time-relative wording) and checks whether your machine keeps awake; afterwards it classifies why a run did not fire (permission halt, slept through, late catch-up, failed, or not enough data). Covers Desktop scheduled tasks, Claude Code crons and cloud routines.
```

- [ ] **Step 4: Regenerate the catalog and run everything**

```bash
python scripts/build_catalog.py
python -m unittest discover -s tests
python scripts/validate.py
git status --short
```

Expected: all tests pass (the earlier suites plus the three new files); `OK: all plugins valid`; `git status` shows only this task's files plus, if anything changed, `README.md` / `llms.txt`.

- [ ] **Step 5: End-to-end smoke of the three scripts**

Use the session scratchpad, not the repo: `SP=C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/4ec2fd29-f30d-4793-83a9-f979fbae59a4/scratchpad`.

```bash
S=plugins/schedule-doctor/skills/schedule-doctor/scripts
printf 'Pull the latest build, run npm test, then git push the result.\nSummarise today results into notes.md\n' > "$SP/prompt.txt"
python $S/preflight.py --prompt-file "$SP/prompt.txt" --guard-hours 2
python $S/power_check.py
python $S/diagnose.py --record tests/fixtures/schedule_doctor/records/late_catchup.json
```

Expected: preflight lists `Bash: pre-approve`, `Bash(git push): approve once with Run now`, `Write/Edit`, reports `time guard: missing` with a snippet and staleness hints for `latest` and `today`; power_check prints this machine's settings; diagnose prints `verdict: late-catchup` with `delay_minutes: 192.5`. Read the SKILL.md steps once against this output: every command and field name it cites must exist.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
feat: add schedule-doctor skill text, README and changelog entry

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-review notes

- **Spec coverage:** layout (Task 1, 5); `preflight.py` tools, guard, staleness, size limit (Task 3); `power_check.py` with the Keep-awake caveat (Task 4); `diagnose.py` record, five verdicts plus `failed-unknown`, named threshold printed, slept-through only on evidence (Task 2); process, per-surface fetch table, rules (Task 5); error handling as one-line exit 2 (each script's tests); testing per script with synthetic fixtures (Tasks 2-4); out-of-scope items appear as rules in Task 5 and Global Constraints.
- **Deviation from the spec, made in Task 1:** a sixth verdict `failed-unknown`, so an on-time run that errored is not reported healthy; and a 20,000-character prompt limit.
- **Type consistency:** `classify` / `analyze` / `summarize` return shapes and the verdict and constant names are the same in the tests, the implementations and the SKILL.md text.
