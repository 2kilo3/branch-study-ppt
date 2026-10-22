#!/usr/bin/env python3
"""Freeze an explicitly allowlisted review input set, or verify it read-only.

Standard library only. No source edits, chmod, recursive copy, cache, network,
PPT execution, automatic cleanup, or acceptance judgment. See review-control.md.
Use -B -X utf8 when invoking Python; JSON stdout is UTF-8 even on a legacy pipe.
"""

import sys

sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat

from runtime_support import write_json_utf8

ROLES = ("candidate", "ledger", "outline", "media", "run_state", "audit_metrics")
ESSENTIAL_ROLES = {"candidate", "audit_metrics"}
MANIFEST = "manifest.json"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_AUDIT_BYTES = 16 * 1024 * 1024
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    prefix + str(number) for prefix in ("COM", "LPT") for number in range(1, 10)
}


class SnapshotError(ValueError):
    """A rejected input or incomplete operation, with no private absolute path."""


def relative_name(value):
    """Accept portable relative file names, never normalize traversal away."""
    if not isinstance(value, str) or not value:
        raise SnapshotError("Every input needs a nonempty relative file path")
    if (PurePosixPath(value).is_absolute() or PureWindowsPath(value).drive
            or "\\" in value or ":" in value):
        raise SnapshotError("Absolute, drive-qualified, or backslash paths are forbidden")
    parts = value.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise SnapshotError("Empty, dot, and parent path components are forbidden")
    for part in parts:
        if (part.endswith((" ", ".")) or any(ord(c) < 32 for c in part)
                or any(c in '<>"|?*' for c in part)
                or part.split(".", 1)[0].upper() in WINDOWS_RESERVED):
            raise SnapshotError("Input path is not a portable regular-file name")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise SnapshotError("Input paths must be valid Unicode") from exc
    if parts[0].casefold() == MANIFEST.casefold():
        raise SnapshotError("The snapshot manifest path is reserved")
    return value


def absolute_path(value):
    """Allow runtime absolute paths, but reject lexical traversal before abspath."""
    raw = os.fspath(value)
    if ".." in Path(raw).parts:
        raise SnapshotError("Parent traversal is forbidden in root/output paths")
    return Path(os.path.abspath(raw))


def is_link(info):
    # A Windows junction or other reparse point must not be followed either.
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def check_path(path, kind):
    """Reject links in every existing component and hardlinked input files."""
    parts = [path] + list(path.parents)
    for component in reversed(parts):
        info = component.lstat()
        if is_link(info):
            raise SnapshotError("Symlinks and reparse points are forbidden")
        if component != path and not stat.S_ISDIR(info.st_mode):
            raise SnapshotError("A parent path is not a directory")
    info = path.lstat()
    if kind == "directory":
        if not stat.S_ISDIR(info.st_mode):
            raise SnapshotError("Expected a directory")
    elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise SnapshotError("Expected a regular file with exactly one hard link")
    return info


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_nlink)


def read_regular(path, destination=None, max_bytes=None):
    """Hash a checked stream; optionally copy its bytes to an exclusive new file."""
    before = check_path(path, "file")
    if max_bytes is not None and before.st_size > max_bytes:
        raise SnapshotError("JSON input exceeds its size limit")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(str(path), flags)
    digest = hashlib.sha256()
    size = 0
    chunks = [] if max_bytes is not None else None
    with os.fdopen(fd, "rb") as source:
        opened = os.fstat(source.fileno())
        # Windows path/handle ctime can differ; compare ctime only within the same API.
        if (identity(opened)[:4] != identity(before)[:4]
                or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1):
            raise SnapshotError("An input changed while it was being opened")
        output = None
        try:
            if destination is not None:
                check_path(destination.parent, "directory")
                # No overwrite, including an attacker-created symlink/hardlink.
                out_flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | getattr(os, "O_BINARY", 0)
                             | getattr(os, "O_NOFOLLOW", 0))
                output = os.fdopen(os.open(str(destination), out_flags, 0o666), "wb")
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if max_bytes is not None and size > max_bytes:
                    raise SnapshotError("JSON input exceeds its size limit")
                digest.update(chunk)
                if output is not None:
                    output.write(chunk)
                if chunks is not None:
                    chunks.append(chunk)
            if identity(os.fstat(source.fileno())) != identity(opened):
                raise SnapshotError("An input changed while it was being read")
        finally:
            if output is not None:
                output.close()
    if identity(check_path(path, "file")) != identity(before):
        raise SnapshotError("An input changed while it was being read")
    return digest.hexdigest(), size, b"".join(chunks) if chunks is not None else None


