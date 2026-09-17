"""Block until a TF transform is available, then exit.

Launch-sequencing helper for ``nav2_bringup.launch.py``: it runs before Nav2's
own launch tree is included. Exit zero only after observing the requested
transform; timeout, invalid configuration and interruption exit nonzero.
This checks initial TF availability, not publisher identity or Nav2 readiness.
"""

from __future__ import annotations

import math
import time
from typing import List, Optional

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.time import Time
from tf2_ros import Buffer, TransformListener


def main(args: Optional[List[str]] = None) -> int:
    rclpy.init(args=args)
    try:
        return wait_for_transform()
    except (KeyboardInterrupt, ExternalShutdownException):
        return 130
    finally:
        rclpy.try_shutdown()


def wait_for_transform() -> int:
    node = Node("wait_for_tf")
    try:
        return check_transform(node)
    finally:
        node.destroy_node()


def check_transform(node: Node) -> int:
    node.declare_parameter("target_frame", "odom")
    node.declare_parameter("source_frame", "base_link")
    node.declare_parameter("timeout_sec", 30.0)
    node.declare_parameter("poll_hz", 5.0)

    target = node.get_parameter("target_frame").value
    source = node.get_parameter("source_frame").value
    timeout_sec = node.get_parameter("timeout_sec").value
    poll_hz = node.get_parameter("poll_hz").value
    if (not target or not source or
            not math.isfinite(timeout_sec) or timeout_sec <= 0 or
            not math.isfinite(poll_hz) or poll_hz <= 0):
        node.get_logger().error(
            "Frames must be non-empty; timeout_sec and poll_hz must be finite and positive"
        )
        return 2
    poll_period = 1.0 / poll_hz

    buffer = Buffer()
    listener = TransformListener(buffer, node)

    deadline = time.monotonic() + timeout_sec
    try:
        while rclpy.ok():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            if buffer.can_transform(target, source, Time()):
                node.get_logger().info(f"Transform {target} <- {source} available")
                return 0
            rclpy.spin_once(node, timeout_sec=min(poll_period, remaining))
        if not rclpy.ok():
            return 130
        node.get_logger().error(
            f"Timed out after {timeout_sec}s waiting for {target} <- {source}. "
            "Nav2 will not start. Check robot bringup, frame names and global /tf topics."
        )
        return 1
    finally:
        listener.unregister()


if __name__ == "__main__":
    raise SystemExit(main())
