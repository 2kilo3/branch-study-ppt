#!/usr/bin/env python3
"""Read-only, standard-library PPTX package audit; write JSON to stdout.

Example:
  python -B -X utf8 audit_pptx.py deck.pptx --min-font 20 --rate-min 230 --rate-max 250 \
      --video-seconds 120 --transition-seconds 45 > audit.json

Both video and transition seconds are TOTAL deck-wide allowances, not per slide.
Exit 0: audit completed (findings may exist). Exit 2: input/ZIP/XML/argument error.
This is structural triage, not a PowerPoint renderer or a visual QA substitute.
Below-minimum font findings are review candidates, not automatic defects;
intentional captions, credits, or template exceptions may be acceptable.
Archive limits: 20,000 members, 8 GiB total declared uncompressed size,
8 GiB actual input bytes (including the before/after fingerprint scan),
16 MiB per XML read, 128 MiB aggregate XML reads, compression ratio <= 1,000.
Duplicate members, encrypted entries, DTDs and entity declarations are rejected.
No archive extraction, network requests or embedded-content execution occurs.
Success and error JSON use UTF-8 bytes on stdout, independent of host locale.
"""

import argparse
import hashlib
import math
import os
import posixpath
import sys
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from pathlib import Path
from runtime_support import write_json_utf8
from plan_timing import plan_timing

EMU_PER_INCH = 914400
SHAPES = {"sp", "pic", "cxnSp", "graphicFrame"}
FONT_PROPERTIES = {"rPr", "defRPr", "endParaRPr"}
NOTES_EXCLUDED_PLACEHOLDERS = {"sldNum", "dt", "hdr", "ftr", "sldImg"}
MAX_MEMBERS = 20_000
MAX_INPUT_BYTES = 8 * 1024**3
MAX_UNCOMPRESSED_BYTES = 8 * 1024**3
MAX_XML_BYTES = 16 * 1024**2
MAX_TOTAL_XML_BYTES = 128 * 1024**2
MAX_COMPRESSION_RATIO = 1_000


def validate_archive(zf):
    """Bound declared resources before reading content; never extract members."""
    entries = zf.infolist()
    if len(entries) > MAX_MEMBERS:
        raise ValueError("Archive member-count limit exceeded")
    names = [entry.filename for entry in entries]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate archive member names are not allowed")
    if sum(entry.file_size for entry in entries) > MAX_UNCOMPRESSED_BYTES:
        raise ValueError("Archive total uncompressed-size limit exceeded")
    for entry in entries:
        if entry.flag_bits & 1:
            raise ValueError("Encrypted archive members are not supported")
        if entry.file_size / max(entry.compress_size, 1) > MAX_COMPRESSION_RATIO:
            raise ValueError("Archive compression-ratio limit exceeded")
        if entry.filename.lower().endswith((".xml", ".rels")) and entry.file_size > MAX_XML_BYTES:
            raise ValueError("Archive XML member-size limit exceeded")
    return set(names)


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def child(element, name):
    return next((e for e in element if local_name(e.tag) == name), None)


def descendants(element, name):
    return (e for e in element.iter() if local_name(e.tag) == name)


def namespaced_id(element):
    return next((value for key, value in element.attrib.items()
                 if key.endswith("}id")), None)


def relationship_source(rels_name):
    """Return source part name, or empty string for package relationships."""
    if rels_name == "_rels/.rels":
        return ""
    directory, filename = posixpath.split(rels_name)
    if posixpath.basename(directory) != "_rels" or not filename.endswith(".rels"):
        raise ValueError("Not an OPC relationship part: " + rels_name)
    return posixpath.join(posixpath.dirname(directory), filename[:-5])


def relationship_part(source):
    directory, filename = posixpath.split(source)
    return posixpath.join(directory, "_rels", filename + ".rels")


def resolve_target(source, target):
    """Resolve an internal OPC URI to a ZIP member; fragments are not members."""
    if not target:
        return None
    parsed = urllib.parse.urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None  # Absolute URLs require TargetMode="External".
    path = urllib.parse.unquote(parsed.path)
    if not path:
        return source or None
    if "\\" in path:
        return None
    result = posixpath.normpath(
        path.lstrip("/") if path.startswith("/") else
        posixpath.join(posixpath.dirname(source), path)
    )
    if result == ".." or result.startswith("../") or result in {".", ""}:
        return None
    return result


def han_count(text):
    """Count Han ideographs (including ideographic zero), not words/punctuation.

    Uses this Python runtime's Unicode database, reported in the result. Han
    characters are also used in Japanese/Korean: this is not language detection.
    """
    return sum(ch == "〇" or unicodedata.name(ch, "").startswith(
        ("CJK UNIFIED IDEOGRAPH-", "CJK COMPATIBILITY IDEOGRAPH-")) for ch in text)