def validate_files(files, required_roles=()):
    required = ESSENTIAL_ROLES | set(required_roles)
    if not required <= set(ROLES):
        raise SnapshotError("Unknown required review input role")
    if (not isinstance(files, dict) or not required <= set(files)
            or not set(files) <= set(ROLES)):
        raise SnapshotError("All required roles must be provided from the six-role allowlist")
    normalized = {role: relative_name(files[role]) for role in ROLES if role in files}
    names = [name.casefold() for name in normalized.values()]
    if len(set(names)) != len(names):
        raise SnapshotError("Each role requires a distinct file path")
    for name in names:
        if any(other.startswith(name + "/") for other in names):
            raise SnapshotError("A file path cannot also be a parent directory")
    if not normalized["candidate"].lower().endswith(".pptx"):
        raise SnapshotError("The candidate role requires a .pptx file")
    return normalized


def decode_object(data):
    def no_duplicate_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise SnapshotError("Duplicate JSON keys are forbidden")
            result[key] = value
        return result
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=no_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SnapshotError("Expected a UTF-8 JSON document") from exc
    if not isinstance(value, dict):
        raise SnapshotError("Expected a JSON object")
    return value


def audit_fingerprint(audit):
    """The measured audit, not a handwritten outline, owns candidate measurements."""
    value = audit.get("input_fingerprint")
    if (not isinstance(value, dict) or not isinstance(value.get("sha256"), str)
            or not HASH_RE.fullmatch(value["sha256"])
            or type(value.get("size_bytes")) is not int or value["size_bytes"] < 0
            or "error" in audit):
        raise SnapshotError("Audit requires an input_fingerprint with SHA-256 and byte count")
    return value["sha256"], value["size_bytes"]


