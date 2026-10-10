# pyrefly: ignore [missing-import]
from flask import Flask, request, jsonify
import uuid
import time
import sqlite3
from datetime import datetime, timezone
from logging_system.logger import write_log
from logging_system.log_monitor import compute_metrics_from_file
from anomaly_detection.rule_detector import detect_anomalies, summary_report
from routes.simulation_routes import simulation_bp
from routes.dashboard_routes import dashboard_bp
from database.db import init_db, save_alert, DatabaseUnavailableError

app = Flask(__name__)

# ─── Initialize Database ─────────────────────────────────────────────────────
init_db()

# ─── Register Blueprints ─────────────────────────────────────────────────────
app.register_blueprint(simulation_bp)
app.register_blueprint(dashboard_bp)

# ─── Phase 2: Core Endpoints ────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    """Root endpoint — confirms the app is running."""
    write_log("INFO", "Root endpoint accessed")
    return jsonify({
        "status": "running",
        "message": "Emergency Alert Monitor is online",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }), 200


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    start = time.time()

    write_log("INFO", "Health check requested")

    elapsed_ms = int((time.time() - start) * 1000)
    write_log("INFO", f"Health check completed (response_time={elapsed_ms}ms)")

    return jsonify({
        "status": "healthy",
        "service": "emergency-alert-monitor",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }), 200


@app.route("/alert", methods=["POST"])
def alert():
    """
    Accept an alert and return a confirmation.
    Expected JSON body: { "type": str, "message": str, "location": str }
    """
    start = time.time()

    # Generate a full uuid4; the short tag is the first 8 chars
    full_id = str(uuid.uuid4())
    short_id = full_id[:8]

    write_log("INFO", "Alert request received", alert_id=short_id)

    data = request.get_json(silent=True)

    # Validate required fields
    if not data:
        elapsed_ms = int((time.time() - start) * 1000)
        write_log("WARNING", f"Alert request rejected - invalid JSON body (response_time={elapsed_ms}ms)", alert_id=short_id)
        return jsonify({
            "status": "error",
            "message": "Request body must be valid JSON"
        }), 400

    missing = [f for f in ("type", "message", "location") if f not in data]
    if missing:
        elapsed_ms = int((time.time() - start) * 1000)
        write_log("WARNING", f"Alert request rejected - missing fields: {', '.join(missing)} (response_time={elapsed_ms}ms)", alert_id=short_id)
        return jsonify({
            "status": "error",
            "message": f"Missing required fields: {', '.join(missing)}"
        }), 400

    # Save to database (real SQLite persistence)
    try:
        save_alert(full_id, data["type"], data["location"], data["message"])
    except (DatabaseUnavailableError, sqlite3.Error, Exception) as exc:
        elapsed_ms = int((time.time() - start) * 1000)
        write_log("ERROR", "Database connection failed", alert_id=short_id)
        write_log("ERROR", f"HTTP 500 Internal Server Error (response_time={elapsed_ms}ms)", alert_id=short_id)
        return jsonify({
            "status": "error",
            "message": "Alert could not be saved: database unavailable",
            "alert_id": full_id,
        }), 500

    write_log("INFO", "Alert processed successfully", alert_id=short_id)

    elapsed_ms = int((time.time() - start) * 1000)
    write_log("INFO", f"Notification sent successfully (response_time={elapsed_ms}ms)", alert_id=short_id)

    return jsonify({
        "status": "success",
        "message": "Alert received and processed",
        "alert_id": full_id,
        "received": {
            "type": data["type"],
            "message": data["message"],
            "location": data["location"]
        },
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }), 201


# ─── Phase 5: Metrics Endpoint ──────────────────────────────────────────────

@app.route("/metrics", methods=["GET"])
def get_metrics():
    """
    Returns computed log metrics.
    Supports optional ?window=<seconds> query parameter (e.g. ?window=60 or ?window=3600).
    """
    window = request.args.get("window", default=None, type=int)
    metrics = compute_metrics_from_file(window_seconds=window)
    return jsonify(metrics.to_dict()), 200


# ─── Phase 6: Anomaly Detection Endpoint ────────────────────────────────────

@app.route("/anomalies", methods=["GET"])
def get_anomalies():
    """
    Runs rule-based anomaly detection against current metrics.
    Returns a list of per-metric results with status, severity, and reason.
    Supports optional ?window=<seconds> query parameter.
    """
    window = request.args.get("window", default=None, type=int)
    metrics = compute_metrics_from_file(window_seconds=window)
    results = detect_anomalies(metrics)

    has_any_anomaly = any(r.status == "ANOMALY" for r in results)
    write_log(
        "WARNING" if has_any_anomaly else "INFO",
        f"Anomaly detection completed: {sum(1 for r in results if r.status == 'ANOMALY')} anomalies found"
    )

    return jsonify({
        "anomaly_detected": has_any_anomaly,
        "total_checks": len(results),
        "results": [r.to_dict() for r in results],
    }), 200


# ─── Startup Banner ─────────────────────────────────────────────────────────

BANNER = r"""
+======================================================+
|        EMERGENCY ALERT MONITOR                       |
|        Phase 6 -- Anomaly Detection Ready            |
|        Port : 5000  |  Debug : ON                    |
+======================================================+
"""

# ─── Run ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(BANNER)
    write_log("INFO", "Emergency Alert Monitor starting up")
    app.run(debug=True, host="0.0.0.0", port=5000)
