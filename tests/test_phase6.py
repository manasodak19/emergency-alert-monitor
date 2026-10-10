"""
Tests for Phase 6 — Basic anomaly detection.

Verifies requirements:
10. Feed it normal metrics (e.g. database_error_count = 2) -> expect NORMAL.
11. Feed it abnormal metrics (e.g. database_error_count = 35) -> expect ANOMALY
    with reason "Unusual increase in database errors."
12. Confirm changing a value in config.py changes the detection threshold
    (proves it's configurable, not hardcoded).
"""

import os
import sys
import unittest
from unittest.mock import patch

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from anomaly_detection.rule_detector import (
    detect_anomalies,
    has_anomaly,
    anomalies_only,
    summary_report,
    AnomalyResult,
    STATUS_NORMAL,
    STATUS_WARNING,
    STATUS_ANOMALY,
)
from config.config import THRESHOLDS, ANOMALY_REASONS


# ─── Helpers ────────────────────────────────────────────────────────────────

def _make_metrics(**overrides) -> dict:
    """
    Build a fake metrics dict with every threshold-tracked metric set to 0
    by default, then apply overrides.
    """
    base = {key: 0 for key in THRESHOLDS}
    base.update(overrides)
    return base


class TestPhase6AnomalyDetection(unittest.TestCase):
    """Phase 6 — Rule-based anomaly detection tests."""

    # ── Requirement 10: Normal metrics → NORMAL ─────────────────────────

    def test_10_normal_metrics_produce_normal_status(self):
        """
        Req 10:
        Feed normal metrics (e.g. database_error_count = 2) and verify
        every metric is classified as NORMAL.
        """
        metrics = _make_metrics(
            database_error_count=2,
            broadcast_failure_count=1,
            notification_delay_count=3,
            http_500_count=0,
            error_count=4,
            warning_count=5,
        )

        results = detect_anomalies(metrics)

        # Every result should be NORMAL
        for r in results:
            self.assertEqual(
                r.status, STATUS_NORMAL,
                f"{r.metric}={r.value} should be NORMAL but got {r.status}",
            )

        # Specifically verify the database_error_count result
        db_result = next(r for r in results if r.metric == "database_error_count")
        self.assertEqual(db_result.status, STATUS_NORMAL)
        self.assertEqual(db_result.value, 2)
        self.assertIsNone(db_result.reason)

        # No anomalies should be present
        self.assertFalse(has_anomaly(results))
        self.assertEqual(len(anomalies_only(results)), 0)

        # Print the report for manual inspection
        print("\n" + summary_report(results))

    # ── Requirement 11: Abnormal metrics → ANOMALY with reason ──────────

    def test_11_abnormal_metrics_produce_anomaly_with_reason(self):
        """
        Req 11:
        Feed abnormal metrics (e.g. database_error_count = 35) and verify
        the result is ANOMALY with reason 'Unusual increase in database errors.'
        """
        metrics = _make_metrics(
            database_error_count=35,
            broadcast_failure_count=15,
            notification_delay_count=25,
        )

        results = detect_anomalies(metrics)

        # -- database_error_count --
        db_result = next(r for r in results if r.metric == "database_error_count")
        self.assertEqual(db_result.status, STATUS_ANOMALY)
        self.assertEqual(db_result.value, 35)
        self.assertEqual(db_result.reason, "Unusual increase in database errors.")

        # -- broadcast_failure_count --
        bc_result = next(r for r in results if r.metric == "broadcast_failure_count")
        self.assertEqual(bc_result.status, STATUS_ANOMALY)
        self.assertEqual(bc_result.reason, "Unusual increase in broadcast failures.")

        # -- notification_delay_count --
        nd_result = next(r for r in results if r.metric == "notification_delay_count")
        self.assertEqual(nd_result.status, STATUS_ANOMALY)
        self.assertEqual(nd_result.reason, "Unusual increase in notification delays.")

        # Overall check
        self.assertTrue(has_anomaly(results))
        self.assertGreaterEqual(len(anomalies_only(results)), 3)

        # Print the report
        print("\n" + summary_report(results))

    # ── Requirement 12: Configurable thresholds ─────────────────────────

    def test_12_changing_config_changes_detection_threshold(self):
        """
        Req 12:
        Prove that detection thresholds are configurable by passing
        custom thresholds and observing different classification.

        With default config, database_error_count = 10 falls in the
        WARNING band (normal_max=5, anomaly_min=20). After tightening
        the threshold so that anomaly_min=8, the same value should be
        classified as ANOMALY.
        """
        metrics = _make_metrics(database_error_count=10)

        # -- With default thresholds: 10 is between 5 and 20 → WARNING --
        results_default = detect_anomalies(metrics)
        db_default = next(r for r in results_default if r.metric == "database_error_count")
        self.assertEqual(
            db_default.status, STATUS_WARNING,
            f"Expected WARNING with default threshold, got {db_default.status}",
        )

        # -- With tightened thresholds: anomaly_min lowered to 8 → ANOMALY --
        custom_thresholds = {
            "database_error_count": {"normal_max": 3, "anomaly_min": 8},
        }
        results_custom = detect_anomalies(metrics, thresholds=custom_thresholds)
        db_custom = next(r for r in results_custom if r.metric == "database_error_count")
        self.assertEqual(
            db_custom.status, STATUS_ANOMALY,
            f"Expected ANOMALY with custom threshold, got {db_custom.status}",
        )

        # -- With relaxed thresholds: normal_max raised to 15 → NORMAL --
        relaxed_thresholds = {
            "database_error_count": {"normal_max": 15, "anomaly_min": 50},
        }
        results_relaxed = detect_anomalies(metrics, thresholds=relaxed_thresholds)
        db_relaxed = next(r for r in results_relaxed if r.metric == "database_error_count")
        self.assertEqual(
            db_relaxed.status, STATUS_NORMAL,
            f"Expected NORMAL with relaxed threshold, got {db_relaxed.status}",
        )

        print("\n[PASS] Same value (10) classified differently with different thresholds:")
        print(f"  Default  (normal_max=5,  anomaly_min=20) -> {db_default.status}")
        print(f"  Tight    (normal_max=3,  anomaly_min=8)  -> {db_custom.status}")
        print(f"  Relaxed  (normal_max=15, anomaly_min=50) -> {db_relaxed.status}")

    # ── Extra: WARNING band ─────────────────────────────────────────────

    def test_warning_band_produces_warning_status(self):
        """Values between normal_max and anomaly_min should produce WARNING."""
        metrics = _make_metrics(database_error_count=12)  # between 5 and 20

        results = detect_anomalies(metrics)
        db_result = next(r for r in results if r.metric == "database_error_count")

        self.assertEqual(db_result.status, STATUS_WARNING)
        self.assertEqual(db_result.severity, "medium")
        self.assertIn("elevated", db_result.reason)

    # ── Extra: Severity scaling ─────────────────────────────────────────

    def test_severity_scales_with_anomaly_magnitude(self):
        """Higher values above anomaly_min should produce higher severity."""
        # anomaly_min for database_error_count is 20
        # 1x–2x → medium, 2x–5x → high, >5x → critical

        cases = [
            (25,  "medium"),   # 25/20 = 1.25x
            (45,  "high"),     # 45/20 = 2.25x
            (120, "critical"), # 120/20 = 6x
        ]
        for value, expected_severity in cases:
            metrics = _make_metrics(database_error_count=value)
            results = detect_anomalies(metrics)
            db = next(r for r in results if r.metric == "database_error_count")
            self.assertEqual(
                db.severity, expected_severity,
                f"database_error_count={value} should be {expected_severity}, "
                f"got {db.severity}",
            )

    # ── Extra: Edge cases ───────────────────────────────────────────────

    def test_boundary_values(self):
        """Test exact boundary values: normal_max and anomaly_min."""
        # database_error_count: normal_max=5, anomaly_min=20

        # Exactly at normal_max → NORMAL
        metrics_at_max = _make_metrics(database_error_count=5)
        results = detect_anomalies(metrics_at_max)
        db = next(r for r in results if r.metric == "database_error_count")
        self.assertEqual(db.status, STATUS_NORMAL)

        # Exactly at anomaly_min → ANOMALY
        metrics_at_min = _make_metrics(database_error_count=20)
        results = detect_anomalies(metrics_at_min)
        db = next(r for r in results if r.metric == "database_error_count")
        self.assertEqual(db.status, STATUS_ANOMALY)

    def test_accepts_logmetrics_object(self):
        """detect_anomalies should accept a LogMetrics-like object with to_dict()."""
        from logging_system.log_monitor import LogMetrics

        m = LogMetrics()
        m.database_error_count = 2
        m.broadcast_failure_count = 0
        m.error_count = 3

        results = detect_anomalies(m)
        self.assertTrue(len(results) > 0)
        db = next(r for r in results if r.metric == "database_error_count")
        self.assertEqual(db.status, STATUS_NORMAL)


if __name__ == "__main__":
    unittest.main()
