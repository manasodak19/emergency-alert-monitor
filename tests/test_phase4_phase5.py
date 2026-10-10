"""
Tests for Phase 4 (Failure Simulation) and Phase 5 (Log Monitoring).

Verifies requirements:
4. Call POST /simulate/database-failure.
5. Confirm logs/app.log now shows multiple ERROR Database connection failed lines.
6. Confirm normal /alert calls still work fine afterward (simulation doesn't break the app).
7. Generate a mix of normal logs and simulated failures (Phases 2–4).
8. Run the log monitor and print the computed metrics.
9. Confirm the counts match what you actually generated (e.g. 3 calls to database-failure
   generating 10 errors each -> database_error_count should read ~30).
"""

import os
import sys
import unittest
import tempfile
import json
from datetime import datetime

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import app
from logging_system.logger import LOG_FILE, write_log
from logging_system.log_parser import parse_log_file, parse_line, LogEntry
from logging_system.log_monitor import compute_metrics, compute_metrics_from_file, LogMetrics
from database.db import stop_failure_simulation


class TestPhase4And5(unittest.TestCase):

    def setUp(self):
        stop_failure_simulation()
        self.client = app.test_client()
        self.app_ctx = app.app_context()
        self.app_ctx.push()

    def tearDown(self):
        stop_failure_simulation()
        self.app_ctx.pop()

    def test_01_database_failure_simulation_and_log_verification(self):
        """
        Req 4 & 5:
        Call POST /simulate/database-failure and verify logs/app.log contains
        multiple 'ERROR Database connection failed' lines.
        """
        # Record initial count of DB errors in the log
        initial_metrics = compute_metrics_from_file()
        initial_db_errors = initial_metrics.database_error_count

        res = self.client.post("/simulate/database-failure?count=10")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["simulation"], "database-failure")
        self.assertEqual(data["database_errors_generated"], 10)

        # Parse the log file and check for multiple ERROR Database connection failed lines
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Database connection failed", content)
        db_error_occurrences = sum(1 for line in content.splitlines() if "ERROR" in line and "Database connection failed" in line)
        self.assertGreaterEqual(db_error_occurrences, 10, "Should have at least 10 ERROR Database connection failed lines")

        # Verify updated metrics reflect this call
        new_metrics = compute_metrics_from_file()
        self.assertGreaterEqual(new_metrics.database_error_count - initial_db_errors, 10)

    def test_02_alert_endpoint_still_works_after_simulation(self):
        """
        Req 6:
        Confirm normal /alert calls still work fine after simulations.
        """
        # Run a failure simulation first
        res_sim = self.client.post("/simulate/database-failure?count=5")
        self.assertEqual(res_sim.status_code, 200)

        # Recover from failure simulation so the system is ready to process alerts again
        res_rec = self.client.post("/simulate/database-recover")
        self.assertEqual(res_rec.status_code, 200)

        # Call normal /alert
        payload = {
            "type": "fire",
            "message": "Smoke detected on floor 4",
            "location": "Sector 7"
        }
        res_alert = self.client.post("/alert", json=payload)
        self.assertEqual(res_alert.status_code, 201)
        data = res_alert.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("alert_id", data)
        self.assertEqual(data["received"]["type"], "fire")

    def test_03_comprehensive_metrics_and_count_accuracy(self):
        """
        Req 7, 8, 9:
        Generate a known mix of normal logs and simulations, then verify:
        - 3 calls to database-failure with 10 errors each -> database_error_count increases by 30
        - broadcast_failure_count increases
        - notification_delay_count increases
        - http_500_count increases
        - warning_count and error_count are tracked
        - average_response_time is computed
        - /metrics endpoint returns consistent data
        """
        baseline_metrics = compute_metrics_from_file()
        base_db = baseline_metrics.database_error_count
        base_broadcast = baseline_metrics.broadcast_failure_count
        base_notification = baseline_metrics.notification_delay_count
        base_500 = baseline_metrics.http_500_count

        # 1. Normal traffic
        self.client.get("/health")
        self.client.post("/alert", json={"type": "flood", "message": "Water rising", "location": "Dock 3"})
        # 1 invalid alert (triggers WARNING)
        self.client.post("/alert", json={})

        # 2. 3 calls to database-failure generating 10 errors each (exactly 30 errors)
        for _ in range(3):
            res = self.client.post("/simulate/database-failure?count=10")
            self.assertEqual(res.status_code, 200)

        # 3. 2 calls to broadcast-failure generating 5 errors each (10 broadcast failures)
        for _ in range(2):
            res = self.client.post("/simulate/broadcast-failure?count=5")
            self.assertEqual(res.status_code, 200)

        # 4. 2 calls to notification-delay generating 5 delays each
        for _ in range(2):
            res = self.client.post("/simulate/notification-delay?count=5")
            self.assertEqual(res.status_code, 200)

        # 5. 1 call to http-500 generating 5 HTTP 500 errors
        res = self.client.post("/simulate/http-500?count=5")
        self.assertEqual(res.status_code, 200)

        # 6. Re-evaluate metrics
        updated_metrics = compute_metrics_from_file()

        # Database errors should have increased by at least 30
        db_diff = updated_metrics.database_error_count - base_db
        self.assertGreaterEqual(db_diff, 30, f"Expected at least 30 database errors, got difference of {db_diff}")

        # Broadcast failures should have increased by at least 10
        bc_diff = updated_metrics.broadcast_failure_count - base_broadcast
        self.assertGreaterEqual(bc_diff, 10, f"Expected at least 10 broadcast failures, got {bc_diff}")

        # Notification delays should have increased by at least 10
        nd_diff = updated_metrics.notification_delay_count - base_notification
        self.assertGreaterEqual(nd_diff, 10, f"Expected at least 10 notification delay entries, got {nd_diff}")

        # HTTP 500 should have increased by at least 5
        h500_diff = updated_metrics.http_500_count - base_500
        self.assertGreaterEqual(h500_diff, 5, f"Expected at least 5 HTTP 500 entries, got {h500_diff}")

        # Response time should be present
        self.assertIsNotNone(updated_metrics.average_response_time)
        self.assertGreaterEqual(updated_metrics.average_response_time, 0)

        # 7. Check the /metrics endpoint
        res_m = self.client.get("/metrics")
        self.assertEqual(res_m.status_code, 200)
        api_data = res_m.get_json()
        self.assertEqual(api_data["database_error_count"], updated_metrics.database_error_count)
        self.assertEqual(api_data["broadcast_failure_count"], updated_metrics.broadcast_failure_count)
        self.assertEqual(api_data["notification_delay_count"], updated_metrics.notification_delay_count)
        self.assertEqual(api_data["http_500_count"], updated_metrics.http_500_count)

        # Print the formatted report to stdout for test demonstration
        print("\n" + updated_metrics.pretty_print())


if __name__ == "__main__":
    unittest.main()
