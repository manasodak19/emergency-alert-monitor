"""
Phase 8 — Database & Failure Simulation Tests.

All tests use a temporary SQLite database and a temporary log file.
Never mutates data/alerts.db or logs/app.log.
"""

import os
import sys
import time
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from contextlib import closing
from unittest.mock import patch

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config.config as config
import logging_system.logger as logger_mod
import routes.dashboard_routes as dash_mod
import logging_system.log_parser as parser_mod

from app import app
from database.db import (
    init_db,
    save_alert,
    get_recent_alerts,
    count_alerts,
    save_anomaly,
    get_recent_anomalies,
    count_anomalies,
    start_failure_simulation,
    stop_failure_simulation,
    is_failure_simulated,
    failure_seconds_remaining,
    DatabaseUnavailableError,
)
from routes.dashboard_routes import init_dashboard_state


class TestDatabaseAndFailureSimulation(unittest.TestCase):
    """Test suite for Phase 8 SQLite persistence and failure simulation."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="eam_db_test_")
        cls._fake_db = os.path.join(cls._tmpdir, "alerts.db")
        cls._fake_log = os.path.join(cls._tmpdir, "app.log")

        # Patch DATABASE_PATH in config
        cls._orig_db_path = config.DATABASE_PATH
        config.DATABASE_PATH = cls._fake_db

        # Patch logger and dashboard log paths
        cls._orig_logger_log = logger_mod.LOG_FILE
        logger_mod.LOG_FILE = cls._fake_log

        cls._orig_dash_log = dash_mod._LOG_FILE
        dash_mod._LOG_FILE = cls._fake_log

        # Replace file handlers in logger so writes go to fake_log
        cls._orig_file_handlers = [
            h for h in logger_mod.logger.handlers if isinstance(h, logger_mod.logging.FileHandler)
        ]
        for h in cls._orig_file_handlers:
            logger_mod.logger.removeHandler(h)
            h.close()

        cls._test_file_handler = logger_mod.logging.FileHandler(cls._fake_log, mode="a", encoding="utf-8")
        cls._test_file_handler.setLevel(logger_mod.logging.DEBUG)
        cls._test_file_handler.setFormatter(logger_mod.plain_formatter)
        logger_mod.logger.addHandler(cls._test_file_handler)

        # Patch parser default path
        cls._orig_parse_log = parser_mod.parse_log_file

        def _patched_parse_log(path=None):
            if path is None:
                path = cls._fake_log
            return cls._orig_parse_log(path)

        parser_mod.parse_log_file = _patched_parse_log

        cls.app = app
        cls.app.config["TESTING"] = True

    @classmethod
    def tearDownClass(cls):
        config.DATABASE_PATH = cls._orig_db_path
        logger_mod.LOG_FILE = cls._orig_logger_log
        dash_mod._LOG_FILE = cls._orig_dash_log
        parser_mod.parse_log_file = cls._orig_parse_log

        # Restore original file handler
        if hasattr(cls, "_test_file_handler"):
            logger_mod.logger.removeHandler(cls._test_file_handler)
            cls._test_file_handler.close()

        for h in getattr(cls, "_orig_file_handlers", []):
            new_h = logger_mod.logging.FileHandler(cls._orig_logger_log, mode="a", encoding="utf-8")
            new_h.setLevel(logger_mod.logging.DEBUG)
            new_h.setFormatter(logger_mod.plain_formatter)
            logger_mod.logger.addHandler(new_h)

        stop_failure_simulation()
        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def setUp(self):
        stop_failure_simulation()
        # Initialize fresh DB tables
        if os.path.isfile(self._fake_db):
            os.remove(self._fake_db)
        init_db(self._fake_db)

        # Clear fake log file by truncating
        if hasattr(self, "_test_file_handler"):
            self._test_file_handler.flush()
        with open(self._fake_log, "w", encoding="utf-8") as f:
            f.write("")

        # Reset in-memory dashboard state
        dash_mod._anomaly_count = 0
        dash_mod._anomaly_history.clear()
        dash_mod._last_anomaly_metrics = set()
        dash_mod._trend_data.clear()
        dash_mod._trend_last_ts = 0.0

        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        stop_failure_simulation()
        self.ctx.pop()

    # ── Test 1: init_db() creates tables & is idempotent ───────────────
    def test_01_init_db_creates_tables_and_idempotent(self):
        """init_db() creates both tables and is safe to call twice."""
        # Calling second time should not throw
        init_db(self._fake_db)

        with closing(sqlite3.connect(self._fake_db)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r[0] for r in cursor.fetchall()}

        self.assertIn("alerts", tables)
        self.assertIn("anomalies", tables)

    # ── Test 2: Valid POST /alert returns 201 and stores row ───────────
    def test_02_valid_alert_persists_in_database(self):
        """Valid POST /alert returns 201 and exactly one row exists with returned alert_id."""
        payload = {
            "type": "weather",
            "message": "Flash flood warning in zone 4",
            "location": "River Valley"
        }
        res = self.client.post("/alert", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        alert_id = data["alert_id"]

        with closing(sqlite3.connect(self._fake_db)) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, type, location, message, status FROM alerts")
            rows = cursor.fetchall()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], alert_id)
        self.assertEqual(rows[0][1], "weather")
        self.assertEqual(rows[0][2], "River Valley")
        self.assertEqual(rows[0][3], "Flash flood warning in zone 4")
        self.assertEqual(rows[0][4], "processed")

    # ── Test 3: Invalid POST /alert returns 400 and stores nothing ─────
    def test_03_invalid_alert_stores_nothing(self):
        """Invalid POST /alert returns 400 and stores nothing in database."""
        res = self.client.post("/alert", json={"type": "missing_fields"})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(count_alerts(self._fake_db), 0)

    # ── Test 4: Failure simulation causes 500 & database error logs ────
    def test_04_failure_simulation_produces_500_and_logs(self):
        """
        After POST /simulate/database-failure, POST /alert returns 500 JSON,
        stores nothing, and log contains database-error line and HTTP 500 line.
        """
        res_sim = self.client.post("/simulate/database-failure?count=5")
        self.assertEqual(res_sim.status_code, 200)
        sim_data = res_sim.get_json()
        self.assertTrue(sim_data.get("db_failure_active"))

        # Attempt to save alert during failure
        payload = {"type": "fire", "message": "Smoke detected", "location": "Building A"}
        res_alert = self.client.post("/alert", json=payload)
        self.assertEqual(res_alert.status_code, 500)
        alert_data = res_alert.get_json()
        self.assertEqual(alert_data["status"], "error")
        self.assertIn("database unavailable", alert_data["message"])

        # DB must still have 0 alerts
        self.assertEqual(count_alerts(self._fake_db), 0)

        # Flush log handlers
        for h in logger_mod.logger.handlers:
            h.flush()

        # Check log file contents
        with open(self._fake_log, "r", encoding="utf-8") as f:
            log_content = f.read()

        self.assertIn("Database connection failed", log_content)
        self.assertIn("HTTP 500 Internal Server Error", log_content)

    # ── Test 5: Recover simulation restores alert processing ──────────
    def test_05_recover_simulation_restores_alert_processing(self):
        """After POST /simulate/database-recover, POST /alert returns 201 and stores row."""
        self.client.post("/simulate/database-failure?count=2")
        self.assertTrue(is_failure_simulated())

        res_rec = self.client.post("/simulate/database-recover")
        self.assertEqual(res_rec.status_code, 200)
        rec_data = res_rec.get_json()
        self.assertFalse(rec_data.get("db_failure_active"))
        self.assertFalse(is_failure_simulated())

        payload = {"type": "chemical", "message": "Spill contained", "location": "Lab 2"}
        res_alert = self.client.post("/alert", json=payload)
        self.assertEqual(res_alert.status_code, 201)
        self.assertEqual(count_alerts(self._fake_db), 1)

    # ── Test 6: Failure simulation expires automatically ──────────────
    def test_06_simulation_expires_automatically(self):
        """Simulation expires by itself and /alert works again."""
        start_failure_simulation(1)
        self.assertTrue(is_failure_simulated())

        time.sleep(1.1)
        self.assertFalse(is_failure_simulated())

        payload = {"type": "flood", "message": "Water receding", "location": "Basement"}
        res_alert = self.client.post("/alert", json=payload)
        self.assertEqual(res_alert.status_code, 201)
        self.assertEqual(count_alerts(self._fake_db), 1)

    # ── Test 7: Dashboard and APIs return 200 during simulation ────────
    def test_07_dashboard_apis_healthy_during_simulation(self):
        """During simulation, /dashboard, /api/status, /api/alerts return 200 with SIMULATED_FAILURE."""
        start_failure_simulation(60)

        res_dash = self.client.get("/dashboard")
        self.assertEqual(res_dash.status_code, 200)

        res_stat = self.client.get("/api/status")
        self.assertEqual(res_stat.status_code, 200)
        stat_data = res_stat.get_json()
        self.assertEqual(stat_data["db_status"], "SIMULATED_FAILURE")
        self.assertGreater(stat_data["db_failure_seconds_remaining"], 0)

        res_alerts = self.client.get("/api/alerts")
        self.assertEqual(res_alerts.status_code, 200)
        alerts_data = res_alerts.get_json()
        self.assertIn("count", alerts_data)
        self.assertIn("alerts", alerts_data)

    # ── Test 8: Anomaly persistence & restart recovery ────────────────
    def test_08_anomalies_persisted_and_restored(self):
        """Anomalies are persisted to SQLite; reloading dashboard restores history."""
        # Save directly to anomaly table
        save_anomaly("2026-10-08 12:00:00", "Database errors", "Database errors: 30", "HIGH", self._fake_db)
        self.assertEqual(count_anomalies(self._fake_db), 1)

        # Clear in-memory history and reload
        dash_mod._anomaly_history.clear()
        dash_mod._anomaly_count = 0
        init_dashboard_state()

        self.assertEqual(dash_mod._anomaly_count, 1)
        self.assertEqual(len(dash_mod._anomaly_history), 1)
        self.assertEqual(dash_mod._anomaly_history[0]["type"], "Database errors")

    # ── Test 9: Dashboard routes do not change log file ───────────────
    def test_09_dashboard_routes_do_not_modify_log(self):
        """GET /dashboard, /api/status, and /api/alerts never write to log file."""
        with open(self._fake_log, "w", encoding="utf-8") as f:
            f.write("2026-10-08 12:00:00 INFO Initial log line\n")

        size_before = os.path.getsize(self._fake_log)

        for _ in range(3):
            self.client.get("/dashboard")
            self.client.get("/api/status")
            self.client.get("/api/alerts")

        size_after = os.path.getsize(self._fake_log)
        self.assertEqual(size_before, size_after)

    # ── Test 10: SQL injection safety ─────────────────────────────────
    def test_10_sql_injection_safety(self):
        """SQL injection attempt in alert fields is safely parameterized."""
        injection_type = "x'); DROP TABLE alerts;--"
        payload = {
            "type": injection_type,
            "message": "Normal message",
            "location": "Secure Room"
        }
        res = self.client.post("/alert", json=payload)
        self.assertEqual(res.status_code, 201)

        # Verify alerts table still exists and row was stored as plain text
        alerts = get_recent_alerts(limit=5, db_path=self._fake_db)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["type"], injection_type)


if __name__ == "__main__":
    unittest.main()
