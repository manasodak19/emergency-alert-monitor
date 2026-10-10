"""
Phase 8 — SQLite Database & Controlled Failure Simulation.

Stores alerts and persisted anomaly history using standard library sqlite3.
Implements in-memory timed failure simulation that only blocks write alerts.
"""

import os
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime
from typing import Dict, List, Optional, Any

import config.config as config


# ─── Exception ───────────────────────────────────────────────────────────────

class DatabaseUnavailableError(Exception):
    """Raised when the database is unavailable or simulated offline."""
    pass


# ─── Failure Simulation State ────────────────────────────────────────────────

_failure_lock = threading.Lock()
_failure_expiry: float = 0.0


def start_failure_simulation(seconds: int) -> None:
    """Activate failure simulation for a duration in seconds."""
    global _failure_expiry
    with _failure_lock:
        _failure_expiry = time.time() + float(seconds)


def stop_failure_simulation() -> None:
    """Immediately deactivate failure simulation."""
    global _failure_expiry
    with _failure_lock:
        _failure_expiry = 0.0


def is_failure_simulated() -> bool:
    """Return True if simulated failure is currently active and unexpired."""
    with _failure_lock:
        return time.time() < _failure_expiry


def failure_seconds_remaining() -> int:
    """Return seconds remaining on active simulated failure, or 0 if expired."""
    with _failure_lock:
        rem = _failure_expiry - time.time()
        return max(0, int(round(rem))) if rem > 0 else 0


# ─── Connection & Helpers ───────────────────────────────────────────────────

def get_db_path(db_path: Optional[str] = None) -> str:
    """Get the active database file path (read dynamically from config if None)."""
    if db_path is not None:
        return db_path
    return getattr(config, "DATABASE_PATH", os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "alerts.db"
    ))


def init_db(db_path: Optional[str] = None) -> None:
    """
    Initialize SQLite tables if they do not already exist.
    Creates parent directories if necessary. Safe to call multiple times.
    """
    path = get_db_path(db_path)
    parent_dir = os.path.dirname(os.path.abspath(path))
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    with closing(sqlite3.connect(path, timeout=5)) as conn:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    location TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'processed'
                );
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS anomalies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    type TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    severity TEXT NOT NULL
                );
            """)


# ─── Alert Operations ───────────────────────────────────────────────────────

def save_alert(
    alert_id: str,
    alert_type: str,
    location: str,
    message: str,
    created_at: Optional[str] = None,
    status: str = "processed",
    db_path: Optional[str] = None,
) -> None:
    """
    Save a new alert to the SQLite database.
    Raises DatabaseUnavailableError if simulated failure is active.
    """
    if is_failure_simulated():
        raise DatabaseUnavailableError("Simulated database failure is active")

    if created_at is None:
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    path = get_db_path(db_path)
    with closing(sqlite3.connect(path, timeout=5)) as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO alerts (id, type, location, message, created_at, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (alert_id, alert_type, location, message, created_at, status),
            )


def get_recent_alerts(limit: int = 10, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch the latest stored alerts (ordered by rowid DESC)."""
    path = get_db_path(db_path)
    if not os.path.isfile(path):
        return []

    with closing(sqlite3.connect(path, timeout=5)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, type, location, message, created_at, status
            FROM alerts
            ORDER BY rowid DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    return [
        {
            "id": r[0],
            "type": r[1],
            "location": r[2],
            "message": r[3],
            "created_at": r[4],
            "status": r[5],
        }
        for r in rows
    ]


def count_alerts(db_path: Optional[str] = None) -> int:
    """Return total count of alerts in the database."""
    path = get_db_path(db_path)
    if not os.path.isfile(path):
        return 0

    with closing(sqlite3.connect(path, timeout=5)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM alerts")
        row = cursor.fetchone()
        return row[0] if row else 0


# ─── Anomaly Operations ─────────────────────────────────────────────────────

def save_anomaly(
    timestamp: str,
    anomaly_type: str,
    reason: str,
    severity: str,
    db_path: Optional[str] = None,
) -> int:
    """
    Persist an anomaly record to SQLite.
    Never blocked by the failure simulation flag.
    """
    path = get_db_path(db_path)
    with closing(sqlite3.connect(path, timeout=5)) as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO anomalies (timestamp, type, reason, severity)
                VALUES (?, ?, ?, ?)
                """,
                (timestamp, anomaly_type, reason, severity),
            )
            return cursor.lastrowid or 0


def get_recent_anomalies(limit: int = 50, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch the latest anomaly records (ordered by id DESC)."""
    path = get_db_path(db_path)
    if not os.path.isfile(path):
        return []

    with closing(sqlite3.connect(path, timeout=5)) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, timestamp, type, reason, severity
            FROM anomalies
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()

    return [
        {
            "id": r[0],
            "timestamp": r[1],
            "type": r[2],
            "reason": r[3],
            "severity": r[4],
        }
        for r in rows
    ]


def count_anomalies(db_path: Optional[str] = None) -> int:
    """Return total count of anomalies in the database."""
    path = get_db_path(db_path)
    if not os.path.isfile(path):
        return 0

    with closing(sqlite3.connect(path, timeout=5)) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM anomalies")
        row = cursor.fetchone()
        return row[0] if row else 0
