"""Candidate-bound timing additions, with legacy field regression coverage."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

import audit_pptx as audit
from test_audit_pptx import fixture


class AuditTimingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "时长🙂.pptx"

    def rewrite(self, name, transform):
        with zipfile.ZipFile(self.path) as package:
            parts = {item: package.read(item) for item in package.namelist()}
        parts[name] = transform(parts[name])
        with zipfile.ZipFile(self.path, "w") as package:
            for item, data in parts.items():
                package.writestr(item, data)

    def test_new_budget_and_old_total_semantics(self):
        fixture(self.path)
        result = audit.audit_pptx(self.path, video_seconds=720, transition_seconds=120)
        self.assertEqual(result["schema_version"], 1)
        interval = result["timing_budget"]["target_character_interval"]
        self.assertEqual((interval["min"], interval["max"]), (7000, 7130))
        self.assertEqual(result["timing_budget"]["current_characters"]["deficit_to_minimum_characters"], 6993)
        estimates = result["timing_estimate"]
        self.assertEqual(estimates["narration_seconds"], {"min": 1.68, "max": 1.83})
        self.assertEqual(estimates["total_seconds"], {"min": 841.68, "max": 841.83})
        self.assertEqual(estimates["body_seconds"], {"min": 721.68, "max": 721.8261})
        self.assertEqual(estimates["session_seconds"], {"min": 841.68, "max": 841.8261})
        self.assertIn("NOT body", estimates["legacy_total_fields_mean"])

    def test_hidden_notes_remain_in_legacy_scope_and_are_disclosed(self):
        fixture(self.path, slide_names=("slide1.xml", "slide2.xml"))
        self.rewrite("ppt/slides/slide2.xml", lambda data: data.replace(b"<p:sld ", b'<p:sld show="0" ', 1))
        result = audit.audit_pptx(self.path)
        self.assertEqual(result["summary"]["total_notes_chinese_characters"], 14)
        basis = result["timing_budget"]["count_basis"]
        self.assertEqual(basis["hidden_slide_numbers"], [2])
        self.assertEqual(basis["hidden_slide_notes_han_characters"], 7)
        self.assertEqual(basis["actual_played_slide_sequence"], "unknown")
        self.assertIsNone(basis["actual_spoken_characters"])

    def test_missing_notes_remain_unknown_as_spoken_content(self):
        fixture(self.path, notes=False)
        result = audit.audit_pptx(self.path)
        budget = result["timing_budget"]
        self.assertEqual(budget["current_characters"]["count"], 0)
        self.assertEqual(budget["count_basis"]["slides_without_readable_notes"], [1])
        self.assertIsNone(budget["count_basis"]["actual_spoken_characters"])
        self.assertIsNone(budget["measurement_status"]["actual_session_seconds"])

    def test_fingerprint_binds_unchanged_bytes(self):
        fixture(self.path)
        data = self.path.read_bytes()
        result = audit.audit_pptx(self.path)
        self.assertEqual(result["input_fingerprint"], {
            "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)})
        self.assertEqual(self.path.read_bytes(), data)

    def test_fingerprint_scan_preserves_bounded_input_resources(self):
        fixture(self.path)
        with mock.patch.object(audit, "MAX_INPUT_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "input-byte limit"):
                audit.audit_pptx(self.path)

    def test_changed_candidate_rejected_instead_of_returning_old_measurements(self):
        fixture(self.path)
        original = audit._audit_open_pptx

        def mutate(*args, **kwargs):
            result = original(*args, **kwargs)
            with self.path.open("ab") as stream:
                stream.write(b"candidate changed")
            return result

        with mock.patch.object(audit, "_audit_open_pptx", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "Candidate changed during audit"):
                audit.audit_pptx(self.path)

    def test_replaced_candidate_path_rejected(self):
        fixture(self.path)
        original = audit._audit_open_pptx

        def replace(*args, **kwargs):
            result = original(*args, **kwargs)
            alternate = self.path.with_name("replacement.pptx")
            alternate.write_bytes(self.path.read_bytes())
            try:
                alternate.replace(self.path)
            except PermissionError:
                self.skipTest("Host prevents replacing an open file")
            return result

        with mock.patch.object(audit, "_audit_open_pptx", side_effect=replace):
            with self.assertRaisesRegex(ValueError, "Candidate changed during audit"):
                audit.audit_pptx(self.path)

    def test_new_cli_requirements_and_infeasible_is_report_not_crash(self):
        fixture(self.path)
        proc = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", audit.__file__, str(self.path),
             "--video-seconds", "720", "--transition-seconds", "180",
             "--body-min-minutes", "40", "--session-max-minutes", "45"],
            capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout.decode("utf-8"))
        self.assertFalse(result["timing_budget"]["target_character_interval"]["feasible"])
        self.assertIsNone(result["timing_budget"]["planned_breakdowns"])


if __name__ == "__main__":
    unittest.main()
