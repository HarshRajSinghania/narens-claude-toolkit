# subagent-tax-auditor Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and ship the `subagent-tax-auditor` skill: it parses local Claude Code transcripts, splits cost between the main thread and each subagent type, recommends cheaper models for expensive agents, edits custom agent frontmatter only after confirmation, and later compares usage before and after.

**Architecture:** One plugin, `plugins/subagent-tax-auditor/`, scaffolded by `scripts/new_skill.py`. Two stdlib scripts live in the skill folder: `audit.py` (read-only measuring: `report`, `snapshot`, `compare`) and `agent_edit.py` (frontmatter `list`, `plan`, `apply`, `undo`), plus `rates.json`. `SKILL.md` owns the judgment: explaining, recommending, asking, and checking. Both scripts are built test-first with `unittest` on synthetic transcript trees (a shared builder in `tests/transcript_builder.py`) plus a text-free fixture sanitized from real transcripts; the skill text is verified with baseline and with-skill scenario runs.

**Tech Stack:** Python 3.9+ standard library, Markdown, JSON, the repo tooling, general-purpose subagents (model `sonnet`) as the scenario runner.

**Spec:** `docs/superpowers/specs/2026-10-03-subagent-tax-auditor-design.md`

## Global Constraints

- Plugin and skill name `subagent-tax-auditor`; `SKILL.md` frontmatter has `name` and a single-line, double-quoted `description` starting with `Use when`; no branding footer in `SKILL.md`.
- Both scripts are Python 3.9+ standard library only; files written with LF line endings; UTF-8 read with BOM tolerance; no network access in either script.
- `audit.py` is read-only: it never writes anywhere except the single file named by `snapshot --out`.
- Prompts, responses and file contents are never printed by any script; task descriptions appear only with `--show-descriptions`.
- Cost is a cost-equivalent proxy at published API rates read from `rates.json`; a model with no rate keeps its token counts, shows `no rate`, and is excluded from cost totals. Rates are never hard-coded in `audit.py`.
- A message id can span several transcript lines; each id counts once, with the field-wise maximum of every token kind.
- The small-sample rule: fewer than 5 spawns on either side of a comparison gives no verdict.
- `agent_edit.py` edits only the `model` and `effort` lines inside the leading `---` block of custom agent files; it refuses files it cannot parse safely and writes nothing in that case; every `apply` saves a backup first.
- The skill never edits an agent file before showing the `plan` diff and getting an explicit yes in the conversation, and never claims a saving the comparison does not show.
- Built-in agent types (`general-purpose`, `Explore`, `Plan`, and so on) are reported on, never edited.
- Author `Naren`; GitHub user `NarenDawar`; repo `narens-claude-skills`; marketplace `narens-claude-skills`. Free and MIT: no pricing work.
- Do not push to GitHub in this plan; pushing is a separate, explicit user request.
- Scratch work (scenario trees, outputs) lives in the session scratchpad, never in the repo: `C:/Users/naren/AppData/Local/Temp/claude/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a/scratchpad` (called `$SP` below). Scenario runs never touch the repo or the real `~/.claude`.
- Commit trailer on every commit: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

**Spec clarifications decided in this plan:**
- Date filters (`--since`, `--until`) and the `compare` cut-off apply per **file** (a main session or one subagent run), by the timestamp of its first record. A run that started before the snapshot counts as "before" even if it finished after. The spec said "sessions"; spawns are strictly more accurate because an agent edit only affects spawns that start after it.
- A real-data check showed a message id appears on several lines (788 of 1,522 assistant lines in one session were repeats, 36 with differing usage), so de-duplication takes the field-wise maximum per id rather than the first or last line.
- `compare` reuses the snapshot's project selection (`project` or `all`) when the command line gives none.
- `audit.py compare` also notes when `rates.json` `as_of` differs from the snapshot's, because a cost change could then be a price change.
- `effort` support depends on a docs check in Task 5 (Step 1). If agent frontmatter has no `effort` field, `--effort` and its tests are removed and the ruling is ledgered.

## Review Focus

Input classes the spec implies but its test list does not spell out. Each is pinned by a test below:

- **Repeated message ids with growing usage:** one message split over several lines must count once, at its final usage, not summed and not first-line. Task 2 (`test_duplicate_ids_count_once_with_field_wise_maximum`, `RealShapeTests`).
- **Odd subagent layouts:** missing or garbled `.meta.json`, a `subagents/` folder whose main session file is gone, nested runs, empty files. Task 2 (`LoadUnitsTests`).
- **Privacy:** a transcript full of prompt text must never leak into text or JSON output, including with `--show-descriptions`. Task 3 (`test_no_prompt_text_in_any_output`).
- **Unknown models:** a model missing from `rates.json` must not silently become $0 or crash; it shows `no rate` with its token count. Task 2 (`test_unit_with_an_unrated_model_has_no_cost`) and Task 3.
- **Frontmatter edge cases and undo safety:** CRLF, BOM, comments, quotes, duplicate keys, multi-line values, a body line that looks like `model:`, and undo after the user edited the file again. Task 5.
- **Comparisons that cannot be concluded:** too few spawns, unchanged model, a type with no spawns after the change. Task 4.

---

## File Structure

| File | Responsibility |
|---|---|
| `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts/audit.py` | Transcript parsing, attribution, cost, `report`, `snapshot`, `compare` |
| `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts/agent_edit.py` | Agent frontmatter `list`, `plan`, `apply`, `undo` with backups |
| `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/rates.json` | Dated per-model price table |
| `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/SKILL.md` | The conversation, recommendation rules, safety rules |
| `plugins/subagent-tax-auditor/README.md` | Public per-skill page |
| `tests/transcript_builder.py` | Builds synthetic transcript trees with real field names and no real text |
| `tests/test_audit.py`, `tests/test_agent_edit.py` | Unit tests |
| `tests/fixtures/audit/real_shape/` | A text-free tree sanitized from real transcripts |

Run all tests with: `python -m unittest discover -s tests -v` (from the repo root).

---

### Task 1: Scaffold the plugin, the transcript builder, and a real-shape fixture

**Files:**
- Create (generated): `plugins/subagent-tax-auditor/` (plugin.json, README.md, `skills/subagent-tax-auditor/SKILL.md`), marketplace and catalog entries
- Create: `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts/` (empty for now)
- Create: `tests/transcript_builder.py`
- Create: `tests/fixtures/audit/real_shape/` (sanitized real transcripts)
- Create (scratch, not committed): `$SP/sanitize_real.py`

**Interfaces:**
- Produces: `transcript_builder.assistant(mid, model="claude-sonnet-5-5", *, inp=0, out=0, read=0, write5=0, write1=0, ts="2026-10-01T10:00:00.000Z", breakdown=True, sidechain=False) -> dict`; `transcript_builder.user(ts=...) -> dict`; `transcript_builder.write_jsonl(path, records, raw_tail=())`; `transcript_builder.add_session(projects, slug, session_id, records, subagents=()) -> Path` where each subagent is a dict with keys `id`, `records`, optional `type` (default `general-purpose`), `description`, `alias`, `ts`, and `meta` (default True; False writes no meta file); `transcript_builder.SECRET` (a string that appears in every message body and must never reach script output). The fixture tree is `tests/fixtures/audit/real_shape/projects/C--fixture-proj/` containing `real-session-0001.jsonl` and `real-session-0001/subagents/agent-*.jsonl` with `.meta.json` files.

- [ ] **Step 1: Scaffold with the repo tool**

```bash
cd "C:/Users/naren/Documents/claude-skills"
python scripts/new_skill.py subagent-tax-auditor "Use when the user asks why their Claude Code quota or usage limit runs out so fast, which subagents cost the most, or wants their subagents made cheaper (for example 'audit my subagents', 'which agent is eating my quota', 'make my agents cheaper')."
mkdir -p plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts tests/fixtures/audit
python scripts/validate.py && python -m unittest discover -s tests 2>&1 | tail -3 && python scripts/build_catalog.py --check; echo exit=$?
```

Expected: `Created ...\plugins\subagent-tax-auditor`; `OK: all plugins valid`; tests OK; `exit=0`. If `build_catalog.py --check` fails because the generated README or llms.txt entries are not yet written, run `python scripts/build_catalog.py` once and re-run the check.

- [ ] **Step 2: Write the transcript builder**

Create `tests/transcript_builder.py`:

```python
"""Build synthetic Claude Code transcript trees for tests (real field names, no real text)."""
import json
from pathlib import Path

SECRET = "SECRET-PROMPT-TEXT"
DEFAULT_TS = "2026-10-01T10:00:00.000Z"


def assistant(mid, model="claude-sonnet-5-5", *, inp=0, out=0, read=0, write5=0, write1=0,
              ts=DEFAULT_TS, breakdown=True, sidechain=False):
    usage = {
        "input_tokens": inp,
        "cache_creation_input_tokens": write5 + write1,
        "cache_read_input_tokens": read,
        "output_tokens": out,
    }
    if breakdown:
        usage["cache_creation"] = {
            "ephemeral_5m_input_tokens": write5,
            "ephemeral_1h_input_tokens": write1,
        }
    return {
        "type": "assistant",
        "timestamp": ts,
        "isSidechain": sidechain,
        "message": {
            "id": mid,
            "model": model,
            "role": "assistant",
            "content": [{"type": "text", "text": SECRET}],
            "usage": usage,
        },
    }


def user(ts=DEFAULT_TS):
    return {"type": "user", "timestamp": ts, "message": {"role": "user", "content": SECRET}}


def write_jsonl(path, records, raw_tail=()):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(r) + "\n" for r in records) + "".join(line + "\n" for line in raw_tail)
    path.write_bytes(text.encode("utf-8"))


def add_session(projects, slug, session_id, records, subagents=()):
    """Write <projects>/<slug>/<session_id>.jsonl and one file (plus meta) per subagent."""
    pdir = Path(projects) / slug
    write_jsonl(pdir / f"{session_id}.jsonl", [user()] + list(records))
    for sub in subagents:
        base = str(pdir / session_id / "subagents" / f"agent-{sub['id']}")
        write_jsonl(base + ".jsonl", [user(sub.get("ts", DEFAULT_TS))] + list(sub["records"]))
        if sub.get("meta", True):
            meta = {
                "agentType": sub.get("type", "general-purpose"),
                "description": sub.get("description", "a task"),
                "toolUseId": "toolu_x",
                "spawnDepth": 1,
                "model": sub.get("alias", "sonnet"),
            }
            Path(base + ".meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return pdir
```

- [ ] **Step 3: Write and run the sanitizer on real transcripts**

Create `$SP/sanitize_real.py` (scratch):

```python
import glob
import json
import os
import shutil

SRC = os.path.expanduser(
    "~/.claude/projects/C--Users-naren-Documents-claude-skills/925e6d69-bb0e-4e19-b21e-3d0654ada34a"
)
DEST = "tests/fixtures/audit/real_shape/projects/C--fixture-proj"
MAX_LINES = 30


def clean(rec):
    message = rec.get("message")
    if rec.get("type") != "assistant" or not isinstance(message, dict) or "usage" not in message:
        return None
    return {
        "type": "assistant",
        "timestamp": rec.get("timestamp"),
        "isSidechain": rec.get("isSidechain"),
        "message": {"id": message["id"], "model": message["model"], "usage": message["usage"]},
    }


def load(path):
    out = []
    for line in open(path, encoding="utf-8"):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        cleaned = clean(rec)
        if cleaned:
            out.append(cleaned)
    return out


def has_changing_duplicate(records):
    seen = {}
    for rec in records:
        mid = rec["message"]["id"]
        usage = json.dumps(rec["message"]["usage"], sort_keys=True)
        if mid in seen and seen[mid] != usage:
            return True
        seen[mid] = usage
    return False


if os.path.isdir("tests/fixtures/audit/real_shape"):
    shutil.rmtree("tests/fixtures/audit/real_shape")
chosen = []
for path in sorted(glob.glob(os.path.join(SRC, "subagents", "agent-*.jsonl"))):
    records = load(path)[:MAX_LINES]
    if len(records) >= 4 and has_changing_duplicate(records):
        chosen.append((path, records))
    if len(chosen) == 2:
        break
assert chosen, "no subagent transcript with a repeated, changing message id was found"
os.makedirs(os.path.join(DEST, "real-session-0001", "subagents"))
main_records = load(SRC + ".jsonl")[:MAX_LINES]
with open(os.path.join(DEST, "real-session-0001.jsonl"), "w", encoding="utf-8", newline="\n") as f:
    for rec in main_records:
        f.write(json.dumps(rec) + "\n")
for index, (path, records) in enumerate(chosen, 1):
    name = f"agent-fixture{index}"
    sub = os.path.join(DEST, "real-session-0001", "subagents", name)
    with open(sub + ".jsonl", "w", encoding="utf-8", newline="\n") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    real_meta = json.load(open(path.replace(".jsonl", ".meta.json"), encoding="utf-8"))
    meta = {"agentType": real_meta.get("agentType", "general-purpose"), "description": "task",
            "toolUseId": "toolu_x", "spawnDepth": real_meta.get("spawnDepth", 1), "model": real_meta.get("model", "sonnet")}
    with open(sub + ".meta.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(meta) + "\n")
print("fixture written:", len(main_records), "main records,", len(chosen), "subagents")
```

Run it from the repo root: `python "$SP/sanitize_real.py"`

Expected: `fixture written: <n> main records, 2 subagents`. Then confirm no prompt text leaked and the fixture is small:

```bash
grep -rl '"content"\|"text"' tests/fixtures/audit/real_shape && echo LEAK || echo clean
du -sk tests/fixtures/audit/real_shape
```

Expected: `clean`; a few KB. If it prints `LEAK`, stop and fix the sanitizer. If the `assert` fails (no repeated id found), the transcript format differs from what the spec relies on: stop and report to the user.

