#!/usr/bin/env python3
"""Read-only, offline runtime check: python -B -X utf8 scripts/preflight.py.

Exit 0: the bundled Python helpers are ready, not the full PPT workflow.
Exit 2: a helper requirement or package-integrity check failed.
No installs, environment edits, network requests or third-party imports occur.
Optional tool discovery is PATH/spec lookup, not a claim of usable automation.
"""

import sys

# Also protect a caller who omits -B. This changes only this Python process.
sys.dont_write_bytecode = True

import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

try:
    from runtime_support import write_json_utf8
except (ImportError, SyntaxError) as exc:
    # The shared writer may itself be missing. Keep the bootstrap failure
    # byte-safe too, including environments whose text stream is UTF-16.
    message = json.dumps({"read_only": True, "ready_for_python_helpers": False,
                          "error": "Cannot load runtime_support",
                          "reason": type(exc).__name__}) + "\n"
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(message)
        sys.stdout.flush()
    else:
        sys.stdout.flush()
        buffer.write(message.encode("utf-8"))
        buffer.flush()
    raise SystemExit(2)

MINIMUM_PYTHON = (3, 7)
STDLIB_MODULES = (
    "argparse", "collections", "fractions", "hashlib", "io", "importlib", "json", "math",
    "os", "pathlib", "posixpath", "shutil", "subprocess", "sys", "tempfile",
    "unicodedata", "unittest", "unittest.mock", "urllib.parse", "warnings",
    "xml.etree.ElementTree", "zipfile", "zlib",
)
REQUIRED_FILES = (
    "SKILL.md",
    "assets/run-state-template.json", "assets/template-audit.json",
    "assets/template-preview.jpg", "assets/template.pptx",
    "references/design.md", "references/writing.md", "references/portability.md", "references/review.md",
    "references/reviewer-prompt.md", "references/runtime.md",
    "references/security.md", "references/source-recovery.md",
    "references/workflow.md", "references/page-planning.md",
    "references/timing.md", "references/toolchain.md", "references/media-workflow.md",
    "references/review-control.md", "references/iteration-review.md",
    "scripts/audit_pptx.py", "scripts/runtime_support.py",
    "scripts/preflight.py", "scripts/test_audit_pptx.py",
    "scripts/test_runtime.py", "scripts/plan_timing.py", "scripts/test_plan_timing.py",
    "scripts/test_audit_timing.py", "scripts/freeze_review.py", "scripts/test_freeze_review.py",
)


def inspect_package(root):
    """Read only required files; report relative names, never machine paths."""
    results = []
    for relative in REQUIRED_FILES:
        try:
            path = root / relative
            with path.open("rb") as handle:
                if not handle.read(1):
                    raise ValueError("empty file")
            if relative.endswith(".json"):
                with path.open(encoding="utf-8") as handle:
                    json.load(handle)
            results.append({"file": relative, "status": "readable"})
        except (OSError, ValueError) as exc:
            results.append({"file": relative, "status": "failed",
                            "reason": type(exc).__name__})
    return results


def probe_utf8(script_dir):
    """Verify inherited-environment pipe bytes without creating a fixture."""
    command = [
        sys.executable, "-B", "-X", "utf8", "-c",
        "from runtime_support import write_json_utf8; "
        r"write_json_utf8({'probe': '\u4e2d\u6587\U0001f642'})",
    ]
    try:
        proc = subprocess.run(command, cwd=str(script_dir), capture_output=True,
                              timeout=15, check=False)
        result = json.loads(proc.stdout.decode("utf-8"))
        if proc.returncode != 0 or result != {"probe": "中文🙂"} or proc.stderr:
            raise ValueError("unexpected child result")
        return {"status": "passed", "child_flags": ["-B", "-X", "utf8"],
                "parent_decode": "utf-8", "inherited_io_encoding_retained": True}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return {"status": "failed", "reason": type(exc).__name__}


def preflight(root=None):
    root = Path(__file__).resolve().parent.parent if root is None else Path(root)
    imports = []
    for module in STDLIB_MODULES:
        try:
            importlib.import_module(module)
            imports.append({"module": module, "status": "available"})
        except (ImportError, OSError) as exc:
            imports.append({"module": module, "status": "failed",
                            "reason": type(exc).__name__})
    files = inspect_package(root)
    try:
        importlib.import_module("audit_pptx")
        audit_import = "passed"
    except (ImportError, OSError, SyntaxError):
        audit_import = "failed"
    helper_imports = {}
    for module in ("plan_timing", "freeze_review"):
        try:
            importlib.import_module(module)
            helper_imports[module] = "passed"
        except (ImportError, OSError, SyntaxError):
            helper_imports[module] = "failed"
    minimum_met = sys.version_info[:2] >= MINIMUM_PYTHON
    utf8 = (probe_utf8(root / "scripts") if minimum_met else
            {"status": "not_run", "reason": "Python 3.7 or newer is required"})
    try:
        pptx_spec = importlib.util.find_spec("pptx") is not None
    except (ImportError, ValueError):
        pptx_spec = False
    candidates = {
        name: shutil.which(name) is not None
        for name in ("POWERPNT", "libreoffice", "soffice", "pdftoppm", "ffprobe")
    }
    ready = (
        minimum_met
        and all(item["status"] == "available" for item in imports)
        and all(item["status"] == "readable" for item in files)
        and audit_import == "passed" and all(v == "passed" for v in helper_imports.values())
        and utf8["status"] == "passed"
    )
    return {
        "schema_version": 1, "read_only": True, "network_accessed": False,
        "ready_for_python_helpers": ready,
        "interpreter": {
            "implementation": sys.implementation.name,
            "version": ".".join(str(v) for v in sys.version_info[:3]),
            "platform": sys.platform, "static_minimum": "3.7",
            "minimum_met": minimum_met,
            "bytecode_writes_disabled": sys.dont_write_bytecode,
            "utf8_mode": getattr(sys.flags, "utf8_mode", None),
            "stdout_text_encoding": getattr(sys.stdout, "encoding", None),
            "pythonioencoding_is_set": "PYTHONIOENCODING" in os.environ,
        },
        "stdlib_imports": imports, "package_files": files,
        "audit_module_import": audit_import, "helper_module_imports": helper_imports,
        "utf8_pipe_contract": utf8,
        "optional_discovery": {
            "python_pptx_spec_found": pptx_spec,
            "commands_on_path": candidates,
            "not_imported_or_launched": True,
            "absence_is_not_a_workflow_blocker": True,
        },
        "host_capabilities_requiring_separate_verification": [
            "Authorized official-source search and full-text/browser access",
            "Editable PPTX creation, including notes, charts and media, via an available tool",
            "Full-slide rendering, Chinese font availability and actual visual inspection",
            "Media duration/decoding and target PowerPoint playback when required",
            "A genuinely fresh independent review context",
            "Authorized output directory and delivery destination",
        ],
        "limits": [
            "No host editor, browser, renderer or review session was exercised.",
            "PATH/spec discovery does not verify application automation or working imports.",
            "Python-pptx is optional; map actual host capabilities before declaring a blocker.",
            "Readable package assets are not visual, media, rights or full PPTX validation.",
            "This check does not prove cross-platform or end-to-end PPT compatibility.",
        ],
    }


def main():
    result = preflight()
    write_json_utf8(result)
    return 0 if result["ready_for_python_helpers"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
