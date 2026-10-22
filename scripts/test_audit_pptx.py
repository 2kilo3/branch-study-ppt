#!/usr/bin/env python3
"""Synthetic fixtures; run: python -B -X utf8 -m unittest discover -s scripts -v

No source presentation, speaker notes, or proprietary imagery is bundled here.
Fixtures exercise this structural checker, not full PowerPoint interoperability.
"""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import warnings
import zipfile
from pathlib import Path

import audit_pptx as audit

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"


def rels(*items):
    return '<Relationships xmlns="%s">%s</Relationships>' % (PKG, "".join(items))


def rel(rid, kind, target, external=False):
    return '<Relationship Id="%s" Type="%s/%s" Target="%s"%s/>' % (
        rid, R, kind, target, ' TargetMode="External"' if external else "")


def shape(sid, text, x=0, y=0, width=100, height=100, size=2000,
          placeholder="", rotation=0, field=""):
    ph = '<p:ph type="%s"/>' % placeholder if placeholder else ""
    return '''<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="Shape {sid}"/>
      <p:cNvSpPr/><p:nvPr>{ph}</p:nvPr></p:nvSpPr>
      <p:spPr><a:xfrm rot="{rotation}"><a:off x="{x}" y="{y}"/>
      <a:ext cx="{width}" cy="{height}"/></a:xfrm></p:spPr>
      <p:txBody><a:bodyPr/><a:p><a:r><a:rPr sz="{size}"/>
      <a:t>{text}</a:t></a:r>{field}</a:p></p:txBody></p:sp>'''.format(**locals())


def slide(shapes, tag="sld"):
    return '<p:%s xmlns:p="%s" xmlns:a="%s" xmlns:r="%s"><p:cSld><p:spTree>%s</p:spTree></p:cSld></p:%s>' % (
        tag, P, A, R, shapes, tag)