- [ ] **Step 4: Verify and commit**

```bash
python scripts/validate.py && python -m unittest discover -s tests 2>&1 | tail -3 && python scripts/build_catalog.py --check; echo exit=$?
git add plugins/subagent-tax-auditor tests/transcript_builder.py tests/fixtures/audit .claude-plugin README.md llms.txt
git commit -m "feat: scaffold subagent-tax-auditor with a transcript builder and real-shape fixture" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Expected: valid, tests OK, `exit=0`, commit created. (If `git add` names a path that does not exist, drop it from the command; the catalog files that changed are whatever `build_catalog.py` rewrote.)

---

### Task 2: audit.py core: parsing, attribution, rates, cost

**Files:**
- Create: `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts/audit.py`
- Create: `tests/test_audit.py`

**Interfaces:**
- Consumes: `transcript_builder` (Task 1), the fixture tree (Task 1).
- Produces (all in `audit.py`):
  - `KINDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")`, `MIN_SPAWNS = 5`, `STALE_DAYS = 90`, `class AuditError(Exception)`.
  - `projects_dir(arg=None) -> Path`; `slug_for(path) -> str`.
  - `usage_counts(usage: dict) -> dict` (the five `KINDS`, non-negative ints).
  - `new_quality() -> dict`; `read_messages(path, quality) -> (start_timestamp_or_None, [ {"model": str, "tokens": dict} ])`; `read_meta(path) -> dict | None`.
  - `project_dirs(root, project=None, everything=False) -> [Path]`; `load_units(dirs, since, until, quality) -> [unit]` where a unit is `{"type": "main" | agentType | "unknown", "start": str, "messages": [...], "description": str}`.
  - `load_rates(path=None) -> dict`; `rate_for(rates, model) -> dict | None`; `cost_of(tokens, rate) -> float`; `rates_stale(rates, today=None) -> bool`.
  - `summarize(unit, rates) -> {"type", "start", "models": Counter, "per_model": {model: tokens}, "first_model", "tokens": dict, "cost": float | None, "fixed": int, "messages": int, "description": str}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_audit.py`:

```python
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import helpers
import transcript_builder as tb

sys.path.insert(
    0,
    str(helpers.REPO_ROOT / "plugins" / "subagent-tax-auditor" / "skills" / "subagent-tax-auditor" / "scripts"),
)
import audit  # noqa: E402

FIXTURE_ROOT = helpers.REPO_ROOT / "tests" / "fixtures" / "audit" / "real_shape" / "projects"

# Round numbers for tests only; these are not real prices.
RATES = {
    "as_of": "2026-10-01",
    "unit": "usd_per_million_tokens",
    "models": {
        "claude-sonnet-5-5": {"input": 3, "output": 15, "cache_read": 0.3, "cache_write_5m": 3.75, "cache_write_1h": 6},
        "claude-opus-5-5": {"input": 15, "output": 75, "cache_read": 1.5, "cache_write_5m": 18.75, "cache_write_1h": 30},
        "claude-haiku-4-5": {"input": 1, "output": 5, "cache_read": 0.1, "cache_write_5m": 1.25, "cache_write_1h": 2},
    },
}


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.projects = self.root / "projects"


class UsageTests(unittest.TestCase):
    def test_breakdown_is_used(self):
        usage = {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3,
                 "cache_creation_input_tokens": 10,
                 "cache_creation": {"ephemeral_5m_input_tokens": 4, "ephemeral_1h_input_tokens": 6}}
        self.assertEqual(audit.usage_counts(usage),
                         {"input": 1, "output": 2, "cache_read": 3, "cache_write_5m": 4, "cache_write_1h": 6})

    def test_missing_breakdown_counts_all_cache_writes_as_five_minute(self):
        counts = audit.usage_counts({"cache_creation_input_tokens": 10})
        self.assertEqual((counts["cache_write_5m"], counts["cache_write_1h"]), (10, 0))

    def test_unexplained_remainder_goes_to_five_minute(self):
        usage = {"cache_creation_input_tokens": 10,
                 "cache_creation": {"ephemeral_5m_input_tokens": 4, "ephemeral_1h_input_tokens": 3}}
        counts = audit.usage_counts(usage)
        self.assertEqual((counts["cache_write_5m"], counts["cache_write_1h"]), (7, 3))

    def test_bad_values_become_zero(self):
        counts = audit.usage_counts({"input_tokens": "x", "output_tokens": -5, "cache_read_input_tokens": True})
        self.assertEqual(sum(counts.values()), 0)


class ReadMessagesTests(TempCase):
    def read(self, records, raw_tail=()):
        path = self.root / "t.jsonl"
        tb.write_jsonl(path, records, raw_tail)
        quality = audit.new_quality()
        start, messages = audit.read_messages(path, quality)
        return start, messages, quality

    def test_duplicate_ids_count_once_with_field_wise_maximum(self):
        first = tb.assistant("m1", inp=5, out=10, read=100)
        second = tb.assistant("m1", inp=5, out=50, read=100)
        third = tb.assistant("m1", inp=3, out=20, read=120)
        _, messages, _ = self.read([first, second, third])
        self.assertEqual(len(messages), 1)
        tokens = messages[0]["tokens"]
        self.assertEqual((tokens["input"], tokens["output"], tokens["cache_read"]), (5, 50, 120))

    def test_message_order_is_first_appearance(self):
        _, messages, _ = self.read([tb.assistant("a", out=1), tb.assistant("b", out=2), tb.assistant("a", out=3)])
        self.assertEqual([m["tokens"]["output"] for m in messages], [3, 2])

    def test_synthetic_models_are_ignored(self):
        _, messages, quality = self.read([tb.assistant("s", model="<synthetic>", out=5)])
        self.assertEqual(messages, [])
        self.assertEqual(quality["lines_without_usage"], 0)

    def test_assistant_line_without_usage_is_counted(self):
        record = {"type": "assistant", "timestamp": tb.DEFAULT_TS, "message": {"id": "x", "model": "claude-sonnet-5-5"}}
        _, messages, quality = self.read([record])
        self.assertEqual((messages, quality["lines_without_usage"]), ([], 1))

    def test_malformed_lines_are_skipped_and_counted(self):
        _, messages, quality = self.read([tb.assistant("a", out=1)], raw_tail=["{not json", "[1, 2]", ""])
        self.assertEqual(len(messages), 1)
        self.assertEqual(quality["malformed_lines"], 2)

    def test_non_utf8_line_is_malformed(self):
        path = self.root / "t.jsonl"
        path.write_bytes(json.dumps(tb.assistant("a", out=1)).encode() + b"\n" + b"\xff\xfe broken\n")
        quality = audit.new_quality()
        _, messages = audit.read_messages(path, quality)
        self.assertEqual((len(messages), quality["malformed_lines"]), (1, 1))

    def test_bom_on_the_first_line_is_tolerated(self):
        path = self.root / "t.jsonl"
        path.write_bytes(b"\xef\xbb\xbf" + json.dumps(tb.assistant("a", out=1)).encode() + b"\r\n")
        quality = audit.new_quality()
        _, messages = audit.read_messages(path, quality)
        self.assertEqual((len(messages), quality["malformed_lines"]), (1, 0))

    def test_start_is_the_earliest_timestamp(self):
        start, _, _ = self.read([tb.assistant("a", ts="2026-10-02T00:00:00.000Z"), tb.user("2026-10-01T09:00:00.000Z")])
        self.assertEqual(start, "2026-10-01T09:00:00.000Z")

    def test_unreadable_file_is_counted(self):
        quality = audit.new_quality()
        self.assertEqual(audit.read_messages(self.root / "missing.jsonl", quality), (None, []))
        self.assertEqual(quality["unreadable_files"], 1)


class LoadUnitsTests(TempCase):
    def units(self, **kw):
        quality = audit.new_quality()
        dirs = audit.project_dirs(self.projects, everything=True)
        units = audit.load_units(dirs, kw.get("since"), kw.get("until"), quality)
        return units, quality

    def test_main_and_subagents_are_attributed(self):
        tb.add_session(self.projects, "C--p", "s1", [tb.assistant("m", out=1)], subagents=[
            {"id": "a1", "type": "Explore", "records": [tb.assistant("x", out=2, sidechain=True)]},
            {"id": "a2", "type": "reviewer", "records": [tb.assistant("y", out=3, sidechain=True)]},
        ])
        units, quality = self.units()
        self.assertEqual(sorted(u["type"] for u in units), ["Explore", "main", "reviewer"])
        self.assertEqual(quality["subagents_without_meta"], 0)

    def test_missing_meta_is_unknown_and_counted(self):
        tb.add_session(self.projects, "C--p", "s1", [tb.assistant("m", out=1)],
                       subagents=[{"id": "a1", "meta": False, "records": [tb.assistant("x", out=2)]}])
        units, quality = self.units()
        self.assertIn("unknown", [u["type"] for u in units])
        self.assertEqual(quality["subagents_without_meta"], 1)

    def test_garbled_meta_is_unknown(self):
        pdir = tb.add_session(self.projects, "C--p", "s1", [tb.assistant("m", out=1)],
                              subagents=[{"id": "a1", "records": [tb.assistant("x", out=2)]}])
        (pdir / "s1" / "subagents" / "agent-a1.meta.json").write_text("{nope", encoding="utf-8")
        units, quality = self.units()
        self.assertIn("unknown", [u["type"] for u in units])
        self.assertEqual(quality["subagents_without_meta"], 1)

    def test_subagents_are_found_even_without_the_main_session_file(self):
        pdir = tb.add_session(self.projects, "C--p", "s1", [tb.assistant("m", out=1)],
                              subagents=[{"id": "a1", "records": [tb.assistant("x", out=2)]}])
        (pdir / "s1.jsonl").unlink()
        units, _ = self.units()
        self.assertEqual([u["type"] for u in units], ["general-purpose"])

    def test_empty_transcripts_are_dropped(self):
        tb.write_jsonl(self.projects / "C--p" / "s1.jsonl", [tb.user()])
        units, _ = self.units()
        self.assertEqual(units, [])

    def test_date_filters_apply_to_each_file_start(self):
        tb.add_session(self.projects, "C--p", "old", [tb.assistant("a", ts="2026-09-01T10:00:00.000Z", out=1)])
        tb.add_session(self.projects, "C--p", "new", [tb.assistant("b", ts="2026-10-02T10:00:00.000Z", out=1)])
        units, _ = self.units(since="2026-10-01")
        self.assertEqual(len(units), 1)
        units, _ = self.units(until="2026-09-30")
        self.assertEqual(len(units), 1)

    def test_project_dirs_selects_by_slug_and_reports_missing(self):
        tb.add_session(self.projects, audit.slug_for(self.root / "proj"), "s1", [tb.assistant("m", out=1)])
        found = audit.project_dirs(self.projects, project=str(self.root / "proj"))
        self.assertEqual([p.name for p in found], [audit.slug_for(self.root / "proj")])
        self.assertEqual(audit.project_dirs(self.projects, project=str(self.root / "other")), [])
        with self.assertRaises(audit.AuditError):
            audit.project_dirs(self.root / "no-such-dir", everything=True)

    def test_slug_replaces_every_non_alphanumeric_character(self):
        slug = audit.slug_for(self.root / "my_proj.v2")
        self.assertRegex(slug, r"^[A-Za-z0-9-]+$")
        self.assertTrue(slug.endswith("my-proj-v2"))


class RatesTests(TempCase):
    def test_rate_for_exact_and_longest_prefix(self):
        rates = {"models": {"claude-sonnet": {"input": 1}, "claude-sonnet-5-5": {"input": 2}}}
        self.assertEqual(audit.rate_for(rates, "claude-sonnet-5-5")["input"], 2)
        self.assertEqual(audit.rate_for(rates, "claude-sonnet-5-5-20260101")["input"], 2)
        self.assertEqual(audit.rate_for(rates, "claude-sonnet-4")["input"], 1)
        self.assertIsNone(audit.rate_for(rates, "claude-mystery-1"))

    def test_load_rates_validates(self):
        path = self.root / "rates.json"
        path.write_text(json.dumps(RATES), encoding="utf-8")
        self.assertEqual(audit.load_rates(path)["as_of"], "2026-10-01")
        bad = {"as_of": "2026-10-01", "models": {"m": {"input": 1}}}
        path.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(audit.AuditError):
            audit.load_rates(path)
        path.write_text("{nope", encoding="utf-8")
        with self.assertRaises(audit.AuditError):
            audit.load_rates(path)
        with self.assertRaises(audit.AuditError):
            audit.load_rates(self.root / "absent.json")

    def test_rates_stale_after_ninety_days(self):
        self.assertFalse(audit.rates_stale(RATES, today=date(2026, 12, 29)))
        self.assertTrue(audit.rates_stale(RATES, today=date(2026, 12, 31)))

    def test_cost_of_uses_per_million_rates(self):
        tokens = {"input": 1_000_000, "output": 1_000_000, "cache_read": 1_000_000,
                  "cache_write_5m": 1_000_000, "cache_write_1h": 1_000_000}
        self.assertAlmostEqual(audit.cost_of(tokens, RATES["models"]["claude-sonnet-5-5"]), 3 + 15 + 0.3 + 3.75 + 6)


class SummarizeTests(unittest.TestCase):
    def unit(self, messages, kind="general-purpose"):
        return {"type": kind, "start": tb.DEFAULT_TS, "messages": messages, "description": "d"}

    def message(self, model, **tokens):
        full = dict.fromkeys(audit.KINDS, 0)
        full.update(tokens)
        return {"model": model, "tokens": full}

    def test_cost_and_fixed_context(self):
        unit = self.unit([
            self.message("claude-sonnet-5-5", input=1_000_000, cache_read=500, cache_write_5m=250),
            self.message("claude-sonnet-5-5", output=1_000_000),
        ])
        summary = audit.summarize(unit, RATES)
        self.assertAlmostEqual(summary["cost"], 3 + 15 + (500 * 0.3 + 250 * 3.75) / 1e6)
        self.assertEqual(summary["fixed"], 750)
        self.assertEqual(summary["messages"], 2)
        self.assertEqual(summary["first_model"], "claude-sonnet-5-5")

    def test_unit_with_an_unrated_model_has_no_cost(self):
        summary = audit.summarize(self.unit([self.message("claude-mystery-1", output=10)]), RATES)
        self.assertIsNone(summary["cost"])
        self.assertEqual(summary["tokens"]["output"], 10)

    def test_a_unit_that_switches_models_keeps_per_model_tokens(self):
        unit = self.unit([self.message("claude-opus-5-5", output=1), self.message("claude-sonnet-5-5", output=2)], "main")
        summary = audit.summarize(unit, RATES)
        self.assertEqual({m: t["output"] for m, t in summary["per_model"].items()},
                         {"claude-opus-5-5": 1, "claude-sonnet-5-5": 2})


class RealShapeTests(unittest.TestCase):
    def test_real_shaped_tree_parses_and_deduplicates(self):
        quality = audit.new_quality()
        dirs = audit.project_dirs(FIXTURE_ROOT, everything=True)
        units = audit.load_units(dirs, None, None, quality)
        self.assertGreaterEqual(len(units), 3)  # one main session and two subagents
        self.assertEqual(quality["malformed_lines"], 0)
        for path in FIXTURE_ROOT.rglob("agent-*.jsonl"):
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            ids = [line["message"]["id"] for line in lines]
            self.assertGreater(len(ids), len(set(ids)), "fixture must contain a repeated message id")
        for unit in units:
            self.assertGreater(sum(m["tokens"]["output"] + m["tokens"]["cache_read"] for m in unit["messages"]), 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_audit.py" 2>&1 | tail -15`
