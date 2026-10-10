"""
Phase 5 — Log parser.

Reads logs/app.log line by line and extracts structured fields from each
entry.  The locked log format is:

    2026-09-26 14:20:12 LEVEL [alert_id=XXXXXXXX] Message text (response_time=42ms)

All fields after LEVEL are optional — the parser gracefully handles lines
with or without an alert_id tag and/or a response_time suffix.
"""

import re
import os
from datetime import datetime
from typing import List, Optional


# ─── Compiled regex for the locked log format ────────────────────────────────

# Group 1: timestamp    "2026-09-26 14:20:12"
# Group 2: level        "INFO" | "WARNING" | "ERROR" | "CRITICAL" | "DEBUG"
# Group 3: rest         everything after the level (message + optional tags)
_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"  # timestamp
    r"\s+"
    r"(DEBUG|INFO|WARNING|ERROR|CRITICAL)"        # level
    r"\s+"
    r"(.+)$"                                      # rest of line
)

# Optional [alert_id=XXXXXXXX] prefix inside the message
_ALERT_ID_RE = re.compile(r"^\[alert_id=([a-f0-9]{8})\]\s*")

# Optional (response_time=NNms) suffix
_RESPONSE_TIME_RE = re.compile(r"\(response_time=(\d+)ms\)")

# ─── Error-type classification keywords ──────────────────────────────────────
_ERROR_CATEGORIES = [
    ("http_500",           ["500", "http 500", "internal server error"]),
    ("database",           ["database", "db-primary", "replica", "persist"]),
    ("broadcast",          ["broadcast", "channel", "sms-gateway", "push-notification",
                            "email-relay", "public-pa-system"]),
    ("notification_delay", ["notification", "sla breach", "sla limit", "latency",
                            "notification pipeline", "delivery delay"]),
    ("sensor",             ["sensor", "anomalous value", "out-of-range",
                            "data integrity"]),
    ("queue",              ["message queue", "queue depth", "queue overflow"]),
    ("system_outage",      ["full system outage", "system health monitor",
                            "incident auto-created"]),
]


# ─── Data class for a parsed log entry ───────────────────────────────────────

class LogEntry:
    """One parsed line from the log file."""

    __slots__ = (
        "timestamp", "level", "message", "alert_id",
        "response_time_ms", "error_category", "raw",
    )

    def __init__(
        self,
        timestamp: datetime,
        level: str,
        message: str,
        alert_id: Optional[str] = None,
        response_time_ms: Optional[int] = None,
        error_category: Optional[str] = None,
        raw: str = "",
    ):
        self.timestamp = timestamp
        self.level = level
        self.message = message
        self.alert_id = alert_id
        self.response_time_ms = response_time_ms
        self.error_category = error_category
        self.raw = raw

    @property
    def error_type(self) -> Optional[str]:
        """Alias for error_category to satisfy both naming conventions."""
        return self.error_category

    def __repr__(self) -> str:
        tag = f" [{self.alert_id}]" if self.alert_id else ""
        rt = f" ({self.response_time_ms}ms)" if self.response_time_ms is not None else ""
        cat = f" <{self.error_category}>" if self.error_category else ""
        return f"LogEntry({self.timestamp} {self.level}{tag}{cat}{rt})"


# ─── Classification helper ──────────────────────────────────────────────────

def classify_error_type(message: str) -> Optional[str]:
    """
    Return the error-category name if the message matches known failure types,
    otherwise None.
    """
    lower = message.lower()
    for category, keywords in _ERROR_CATEGORIES:
        if any(kw in lower for kw in keywords):
            return category
    return None


# ─── Public API ──────────────────────────────────────────────────────────────

def parse_line(line: str) -> Optional[LogEntry]:
    """
    Parse a single log line into a LogEntry.

    Returns None if the line does not match the expected format
    (blank lines, Flask's own debug output, etc.).
    """
    line = line.strip()
    if not line:
        return None

    match = _LINE_RE.match(line)
    if not match:
        return None

    timestamp_str, level, rest = match.groups()
    try:
        timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

    # Extract optional alert_id
    alert_id = None
    aid_match = _ALERT_ID_RE.match(rest)
    if aid_match:
        alert_id = aid_match.group(1)
        rest = rest[aid_match.end():]       # strip the tag from the message

    # Extract optional response_time
    response_time_ms = None
    rt_match = _RESPONSE_TIME_RE.search(rest)
    if rt_match:
        response_time_ms = int(rt_match.group(1))

    # Classify the error type
    error_category = classify_error_type(rest)

    return LogEntry(
        timestamp=timestamp,
        level=level,
        message=rest.strip(),
        alert_id=alert_id,
        response_time_ms=response_time_ms,
        error_category=error_category,
        raw=line,
    )


def parse_log_file(path: Optional[str] = None) -> List[LogEntry]:
    """
    Parse every line in the log file and return a list of LogEntry objects.

    Parameters
    ----------
    path : str, optional
        Absolute path to the log file.  Defaults to ``logs/app.log``
        relative to the project root.

    Returns
    -------
    list[LogEntry]
        Parsed entries in chronological order.  Lines that don't match
        the expected format are silently skipped.
    """
    if path is None:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(project_root, "logs", "app.log")

    if not os.path.isfile(path):
        return []

    entries: List[LogEntry] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            entry = parse_line(line)
            if entry is not None:
                entries.append(entry)

    return entries


# ─── Quick self-test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    entries = parse_log_file()
    print(f"Parsed {len(entries)} log entries from logs/app.log\n")
    for e in entries[-20:]:          # show last 20
        print(e)
