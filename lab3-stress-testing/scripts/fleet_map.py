#!/usr/bin/env python3
"""fleet_map.py - single top-down "operator map" of the whole fleet (Lab 3 climax).

Looks up every robot's pose over tf2 and draws each as an icon on ONE image, then
publishes it (default /fleet_map/image_raw). Opened in Lichtblick / Foxglove it is the
climax visual: with a good RMW + good settings the fleet glides; with a bad one the poses
arrive late or not at all and robots visibly freeze and jump on the map.

The freeze is real: when a robot's tf goes stale (delivery degraded by the shared medium)
this node keeps its LAST known pose, so the icon stops moving exactly as long as its state
stops arriving - the operator sees the fleet stutter.

The view AUTO-FITS the fleet: it stays anchored on the per-robot odometry grid's origin
and grows its half-extent with a slow EMA, so the whole fleet stays framed no matter where
it has driven (the mock robots wander) while frame-to-frame motion - and freezing - stays
visible. Reuses lab1's SpriteAtlas for
rotated robot icons; the rest is a plain numpy grid. Reliable QoS so Foxglove receives it.

Runs on the console (across the AP in the routed topology), so the same shared-medium
contention that drives the metrics drives the picture. numpy-only, no OpenCV.

Usage:
    fleet_map.py                       # auto-discover robots from tf (*/base_link)
    fleet_map.py --robots robot_a,robot_b --anchor odom --rate 10
"""
from __future__ import annotations

import argparse
import math
import sys
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import numpy as np
import yaml

import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from sensor_msgs.msg import CompressedImage, Image
from tf2_ros import (
    Buffer,
    ConnectivityException,
    ExtrapolationException,
    LookupException,
    TransformListener,
)

from dynamic_image_publisher.compositor import (
    SpriteAtlas,
    alpha_blit,
    load_meta,
    load_rgba,
    yaw_from_quaternion,
)

# per-robot label-dot colors (RGB)
PALETTE = [
    (66, 135, 245), (245, 130, 48), (60, 180, 75), (230, 25, 75),
    (145, 30, 180), (70, 240, 240), (240, 50, 230), (170, 200, 40),
    (250, 150, 190), (0, 150, 150), (170, 110, 40), (120, 120, 0),
]

GLYPHS = {
    " ": (0, 0, 0, 0, 0), ":": (0, 2, 0, 2, 0),
    "0": (7, 5, 5, 5, 7), "1": (2, 6, 2, 2, 7), "2": (7, 1, 7, 4, 7),
    "3": (7, 1, 7, 1, 7), "4": (5, 5, 7, 1, 1), "5": (7, 4, 7, 1, 7),
    "6": (7, 4, 7, 5, 7), "7": (7, 1, 1, 1, 1), "8": (7, 5, 7, 5, 7),
    "9": (7, 5, 7, 1, 7), "A": (2, 5, 7, 5, 5), "B": (6, 5, 6, 5, 6),
    "C": (3, 4, 4, 4, 3), "D": (6, 5, 5, 5, 6), "E": (7, 4, 6, 4, 7),
    "F": (7, 4, 6, 4, 4), "G": (3, 4, 5, 5, 3), "M": (5, 7, 7, 5, 5),
    "S": (3, 4, 2, 1, 6),
}

FRESH = (35, 160, 80)
DEGRADED = (235, 165, 35)
STALE = (205, 55, 55)