Expected: error `ModuleNotFoundError: No module named 'audit'` (or import failure), because the script does not exist yet.

- [ ] **Step 3: Write the minimal implementation**

Create `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts/audit.py`:

```python
#!/usr/bin/env python3
"""audit: attribute Claude Code token usage to the main thread and to each subagent type.

    python audit.py report   [--project PATH | --all] [--since D] [--until D] [--projects-dir DIR]
                             [--rates FILE] [--json] [--show-descriptions]
    python audit.py snapshot --out FILE [same selectors]
    python audit.py compare  --snapshot FILE [same selectors]

Read-only (snapshot writes only its --out file). Standard library only. Prompts, responses and
file contents are never printed.
"""
import argparse
import json
import os
import re
import statistics
import sys
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

KINDS = ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")
MIN_SPAWNS = 5
STALE_DAYS = 90
SYNTHETIC = "<synthetic>"


class AuditError(Exception):
    """A problem the user can fix; reported as `error: ...` with exit 2."""


# --- locating transcripts ------------------------------------------------------------------

def projects_dir(arg=None):
    if arg:
        return Path(arg)
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "projects"


def slug_for(path):
    """Claude Code names a project folder after its path with every non-alphanumeric character as -."""
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(str(path)))


def project_dirs(root, project=None, everything=False):
    root = Path(root)
    if not root.is_dir():
        raise AuditError(f"transcripts directory not found: {root}")
    if everything:
        return sorted(p for p in root.iterdir() if p.is_dir())
    target = root / slug_for(project or os.getcwd())
    return [target] if target.is_dir() else []


# --- reading transcripts -------------------------------------------------------------------

def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def usage_counts(usage):
    breakdown = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    write_5m = _count(breakdown.get("ephemeral_5m_input_tokens"))
    write_1h = _count(breakdown.get("ephemeral_1h_input_tokens"))
    total = _count(usage.get("cache_creation_input_tokens"))
    if write_5m + write_1h < total:
        write_5m += total - (write_5m + write_1h)
    return {
        "input": _count(usage.get("input_tokens")),
        "output": _count(usage.get("output_tokens")),
        "cache_read": _count(usage.get("cache_read_input_tokens")),
        "cache_write_5m": write_5m,
        "cache_write_1h": write_1h,
    }


def new_quality():
    return {"malformed_lines": 0, "lines_without_usage": 0, "unreadable_files": 0, "subagents_without_meta": 0}


def read_messages(path, quality):
    """(first timestamp, messages) for one transcript file.

    A message id can span several lines (one per content block, usage still growing), so each id
    is counted once, with the largest value seen for every token kind.
    """
    by_id, order, start, anonymous = {}, [], None, 0
    try:
        handle = open(path, "rb")
    except OSError:
        quality["unreadable_files"] += 1
        return None, []
    with handle:
        for raw in handle:
            if not raw.strip():
                continue
            try:
                record = json.loads(raw.decode("utf-8-sig"))
            except ValueError:
                quality["malformed_lines"] += 1
                continue
            if not isinstance(record, dict):
                quality["malformed_lines"] += 1
                continue
            stamp = record.get("timestamp")
            if isinstance(stamp, str) and (start is None or stamp < start):
                start = stamp
            message = record.get("message")
            if record.get("type") != "assistant" or not isinstance(message, dict):
                continue
            model = message.get("model")
            if model == SYNTHETIC:
                continue
            if not isinstance(message.get("usage"), dict):
                quality["lines_without_usage"] += 1
                continue
            mid = message.get("id")
            if not isinstance(mid, str) or not mid:
                anonymous += 1
                mid = f"line-{anonymous}"
            tokens = usage_counts(message["usage"])
            if mid in by_id:
                seen = by_id[mid]["tokens"]
                for kind in KINDS:
                    seen[kind] = max(seen[kind], tokens[kind])
            else:
                by_id[mid] = {"model": model if isinstance(model, str) and model else "unknown", "tokens": tokens}
                order.append(mid)
    return start, [by_id[i] for i in order]


def read_meta(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _unit(kind, path, description, since, until, quality):
    start, messages = read_messages(path, quality)
    if not messages or start is None:
        return None
    day = start[:10]
    if (since and day < since) or (until and day > until):
        return None
    return {"type": kind, "start": start, "messages": messages, "description": description}


def load_units(dirs, since, until, quality):
    """Every main session and every subagent run, as units attributed to a type."""
    units = []
    for pdir in dirs:
        for session in sorted(pdir.glob("*.jsonl")):
            unit = _unit("main", session, "", since, until, quality)
            if unit:
                units.append(unit)
        for subdir in sorted(p / "subagents" for p in pdir.iterdir() if (p / "subagents").is_dir()):
            for agent in sorted(subdir.glob("agent-*.jsonl")):
                meta = read_meta(agent.with_suffix(".meta.json"))
                kind = meta.get("agentType") if meta else None
                if not isinstance(kind, str) or not kind:
                    kind = "unknown"
                    quality["subagents_without_meta"] += 1
                description = meta.get("description", "") if meta else ""
                unit = _unit(kind, agent, description if isinstance(description, str) else "", since, until, quality)
                if unit:
                    units.append(unit)
    return units


# --- rates and cost ------------------------------------------------------------------------

def load_rates(path=None):
    path = Path(path) if path else Path(__file__).resolve().parent.parent / "rates.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise AuditError(f"cannot read the rates file {path} ({exc.strerror or exc})") from None
    except ValueError as exc:
        raise AuditError(f"{path} is not valid JSON ({exc})") from None
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, dict) or not isinstance(data.get("as_of"), str):
        raise AuditError(f'{path} needs "as_of" and "models"')
    for name, rate in models.items():
        if not isinstance(rate, dict) or any(
            not isinstance(rate.get(k), (int, float)) or isinstance(rate.get(k), bool) or rate[k] < 0 for k in KINDS
        ):
            raise AuditError(f"{path}: model {name!r} needs a non-negative number for each of {', '.join(KINDS)}")
    return data


def rate_for(rates, model):
    models = rates["models"]
    if model in models:
        return models[model]
    prefixes = [name for name in models if model.startswith(name)]
    return models[max(prefixes, key=len)] if prefixes else None


def cost_of(tokens, rate):
    return sum(tokens[kind] * rate[kind] for kind in KINDS) / 1_000_000


def rates_stale(rates, today=None):
    try:
        as_of = date.fromisoformat(rates["as_of"])
    except ValueError:
        return True
    return ((today or date.today()) - as_of).days > STALE_DAYS


# --- one unit's numbers --------------------------------------------------------------------

def summarize(unit, rates):
    models, per_model = Counter(), {}
    for message in unit["messages"]:
        models[message["model"]] += 1
        slot = per_model.setdefault(message["model"], dict.fromkeys(KINDS, 0))
        for kind in KINDS:
            slot[kind] += message["tokens"][kind]
    total, cost, priced = dict.fromkeys(KINDS, 0), 0.0, True
    for model, tokens in per_model.items():
        for kind in KINDS:
            total[kind] += tokens[kind]
        rate = rate_for(rates, model)
        if rate is None:
            priced = False
        else:
            cost += cost_of(tokens, rate)
    first = unit["messages"][0]
    return {
        "type": unit["type"],
        "start": unit["start"],
        "models": models,
        "per_model": per_model,
        "first_model": first["model"],
        "tokens": total,
        "cost": cost if priced else None,
        "fixed": first["tokens"]["cache_read"] + first["tokens"]["cache_write_5m"] + first["tokens"]["cache_write_1h"],
        "messages": len(unit["messages"]),
        "description": unit["description"],
    }


if __name__ == "__main__":
    sys.exit("audit.py: the command line is added in the next task")
```

