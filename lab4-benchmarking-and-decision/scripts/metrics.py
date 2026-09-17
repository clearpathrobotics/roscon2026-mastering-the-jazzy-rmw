"""Deterministic Lab 4 metric reducers.

This module deliberately has no ROS or Docker dependencies.  Collection code
records monotonic receipt times and CPU samples; these functions turn those
observations into stable JSON-friendly values.
"""
from __future__ import annotations

import math
from typing import Any, Iterable


def expected_rates_from_inventory(
    expected_topics: dict[str, dict[str, Any]], inventory_duration: float, replay_rate: float
) -> dict[str, float]:
    """Return per-topic scheduled rates from strict replay inventory."""
    if inventory_duration <= 0 or replay_rate <= 0:
        return {}
    return {
        topic: float(item.get("message_count", 0)) / inventory_duration * replay_rate
        for topic, item in expected_topics.items()
    }


def percentile(values: Iterable[float], pct: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    rank = max(1, math.ceil((pct / 100.0) * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def _rounded(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None


def reduce_topic_observations(
    receipts: dict[str, Iterable[float]],
    window_start: float,
    window_end: float,
    expected_rates: dict[str, float] | None = None,
    min_samples: int = 30,
) -> dict[str, Any]:
    """Reduce per-topic monotonic receipt timestamps.

    Silence includes both observation boundaries.  Thus a topic received at
    2s and 8s in a [0s, 10s] window has a maximum silence of 6s, and a topic
    with no receipts has a maximum and terminal silence of 10s.  Gap
    percentiles are unavailable until that topic reaches ``min_samples``.
    """
    if window_end < window_start:
        raise ValueError("measurement window must not end before it starts")
    duration = window_end - window_start
    rates = expected_rates or {}
    topics: dict[str, dict[str, Any]] = {}
    for topic, raw_stamps in receipts.items():
        stamps = sorted(float(stamp) for stamp in raw_stamps if window_start <= float(stamp) <= window_end)
        gaps = [b - a for a, b in zip(stamps, stamps[1:])]
        if stamps:
            boundary_gaps = [stamps[0] - window_start, *gaps, window_end - stamps[-1]]
            maximum_silence = max(boundary_gaps)
            terminal_silence = window_end - stamps[-1]
            first_offset = stamps[0] - window_start
            last_offset = stamps[-1] - window_start
        else:
            maximum_silence = duration
            terminal_silence = duration
            first_offset = None
            last_offset = None
        enough = len(stamps) >= min_samples
        expected = rates.get(topic)
        expected_count = expected * duration if expected is not None else None
        received_expected_ratio = (
            len(stamps) / expected_count if expected_count and expected_count > 0 else None
        )
        topics[topic] = {
            "received_count": len(stamps),
            "estimated_expected_count": _rounded(expected_count),
            "received_expected_ratio": _rounded(received_expected_ratio),
            "first_receipt_offset_s": _rounded(first_offset),
            "last_receipt_offset_s": _rounded(last_offset),
            "arrival_gap_p50_ms": _rounded(percentile((gap * 1000 for gap in gaps), 50) if enough else None),
            "arrival_gap_p95_ms": _rounded(percentile((gap * 1000 for gap in gaps), 95) if enough else None),
            "arrival_gap_p99_ms": _rounded(percentile((gap * 1000 for gap in gaps), 99) if enough else None),
            "maximum_silence_ms": _rounded(maximum_silence * 1000),
            "terminal_silence_ms": _rounded(terminal_silence * 1000),
            "gap_samples": len(gaps),
            "minimum_samples": min_samples,
            "gap_metrics_available": enough,
        }
    return {
        "window_start": window_start,
        "window_end": window_end,
        "duration_s": duration,
        "topics": topics,
    }


def reduce_cpu_samples(
    samples: Iterable[dict[str, float] | tuple[float, float]],
    window_start: float,
    window_end: float,
) -> dict[str, Any]:
    """Reduce receiver workload CPU samples that overlap an active window."""
    selected: list[dict[str, float]] = []
    for sample in samples:
        if isinstance(sample, dict):
            timestamp, value = sample.get("timestamp"), sample.get("cpu_pct")
        else:
            timestamp, value = sample
        try:
            timestamp, value = float(timestamp), float(value)
        except (TypeError, ValueError):
            continue
        if window_start <= timestamp <= window_end and math.isfinite(value):
            selected.append({"timestamp": timestamp, "cpu_pct": value})
    mean = sum(s["cpu_pct"] for s in selected) / len(selected) if selected else None
    return {
        "mean_cpu_pct": _rounded(mean),
        "samples": selected,
        "sample_count": len(selected),
        "available": bool(selected),
        "window_start": window_start,
        "window_end": window_end,
    }


def classify_inventory(
    expected_topics: list[dict[str, Any]],
    discovered_topics: dict[str, list[str]],
    received_topics: Iterable[str],
) -> dict[str, Any]:
    """Keep expectation, graph discovery, type matching, and reception separate."""
    expected = {item["topic"]: item for item in expected_topics}
    discovered = set(discovered_topics)
    matched = {
        topic for topic, item in expected.items()
        if topic in discovered and item.get("type") in discovered_topics.get(topic, [])
    }
    received = set(received_topics) & set(expected)
    return {
        "expected_topics": sorted(expected),
        "discovered_topics": sorted(discovered),
        "matched_topics": sorted(matched),
        "received_topics": sorted(received),
        "expected_count": len(expected),
        "discovered_count": len(discovered),
        "matched_count": len(matched),
        "received_count": len(received),
    }


def reduce_class_observations(
    topic_metrics: dict[str, dict[str, Any]],
    topic_classes: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """Summarize classes without allowing a busy topic to hide a silent one."""
    result: dict[str, dict[str, Any]] = {}
    for topic, metrics in topic_metrics.items():
        cname = topic_classes.get(topic)
        if cname is None:
            continue
        item = result.setdefault(cname, {"topics": [], "maximum_silence_ms": None, "terminal_silence_ms": None})
        item["topics"].append(topic)
        for key in ("maximum_silence_ms", "terminal_silence_ms"):
            value = metrics[key]
            item[key] = value if item[key] is None else max(item[key], value)
    for item in result.values():
        item["topics"].sort()
    return result
