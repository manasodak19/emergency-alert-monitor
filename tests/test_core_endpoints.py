"""
Tests for Core Endpoints (Home, Health, Alert validation, and Logging).

Verifies requirements:
- Home endpoint (GET /) returns 200 and expected status.
- Health endpoint (GET /health) returns 200 and service status.
- Valid alert submission (POST /alert) returns 201.
- Invalid alert submission (missing JSON or fields) returns 400.
- Log generation occurs as expected.

Uses temporary SQLite database and temporary log file to ensure full isolation.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config.config as config
import logging_system.logger as logger_mod
import routes.dashboard_routes as dash_mod
from app import app
from database.db import init_db, stop_failure_simulation


class TestCoreEndpoints(unittest.TestCase):
    """Test suite covering core application endpoints and validation."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp(prefix="eam_core_test_")
        cls._fake_db = os.path.join(cls._tmpdir, "alerts.db")
        cls._fake_log = os.path.join(cls._tmpdir, "app.log")

        # Patch config paths
        cls._orig_db_path = getattr(config, "DATABASE_PATH", None)
        config.DATABASE_PATH = cls._fake_db

        cls._orig_logger_log = logger_mod.LOG_FILE
        logger_mod.LOG_FILE = cls._fake_log

        cls._orig_dash_log = dash_mod._LOG_FILE
        dash_mod._LOG_FILE = cls._fake_log

        # Replace file handlers in logger
        cls._orig_file_handlers = [
            h for h in logger_mod.logger.handlers if isinstance(h, logger_mod.logging.FileHandler)
        ]
        for h in cls._orig_file_handlers:
            logger_mod.logger.removeHandler(h)

        cls._test_handler = logger_mod.logging.FileHandler(cls._fake_log, mode="a", encoding="utf-8")
        cls._test_handler.setFormatter(logger_mod.plain_formatter)
        logger_mod.logger.addHandler(cls._test_handler)

        init_db(cls._fake_db)
        app.config["TESTING"] = True
        cls.client = app.test_client()

    @classmethod
    def tearDownClass(cls):
        # Restore logger handlers
        logger_mod.logger.removeHandler(cls._test_handler)
        cls._test_handler.close()
        for h in cls._orig_file_handlers:
            logger_mod.logger.addHandler(h)

        if cls._orig_db_path is not None:
            config.DATABASE_PATH = cls._orig_db_path
        logger_mod.LOG_FILE = cls._orig_logger_log
        dash_mod._LOG_FILE = cls._orig_dash_log

        shutil.rmtree(cls._tmpdir, ignore_errors=True)

    def setUp(self):
        stop_failure_simulation()
        self.app_ctx = app.app_context()
        self.app_ctx.push()

    def tearDown(self):
        stop_failure_simulation()
        self.app_ctx.pop()

    def test_01_home_endpoint(self):
        """GET / confirms the service is online and returns 200."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "running")
        self.assertIn("online", data.get("message", "").lower())
        self.assertIn("timestamp", data)

    def test_02_health_endpoint(self):
        """GET /health confirms service health and returns 200."""
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("service"), "emergency-alert-monitor")
        self.assertIn("timestamp", data)

    def test_03_valid_alert_submission(self):
        """POST /alert with valid payload returns 201 and creates alert."""
        payload = {
            "type": "EARTHQUAKE",
            "message": "Tremor magnitude 4.2 detected",
            "location": "Fault Zone 9"
        }
        res = self.client.post("/alert", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertIn("alert_id", data)
        self.assertEqual(data.get("received", {}).get("type"), "EARTHQUAKE")
        self.assertEqual(data.get("received", {}).get("location"), "Fault Zone 9")

    def test_04_invalid_alert_empty_json(self):
        """POST /alert with empty or non-JSON payload returns 400."""
        res = self.client.post("/alert", data="not-json", content_type="text/plain")
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data.get("status"), "error")
        self.assertIn("valid json", data.get("message", "").lower())

    def test_05_invalid_alert_missing_required_fields(self):
        """POST /alert missing required fields returns 400."""
        res = self.client.post("/alert", json={"type": "FIRE"})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertEqual(data.get("status"), "error")
        self.assertIn("missing required fields", data.get("message", "").lower())

    def test_06_log_generation_on_requests(self):
        """Confirm requests write log lines to the log file."""
        initial_size = os.path.getsize(self._fake_log) if os.path.isfile(self._fake_log) else 0
        self.client.get("/health")
        new_size = os.path.getsize(self._fake_log)
        self.assertGreater(new_size, initial_size)

        with open(self._fake_log, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Health check requested", content)


if __name__ == "__main__":
    unittest.main()