def _make_grid(size: int) -> np.ndarray:
    """A light-gray canvas with a faint grid + border (HxWx3 uint8 RGB)."""
    img = np.full((size, size, 3), 235, dtype=np.uint8)
    step = max(10, size // 10)
    img[::step, :, :] = 205
    img[:, ::step, :] = 205
    img[:3, :, :] = 120
    img[-3:, :, :] = 120
    img[:, :3, :] = 120
    img[:, -3:, :] = 120
    return img


def _fleet_offset(index: int, count: int, spacing: float) -> tuple[float, float]:
    """Place independent per-robot odometry frames on one deterministic grid."""
    columns = max(1, math.ceil(math.sqrt(count)))
    rows = math.ceil(count / columns)
    column = index % columns
    row = index // columns
    return (
        (column - (columns - 1) / 2.0) * spacing,
        (row - (rows - 1) / 2.0) * spacing,
    )


def _draw_line(image: np.ndarray, start: tuple[int, int], end: tuple[int, int],
               color: tuple[int, int, int]) -> None:
    """Draw a clipped one-pixel line into an RGB image."""
    start_col, start_row = start
    end_col, end_row = end
    steps = max(abs(end_col - start_col), abs(end_row - start_row))
    if steps == 0:
        return
    columns = np.rint(np.linspace(start_col, end_col, steps + 1)).astype(int)
    rows = np.rint(np.linspace(start_row, end_row, steps + 1)).astype(int)
    valid = (
        (rows >= 0) & (rows < image.shape[0]) &
        (columns >= 0) & (columns < image.shape[1])
    )
    image[rows[valid], columns[valid]] = color


def _draw_text(image: np.ndarray, text: str, col: int, row: int,
               color: tuple[int, int, int], scale: int = 3) -> None:
    """Draw compact 3x5 status text without an image-library dependency."""
    for char in text:
        for glyph_row, bits in enumerate(GLYPHS.get(char, GLYPHS[" "])):
            for glyph_col in range(3):
                if bits & (1 << (2 - glyph_col)):
                    top = row + glyph_row * scale
                    left = col + glyph_col * scale
                    image[top:top + scale, left:left + scale] = color
        col += 4 * scale


def _freshness_color(age_ms: float, degraded_ms: float,
                     stale_ms: float) -> tuple[int, int, int]:
    if age_ms >= stale_ms:
        return STALE
    if age_ms >= degraded_ms:
        return DEGRADED
    return FRESH


class FleetMap(Node):
    def __init__(self, robots: list[str], anchor: str, rate: float,
                 model: str, size: int, angle_steps: int, pad: float,
                 spacing: float, degraded_ms: float, stale_ms: float,
                 max_view: float, min_view: float) -> None:
        super().__init__("fleet_map")
        self._fixed_robots = [r.strip() for r in robots if r.strip()]
        # Per-robot anchor frame. The mock robot's map/world roots are STATIC
        # (transient-local) and don't reliably reach the console across the routed
        # AP, but {ns}/odom->base_link is DYNAMIC and always arrives, so we anchor
        # each robot on {ns}/<anchor> (odom).
        self._anchor = anchor
        self._pad = pad
        self._size = size
        self._spacing = spacing
        self._degraded_ms = degraded_ms
        self._stale_ms = stale_ms
        self._max_half = max_view
        self._min_half = min_view

        # Robot icon: reuse lab1's pre-rotated sprite atlas.
        share = Path(get_package_share_directory("dynamic_image_publisher"))
        assets = share / "assets"
        sprite = load_rgba(assets / "sprites" / f"{model}.npy")
        smeta = load_meta(assets / "sprites" / f"{model}.json")
        soc, sorr = smeta["origin_px"]
        self.atlas = SpriteAtlas(sprite, soc, sorr, num_angles=angle_steps)

        self.pristine = _make_grid(size)

        # Reliable + keep-last-1: a reliable publisher matches BOTH reliable and
        # best-effort subscribers (best-effort matches only best-effort, and Foxglove
        # Bridge subscribes reliably, so best-effort would show nothing).
        img_qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.pub = self.create_publisher(Image, "fleet_map/image_raw", img_qos)
        self.compressed_pub = self.create_publisher(
            CompressedImage, "fleet_map/image_raw/compressed", img_qos
        )
        self.freshness_pub = self.create_publisher(
            DiagnosticArray, "fleet_map/state_freshness", 10
        )
        self._msg = Image()
        self._msg.height = self._msg.width = size
        self._msg.encoding = "rgb8"
        self._msg.is_bigendian = 0
        self._msg.step = size * 3
        self._msg.header.frame_id = "fleet_map"

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self._last_pose: dict[str, tuple[float, float, float]] = {}
        self._last_tf_stamp_ns: dict[str, int] = {}
        self._trails: dict[str, deque[tuple[float, float]]] = {}
        self._robots: list[str] = list(self._fixed_robots)
        self._last_log = 0.0
        # The frame is anchored on the odometry grid's origin, so only the half-extent
        # (meters) adapts, and it does so slowly.
        self._half = 5.0
        self._view_init = False

        self.get_logger().info(
            f"fleet_map: {size}x{size} grid, model='{model}', anchor='{anchor}', "
            f"robots={self._robots or 'auto-discover'}"
        )

    def _discover(self) -> None:
        try:
            frames = yaml.safe_load(self.tf_buffer.all_frames_as_yaml()) or {}
        except Exception:  # noqa: BLE001
            return
        found = sorted({f[: -len("/base_link")] for f in frames if f.endswith("/base_link")})
        if found and found != self._robots:
            self._robots = found
            self.get_logger().info(f"fleet_map: tracking {len(found)} robots: {found}")

    def _pose(self, ns: str):
        target = f"{ns}/base_link"
        try:
            tf = self.tf_buffer.lookup_transform(f"{ns}/{self._anchor}", target, rclpy.time.Time())
        except (LookupException, ConnectivityException, ExtrapolationException):
            return self._last_pose.get(ns)  # freeze at last known pose
        t = tf.transform.translation
        q = tf.transform.rotation
        pose = (t.x, t.y, yaw_from_quaternion(q.x, q.y, q.z, q.w))
        # A diverged estimator publishes NaN; keep the last good pose so one bad robot
        # cannot corrupt the shared view every other robot is drawn in.
        if not all(math.isfinite(v) for v in pose):
            return self._last_pose.get(ns)
        self._last_pose[ns] = pose
        self._last_tf_stamp_ns[ns] = (
            tf.header.stamp.sec * 1_000_000_000 + tf.header.stamp.nanosec
        )
        return pose

    def _freshness_ms(self, ns: str, now_ns: int) -> float:
        stamp_ns = self._last_tf_stamp_ns.get(ns)
        if stamp_ns is None:
            return math.inf
        return max(0.0, (now_ns - stamp_ns) / 1_000_000.0)

    def _publish_freshness(self, ages: list[tuple[str, float]]) -> None:
        message = DiagnosticArray()
        message.header.stamp = self.get_clock().now().to_msg()
        for ns, age_ms in ages:
            status = DiagnosticStatus()
            status.name = f"fleet/{ns}/state_freshness"
            status.hardware_id = ns
            if age_ms >= self._stale_ms:
                status.level, status.message = DiagnosticStatus.ERROR, "STALE"
            elif age_ms >= self._degraded_ms:
                status.level, status.message = DiagnosticStatus.WARN, "DEGRADED"
            else:
                status.level, status.message = DiagnosticStatus.OK, "FRESH"
            value = "inf" if math.isinf(age_ms) else f"{age_ms:.1f}"
            status.values = [KeyValue(key="state_freshness_ms", value=value)]
            message.status.append(status)
        self.freshness_pub.publish(message)

    def _update_view(self, poses: list[tuple[float, float, float]]) -> None:
        finite = [p for p in poses if math.isfinite(p[0]) and math.isfinite(p[1])]
        if not finite:
            return
        # The frame stays on the odometry grid's origin instead of the fleet centroid: a
        # centroid view follows a lone robot around and hides the motion (and the
        # freeze-and-jump) the map exists to show. Only the extent reacts.
        half = max(max(abs(p[0]) for p in finite), max(abs(p[1]) for p in finite)) * self._pad
        # Bound the fit: a runaway estimate would otherwise zoom out until real motion
        # is invisible, and a lone robot near the origin would zoom in until its loop
        # no longer fits.
        half = min(max(half, self._min_half), self._max_half)
        if not self._view_init:
            self._half, self._view_init = half, True
            return
        a = 0.03  # slow EMA so short freezes show without the view jumping
        self._half += a * (half - self._half)

    def _project(self, x: float, y: float) -> tuple[int, int]:
        ppm = (self._size / 2.0 - 40.0) / max(0.5, self._half)
        col = self._size / 2.0 - y * ppm
        row = self._size / 2.0 - x * ppm
        return int(round(col)), int(round(row))

    def render_once(self) -> None:
        now_ns = self.get_clock().now().nanoseconds
        poses = []
        for index, ns in enumerate(self._robots):
            pose = self._pose(ns)
            if pose is not None:
                x, y, yaw = pose
                offset_x, offset_y = _fleet_offset(index, len(self._robots), self._spacing)
                pose = (x + offset_x, y + offset_y, yaw)
            poses.append((ns, pose))
        live = [p for _, p in poses if p is not None]
        if live:
            self._update_view(live)
        frame = self.pristine.copy()
        ages = [(ns, self._freshness_ms(ns, now_ns)) for ns in self._robots]
        self._publish_freshness(ages)
        status_width = max(1, self._size // max(1, len(ages)))
        for index, (ns, age_ms) in enumerate(ages):
            color = _freshness_color(age_ms, self._degraded_ms, self._stale_ms)
            left = index * status_width
            right = self._size if index == len(ages) - 1 else left + status_width
            frame[:28, left:right] = color
            label = chr(ord("A") + index) if index < 7 else ns[-1:].upper()
            age_label = "9999" if math.isinf(age_ms) else str(min(9999, round(age_ms)))
            _draw_text(frame, f"{label}:{age_label}MS", left + 8, 6, (255, 255, 255), 3)
        for index, (ns, pose) in enumerate(poses):
            if pose is None:
                continue
            x, y, _ = pose
            trail = self._trails.setdefault(ns, deque(maxlen=600))
            if not trail or math.hypot(x - trail[-1][0], y - trail[-1][1]) >= 0.05:
                trail.append((x, y))
            points = [self._project(point_x, point_y) for point_x, point_y in trail]
            trail_color = tuple(channel * 2 // 3 for channel in PALETTE[index % len(PALETTE)])
            for start, end in zip(points, points[1:]):
                _draw_line(frame, start, end, trail_color)
        placed = 0
        for index, (ns, pose) in enumerate(poses):
            if pose is None:
                continue
            x, y, yaw = pose
            col, row = self._project(x, y)
            _, rot, oc, orr = self.atlas.lookup(yaw)
            if alpha_blit(frame, rot, int(round(row - orr)), int(round(col - oc))) is not None:
                placed += 1
            # a solid color dot marks each robot even when zoomed out / off-icon
            r = min(max(int(row), 3), self._size - 4)
            c = min(max(int(col), 3), self._size - 4)
            cr, cg, cb = PALETTE[index % len(PALETTE)]
            frame[r - 3:r + 4, c - 3:c + 4] = (cr, cg, cb)
            freshness_color = _freshness_color(
                ages[index][1], self._degraded_ms, self._stale_ms
            )
            frame[max(0, r - 7):min(self._size, r + 8), max(0, c - 7)] = freshness_color
            frame[max(0, r - 7):min(self._size, r + 8), min(self._size - 1, c + 7)] = freshness_color
            frame[max(0, r - 7), max(0, c - 7):min(self._size, c + 8)] = freshness_color
            frame[min(self._size - 1, r + 7), max(0, c - 7):min(self._size, c + 8)] = freshness_color
        self._msg.header.stamp = self.get_clock().now().to_msg()
        self._msg.data = frame.tobytes()
        self.pub.publish(self._msg)
        encoded, jpeg = cv2.imencode(
            ".jpg",
            cv2.cvtColor(frame, cv2.COLOR_RGB2BGR),
            [cv2.IMWRITE_JPEG_QUALITY, 85],
        )
        if encoded:
            compressed = CompressedImage()
            compressed.header = self._msg.header
            compressed.format = "jpeg"
            compressed.data = jpeg.tobytes()
            self.compressed_pub.publish(compressed)
        now = time.monotonic()
        if now - self._last_log > 3.0:
            self._last_log = now
            self.get_logger().info(
                f"fleet_map: {placed}/{len(self._robots)} robots  "
                f"freshness_ms={[round(age) for _, age in ages]}  "
                f"half={self._half:.1f}m"
            )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Fleet operator-map compositor (Lab 3 climax)")
    ap.add_argument("--robots", default="", help="comma-separated namespaces; empty = auto-discover from tf")
    ap.add_argument("--anchor", default="odom",
                    help="per-robot reference frame suffix (dynamic {ns}/odom is reliable across the AP)")
    ap.add_argument("--rate", type=float, default=10.0)
    ap.add_argument("--model", default="a300", help="robot sprite model (a300|r100|j100)")
    ap.add_argument("--size", type=int, default=900, help="output image size (px, square)")
    ap.add_argument("--pad", type=float, default=1.4, help="view padding factor around the fleet")
    ap.add_argument("--spacing", type=float, default=4.0,
                    help="meters between independent robot odometry origins")
    ap.add_argument("--degraded-ms", type=float, default=60.0,
                    help="freshness age that changes a robot status to amber")
    ap.add_argument("--stale-ms", type=float, default=1000.0,
                    help="freshness age that changes a robot status to red")
    ap.add_argument("--angle-steps", type=int, default=256)
    ap.add_argument("--max-view", type=float, default=250.0,
                    help="largest half-extent (m) the auto-fit may zoom out to")
    ap.add_argument("--min-view", type=float, default=8.0,
                    help="smallest half-extent (m); keeps a lone robot's loop in frame")
    args = ap.parse_args(argv)

    rclpy.init()
    node = FleetMap(args.robots.split(","), args.anchor, args.rate,
                    args.model, args.size, args.angle_steps, args.pad, args.spacing,
                    args.degraded_ms, args.stale_ms, args.max_view, args.min_view)

    # Spin the node (TF listener) on a background thread; render on the main thread
    # at a steady rate so TF callback load can't throttle the map.
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()

    period = 1.0 / max(1e-3, args.rate)
    next_discover = 0.0
    try:
        while rclpy.ok():
            start = time.monotonic()
            if not node._fixed_robots and start >= next_discover:
                node._discover()
                next_discover = start + 2.0
            node.render_once()
            slack = period - (time.monotonic() - start)
            if slack > 0:
                time.sleep(slack)
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
