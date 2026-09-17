#!/usr/bin/env python3
"""fleet_inspector.py - subscribe to robot sensor topics from the console and measure
what the shared medium does to them (Lab 3 diagnosis + remediation tool).

Why this exists: in the routed topology the operator map is built from tf ONLY, and
Foxglove Bridge subscribes lazily (it advertises every topic but subscribes only when a
Lichtblick panel asks). So by default a robot's `scan` and `camera/image_raw` have ZERO
remote subscribers and never cross the AP - the robots publish them into the void.

That makes this node the load lever AND the measurement: a subscriber is what pulls a
topic across the shared medium, so starting one here is what creates offered load. Run it
with --sensors none first and nothing changes; add scan, then camera, and watch the AP.

It is also the QoS experiment. A RELIABLE writer matches a BEST_EFFORT reader, and serves
that reader WITHOUT retransmission repair - so flipping --qos here changes delivery
behaviour with no robot restart and no change to the robot code.

Usage (from the routed console container):
    fleet_inspector.py --sensors none
    fleet_inspector.py --sensors scan   --qos reliable
    fleet_inspector.py --sensors scan   --qos best_effort
    fleet_inspector.py --sensors camera --max-camera 1
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
import threading
import time
from collections import deque

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSHistoryPolicy, QoSProfile, QoSReliabilityPolicy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from sensor_msgs.msg import Image, LaserScan

SCAN_RE = re.compile(r"^/(?P<ns>[^/]+)/scan$")
CAMERA_RE = re.compile(r"^/(?P<ns>[^/]+)/sensor_\d+/camera/image_raw$")

# An inter-arrival gap this large is an operator-visible stall, not jitter.
STALL_S = 0.5


def _msg_bytes(msg) -> int:
    """Approximate on-the-wire payload size without serializing every message."""
    if isinstance(msg, Image):
        return len(msg.data)
    if isinstance(msg, LaserScan):
        return 4 * (len(msg.ranges) + len(msg.intensities))
    return 0


class TopicStats:
    def __init__(self, topic: str) -> None:
        self.topic = topic
        self.count = 0
        self.bytes = 0
        self.gaps = 0
        self.ages: deque[float] = deque(maxlen=512)
        self.last_rx: float | None = None

    def record(self, age_s: float, size: int) -> None:
        now = time.monotonic()
        if self.last_rx is not None and now - self.last_rx > STALL_S:
            self.gaps += 1
        self.last_rx = now
        self.count += 1
        self.bytes += size
        self.ages.append(age_s * 1000.0)


class FleetInspector(Node):
    def __init__(self, robots: list[str], sensors: str, qos_name: str,
                 depth: int, max_camera: int) -> None:
        super().__init__("fleet_inspector")
        self._lock = threading.Lock()
        self._stats: dict[str, TopicStats] = {}
        self._window_start = time.monotonic()

        reliability = (QoSReliabilityPolicy.RELIABLE if qos_name == "reliable"
                       else QoSReliabilityPolicy.BEST_EFFORT)
        self._qos = QoSProfile(
            reliability=reliability,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=depth,
        )
        self._diag = self.create_publisher(DiagnosticArray, "fleet_inspector/link_quality", 10)

        wanted = self._discover(robots, sensors, max_camera)
        for topic, msg_type in wanted:
            self._stats[topic] = TopicStats(topic)
            self.create_subscription(
                msg_type, topic,
                lambda msg, t=topic: self._on_msg(t, msg),
                self._qos,
            )
            self.get_logger().info(f"fleet_inspector subscribing {topic} ({qos_name})")

        if not wanted:
            self.get_logger().info(
                "fleet_inspector: no sensor subscriptions (--sensors none); "
                "the robots' sensor topics stay unsubscribed and off the AP"
            )

    def _discover(self, robots: list[str], sensors: str, max_camera: int):
        """Resolve the topics to subscribe to, by name if given, else from the graph."""
        if sensors == "none":
            return []

        allow = [r.strip().strip("/") for r in robots if r.strip()]
        if allow:
            # Named robots are built directly: a saturated or still-converging graph
            # must not silently reduce what the student asked to measure.
            scans = [(ns, f"/{ns}/scan") for ns in allow]
            cameras = [(ns, f"/{ns}/sensor_0/camera/image_raw") for ns in allow]
        else:
            # Robots join the graph a few seconds apart, so keep polling until the set of
            # matching topics stops growing rather than stopping at the first robot seen.
            deadline = time.monotonic() + 15.0
            names: list[tuple[str, list[str]]] = []
            matched = 0
            stable = 0
            while time.monotonic() < deadline:
                names = self.get_topic_names_and_types()
                found = sum(1 for n, _ in names if SCAN_RE.match(n) or CAMERA_RE.match(n))
                if found and found == matched:
                    stable += 1
                    if stable >= 3:
                        break
                else:
                    stable = 0
                matched = found
                time.sleep(0.5)

            scans = []
            cameras = []
            for name, _types in sorted(names):
                m = SCAN_RE.match(name)
                if m:
                    scans.append((m.group("ns"), name))
                    continue
                m = CAMERA_RE.match(name)
                if m:
                    cameras.append((m.group("ns"), name))

        wanted: list[tuple[str, type]] = []
        if sensors in ("scan", "both"):
            wanted += [(topic, LaserScan) for _ns, topic in scans]
        if sensors in ("camera", "both"):
            # Raw camera frames are ~2.7 MB each at 10 Hz; one stream already exceeds a
            # healthy AP, so the camera tier is capped rather than fleet-wide by default.
            wanted += [(topic, Image) for _ns, topic in cameras[:max_camera]]

        if allow and wanted:
            self._wait_for_topics([t for t, _ in wanted])
        return wanted

    def _wait_for_topics(self, topics: list[str], timeout: float = 20.0) -> None:
        """Give named topics time to appear so subscriptions match promptly."""
        deadline = time.monotonic() + timeout
        pending = set(topics)
        while pending and time.monotonic() < deadline:
            live = {n for n, _ in self.get_topic_names_and_types()}
            pending -= live
            if pending:
                time.sleep(0.5)
        if pending:
            self.get_logger().warn(
                "not yet in the graph (subscribing anyway): " + ", ".join(sorted(pending))
            )

    def _on_msg(self, topic: str, msg) -> None:
        stamp = msg.header.stamp
        age = self.get_clock().now().nanoseconds / 1e9 - (stamp.sec + stamp.nanosec / 1e9)
        with self._lock:
            self._stats[topic].record(age, _msg_bytes(msg))

    def report(self) -> str:
        """Drain the window into a printable table and publish the same as diagnostics."""
        now = time.monotonic()
        with self._lock:
            elapsed = max(1e-6, now - self._window_start)
            rows = []
            diag = DiagnosticArray()
            diag.header.stamp = self.get_clock().now().to_msg()
            total_mb = 0.0
            for topic, st in sorted(self._stats.items()):
                hz = st.count / elapsed
                mbps = st.bytes / elapsed / 1e6
                total_mb += mbps
                ages = sorted(st.ages)
                mean = statistics.fmean(ages) if ages else float("nan")
                p95 = ages[min(len(ages) - 1, int(0.95 * len(ages)))] if ages else float("nan")
                rows.append((topic, hz, mean, p95, mbps, st.gaps))

                status = DiagnosticStatus()
                status.name = f"fleet_inspector{topic}"
                status.level = (DiagnosticStatus.OK if hz > 0 and p95 < 500
                                else DiagnosticStatus.WARN if hz > 0
                                else DiagnosticStatus.ERROR)
                status.message = f"{hz:.1f} Hz, p95 age {p95:.0f} ms"
                status.values = [
                    KeyValue(key="rate_hz", value=f"{hz:.2f}"),
                    KeyValue(key="age_ms_mean", value=f"{mean:.1f}"),
                    KeyValue(key="age_ms_p95", value=f"{p95:.1f}"),
                    KeyValue(key="mbytes_per_s", value=f"{mbps:.3f}"),
                    KeyValue(key="gaps", value=str(st.gaps)),
                ]
                diag.status.append(status)
                st.count = 0
                st.bytes = 0
                st.gaps = 0
                st.ages.clear()
            self._window_start = now
        # A SIGTERM (docker stop / compose down) can shut rclpy down mid-report;
        # only publish while the context is still valid.
        if rclpy.ok():
            self._diag.publish(diag)

        if not rows:
            return "  (no subscriptions - nothing is being pulled across the AP)"
        out = [f"  {'topic':<44}{'Hz':>7}{'age_ms':>9}{'p95_ms':>9}{'MB/s':>9}{'gaps':>6}"]
        for topic, hz, mean, p95, mbps, gaps in rows:
            mean_s = "-" if mean != mean else f"{mean:.1f}"
            p95_s = "-" if p95 != p95 else f"{p95:.1f}"
            out.append(f"  {topic:<44}{hz:>7.1f}{mean_s:>9}{p95_s:>9}{mbps:>9.3f}{gaps:>6d}")
        out.append(f"  {'TOTAL':<44}{'':>7}{'':>9}{'':>9}{total_mb:>9.3f}")
        return "\n".join(out)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description="Measure robot sensor delivery across the shared AP (Lab 3)")
    ap.add_argument("--robots", default="",
                    help="comma-separated namespaces; empty = every robot in the graph")
    ap.add_argument("--sensors", default="none", choices=["none", "scan", "camera", "both"],
                    help="which sensor class to subscribe to (default none: adds no AP load)")
    ap.add_argument("--qos", default="reliable", choices=["reliable", "best_effort"],
                    help="subscription reliability (a RELIABLE writer also serves a BEST_EFFORT reader)")
    ap.add_argument("--depth", type=int, default=10, help="subscription history depth")
    ap.add_argument("--max-camera", type=int, default=1,
                    help="how many robots' raw camera streams to subscribe to")
    ap.add_argument("--report-rate", type=float, default=1.0, help="table refresh rate (Hz)")
    ap.add_argument("--duration", type=float, default=0.0, help="stop after N seconds (0 = run until Ctrl-C)")
    args = ap.parse_args(argv)

    rclpy.init()
    node = FleetInspector(args.robots.split(","), args.sensors, args.qos,
                          args.depth, args.max_camera)

    executor = SingleThreadedExecutor()
    executor.add_node(node)

    def _spin() -> None:
        # SIGTERM shuts rclpy down under the spin; exit quietly instead of letting
        # ExternalShutdownException surface as a stray traceback from the thread.
        try:
            executor.spin()
        except ExternalShutdownException:
            pass
    spinner = threading.Thread(target=_spin, daemon=True)
    spinner.start()

    period = 1.0 / max(1e-3, args.report_rate)
    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    header = (f"fleet_inspector  sensors={args.sensors}  qos={args.qos}  "
              f"depth={args.depth}   (Ctrl-C to stop)")
    print(header, flush=True)
    try:
        while rclpy.ok():
            time.sleep(period)
            print(node.report(), flush=True)
            if deadline is not None and time.monotonic() >= deadline:
                break
    except KeyboardInterrupt:
        pass
    finally:
        # Stop the executor and join before teardown; destroying the node while the
        # spin thread is still live aborts in the C++ layer.
        executor.shutdown()
        spinner.join(timeout=2.0)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
