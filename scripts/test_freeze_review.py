"""Offline synthetic tests for review snapshots; never opens a real user PPT."""

import sys

sys.dont_write_bytecode = True

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import freeze_review as snapshot


def sha(data):
    return hashlib.sha256(data).hexdigest()


def tree(root):
    return {path.relative_to(root).as_posix(): sha(path.read_bytes())
            for path in root.rglob("*") if path.is_file()}


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # realpath avoids host-provided aliases such as macOS /var -> /private/var.
        self.base = Path(os.path.realpath(self.temp.name))
        self.root = self.base / "工作🙂"
        self.root.mkdir()
        self.output = self.base / "候选快照🙂"
        self.files = {
            "candidate": "candidate/学习会🙂.pptx",
            "ledger": "sources/claim-ledger.md",
            "outline": "outline-and-timing.md",
            "media": "media-manifest.md",
            "run_state": "run-state.json",
            "audit_metrics": "metrics/audit.json",
        }
        for role, name in self.files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("测试材料：" + role, encoding="utf-8")
        self.candidate = self.root / self.files["candidate"]
        self.audit = self.root / self.files["audit_metrics"]
        self.rebind()

    def rebind(self):
        data = self.candidate.read_bytes()
        self.audit.write_text(json.dumps({
            "input_fingerprint": {"sha256": sha(data), "size_bytes": len(data)},
            "summary": {"slide_count": 1, "total_notes_chinese_characters": 10},
        }, ensure_ascii=False), encoding="utf-8")

    def freeze(self, **kwargs):
        return self.freeze_inputs(self.root, self.output, self.files, **kwargs)

    def freeze_inputs(self, *args, **kwargs):
        # All fixtures are newly created in this test's private temporary tree.
        return snapshot.freeze_review(*args, private_stable_workspace=True, **kwargs)

    def verify(self, frozen):
        return snapshot.verify_review(self.output, frozen["manifest_sha256"])

    def edit_manifest(self, edit):
        path = self.output / snapshot.MANIFEST
        value = json.loads(path.read_text(encoding="utf-8"))
        edit(value)
        data = json.dumps(value, ensure_ascii=False).encode("utf-8")
        path.write_bytes(data)
        return sha(data)

    def link(self, source, target, hard=False):
        try:
            if hard:
                os.link(source, target)
            else:
                target.symlink_to(source, target_is_directory=source.is_dir())
        except (NotImplementedError, OSError) as exc:
            self.skipTest("Host does not permit this link fixture: " + type(exc).__name__)

    def test_path_and_handle_creation_times_may_differ_but_each_stays_stable(self):
        real_fstat = os.fstat

        def handle_stat(fd):
            info = real_fstat(fd)
            fields = {name: getattr(info, name) for name in
                      ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink", "st_mode")}
            fields["st_ctime_ns"] += 100
            return SimpleNamespace(**fields)

        with mock.patch.object(snapshot.os, "fstat", side_effect=handle_stat):
            digest, size, _ = snapshot.read_regular(self.candidate)
        self.assertEqual(digest, hashlib.sha256(self.candidate.read_bytes()).hexdigest())
        self.assertEqual(size, self.candidate.stat().st_size)

    def test_changed_handle_timestamp_during_read_is_rejected(self):
        real_fstat = os.fstat
        calls = []

        def handle_stat(fd):
            info = real_fstat(fd)
            fields = {name: getattr(info, name) for name in
                      ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_nlink", "st_mode")}
            fields["st_ctime_ns"] += len(calls)
            calls.append(fd)
            return SimpleNamespace(**fields)

        with mock.patch.object(snapshot.os, "fstat", side_effect=handle_stat):
            with self.assertRaises(snapshot.SnapshotError):
                snapshot.read_regular(self.candidate)

    def test_round_trip_relative_manifest_source_unchanged_and_read_only_verify(self):
        before = tree(self.root)
        frozen = self.freeze(required_roles=list(snapshot.ROLES))
        self.assertEqual(before, tree(self.root))
        self.assertEqual(frozen["file_count"], 6)
        manifest = json.loads((self.output / snapshot.MANIFEST).read_text(encoding="utf-8"))
        self.assertNotIn(str(self.base), json.dumps(manifest))
        self.assertEqual({row["path"] for row in manifest["files"]}, set(self.files.values()))
        self.assertEqual(manifest["acceptance_status"], "not_assessed")
        output_before = tree(self.output)
        verified = self.verify(frozen)
        self.assertEqual(verified["integrity"], "consistent")
        self.assertTrue(verified["read_only"])
        self.assertEqual(output_before, tree(self.output))
        self.assertEqual(before, tree(self.root))

    def test_optional_roles_do_not_require_dummy_files(self):
        minimal = {role: self.files[role] for role in snapshot.ESSENTIAL_ROLES}
        frozen = self.freeze_inputs(self.root, self.output, minimal)
        self.assertEqual(frozen["file_count"], 2)
        self.assertEqual(self.verify(frozen)["integrity"], "consistent")

    def test_task_required_role_cannot_be_omitted(self):
        files = {role: self.files[role] for role in snapshot.ESSENTIAL_ROLES}
        with self.assertRaises(snapshot.SnapshotError):
            self.freeze_inputs(self.root, self.output, files, ["ledger"])
        self.assertFalse(self.output.exists())

    def test_unknown_or_duplicate_role_file_rejected(self):
        for files in ({**self.files, "unapproved": "secret.txt"},
                      {**self.files, "ledger": self.files["outline"]},
                      {"candidate": self.files["candidate"]}):
            with self.subTest(files=files), self.assertRaises(snapshot.SnapshotError):
                self.freeze_inputs(self.root, self.output, files)

    def test_unselected_files_are_not_copied(self):
        (self.root / "private-unrelated.txt").write_text("not allowed", encoding="utf-8")
        frozen = self.freeze()
        self.assertFalse((self.output / "private-unrelated.txt").exists())
        self.assertEqual(self.verify(frozen)["integrity"], "consistent")

    def test_changed_missing_and_unexpected_are_reported_together(self):
        frozen = self.freeze()
        changed = self.output / self.files["ledger"]
        changed.write_text("changed", encoding="utf-8")
        (self.output / self.files["outline"]).unlink()
        (self.output / "review-report.md").write_text("outside snapshot only", encoding="utf-8")
        (self.output / "empty-unexpected-directory").mkdir()
        result = self.verify(frozen)
        self.assertEqual(result["integrity"], "different")
        self.assertEqual(result["changed"], [self.files["ledger"]])
        self.assertEqual(result["missing"], [self.files["outline"]])
        self.assertEqual(result["unexpected"],
                         ["empty-unexpected-directory/", "review-report.md"])

    def test_manifest_tamper_is_detected_by_external_digest(self):
        frozen = self.freeze()
        self.edit_manifest(lambda value: value.update(extra="changed"))
        result = self.verify(frozen)
        self.assertFalse(result["manifest_digest_matches"])
        self.assertEqual(result["changed"], [snapshot.MANIFEST])

    def test_missing_manifest_is_reported(self):
        frozen = self.freeze()
        (self.output / snapshot.MANIFEST).unlink()
        self.assertEqual(self.verify(frozen)["missing"], [snapshot.MANIFEST])

    def test_file_plus_manifest_tamper_does_not_defeat_trusted_digest(self):
        frozen = self.freeze()
        changed = self.output / self.files["ledger"]
        changed.write_bytes(b"replaced")
        def change_row(value):
            for row in value["files"]:
                if row["id"] == "ledger":
                    row["sha256"], row["bytes"] = sha(b"replaced"), 8
        self.edit_manifest(change_row)
        self.assertEqual(self.verify(frozen)["changed"], [snapshot.MANIFEST])

    def test_manifest_traversal_rejected_even_with_matching_external_digest(self):
        self.freeze()
        digest = self.edit_manifest(
            lambda value: value["files"][0].update(path="../outside.pptx"))
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.verify_review(self.output, digest)

    def test_manifest_unknown_role_and_bad_hash_rejected(self):
        frozen = self.freeze()
        original = (self.output / snapshot.MANIFEST).read_bytes()
        for edit in (
            lambda value: value["files"][0].update(id="secret"),
            lambda value: value["files"][0].update(sha256="not a hash"),
            lambda value: value.update(required_roles=[]),
        ):
            with self.subTest(edit=edit):
                (self.output / snapshot.MANIFEST).write_bytes(original)
                digest = self.edit_manifest(edit)
                with self.assertRaises(snapshot.SnapshotError):
                    snapshot.verify_review(self.output, digest)
        self.assertEqual(frozen["review_status"], "not_assessed")

    def test_expected_manifest_digest_is_required_and_validated(self):
        self.freeze()
        for value in ("", None, "A" * 64, "../manifest.json"):
            with self.subTest(value=value), self.assertRaises(snapshot.SnapshotError):
                snapshot.verify_review(self.output, value)

    def test_no_overwrite_or_automatic_deletion(self):
        self.output.mkdir()
        retained = self.output / "keep.txt"
        retained.write_bytes(b"keep")
        with self.assertRaises(snapshot.SnapshotError):
            self.freeze()
        self.assertEqual(retained.read_bytes(), b"keep")

    def test_output_cannot_be_input_or_inside_input_or_its_ancestor(self):
        for output in (self.root, self.root / "snap", self.base):
            with self.subTest(output=output), self.assertRaises(snapshot.SnapshotError):
                self.freeze_inputs(self.root, output, self.files)
        self.assertFalse((self.root / "snap").exists())

    def test_file_path_traversal_absolute_and_portability_rejected(self):
        for name in ("../outside.md", "a/../outside.md", "/outside.md", "C:/outside.md",
                     "a\\outside.md", "a//b.md", "./a.md", "a/./b.md",
                     "manifest.json", "manifest.json/x", "a/NUL.txt", "a/x."):
            with self.subTest(name=name), self.assertRaises(snapshot.SnapshotError):
                self.freeze_inputs(self.root, self.output, {**self.files, "ledger": name})

    def test_root_and_output_parent_traversal_not_normalized_away(self):
        with self.assertRaises(snapshot.SnapshotError):
            self.freeze_inputs(self.root / ".." / self.root.name,
                               self.output, self.files)
        with self.assertRaises(snapshot.SnapshotError):
            self.freeze_inputs(self.root, self.base / ".." / "snapshot", self.files)

    def test_mismatched_audit_hash_or_size_rejected_before_output_creation(self):
        for field, bad in (("sha256", "0" * 64), ("size_bytes", 999)):
            self.rebind()
            value = json.loads(self.audit.read_text(encoding="utf-8"))
            value["input_fingerprint"][field] = bad
            self.audit.write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(field=field), self.assertRaises(snapshot.SnapshotError):
                self.freeze()
            self.assertFalse(self.output.exists())

    def test_old_or_error_audit_cannot_be_freeze_authority(self):
        for value in ({}, {"input_fingerprint": {}, "error": "failed"},
                      {"candidate_sha256": sha(self.candidate.read_bytes())}):
            self.audit.write_text(json.dumps(value), encoding="utf-8")
            with self.subTest(value=value), self.assertRaises(snapshot.SnapshotError):
                self.freeze()
        self.assertFalse(self.output.exists())

    def test_symlink_input_file_rejected(self):
        source = self.root / self.files["ledger"]
        outside = self.base / "outside.txt"
        outside.write_bytes(b"outside")
        source.unlink()
        self.link(outside, source)
        with self.assertRaises(snapshot.SnapshotError):
            self.freeze()
        self.assertFalse(self.output.exists())

    def test_symlink_input_parent_or_root_rejected(self):
        linked_root = self.base / "root-link"
        self.link(self.root, linked_root)
        with self.assertRaises(snapshot.SnapshotError):
            self.freeze_inputs(linked_root, self.output, self.files)
        linked_parent = self.root / "linked-parent"
        self.link(self.root / "sources", linked_parent)
        with self.assertRaises(snapshot.SnapshotError):
            self.freeze_inputs(self.root, self.output,
                               {**self.files, "ledger": "linked-parent/claim-ledger.md"})

    def test_symlink_output_parent_and_dangling_output_rejected(self):
        outside = self.base / "outside"
        outside.mkdir()
        parent_link = self.base / "parent-link"
        self.link(outside, parent_link)
        with self.assertRaises(snapshot.SnapshotError):
            self.freeze_inputs(self.root, parent_link / "snap", self.files)
        self.link(self.base / "missing-target", self.output)
        with self.assertRaises(snapshot.SnapshotError):
            self.freeze()
        self.assertFalse((self.base / "missing-target").exists())

    def test_hardlinked_input_rejected(self):
        self.link(self.root / self.files["ledger"], self.base / "second-link", hard=True)
        with self.assertRaises(snapshot.SnapshotError):
            self.freeze()
        self.assertFalse(self.output.exists())

    def test_verify_reports_symlink_without_reading_target(self):
        frozen = self.freeze()
        target = self.output / self.files["ledger"]
        target.unlink()
        self.link(self.base / "nonexistent-private-target", target)
        result = self.verify(frozen)
        self.assertEqual(result["unsafe"], [self.files["ledger"]])
        self.assertEqual(result["integrity"], "different")

    def test_verify_reports_hardlink_and_does_not_follow_unexpected_symlink_dir(self):
        frozen = self.freeze()
        self.link(self.output / self.files["ledger"], self.base / "alias", hard=True)
        self.link(self.root, self.output / "linked-directory")
        result = self.verify(frozen)
        self.assertEqual(result["unsafe"], ["linked-directory", self.files["ledger"]])
        self.assertIn("linked-directory", result["unexpected"])

    def test_concurrent_input_edit_leaves_no_valid_manifest_and_never_deletes(self):
        original = snapshot.read_regular
        edited = []
        def changing(path, destination=None, max_bytes=None):
            result = original(path, destination, max_bytes)
            if destination is not None and path == self.root / self.files["ledger"]:
                self.candidate.write_bytes(b"changed after copy")
                edited.append(True)
            return result
        with mock.patch.object(snapshot, "read_regular", side_effect=changing):
            with self.assertRaises(snapshot.SnapshotError):
                self.freeze()
        self.assertTrue(edited)
        self.assertTrue(self.output.exists())
        self.assertFalse((self.output / snapshot.MANIFEST).exists())
        self.assertEqual(self.candidate.read_bytes(), b"changed after copy")

    def test_subprocess_utf8_json_legacy_pipes_and_no_bytecode(self):
        tools = self.base / "tools"
        tools.mkdir()
        for name in ("freeze_review.py", "runtime_support.py"):
            shutil.copyfile(Path(snapshot.__file__).parent / name, tools / name)
        baseline = tree(tools)
        for encoding in ("ascii", "gbk"):
            with self.subTest(encoding=encoding):
                output = self.base / ("snapshot-" + encoding)
                env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP") if key in os.environ}
                env.update(PYTHONIOENCODING=encoding, PYTHONUTF8="0")
                command = [sys.executable, "-X", "utf8=0", str(tools / "freeze_review.py"),
                           "freeze", "--private-stable-workspace",
                           "--input-root", str(self.root), "--output", str(output),
                           "--candidate", self.files["candidate"],
                           "--audit", self.files["audit_metrics"]]
                proc = subprocess.run(command, env=env, capture_output=True, timeout=30)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(proc.stderr, b"")
                value = json.loads(proc.stdout.decode("utf-8"))
                command = command[:4] + ["verify", "--snapshot", str(output),
                                        "--expected-manifest-sha256", value["manifest_sha256"]]
                proc = subprocess.run(command, env=env, capture_output=True, timeout=30)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
                self.assertEqual(json.loads(proc.stdout.decode("utf-8"))["integrity"], "consistent")
        self.assertEqual(baseline, tree(tools))
        self.assertEqual(list(tools.rglob("__pycache__")), [])

    def test_argument_errors_are_utf8_json_not_locale_tracebacks(self):
        env = {key: os.environ[key] for key in ("SystemRoot", "WINDIR", "PATH", "TEMP", "TMP") if key in os.environ}
        env.update(PYTHONIOENCODING="gbk", PYTHONUTF8="0")
        proc = subprocess.run([sys.executable, "-B", "-X", "utf8=0", snapshot.__file__,
                               "verify", "--snapshot", str(self.output),
                               "--expected-manifest-sha256", "不是哈希🙂"],
                              env=env, capture_output=True, timeout=30)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stderr, b"")
        self.assertIn("error", json.loads(proc.stdout.decode("utf-8")))

    def test_freeze_refuses_without_explicit_stable_private_precondition(self):
        with self.assertRaises(snapshot.SnapshotError):
            snapshot.freeze_review(self.root, self.output, self.files)
        self.assertFalse(self.output.exists())

    def test_invalid_cli_does_not_echo_private_absolute_arguments(self):
        sentinel = "/private/person-name/confidential-user-file"
        proc = subprocess.run(
            [sys.executable, "-B", snapshot.__file__, "verify", "--snapshot", str(self.output),
             "--expected-manifest-sha256", "0" * 64, "--unexpected", sentinel],
            capture_output=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(proc.stderr, b"")
        self.assertNotIn(sentinel.encode("utf-8"), proc.stdout)
        self.assertNotIn(str(self.base).encode("utf-8"), proc.stdout)
        self.assertIn("error", json.loads(proc.stdout.decode("utf-8")))


if __name__ == "__main__":
    unittest.main()
