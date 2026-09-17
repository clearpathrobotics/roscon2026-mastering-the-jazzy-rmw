"""Interactive helper: broadcast a manually controlled ``world -> laser`` transform.

Broadcasts a ``fixed_frame -> sensor_frame`` transform built from live ``x``, ``y``,
``z`` and ``yaw`` parameters. The pose is re-read from the parameters on every timer
tick, so updating a parameter at runtime moves the virtual sensor immediately::

    ros2 param set /urdf_raycast_pose_broadcaster x 3.0
    ros2 param set /urdf_raycast_pose_broadcaster yaw 1.57

Use this instead of ``demo_mover`` when you want to drive the sensor by hand and watch
the raycast ``LaserScan`` change as the sensor frame moves.
"""

from __future__ import annotations

import math
from typing import List, Optional

import rclpy
from geometry_msgs.msg import TransformStamped
from rclpy.node import Node
from tf2_ros import TransformBroadcaster


class PoseBroadcaster(Node):
    """Broadcast a ``fixed_frame -> sensor_frame`` transform from live parameters.

    The translation (``x``, ``y``, ``z``) and heading (``yaw``) are read from ROS
    parameters every tick, so ``ros2 param set`` updates take effect immediately and
    move the virtual sensor without restarting the node.
    """

    def __init__(self) -> None:
        """Declare pose parameters and start the broadcast timer."""
        super().__init__("urdf_raycast_pose_broadcaster")

        self.declare_parameter("fixed_frame", "world")
        self.declare_parameter("sensor_frame", "laser")
        self.declare_parameter("x", 0.0)
        self.declare_parameter("y", 0.0)
        self.declare_parameter("z", 0.5)
        self.declare_parameter("yaw", 0.0)
        self.declare_parameter("rate_hz", 30.0)

        self.fixed_frame = self._str("fixed_frame")
        self.sensor_frame = self._str("sensor_frame")

        self.broadcaster = TransformBroadcaster(self)
        self.timer = self.create_timer(1.0 / self._dbl("rate_hz"), self._on_timer)

    def _str(self, name: str) -> str:
        """Return the string value of a declared parameter."""
        return self.get_parameter(name).get_parameter_value().string_value

    def _dbl(self, name: str) -> float:
        """Return the double value of a declared parameter."""
        return self.get_parameter(name).get_parameter_value().double_value

    def _on_timer(self) -> None:
        """Read the current pose parameters and broadcast them as a transform."""
        x = self._dbl("x")
        y = self._dbl("y")
        z = self._dbl("z")
        yaw = self._dbl("yaw")

        tf = TransformStamped()
        tf.header.stamp = self.get_clock().now().to_msg()
        tf.header.frame_id = self.fixed_frame
        tf.child_frame_id = self.sensor_frame
        tf.transform.translation.x = x
        tf.transform.translation.y = y
        tf.transform.translation.z = z
        tf.transform.rotation.z = math.sin(yaw / 2.0)
        tf.transform.rotation.w = math.cos(yaw / 2.0)
        self.broadcaster.sendTransform(tf)


def main(args: Optional[List[str]] = None) -> None:
    """Spin the :class:`PoseBroadcaster` until interrupted."""
    rclpy.init(args=args)
    node = PoseBroadcaster()
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
