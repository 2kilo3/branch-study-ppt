#!/usr/bin/env python3
"""Read-only, standard-library timing budget; no PPTX is needed.

Example:
  python -B -X utf8 plan_timing.py --video-seconds 720 --reserve-seconds 120 \
      --current-characters 2273 > timing-plan.json

The body is speech + video. The session is body + reserve; reserve is INSIDE
the session ceiling. Defaults retain body >= 40 minutes and session <= 45
minutes over the WHOLE assumed speaking-rate range, 230--250 characters/minute.
Inputs describe a plan, not measured playback or a rehearsal.
Exit 0: calculation completed, possibly infeasible. Exit 2: invalid arguments.
Success/error JSON uses the shared UTF-8 writer, independent of host locale.
No files are read or written. Use -B to prevent imported-module bytecode caches.
"""

import argparse
import math
from fractions import Fraction

from runtime_support import write_json_utf8


def finite_number(value, name, positive=False):
    """Use exact decimal-rational arithmetic for ceil/floor boundary decisions."""
    try:
        valid = not isinstance(value, bool) and math.isfinite(float(value))
        result = Fraction(str(value)) if valid else None
    except (ValueError, TypeError, OverflowError, ZeroDivisionError):
        result = None
    if result is None:
        raise ValueError(name + " must be a finite number")
    if result < 0 or (positive and result == 0):
        raise ValueError(name + (" must be positive" if positive else " cannot be negative"))
    return result


def json_number(value, digits=None):
    """Never emit NaN/Infinity even when finite inputs produce huge results."""
    try:
        number = float(value)
    except OverflowError:
        raise ValueError("Calculated timing exceeds the finite numeric output range")
    if not math.isfinite(number):
        raise ValueError("Calculated timing exceeds the finite numeric output range")
    return round(number, digits) if digits is not None else number


def minute_range(low, high):
    return {"min": json_number(low, 4), "max": json_number(high, 4)}


def timing_ranges(characters, rate_min, rate_max, video_minutes, reserve_minutes):
    """Named, non-overlapping timing components for a specified character count."""
    speech_min, speech_max = Fraction(characters) / rate_max, Fraction(characters) / rate_min
    body_min, body_max = speech_min + video_minutes, speech_max + video_minutes
    session_min, session_max = body_min + reserve_minutes, body_max + reserve_minutes
    return {
        "speech_minutes": minute_range(speech_min, speech_max),
        "body_minutes": minute_range(body_min, body_max),
        "session_minutes": minute_range(session_min, session_max),
        "speech_seconds": minute_range(speech_min * 60, speech_max * 60),
        "body_seconds": minute_range(body_min * 60, body_max * 60),
        "session_seconds": minute_range(session_min * 60, session_max * 60),
    }


