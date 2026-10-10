"""
Tests for Phase 7 -- Admin Dashboard.

Uses a temporary log file (via monkeypatch) so tests never read or pollute
the real logs/app.log.

Requirements tested:
  1. GET /dashboard returns 200 and contains "Emergency Alert Monitor".
  2. GET /api/status returns 200, valid JSON, and all contract keys.
  3. Empty log -> status == "NORMAL" and database_error_count == 0.
  4. Log with many "Database connection failed" ERROR lines ->
     status == "ANOMALY" and anomaly_count >= 1.
  5. Repeated /api/status calls during one anomaly do NOT keep adding
     new anomaly entries.
  6. /dashboard and /api/status do not change the log file contents.
"""

import os
import sys
import json
import unittest
import tempfile
import shutil
from datetime import datetime, timedelta

# Ensure project root is importable
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _write_fake_log(path, lines):
    """Write a list of raw log lines to the given path."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _make_timestamp(offset_seconds=0):
    """Return a log-format timestamp string offset from 'now'."""
    dt = datetime.now() - timedelta(seconds=offset_seconds)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


class TestPhase7Dashboard(unittest.TestCase):
    """Phase 7 -- Admin Dashboard tests."""

    @classmethod
    def setUpClass(cls):
        """
        Create a temp directory for the fake log file and patch the
        relevant module-level paths so the dashboard reads from it.
        """
        cls._tmpdir = tempfile.mkdtemp(prefix="eam_test_")
        cls._fake_log = os.path.join(cls._tmpdir, "app.log")

        # Patch logger.LOG_FILE so nothing touches the real log
        import logging_system.logger as _logger_mod
        cls._orig_log_file = _logger_mod.LOG_FILE
        _logger_mod.LOG_FILE = cls._fake_log

        # Patch the dashboard route's log path
        import routes.dashboard_routes as _dash_mod
        cls._orig_dash_log = _dash_mod._LOG_FILE
        _dash_mod._LOG_FILE = cls._fake_log

        # Patch parse_log_file default path so compute_metrics_from_file
        # picks up our fake log
        import logging_system.log_parser as _parser_mod
        cls._orig_parser_root = None
        # We'll monkey-patch parse_log_file to default to our fake log
        cls._orig_parse_log_file = _parser_mod.parse_log_file

        def _patched_parse_log_file(path=None):
            if path is None:
                path = cls._fake_log
            return cls._orig_parse_log_file(path)

        _parser_mod.parse_log_file = _patched_parse_log_file

        # Reset anomaly state between class runs
        import routes.dashboard_routes as _d
        _d._anomaly_count = 0
        _d._anomaly_history.clear()
        _d._last_anomaly_metrics = set()
        _d._trend_data.clear()
        _d._trend_last_ts = 0.0

        # Import the Flask app AFTER patching
        from app import app
        cls.app = app
        cls.app.config["TESTING"] = True

    @classmethod
    def tearDownClass(cls):
        """Restore original paths and clean up temp dir."""
        import logging_system.logger as _logger_mod
        _logger_mod.LOG_FILE = cls._orig_log_file

        import routes.dashboard_routes as _dash_mod
        _dash_mod._LOG_FILE = cls._orig_dash_log

        import logging_system.log_parser as _parser_mod
        _parser_mod.parse_log_file = cls._orig_parse_log_file

        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def setUp(self):
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()
        # Reset anomaly state for each test
        import routes.dashboard_routes as _d
        _d._anomaly_count = 0
        _d._anomaly_history.clear()
        _d._last_anomaly_metrics = set()
        _d._trend_data.clear()
        _d._trend_last_ts = 0.0
        # Start with an empty fake log
        if os.path.isfile(self._fake_log):
            os.remove(self._fake_log)

    def tearDown(self):
        self.ctx.pop()

    # ── Test 1: GET /dashboard returns 200 + title ─────────────────────

    def test_01_dashboard_returns_200_with_title(self):
        """GET /dashboard returns 200 and contains 'Emergency Alert Monitor'."""
        res = self.client.get("/dashboard")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")
        self.assertIn("Emergency Alert Monitor", html)

    # ── Test 2: GET /api/status returns 200, valid JSON, all keys ──────

    def test_02_api_status_returns_valid_json_with_all_keys(self):
        """GET /api/status returns 200 + JSON with every contract key."""
        res = self.client.get("/api/status")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsNotNone(data)

        # Top-level keys
        for key in (
            "status", "reason", "severity", "window_seconds",
            "generated_at", "metrics", "thresholds",
            "anomaly_count", "anomalies", "recent_logs", "trend",
        ):
            self.assertIn(key, data, f"Missing top-level key: {key}")

        # Metric sub-keys
        metrics = data["metrics"]
        for mkey in (
            "total_requests", "error_count", "warning_count",
            "database_error_count", "broadcast_failure_count",
            "notification_delay_count", "http_500_count",
            "average_response_time_ms",
        ):
            self.assertIn(mkey, metrics, f"Missing metrics key: {mkey}")

    # ── Test 3: Empty log -> NORMAL, zeros ─────────────────────────────

    def test_03_empty_log_produces_normal_and_zeros(self):
        """With an empty (or missing) log: status == NORMAL, counts == 0."""
        # Ensure no log file
        if os.path.isfile(self._fake_log):
            os.remove(self._fake_log)

        res = self.client.get("/api/status")
        data = res.get_json()

        self.assertEqual(data["status"], "NORMAL")
        self.assertEqual(data["metrics"]["database_error_count"], 0)
        self.assertEqual(data["metrics"]["error_count"], 0)
        self.assertEqual(data["metrics"]["total_requests"], 0)

    # ── Test 4: Many DB errors -> ANOMALY with anomaly_count >= 1 ──────

    def test_04_database_errors_produce_anomaly(self):
        """Log with 25 'Database connection failed' ERROR lines -> ANOMALY."""
        ts = _make_timestamp
        lines = []
        for i in range(25):
            lines.append(
                f"{ts(i)} ERROR Database connection failed "
                f"(attempt {i+1}/25 host=db-primary port=5432: connection refused)"
            )
        _write_fake_log(self._fake_log, lines)

        res = self.client.get("/api/status")
        data = res.get_json()

        self.assertEqual(data["status"], "ANOMALY")
        self.assertGreaterEqual(data["anomaly_count"], 1)
        self.assertGreaterEqual(data["metrics"]["database_error_count"], 20)

    # ── Test 5: Repeated polls do NOT keep adding anomaly entries ───────

    def test_05_repeated_polls_do_not_duplicate_anomalies(self):
        """Calling /api/status 5 times during one anomaly adds only 1 entry."""
        ts = _make_timestamp
        lines = [
            f"{ts(i)} ERROR Database connection failed (attempt {i+1}/25)"
            for i in range(25)
        ]
        _write_fake_log(self._fake_log, lines)

        # First call detects the anomaly
        res1 = self.client.get("/api/status")
        d1 = res1.get_json()
        count_after_first = d1["anomaly_count"]
        self.assertGreaterEqual(count_after_first, 1)

        # Four more calls -- anomaly_count must NOT keep incrementing
        for _ in range(4):
            res = self.client.get("/api/status")
            d = res.get_json()
            self.assertEqual(
                d["anomaly_count"], count_after_first,
                "anomaly_count should not increase on repeated polls "
                "when the anomaly set hasn't changed."
            )

    # ── Test 6: Dashboard routes do NOT change the log file ────────────

    def test_06_dashboard_does_not_write_to_log(self):
        """GET /dashboard and /api/status must NOT modify the log file."""
        # Write a known log with a fixed size
        ts = _make_timestamp(0)
        lines = [f"{ts} INFO Alert request received"]
        _write_fake_log(self._fake_log, lines)
        size_before = os.path.getsize(self._fake_log)

        # Hit the dashboard and API several times
        for _ in range(5):
            self.client.get("/dashboard")
            self.client.get("/api/status")

        size_after = os.path.getsize(self._fake_log)
        self.assertEqual(
            size_before, size_after,
            f"Log file size changed from {size_before} to {size_after} -- "
            f"dashboard routes must NOT write to the log."
        )

    # ── Test 7: Static assets load ─────────────────────────────────────

    def test_07_static_assets_return_200(self):
        """CSS and JS static files load without 404."""
        for path in ("/dashboard/static/dashboard.css", "/dashboard/static/dashboard.js"):
            res = self.client.get(path)
            self.assertEqual(
                res.status_code, 200,
                f"Expected 200 for {path}, got {res.status_code}",
            )
            res.close()


if __name__ == "__main__":
    unittest.main()
