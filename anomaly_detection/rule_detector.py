"""
Phase 6 — Rule-based anomaly detector.

Consumes a LogMetrics object (from Phase 5) and compares each metric
against the configurable thresholds defined in ``config.config``.

Usage
-----
    from logging_system.log_monitor import compute_metrics_from_file
    from anomaly_detection.rule_detector import detect_anomalies

    metrics = compute_metrics_from_file()
    results = detect_anomalies(metrics)

    for r in results:
        print(r)

Each result is an ``AnomalyResult`` with:
  • metric   — the metric name that was evaluated
  • value    — the actual value observed
  • status   — "NORMAL", "WARNING", or "ANOMALY"
  • severity — "low", "medium", "high", or "critical"
  • reason   — human-readable explanation (only set when status != NORMAL)
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

# Ensure the project root is on sys.path so imports work when running
# this module standalone or from tests.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config.config import THRESHOLDS, ANOMALY_REASONS  # noqa: E402


# ─── Status / Severity constants ────────────────────────────────────────────

STATUS_NORMAL  = "NORMAL"
STATUS_WARNING = "WARNING"
STATUS_ANOMALY = "ANOMALY"

SEVERITY_LOW      = "low"
SEVERITY_MEDIUM   = "medium"
SEVERITY_HIGH     = "high"
SEVERITY_CRITICAL = "critical"


# ─── Result dataclass ───────────────────────────────────────────────────────

@dataclass
class AnomalyResult:
    """Detection result for a single metric."""

    metric: str
    value: float
    status: str                        # NORMAL | WARNING | ANOMALY
    severity: str  = SEVERITY_LOW      # low | medium | high | critical
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def __repr__(self) -> str:
        tag = f"[{self.status}]"
        if self.status == STATUS_ANOMALY:
            tag = f"[!! {self.status} !!]"
        elif self.status == STATUS_WARNING:
            tag = f"[~ {self.status} ~]"
        return (
            f"{tag}  {self.metric} = {self.value}  "
            f"(severity={self.severity})"
            + (f"  reason: {self.reason}" if self.reason else "")
        )


# ─── Severity calculator ────────────────────────────────────────────────────

def _compute_severity(value: float, anomaly_min: float) -> str:
    """
    Map the ratio ``value / anomaly_min`` to a severity label.

    • < 1×   → low       (below the anomaly threshold — WARNING band)
    • 1×–2×  → medium
    • 2×–5×  → high
    • > 5×   → critical
    """
    if anomaly_min == 0:
        # Any non-zero value against a zero-threshold is critical
        return SEVERITY_CRITICAL if value > 0 else SEVERITY_LOW

    ratio = value / anomaly_min
    if ratio < 1:
        return SEVERITY_LOW
    elif ratio < 2:
        return SEVERITY_MEDIUM
    elif ratio < 5:
        return SEVERITY_HIGH
    else:
        return SEVERITY_CRITICAL


# ─── Core detection function ────────────────────────────────────────────────

def detect_anomalies(
    metrics,
    thresholds: Optional[Dict] = None,
) -> List[AnomalyResult]:
    """
    Compare *metrics* against *thresholds* and return a list of results.

    Parameters
    ----------
    metrics : LogMetrics | dict
        A ``LogMetrics`` instance or a plain dict with the same keys.
        When a ``LogMetrics`` object is passed, ``to_dict()`` is called
        automatically.
    thresholds : dict, optional
        Override the default ``THRESHOLDS`` from ``config.config``.
        Useful for testing or per-run overrides.

    Returns
    -------
    list[AnomalyResult]
        One result per threshold-defined metric.
    """
    if thresholds is None:
        thresholds = THRESHOLDS

    # Accept either a LogMetrics instance or a raw dict
    if hasattr(metrics, "to_dict"):
        metrics_dict = metrics.to_dict()
    elif isinstance(metrics, dict):
        metrics_dict = metrics
    else:
        raise TypeError(
            f"metrics must be a LogMetrics instance or a dict, got {type(metrics).__name__}"
        )

    results: List[AnomalyResult] = []

    for metric_name, bounds in thresholds.items():
        value = metrics_dict.get(metric_name)
        if value is None:
            # Metric not present in the data — skip silently
            continue

        normal_max  = bounds["normal_max"]
        anomaly_min = bounds["anomaly_min"]

        if value <= normal_max:
            # ── NORMAL ───────────────────────────────────────────────
            results.append(AnomalyResult(
                metric=metric_name,
                value=value,
                status=STATUS_NORMAL,
                severity=SEVERITY_LOW,
                reason=None,
            ))

        elif value >= anomaly_min:
            # ── ANOMALY ──────────────────────────────────────────────
            reason = ANOMALY_REASONS.get(
                metric_name,
                f"{metric_name} exceeded anomaly threshold ({value} >= {anomaly_min}).",
            )
            results.append(AnomalyResult(
                metric=metric_name,
                value=value,
                status=STATUS_ANOMALY,
                severity=_compute_severity(value, anomaly_min),
                reason=reason,
            ))

        else:
            # ── WARNING band (between normal_max and anomaly_min) ────
            results.append(AnomalyResult(
                metric=metric_name,
                value=value,
                status=STATUS_WARNING,
                severity=SEVERITY_MEDIUM,
                reason=f"{metric_name} is elevated ({value}); "
                       f"above normal ({normal_max}) but below anomaly ({anomaly_min}).",
            ))

    return results


# ─── Convenience helpers ────────────────────────────────────────────────────

def has_anomaly(results: List[AnomalyResult]) -> bool:
    """Return True if any result has ANOMALY status."""
    return any(r.status == STATUS_ANOMALY for r in results)


def anomalies_only(results: List[AnomalyResult]) -> List[AnomalyResult]:
    """Filter the results list to only ANOMALY entries."""
    return [r for r in results if r.status == STATUS_ANOMALY]


def summary_report(results: List[AnomalyResult]) -> str:
    """Pretty-print all detection results as an ASCII report."""
    lines = []
    lines.append("=" * 62)
    lines.append("  [!] ANOMALY DETECTION REPORT (PHASE 6) [!]")
    lines.append("=" * 62)

    normal  = [r for r in results if r.status == STATUS_NORMAL]
    warning = [r for r in results if r.status == STATUS_WARNING]
    anomaly = [r for r in results if r.status == STATUS_ANOMALY]

    if anomaly:
        lines.append("")
        lines.append(f"  --- ANOMALIES ({len(anomaly)}) ---")
        for r in anomaly:
            lines.append(f"    [!!] {r.metric} = {r.value}  "
                         f"(severity={r.severity})")
            lines.append(f"         reason: {r.reason}")

    if warning:
        lines.append("")
        lines.append(f"  --- WARNINGS ({len(warning)}) ---")
        for r in warning:
            lines.append(f"    [~]  {r.metric} = {r.value}  "
                         f"(severity={r.severity})")
            lines.append(f"         reason: {r.reason}")

    if normal:
        lines.append("")
        lines.append(f"  --- NORMAL ({len(normal)}) ---")
        for r in normal:
            lines.append(f"    [ok] {r.metric} = {r.value}")

    lines.append("")
    lines.append(f"  Total checks: {len(results)}  |  "
                 f"Anomalies: {len(anomaly)}  |  "
                 f"Warnings: {len(warning)}  |  "
                 f"Normal: {len(normal)}")
    lines.append("=" * 62)
    return "\n".join(lines)


# ─── CLI entry point ────────────────────────────────────────────────────────

def main():
    """
    Run as:  python -m anomaly_detection.rule_detector [--window SECONDS]
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Emergency Alert Monitor — Rule-based anomaly detector"
    )
    parser.add_argument(
        "--window", "-w",
        type=int,
        default=None,
        help="Only analyse entries from the last N seconds",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of formatted text",
    )
    args = parser.parse_args()

    from logging_system.log_monitor import compute_metrics_from_file
    import json as _json

    metrics = compute_metrics_from_file(window_seconds=args.window)
    results = detect_anomalies(metrics)

    if args.json:
        print(_json.dumps([r.to_dict() for r in results], indent=2))
    else:
        print(summary_report(results))


if __name__ == "__main__":
    main()
