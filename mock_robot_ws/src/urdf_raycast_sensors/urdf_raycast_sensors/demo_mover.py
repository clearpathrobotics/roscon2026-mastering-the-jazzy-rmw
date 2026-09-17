"""Demo helper: broadcast a moving ``world -> laser`` transform.

Drives the virtual sensor link in a circle so the raycast LaserScan visibly changes
as the sensor "moves around" the room. Purely for demonstration/testing.
"""

from __future__ import annotations

import math
from typing import List, Optional

import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.node import Node
from tf2_ros import TransformBroadcaster


class DemoMover(Node):
    """Broadcast a ``fixed_frame -> sensor_frame`` transform moving in a circle.

    Used only for demos/tests: it drives the virtual sensor link around a circular
    path so the raycast ``LaserScan`` visibly changes over time without requiring any
    external motion source.
    """

    def __init__(self) -> None:
        """Declare motion parameters and start the broadcast timer."""
        super().__init__("urdf_raycast_demo_mover")

        self.declare_parameter("fixed_frame", "world")
        self.declare_parameter("sensor_frame", "laser")
        self.declare_parameter("radius", 2.5)
        self.declare_parameter("period_s", 20.0)
        self.declare_parameter("height", 0.5)
        self.declare_parameter("rate_hz", 30.0)

        self.fixed_frame = self._str("fixed_frame")
        self.sensor_frame = self._str("sensor_frame")
        self.radius = self._dbl("radius")
        self.period_s = max(self._dbl("period_s"), 1e-3)
        self.height = self._dbl("height")

        self.broadcaster = TransformBroadcaster(self)
        self.start = self.get_clock().now()
        self.timer = self.create_timer(1.0 / self._dbl("rate_hz"), self._on_timer)

    def _str(self, name: str) -> str:
        """Return the string value of a declared parameter."""
        return self.get_parameter(name).get_parameter_value().string_value

    def _dbl(self, name: str) -> float:
        """Return the double value of a declared parameter."""
        return self.get_parameter(name).get_parameter_value().double_value

    def _on_timer(self) -> None:
        """Compute the current circular pose and broadcast it as a transform."""
        elapsed = (self.get_clock().now() - self.start).nanoseconds * 1e-9
        theta = 2.0 * math.pi * (elapsed / self.period_s)

        tf = TransformStamped()
        tf.header.stamp = self.get_clock().now().to_msg()
        tf.header.frame_id = self.fixed_frame
        tf.child_frame_id = self.sensor_frame
        tf.transform.translation.x = self.radius * math.cos(theta)
        tf.transform.translation.y = self.radius * math.sin(theta)
        tf.transform.translation.z = self.height
        # Face along the direction of travel (yaw = theta + 90 deg).
        yaw = theta + math.pi / 2.0
        tf.transform.rotation.z = math.sin(yaw / 2.0)
        tf.transform.rotation.w = math.cos(yaw / 2.0)
        self.broadcaster.sendTransform(tf)


def main(args: Optional[List[str]] = None) -> None:
    """Spin the :class:`DemoMover` until interrupted."""
    rclpy.init(args=args)
    node = DemoMover()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
