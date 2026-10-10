"""
Phase 4 — Failure-simulation endpoints.

Safe endpoints that generate realistic WARNING / ERROR logs on demand
without breaking anything real. Useful for demonstrating the monitoring
dashboard, anomaly detection, and log-parsing pipeline.

All endpoints are POST-only and live under the /simulate prefix.
"""

# pyrefly: ignore [missing-import]
from flask import Blueprint, jsonify, request
import time
import random
import uuid
from datetime import datetime, timezone
from logging_system.logger import write_log
from config.config import DB_FAILURE_SIM_SECONDS
from database.db import start_failure_simulation, stop_failure_simulation

simulation_bp = Blueprint("simulation", __name__, url_prefix="/simulate")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _sim_id() -> str:
    """Short simulation-trace ID (first 8 chars of a uuid4)."""
    return str(uuid.uuid4())[:8]


def _random_delay(lo: float = 0.01, hi: float = 0.04) -> None:
    """Small sleep to make log timestamps realistic without slowing tests down."""
    time.sleep(random.uniform(lo, hi))


def _get_count(default: int = 10, max_limit: int = 50) -> int:
    """Extract optional count parameter from query string or JSON payload."""
    data = request.get_json(silent=True) or {}
    raw = request.args.get("count", data.get("count", default))
    try:
        val = int(raw)
        return max(1, min(val, max_limit))
    except (ValueError, TypeError):
        return default


# ─── POST /simulate/database-failure ─────────────────────────────────────────

@simulation_bp.route("/database-failure", methods=["POST"])
def simulate_database_failure():
    """
    Simulates a database connection failure.
    Produces multiple 'ERROR Database connection failed' log lines in a loop
    as required by Phase 4 and Phase 5 verification, and initiates timed failure simulation.
    """
    sim = _sim_id()
    start = time.time()
    count = _get_count(default=10)

    # Activate controlled database failure simulation
    start_failure_simulation(DB_FAILURE_SIM_SECONDS)

    write_log("INFO", f"Database health-check triggered (simulating {count} retries)", alert_id=sim)

    # Retry loop generating ERROR Database connection failed lines
    for attempt in range(1, count + 1):
        _random_delay()
        write_log(
            "ERROR",
            f"Database connection failed (attempt {attempt}/{count} host=db-primary port=5432: connection refused)",
            alert_id=sim,
        )

    _random_delay()
    write_log("CRITICAL", "Database connection failed — maximum retries exceeded, pool offline", alert_id=sim)

    elapsed_ms = int((time.time() - start) * 1000)
    write_log("ERROR", f"Database failure simulation completed (response_time={elapsed_ms}ms)", alert_id=sim)

    return jsonify({
        "status": "simulated",
        "simulation": "database-failure",
        "sim_id": sim,
        "database_errors_generated": count,
        "total_lines_generated": count + 3,
        "db_failure_active": True,
        "expires_in_seconds": DB_FAILURE_SIM_SECONDS,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }), 200


# ─── POST /simulate/database-recover ─────────────────────────────────────────

@simulation_bp.route("/database-recover", methods=["POST"])
def simulate_database_recover():
    """
    Recovers the database from simulated failure.
    Stops failure simulation and writes an INFO log.
    """
    stop_failure_simulation()
    write_log("INFO", "Database connection restored")

    return jsonify({
        "status": "recovered",
        "simulation": "database-recover",
        "db_failure_active": False,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }), 200


# ─── POST /simulate/broadcast-failure ────────────────────────────────────────

@simulation_bp.route("/broadcast-failure", methods=["POST"])
def simulate_broadcast_failure():
    """
    Simulates public-alert broadcast failures across alert channels.
    Produces ERROR lines for broadcast failure.
    """
    sim = _sim_id()
    start = time.time()
    count = _get_count(default=5)

    channels = ["SMS-gateway", "push-notification-service", "email-relay", "public-PA-system"]

    write_log("INFO", f"Broadcast dispatch initiated for {count} targets", alert_id=sim)

    for i in range(1, count + 1):
        _random_delay()
        target = channels[(i - 1) % len(channels)]
        write_log("WARNING", f"Broadcast to {target} experiencing high upstream queue depth", alert_id=sim)
        write_log("ERROR", f"Broadcast failure: channel {target} delivery failed (HTTP 503 service unavailable)", alert_id=sim)

    elapsed_ms = int((time.time() - start) * 1000)
    write_log("ERROR", f"Broadcast failure simulation completed (response_time={elapsed_ms}ms)", alert_id=sim)

    return jsonify({
        "status": "simulated",
        "simulation": "broadcast-failure",
        "sim_id": sim,
        "broadcast_failures_generated": count,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }), 200


# ─── POST /simulate/notification-delay ───────────────────────────────────────

