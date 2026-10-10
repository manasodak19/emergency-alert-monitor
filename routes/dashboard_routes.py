"""
Phase 7 -- Admin Dashboard routes.

Two endpoints:
  GET /dashboard   -> renders the single-page admin dashboard (HTML)
  GET /api/status  -> returns JSON with metrics, anomalies, logs, trend

CRITICAL: These routes NEVER call write_log() or write to logs/app.log.
          The dashboard polls every 3 s; writing would flood the log and
          corrupt the very metrics being measured.
"""

import os
import threading
import time as _time
from datetime import datetime
from collections import deque

# pyrefly: ignore [missing-import]
from flask import Blueprint, jsonify, render_template, request

# Phase 5 -- log parsing and metrics
from logging_system.log_parser import parse_line
from logging_system.log_monitor import compute_metrics_from_file

# Phase 6 -- anomaly detection (reuse, don't duplicate thresholds)
from anomaly_detection.rule_detector import (
    detect_anomalies,
    STATUS_NORMAL,
    STATUS_WARNING,
    STATUS_ANOMALY,
)
from config.config import THRESHOLDS

# Phase 8 -- SQLite persistence & failure detection
from database.db import (
    save_anomaly,
    get_recent_anomalies,
    count_anomalies,
    get_recent_alerts,
    count_alerts,
    is_failure_simulated,
    failure_seconds_remaining,
)

# ---------------------------------------------------------------------------
# Blueprint setup
# ---------------------------------------------------------------------------
# template_folder and static_folder are relative to THIS file's directory.
dashboard_bp = Blueprint(
    "dashboard",
    __name__,
    template_folder="../dashboard/templates",
    static_folder="../dashboard/static",
    static_url_path="/dashboard/static",
)

# ---------------------------------------------------------------------------
# In-memory anomaly history  (thread-safe, capped at 50, newest first)
# ---------------------------------------------------------------------------
_anomaly_lock = threading.Lock()
_anomaly_history: deque = deque(maxlen=50)   # newest at index 0
_anomaly_count: int = 0                      # total since app start
_last_anomaly_metrics: set = set()           # metric names of last ANOMALY set


def init_dashboard_state():
    """Load persisted anomaly records into in-memory history on startup."""
    global _anomaly_count
    with _anomaly_lock:
        _anomaly_history.clear()
        try:
            persisted = get_recent_anomalies(limit=50)
            # persisted rows are ordered id DESC (newest first);
            # append from oldest to newest with appendleft or append newest directly
            for a in reversed(persisted):
                _anomaly_history.appendleft({
                    "timestamp": a["timestamp"],
                    "type": a["type"],
                    "reason": a["reason"],
                    "severity": a["severity"],
                })
            _anomaly_count = count_anomalies()
        except Exception:
            pass


init_dashboard_state()

# ---------------------------------------------------------------------------
# In-memory trend buffer  (last 200 samples, at most one per 2 s)
# ---------------------------------------------------------------------------
_trend_lock = threading.Lock()
_trend_data: deque = deque(maxlen=200)
_trend_last_ts: float = 0.0                  # epoch of last sample

# ---------------------------------------------------------------------------
# Path to the log file (derived the same way logger.py does it)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LOG_FILE = os.path.join(_PROJECT_ROOT, "logs", "app.log")

# Metric display names for human-readable reasons
_METRIC_LABELS = {
    "database_error_count": "Database errors",
    "broadcast_failure_count": "Broadcast failures",
    "notification_delay_count": "Notification delays",
    "http_500_count": "HTTP 500 errors",
    "sensor_error_count": "Sensor errors",
    "queue_error_count": "Queue errors",
    "system_outage_count": "System outages",
    "error_count": "Total errors",
    "warning_count": "Total warnings",
    "critical_count": "Critical events",
}

# Impact message shown alongside anomaly alerts
_IMPACT_MSG = "Emergency notification delivery may be affected."

# How many seconds of logs the dashboard analyses by default
_DEFAULT_WINDOW = 60


# ---------------------------------------------------------------------------
# Helpers  (no logging, no side-effects on the log file)
# ---------------------------------------------------------------------------

