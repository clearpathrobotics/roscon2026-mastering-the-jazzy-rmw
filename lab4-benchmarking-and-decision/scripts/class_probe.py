#!/usr/bin/env python3
"""class_probe.py — topic-class-aware metrics probe for fleet MCAP replay.

Used by Lab 4's Benchmarking & Decision Matrix controlled cross-RMW comparison.

Subscribes to the live topics produced by replaying the workshop bag on the
fleet, buckets them into the workshop topic classes (sensor / control / state)
using the `match` regexes in benchmark.yaml, and derives the per-class metrics
the comparison sheet and Pugh scorer consume.

Why not header-stamp latency? Replayed bag messages carry the *original*
recording timestamps, so `now - header.stamp` is meaningless. The honest,
subscriber-only signals are:

  * inter-arrival gaps and boundary-inclusive silence — how delayed / bursty
      delivery is (arrival-gap and silence metrics are kept separate).
  * received vs expected — an estimated delivery shortfall relative to the
      metadata-derived schedule, not a packet-loss measurement.
  * bytes/s             — bandwidth.
      throughput_mbps  = sensor-class bytes * 8 / 1e6 / duration

`expected` comes from the inventory's recorded per-topic counts over the bag
duration, scaled to the probe window. Missing inventory topics stay observed as
empty topics and remain in denominators.

Raw subscriptions are used so message bytes are captured without needing to
deserialize every message type.

Usage (run inside a fleet replica, which is already on the fleet's network):
    class_probe.py --duration 30 --publishers 3 \
        --bag-metadata /bags/metadata.yaml \
        --out /tmp/probe.json \
        --template B --scenario S2 --rmw cyclone --run-id <id>

Prints the metrics JSON to stdout and (if --out) writes the full result JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time

import yaml

from metrics import (classify_inventory, expected_rates_from_inventory,
                     reduce_class_observations, reduce_topic_observations)

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy, QoSDurabilityPolicy
from rosidl_runtime_py.utilities import get_message

HERE = os.path.dirname(os.path.abspath(__file__))
CONTAINER_CONFIG = "/scripts/lab4/benchmark.yaml"
HOST_CONFIG = os.path.join(HERE, "benchmark.yaml")
DEFAULT_CONFIG = CONTAINER_CONFIG if os.path.isfile(CONTAINER_CONFIG) else HOST_CONFIG


def class_of(topic: str, classes: dict) -> str | None:
    """Return the first class whose `match` regexes hit this topic name."""
    for cname, spec in classes.items():
        for pat in spec.get("match", []):
            if re.search(pat, topic):
                return cname
    return None


def build_qos(spec: dict) -> QoSProfile:
    qos = spec.get("qos", {}) or {}
    reliability = (
        QoSReliabilityPolicy.BEST_EFFORT
        if qos.get("reliability") == "best_effort"
        else QoSReliabilityPolicy.RELIABLE
    )
    return QoSProfile(
        reliability=reliability,
        history=QoSHistoryPolicy.KEEP_LAST,
        depth=int(qos.get("depth", 10)),
        durability=QoSDurabilityPolicy.VOLATILE,
    )


def bag_rates(metadata_path: str) -> dict[str, float]:
    """topic -> messages/second from bag metadata (0 if unavailable)."""
    if not metadata_path or not os.path.exists(metadata_path):
        return {}
    meta = yaml.safe_load(open(metadata_path, encoding="utf-8"))
    info = meta["rosbag2_bagfile_information"]
    dur = info["duration"]["nanoseconds"] / 1e9
    rates: dict[str, float] = {}
    if dur <= 0:
        return rates
    for t in info["topics_with_message_count"]:
        rates[t["topic_metadata"]["name"]] = t["message_count"] / dur
    return rates


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Topic-class metrics probe")
    ap.add_argument("--duration", type=float, default=30.0)
    ap.add_argument("--publishers", type=int, default=1, help="fleet replicas publishing each topic")
    ap.add_argument("--bag-metadata", default="", help="path to bag metadata.yaml for drop%% baseline")
    ap.add_argument("--expected-inventory", default="",
                    help="Lab 4 inventory JSON; expected topics come from metadata, not discovery")
    ap.add_argument("--expected-rates", default="",
                    help="mock workload: 'suffix=hz,...' sensor publish rates, matched by "
                         "topic-name suffix (replaces the bag-metadata drop%% baseline)")
    ap.add_argument("--discover-wait", type=float, default=5.0)
    ap.add_argument("--min-samples", type=int, default=30,
                    help="min received messages for a gap-based metric to be reported (else null)")
    ap.add_argument("--benchmark-config", default=DEFAULT_CONFIG)
    ap.add_argument("--out", default="")
    # result dimensions
    for dim in ("template", "scenario", "rmw", "rmw-impl", "run-id"):
        ap.add_argument(f"--{dim}", default="")
    args = ap.parse_args(argv)

    defs = yaml.safe_load(open(args.benchmark_config, encoding="utf-8"))
    classes = defs["topic_classes"]
    rates = bag_rates(args.bag_metadata)
    inventory = {}
    if args.expected_inventory:
        inventory = json.load(open(args.expected_inventory, encoding="utf-8"))
    expected_topics = {item["topic"]: item for item in inventory.get("expected_topics", [])}

    # mock workload: sensor rates are configured (no bag metadata). Parse
    # 'suffix=hz,...' and match each discovered sensor topic by name suffix.
    expected_suffix_rates: list[tuple[str, float]] = []
    for pair in args.expected_rates.split(","):
        pair = pair.strip()
        if "=" in pair:
            suf, hz = pair.rsplit("=", 1)
            try:
                expected_suffix_rates.append((suf.strip(), float(hz)))
            except ValueError:
                pass

    rclpy.init()
    node = rclpy.create_node("workshop_class_probe")

    # let discovery settle, then snapshot the graph. Discovery is an
    # observation; inventory remains the expectation used for subscriptions
    # and loss denominators.
    time.sleep(args.discover_wait)
    discovered = dict(node.get_topic_names_and_types())
    topics = list(discovered.items())
    if expected_topics:
        topics = [(name, [item["type"]]) for name, item in expected_topics.items()]

    # per class: arrival monotonic times per topic, byte totals
    arrivals: dict[str, dict[str, list[float]]] = {c: {} for c in classes}
    byte_totals: dict[str, int] = {c: 0 for c in classes}
    subscribed: dict[str, str] = {}  # topic -> class
    unknown_types: dict[str, str] = {}
    absent_expected_topics = sorted(set(expected_topics) - set(discovered))

    def make_cb(cname: str, topic: str):
        bucket = arrivals[cname].setdefault(topic, [])

        def cb(serialized):
            bucket.append(time.monotonic())
            try:
                byte_totals[cname] += len(serialized)
            except TypeError:
                try:
                    byte_totals[cname] += len(serialized.buffer)
                except Exception:  # noqa: BLE001
                    pass

        return cb

    for topic, types in topics:
        cname = class_of(topic, classes)
        if not cname or not types:
            continue
        # Create an empty observation bucket before type resolution so a
        # never-received or unresolvable expected topic remains in denominators.
        arrivals[cname].setdefault(topic, [])
        try:
            msg_type = get_message(types[0])
        except Exception:  # noqa: BLE001 - unknown/unresolvable type, skip
            unknown_types[topic] = types[0]
            continue
        node.create_subscription(msg_type, topic, make_cb(cname, topic), build_qos(classes[cname]), raw=True)
        subscribed[topic] = cname

    if not subscribed:
        print("class_probe: no matching topics discovered", file=sys.stderr)

    # Brief settle so publisher/subscriber matching completes before the
    # measurement window — otherwise the initial (large) matching gap can skew
    # p99 on low-rate control topics.
    if subscribed:
        time.sleep(1.5)

    # Drain callbacks on a dedicated executor thread so high-rate topics (e.g.
    # /tf at ~90 Hz x N replicas) aren't throttled by the measurement loop. A
    # single-threaded executor keeps all callbacks on one thread, so the plain
    # list/counter updates in the callbacks need no locking.
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()
    measurement_start = time.monotonic()
    time.sleep(args.duration)
    measurement_end = time.monotonic()
    executor.shutdown()
    spinner.join(timeout=2.0)

    node.destroy_node()
    rclpy.shutdown()

    # --- reduce to per-topic and per-class metrics --------------------------
    flat_arrivals = {topic: stamps for bucket in arrivals.values() for topic, stamps in bucket.items()}
    expected_rates: dict[str, float] = {}
    inventory_duration = float(inventory.get("duration_s", 0) or 0)
    replay_rate = float(inventory.get("replay_rate", 1) or 1)
    if expected_topics:
        expected_rates = expected_rates_from_inventory(expected_topics, inventory_duration, replay_rate)
    sensor_topics = [t for t, c in subscribed.items() if c == "sensor"]
    if expected_suffix_rates:
        # mock workload: each namespaced sensor topic is one publisher; match its
        # configured rate by name suffix and sum over all discovered sensor topics.
        def _suffix_rate(topic: str) -> float:
            for suf, hz in expected_suffix_rates:
                if topic.endswith(suf):
                    return hz
            return 0.0
        expected_rates.update({t: _suffix_rate(t) for t in sensor_topics})
    elif not expected_topics:
        # Legacy bag-metadata path: replay namespaces every topic per replica
        # (/robot_<id>/camera/image_raw), but the bag's own recorded metadata
        # keeps the un-namespaced name (/camera/image_raw) - an exact dict
        # lookup here would never match, so match by suffix instead. Each
        # replica's own namespaced topic is a separate entry in sensor_topics,
        # so summing over them already accounts for N publishers - don't
        # multiply by args.publishers again (that would double-count).
        def _bag_rate(topic: str) -> float:
            for name, hz in rates.items():
                if topic.endswith(name):
                    return hz
            return 0.0
        expected_rates.update({t: _bag_rate(t) for t in sensor_topics})
    reduced = reduce_topic_observations(flat_arrivals, measurement_start, measurement_end,
                                        expected_rates, args.min_samples)
    topic_classes = {topic: cname for cname, bucket in arrivals.items() for topic in bucket}
    class_metrics = reduce_class_observations(reduced["topics"], topic_classes)
    def class_count(cname: str) -> int:
        return sum(value["received_count"] for topic, value in reduced["topics"].items()
                   if topic_classes.get(topic) == cname)
    def worst(cname: str, key: str) -> float | None:
        values = [reduced["topics"][topic][key] for topic in class_metrics.get(cname, {}).get("topics", [])
                  if reduced["topics"][topic]["gap_metrics_available"] and reduced["topics"][topic][key] is not None]
        return max(values) if values else None
    sensor_expected = sum(value["estimated_expected_count"] or 0 for topic, value in reduced["topics"].items()
                          if topic_classes.get(topic) == "sensor")
    sensor_ratio = class_count("sensor") / sensor_expected if sensor_expected > 0 else None
    sensor_shortfall = max(0.0, (1.0 - sensor_ratio) * 100.0) if sensor_ratio is not None else None
    throughput_mbps = byte_totals["sensor"] * 8 / 1e6 / (measurement_end - measurement_start)
    received_topics = [topic for topic, value in reduced["topics"].items() if value["received_count"] > 0]
    inventory_summary = classify_inventory(list(expected_topics.values()), discovered, received_topics) if expected_topics else {
        "expected_topics": [], "discovered_topics": sorted(discovered), "matched_topics": [],
        "received_topics": sorted(received_topics), "expected_count": 0,
        "discovered_count": len(discovered), "matched_count": 0, "received_count": len(received_topics)}
    control_p99 = worst("control", "arrival_gap_p99_ms")
    state_p95 = worst("state", "arrival_gap_p95_ms")
    metrics = {
        "sensor_estimated_delivery_shortfall_pct": round(sensor_shortfall, 2) if sensor_shortfall is not None else None,
        "sensor_received_expected_ratio": round(sensor_ratio, 4) if sensor_ratio is not None else None,
        "control_arrival_gap_p99_ms": control_p99,
        "state_arrival_gap_p95_ms": state_p95,
        "control_max_silence_ms": class_metrics.get("control", {}).get("maximum_silence_ms"),
        "state_max_silence_ms": class_metrics.get("state", {}).get("maximum_silence_ms"),
        "throughput_mbps": round(throughput_mbps, 2) if throughput_mbps is not None else None,
        "cpu_pct": None,  # filled by the sweep from docker stats
    }
    metrics.update({"sensor_drop_pct": metrics["sensor_estimated_delivery_shortfall_pct"],
                    "control_p99_ms": metrics["control_arrival_gap_p99_ms"],
                    "state_freshness_ms": metrics["state_arrival_gap_p95_ms"]})

    result = {
        "template": args.template,
        "scenario": args.scenario,
        "rmw": args.rmw,
        "rmw_impl": getattr(args, "rmw_impl", "") or "",
        "workload": "mcap",
        "run_id": getattr(args, "run_id", "") or "",
        "publishers": args.publishers,
        "duration": args.duration,
        "measurement_window": {"monotonic_start": measurement_start, "monotonic_end": measurement_end,
                                "duration_s": measurement_end - measurement_start, "warmup_excluded": True},
        "topics": subscribed,
        "topic_metrics": reduced["topics"],
        "class_silence": class_metrics,
        "inventory_summary": inventory_summary,
        "expected_topics": expected_topics,
        "discovered_topics": {name: types for name, types in discovered.items()},
        "absent_expected_topics": absent_expected_topics,
        "unknown_types": unknown_types,
        "instrumentation_limitations": (["unknown message types"] if unknown_types else []) + [
            "estimated delivery shortfall uses metadata counts and replay scheduling; it is not packet loss",
            "receiver workload CPU is not isolated middleware overhead"],
        "counts": {c: class_count(c) for c in classes},
        "metrics": metrics,
    }

    print(json.dumps(metrics))
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        json.dump(result, open(args.out, "w", encoding="utf-8"), indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
