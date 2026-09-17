"""Shared evidence and compatibility rules for Lab 4 reports."""
from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any

VOLATILE = {"cell_id", "run_id", "started", "ended", "status", "reasons", "artifacts",
            "metrics", "metric_availability", "observations", "cpu_measurement",
            "template_a_metrics", "instrumentation_limitations"}
IDENTITY = ("template", "topology", "scenario", "scale", "workload", "engine",
            "netem", "duration", "bag_id", "bag_digest", "workload_id", "config_id",
            "configuration_id", "measurement_settings", "measurement_window", "settings")


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def metric(row: dict, name: str):
    value = (row.get("metrics") or {}).get(name)
    return value if finite(value) else None


def canonical(value: Any):
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in sorted(value.items()) if k not in {"monotonic_start", "monotonic_end", "cell_started", "cell_ended", "observed_workload_started", "observed_workload_ended", "observed_probe_started", "observed_probe_ended"}}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return value


def compatibility_key(row: dict) -> tuple:
    """All experiment settings except the candidate RMW and volatile evidence."""
    data = {}
    for key in IDENTITY:
        if key in row:
            data[key] = canonical(row[key])
    # Select stable provenance. Runtime namespaces are expected to differ from
    # cell to cell, while their image identities and the replay inputs must
    # remain compatible.
    provenance = row.get("provenance")
    if isinstance(provenance, dict):
        effective = dict(provenance.get("effective_settings") or {})
        effective.pop("rmw", None)
        effective.pop("rmw_implementation", None)
        data["provenance"] = canonical({
            "metadata": provenance.get("metadata"),
            "storage_identifier": provenance.get("storage_identifier"),
            "storage_files": provenance.get("storage_files"),
            "duration_ns": provenance.get("duration_ns"),
            "topics": provenance.get("topics"),
            "replay_rate": provenance.get("replay_rate"),
            "qos": provenance.get("qos"),
            "requested_replicas": provenance.get("requested_replicas"),
            "image_ids": sorted(set((provenance.get("image_ids") or {}).values())),
            "benchmark_config": provenance.get("benchmark_config"),
            "effective_settings": effective,
        })
    effective = row.get("effective_settings")
    if isinstance(effective, dict):
        effective = dict(effective)
        effective.pop("rmw", None)
        effective.pop("rmw_implementation", None)
        data["effective_settings"] = canonical(effective)
    return tuple(json.dumps(data, sort_keys=True, separators=(",", ":")) for _ in [0])


def groups(results: list[dict]) -> list[tuple[tuple, list[dict]]]:
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    order: list[tuple] = []
    for index, row in enumerate(results):
        row = dict(row)
        row.setdefault("_report_index", index + 1)
        key = compatibility_key(row)
        if key not in grouped:
            order.append(key)
        grouped[key].append(row)
    return [(key, grouped[key]) for key in order]


def requested_rmws(rows: list[dict], defs: dict) -> list[str]:
    found = []
    for row in rows:
        values = row.get("requested_rmws") or row.get("requested_rmw") or []
        if isinstance(values, str):
            values = [x for x in values.split(",") if x]
        for value in values:
            if value not in found:
                found.append(value)
    if not found:
        found = [r for r in defs.get("rmws", {}) if any(x.get("rmw") == r for x in rows)]
    return found


def legacy(row: dict) -> bool:
    # Rows from the schema-version-1 producer explicitly carry schema_version 1.  A
    # compact fixture or older in-memory consumer row without a version is
    # retained for backwards compatibility and is not silently treated as
    # historical data.
    return "schema_version" in row and int(row.get("schema_version", 1) or 1) < 2


def status(row: dict) -> str:
    return "legacy/unverified" if legacy(row) else str(row.get("status", "ok"))


def evidence_note(row: dict, name: str) -> str:
    if legacy(row):
        return "legacy/unverified"
    if status(row) != "ok":
        return status(row)
    if metric(row, name) is None:
        return "missing"
    return "observed"


def template_metric_sources(template: str) -> dict[str, str]:
    if template == "A":
        return {"latency_p99": "service_rtt_p99_ms", "data_freshness": "pubsub_latency_mean_ms",
                "reliability": "pubsub_latency_max_ms", "throughput_eff": "pubsub_received_hz",
                "cpu_overhead": "cpu_pct"}
    return {"latency_p99": "control_arrival_gap_p99_ms", "data_freshness": "state_max_silence_ms",
            "reliability": "sensor_estimated_delivery_shortfall_pct", "throughput_eff": "throughput_mbps",
            "cpu_overhead": "cpu_pct"}


def value_for(row: dict, template: str, criterion: str):
    source = template_metric_sources(template).get(criterion)
    if not source:
        return None
    if template == "A":
        value = metric(row, source) if source == "cpu_pct" else (row.get("template_a_metrics") or {}).get(source)
    else:
        value = metric(row, source)
        # Unversioned compact rows used the older names.  Explicit legacy
        # rows do not get this semantic upgrade.
        if value is None and not legacy(row):
            aliases = {"control_arrival_gap_p99_ms": "control_p99_ms",
                       "state_max_silence_ms": "state_freshness_ms",
                       "sensor_estimated_delivery_shortfall_pct": "sensor_drop_pct"}
            value = metric(row, aliases.get(source, ""))
    return value if finite(value) else None


def required_criteria(defs: dict, template: str) -> dict[str, dict]:
    sources = template_metric_sources(template)
    return {name: dict(spec, metric=sources[name]) for name, spec in defs["decision"]["criteria"].items() if name in sources}


def source_label(template: str, criterion: str, defs: dict | None = None) -> str:
    labels = {
        "A": {"latency_p99": "Service RTT p99 (ms)", "data_freshness": "Pub/sub mean latency (ms)",
              "reliability": "Pub/sub maximum latency (ms)", "throughput_eff": "Received rate (Hz)",
              "cpu_overhead": "Receiver workload CPU (%)"},
        "B": {"latency_p99": "Control arrival-gap p99 (ms)", "data_freshness": "State maximum silence (ms)",
              "reliability": "Estimated delivery shortfall (%)", "throughput_eff": "Throughput (Mb/s)",
              "cpu_overhead": "Receiver workload CPU (%)"},
    }
    label = labels.get(template, {}).get(criterion)
    if label:
        return label
    if defs:
        return defs.get("decision", {}).get("criteria", {}).get(criterion, {}).get("label", criterion)
    return criterion