def _read_tail(path: str, max_lines: int = 15) -> list:
    """
    Read the last *max_lines* lines from the log file.
    Uses a seek-from-end strategy so we never load a huge file into memory.
    Returns a list of dicts: {timestamp, level, message} newest first.
    """
    if not os.path.isfile(path):
        return []

    try:
        # Read approximately the last 8 KB -- enough for ~15 lines
        with open(path, "rb") as fh:
            try:
                fh.seek(-8192, 2)          # from end
            except OSError:
                fh.seek(0)                 # file is smaller than 8 KB
            tail_bytes = fh.read()

        lines = tail_bytes.decode("utf-8", errors="replace").splitlines()
        # Keep only the last max_lines log lines (skip blanks / junk)
        parsed = []
        for raw in lines:
            entry = parse_line(raw)
            if entry is not None:
                parsed.append({
                    "timestamp": entry.timestamp.strftime("%H:%M:%S"),
                    "level": entry.level,
                    "message": entry.message,
                })
        # newest first, limited
        return list(reversed(parsed[-max_lines:]))
    except Exception:
        return []


def _build_reason(results, metrics_dict):
    """
    Build a single human-readable reason string from the worst anomaly.
    Example: "Database errors: 35 (normal max 5)"
    """
    # Pick the worst (ANOMALY first, then WARNING)
    for status in (STATUS_ANOMALY, STATUS_WARNING):
        for r in results:
            if r.status == status:
                label = _METRIC_LABELS.get(r.metric, r.metric)
                bounds = THRESHOLDS.get(r.metric, {})
                normal_max = bounds.get("normal_max", "?")
                return f"{label}: {int(r.value)} (normal max {normal_max})"
    return "All systems operating normally."


def _overall_status(results):
    """Derive the single overall status from a list of AnomalyResults."""
    statuses = {r.status for r in results}
    if STATUS_ANOMALY in statuses:
        return STATUS_ANOMALY
    if STATUS_WARNING in statuses:
        return STATUS_WARNING
    return STATUS_NORMAL


def _overall_severity(results):
    """
    Derive the single worst severity.
    The rule_detector already uses: low, medium, high, critical.
    We map to uppercase for the JSON contract and add NONE for NORMAL.
    """
    order = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    worst = 0
    for r in results:
        if r.status in (STATUS_ANOMALY, STATUS_WARNING):
            worst = max(worst, order.get(r.severity, 0))
    return {0: "NONE", 1: "LOW", 2: "MEDIUM", 3: "HIGH", 4: "CRITICAL"}[worst]


def _count_alert_requests(path: str, window_seconds: int = None) -> int:
    """
    Count lines containing 'Alert request received' in the log file.
    Uses the same file and window logic as compute_metrics_from_file.
    This is a lightweight count; we reuse parse_log_file indirectly through
    the entries that compute_metrics already processed -- but to avoid
    re-parsing, we just grep the tail.  For accuracy we parse the full
    set of entries once inside _build_status_payload.
    """
    # This is actually called with pre-parsed entries -- see _build_status_payload
    return 0  # placeholder; the real count is done in _build_status_payload