def note_text(root):
    """Count body/custom notes text; exclude notes-page furniture and fields."""
    texts = []
    excluded_placeholders = 0
    excluded_fields = 0

    def walk(node):
        nonlocal excluded_placeholders, excluded_fields
        if local_name(node.tag) in SHAPES:
            placeholder = next(descendants(node, "ph"), None)
            if (placeholder is not None and
                    placeholder.get("type") in NOTES_EXCLUDED_PLACEHOLDERS):
                excluded_placeholders += 1
                return
        if (local_name(node.tag) == "fld" and
                node.get("type", "").lower() in {"slidenum", "slidenumber"}):
            excluded_fields += 1
            return
        if local_name(node.tag) == "t" and node.text:
            texts.append(node.text)
        for sub in node:
            walk(sub)

    # Only notes slide content, never inherited master labels or metadata.
    content = child(root, "cSld")
    if content is not None:
        walk(content)
    return "\n".join(texts), excluded_placeholders, excluded_fields


def shape_info(shape):
    nv = next(descendants(shape, "cNvPr"), None)
    return {
        "shape_type": local_name(shape.tag),
        "shape_id": nv.get("id") if nv is not None else None,
        "shape_name": nv.get("name") if nv is not None else None,
    }


def explicit_font_findings(root, minimum):
    parents = {sub: node for node in root.iter() for sub in node}
    findings = []
    explicit_count = 0
    for node in root.iter():
        if local_name(node.tag) not in FONT_PROPERTIES or "sz" not in node.attrib:
            continue
        size = int(node.get("sz")) / 100.0  # DrawingML sz is 1/100 point.
        explicit_count += 1
        if size >= minimum:
            continue
        ancestor = parents.get(node)
        context = ancestor
        while ancestor is not None and local_name(ancestor.tag) not in SHAPES:
            ancestor = parents.get(ancestor)
        text = "".join(e.text or "" for e in descendants(context, "t")) if context is not None else ""
        findings.append({
            **(shape_info(ancestor) if ancestor is not None else {}),
            "property": local_name(node.tag),
            "explicit_points": size,
            "text_excerpt": text[:120],
        })
    return explicit_count, findings


def bounds_findings(root, width, height):
    findings = []
    checked = 0
    skipped = Counter()
    content = child(root, "cSld")
    tree = child(content, "spTree") if content is not None else None
    if tree is None:
        return checked, findings, dict(skipped)
    for shape in tree:
        kind = local_name(shape.tag)
        if kind == "grpSp":
            skipped["groups"] += 1
            skipped["nested_shapes_in_groups"] += sum(
                local_name(e.tag) in SHAPES for e in shape.iter())
            continue
        if kind not in SHAPES:
            if kind not in {"nvGrpSpPr", "grpSpPr", "extLst"}:
                skipped["unsupported_top_level_elements"] += 1
            continue
        props = child(shape, "spPr")
        transform = child(shape, "xfrm") if kind == "graphicFrame" else (
            child(props, "xfrm") if props is not None else None)
        if transform is None:
            skipped["missing_explicit_transform"] += 1
            continue
        if int(transform.get("rot", "0")) % 21600000:
            skipped["rotated_shapes"] += 1
            continue
        off, ext = child(transform, "off"), child(transform, "ext")
        if off is None or ext is None:
            skipped["incomplete_transform"] += 1
            continue
        x, y, cx, cy = (int(off.get("x")), int(off.get("y")),
                         int(ext.get("cx")), int(ext.get("cy")))
        if cx < 0 or cy < 0:
            skipped["invalid_negative_extent"] += 1
            continue
        checked += 1
        edges = [edge for edge, outside in (
            ("left", x < 0), ("top", y < 0),
            ("right", x + cx > width), ("bottom", y + cy > height)) if outside]
        if edges:
            findings.append({**shape_info(shape), "outside_edges": edges,
                             "bounds_emu": {"x": x, "y": y, "width": cx, "height": cy}})
    return checked, findings, dict(skipped)


