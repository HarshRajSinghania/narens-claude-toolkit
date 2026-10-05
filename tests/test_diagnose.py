import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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


class TimestampCompatibilityTests(unittest.TestCase):
    def test_fractional_seconds_are_truncated_or_padded_to_microseconds(self):
        for fraction, microsecond in (("1", 100000), ("123", 123000), ("12345", 123450),
                                      ("3478805", 347880), ("9999999", 999999)):
            for suffix in ("Z", "z", "", "+00:00"):
                with self.subTest(fraction=fraction, suffix=suffix):
                    actual = diagnose.parse_time(f"2026-10-01T21:22:39.{fraction}{suffix}", "at")
                    self.assertEqual(actual, datetime(2026, 10, 1, 21, 22, 39, microsecond, timezone.utc))

    def test_compact_timezone_offsets_preserve_the_instant(self):
        for suffix, minutes in (("+0000", 0), ("+0530", 330), ("-0430", -270)):
            for fraction in ("", ".3478805"):
                with self.subTest(suffix=suffix, fraction=fraction):
                    actual = diagnose.parse_time(f"2026-10-01T21:22:39{fraction}{suffix}", "at")
                    expected = datetime(2026, 10, 1, 21, 22, 39,
                                        347880 if fraction else 0, timezone(timedelta(minutes=minutes)))
                    self.assertEqual(actual, expected)

    def test_windows_machine_events_can_be_classified(self):
        result = diagnose.classify(rec(
            started_at=None, ended_at=None,
            machine_events=[{"kind": "sleep", "at": "2026-10-03T21:22:39.3478805Z"}],
        ))
        self.assertEqual(result["verdict"], "slept-through")

    def test_normalization_does_not_accept_malformed_timestamps(self):
        for value in ("2026-13-01T21:22:39.1234567Z", "2026-10-01T21:22:39.123+2500",
                      "2026-10-01T99:22:39.1234567Z"):
            with self.subTest(value=value):
                with self.assertRaises(diagnose.DiagnoseError):
                    diagnose.parse_time(value, "at")


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

    def test_whitespace_error_text_is_not_a_failure(self):
        result = diagnose.classify(rec(error_text=" \t\n "))
        self.assertEqual(result["verdict"], "healthy")
        self.assertIsNone(result["evidence"]["error_text"])

    def test_error_text_is_trimmed_before_truncation(self):
        result = diagnose.classify(rec(error_text=" " * 250 + "exit code 1  "))
        self.assertEqual(result["verdict"], "failed-unknown")
        self.assertEqual(result["evidence"]["error_text"], "exit code 1")

    def test_permission_tool_must_be_string_or_null(self):
        for tool in (True, False, 0, 1, [], {}):
            with self.subTest(tool=tool):
                with self.assertRaisesRegex(diagnose.DiagnoseError, "permission_denied_tool"):
                    diagnose.classify(rec(permission_denied_tool=tool))

    def test_date_only_timestamps_are_refused_in_all_fields(self):
        for field in ("scheduled_for", "started_at", "ended_at"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(diagnose.DiagnoseError, field):
                    diagnose.classify(rec(**{field: "2026-10-04"}))
        with self.assertRaisesRegex(diagnose.DiagnoseError, "machine_events"):
            diagnose.classify(rec(machine_events=[{"kind": "sleep", "at": "2026-10-04"}]))

    def test_space_separated_timestamp_still_has_a_time_component(self):
        self.assertEqual(self.verdict(rec(started_at="2026-10-04 07:00:05+00:00")), "healthy")

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

    def test_status_vocabulary_decides_between_healthy_failed_and_unfinished(self):
        cases = {
            "completed": "healthy",
            " COMPLETED ": "healthy",
            "succeeded": "healthy",
            "timed_out": "failed-unknown",
            "Timed-Out": "failed-unknown",
            "errored": "failed-unknown",
            "cancelled": "unfinished-unknown",
            "stopped": "unfinished-unknown",
            "running": "unfinished-unknown",
            "something new": "unfinished-unknown",
        }
        for status, verdict in cases.items():
            with self.subTest(status):
                self.assertEqual(self.verdict(rec(status=status)), verdict)

    def test_no_status_is_healthy_only_when_the_run_has_an_end_time(self):
        self.assertEqual(self.verdict(rec(status=None)), "healthy")
        result = diagnose.classify(rec(status=None, ended_at=None))
        self.assertEqual(result["verdict"], "unfinished-unknown")
        self.assertIn("no sign it finished", result["why"])

    def test_a_run_still_waiting_on_approval_is_a_permission_halt(self):
        for status in ("waiting for approval", "permission-denied", "Permission_Required"):
            with self.subTest(status):
                self.assertEqual(
                    self.verdict(rec(status=status, ended_at=None)), "permission-halt"
                )

    def test_last_event_wording_is_matched_loosely(self):
        for event in ("permission_denied", "Waiting for permission to use Bash", "tool-denied"):
            with self.subTest(event):
                self.assertEqual(self.verdict(rec(last_event=event)), "permission-halt")

    def test_machine_event_kinds_are_normalized(self):
        for kind in ("Sleep", " SLEEP ", "hibernate", "Lid_Close"):
            with self.subTest(kind):
                events = [{"kind": kind, "at": "2026-10-03T22:10:00+00:00"}]
                self.assertEqual(
                    self.verdict(rec(started_at=None, machine_events=events)), "slept-through"
                )

    def test_wake_kind_is_case_insensitive_too(self):
        events = [
            {"kind": "sleep", "at": "2026-10-03T22:10:00+00:00"},
            {"kind": "Wake", "at": "2026-10-04T06:00:00+00:00"},
        ]
        self.assertEqual(
            self.verdict(rec(started_at=None, machine_events=events)), "never-ran-unknown"
        )

    def test_an_unrecognised_machine_event_kind_is_an_error_not_silently_dropped(self):
        events = [{"kind": "reboot", "at": "2026-10-03T22:10:00+00:00"}]
        with self.assertRaises(diagnose.DiagnoseError) as ctx:
            diagnose.classify(rec(machine_events=events))
        self.assertIn("sleep", str(ctx.exception))

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
        "unfinished_unknown": "unfinished-unknown",
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

    def test_invalid_record_fields_are_clean_cli_errors(self):
        for fields in ({"started_at": "2026-10-04"}, {"permission_denied_tool": True}):
            with self.subTest(fields=fields):
                code, out, err = run_main("--record", self.write(json.dumps(rec(**fields))), "--json")
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.startswith("error:"))
                self.assertEqual(len(err.splitlines()), 1)

    def test_byte_order_mark_is_ignored(self):
        path = self.write(json.dumps(rec()), encoding="utf-8-sig")
        code, out, _ = run_main("--record", path, "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["verdict"], "healthy")

    def test_utf16_file_from_windows_powershell_is_read(self):
        # PowerShell 5.1 `>` writes UTF-16LE with a byte order mark.
        for encoding in ("utf-16", "utf-16-be"):
            with self.subTest(encoding):
                text = json.dumps(rec())
                data = text.encode(encoding)
                if encoding == "utf-16-be":
                    data = b"\xfe\xff" + data
                tmp = tempfile.TemporaryDirectory()
                self.addCleanup(tmp.cleanup)
                path = Path(tmp.name) / "record.json"
                path.write_bytes(data)
                code, out, err = run_main("--record", str(path), "--json")
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(json.loads(out)["verdict"], "healthy")

    def test_undecodable_file_is_a_clean_error_not_a_traceback(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "bad.json"
        path.write_bytes(b"\x80\x81\x82")
        code, _, err = run_main("--record", str(path))
        self.assertEqual(code, 2)
        self.assertIn("not UTF-8 or UTF-16 text", err)
        self.assertNotIn("Traceback", err)

    def test_negative_threshold_is_refused(self):
        code, _, err = run_main("--record", str(RECORDS / "healthy.json"), "--late-minutes", "-1")
        self.assertEqual(code, 2)
        self.assertIn("must not be negative", err)

    def test_non_finite_late_minutes_is_a_clean_error(self):
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value):
                code, out, err = run_main(
                    "--record", str(RECORDS / "healthy.json"), f"--late-minutes={value}", "--json"
                )
                self.assertEqual((code, out), (2, ""))
                self.assertIn("finite", err)
                self.assertNotIn("Traceback", err)

    def test_late_minutes_option_changes_the_verdict(self):
        path = self.write(json.dumps(rec(started_at="2026-10-04T07:10:00+00:00")))
        code, out, _ = run_main("--record", path, "--late-minutes", "5", "--json")
        self.assertEqual((code, json.loads(out)["verdict"]), (0, "late-catchup"))


if __name__ == "__main__":
    unittest.main()
