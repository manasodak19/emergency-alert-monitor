"""
Shared logging utility for the Emergency Alert Monitor.

Log format (locked — Phase 5's parser depends on this exact format):
    2026-09-26 14:20:12 INFO Alert request received

Writes to:
    - logs/app.log  (FileHandler, append mode)
    - Console/stdout (StreamHandler)
"""

import logging
import os

# ─── Build the logger once ───────────────────────────────────────────────────

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")

# Ensure the logs/ directory exists at import time
os.makedirs(LOG_DIR, exist_ok=True)

# Create a dedicated logger (avoids polluting the root logger)
logger = logging.getLogger("emergency_alert_monitor")
logger.setLevel(logging.DEBUG)

# Locked format: "YYYY-MM-DD HH:MM:SS LEVEL Message"
plain_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                                    datefmt="%Y-%m-%d %H:%M:%S")


# ─── Colored Console Formatter (Enhancement 3) ──────────────────────────────

class ColoredConsoleFormatter(logging.Formatter):
    """
    Custom formatter that adds ANSI color codes around the log level
    for console output only.  The log FILE stays plain text.

    Colors:
        INFO     → green   (\033[32m)
        WARNING  → yellow  (\033[33m)
        ERROR    → red     (\033[31m)
        CRITICAL → red     (\033[31m)
    """
    COLORS = {
        logging.INFO:     "\033[32m",   # green
        logging.WARNING:  "\033[33m",   # yellow
        logging.ERROR:    "\033[31m",   # red
        logging.CRITICAL: "\033[31m",   # red
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, "")
        formatted = super().format(record)
        if color:
            return f"{color}{formatted}{self.RESET}"
        return formatted


colored_formatter = ColoredConsoleFormatter("%(asctime)s %(levelname)s %(message)s",
                                            datefmt="%Y-%m-%d %H:%M:%S")


# ─── Handlers ────────────────────────────────────────────────────────────────

# File handler — append to logs/app.log (plain text, NO escape codes)
file_handler = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(plain_formatter)

# Console handler — mirrors to stdout WITH color
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(colored_formatter)

# Attach handlers (guard against duplicate handlers on reload)
if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


# ─── Public API ──────────────────────────────────────────────────────────────

def write_log(level: str, message: str, alert_id: str = None) -> None:
    """
    Write a single log entry.

    Parameters
    ----------
    level : str
        One of "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
        (case-insensitive).
    message : str
        The human-readable log message.
    alert_id : str, optional
        Short alert-ID tag (first 8 chars of a uuid4).  When provided,
        the message is prefixed with ``[alert_id=XXXXXXXX]`` so that
        every log line for one alert can be traced by searching the
        log file for that tag.
    """
    if alert_id is not None:
        message = f"[alert_id={alert_id}] {message}"

    level = level.upper().strip()
    log_func = {
        "DEBUG": logger.debug,
        "INFO": logger.info,
        "WARNING": logger.warning,
        "ERROR": logger.error,
        "CRITICAL": logger.critical,
    }.get(level, logger.info)

    log_func(message)