def freeze_review(input_root, output, files, required_roles=(),
                  private_stable_workspace=False):
    if private_stable_workspace is not True:
        raise SnapshotError("Freeze requires an explicitly confirmed private, stable workspace")
    files = validate_files(files, required_roles)
    root, target = absolute_path(input_root), absolute_path(output)
    check_path(root, "directory")
    check_path(target.parent, "directory")
    if target == root or root in target.parents or target in root.parents:
        raise SnapshotError("Snapshot and input root must be separate, non-nested trees")
    if os.path.lexists(target):
        raise SnapshotError("Output already exists; select a new snapshot directory")
    for name in files.values():
        check_path(root / name, "file")
    candidate_hash, candidate_size, _ = read_regular(root / files["candidate"])
    _, _, audit_bytes = read_regular(root / files["audit_metrics"],
                                    max_bytes=MAX_AUDIT_BYTES)
    if audit_fingerprint(decode_object(audit_bytes)) != (candidate_hash, candidate_size):
        raise SnapshotError("Audit is bound to a different candidate; regenerate it")

    # Exclusive directory creation; an error leaves an incomplete snapshot for
    # inspection. Never recursively delete a path supplied by a caller.
    target.mkdir()
    rows = []
    for role in ROLES:
        if role not in files:
            continue
        destination = target / files[role]
        for parent in reversed(destination.parent.parents):
            if parent == target or target in parent.parents:
                if not parent.exists():
                    parent.mkdir()
                check_path(parent, "directory")
        if not destination.parent.exists():
            destination.parent.mkdir()
        check_path(destination.parent, "directory")
        digest, size, _ = read_regular(root / files[role], destination)
        rows.append({"id": role, "path": files[role], "sha256": digest, "bytes": size})
    copied = {row["id"]: row for row in rows}
    if copied["candidate"]["sha256"] != candidate_hash:
        raise SnapshotError("Candidate changed after preflight; snapshot is incomplete")
    _, _, copied_audit = read_regular(target / files["audit_metrics"],
                                     max_bytes=MAX_AUDIT_BYTES)
    if audit_fingerprint(decode_object(copied_audit)) != (candidate_hash, candidate_size):
        raise SnapshotError("Audit changed after preflight; snapshot is incomplete")
    # A final source-vs-copy comparison catches ordinary concurrent edits to
    # earlier files. This is not an OS lock against a hostile concurrent writer.
    for row in rows:
        digest, size, _ = read_regular(root / row["path"])
        if digest != row["sha256"] or size != row["bytes"]:
            raise SnapshotError("Input changed during freeze; snapshot is incomplete")
        copied_hash, copied_size, _ = read_regular(target / row["path"])
        if copied_hash != digest or copied_size != size:
            raise SnapshotError("Output changed during freeze; snapshot is incomplete")
    manifest = {
        "schema_version": 1,
        "purpose": "review-input-snapshot",
        "required_roles": sorted(ESSENTIAL_ROLES | set(required_roles)),
        "candidate_sha256": candidate_hash,
        "measurement_authority": files["audit_metrics"],
        "acceptance_status": "not_assessed",
        "files": rows,
    }
    encoded = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    check_path(target, "directory")
    with (target / MANIFEST).open("xb") as stream:
        stream.write(encoded)
    expected = hashlib.sha256(encoded).hexdigest()
    checked = verify_review(target, expected)
    if checked["integrity"] != "consistent":
        raise SnapshotError("Output changed during freeze; do not use this snapshot")
    return {"operation": "freeze", "snapshot_created": True, "file_count": len(rows),
            "manifest_sha256": expected, "candidate_sha256": candidate_hash,
            "review_status": "not_assessed", "input_files_modified": False,
            "os_permissions_changed": False,
            "path_safety": "private_stable_workspace; no hostile ancestor-race protection"}


def parse_manifest(data):
    value = decode_object(data)
    if value.get("schema_version") != 1 or value.get("purpose") != "review-input-snapshot":
        raise SnapshotError("Unsupported snapshot manifest")
    rows = value.get("files")
    required = value.get("required_roles")
    if (not isinstance(required, list) or any(role not in ROLES for role in required)
            or len(set(required)) != len(required)
            or not ESSENTIAL_ROLES <= set(required)):
        raise SnapshotError("Manifest must state its required review roles")
    if not isinstance(rows, list) or not 2 <= len(rows) <= len(ROLES):
        raise SnapshotError("Manifest needs two to six explicit file records")
    files, records = {}, {}
    for row in rows:
        if not isinstance(row, dict) or row.get("id") in files:
            raise SnapshotError("Invalid or duplicate manifest record")
        role, name = row.get("id"), row.get("path")
        if role not in ROLES:
            raise SnapshotError("Unknown file role in manifest")
        if (not isinstance(row.get("sha256"), str)
                or not HASH_RE.fullmatch(row["sha256"])
                or type(row.get("bytes")) is not int or row["bytes"] < 0):
            raise SnapshotError("Invalid hash or byte count in manifest")
        files[role] = name
        records[role] = row
    validate_files(files, required)
    if (value.get("candidate_sha256") != records["candidate"]["sha256"]
            or value.get("measurement_authority") != files["audit_metrics"]
            or value.get("acceptance_status") != "not_assessed"):
        raise SnapshotError("Manifest binding or purpose is inconsistent")
    return rows


def inventory(root):
    """List without following links; include unknown empty directories."""
    files, directories, unsafe = set(), set(), set()
    pending = [root]
    while pending:
        current = pending.pop()
        check_path(current, "directory")
        with os.scandir(current) as entries:
            for entry in entries:
                path = Path(entry.path)
                name = path.relative_to(root).as_posix()
                # Windows DirEntry.stat reports st_nlink=0; lstat supplies the real link count.
                info = path.lstat()
                if is_link(info):
                    unsafe.add(name)
                elif stat.S_ISDIR(info.st_mode):
                    directories.add(name + "/")
                    pending.append(path)
                elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    unsafe.add(name)
                else:
                    files.add(name)
    return files, directories, unsafe


