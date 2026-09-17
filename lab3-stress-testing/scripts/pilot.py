#!/usr/bin/env python3
"""pilot.py - autonomous cmd_vel driver for the Lab 3 mock-robot workload.

Lab 1's mock robot only *subscribes* to cmd_vel (twist_mux `external` input on
`<ns>/cmd_vel`, priority 1, TwistStamped). Nothing drives it, so on its own the
fleet sits still and the control topic class is empty. This node fills both gaps:
it publishes a gentle autonomous wander per robot so the fleet visibly drives
around (the raycast scan and top-down image react to motion) and the control
class carries real traffic for the probe to measure.

Each namespace gets its own phase offset so the robots don't move in lockstep.
The pattern is a broad loop with small speed and curvature variations. It stays
bounded without slowing to a pivot, so motion remains legible on the fleet map.

Usage (co-located inside each robot replica, or central over the network):
    pilot.py --ns robot_7 --rate 10
    pilot.py --ns robot_a,robot_b,robot_c --rate 10 --linear 0.25 --angular 0.6
"""
from __future__ import annotations

import argparse
import hashlib
import math
import sys

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from geometry_msgs.msg import TwistStamped


def _phase(name: str) -> float:
    """Stable per-robot phase in [0, 2pi) from the namespace string."""
    digest = hashlib.blake2s(name.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big") / 2**32 * math.tau


def _command(t: float, phase: float, linear: float, angular: float) -> tuple[float, float]:
    """Return a bounded broad-loop command that never degenerates into a pivot."""
    direction = 1.0 if int(phase / (math.pi / 2.0)) % 2 == 0 else -1.0
    speed = linear * (0.9 + 0.1 * math.sin(0.17 * t + phase))
    yaw_rate = direction * angular * (0.9 + 0.1 * math.cos(0.13 * t + phase))
    return speed, yaw_rate


class Pilot(Node):
    def __init__(self, namespaces: list[str], rate: float, linear: float,
                 angular: float, base_frame: str) -> None:
        super().__init__("lab3_pilot")
        qos = QoSProfile(
            reliability=QoSReliabilityPolicy.RELIABLE,
            history=QoSHistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self._linear = linear
        self._angular = angular
        self._base_frame = base_frame
        # one publisher + phase per commanded robot
        self._pubs = []
        for ns in namespaces:
            ns = ns.strip().strip("/")
            if not ns:
                continue
            topic = f"/{ns}/cmd_vel"
            self._pubs.append((self.create_publisher(TwistStamped, topic, qos), _phase(ns)))
            self.get_logger().info(f"pilot driving {topic}")
        self._t = 0.0
        self._dt = 1.0 / max(1e-3, rate)
        self.create_timer(self._dt, self._tick)

    def _tick(self) -> None:
        self._t += self._dt
        stamp = self.get_clock().now().to_msg()
        for pub, phase in self._pubs:
            msg = TwistStamped()
            msg.header.stamp = stamp
            msg.header.frame_id = self._base_frame
            msg.twist.linear.x, msg.twist.angular.z = _command(
                self._t, phase, self._linear, self._angular
            )
            pub.publish(msg)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Autonomous cmd_vel pilot (Lab 3 mock workload)")
    ap.add_argument("--ns", required=True,
                    help="robot namespace(s), comma-separated (e.g. robot_7 or robot_a,robot_b)")
    ap.add_argument("--rate", type=float, default=10.0, help="cmd_vel publish rate (Hz)")
    ap.add_argument("--linear", type=float, default=0.45, help="forward speed (m/s)")
    ap.add_argument("--angular", type=float, default=0.1, help="nominal yaw rate (rad/s)")
    ap.add_argument("--base-frame", default="base_link", help="TwistStamped header frame_id")
    args = ap.parse_args(argv)

    rclpy.init()
    node = Pilot(args.ns.split(","), args.rate, args.linear, args.angular, args.base_frame)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
