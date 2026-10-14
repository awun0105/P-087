"""Log redaction and excerpt extraction for worker failure diagnostics."""

import re
from pathlib import Path

# Match absolute filesystem paths with at least two segments (e.g. /home/user/app, /opt/bin/colmap)
_ABSOLUTE_PATH_RE = re.compile(r"/(?:[\w.-]+/)+[\w.-]+")


def redacted_excerpt(
    text: str,
    workspace: Path,
    *,
    max_lines: int = 40,
    max_bytes: int = 4096,
) -> list[str]:
    """Extract a sanitized tail excerpt of process logs safe for API and UI rendering.

    Replaces workspace paths with '<workspace>' and any other absolute system paths with '<path>',
    strips empty lines, and truncates to at most max_lines lines and max_bytes total bytes.
    """
    if not text:
        return []

    # 1. Redact workspace path (both resolved and verbatim)
    resolved_ws = str(workspace.resolve())
    raw_ws = str(workspace)
    sanitized = text.replace(resolved_ws, "<workspace>").replace(raw_ws, "<workspace>")

    # 2. Redact any remaining absolute paths with at least two segments
    sanitized = _ABSOLUTE_PATH_RE.sub("<path>", sanitized)

    # 3. Discard empty lines and keep the last max_lines
    lines = [line for line in sanitized.splitlines() if line.strip()]
    if not lines:
        return []

    lines = lines[-max_lines:]

    # 4. If total UTF-8 bytes exceed max_bytes, drop lines from the start until within budget
    def total_bytes(items: list[str]) -> int:
        return sum(len(line.encode("utf-8")) for line in items)

    while len(lines) > 1 and total_bytes(lines) > max_bytes:
        lines.pop(0)
    if total_bytes(lines) > max_bytes:
        # Một dòng đơn dài hơn ngân sách: giữ phần cuối của nó thay vì trả đoạn trích rỗng.
        lines = [lines[0].encode("utf-8")[-max_bytes:].decode("utf-8", errors="ignore")]

    return lines
