"""Standard-library JSON output shared by the read-only command-line tools."""

import json
import sys


def write_json_utf8(value, stream=None):
    """Emit one JSON document; real pipes/files get UTF-8, regardless of locale.

    Bypass the text encoder rather than relying on -X utf8: inherited
    PYTHONIOENCODING can override that flag for standard streams. Text-only
    embedding streams such as StringIO receive Unicode; a restrictive text
    encoder gets equivalent ASCII-escaped JSON when no binary buffer exists.
    """
    stream = sys.stdout if stream is None else stream
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        stream.flush()
        # Escape filesystem surrogate code points instead of emitting invalid
        # UTF-8. Ordinary Chinese and emoji remain literal Unicode in the JSON.
        buffer.write(text.encode("utf-8", errors="backslashreplace"))
        buffer.flush()
    else:
        try:
            stream.write(text)
        except UnicodeEncodeError:
            stream.write(json.dumps(value, ensure_ascii=True, indent=2) + "\n")
        stream.flush()
