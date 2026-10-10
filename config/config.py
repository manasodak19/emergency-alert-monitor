"""
Phase 6 & 8 — Centralized configuration.

Thresholds for anomaly detection and runtime database settings.
"""

import os

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Database configuration
DATABASE_PATH = os.environ.get(
    "ALERT_DB_PATH",
    os.path.join(_PROJECT_ROOT, "data", "alerts.db"),
)
DB_FAILURE_SIM_SECONDS = 60

THRESHOLDS = {
    "database_error_count": {
        "normal_max": 5,
        "anomaly_min": 20,
    },
    "broadcast_failure_count": {
        "normal_max": 2,
        "anomaly_min": 10,
    },
    "notification_delay_count": {
        "normal_max": 5,
        "anomaly_min": 20,
    },
    "http_500_count": {
        "normal_max": 3,
        "anomaly_min": 15,
    },
    "sensor_error_count": {
        "normal_max": 2,
        "anomaly_min": 8,
    },
    "queue_error_count": {
        "normal_max": 3,
        "anomaly_min": 10,
    },
    "system_outage_count": {
        "normal_max": 0,
        "anomaly_min": 1,
    },
    "error_count": {
        "normal_max": 10,
        "anomaly_min": 50,
    },
    "warning_count": {
        "normal_max": 15,
        "anomaly_min": 60,
    },
    "critical_count": {
        "normal_max": 0,
        "anomaly_min": 3,
    },
}

# Human-readable reason strings keyed by metric name.
# Used by the rule detector to produce actionable alert messages.
ANOMALY_REASONS = {
    "database_error_count": "Unusual increase in database errors.",
    "broadcast_failure_count": "Unusual increase in broadcast failures.",
    "notification_delay_count": "Unusual increase in notification delays.",
    "http_500_count": "Unusual increase in HTTP 500 errors.",
    "sensor_error_count": "Unusual increase in sensor errors.",
    "queue_error_count": "Unusual increase in queue errors.",
    "system_outage_count": "System outage detected.",
    "error_count": "Overall error rate is abnormally high.",
    "warning_count": "Overall warning rate is abnormally high.",
    "critical_count": "Critical events detected.",
}