def _audit_open_pptx(filename, input_stream, min_font=20.0, rate_min=230.0, rate_max=250.0,
                     video_seconds=0.0, transition_seconds=45.0,
                     body_min_minutes=40.0, session_max_minutes=45.0):
    values = (min_font, rate_min, rate_max, video_seconds, transition_seconds)
    if not all(math.isfinite(n) for n in values):
        raise ValueError("All numeric settings must be finite")
    if min(min_font, rate_min, rate_max) <= 0 or rate_min > rate_max:
        raise ValueError("Font/rates must be positive, and rate-min <= rate-max")
    if min(video_seconds, transition_seconds) < 0:
        raise ValueError("Video and transition allowances cannot be negative")
    # Validate the new budget inputs even if the archive later fails to open.
    plan_timing(video_seconds, transition_seconds, rate_min, rate_max,
                body_min_minutes, session_max_minutes)

    with zipfile.ZipFile(input_stream) as zf:
        members = validate_archive(zf)
        xml_cache = {}
        xml_bytes_read = 0

        def read_xml(name):
            nonlocal xml_bytes_read
            if name not in xml_cache:
                info = zf.getinfo(name)
                if info.file_size > MAX_XML_BYTES:
                    raise ValueError("XML read-size limit exceeded")
                if xml_bytes_read + info.file_size > MAX_TOTAL_XML_BYTES:
                    raise ValueError("Aggregate XML read-size limit exceeded")
                with zf.open(info) as stream:
                    content = stream.read(MAX_XML_BYTES + 1)
                if len(content) > MAX_XML_BYTES:
                    raise ValueError("XML read-size limit exceeded")
                xml_bytes_read += len(content)
                # XML encodings UTF-8/16/32 all preserve these ASCII tokens
                # after NUL removal. No DTD/entity declaration is needed here.
                declaration_check = content.replace(b"\x00", b"").upper()
                if b"<!DOCTYPE" in declaration_check or b"<!ENTITY" in declaration_check:
                    raise ValueError("XML DTD and ENTITY declarations are not allowed")
                xml_cache[name] = ET.fromstring(content)
            return xml_cache[name]

        all_rels = {}
        broken = []
        internal = external = 0
        for name in sorted(members):
            if not name.endswith(".rels"):
                continue
            source = relationship_source(name)
            rels = []
            for rel in read_xml(name):
                if local_name(rel.tag) != "Relationship":
                    continue
                item = {"id": rel.get("Id"), "type": rel.get("Type", ""),
                        "target": rel.get("Target", ""),
                        "external": rel.get("TargetMode", "").lower() == "external"}
                item["resolved"] = None if item["external"] else resolve_target(source, item["target"])
                rels.append(item)
                if item["external"]:
                    external += 1
                else:
                    internal += 1
                    if item["resolved"] not in members:
                        broken.append({"relationship_part": name, "source_part": source,
                                       "relationship_id": item["id"], "target": item["target"],
                                       "resolved_target": item["resolved"],
                                       "reason": "missing_zip_member" if item["resolved"] else "invalid_internal_target"})
            all_rels[source] = rels

        office_doc = next((r for r in all_rels.get("", [])
                           if r["type"].endswith("/officeDocument") and not r["external"]), None)
        presentation_part = office_doc["resolved"] if office_doc else "ppt/presentation.xml"
        if presentation_part not in members:
            raise ValueError("Presentation part is missing: " + str(presentation_part))
        presentation = read_xml(presentation_part)
        size = child(presentation, "sldSz")
        if size is None:
            raise ValueError("Presentation has no slide dimensions")
        width, height = int(size.get("cx")), int(size.get("cy"))
        if width <= 0 or height <= 0:
            raise ValueError("Slide dimensions must be positive")
        slide_ids = child(presentation, "sldIdLst")
        ids = list(slide_ids) if slide_ids is not None else []
        ids = [i for i in ids if local_name(i.tag) == "sldId"]
        rel_by_id = {r["id"]: r for r in all_rels.get(presentation_part, [])}
        slides = []
        missing_slides = []
        font_total = bounds_total = note_total = 0
        for number, slide_id in enumerate(ids, 1):
            relation_id = namespaced_id(slide_id)
            relation = rel_by_id.get(relation_id)
            part = relation["resolved"] if relation and not relation["external"] else None
            if part not in members:
                missing_slides.append({"slide_number": number, "relationship_id": relation_id, "part": part})
                continue
            root = read_xml(part)
            font_count, fonts = explicit_font_findings(root, min_font)
            checked, bounds, skipped = bounds_findings(root, width, height)
            notes_rel = next((r for r in all_rels.get(part, [])
                              if r["type"].endswith("/notesSlide") and not r["external"]), None)
            notes_part = notes_rel["resolved"] if notes_rel else None
            notes_status = "no_notes_relationship" if notes_rel is None else "missing_notes_part"
            text, excluded_ph, excluded_fields = "", 0, 0
            if notes_part in members:
                text, excluded_ph, excluded_fields = note_text(read_xml(notes_part))
                notes_status = "read"
            count = han_count(text)
            note_total += count
            font_total += len(fonts)
            bounds_total += len(bounds)
            slides.append({
                "slide_number": number, "part": part, "hidden": root.get("show") in {"0", "false"},
                "notes": {"status": notes_status, "part": notes_part,
                          "chinese_character_count": count,
                          "excluded_placeholder_shapes": excluded_ph,
                          "excluded_slide_number_fields": excluded_fields},
                "estimated_narration_seconds": {"min": round(count / rate_max * 60, 2),
                                                "max": round(count / rate_min * 60, 2)},
                "explicit_font_size_properties_scanned": font_count,
                "explicit_font_sizes_below_minimum": fonts,
                "simple_shape_bounds_checked": checked,
                "out_of_canvas_simple_shapes": bounds,
                "bounds_checks_skipped": skipped,
            })
        speech_min, speech_max = note_total / rate_max * 60, note_total / rate_min * 60
        allowance = video_seconds + transition_seconds
        budget = plan_timing(video_seconds, transition_seconds, rate_min, rate_max,
                             body_min_minutes, session_max_minutes, note_total)
        budget["count_basis"] = {
            "unit": "notes_han_code_point_proxy_not_total_spoken_characters",
            "scope": "all_listed_slides_including_hidden",
            "hidden_slide_numbers": [s["slide_number"] for s in slides if s["hidden"]],
            "hidden_slide_notes_han_characters": sum(
                s["notes"]["chinese_character_count"] for s in slides if s["hidden"]),
            "slides_without_readable_notes": [s["slide_number"] for s in slides
                                              if s["notes"]["status"] != "read"],
            "missing_slide_numbers": [s["slide_number"] for s in missing_slides],
            "actual_spoken_characters": None,
            "actual_played_slide_sequence": "unknown",
        }
        budget["measurement_status"]["actual_spoken_characters"] = None
        named_ranges = budget["current_characters"]["estimated_breakdown"]
        return {
            "schema_version": 1,
            "file": str(filename), "read_only": True,
            "slide_count": len(ids), "slides_read": len(slides),
            "missing_slide_parts_or_relationships": missing_slides,
            "slide_dimensions": {"width_emu": width, "height_emu": height,
                                 "width_inches": round(width / EMU_PER_INCH, 6),
                                 "height_inches": round(height / EMU_PER_INCH, 6)},
            "summary": {"explicit_font_size_findings_below_minimum": font_total,
                        "out_of_canvas_simple_shape_findings": bounds_total,
                        "broken_internal_relationships": len(broken),
                        "total_notes_chinese_characters": note_total,
                        "slides_with_zero_counted_chinese_characters": [s["slide_number"] for s in slides
                                                                         if not s["notes"]["chinese_character_count"]]},
            "settings": {"minimum_explicit_font_points": min_font,
                         "rate_min_chinese_characters_per_minute": rate_min,
                         "rate_max_chinese_characters_per_minute": rate_max,
                         "video_seconds_total": video_seconds,
                         "transition_seconds_total": transition_seconds,
                         "body_minimum_minutes": body_min_minutes,
                         "session_maximum_minutes": session_max_minutes,
                         "reserve_seconds_total": transition_seconds},
            "timing_estimate": {
                "narration_seconds": {"min": round(speech_min, 2), "max": round(speech_max, 2)},
                "total_seconds": {"min": round(speech_min + allowance, 2), "max": round(speech_max + allowance, 2)},
                "total_minutes": {"min": round((speech_min + allowance) / 60, 2),
                                  "max": round((speech_max + allowance) / 60, 2)},
                "formula": "notes Han characters / speaking rate * 60 + total video seconds + total transition seconds",
                "speech_seconds": named_ranges["speech_seconds"],
                "speech_minutes": named_ranges["speech_minutes"],
                "body_seconds": named_ranges["body_seconds"],
                "body_minutes": named_ranges["body_minutes"],
                "session_seconds": named_ranges["session_seconds"],
                "session_minutes": named_ranges["session_minutes"],
                "legacy_total_fields_mean": "session including video and reserve, NOT body",
                "basis": "notes Han proxy across all listed slides including hidden; not measured elapsed time",
            },
            "timing_budget": budget,
            "relationships": {"internal_checked": internal, "external_not_checked": external,
                              "broken_internal_targets": broken},
            "unicode_database_version": unicodedata.unidata_version,
            "limitations": [
                "Fonts: scans explicit rPr/defRPr/endParaRPr sz attributes in slide XML only. Below-minimum findings are review candidates, not automatic defects; intentional caption or template exceptions may be acceptable. A finding may be an unused default or an empty paragraph. This is NOT an effective/inherited font-size guarantee: masters, layouts, themes, auto-fit, charts, SmartArt and rendered text are not resolved.",
                "Notes: counts Han ideograph code points using this Python Unicode database, plus 〇. This is not language detection or a word count. Punctuation, Latin text and Arabic digits do not count. Notes-page slide number/date/header/footer/slide-image placeholders and slide-number fields are excluded; body and custom notes text remain, including citations and stage directions.",
                "Timing: approximate narration from a Han-count proxy only, across all listed slides including hidden slides; actual played sequence and total spoken characters are unknown. Missing notes can underestimate duration; unspoken citations and stage directions can overestimate it. Speaking pace, pauses, non-Han speech, animations, questions and actual media duration are not measured. Video and transition/reserve inputs are deck-wide additions, assumed not to overlap narration. Reserve is inside the session ceiling. Legacy total_seconds/total_minutes mean session, not body. No PPTX playback timing is inferred; within_target is only a proxy estimate, not timing acceptance.",
                "Geometry: checks only explicit, unrotated, top-level shape/picture/connector/graphic-frame rectangles. Nested groups, rotations and inherited/missing transforms are skipped, not proved in-bounds. Text overflow, overlaps, crop, shadows, stroke width and animation movement require rendered visual review. Intentional bleed may trigger a finding.",
                "Relationships: checks existence of internal target ZIP members, resolving relative paths and percent-encoded paths. External URLs, target fragments, content-type correctness, relationship ID references and schema validity are not validated. Passing this audit does not establish PowerPoint playback compatibility.",
            ],
            "slides": slides,
        }