def fixture(path, broken=False, extra_shapes="", slide_names=("slide1.xml",), notes=True):
    ids = ''.join('<p:sldId id="%s" r:id="rId%s"/>' % (255 + i, i)
                  for i, name in enumerate(slide_names, 1))
    data = {
        "_rels/.rels": rels(rel("office", "officeDocument", "/ppt/presentation.xml")),
        "ppt/presentation.xml": '<p:presentation xmlns:p="%s" xmlns:r="%s"><p:sldIdLst>%s</p:sldIdLst><p:sldSz cx="1000" cy="500"/></p:presentation>' % (P, R, ids),
        "ppt/_rels/presentation.xml.rels": rels(*(rel("rId%s" % i, "slide", "slides/" + name)
                                                 for i, name in enumerate(slide_names, 1))),
        "ppt/media/image one.png": b"fixture, not rendered",
    }
    for i, name in enumerate(slide_names, 1):
        data["ppt/slides/" + name] = slide(shape(1, "幻灯片", size=1900) + extra_shapes)
        links = [rel("image", "image", "../media/image%20one.png"),
                 rel("url", "hyperlink", "https://example.invalid/not-checked", external=True),
                 rel("fragment", "hyperlink", "#same-part-fragment")]
        if notes:
            links.append(rel("notes", "notesSlide", "../notesSlides/notes%s.xml" % i))
            field = '<a:fld id="field" type="slidenum"><a:t>字段页码</a:t></a:fld>'
            note_shapes = shape(1, "正文汉字 abc 123，。", placeholder="body", field=field)
            note_shapes += shape(2, "补充〇")
            note_shapes += shape(3, "应当排除的中文页码", placeholder="sldNum")
            note_shapes += shape(4, "页脚文字", placeholder="ftr")
            data["ppt/notesSlides/notes%s.xml" % i] = slide(note_shapes, "notes")
        if broken:
            links.append(rel("missing", "image", "../media/absent.png"))
            links.append(rel("escape", "image", "../../../outside.xml"))
            links.append(rel("empty", "image", ""))
        data["ppt/slides/_rels/" + name + ".rels"] = rels(*links)
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in data.items():
            zf.writestr(name, content)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "fixture.pptx"

    def test_good_targets_and_notes_exclusions(self):
        fixture(self.path)
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        result = audit.audit_pptx(self.path)
        self.assertEqual(result["slide_count"], 1)
        self.assertEqual(result["slide_dimensions"]["width_emu"], 1000)
        self.assertEqual(result["relationships"]["broken_internal_targets"], [])
        self.assertEqual(result["relationships"]["external_not_checked"], 1)
        self.assertEqual(result["summary"]["total_notes_chinese_characters"], 7)
        self.assertEqual(result["slides"][0]["notes"]["excluded_placeholder_shapes"], 2)
        self.assertEqual(result["slides"][0]["notes"]["excluded_slide_number_fields"], 1)
        self.assertEqual(result["summary"]["explicit_font_size_findings_below_minimum"], 1)
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_missing_and_invalid_targets(self):
        fixture(self.path, broken=True)
        broken = audit.audit_pptx(self.path)["relationships"]["broken_internal_targets"]
        self.assertEqual(len(broken), 3)
        self.assertEqual(broken[0]["resolved_target"], "ppt/media/absent.png")
        self.assertEqual(broken[0]["reason"], "missing_zip_member")
        self.assertEqual(broken[1]["reason"], "invalid_internal_target")
        self.assertEqual(broken[2]["reason"], "invalid_internal_target")

    def test_geometry_skips_rotation_and_groups(self):
        nested = '<p:grpSp>' + shape(3, "组内", x=-9000) + '</p:grpSp>'
        extra = shape(2, "越界", x=-1, y=450, width=100, height=100)
        extra += nested + shape(4, "旋转", x=-9000, rotation=5400000)
        fixture(self.path, extra_shapes=extra)
        s = audit.audit_pptx(self.path)["slides"][0]
        self.assertEqual(s["simple_shape_bounds_checked"], 2)
        self.assertEqual(len(s["out_of_canvas_simple_shapes"]), 1)
        self.assertEqual(s["out_of_canvas_simple_shapes"][0]["outside_edges"], ["left", "bottom"])
        self.assertEqual(s["bounds_checks_skipped"]["groups"], 1)
        self.assertEqual(s["bounds_checks_skipped"]["nested_shapes_in_groups"], 1)
        self.assertEqual(s["bounds_checks_skipped"]["rotated_shapes"], 1)

    def test_manifest_order_and_deck_wide_timing(self):
        fixture(self.path, slide_names=("slide9.xml", "slide2.xml"))
        result = audit.audit_pptx(self.path, rate_min=60, rate_max=120,
                                  video_seconds=10, transition_seconds=5)
        self.assertEqual([s["part"] for s in result["slides"]],
                         ["ppt/slides/slide9.xml", "ppt/slides/slide2.xml"])
        self.assertEqual(result["summary"]["total_notes_chinese_characters"], 14)
        self.assertEqual(result["timing_estimate"]["narration_seconds"], {"min": 7, "max": 14})
        self.assertEqual(result["timing_estimate"]["total_seconds"], {"min": 22, "max": 29})

    def test_missing_notes_not_fabricated(self):
        fixture(self.path, notes=False)
        result = audit.audit_pptx(self.path)
        self.assertEqual(result["slides"][0]["notes"]["status"], "no_notes_relationship")
        self.assertEqual(result["summary"]["total_notes_chinese_characters"], 0)

    def test_input_validation(self):
        fixture(self.path)
        for settings in ({"rate_min": 300, "rate_max": 230}, {"min_font": 0},
                         {"video_seconds": -1}, {"rate_max": float("nan")}):
            with self.assertRaises(ValueError):
                audit.audit_pptx(self.path, **settings)

    def test_han_not_punctuation_or_latin(self):
        self.assertEqual(audit.han_count("汉字 abc 123，。〇𠀀"), 4)

    def test_cli_json_and_invalid_archive(self):
        fixture(self.path)
        proc = subprocess.run([sys.executable, "-B", "-X", "utf8",
                               str(Path(audit.__file__)), str(self.path)],
                              capture_output=True, text=True, encoding="utf-8", check=True)
        self.assertEqual(json.loads(proc.stdout)["slide_count"], 1)
        self.path.write_bytes(b"not a ZIP")
        proc = subprocess.run([sys.executable, "-B", "-X", "utf8",
                               str(Path(audit.__file__)), str(self.path)],
                              capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("error", json.loads(proc.stdout))

    def test_duplicate_archive_members_rejected(self):
        fixture(self.path)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.path, "a") as zf:
                zf.writestr("ppt/presentation.xml", "<duplicate/>")
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            audit.audit_pptx(self.path)

    def test_resource_limits_rejected(self):
        fixture(self.path)
        limits = (("MAX_MEMBERS", 1, "member-count"),
                  ("MAX_UNCOMPRESSED_BYTES", 1, "uncompressed-size"),
                  ("MAX_XML_BYTES", 16, "XML member-size"),
                  ("MAX_TOTAL_XML_BYTES", 16, "Aggregate XML"))
        for constant, value, message in limits:
            with self.subTest(constant=constant), mock.patch.object(audit, constant, value):
                with self.assertRaisesRegex(ValueError, message):
                    audit.audit_pptx(self.path)
        compressed = Path(self.tmp.name) / "compressed.pptx"
        with zipfile.ZipFile(compressed, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("oversized.bin", b"0" * 100_000)
        with mock.patch.object(audit, "MAX_COMPRESSION_RATIO", 10):
            with self.assertRaisesRegex(ValueError, "compression-ratio"):
                audit.audit_pptx(compressed)

    def test_xml_declarations_rejected_in_utf8_and_utf16(self):
        for encoding in ("utf-8", "utf-16"):
            for declaration in ('<!DOCTYPE x [<!ENTITY e "bad">]>', '<!ENTITY e "bad">'):
                with self.subTest(encoding=encoding, declaration=declaration):
                    with zipfile.ZipFile(self.path, "w") as zf:
                        document = '<?xml version="1.0" encoding="%s"?>%s<x/>' % (
                            encoding, declaration)
                        zf.writestr("_rels/.rels", document.encode(encoding))
                    with self.assertRaisesRegex(ValueError, "DTD and ENTITY"):
                        audit.audit_pptx(self.path)


if __name__ == "__main__":
    unittest.main()