@simulation_bp.route("/notification-delay", methods=["POST"])
def simulate_notification_delay():
    """
    Simulates severe delivery latency in the notification pipeline.
    Produces WARNING and ERROR lines for notification delays and SLA breaches.
    """
    sim = _sim_id()
    start = time.time()
    count = _get_count(default=5)

    write_log("INFO", f"Notification delivery stress simulation started ({count} batches)", alert_id=sim)

    for i in range(1, count + 1):
        _random_delay()
        latency = 3000 + i * 800
        write_log("WARNING", f"Notification delay detected: batch {i}/{count} latency {latency}ms", alert_id=sim)
        if latency >= 5000:
            write_log("ERROR", f"Notification delay SLA breach: batch {i}/{count} latency {latency}ms exceeds 5000ms SLA", alert_id=sim)

    elapsed_ms = int((time.time() - start) * 1000)
    write_log("WARNING", f"Notification delay simulation completed (response_time={elapsed_ms}ms)", alert_id=sim)

    return jsonify({
        "status": "simulated",
        "simulation": "notification-delay",
        "sim_id": sim,
        "batches_tested": count,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }), 200


# ─── POST /simulate/http-500 ─────────────────────────────────────────────────

@simulation_bp.route("/http-500", methods=["POST"])
def simulate_http_500():
    """
    Simulates internal server errors (HTTP 500) to populate http_500_count.
    """
    sim = _sim_id()
    start = time.time()
    count = _get_count(default=5)

    for i in range(1, count + 1):
        _random_delay()
        write_log("ERROR", f"HTTP 500 Internal Server Error encountered on worker thread {i}", alert_id=sim)

    elapsed_ms = int((time.time() - start) * 1000)
    write_log("ERROR", f"HTTP 500 simulation completed (response_time={elapsed_ms}ms)", alert_id=sim)

    return jsonify({
        "status": "simulated",
        "simulation": "http-500",
        "sim_id": sim,
        "http_500_errors_generated": count,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }), 200


# ─── POST /simulate/sensor-malfunction ───────────────────────────────────────

@simulation_bp.route("/sensor-malfunction", methods=["POST"])
def simulate_sensor_malfunction():
    """
    Simulates environmental sensors reporting out-of-range values.
    """
    sim = _sim_id()
    start = time.time()

    sensors = [
        ("TEMP-001", "temperature", "214 °C",  "normal range 15-45 °C"),
        ("HUM-003",  "humidity",    "-12 %",   "normal range 20-80 %"),
        ("SEIS-007", "seismic",     "NaN g",   "expected numeric value"),
        ("AIR-002",  "air-quality", "9999 AQI", "valid range 0-500"),
    ]

    write_log("INFO", "Sensor data ingestion cycle started", alert_id=sim)

    for sensor_id, sensor_type, bad_value, reason in sensors:
        _random_delay()
        write_log("WARNING", f"Sensor {sensor_id} ({sensor_type}) reported anomalous value: {bad_value} — {reason}", alert_id=sim)

    _random_delay()
    write_log("ERROR", "Sensor cluster reporting out-of-range values — data integrity alert raised", alert_id=sim)

    elapsed_ms = int((time.time() - start) * 1000)
    write_log("INFO", f"Sensor-malfunction simulation completed (response_time={elapsed_ms}ms)", alert_id=sim)

    return jsonify({
        "status": "simulated",
        "simulation": "sensor-malfunction",
        "sim_id": sim,
        "sensors_affected": [s[0] for s in sensors],
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }), 200


# ─── POST /simulate/full-outage ──────────────────────────────────────────────

@simulation_bp.route("/full-outage", methods=["POST"])
def simulate_full_outage():
    """
    Simulates a cascading full-system outage.
    """
    sim = _sim_id()
    start = time.time()

    write_log("INFO", "System health monitor detected anomaly — initiating diagnostics", alert_id=sim)
    _random_delay()

    write_log("WARNING", "Primary database not responding (ping timeout 3000ms)", alert_id=sim)
    _random_delay()
    write_log("ERROR", "Database failover to replica FAILED — replica is desynchronized", alert_id=sim)
    _random_delay()

    write_log("WARNING", "Message queue depth rising: 12450 pending messages", alert_id=sim)
    _random_delay()
    write_log("ERROR", "Message queue overflow — oldest messages being dropped", alert_id=sim)
    _random_delay()

    write_log("ERROR", "Broadcast subsystem unavailable — dependent routing table offline", alert_id=sim)
    _random_delay()

    write_log("CRITICAL", "FULL SYSTEM OUTAGE — all alert channels offline, manual intervention required", alert_id=sim)
    _random_delay()
    write_log("CRITICAL", "Incident auto-created: INC-2026-09-27-001 — paging on-call engineer", alert_id=sim)

    elapsed_ms = int((time.time() - start) * 1000)
    write_log("ERROR", f"Full-outage simulation completed (response_time={elapsed_ms}ms)", alert_id=sim)

    return jsonify({
        "status": "simulated",
        "simulation": "full-outage",
        "sim_id": sim,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }), 200
