"""SSE event serialization.

Per W3C EventSource: each event is a sequence of fields ('event:', 'data:', etc.)
followed by an empty line. We use:

    event: <name>\n
    data: <single-line-json>\n
    \n
"""

from __future__ import annotations

import json
from typing import Any


def format_event(name: str, data: Any) -> str:
    """Format an SSE event with name + JSON data, raw UTF-8 (no \\u escapes)."""
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = payload.replace("\n", "\\n").replace("\r", "\\r")
    return f"event: {name}\ndata: {payload}\n\n"
