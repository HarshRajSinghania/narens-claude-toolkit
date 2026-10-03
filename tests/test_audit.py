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
