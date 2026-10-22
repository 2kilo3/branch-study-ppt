"""Offline synthetic runtime regressions; no user PPT or host application needed."""

import hashlib
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

import audit_pptx as audit
import preflight
from runtime_support import write_json_utf8
from test_audit_pptx import fixture

ROOT = Path(__file__).resolve().parent.parent


def tree_digest(root):
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }


class TextOnlyAscii:
    """A strict, text-only embedding stream without a .buffer attribute."""

    def __init__(self):
        self.data = ""

    def write(self, value):
        value.encode("ascii")  # Reject before writing, as TextIOWrapper does.
        self.data += value

    def flush(self):
        pass


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "支部学习🙂.pptx"

    def child(self, script, args=(), encoding="ascii", utf8="utf8", cwd=None):
        env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP") if key in os.environ}
        env.update(PYTHONIOENCODING=encoding, PYTHONUTF8="0")
        return subprocess.run(
            [sys.executable, "-B", "-X", utf8, str(script)] + list(args),
            env=env, cwd=cwd, capture_output=True, timeout=30, check=False,
        )

    def test_json_binary_buffer_overrides_text_encoding(self):
        for encoding in ("ascii", "gbk"):
            with self.subTest(encoding=encoding):
                raw = io.BytesIO()
                stream = io.TextIOWrapper(raw, encoding=encoding)
                write_json_utf8({"中文": "🙂"}, stream)
                self.assertEqual(json.loads(raw.getvalue().decode("utf-8")),
                                 {"中文": "🙂"})
                stream.detach()

    def test_json_stringio_preserves_unicode(self):
        stream = io.StringIO()
        write_json_utf8({"中文": "🙂"}, stream)
        self.assertIn("中文", stream.getvalue())
        self.assertEqual(json.loads(stream.getvalue()), {"中文": "🙂"})

    def test_json_text_only_restrictive_stream_uses_safe_escapes(self):
        stream = TextOnlyAscii()
        write_json_utf8({"中文": "🙂"}, stream)
        stream.data.encode("ascii")
        self.assertEqual(json.loads(stream.data), {"中文": "🙂"})

    def test_json_surrogate_filename_still_emits_valid_utf8(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="ascii")
        value = {"file": "non_utf8_\udcff.pptx"}
        write_json_utf8(value, stream)
        self.assertEqual(json.loads(raw.getvalue().decode("utf-8")), value)
        stream.detach()

    def test_success_bytes_with_chinese_emoji_and_hostile_io(self):
        fixture(self.path)
        for utf8 in ("utf8", "utf8=0"):
            for encoding in ("ascii", "gbk"):
                with self.subTest(utf8=utf8, encoding=encoding):
                    proc = self.child(audit.__file__, [str(self.path)], encoding, utf8)
                    self.assertEqual(proc.returncode, 0, proc.stderr)
                    self.assertEqual(proc.stderr, b"")
                    result = json.loads(proc.stdout.decode("utf-8"))
                    self.assertEqual(result["file"], str(self.path))
                    self.assertIn("幻灯片".encode("utf-8"), proc.stdout)
                    self.assertIn("🙂".encode("utf-8"), proc.stdout)

    def test_invalid_zip_error_bytes_with_hostile_io(self):
        self.path.write_bytes(b"not a ZIP")
        for utf8 in ("utf8", "utf8=0"):
            for encoding in ("ascii", "gbk"):
                with self.subTest(utf8=utf8, encoding=encoding):
                    proc = self.child(audit.__file__, [str(self.path)], encoding, utf8)
                    self.assertEqual(proc.returncode, 2, proc.stderr)
                    self.assertEqual(proc.stderr, b"")
                    result = json.loads(proc.stdout.decode("utf-8"))
                    self.assertEqual(result["file"], str(self.path))
                    self.assertIn("error", result)

    def test_missing_file_error_bytes_with_hostile_io(self):
        proc = self.child(audit.__file__, [str(self.path)], "ascii", "utf8=0")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        result = json.loads(proc.stdout.decode("utf-8"))
        self.assertEqual(result["file"], str(self.path))
        self.assertIn("error", result)

    def test_argument_errors_are_utf8_json(self):
        for args in ([str(self.path), "--未知🙂"], [],
                     [str(self.path), "--min-font", "不是数字🙂"]):
            with self.subTest(args=args):
                proc = self.child(audit.__file__, args, "gbk", "utf8=0")
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertEqual(proc.stderr, b"")
                self.assertIn("error", json.loads(proc.stdout.decode("utf-8")))

    def test_main_can_be_embedded_with_stringio(self):
        fixture(self.path)
        for args, status in (([str(self.path)], 0), ([], 2)):
            with self.subTest(args=args):
                stream = io.StringIO()
                with mock.patch("sys.stdout", stream):
                    self.assertEqual(audit.main(args), status)
                self.assertTrue(json.loads(stream.getvalue())["read_only"])

    def test_parent_text_decode_is_explicit_utf8(self):
        fixture(self.path)
        env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP") if key in os.environ}
        env["PYTHONIOENCODING"] = "gbk"
        proc = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", audit.__file__, str(self.path)],
            env=env, capture_output=True, text=True, encoding="utf-8",
            timeout=30, check=True,
        )
        self.assertEqual(json.loads(proc.stdout)["file"], str(self.path))

    def test_preflight_passes_with_hostile_io(self):
        for encoding in ("ascii", "gbk"):
            with self.subTest(encoding=encoding):
                proc = self.child(preflight.__file__, encoding=encoding, utf8="utf8=0")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                result = json.loads(proc.stdout.decode("utf-8"))
                self.assertTrue(result["ready_for_python_helpers"])
                self.assertTrue(result["read_only"])
                self.assertFalse(result["network_accessed"])
                self.assertEqual(result["interpreter"]["utf8_mode"], 0)
                self.assertEqual(result["utf8_pipe_contract"]["status"], "passed")

    @unittest.skipUnless(os.name == "posix", "POSIX C-locale regression")
    def test_preflight_probe_works_in_ascii_filesystem_locale(self):
        env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP") if key in os.environ}
        env.update(LC_ALL="C", PYTHONCOERCECLOCALE="0", PYTHONUTF8="0",
                   PYTHONIOENCODING="ascii")
        proc = subprocess.run(
            [sys.executable, "-B", "-X", "utf8=0", preflight.__file__],
            env=env, capture_output=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout.decode("utf-8"))
        self.assertEqual(result["interpreter"]["utf8_mode"], 0)
        self.assertEqual(result["utf8_pipe_contract"]["status"], "passed")

    def test_preflight_no_python_pptx_is_not_universal_blocker(self):
        with mock.patch.object(preflight.importlib.util, "find_spec", return_value=None):
            result = preflight.preflight()
        self.assertTrue(result["ready_for_python_helpers"])
        self.assertFalse(result["optional_discovery"]["python_pptx_spec_found"])
        self.assertTrue(result["optional_discovery"]["absence_is_not_a_workflow_blocker"])

    def test_preflight_missing_asset_reports_relative_path(self):
        root = Path(self.tmp.name) / "incomplete"
        root.mkdir()
        results = preflight.inspect_package(root)
        self.assertTrue(all(row["status"] == "failed" for row in results))
        self.assertIn("assets/template.pptx", [row["file"] for row in results])
        self.assertNotIn(str(root), json.dumps(results))

    def test_preflight_missing_writer_bootstrap_is_utf8_json(self):
        root = Path(self.tmp.name) / "broken_package"
        root.mkdir()
        script = root / "preflight.py"
        shutil.copyfile(preflight.__file__, script)
        (root / "runtime_support.py").write_text("different_name = None\n", encoding="utf-8")
        proc = self.child(script, encoding="utf-16", utf8="utf8=0")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(proc.stderr, b"")
        result = json.loads(proc.stdout.decode("utf-8"))
        self.assertEqual(result["error"], "Cannot load runtime_support")
        self.assertFalse(result["ready_for_python_helpers"])

    def test_preflight_failed_probe_is_reported(self):
        with mock.patch.object(preflight.subprocess, "run", side_effect=PermissionError):
            result = preflight.probe_utf8(ROOT / "scripts")
        self.assertEqual(result, {"status": "failed", "reason": "PermissionError"})

    def test_preflight_old_version_skips_unsupported_probe(self):
        # A version-branch unit test, not execution on a Python 3.6 runtime.
        with mock.patch.object(preflight.sys, "version_info", (3, 6, 15)):
            with mock.patch.object(preflight.subprocess, "run") as run:
                result = preflight.preflight()
        self.assertFalse(result["ready_for_python_helpers"])
        self.assertFalse(result["interpreter"]["minimum_met"])
        self.assertEqual(result["utf8_pipe_contract"]["status"], "not_run")
        run.assert_not_called()

    def test_b_flag_keeps_package_tree_unchanged(self):
        # Fresh copy with no preexisting caches, then actual import/CLI/probe.
        copied = Path(self.tmp.name) / "技能🙂"
        shutil.copytree(ROOT, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        fixture(self.path)
        before = tree_digest(copied)
        code = (
            "import audit_pptx, preflight; "
            "assert preflight.preflight()['ready_for_python_helpers']"
        )
        proc = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", "-c", code],
            cwd=str(copied / "scripts"), capture_output=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self.child(copied / "scripts/audit_pptx.py", [str(self.path)])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self.child(copied / "scripts/preflight.py")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(before, tree_digest(copied))
        self.assertEqual(list(copied.rglob("__pycache__")), [])


if __name__ == "__main__":
    unittest.main()