def fingerprint_stream(stream):
    """Hash the exact opened bytes without extracting or executing the package."""
    stream.seek(0)
    if os.fstat(stream.fileno()).st_size > MAX_INPUT_BYTES:
        raise ValueError("Archive input-byte limit exceeded")
    digest, size = hashlib.sha256(), 0
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
        if size > MAX_INPUT_BYTES:
            raise ValueError("Archive input-byte limit exceeded")
    stream.seek(0)
    return {"sha256": digest.hexdigest(), "size_bytes": size}


def audit_pptx(filename, min_font=20.0, rate_min=230.0, rate_max=250.0,
               video_seconds=0.0, transition_seconds=45.0,
               body_min_minutes=40.0, session_max_minutes=45.0):
    """Bind mechanical measurements to unchanged input bytes, not a filename."""
    with open(filename, "rb") as stream:
        before = fingerprint_stream(stream)
        result = _audit_open_pptx(filename, stream, min_font, rate_min, rate_max,
                                  video_seconds, transition_seconds,
                                  body_min_minutes, session_max_minutes)
        after = fingerprint_stream(stream)
        if before != after or not os.path.samestat(os.fstat(stream.fileno()), os.stat(filename)):
            raise ValueError("Candidate changed during audit; discard measurements and rerun on a frozen candidate")
    result["input_fingerprint"] = before
    return result


