"""Offline timing regressions; no deck creation, media, or PowerPoint required."""

import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import plan_timing as timing


class TimingTests(unittest.TestCase):
    def test_feedback_interval_and_initial_deficit(self):
        result = timing.plan_timing(720, 120, current_characters=2273)
        interval = result["target_character_interval"]
        self.assertEqual((interval["min"], interval["max"]), (7000, 7130))
        self.assertTrue(interval["feasible"])
        self.assertEqual(interval["width_characters"], 130)
        self.assertEqual(interval["integer_target_count"], 131)
        self.assertEqual(result["current_characters"]["status"], "below_target")
        self.assertEqual(result["current_characters"]["deficit_to_minimum_characters"], 4727)

    def test_feedback_later_count_separates_body_and_session(self):
        result = timing.plan_timing(720, 120, current_characters=7026)
        current = result["current_characters"]
        self.assertEqual(current["status"], "within_target")
        self.assertEqual(current["headroom_to_maximum_characters"], 104)
        ranges = current["estimated_breakdown"]
        self.assertEqual(ranges["speech_minutes"], {"min": 28.104, "max": 30.5478})
        self.assertEqual(ranges["body_minutes"], {"min": 40.104, "max": 42.5478})
        self.assertEqual(ranges["session_minutes"], {"min": 42.104, "max": 44.5478})
        self.assertIsNone(result["measurement_status"]["actual_session_seconds"])

    def test_verified_video_reserve_table(self):
        cases = [
            (8, 1, 8000, 8280, True), (8, 2, 8000, 8050, True), (8, 3, 8000, 7820, False),
            (12, 1, 7000, 7360, True), (12, 2, 7000, 7130, True), (12, 3, 7000, 6900, False),
            (16, 1, 6000, 6440, True), (16, 2, 6000, 6210, True), (16, 3, 6000, 5980, False),
        ]
        for video, reserve, lower, upper, feasible in cases:
            with self.subTest(video=video, reserve=reserve):
                result = timing.plan_timing(video * 60, reserve * 60)
                interval = result["target_character_interval"]
                self.assertEqual((interval["min"], interval["max"], interval["feasible"]),
                                 (lower, upper, feasible))
                if feasible:
                    for planned in result["planned_breakdowns"].values():
                        self.assertTrue(planned["satisfies_body_minimum_at_fastest_rate"])
                        self.assertTrue(planned["satisfies_session_ceiling_at_slowest_rate"])
                else:
                    self.assertIsNone(result["planned_breakdowns"])
                    self.assertEqual(interval["gap_characters"], lower - upper)
                    self.assertEqual(interval["integer_target_count"], 0)

    def test_changed_rate_and_requirements(self):
        interval = timing.plan_timing(720, 120, rate_min=240, rate_max=250)["target_character_interval"]
        self.assertEqual((interval["min"], interval["max"]), (7000, 7440))
        result = timing.plan_timing(720, 120, rate_min=200, rate_max=280)
        self.assertFalse(result["target_character_interval"]["feasible"])
        interval = timing.plan_timing(720, 120, body_min_minutes=35,
                                       session_max_minutes=40)["target_character_interval"]
        self.assertEqual((interval["min"], interval["max"]), (5750, 5980))

    def test_empty_and_zero_count_are_distinct(self):
        unknown = timing.plan_timing(720, 120)["current_characters"]
        self.assertEqual(unknown["status"], "unknown")
        self.assertIsNone(unknown["count"])
        self.assertIsNone(unknown["estimated_breakdown"])
        zero = timing.plan_timing(720, 120, current_characters=0)["current_characters"]
        self.assertEqual(zero["status"], "below_target")
        self.assertEqual(zero["count"], 0)

    def test_surplus_and_infeasible_current_status(self):
        current = timing.plan_timing(720, 120, current_characters=7200)["current_characters"]
        self.assertEqual(current["status"], "above_target")
        self.assertEqual(current["surplus_above_maximum_characters"], 70)
        self.assertEqual(current["headroom_to_maximum_characters"], -70)
        current = timing.plan_timing(720, 180, current_characters=6950)["current_characters"]
        self.assertEqual(current["status"], "no_feasible_interval")
        self.assertEqual(current["deficit_to_minimum_characters"], 50)
        self.assertEqual(current["surplus_above_maximum_characters"], 50)

    def test_video_at_or_beyond_limits_is_not_arbitrarily_rejected(self):
        interval = timing.plan_timing(2400, 120)["target_character_interval"]
        self.assertEqual((interval["min"], interval["max"]), (0, 690))
        self.assertTrue(interval["feasible"])
        interval = timing.plan_timing(2700, 0)["target_character_interval"]
        self.assertEqual((interval["min"], interval["max"]), (0, 0))
        self.assertTrue(interval["feasible"])
        for video, reserve in ((2700, 1), (2701, 0), (0, 3000)):
            with self.subTest(video=video, reserve=reserve):
                result = timing.plan_timing(video, reserve)
                self.assertFalse(result["target_character_interval"]["feasible"])
                self.assertIn("video_plus_reserve_exceeds_session_ceiling",
                              result["infeasibility_reasons"])

    def test_conflicting_constraints_are_reported_as_infeasible(self):
        result = timing.plan_timing(0, 120, body_min_minutes=46, session_max_minutes=45)
        self.assertFalse(result["target_character_interval"]["feasible"])
        self.assertIn("body_minimum_plus_reserve_exceeds_session_ceiling",
                      result["infeasibility_reasons"])

    def test_rounding_does_not_add_spurious_character_at_decimal_boundary(self):
        interval = timing.plan_timing(0, 0, rate_min=25, rate_max=25,
                                       body_min_minutes=0.28, session_max_minutes=0.28)["target_character_interval"]
        self.assertEqual((interval["min"], interval["max"]), (7, 7))
        interval = timing.plan_timing(1, 1, rate_min=230, rate_max=250)["target_character_interval"]
        self.assertEqual((interval["min"], interval["max"]), (9996, 10342))

    def test_invalid_numbers(self):
        cases = [
            {"video_seconds": -1}, {"reserve_seconds": -1},
            {"rate_min": 0}, {"rate_max": -1}, {"rate_min": 260},
            {"body_min_minutes": 0}, {"session_max_minutes": -1},
            {"current_characters": -1}, {"current_characters": 1.5},
            {"video_seconds": True}, {"reserve_seconds": "not a number"},
        ]
        for key in ("video_seconds", "reserve_seconds", "rate_min", "rate_max",
                    "body_min_minutes", "session_max_minutes", "current_characters"):
            for value in (float("inf"), float("-inf"), float("nan")):
                cases.append({key: value})
        for overrides in cases:
            args = {"video_seconds": 720, "reserve_seconds": 120}
            args.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                timing.plan_timing(**args)

    def test_finite_inputs_cannot_emit_nonfinite_results(self):
        with self.assertRaisesRegex(ValueError, "finite numeric output"):
            timing.plan_timing(0, 0, rate_min=1e-308, rate_max=1e308,
                               current_characters=1e308)

    def test_main_with_stringio(self):
        output = io.StringIO()
        with mock.patch("sys.stdout", output):
            status = timing.main(["--video-seconds", "720", "--reserve-seconds", "120"])
        self.assertEqual(status, 0)
        self.assertTrue(json.loads(output.getvalue())["target_character_interval"]["feasible"])

    def test_cli_success_error_locale_and_no_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            scripts = Path(folder) / "技能🙂"
            scripts.mkdir()
            for name in ("plan_timing.py", "runtime_support.py"):
                shutil.copyfile(Path(timing.__file__).with_name(name), scripts / name)
            before = {p.name: p.read_bytes() for p in scripts.iterdir()}
            good = ["--video-seconds", "720", "--reserve-seconds", "120"]
            cases = [(good, 0), (good + ["--未知🙂"], 2),
                     (good + ["--rate-min", "不是数字🙂"], 2),
                     (good + ["--rate-max", "nan"], 2), ([], 2)]
            for encoding in ("ascii", "gbk"):
                for flags, status in cases:
                    with self.subTest(encoding=encoding, flags=flags):
                        env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP") if key in os.environ}
                        env.update(PYTHONIOENCODING=encoding, PYTHONUTF8="0")
                        proc = subprocess.run(
                            [sys.executable, "-B", "-X", "utf8=0", str(scripts / "plan_timing.py")] + flags,
                            env=env, capture_output=True, timeout=30)
                        self.assertEqual(proc.returncode, status, proc.stderr)
                        self.assertEqual(proc.stderr, b"")
                        output = json.loads(proc.stdout.decode("utf-8"))
                        self.assertTrue(output["read_only"])
                        if status:
                            self.assertIn("error", output)
            self.assertEqual(before, {p.name: p.read_bytes() for p in scripts.iterdir()})
            self.assertEqual(list(scripts.rglob("__pycache__")), [])


if __name__ == "__main__":
    unittest.main()
