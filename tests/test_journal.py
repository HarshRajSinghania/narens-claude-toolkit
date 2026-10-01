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