class JsonArgumentParser(argparse.ArgumentParser):
    """Keep argument failures in the same machine-readable JSON channel."""

    def error(self, message):
        raise ValueError(message)


def main(argv=None):
    parser = JsonArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--min-font", type=float, default=20, help="Review threshold for explicit slide font size, not an automatic defect rule (points; default: 20)")
    parser.add_argument("--rate-min", type=float, default=230, help="Slow narration rate in counted Chinese characters/minute")
    parser.add_argument("--rate-max", type=float, default=250, help="Fast narration rate in counted Chinese characters/minute")
    parser.add_argument("--video-seconds", type=float, default=0, help="TOTAL video allowance for the whole deck (default: 0)")
    parser.add_argument("--transition-seconds", type=float, default=45, help="TOTAL transition/pause allowance for the whole deck, NOT per slide (default: 45)")
    parser.add_argument("--body-min-minutes", type=float, default=40, help="Minimum speech + video duration (default: 40)")
    parser.add_argument("--session-max-minutes", type=float, default=45, help="Maximum speech + video + transition reserve duration (default: 45)")
    args = None
    try:
        args = parser.parse_args(argv)
        result = audit_pptx(args.pptx, args.min_font, args.rate_min, args.rate_max,
                            args.video_seconds, args.transition_seconds,
                            args.body_min_minutes, args.session_max_minutes)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, zipfile.BadZipFile,
            RuntimeError, NotImplementedError) as exc:
        write_json_utf8({"error": str(exc), "file": str(args.pptx) if args else None,
                         "read_only": True})
        return 2
    write_json_utf8(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
