#!/usr/bin/env python3
"""Emit one per-cell result JSON line from R_* environment variables.

Used by run_sweep.sh to serialize a cell's outcome without bash quoting/rounding
hazards. Numeric metrics that couldn't be measured arrive as "n/a" and become
JSON null. Output is a single line, appended to results.jsonl.
"""
from __future__ import annotations

import json
import math
import os


def num(value):
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("", "n/a", "nan", "none"):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def as_int(value, default=None):
    try:
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return default


g = os.environ.get
def json_value(value):
    """Return an optional string value without inventing missing evidence."""
    return value if value not in (None, "", "n/a", "null") else None


def json_object(name):
    try:
        value = json.loads(g(name, ""))
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def csv_list(name):
    return [x for x in g(name, "").split(",") if x]


result = {
    "schema_version": 2,
    "cell_id": json_value(g("R_CELL_ID")),
    "template": g("R_TEMPLATE"),
    "topology": g("R_TOPOLOGY") or "bridge",
    "scenario": g("R_SCENARIO"),
    "rmw": g("R_RMW"),
    "requested_rmws": csv_list("R_REQUESTED_RMWS"),
    "rmw_impl": g("R_RMW_IMPL"),
    "workload": g("R_WORKLOAD"),
    "engine": g("R_ENGINE"),
    "scale": as_int(g("R_SCALE")),
    "scale_source": g("R_SCALE_SOURCE") or None,
    "duration": as_int(g("R_DURATION")),
    "netem": g("R_NETEM"),
    "run_id": g("R_RUN_ID"),
    "started": json_value(g("R_STARTED")),
    "ended": json_value(g("R_ENDED")),
    "status": g("R_STATUS") or "failed",
    "reasons": [r for r in g("R_REASONS", "").split(",") if r],
    "measurement_window": json_object("R_MEASUREMENT_WINDOW"),
    "artifacts": json_object("R_ARTIFACTS"),
    "provenance": json_object("R_PROVENANCE"),
    "metric_availability": json_object("R_METRIC_AVAILABILITY"),
    "observations": json_object("R_OBSERVATIONS"),
    "cpu_measurement": json_object("R_CPU_MEASUREMENT"),
    "template_a_metrics": json_object("R_TEMPLATE_A_METRICS"),
    "metrics": {
        "sensor_drop_pct": num(g("R_SENSOR_DROP")),
        "sensor_estimated_delivery_shortfall_pct": num(g("R_SENSOR_SHORTFALL")),
        "sensor_received_expected_ratio": num(g("R_SENSOR_RATIO")),
        "control_p99_ms": num(g("R_CONTROL_P99")),
        "control_arrival_gap_p99_ms": num(g("R_CONTROL_GAP_P99")),
        "state_freshness_ms": num(g("R_STATE_FRESH")),
        "state_arrival_gap_p95_ms": num(g("R_STATE_GAP_P95")),
        "control_max_silence_ms": num(g("R_CONTROL_SILENCE")),
        "state_max_silence_ms": num(g("R_STATE_SILENCE")),
        "throughput_mbps": num(g("R_THROUGHPUT")),
        "cpu_pct": num(g("R_CPU")),
    },
}
if result["status"] not in {"ok", "invalid", "failed", "interrupted"}:
    result["status"] = "failed"
result["metric_availability"] = {k: v is not None for k, v in result["metrics"].items()}
print(json.dumps(result, allow_nan=False, sort_keys=True))