def plan_timing(video_seconds, reserve_seconds, rate_min=230, rate_max=250,
                body_min_minutes=40, session_max_minutes=45, current_characters=None):
    """Return a robust whole-rate-range budget, without editing any content.

    The minimum nonnegative integer count is ceil(rmax * (bodymin - video)).
    The maximum is floor(rmin * (sessionmax - video - reserve)).
    Width means endpoint difference, NOT the inclusive count of integer targets.
    """
    values = {
        "video_seconds": finite_number(video_seconds, "video-seconds"),
        "reserve_seconds": finite_number(reserve_seconds, "reserve-seconds"),
        "rate_min": finite_number(rate_min, "rate-min", positive=True),
        "rate_max": finite_number(rate_max, "rate-max", positive=True),
        "body_min_minutes": finite_number(body_min_minutes, "body-min-minutes", positive=True),
        "session_max_minutes": finite_number(session_max_minutes, "session-max-minutes", positive=True),
    }
    slow, fast = values["rate_min"], values["rate_max"]
    if slow > fast:
        raise ValueError("rate-min must be <= rate-max")
    if current_characters is not None:
        count = finite_number(current_characters, "current-characters")
        if count.denominator != 1:
            raise ValueError("current-characters must be a nonnegative integer")
        current_characters = int(count)
    video, reserve = values["video_seconds"] / 60, values["reserve_seconds"] / 60
    body_min, session_max = values["body_min_minutes"], values["session_max_minutes"]
    raw_lower = math.ceil(fast * (body_min - video))
    lower = max(0, raw_lower)  # Video alone may satisfy the body's lower bound.
    upper = math.floor(slow * (session_max - video - reserve))
    feasible = lower <= upper
    reasons = []
    if video + reserve > session_max:
        reasons.append("video_plus_reserve_exceeds_session_ceiling")
    if body_min + reserve > session_max:
        reasons.append("body_minimum_plus_reserve_exceeds_session_ceiling")
    if not feasible and not reasons:
        reasons.append("no_integer_character_count_satisfies_all_rate_endpoints")

    def breakdown(count):
        ranges = timing_ranges(count, slow, fast, video, reserve)
        return {
            "characters": count,
            **ranges,
            # Decisions use unrounded values; displayed times are rounded.
            "satisfies_body_minimum_at_fastest_rate": Fraction(count) / fast + video >= body_min,
            "satisfies_session_ceiling_at_slowest_rate": Fraction(count) / slow + video + reserve <= session_max,
        }

    planned = None
    if feasible:
        planned = {
            "minimum_characters": breakdown(lower),
            "midpoint_characters": breakdown((lower + upper) // 2),
            "maximum_characters": breakdown(upper),
        }
    current = {
        "count": current_characters,
        "status": "unknown",
        "deficit_to_minimum_characters": None,
        "surplus_above_maximum_characters": None,
        "headroom_to_maximum_characters": None,
        "estimated_breakdown": None,
    }
    if current_characters is not None:
        current.update({
            "status": ("no_feasible_interval" if not feasible else
                       "below_target" if current_characters < lower else
                       "above_target" if current_characters > upper else "within_target"),
            "deficit_to_minimum_characters": max(0, lower - current_characters),
            "surplus_above_maximum_characters": max(0, current_characters - upper),
            "headroom_to_maximum_characters": upper - current_characters,
            "estimated_breakdown": breakdown(current_characters),
        })
    return {
        "schema_version": 1,
        "read_only": True,
        "inputs": {name: json_number(value) for name, value in values.items()},
        "definitions": {
            "body": "speech + video",
            "session": "speech + video + reserve",
            "rate_requirement": "Both bounds must hold across the entire supplied rate range.",
            "character_unit": "Use the same character-count basis as the supplied speaking rates.",
        },
        "target_character_interval": {
            "min": lower, "max": upper, "feasible": feasible,
            "width_characters": max(0, upper - lower),
            "integer_target_count": max(0, upper - lower + 1),
            "gap_characters": max(0, lower - upper),
            "raw_formula_lower_bound": raw_lower,
        },
        "formulas": {
            "minimum": "max(0, ceil(rate_max * (body_min_minutes - video_seconds / 60)))",
            "maximum": "floor(rate_min * (session_max_minutes - video_seconds / 60 - reserve_seconds / 60))",
        },
        "infeasibility_reasons": reasons,
        "planned_breakdowns": planned,
        "current_characters": current,
        "measurement_status": {
            "video_duration": "input_only_not_verified",
            "speaking_rate": "assumed_not_rehearsed",
            "actual_speech_seconds": None,
            "actual_body_seconds": None,
            "actual_session_seconds": None,
            "actual_slide_sequence": "unknown",
        },
        "limitations": [
            "This is a planning calculation, not a rehearsal, playback test or content-quality judgment.",
            "Speech and video are assumed sequential, and the entire reserve is counted inside the session ceiling. Do not double-count pauses already included in a measured speaking rate.",
            "Counts and rates must use the same basis. PPTX Han-code-point counts exclude digits/Latin words but may include unspoken citations or stage directions; they are only a proxy for spoken content.",
            "A narrow or infeasible interval requires an explicit planning decision, not padding notes, silently narrowing an unmeasured rate range, moving reserve outside the ceiling, or claiming a revised requirement passed.",
        ],
    }


class JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError(message)


def main(argv=None):
    parser = JsonArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--video-seconds", type=float, required=True,
                        help="Total planned or independently measured playback seconds; use 0 explicitly for no video")
    parser.add_argument("--reserve-seconds", type=float, required=True,
                        help="Total switching/pause/interaction reserve INSIDE the session ceiling")
    parser.add_argument("--rate-min", type=float, default=230, help="Slow assumed speaking rate in characters/minute")
    parser.add_argument("--rate-max", type=float, default=250, help="Fast assumed speaking rate in characters/minute")
    parser.add_argument("--body-min-minutes", type=float, default=40, help="Minimum speech + video duration (default: 40)")
    parser.add_argument("--session-max-minutes", type=float, default=45, help="Maximum speech + video + reserve duration (default: 45)")
    parser.add_argument("--current-characters", type=int, help="Optional known count in the same units as the rates; otherwise unknown")
    try:
        args = parser.parse_args(argv)
        result = plan_timing(args.video_seconds, args.reserve_seconds, args.rate_min, args.rate_max,
                             args.body_min_minutes, args.session_max_minutes, args.current_characters)
    except (ValueError, TypeError, OverflowError) as exc:
        write_json_utf8({"error": str(exc), "read_only": True})
        return 2
    write_json_utf8(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
