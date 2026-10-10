"""
Phase 5 — Log monitor.

Groups parsed log entries into configurable time windows and computes
operational metrics.  Can be used as:

  1. A library  — ``from logging_system.log_monitor import compute_metrics``
  2. A CLI tool — ``python -m logging_system.log_monitor``
  3. A Flask API — ``GET /metrics`` (registered in app.py)
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from collections import defaultdict

# Ensure the project root is on sys.path when running as a script
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from logging_system.log_parser import LogEntry, parse_log_file   # noqa: E402


# ─── Metrics dataclass ───────────────────────────────────────────────────────

class LogMetrics:
    """Aggregated metrics for a time window of log entries."""

    def __init__(self):
        # Counts by level
        self.total_entries: int = 0
        self.debug_count: int = 0
        self.info_count: int = 0
        self.warning_count: int = 0
        self.error_count: int = 0
        self.critical_count: int = 0

        # Error category counts (as required by Phase 5)
        self.database_error_count: int = 0
        self.broadcast_failure_count: int = 0
        self.notification_delay_count: int = 0
        self.http_500_count: int = 0
        self.sensor_error_count: int = 0
        self.queue_error_count: int = 0
        self.system_outage_count: int = 0

        # Response time stats
        self._response_times: List[int] = []

        # Unique alert/sim IDs seen
        self.unique_alert_ids: set = set()

        # Time window boundaries
        self.window_start: Optional[datetime] = None
        self.window_end: Optional[datetime] = None

    # ── Computed properties ──────────────────────────────────────────────

    @property
    def average_response_time(self) -> Optional[float]:
        """Average response time in ms, or None if no response times recorded."""
        if not self._response_times:
            return None
        return round(sum(self._response_times) / len(self._response_times), 1)

    @property
    def max_response_time(self) -> Optional[int]:
        """Maximum response time in ms."""
        return max(self._response_times) if self._response_times else None

    @property
    def min_response_time(self) -> Optional[int]:
        """Minimum response time in ms."""
        return min(self._response_times) if self._response_times else None

    @property
    def response_time_samples(self) -> int:
        """Number of entries that had a response_time value."""
        return len(self._response_times)

    @property
    def severity_score(self) -> int:
        """
        Weighted severity score:
          WARNING=1, ERROR=5, CRITICAL=20
        """
        return (self.warning_count * 1
                + self.error_count * 5
                + self.critical_count * 20)

    # ── Dict access & serialization ──────────────────────────────────────

    def to_dict(self) -> dict:
        """Return all metrics as a flat and structured dictionary."""
        return {
            # Flat keys matching Phase 5 specification
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "database_error_count": self.database_error_count,
            "broadcast_failure_count": self.broadcast_failure_count,
            "notification_delay_count": self.notification_delay_count,
            "http_500_count": self.http_500_count,
            "average_response_time": self.average_response_time,
            # Additional detail
            "window_start": self.window_start.isoformat() if self.window_start else None,
            "window_end": self.window_end.isoformat() if self.window_end else None,
            "total_entries": self.total_entries,
            "debug_count": self.debug_count,
            "info_count": self.info_count,
            "critical_count": self.critical_count,
            "sensor_error_count": self.sensor_error_count,
            "queue_error_count": self.queue_error_count,
            "system_outage_count": self.system_outage_count,
            "max_response_time": self.max_response_time,
            "min_response_time": self.min_response_time,
            "response_time_samples": self.response_time_samples,
            "severity_score": self.severity_score,
            "unique_alert_ids_count": len(self.unique_alert_ids),
        }

    def __getitem__(self, item: str):
        return self.to_dict()[item]

    def pretty_print(self) -> str:
        """Human-readable multi-line summary (ASCII-safe for all platforms)."""
        lines = []
        lines.append("=" * 62)
        lines.append("  [!] LOG MONITOR -- METRICS REPORT (PHASE 5) [!]")
        lines.append("=" * 62)

        if self.window_start and self.window_end:
            lines.append(f"  Window : {self.window_start}  ->  {self.window_end}")
        lines.append(f"  Total entries analysed : {self.total_entries}")
        lines.append("")

        lines.append("  --- Status & Counts ---")
        lines.append(f"    WARNING count         : {self.warning_count}")
        lines.append(f"    ERROR count           : {self.error_count}")
        lines.append(f"    CRITICAL count        : {self.critical_count}")
        lines.append(f"    INFO count            : {self.info_count}")
        lines.append(f"    DEBUG count           : {self.debug_count}")
        lines.append("")

        lines.append("  --- Error Types (Phase 5 Specifics) ---")
        lines.append(f"    Database errors       : {self.database_error_count}")
        lines.append(f"    Broadcast failures    : {self.broadcast_failure_count}")
        lines.append(f"    Notification delays   : {self.notification_delay_count}")
        lines.append(f"    HTTP 500 errors       : {self.http_500_count}")
        lines.append(f"    Sensor errors         : {self.sensor_error_count}")
        lines.append(f"    Queue errors          : {self.queue_error_count}")
        lines.append(f"    System outages        : {self.system_outage_count}")
        lines.append("")

        lines.append("  --- Performance ---")
        if self.response_time_samples > 0:
            lines.append(f"    Average response time : {self.average_response_time} ms")
            lines.append(f"    Min response time     : {self.min_response_time} ms")
            lines.append(f"    Max response time     : {self.max_response_time} ms")
            lines.append(f"    Samples with duration : {self.response_time_samples}")
        else:
            lines.append("    (no response-time data recorded)")
        lines.append("")

        lines.append(f"  Severity score  : {self.severity_score}")
        lines.append(f"  Unique alert IDs: {len(self.unique_alert_ids)}")
        lines.append("=" * 62)
        return "\n".join(lines)


# ─── Core computation ────────────────────────────────────────────────────────

def compute_metrics(
    entries: List[LogEntry],
    window_seconds: Optional[int] = None,
) -> LogMetrics:
    """
    Aggregate a list of LogEntry objects into a LogMetrics summary.

    Parameters
    ----------
    entries : list[LogEntry]
        Parsed log entries (from ``parse_log_file``).
    window_seconds : int, optional
        If given, only include entries from the last *N* seconds
        (relative to the most recent entry's timestamp).
        If ``None``, all entries are included.

    Returns
    -------
    LogMetrics
        Computed metrics for the selected window.
    """
    metrics = LogMetrics()

    if not entries:
        return metrics

    # Determine time window
    if window_seconds is not None and entries:
        latest = max(e.timestamp for e in entries)
        cutoff = latest - timedelta(seconds=window_seconds)
        filtered = [e for e in entries if e.timestamp >= cutoff]
    else:
        filtered = entries

    if not filtered:
        return metrics

    metrics.window_start = min(e.timestamp for e in filtered)
    metrics.window_end = max(e.timestamp for e in filtered)
    metrics.total_entries = len(filtered)

    for entry in filtered:
        # Level counts
        lvl = entry.level.upper()
        if lvl == "DEBUG":
            metrics.debug_count += 1
        elif lvl == "INFO":
            metrics.info_count += 1
        elif lvl == "WARNING":
            metrics.warning_count += 1
        elif lvl == "ERROR":
            metrics.error_count += 1
        elif lvl == "CRITICAL":
            metrics.critical_count += 1

        msg_lower = entry.message.lower()
        cat = entry.error_category or ""

        # Database errors
        if (cat == "database" or "database" in msg_lower or "db-primary" in msg_lower) and lvl in ("ERROR", "CRITICAL"):
            metrics.database_error_count += 1

        # Broadcast failures
        if (cat == "broadcast" or "broadcast" in msg_lower) and lvl in ("ERROR", "CRITICAL"):
            metrics.broadcast_failure_count += 1

        # Notification delay / latency issues (can be WARNING or ERROR)
        if (cat == "notification_delay" or "notification" in msg_lower or "latency" in msg_lower) and (
            lvl in ("WARNING", "ERROR", "CRITICAL") or "delay" in msg_lower or "latency" in msg_lower
        ):
            metrics.notification_delay_count += 1

        # HTTP 500 errors
        if cat == "http_500" or "500" in msg_lower or "internal server error" in msg_lower:
            if lvl in ("ERROR", "CRITICAL"):
                metrics.http_500_count += 1

        # Sensor errors
        if (cat == "sensor" or "sensor" in msg_lower) and lvl in ("WARNING", "ERROR", "CRITICAL"):
            metrics.sensor_error_count += 1

        # Queue errors
        if (cat == "queue" or "queue" in msg_lower) and lvl in ("WARNING", "ERROR", "CRITICAL"):
            metrics.queue_error_count += 1

        # System outage
        if (cat == "system_outage" or "outage" in msg_lower) and lvl in ("ERROR", "CRITICAL"):
            metrics.system_outage_count += 1

        # Response times
        if entry.response_time_ms is not None:
            metrics._response_times.append(entry.response_time_ms)

        # Unique alert/sim IDs
        if entry.alert_id:
            metrics.unique_alert_ids.add(entry.alert_id)

    return metrics


def compute_metrics_from_file(
    path: Optional[str] = None,
    window_seconds: Optional[int] = None,
) -> LogMetrics:
    """
    Convenience wrapper: parse the log file and compute metrics in one call.

    Parameters
    ----------
    path : str, optional
        Path to the log file (defaults to ``logs/app.log``).
    window_seconds : int, optional
        Time window filter (see ``compute_metrics``).
    """
    entries = parse_log_file(path)
    return compute_metrics(entries, window_seconds=window_seconds)


# ─── CLI entry point ─────────────────────────────────────────────────────────

def main():
    """
    Run as:  python -m logging_system.log_monitor [--window SECONDS]

    Parses logs/app.log, computes metrics, and prints a report.
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="Emergency Alert Monitor — Log metrics analyser"
    )
    parser.add_argument(
        "--window", "-w",
        type=int,
        default=None,
        help="Only analyse entries from the last N seconds (e.g. 60 for last minute, 3600 for last hour)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output metrics as JSON instead of formatted text",
    )
    parser.add_argument(
        "--file", "-f",
        type=str,
        default=None,
        help="Path to the log file (default: logs/app.log)",
    )
    args = parser.parse_args()

    metrics = compute_metrics_from_file(
        path=args.file,
        window_seconds=args.window,
    )

    if args.json:
        print(json.dumps(metrics.to_dict(), indent=2, default=str))
    else:
        print(metrics.pretty_print())


if __name__ == "__main__":
    main()