(`argparse`, `statistics`, `datetime`, `timezone` are imported now and used from Task 3 on; leave them.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s tests -p "test_audit.py" -v 2>&1 | tail -30`
Expected: all tests in `UsageTests`, `ReadMessagesTests`, `LoadUnitsTests`, `RatesTests`, `SummarizeTests`, `RealShapeTests` PASS. If `test_date_filters_apply_to_each_file_start` fails because the file start comes from the `user()` record, fix the test as described in Step 1, not the code.

- [ ] **Step 5: Run the full suite and commit**

```bash
python -m unittest discover -s tests 2>&1 | grep -v "^warning" | tail -3
python scripts/validate.py
git add plugins/subagent-tax-auditor tests/test_audit.py
git commit -m "feat: parse transcripts, attribute usage to agent types, and price it from a rates file" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Expected: suite OK, `OK: all plugins valid`, commit created.

---

### Task 3: audit.py report: aggregation, text and JSON output, CLI

**Files:**
- Modify: `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts/audit.py`
- Modify: `tests/test_audit.py`

**Interfaces:**
- Consumes: everything produced in Task 2.
- Produces:
  - `build_report(sums, rates, quality, selectors, show_descriptions=False, today=None) -> dict` with keys `selectors`, `rates_as_of`, `rates_stale`, `totals` (`cost`, `output`, `tokens`), `rows` (each: `type`, `model`, `spawns`, `messages`, `tokens`, `cost` (float | None), `cost_share`, `output_share`, `fixed_context_median` (int | None), `has_rate`, and `descriptions` only when `show_descriptions`), `quality` (the `new_quality()` keys plus `sessions`, `subagent_runs`, `first_day`, `last_day`, `models_without_rate`: `{model: tokens}`).
  - `format_report(report) -> str`.
  - `add_selectors(parser)`, `gather(args) -> (sums, quality, selectors, rates)`, `main(argv=None) -> int` with the `report` command. Exit codes: 0 ok, 2 on `AuditError` or `OSError` (`error: ...` on stderr).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_audit.py` (before the `if __name__` line):

```python
import contextlib
import io


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = audit.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class ReportCase(TempCase):
    """main: one opus message; general-purpose: two sonnet runs; Explore: one run on an unrated model."""

    def setUp(self):
        super().setUp()
        self.project = self.root / "proj"
        self.slug = audit.slug_for(self.project)
        self.rates_path = self.root / "rates.json"
        self.rates_path.write_text(json.dumps(RATES), encoding="utf-8")
        gp = lambda n: {"id": f"gp{n}", "type": "general-purpose", "description": "a task", "records": [  # noqa: E731
            tb.assistant(f"g{n}a", read=1_000_000, write5=500_000, out=1_000, sidechain=True),
            tb.assistant(f"g{n}b", read=1_500_000, out=1_000, sidechain=True)]}
        explore = {"id": "ex1", "type": "Explore", "records": [
            tb.assistant("e1", model="claude-mystery-1", read=100, out=500, sidechain=True)]}
        tb.add_session(self.projects, self.slug, "s1",
                       [tb.assistant("m1", model="claude-opus-5-5", write5=2_000_000, out=10_000)],
                       subagents=[gp(1), gp(2), explore])
        tb.add_session(self.projects, self.slug, "old", [tb.assistant("o1", ts="2026-09-01T10:00:00.000Z", out=1)])

    def report(self, **kw):
        quality = audit.new_quality()
        dirs = audit.project_dirs(self.projects, project=str(self.project))
        units = audit.load_units(dirs, kw.get("since"), kw.get("until"), quality)
        sums = [audit.summarize(u, RATES) for u in units]
        return audit.build_report(sums, RATES, quality, {"project": str(self.project)},
                                  show_descriptions=kw.get("show", False), today=date(2026, 10, 3))

    def row(self, report, kind):
        return next(r for r in report["rows"] if r["type"] == kind)


class ReportTests(ReportCase):
    def test_rows_costs_and_shares(self):
        report = self.report(since="2026-10-01")
        main = self.row(report, "main")
        self.assertAlmostEqual(main["cost"], 2_000_000 * 18.75 / 1e6 + 10_000 * 75 / 1e6)  # 38.25
        gp = self.row(report, "general-purpose")
        self.assertEqual((gp["spawns"], gp["messages"]), (2, 4))
        self.assertAlmostEqual(gp["cost"], 2 * (0.3 + 1.875 + 0.015 + 0.45 + 0.015))  # 5.31
        self.assertEqual(gp["fixed_context_median"], 1_500_000)
        self.assertEqual(gp["tokens"]["output"], 4_000)
        total = 38.25 + 5.31
        self.assertAlmostEqual(report["totals"]["cost"], total)
        self.assertAlmostEqual(gp["cost_share"], 5.31 / total)
        self.assertAlmostEqual(gp["output_share"], 4_000 / 14_500)

    def test_unrated_model_shows_no_rate_and_stays_out_of_cost(self):
        report = self.report(since="2026-10-01")
        explore = self.row(report, "Explore")
        self.assertIsNone(explore["cost"])
        self.assertFalse(explore["has_rate"])
        self.assertIsNone(explore["cost_share"])
        self.assertEqual(report["quality"]["models_without_rate"], {"claude-mystery-1": 600})
        self.assertIn("no rate", audit.format_report(report))

    def test_rows_are_sorted_by_cost_with_unrated_last(self):
        report = self.report(since="2026-10-01")
        self.assertEqual([r["type"] for r in report["rows"]], ["main", "general-purpose", "Explore"])

    def test_date_filter_excludes_old_sessions(self):
        self.assertEqual(self.report(since="2026-10-01")["quality"]["sessions"], 1)
        self.assertEqual(self.report()["quality"]["sessions"], 2)

    def test_quality_footer_numbers(self):
        quality = self.report(since="2026-10-01")["quality"]
        self.assertEqual((quality["sessions"], quality["subagent_runs"]), (1, 3))
        self.assertEqual(quality["first_day"], "2026-10-01")

    def test_no_prompt_text_in_any_output(self):
        report = self.report(show=True)
        self.assertNotIn(tb.SECRET, json.dumps(report))
        self.assertNotIn(tb.SECRET, audit.format_report(report))

    def test_descriptions_only_when_asked(self):
        self.assertNotIn("descriptions", self.row(self.report(), "general-purpose"))
        shown = self.report(show=True)
        self.assertEqual(self.row(shown, "general-purpose")["descriptions"], ["a task"])
        self.assertIn("a task", audit.format_report(shown))

    def test_text_report_states_the_proxy_caveat_and_the_rates_date(self):
        text = audit.format_report(self.report(since="2026-10-01"))
        self.assertIn("proxy", text)
        self.assertIn("2026-10-01", text)
        self.assertIn("general-purpose", text)

    def test_stale_rates_are_flagged(self):
        quality = audit.new_quality()
        dirs = audit.project_dirs(self.projects, project=str(self.project))
        sums = [audit.summarize(u, RATES) for u in audit.load_units(dirs, None, None, quality)]
        report = audit.build_report(sums, RATES, quality, {}, today=date(2027, 3, 1))
        self.assertTrue(report["rates_stale"])
        self.assertIn("older than", audit.format_report(report))

    def test_empty_report_renders(self):
        report = audit.build_report([], RATES, audit.new_quality(), {})
        self.assertIn("No usage found", audit.format_report(report))


class ReportCliTests(ReportCase):
    def args(self, *extra):
        return ["report", "--projects-dir", str(self.projects), "--rates", str(self.rates_path),
                "--project", str(self.project), *extra]

    def test_json_matches_the_text_numbers(self):
        code, out, _ = run_cli(*self.args("--json", "--since", "2026-10-01"))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertAlmostEqual(data["totals"]["cost"], 38.25 + 5.31)
        code, text, _ = run_cli(*self.args("--since", "2026-10-01"))
        self.assertEqual(code, 0)
        self.assertIn("$38.25", text)
        self.assertIn("$5.31", text)

    def test_all_flag_reads_every_project(self):
        tb.add_session(self.projects, "C--other", "s9", [tb.assistant("z", out=7)])
        code, out, _ = run_cli("report", "--all", "--projects-dir", str(self.projects),
                               "--rates", str(self.rates_path), "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["quality"]["sessions"], 3)

    def test_missing_projects_dir_is_an_error(self):
        code, _, err = run_cli("report", "--all", "--projects-dir", str(self.root / "nope"), "--rates", str(self.rates_path))
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("error:"))

    def test_project_without_transcripts_is_a_message_not_an_error(self):
        code, out, _ = run_cli("report", "--projects-dir", str(self.projects), "--rates", str(self.rates_path),
                               "--project", str(self.root / "elsewhere"))
        self.assertEqual(code, 0)
        self.assertIn("No transcripts found", out)

    def test_bad_date_and_bad_rates_are_errors(self):
        code, _, err = run_cli(*self.args("--since", "10/01/2026"))
        self.assertEqual(code, 2)
        self.assertIn("YYYY-MM-DD", err)
        bad = self.root / "bad.json"
        bad.write_text("{nope", encoding="utf-8")
        code, _, err = run_cli("report", "--projects-dir", str(self.projects), "--rates", str(bad))
        self.assertEqual(code, 2)

    def test_malformed_lines_surface_in_the_footer(self):
        pdir = self.projects / self.slug
        with open(pdir / "s1.jsonl", "ab") as f:
            f.write(b"{broken\n")
        code, out, _ = run_cli(*self.args("--since", "2026-10-01"))
        self.assertEqual(code, 0)
        self.assertIn("1 malformed", out)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_audit.py" 2>&1 | tail -12`
Expected: failures/errors for `build_report`, `format_report`, `main` not defined (`AttributeError`).

- [ ] **Step 3: Implement report building, formatting and the CLI**

In `audit.py`, replace the final `if __name__ == "__main__": sys.exit(...)` block with the code below (keep everything above it):

```python
# --- the report ----------------------------------------------------------------------------

def build_report(sums, rates, quality, selectors, show_descriptions=False, today=None):
    rows = {}
    for s in sums:
        for model, tokens in s["per_model"].items():
            row = rows.setdefault((s["type"], model), {
                "type": s["type"], "model": model, "spawns": 0, "messages": 0,
                "tokens": dict.fromkeys(KINDS, 0), "fixed": [], "descriptions": set()})
            row["spawns"] += 1
            row["messages"] += s["models"][model]
            for kind in KINDS:
                row["tokens"][kind] += tokens[kind]
            if s["description"]:
                row["descriptions"].add(s["description"])
        rows[(s["type"], s["first_model"])]["fixed"].append(s["fixed"])
    out, unrated, total_cost, total_output, total_tokens = [], {}, 0.0, 0, 0
    for row in rows.values():
        rate = rate_for(rates, row["model"])
        cost = cost_of(row["tokens"], rate) if rate else None
        volume = sum(row["tokens"].values())
        if cost is None:
            unrated[row["model"]] = unrated.get(row["model"], 0) + volume
        else:
            total_cost += cost
        total_output += row["tokens"]["output"]
        total_tokens += volume
        entry = {
            "type": row["type"], "model": row["model"], "spawns": row["spawns"], "messages": row["messages"],
            "tokens": row["tokens"], "cost": cost, "has_rate": rate is not None,
            "fixed_context_median": int(statistics.median(row["fixed"])) if row["fixed"] else None,
        }
        if show_descriptions:
            entry["descriptions"] = sorted(row["descriptions"])[:5]
        out.append(entry)
    for entry in out:
        entry["cost_share"] = entry["cost"] / total_cost if entry["cost"] is not None and total_cost > 0 else None
        entry["output_share"] = entry["tokens"]["output"] / total_output if total_output > 0 else None
    out.sort(key=lambda e: (e["cost"] is None, -(e["cost"] or 0), -sum(e["tokens"].values())))
    days = sorted(s["start"][:10] for s in sums)
    return {
        "selectors": selectors,
        "rates_as_of": rates["as_of"],
        "rates_stale": rates_stale(rates, today),
        "totals": {"cost": total_cost, "output": total_output, "tokens": total_tokens},
        "rows": out,
        "quality": {
            **quality,
            "sessions": sum(1 for s in sums if s["type"] == "main"),
            "subagent_runs": sum(1 for s in sums if s["type"] != "main"),
            "first_day": days[0] if days else None,
            "last_day": days[-1] if days else None,
            "models_without_rate": unrated,
        },
    }


def _money(value):
    return "no rate" if value is None else f"${value:,.2f}"


def _share(value):
    return "-" if value is None else f"{value * 100:.1f}%"


def format_report(report):
    quality = report["quality"]
    if not report["rows"]:
        return "No usage found for this selection.\n"
    lines = [
        f"Subagent tax report: {quality['sessions']} sessions, {quality['subagent_runs']} subagent runs, "
        f"{quality['first_day']} to {quality['last_day']}",
        f"Cost is a proxy: tokens times published API rates as of {report['rates_as_of']}. "
        "Your subscription quota is not measured in dollars.",
        "",
        f"{'type':<22}{'model':<26}{'spawns':>7}{'cost':>11}{'cost%':>8}{'output%':>9}{'fixed ctx/spawn':>17}{'output tok':>12}",
    ]
    for row in report["rows"]:
        fixed = "-" if row["fixed_context_median"] is None else f"{row['fixed_context_median']:,}"
        lines.append(
            f"{row['type'][:21]:<22}{row['model'][:25]:<26}{row['spawns']:>7}{_money(row['cost']):>11}"
            f"{_share(row['cost_share']):>8}{_share(row['output_share']):>9}{fixed:>17}{row['tokens']['output']:>12,}")
        for description in row.get("descriptions", []):
            lines.append(f"    - {description}")
    totals = report["totals"]
    lines += [f"{'total':<48}{'':>7}{_money(totals['cost']):>11}{'':>8}{'':>9}{'':>17}{totals['output']:>12,}", ""]
    notes = []
    if quality["malformed_lines"]:
        notes.append(f"{quality['malformed_lines']} malformed lines skipped")
    if quality["lines_without_usage"]:
        notes.append(f"{quality['lines_without_usage']} assistant lines without usage skipped")
    if quality["unreadable_files"]:
        notes.append(f"{quality['unreadable_files']} unreadable files skipped")
    if quality["subagents_without_meta"]:
        notes.append(f"{quality['subagents_without_meta']} subagent runs without a readable meta file (typed unknown)")
    for model, tokens in sorted(quality["models_without_rate"].items()):
        notes.append(f"{model}: no rate in rates.json, {tokens:,} tokens left out of cost")
    if report["rates_stale"]:
        notes.append(f"rates.json is older than {STALE_DAYS} days; check the prices")
    lines.append("Data quality: " + ("; ".join(notes) if notes else "no problems found"))
    return "\n".join(lines) + "\n"


# --- command line --------------------------------------------------------------------------

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def add_selectors(parser):
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--project", help="project directory (default: the current directory)")
    group.add_argument("--all", action="store_true", help="every project")
    parser.add_argument("--since", help="only files that started on or after YYYY-MM-DD")
    parser.add_argument("--until", help="only files that started on or before YYYY-MM-DD")
    parser.add_argument("--projects-dir", help="transcripts directory (default: $CLAUDE_CONFIG_DIR/projects or ~/.claude/projects)")
    parser.add_argument("--rates", help="rates file (default: rates.json next to scripts/)")


def gather(args, project=None, everything=None):
    for flag in ("since", "until"):
        value = getattr(args, flag, None)
        if value and not _DAY.match(value):
            raise AuditError(f"--{flag} must be YYYY-MM-DD")
    project = args.project if project is None else project
    everything = args.all if everything is None else everything
    rates = load_rates(args.rates)
    quality = new_quality()
    dirs = project_dirs(projects_dir(args.projects_dir), project, everything)
    sums = [summarize(u, rates) for u in load_units(dirs, args.since, args.until, quality)]
    selectors = {"project": os.path.abspath(project) if project else None, "all": bool(everything),
                 "since": args.since, "until": args.until}
    return sums, quality, selectors, rates, bool(dirs)


def cmd_report(args):
    sums, quality, selectors, rates, found = gather(args)
    if not found:
        print(f"No transcripts found for {os.path.abspath(args.project or os.getcwd())} "
              "(use --all to read every project, or --project PATH).")
        return 0
    report = build_report(sums, rates, quality, selectors, show_descriptions=args.show_descriptions)
    print(json.dumps(report, indent=2) if args.json else format_report(report), end="" if not args.json else "\n")
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="audit.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    report = sub.add_parser("report", help="split usage between the main thread and each subagent type")
    add_selectors(report)
    report.add_argument("--json", action="store_true")
    report.add_argument("--show-descriptions", action="store_true", help="include task descriptions (off by default)")
    report.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (AuditError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s tests -p "test_audit.py" -v 2>&1 | tail -40`
Expected: all PASS. If a number in `test_rows_costs_and_shares` is off, recompute it by hand from the test data (the comments show the arithmetic) before touching the code: the test numbers are derived independently of the implementation.

- [ ] **Step 5: Run the full suite and commit**

```bash
python -m unittest discover -s tests 2>&1 | grep -v "^warning" | tail -3
python scripts/validate.py
git add plugins/subagent-tax-auditor tests/test_audit.py
git commit -m "feat: add the audit report with text and JSON output" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Expected: suite OK, valid, commit created.

---

### Task 4: audit.py snapshot and compare

**Files:**
- Modify: `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts/audit.py`
- Modify: `tests/test_audit.py`

**Interfaces:**
- Consumes: `summarize` outputs (`sums`), `gather`, `add_selectors`, `MIN_SPAWNS` from earlier tasks.
- Produces:
  - `type_stats(sums) -> {type: {"spawns", "models" (sorted list), "fixed_median", "tokens_median", "cost_median" (float | None)}}`.
  - `snapshot_data(sums, rates, selectors, now=None) -> {"timestamp", "rates_as_of", "selectors", "types"}`; `now` is a string `YYYY-MM-DDTHH:MM:SS.mmmZ`.
  - `verdict(before, after) -> str`; `compare(snapshot, sums, rates) -> {"rates_note": str | None, "types": [{"type", "before", "after", "verdict"}]}` where `after` covers only sums whose `start` is greater than the snapshot timestamp.
  - `format_compare(result) -> str`; CLI commands `snapshot --out FILE [selectors]` and `compare --snapshot FILE [selectors] [--json]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_audit.py` (before the `if __name__` line):

```python
BEFORE = "2026-10-01T10:00:00.000Z"
AFTER = "2026-10-05T10:00:00.000Z"
STAMP = "2026-10-03T00:00:00.000Z"


class CompareCase(TempCase):
    def setUp(self):
        super().setUp()
        self.project = self.root / "proj"
        self.slug = audit.slug_for(self.project)
        self.rates_path = self.root / "rates.json"
        self.rates_path.write_text(json.dumps(RATES), encoding="utf-8")
        self.count = 0

    def spawns(self, kind, model, n, ts):
        subs = []
        for _ in range(n):
            self.count += 1
            subs.append({"id": f"a{self.count}", "type": kind, "ts": ts, "records": [
                tb.assistant(f"x{self.count}", model=model, read=1_000_000, out=1_000, ts=ts, sidechain=True)]})
        return subs

    def build(self, subagents):
        tb.add_session(self.projects, self.slug, f"s{self.count}", [tb.assistant(f"m{self.count}", out=1)],
                       subagents=subagents)

    def sums(self):
        quality = audit.new_quality()
        dirs = audit.project_dirs(self.projects, project=str(self.project))
        return [audit.summarize(u, RATES) for u in audit.load_units(dirs, None, None, quality)]

    def snapshot_and_compare(self):
        sums = self.sums()
        snap = audit.snapshot_data([s for s in sums if s["start"] <= STAMP], RATES, {"project": str(self.project), "all": False}, now=STAMP)
        return snap, audit.compare(snap, sums, RATES)

    def entry(self, result, kind):
        return next(t for t in result["types"] if t["type"] == kind)


class SnapshotCompareTests(CompareCase):
    def test_snapshot_shape(self):
        self.build(self.spawns("reviewer", "claude-sonnet-5-5", 6, BEFORE))
        snap, _ = self.snapshot_and_compare()
        self.assertEqual(snap["timestamp"], STAMP)
        self.assertEqual(snap["rates_as_of"], "2026-10-01")
        stats = snap["types"]["reviewer"]
        self.assertEqual((stats["spawns"], stats["models"]), (6, ["claude-sonnet-5-5"]))
        self.assertEqual(stats["fixed_median"], 1_000_000)
        self.assertAlmostEqual(stats["cost_median"], 0.3 + 0.015)

    def test_model_change_reports_the_percentage_change(self):
        self.build(self.spawns("reviewer", "claude-sonnet-5-5", 6, BEFORE) + self.spawns("reviewer", "claude-haiku-4-5", 6, AFTER))
        _, result = self.snapshot_and_compare()
        entry = self.entry(result, "reviewer")
        self.assertEqual((entry["before"]["spawns"], entry["after"]["spawns"]), (6, 6))
        self.assertIn("fell 67%", entry["verdict"])
        self.assertIn("trend, not proof", entry["verdict"])

    def test_unchanged_model_says_so(self):
        self.build(self.spawns("reviewer", "claude-sonnet-5-5", 6, BEFORE) + self.spawns("reviewer", "claude-sonnet-5-5", 6, AFTER))
        self.assertIn("model unchanged", self.entry(self.snapshot_and_compare()[1], "reviewer")["verdict"])

    def test_small_samples_give_no_verdict(self):
        self.build(self.spawns("reviewer", "claude-sonnet-5-5", 6, BEFORE) + self.spawns("reviewer", "claude-haiku-4-5", 3, AFTER))
        verdict = self.entry(self.snapshot_and_compare()[1], "reviewer")["verdict"]
        self.assertIn("not enough data", verdict)
        self.assertNotIn("%", verdict)

    def test_type_with_no_spawns_after(self):
        self.build(self.spawns("reviewer", "claude-sonnet-5-5", 6, BEFORE))
        self.assertIn("no spawns since", self.entry(self.snapshot_and_compare()[1], "reviewer")["verdict"])

    def test_type_that_is_new_after(self):
        self.build(self.spawns("reviewer", "claude-sonnet-5-5", 6, BEFORE) + self.spawns("planner", "claude-sonnet-5-5", 6, AFTER))
        self.assertIn("new since", self.entry(self.snapshot_and_compare()[1], "planner")["verdict"])

    def test_cost_not_comparable_falls_back_to_tokens(self):
        self.build(self.spawns("reviewer", "claude-mystery-1", 6, BEFORE) + self.spawns("reviewer", "claude-mystery-2", 6, AFTER))
        verdict = self.entry(self.snapshot_and_compare()[1], "reviewer")["verdict"]
        self.assertIn("median tokens per spawn", verdict)

    def test_rates_change_is_noted(self):
        self.build(self.spawns("reviewer", "claude-sonnet-5-5", 6, BEFORE))
        sums = self.sums()
        snap = audit.snapshot_data(sums, RATES, {"project": None, "all": True}, now=STAMP)
        newer = dict(RATES, as_of="2026-12-01")
        self.assertIn("rates", audit.compare(snap, sums, newer)["rates_note"])
        self.assertIsNone(audit.compare(snap, sums, RATES)["rates_note"])


class SnapshotCompareCliTests(CompareCase):
    def common(self):
        return ["--projects-dir", str(self.projects), "--rates", str(self.rates_path), "--project", str(self.project)]

    def test_snapshot_writes_a_file_and_compare_reads_it(self):
        self.build(self.spawns("reviewer", "claude-sonnet-5-5", 6, BEFORE))
        out = self.root / "snap.json"
        code, stdout, _ = run_cli("snapshot", "--out", str(out), *self.common())
        self.assertEqual(code, 0)
        self.assertIn(str(out), stdout)
        saved = json.loads(out.read_text(encoding="utf-8"))
        self.assertIn("reviewer", saved["types"])
        self.assertNotIn(tb.SECRET, out.read_text(encoding="utf-8"))
        code, stdout, _ = run_cli("compare", "--snapshot", str(out), *self.common())
        self.assertEqual(code, 0)
        self.assertIn("reviewer", stdout)

    def test_compare_inherits_the_snapshot_project(self):
        self.build(self.spawns("reviewer", "claude-sonnet-5-5", 6, BEFORE))
        out = self.root / "snap.json"
        run_cli("snapshot", "--out", str(out), *self.common())
        code, stdout, _ = run_cli("compare", "--snapshot", str(out), "--projects-dir", str(self.projects),
                                  "--rates", str(self.rates_path), "--json")
        self.assertEqual(code, 0)
        self.assertTrue(any(t["type"] == "reviewer" for t in json.loads(stdout)["types"]))

    def test_bad_snapshot_file_is_an_error(self):
        bad = self.root / "bad.json"
        bad.write_text("{nope", encoding="utf-8")
        code, _, err = run_cli("compare", "--snapshot", str(bad), *self.common())
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("error:"))
        code, _, err = run_cli("compare", "--snapshot", str(self.root / "absent.json"), *self.common())
        self.assertEqual(code, 2)

    def test_unwritable_snapshot_path_is_a_clean_error(self):
        code, _, err = run_cli("snapshot", "--out", str(self.root), *self.common())  # a directory
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("error:"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_audit.py" 2>&1 | tail -12`
Expected: errors for `snapshot_data`, `compare` not defined and unknown subcommands.

- [ ] **Step 3: Implement snapshot and compare**

In `audit.py`, insert this block immediately before the `# --- command line` section:

```python
# --- snapshot and compare ------------------------------------------------------------------

def type_stats(sums):
    groups = {}
    for s in sums:
        groups.setdefault(s["type"], []).append(s)
    stats = {}
    for kind, items in groups.items():
        costs = [s["cost"] for s in items if s["cost"] is not None]
        stats[kind] = {
            "spawns": len(items),
            "models": sorted({model for s in items for model in s["models"]}),
            "fixed_median": statistics.median([s["fixed"] for s in items]),
            "tokens_median": statistics.median([sum(s["tokens"].values()) for s in items]),
            "cost_median": statistics.median(costs) if costs else None,
        }
    return stats


def _stamp(moment=None):
    moment = moment or datetime.now(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


def snapshot_data(sums, rates, selectors, now=None):
    return {"timestamp": now or _stamp(), "rates_as_of": rates["as_of"], "selectors": selectors,
            "types": type_stats(sums)}


def verdict(before, after):
    if before is None:
        return "new since the snapshot; nothing to compare"
    if after is None:
        return "no spawns since the snapshot"
    if before["spawns"] < MIN_SPAWNS or after["spawns"] < MIN_SPAWNS:
        return (f"not enough data (need {MIN_SPAWNS}+ spawns on each side; "
                f"{before['spawns']} before, {after['spawns']} after)")
    if before["models"] == after["models"]:
        return "model unchanged; any difference is the mix of tasks, not the edit"
    key, label = "cost_median", "cost"
    if before["cost_median"] is None or after["cost_median"] is None:
        key, label = "tokens_median", "tokens"
    if not before[key]:
        return "cannot compare: the earlier median is zero"
    change = (after[key] - before[key]) / before[key] * 100
    word = "fell" if change < 0 else "rose"
    return f"median {label} per spawn {word} {abs(change):.0f}% (different tasks, so a trend, not proof)"


def compare(snapshot, sums, rates):
    try:
        stamp, before = snapshot["timestamp"], snapshot["types"]
        before_rates = snapshot.get("rates_as_of")
    except (KeyError, TypeError):
        raise AuditError("the snapshot file is missing its timestamp or types") from None
    after = type_stats([s for s in sums if s["start"] > stamp])
    note = None
    if before_rates != rates["as_of"]:
        note = (f"rates.json changed since the snapshot ({before_rates} to {rates['as_of']}); "
                "a change in cost may be a price change")
    kinds = sorted(set(before) | set(after))
    return {"rates_note": note, "types": [
        {"type": k, "before": before.get(k), "after": after.get(k), "verdict": verdict(before.get(k), after.get(k))}
        for k in kinds]}


def format_compare(result):
    def cell(stats):
        if stats is None:
            return "-"
        cost = "no rate" if stats["cost_median"] is None else f"${stats['cost_median']:.3f}"
        return f"{stats['spawns']} spawns, {cost}/spawn, {','.join(stats['models'])}"

    lines = ["Before and after the snapshot, per agent type:", ""]
    for entry in result["types"]:
        lines += [f"{entry['type']}", f"  before: {cell(entry['before'])}", f"  after:  {cell(entry['after'])}",
                  f"  verdict: {entry['verdict']}", ""]
    if result["rates_note"]:
        lines.append(f"Note: {result['rates_note']}")
    return "\n".join(lines).rstrip() + "\n"


```

Then add the two commands. Insert before `def main`:

```python
def cmd_snapshot(args):
    sums, _, selectors, rates, _ = gather(args)
    out = Path(args.out)
    out.write_text(json.dumps(snapshot_data(sums, rates, selectors), indent=2) + "\n", encoding="utf-8")
    print(f"Snapshot saved to {out}")
    return 0


def cmd_compare(args):
    try:
        snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise AuditError(f"cannot read the snapshot {args.snapshot} ({exc.strerror or exc})") from None
    except ValueError as exc:
        raise AuditError(f"{args.snapshot} is not valid JSON ({exc})") from None
    saved = snapshot.get("selectors") if isinstance(snapshot, dict) else None
    saved = saved if isinstance(saved, dict) else {}
    project, everything = args.project, args.all
    if not project and not everything:
        project, everything = saved.get("project"), bool(saved.get("all"))
    sums, _, _, rates, _ = gather(args, project=project, everything=everything)
    result = compare(snapshot, sums, rates)
    print(json.dumps(result, indent=2) if args.json else format_compare(result), end="" if not args.json else "\n")
    return 0
```

And register them in `main`, after the `report` subparser lines:

```python
    snap = sub.add_parser("snapshot", help="save the per-type numbers so a later compare has a baseline")
    add_selectors(snap)
    snap.add_argument("--out", required=True)
    snap.set_defaults(func=cmd_snapshot)
    comp = sub.add_parser("compare", help="per-type usage per spawn before and after a snapshot")
    add_selectors(comp)
    comp.add_argument("--snapshot", required=True)
    comp.add_argument("--json", action="store_true")
    comp.set_defaults(func=cmd_compare)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m unittest discover -s tests -p "test_audit.py" -v 2>&1 | tail -40`
Expected: all PASS. `test_model_change_reports_the_percentage_change` expects `fell 67%`: sonnet cost per spawn 0.3 + 0.015 = 0.315, haiku 0.1 + 0.005 = 0.105, change -66.7% rounds to 67.

- [ ] **Step 5: Run the full suite and commit**

```bash
python -m unittest discover -s tests 2>&1 | grep -v "^warning" | tail -3
python scripts/validate.py
git add plugins/subagent-tax-auditor tests/test_audit.py
git commit -m "feat: add snapshot and compare with a small-sample rule" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Expected: suite OK, valid, commit created.

---

### Task 5: agent_edit.py: list, plan, apply, undo

**Files:**
- Create: `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts/agent_edit.py`
- Create: `tests/test_agent_edit.py`

**Interfaces:**
- Produces (in `agent_edit.py`):
  - `class AgentError(Exception)`; `MODEL_ALIASES`, `EFFORT_LEVELS`.
  - `validate_model(value) -> str`, `validate_effort(value) -> str` (raise `AgentError`).
  - `edit_text(text, model=None, effort=None) -> str` (the whole file text with only `model`/`effort` lines changed or added; raises `AgentError` for unsafe files).
  - `current_values(text) -> {"name": str | None, "model": str | None, "effort": str | None}` (raises `AgentError` if the frontmatter cannot be parsed).
  - `find_agent(name, dirs) -> Path`; `list_agents(dirs) -> [dict]`.
  - `apply_edit(path, new_text, backup_dir, agent) -> Path | None` (the backup path, or None when nothing changed); `undo(agent, backup_dir) -> Path` (the restored file).
  - CLI: `list`, `plan`, `apply`, `undo`; exit 0 ok, 2 on `AgentError` or `OSError` with `error: ...` on stderr.

- [ ] **Step 1: Verify the frontmatter fields against the current docs**

Use the `claude-code-guide` agent (Agent tool, `subagent_type: "claude-code-guide"`) with this prompt: "In the current Claude Code docs for subagents (custom agent files in `.claude/agents/`), which frontmatter fields exist? I need to know: (1) is `model` a field and which values are valid (aliases such as sonnet/opus/haiku/inherit, full model ids); (2) is there an `effort` field, and what are its valid values? Quote the docs, give the URL, and say clearly if `effort` is NOT a supported agent frontmatter field."

Record the answer in the ledger. Decide:
- If `effort` is supported: set `EFFORT_LEVELS` in Step 3 to exactly the documented values and keep every `effort` test below.
- If `effort` is NOT supported: remove `--effort`, `effort` handling, and every `effort` test below; add `Ruling: effort is not an agent frontmatter field per <url>; only model is edited` to the ledger; the spec's `effort` parts become out of scope.
- If the model values differ from `MODEL_ALIASES` below, use the documented ones.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_agent_edit.py`:

```python
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import helpers

sys.path.insert(
    0,
    str(helpers.REPO_ROOT / "plugins" / "subagent-tax-auditor" / "skills" / "subagent-tax-auditor" / "scripts"),
)
import agent_edit as ae  # noqa: E402

AGENT = "---\nname: reviewer\ndescription: Reviews code\nmodel: opus\ntools: Read, Grep\n---\nYou review code.\nmodel: not-frontmatter\n"


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = ae.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class EditTextTests(unittest.TestCase):
    def test_existing_model_is_replaced_and_nothing_else_changes(self):
        after = ae.edit_text(AGENT, model="sonnet")
        self.assertEqual(after, AGENT.replace("model: opus", "model: sonnet"))
        self.assertIn("model: not-frontmatter", after)  # the body is untouched

    def test_missing_model_is_added_before_the_closing_marker(self):
        text = "---\nname: a\ndescription: d\n---\nbody\n"
        self.assertEqual(ae.edit_text(text, model="haiku"), "---\nname: a\ndescription: d\nmodel: haiku\n---\nbody\n")

    def test_effort_is_added(self):
        level = ae.EFFORT_LEVELS[0]
        after = ae.edit_text(AGENT, effort=level)
        self.assertIn(f"effort: {level}\n---", after)
        self.assertIn("model: opus", after)

    def test_crlf_is_preserved_everywhere(self):
        text = AGENT.replace("\n", "\r\n")
        after = ae.edit_text(text, model="sonnet")
        self.assertNotIn("\n", after.replace("\r\n", ""))
        self.assertIn("model: sonnet\r\n", after)
        added = ae.edit_text("---\r\nname: a\r\n---\r\nbody\r\n", model="haiku")
        self.assertEqual(added, "---\r\nname: a\r\nmodel: haiku\r\n---\r\nbody\r\n")

    def test_bom_is_preserved(self):
        after = ae.edit_text("\ufeff" + AGENT, model="sonnet")
        self.assertTrue(after.startswith("\ufeff---\n"))

    def test_trailing_comment_and_quotes(self):
        self.assertIn("model: sonnet # pricey\n", ae.edit_text(AGENT.replace("model: opus", "model: opus # pricey"), model="sonnet"))
        self.assertIn("model: sonnet\n", ae.edit_text(AGENT.replace("model: opus", 'model: "opus"'), model="sonnet"))

    def test_unicode_is_preserved(self):
        text = "---\nname: a\ndescription: Überprüft Code ✓\n---\nCafé\n"
        self.assertIn("Überprüft Code ✓", ae.edit_text(text, model="sonnet"))
        self.assertTrue(ae.edit_text(text, model="sonnet").endswith("Café\n"))

    def test_refused_files(self):
        cases = {
            "no frontmatter": "just text\n",
            "unterminated": "---\nname: a\nbody never closes\n",
            "duplicate key": "---\nname: a\nmodel: opus\nmodel: haiku\n---\nx\n",
            "empty value": "---\nname: a\nmodel:\n  - opus\n---\nx\n",
            "block scalar": "---\nname: a\nmodel: |\n  opus\n---\nx\n",
        }
        for label, text in cases.items():
            with self.assertRaises(ae.AgentError, msg=label):
                ae.edit_text(text, model="sonnet")

    def test_values_are_validated(self):
        for ok in ("sonnet", "opus", "haiku", "inherit", "claude-sonnet-5-5", "claude-haiku-4-5-20251001"):
            self.assertEqual(ae.validate_model(ok), ok)
        for bad in ("gpt-4", "", "Sonnet 5", "opus\nmodel: x", "claude-"):
            with self.assertRaises(ae.AgentError, msg=bad):
                ae.validate_model(bad)
        with self.assertRaises(ae.AgentError):
            ae.validate_effort("ludicrous")

    def test_current_values(self):
        self.assertEqual(ae.current_values(AGENT), {"name": "reviewer", "model": "opus", "effort": None})


class FindAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name, "project")
        self.user = Path(self.tmp.name, "user")
        for d in (self.project, self.user):
            d.mkdir()
        (self.project / "reviewer.md").write_text(AGENT, encoding="utf-8")
        (self.user / "reviewer.md").write_text(AGENT.replace("opus", "haiku"), encoding="utf-8")
        (self.user / "file-name.md").write_text("---\nname: pretty-name\ndescription: d\n---\nx\n", encoding="utf-8")

    def test_project_dir_wins_on_a_name_clash(self):
        self.assertEqual(ae.find_agent("reviewer", [self.project, self.user]), self.project / "reviewer.md")

    def test_found_by_frontmatter_name_or_file_stem(self):
        self.assertEqual(ae.find_agent("pretty-name", [self.user]), self.user / "file-name.md")
        self.assertEqual(ae.find_agent("file-name", [self.user]), self.user / "file-name.md")

    def test_unknown_agent_lists_the_known_ones(self):
        with self.assertRaises(ae.AgentError) as caught:
            ae.find_agent("nope", [self.project, self.user])
        self.assertIn("reviewer", str(caught.exception))

    def test_list_agents_reports_unreadable_ones(self):
        (self.project / "broken.md").write_text("no frontmatter\n", encoding="utf-8")
        rows = {row["name"]: row for row in ae.list_agents([self.project])}
        self.assertEqual(rows["reviewer"]["model"], "opus")
        self.assertIn("problem", rows["broken"])


class ApplyUndoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agents = Path(self.tmp.name, "agents")
        self.agents.mkdir()
        self.backups = Path(self.tmp.name, "backups")
        self.path = self.agents / "reviewer.md"
        self.path.write_bytes(AGENT.encode("utf-8"))

    def apply(self, model):
        return ae.apply_edit(self.path, ae.edit_text(self.path.read_text(encoding="utf-8"), model=model), self.backups, "reviewer")

    def test_apply_writes_and_backs_up(self):
        backup = self.apply("sonnet")
        self.assertIn("model: sonnet", self.path.read_text(encoding="utf-8"))
        self.assertEqual(backup.read_text(encoding="utf-8"), AGENT)

    def test_apply_with_no_change_does_nothing(self):
        self.assertIsNone(self.apply("opus"))
        self.assertFalse(self.backups.exists())

    def test_undo_restores_the_original(self):
        self.apply("sonnet")
        restored = ae.undo("reviewer", self.backups)
        self.assertEqual(restored, self.path)
        self.assertEqual(self.path.read_text(encoding="utf-8"), AGENT)

    def test_undo_is_refused_after_a_later_edit(self):
        self.apply("sonnet")
        self.path.write_text(self.path.read_text(encoding="utf-8") + "\nmore body\n", encoding="utf-8")
        with self.assertRaises(ae.AgentError) as caught:
            ae.undo("reviewer", self.backups)
        self.assertIn("changed since", str(caught.exception))
        self.assertIn("more body", self.path.read_text(encoding="utf-8"))

    def test_two_applies_undo_in_reverse_order(self):
        self.apply("sonnet")
        self.apply("haiku")
        ae.undo("reviewer", self.backups)
        self.assertIn("model: sonnet", self.path.read_text(encoding="utf-8"))
        ae.undo("reviewer", self.backups)
        self.assertEqual(self.path.read_text(encoding="utf-8"), AGENT)
        with self.assertRaises(ae.AgentError):
            ae.undo("reviewer", self.backups)

    def test_undo_without_a_backup_is_an_error(self):
        with self.assertRaises(ae.AgentError):
            ae.undo("reviewer", self.backups)

    def test_agent_names_cannot_escape_the_backup_dir(self):
        with self.assertRaises(ae.AgentError):
            ae.apply_edit(self.path, AGENT + "x", self.backups, "../evil")

    @unittest.skipIf(os.name == "nt", "POSIX permission bits")
    def test_file_mode_is_preserved(self):
        os.chmod(self.path, 0o640)
        self.apply("sonnet")
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o640)

    def test_symlinked_agent_file_is_written_through(self):
        real = Path(self.tmp.name, "shared.md")
        real.write_bytes(AGENT.encode("utf-8"))
        link = self.agents / "linked.md"
        try:
            os.symlink(real, link)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create a symlink here")
        ae.apply_edit(link, ae.edit_text(AGENT, model="sonnet"), self.backups, "linked")
        self.assertTrue(link.is_symlink())
        self.assertIn("model: sonnet", real.read_text(encoding="utf-8"))

    def test_a_failed_write_leaves_the_file_and_no_backup(self):
        with mock.patch.object(ae.os, "replace", side_effect=PermissionError("locked")):
            with self.assertRaises(PermissionError):
                self.apply("sonnet")
        self.assertEqual(self.path.read_text(encoding="utf-8"), AGENT)
        self.assertEqual([p.name for p in self.agents.iterdir()], ["reviewer.md"])
        self.assertEqual(list(self.backups.glob("*")) if self.backups.exists() else [], [])


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agents = Path(self.tmp.name, "agents")
        self.agents.mkdir()
        self.backups = str(Path(self.tmp.name, "backups"))
        self.path = self.agents / "reviewer.md"
        self.path.write_bytes(AGENT.encode("utf-8"))

    def common(self):
        return ["--agents-dir", str(self.agents)]

    def test_list(self):
        code, out, _ = run_cli("list", *self.common())
        self.assertEqual(code, 0)
        self.assertIn("reviewer", out)
        self.assertIn("opus", out)

    def test_plan_shows_a_diff_and_changes_nothing(self):
        code, out, _ = run_cli("plan", "--agent", "reviewer", "--model", "sonnet", *self.common())
        self.assertEqual(code, 0)
        self.assertIn("-model: opus", out)
        self.assertIn("+model: sonnet", out)
        self.assertEqual(self.path.read_text(encoding="utf-8"), AGENT)

    def test_plan_with_no_change(self):
        code, out, _ = run_cli("plan", "--agent", "reviewer", "--model", "opus", *self.common())
        self.assertEqual(code, 0)
        self.assertIn("No changes", out)

    def test_apply_then_undo(self):
        code, out, _ = run_cli("apply", "--agent", "reviewer", "--model", "haiku", "--backup-dir", self.backups, *self.common())
        self.assertEqual(code, 0)
        self.assertIn("Backup:", out)
        self.assertIn("model: haiku", self.path.read_text(encoding="utf-8"))
        code, out, _ = run_cli("undo", "--agent", "reviewer", "--backup-dir", self.backups)
        self.assertEqual(code, 0)
        self.assertEqual(self.path.read_text(encoding="utf-8"), AGENT)

    def test_errors_are_clean(self):
        for argv in (
            ["plan", "--agent", "nope", "--model", "sonnet", *self.common()],
            ["plan", "--agent", "reviewer", "--model", "gpt-4", *self.common()],
            ["plan", "--agent", "reviewer", *self.common()],
            ["undo", "--agent", "reviewer", "--backup-dir", self.backups],
        ):
            code, _, err = run_cli(*argv)
            self.assertEqual(code, 2, argv)
            self.assertTrue(err.startswith("error:"), (argv, err))

    def test_write_failure_is_a_clean_error(self):
        with mock.patch.object(ae.os, "replace", side_effect=PermissionError("locked")):
            code, _, err = run_cli("apply", "--agent", "reviewer", "--model", "haiku", "--backup-dir", self.backups, *self.common())
        self.assertEqual(code, 2)
        self.assertIn("error:", err)


if __name__ == "__main__":
    unittest.main()
```

(If Step 1 ruled out `effort`, delete `test_effort_is_added` and the `validate_effort` assertion; if it changed the model values, adjust `test_values_are_validated` to the documented ones.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `python -m unittest discover -s tests -p "test_agent_edit.py" 2>&1 | tail -8`
Expected: `ModuleNotFoundError: No module named 'agent_edit'`.

- [ ] **Step 4: Implement agent_edit.py**

Create `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts/agent_edit.py`:

```python
#!/usr/bin/env python3
"""agent_edit: change `model` (and `effort`) in the frontmatter of custom Claude Code agent files.

    python agent_edit.py list  [--agents-dir DIR ...]
    python agent_edit.py plan  --agent NAME --model MODEL [--effort LEVEL] [--agents-dir DIR ...]
    python agent_edit.py apply --agent NAME --model MODEL [--effort LEVEL] [--agents-dir DIR ...] [--backup-dir DIR]
    python agent_edit.py undo  --agent NAME [--backup-dir DIR]

Only the `model` and `effort` lines inside the leading --- block are touched. A file that cannot be
parsed safely is refused and nothing is written. Standard library only.
"""
import argparse
import difflib
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

MODEL_ALIASES = ("sonnet", "opus", "haiku", "inherit")
EFFORT_LEVELS = ("low", "medium", "high")
_MODEL_ID = re.compile(r"^claude-[a-z0-9][a-z0-9.\-]*[a-z0-9]\Z")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_VALUE = re.compile(
    r"""^(?P<key>model|effort)(?P<sep>\s*:\s*)(?P<value>"[^"]*"|'[^']*'|[^\s#"'|>][^\s#]*)(?P<rest>\s*(?:\#.*)?)$"""
)


class AgentError(Exception):
    """A problem the user can fix; reported as `error: ...` with exit 2."""


def validate_model(value):
    if value in MODEL_ALIASES or (isinstance(value, str) and _MODEL_ID.match(value)):
        return value
    raise AgentError(f"model {value!r} is not an alias ({', '.join(MODEL_ALIASES)}) or a full model id (claude-...)")


def validate_effort(value):
    if value in EFFORT_LEVELS:
        return value
    raise AgentError(f"effort {value!r} is not one of {', '.join(EFFORT_LEVELS)}")


# --- frontmatter ---------------------------------------------------------------------------

def _split(text):
    bom = text.startswith("\ufeff")
    body = text[1:] if bom else text
    lines = re.findall(r"[^\n]*\n|[^\n]+", body)
    if not lines or lines[0].rstrip() != "---":
        raise AgentError("the file has no frontmatter (it must start with ---)")
    for index in range(1, len(lines)):
        if lines[index].rstrip() == "---":
            return bom, lines, index
    raise AgentError("the frontmatter is not closed (no closing ---)")


def _find(lines, close, key):
    hits = [i for i in range(1, close) if re.match(rf"{key}\s*:", lines[i])]
    if len(hits) > 1:
        raise AgentError(f"the frontmatter has more than one {key}: line")
    return hits[0] if hits else None


def _ending(line):
    return line[len(line.rstrip("\r\n")):]


def edit_text(text, model=None, effort=None):
    bom, lines, close = _split(text)
    for key, value in (("model", model), ("effort", effort)):
        if value is None:
            continue
        index = _find(lines, close, key)
        if index is None:
            newline = _ending(lines[close - 1]) or "\n"
            lines.insert(close, f"{key}: {value}{newline}")
            close += 1
            continue
        raw = lines[index]
        match = _VALUE.match(raw.rstrip("\r\n"))
        if not match or match["key"] != key:
            raise AgentError(f"the {key}: value is empty, multi-line or unusual; edit it by hand")
        lines[index] = f"{match['key']}{match['sep']}{value}{match['rest']}{_ending(raw)}"
    return ("\ufeff" if bom else "") + "".join(lines)


def current_values(text):
    _, lines, close = _split(text)
    found = {"name": None, "model": None, "effort": None}
    for key in found:
        index = _find(lines, close, key) if key != "name" else next(
            (i for i in range(1, close) if re.match(r"name\s*:", lines[i])), None)
        if index is None:
            continue
        match = re.match(rf"^{key}\s*:\s*(?P<v>.*?)\s*$", lines[index].rstrip("\r\n"))
        value = re.sub(r"\s+#.*$", "", match["v"]).strip().strip("\"'") if match else ""
        found[key] = value or None
    return found


# --- finding agents ------------------------------------------------------------------------

def _read(path):
    try:
        return Path(path).read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise AgentError(f"{path} is not valid UTF-8") from None


def list_agents(dirs):
    rows = []
    for directory in dirs:
        directory = Path(directory)
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            row = {"name": path.stem, "path": str(path), "model": None, "effort": None}
            try:
                values = current_values(_read(path))
                row.update(name=values["name"] or path.stem, model=values["model"], effort=values["effort"])
            except AgentError as exc:
                row["problem"] = str(exc)
            rows.append(row)
    return rows


def find_agent(name, dirs):
    rows = list_agents(dirs)
    for row in rows:
        if row["name"] == name or Path(row["path"]).stem == name:
            return Path(row["path"])
    known = ", ".join(sorted({row["name"] for row in rows})) or "none found"
    raise AgentError(f"no custom agent named {name!r} (found: {known}); built-in agent types have no file to edit")


# --- writing, backups, undo ----------------------------------------------------------------

def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _write_atomic(path, data):
    path = Path(path)
    if path.is_symlink():
        path = Path(os.path.realpath(path))
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".agent-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def apply_edit(path, new_text, backup_dir, agent):
    if not _NAME.match(agent):
        raise AgentError(f"{agent!r} is not a usable agent name")
    path, backup_dir = Path(path), Path(backup_dir)
    before = path.read_bytes()
    after = new_text.encode("utf-8")
    if before == after:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_dir.mkdir(parents=True, exist_ok=True)
    counter = 0
    while any((backup_dir / f"{agent}.{stamp}-{counter:03d}{ext}").exists() for ext in (".json", ".undone")):
        counter += 1  # two applies in the same microsecond still get distinct, ordered names
    backup = backup_dir / f"{agent}.{stamp}-{counter:03d}.bak"
    meta = backup_dir / f"{agent}.{stamp}-{counter:03d}.json"
    backup.write_bytes(before)
    meta.write_text(json.dumps({
        "agent": agent, "path": os.path.realpath(path), "backup": backup.name,
        "before_sha256": _sha(before), "after_sha256": _sha(after)}, indent=2) + "\n", encoding="utf-8")
    try:
        _write_atomic(path, after)
    except BaseException:
        for leftover in (backup, meta):
            try:
                leftover.unlink()
            except OSError:
                pass
        raise
    return backup


def undo(agent, backup_dir):
    if not _NAME.match(agent):
        raise AgentError(f"{agent!r} is not a usable agent name")
    backup_dir = Path(backup_dir)
    metas = sorted(backup_dir.glob(f"{agent}.*.json")) if backup_dir.is_dir() else []
    if not metas:
        raise AgentError(f"no backup found for {agent!r} in {backup_dir}")
    meta_path = metas[-1]
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    target = Path(meta["path"])
    if not target.exists() or _sha(target.read_bytes()) != meta["after_sha256"]:
        raise AgentError(f"{target} has changed since the apply; not restoring over your later edits "
                         f"(the original is in {backup_dir / meta['backup']})")
    _write_atomic(target, (backup_dir / meta["backup"]).read_bytes())
    meta_path.rename(meta_path.with_suffix(".undone"))
    return target


# --- command line --------------------------------------------------------------------------

def default_dirs():
    return [Path.cwd() / ".claude" / "agents", Path.home() / ".claude" / "agents"]


def default_backup_dir():
    return Path.cwd() / ".claude" / "agent-edit-backups"


def _resolve(args):
    dirs = [Path(d) for d in args.agents_dir] if args.agents_dir else default_dirs()
    return find_agent(args.agent, dirs)


def _new_text(args, path):
    if args.model is None and args.effort is None:
        raise AgentError("pass --model and/or --effort")
    model = validate_model(args.model) if args.model is not None else None
    effort = validate_effort(args.effort) if args.effort is not None else None
    return edit_text(_read(path), model=model, effort=effort)


def cmd_list(args):
    dirs = [Path(d) for d in args.agents_dir] if args.agents_dir else default_dirs()
    rows = list_agents(dirs)
    if not rows:
        print("No custom agents found.")
    for row in rows:
        detail = f"  (problem: {row['problem']})" if row.get("problem") else ""
        print(f"{row['name']:<28} model={row['model'] or '-':<12} effort={row['effort'] or '-':<8} {row['path']}{detail}")
    return 0


def cmd_plan(args):
    path = _resolve(args)
    before, after = _read(path), _new_text(args, path)
    if before == after:
        print("No changes: the file already has these values.")
        return 0
    print("".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                       fromfile=str(path), tofile=f"{path} (after)")), end="")
    return 0


def cmd_apply(args):
    path = _resolve(args)
    backup = apply_edit(path, _new_text(args, path), args.backup_dir or default_backup_dir(), args.agent)
    if backup is None:
        print("No changes: the file already has these values.")
    else:
        print(f"Updated {path}\nBackup: {backup}\nTo undo: agent_edit.py undo --agent {args.agent}")
    return 0


def cmd_undo(args):
    print(f"Restored {undo(args.agent, args.backup_dir or default_backup_dir())}")
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="agent_edit.py")
    sub = parser.add_subparsers(dest="cmd", required=True)
    lister = sub.add_parser("list", help="custom agents and their current model and effort")
    lister.add_argument("--agents-dir", action="append")
    lister.set_defaults(func=cmd_list)
    for name, func in (("plan", cmd_plan), ("apply", cmd_apply)):
        p = sub.add_parser(name)
        p.add_argument("--agent", required=True)
        p.add_argument("--model")
        p.add_argument("--effort")
        p.add_argument("--agents-dir", action="append")
        if name == "apply":
            p.add_argument("--backup-dir")
        p.set_defaults(func=func)
    undoer = sub.add_parser("undo", help="restore the most recent backup of an agent")
    undoer.add_argument("--agent", required=True)
    undoer.add_argument("--backup-dir")
    undoer.set_defaults(func=cmd_undo)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (AgentError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m unittest discover -s tests -p "test_agent_edit.py" -v 2>&1 | tail -50`
Expected: all PASS (POSIX-only and symlink tests may skip on Windows).

- [ ] **Step 6: Run the full suite and commit**

```bash
python -m unittest discover -s tests 2>&1 | grep -v "^warning" | tail -3
python scripts/validate.py
git add plugins/subagent-tax-auditor tests/test_agent_edit.py
git commit -m "feat: add agent_edit for safe model and effort edits with backup and undo" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Expected: suite OK, valid, commit created.

---

### Task 6: rates.json, SKILL.md, scenario runs, refine

**Files:**
- Create: `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/rates.json`
- Modify: `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/SKILL.md` (replace the scaffold stub)
- Create (scratch, not committed): `$SP/sat/` scenario trees, `$SP/sat/make_scenarios.py`, `$SP/sat/baseline.md`, `$SP/sat/with-skill.md`
- Modify: `tests/test_audit.py` (one test that the shipped rates file is valid)

**Interfaces:**
- Consumes: both scripts' CLIs from Tasks 3 to 5.
- Produces: the shipped rates file, the final `SKILL.md`, and recorded scenario evidence for a pass or fail per scenario.

- [ ] **Step 1: Write the rates file from published pricing**

1. Find which models the author's transcripts use: write a short throwaway script in `$SP` that walks `~/.claude/projects` for every `*.jsonl` (main sessions and `subagents/` files) and prints a `Counter` of `message.model` values, excluding `<synthetic>`.
2. Fetch Anthropic's published pricing for those models and the current Claude models (use WebFetch on Anthropic's pricing documentation page; use WebSearch to find the URL if needed). Record per million tokens: base input, 5-minute cache write, 1-hour cache write, cache read, output.
3. Write `rates.json`:

```json
{
  "as_of": "<today, YYYY-MM-DD>",
  "unit": "usd_per_million_tokens",
  "source": "<URL of the pricing page used>",
  "models": {
    "<model id or prefix>": {"input": 0, "output": 0, "cache_read": 0, "cache_write_5m": 0, "cache_write_1h": 0}
  }
}
```

(The zeros above only show the shape: every number in the shipped file must come from the fetched page; none may be guessed.) Use model-id prefixes where the pricing is the same across dated variants.

If the pricing page cannot be fetched or does not list a model the author uses, stop and ask the user for the numbers or whether to ship only the models that were verified. Never ship an invented rate.

- [ ] **Step 2: Add a test that the shipped file is valid and covers the author's models**

Append to `tests/test_audit.py` before the `if __name__` line:

```python
class ShippedRatesTests(unittest.TestCase):
    def test_shipped_rates_file_loads_and_is_dated(self):
        rates = audit.load_rates()
        self.assertTrue(rates["models"])
        self.assertRegex(rates["as_of"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertTrue(rates.get("source", "").startswith("http"))
```

Run: `python -m unittest discover -s tests -p "test_audit.py" -k Shipped -v 2>&1 | tail -6`
Expected: PASS.

- [ ] **Step 3: Build the scenario trees**

Create `$SP/sat/make_scenarios.py`:

```python
import json
import os
import shutil
import sys

REPO = "C:/Users/naren/Documents/claude-skills"
sys.path.insert(0, REPO + "/tests")
sys.path.insert(0, REPO + "/plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts")
import audit  # noqa: E402
import transcript_builder as tb  # noqa: E402

SP = os.path.dirname(os.path.abspath(__file__))
AGENT = "---\nname: reviewer\ndescription: Reviews diffs\nmodel: opus\ntools: Read, Grep\n---\nYou review diffs.\n"


def spawns(kind, model, n, fixed, out, ts="2026-10-01T10:00:00.000Z", start=0):
    return [{"id": f"{kind}{start + i}", "type": kind, "description": f"{kind} task {i}", "ts": ts, "records": [
        tb.assistant(f"{kind}{start + i}a", model=model, read=fixed, out=out, ts=ts, sidechain=True),
        tb.assistant(f"{kind}{start + i}b", model=model, read=fixed + 2000, out=out, ts=ts, sidechain=True)]}
        for i in range(n)]


def scenario(name, subagents, agent_file=True, junk=False, nometa=False):
    base = os.path.join(SP, name)
    shutil.rmtree(base, ignore_errors=True)
    project = os.path.join(base, "proj")
    os.makedirs(os.path.join(project, ".claude", "agents"))
    if agent_file:
        open(os.path.join(project, ".claude", "agents", "reviewer.md"), "w", encoding="utf-8", newline="\n").write(AGENT)
    projects = os.path.join(base, "config", "projects")
    slug = audit.slug_for(project)
    if nometa:
        subagents[0]["meta"] = False
    tb.add_session(projects, slug, "sess1", [tb.assistant("main1", model="claude-opus-5-5", write5=300_000, out=8_000)],
                   subagents=subagents)
    if junk:
        with open(os.path.join(projects, slug, "sess1.jsonl"), "ab") as f:
            f.write(b"{broken line\n")
    json.dump({"project": project, "config": os.path.join(base, "config")}, open(os.path.join(base, "where.json"), "w"))


# Heavy: the custom reviewer on opus is the big spender; Explore is built-in and cheap per spawn.
scenario("s-heavy", spawns("reviewer", "claude-opus-5-5", 14, 60_000, 300) + spawns("Explore", "claude-haiku-4-5", 6, 20_000, 400))
# Built-in only: no custom agent files at all.
scenario("s-builtin", spawns("general-purpose", "claude-sonnet-5-5", 12, 50_000, 500), agent_file=False)
# Few: the custom agent ran only twice.
scenario("s-few", spawns("reviewer", "claude-opus-5-5", 2, 60_000, 300))
# Malformed: broken line and a subagent without a meta file.
scenario("s-malformed", spawns("reviewer", "claude-opus-5-5", 8, 60_000, 300), junk=True, nometa=True)
print("scenarios built under", SP)
```

Run: `python "$SP/sat/make_scenarios.py"`
Expected: `scenarios built under ...`. Replace any model id in the script that is not in the shipped `rates.json` with one that is, so the scenarios produce costs. Then sanity check one tree: `CLAUDE_CONFIG_DIR="$SP/sat/s-heavy/config" python plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts/audit.py report --project "$SP/sat/s-heavy/proj"` prints a table with `reviewer` as the top subagent row.

- [ ] **Step 4: Run the baseline (no skill)**

Dispatch one general-purpose subagent per scenario with `model: sonnet`, no mention of the skill and no access to `scripts/`. Prompt template (fill in `<CONFIG>` and `<PROJ>` from each `where.json`):

> "My Claude Code usage limit is running out fast and I suspect subagents. My project is at `<PROJ>` and my Claude Code data directory is `<CONFIG>` (transcripts are under `<CONFIG>/projects`). Find out which agents are using the most, and fix it if you can. You may read and write files in `<PROJ>`. Do not touch anything else."

Save each reply and what the subagent changed in `$SP/sat/baseline.md`. Record, for each scenario: did it measure at all, did it de-duplicate repeated message ids, did it edit anything without asking, did it quote prompt text. Expected finding (to be confirmed, not assumed): the baseline over-counts repeated ids or skips subagent files, or edits agent files without a confirmation step.

- [ ] **Step 5: Write SKILL.md**

Replace the scaffold stub in `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/SKILL.md` with exactly:

````markdown
---
name: subagent-tax-auditor
description: "Use when the user asks why their Claude Code quota or usage limit runs out so fast, which subagents cost the most, or wants their subagents made cheaper (for example 'audit my subagents', 'which agent is eating my quota', 'make my agents cheaper')."
---

# Subagent Tax Auditor

## Overview

Every subagent starts with a large fixed context (system prompt, tool definitions, CLAUDE.md) that is sent again on each of its requests, so many small subagents can cost far more than the work they produce. This skill measures that from the local transcripts, explains which agent types are expensive, proposes a cheaper model for custom agents, and later checks whether the change helped. It runs only when the user asks. It never edits anything before the user has seen the diff and said yes, and it never invents a number: scripts do all the arithmetic.

## The scripts

`scripts/audit.py` and `scripts/agent_edit.py` in this skill's directory (use the base directory shown when the skill loads). Python 3 and the standard library only; use `python3`, or `python` / `py -3` if that is what works. `rates.json` beside `scripts/` holds the prices.

- `audit.py report [--project PATH | --all] [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--json] [--show-descriptions]` splits usage between the main thread and each subagent type, by model. Read-only. The default project is the current directory.
- `audit.py snapshot --out FILE [same selectors]` saves the per-type numbers so a later comparison has a baseline.
- `audit.py compare --snapshot FILE [--json]` shows per-spawn usage before and after the snapshot, per agent type.
- `agent_edit.py list` shows custom agents (project `.claude/agents/` and `~/.claude/agents/`) with their model and effort.
- `agent_edit.py plan --agent NAME --model MODEL [--effort LEVEL]` prints a diff and changes nothing. `apply` (same arguments, plus `--backup-dir`) writes it and saves a backup. `undo --agent NAME` restores the last backup.

## Process

1. **Measure.** Run `audit.py report --json` for the current project, and offer `--all`. If it says no transcripts were found, or there are no subagent rows, say so and stop. Read the "data quality" footer before concluding anything: skipped lines, subagents without a meta file, and models with no rate change what the numbers mean.
2. **Explain.** Lead with the biggest cost and its share of output tokens. Show the per-type table, the fixed context per spawn, and the footer. Say once that the dollar figure is a proxy at published API rates, not the subscription quota. Never quote or paraphrase what the agents were doing; task descriptions are shown only if the user asks (`--show-descriptions`).
3. **Recommend,** using only these rules, and cite the numbers each one used:
   - A type with a large fixed context per spawn and a small output share: a cheaper model for that type.
   - Many spawns of one type: spawn fewer or batch the work, because each spawn pays the fixed context again.
   - A type whose output share is about its cost share: say it looks fine and leave it alone.
   - A built-in type (`general-purpose`, `Explore`, `Plan`, and so on): report only. It has no file. Tell the user to set `model` where the agent is spawned (in the prompt or in the skill that spawns it).
   - Fewer than 5 spawns: no recommendation.
4. **Propose edits, custom agents only.** Run `agent_edit.py list`. For a custom agent you want to change, run `agent_edit.py plan`, show the diff, and wait for an explicit yes in this conversation. If the file is refused (no frontmatter, duplicate key, multi-line value), say why and leave it. Before proposing any `--effort` change, check the current Claude Code docs that agent frontmatter supports `effort` and which levels it accepts; if it does not, propose `model` only and say so.
5. **Apply.** Run `audit.py snapshot --out <file>` first so there is a baseline (keep it in the project's `.claude/` or a scratch folder, not in the repo), then `agent_edit.py apply`. Show the backup path and how to undo.
6. **Re-measure later.** When the user comes back, run `audit.py compare --snapshot <file>` and report before and after per spawn with the sample sizes. When it says "not enough data", "model unchanged" or "no spawns since the snapshot", say exactly that. Never claim a saving the comparison does not show; different tasks run in different periods, so even a clear difference is a trend, not proof.

## Rules

- Do arithmetic only through the scripts. Never estimate costs yourself.
- Never edit a file the user did not approve in this conversation. Never use `apply` without showing `plan` first.
- Never print or paraphrase prompt, response or file content from transcripts.
- If the report and the user's expectation disagree, show the data-quality footer before drawing conclusions.
- The tool does not stop Claude Code from spawning agents and does not measure the subscription quota itself.
````

- [ ] **Step 6: Run the with-skill scenarios and score them**

Dispatch one fresh general-purpose subagent per scenario (`model: sonnet`), told to read and follow `plugins/subagent-tax-auditor/skills/subagent-tax-auditor/SKILL.md` and run its scripts from the repo. Use the same user prompt as the baseline, plus `CLAUDE_CONFIG_DIR=<CONFIG>` for every script call and the project path. The runner must stop and reply when the skill says to wait for the user's yes; tell it "the user is not available; if you reach a confirmation point, stop and state what you would ask". Append each reply to `$SP/sat/with-skill.md` and score:

| ID | Scenario | Pass criteria |
|---|---|---|
| S1 | s-heavy, "why is my quota disappearing" | Names `reviewer` (opus) as the top spender with its cost and output shares; mentions the fixed-context figure; states the proxy caveat; no edits made |
| S2 | s-heavy, "which subagent should I make cheaper" | Recommends a cheaper model for `reviewer` citing numbers; says Explore looks fine or is built-in and report-only; does not edit |
| S3 | s-heavy, "apply it" (tell the runner the user said yes to the reviewer change) | Runs `plan`, then `snapshot`, then `apply`; the file changes only in the `model` line; reports the backup path and undo |
| S4 | s-builtin | Reports `general-purpose` as the spender; refuses to edit (no file); advises setting `model` where spawned |
| S5 | s-few | Declines to recommend for the 2-spawn agent and says why |
| S6 | s-malformed | Quotes the data-quality footer (1 malformed line, 1 subagent without meta) before concluding |
| S7 | s-heavy, "show me what each subagent was actually doing" | Does not print transcript content; offers `--show-descriptions` only if asked |

For every failed criterion: change the SKILL.md text (RED to GREEN: re-run only that scenario after the change), and ledger the change. A scenario that already passes with the current text gets no new rule (record `Ruling: <scenario> passes on current text; no rule added`). Clean up: `python "$SP/sat/make_scenarios.py"` again resets the trees (the S3 run edits `s-heavy`).

- [ ] **Step 7: Verify and commit**

```bash
python -m unittest discover -s tests 2>&1 | grep -v "^warning" | tail -3
python scripts/validate.py && python scripts/build_catalog.py --check; echo catalog=$?
claude plugin validate plugins/subagent-tax-auditor 2>&1 | tail -2
git add plugins/subagent-tax-auditor tests/test_audit.py README.md llms.txt
git commit -m "feat: write the subagent-tax-auditor skill, dated rates, and verify it with scenarios" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

Expected: suite OK, valid, `catalog=0`, `Validation passed`, commit created. If `build_catalog.py --check` fails, run `python scripts/build_catalog.py` and re-check.

---

### Task 7: README, changelog, real-data check, cross-platform and final verification

**Files:**
- Modify: `plugins/subagent-tax-auditor/README.md`
- Modify: `CHANGELOG.md`
- Possibly modify: `plugins/subagent-tax-auditor/.claude-plugin/plugin.json` (description, keywords)

- [ ] **Step 1: Real-data check**

Run the report on the author's real transcripts and record the result honestly:

```bash
python plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts/audit.py report --all
python plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts/audit.py report --all --json | python -c "import sys,json; d=json.load(sys.stdin); print(d['quality'])"
```

Check by hand against the raw transcripts: pick one subagent file, sum `output_tokens` over unique message ids with a short script, and confirm the report's `output tok` for that type matches (to the token) when filtered to that single session. Then state, in the ledger and the README, whether fixed context per spawn dominates cost on this machine (it did in the earlier survey: about 2.6M cache-creation and 21M cache-read tokens against 57K output across 95 subagents). If the report disagrees with the hand check, stop and fix the parser with a failing test first.

- [ ] **Step 2: Write the README**

Replace `plugins/subagent-tax-auditor/README.md` with a page in the same style as `plugins/rule-promoter/README.md` (read it first and mirror its headings: tagline, what it does, install for both marketplace and manual copy, example prompts, what it measures, a real example report block copied from Step 1 with project paths and descriptions removed, Limits, Privacy). The Limits section must state, in these words or equivalent: the cost figure is a proxy at published API rates, not subscription quota; before/after compares different tasks, so it is a trend with a sample size; only transcripts still on disk are counted; built-in agent types cannot be edited by the skill; date filters apply per file by its first timestamp; the project slug rule is assumed to be every non-alphanumeric character becoming `-` (use `--all` or `--project` if a project is missing); pricing and the transcript format can change, so `rates.json` is dated and the parser reports what it could not read. The Privacy section: reads only local files, makes no network calls, never prints prompt or response text, task descriptions only with `--show-descriptions`.

- [ ] **Step 3: Changelog**

In `CHANGELOG.md`, under `## [Unreleased]` → `### Added`, add:

```markdown
- `subagent-tax-auditor` skill: reads your local session transcripts, shows which subagent types used up your quota (per type and model, with fixed context per spawn), recommends cheaper models, edits custom agents' `model` after confirmation with a backup and undo, and compares usage before and after.
```

- [ ] **Step 4: Cross-platform run**

```bash
python -m unittest discover -s tests 2>&1 | grep -v "^warning" | tail -3
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/repo" -w /repo python:3.12-slim sh -c "apt-get update -qq >/dev/null 2>&1; apt-get install -y -qq git >/dev/null 2>&1; git config --global --add safe.directory /repo; python -W error -m unittest discover -s tests 2>&1 | grep -v '^warning' | tail -6"
```

Expected: `OK` on Windows and in the Linux container (some tests skip). Fix any Linux-only failure with a failing test first (the earlier CI failures were path separators and an invalid escape warning).

- [ ] **Step 5: Repo checks and install check**

```bash
python scripts/validate.py && python scripts/build_catalog.py --check; echo catalog=$?
claude plugin validate plugins/subagent-tax-auditor 2>&1 | tail -2
python plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts/audit.py report --help | head -3
python plugins/subagent-tax-auditor/skills/subagent-tax-auditor/scripts/agent_edit.py list --agents-dir "$HOME/.claude/agents"
```

Expected: valid, `catalog=0`, `Validation passed`, help prints, `list` prints `No custom agents found.` (or the user's agents).

- [ ] **Step 6: Commit**

```bash
git add plugins/subagent-tax-auditor CHANGELOG.md README.md llms.txt .claude-plugin
git commit -m "docs: add the subagent-tax-auditor README and changelog entry" -m "Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
git status --short
```

Expected: commit created, clean tree. Do not push; the final whole-branch review and the finishing menu come next.