def _build_status_payload():
    """
    Assemble the full /api/status JSON response.
    NEVER calls write_log.
    """
    global _anomaly_count, _last_anomaly_metrics

    now = datetime.now()

    # 1. Compute metrics for the default window
    metrics = compute_metrics_from_file(path=_LOG_FILE, window_seconds=_DEFAULT_WINDOW)
    metrics_dict = metrics.to_dict()

    # 2. Run anomaly detection (reuses config/config.py thresholds)
    results = detect_anomalies(metrics)

    status = _overall_status(results)
    severity = _overall_severity(results)
    reason = _build_reason(results, metrics_dict)

    # 3. Count "Alert request received" lines from parsed entries
    #    (re-parse is cheap for a 60 s window; we already did it above)
    from logging_system.log_parser import parse_log_file
    entries = parse_log_file(_LOG_FILE)
    # Apply the same window filter as compute_metrics_from_file
    if _DEFAULT_WINDOW is not None and entries:
        from datetime import timedelta
        latest = max(e.timestamp for e in entries)
        cutoff = latest - timedelta(seconds=_DEFAULT_WINDOW)
        windowed = [e for e in entries if e.timestamp >= cutoff]
    else:
        windowed = entries
    total_requests = sum(
        1 for e in windowed if "Alert request received" in e.message
    )

    # 4. Update anomaly history (only on NEW anomalies)
    anomaly_metrics_now = frozenset(
        r.metric for r in results if r.status == STATUS_ANOMALY
    )
    with _anomaly_lock:
        if status == STATUS_ANOMALY:
            if anomaly_metrics_now != _last_anomaly_metrics:
                # New anomaly or the set of triggered metrics changed
                _anomaly_count += 1
                # Build the anomaly entry
                worst = next(
                    (r for r in results if r.status == STATUS_ANOMALY), None
                )
                if worst:
                    label = _METRIC_LABELS.get(worst.metric, worst.metric)
                    bounds = THRESHOLDS.get(worst.metric, {})
                    normal_max = bounds.get("normal_max", "?")
                    detail = (
                        f"{label}: {int(worst.value)} "
                        f"(normal max {normal_max}). "
                        f"{_IMPACT_MSG}"
                    )
                    entry = {
                        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "type": label,
                        "reason": detail,
                        "severity": worst.severity.upper(),
                    }
                    _anomaly_history.appendleft(entry)
                    # Persist anomaly record to SQLite (write-through)
                    try:
                        save_anomaly(entry["timestamp"], entry["type"], entry["reason"], entry["severity"])
                    except Exception:
                        pass
                    # Print to console ONCE (not to log file)
                    print(
                        f"[ANOMALY] {entry['type']}: {entry['reason']} "
                        f"(severity={entry['severity']})"
                    )
        _last_anomaly_metrics = anomaly_metrics_now
        current_count = _anomaly_count
        # Grab the 10 newest anomaly entries for the response
        recent_anomalies = list(_anomaly_history)[:10]

    # 5. Update trend buffer (at most once per 2 seconds)
    with _trend_lock:
        global _trend_last_ts
        wall = _time.time()
        if wall - _trend_last_ts >= 2.0:
            _trend_data.append({
                "time": now.strftime("%H:%M:%S"),
                "errors": metrics_dict.get("error_count", 0),
            })
            _trend_last_ts = wall
        trend_snapshot = list(_trend_data)[-30:]  # last 30 samples

    # 6. Read recent log lines (tail, no full load)
    recent_logs = _read_tail(_LOG_FILE, max_lines=15)

    # 7. Query SQLite database status and recent alerts
    try:
        raw_alerts = get_recent_alerts(limit=10)
        recent_alerts = [
            {
                "created_at": a.get("created_at", ""),
                "id": str(a.get("id", ""))[:8],
                "type": a.get("type", ""),
                "location": a.get("location", ""),
                "status": a.get("status", "processed"),
            }
            for a in raw_alerts
        ]
        stored_alert_count = count_alerts()
    except Exception:
        recent_alerts = []
        stored_alert_count = 0

    db_status = "SIMULATED_FAILURE" if is_failure_simulated() else "ONLINE"
    db_failure_secs = failure_seconds_remaining()

    # 8. Build threshold subset for the response
    thresholds_out = {}
    for key in (
        "database_error_count",
        "broadcast_failure_count",
        "notification_delay_count",
        "http_500_count",
    ):
        if key in THRESHOLDS:
            thresholds_out[key] = THRESHOLDS[key]

    # 9. Assemble the payload
    return {
        "status": status,
        "reason": reason,
        "severity": severity,
        "window_seconds": _DEFAULT_WINDOW,
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "db_status": db_status,
        "db_failure_seconds_remaining": db_failure_secs,
        "stored_alert_count": stored_alert_count,
        "recent_alerts": recent_alerts,
        "metrics": {
            "total_requests": total_requests,
            "error_count": metrics_dict.get("error_count", 0),
            "warning_count": metrics_dict.get("warning_count", 0),
            "database_error_count": metrics_dict.get("database_error_count", 0),
            "broadcast_failure_count": metrics_dict.get("broadcast_failure_count", 0),
            "notification_delay_count": metrics_dict.get("notification_delay_count", 0),
            "http_500_count": metrics_dict.get("http_500_count", 0),
            "average_response_time_ms": metrics_dict.get("average_response_time") or 0,
        },
        "thresholds": thresholds_out,
        "anomaly_count": current_count,
        "anomalies": recent_anomalies,
        "recent_logs": recent_logs,
        "trend": trend_snapshot,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@dashboard_bp.route("/dashboard")
def dashboard():
    """Serve the admin dashboard HTML page with server-rendered initial data."""
    payload = _build_status_payload()
    return render_template("dashboard.html", data=payload)


@dashboard_bp.route("/api/status")
def api_status():
    """Return the full status JSON (polled every 3 s by the dashboard JS)."""
    return jsonify(_build_status_payload()), 200


@dashboard_bp.route("/api/alerts")
def api_alerts():
    """
    Return stored alerts as JSON.
    Query parameter: ?limit=20 (clamped between 1 and 100).
    NEVER calls write_log() and NEVER modifies logs/app.log.
    """
    limit_arg = request.args.get("limit", default=20, type=int)
    try:
        limit = max(1, min(int(limit_arg), 100))
    except (ValueError, TypeError):
        limit = 20

    try:
        alerts = get_recent_alerts(limit=limit)
        count = count_alerts()
    except Exception:
        alerts = []
        count = 0

    return jsonify({
        "count": count,
        "alerts": alerts,
    }), 200