def verify_review(snapshot, expected_manifest_sha256):
    if (not isinstance(expected_manifest_sha256, str)
            or not HASH_RE.fullmatch(expected_manifest_sha256)):
        raise SnapshotError("A trusted external manifest SHA-256 is required")
    root = absolute_path(snapshot)
    check_path(root, "directory")
    result = {"operation": "verify", "read_only": True, "integrity": "different",
              "review_status": "not_assessed", "changed": [], "missing": [],
              "unexpected": [], "unsafe": [], "manifest_digest_matches": False}
    if not os.path.lexists(root / MANIFEST):
        result["missing"] = [MANIFEST]
        return result
    digest, _, data = read_regular(root / MANIFEST, max_bytes=MAX_MANIFEST_BYTES)
    if digest != expected_manifest_sha256:
        result["changed"] = [MANIFEST]
        result["detail"] = "Manifest changed; untrusted inventory was not used"
        return result
    result["manifest_digest_matches"] = True
    rows = parse_manifest(data)
    expected_files = {row["path"] for row in rows} | {MANIFEST}
    expected_dirs = set()
    for row in rows:
        expected_dirs.update(
            parent.as_posix() + "/" for parent in PurePosixPath(row["path"]).parents
            if parent.as_posix() != "."
        )
    actual, directories, unsafe = inventory(root)
    result["unsafe"] = sorted(unsafe)
    result["missing"] = sorted(expected_files - actual - unsafe)
    result["unexpected"] = sorted((actual | unsafe) - expected_files
                                  | (directories - expected_dirs))
    for row in rows:
        if row["path"] not in actual:
            continue
        digest, size, _ = read_regular(root / row["path"])
        if digest != row["sha256"] or size != row["bytes"]:
            result["changed"].append(row["path"])
    result["changed"].sort()
    if not any(result[key] for key in ("changed", "missing", "unexpected", "unsafe")):
        result["integrity"] = "consistent"
    return result


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse often echoes unrecognized arguments, including private paths.
        raise SnapshotError("Invalid command-line arguments; use --help for syntax")


def main(argv=None):
    parser = JsonArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    freezing = subparsers.add_parser("freeze", help="Create a new allowlisted snapshot")
    freezing.add_argument("--input-root", required=True)
    freezing.add_argument("--output", required=True)
    freezing.add_argument("--private-stable-workspace", action="store_true",
                         help="Assert private stable input/output directories with no other writers")
    for flag in ("candidate", "ledger", "outline", "media", "run-state", "audit"):
        freezing.add_argument("--" + flag, required=flag in ("candidate", "audit"))
    freezing.add_argument("--require-role", action="append", default=[], choices=ROLES,
                         help="Additional role required by this task; repeat as needed")
    verifying = subparsers.add_parser("verify", help="Read-only integrity check")
    verifying.add_argument("--snapshot", required=True)
    verifying.add_argument("--expected-manifest-sha256", required=True)
    try:
        args = parser.parse_args(argv)
        if args.operation == "freeze":
            files = {role: getattr(args, role if role != "audit_metrics" else "audit")
                     for role in ROLES}
            files = {role: name for role, name in files.items() if name is not None}
            result = freeze_review(args.input_root, args.output, files, args.require_role,
                                   args.private_stable_workspace)
        else:
            result = verify_review(args.snapshot, args.expected_manifest_sha256)
        write_json_utf8(result)
        return 1 if result.get("integrity") == "different" else 0
    except (SnapshotError, OSError, TypeError, RecursionError) as exc:
        # OSError text often contains private absolute paths. Report its class
        # only; semantic errors above are deliberately path-free.
        detail = str(exc) if isinstance(exc, SnapshotError) else type(exc).__name__
        write_json_utf8({"error": detail, "operation_completed": False,
                         "review_status": "not_assessed",
                         "note": "No cleanup was attempted; a partial output may remain"})
        return 2


if __name__ == "__main__":
    sys.exit(main())
