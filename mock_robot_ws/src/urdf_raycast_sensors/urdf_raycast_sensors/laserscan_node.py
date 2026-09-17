"""ROS 2 node: synthesize a 2D LaserScan by raycasting against URDF box collisions.

The obstacle world is read once from a URDF (parameter or ``/robot_description``
topic). The virtual sensor's pose is tracked from tf2, so moving the sensor link in TF
moves the scan origin. Each tick fires a fan of rays in the sensor's XY plane and
publishes the resulting ranges as ``sensor_msgs/LaserScan``.
"""

from __future__ import annotations

import array
import math
from typing import List, Optional

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import (
    QoSDurabilityPolicy,
    QoSHistoryPolicy,
    QoSProfile,
    QoSReliabilityPolicy,
)
from rclpy.qos_overriding_options import QoSOverridingOptions
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from tf2_ros import (
    Buffer,
    LookupException,
    TransformListener,
    ConnectivityException,
    ExtrapolationException,
)

from .raycast import Box, cast, ray_directions_2d
from .urdf_geometry import boxes_from_urdf


def _quat_to_matrix(x: float, y: float, z: float, w: float) -> np.ndarray:
    """Convert a quaternion to a 3x3 rotation matrix (sensor -> fixed)."""
    n = math.sqrt(x * x + y * y + z * z + w * w)
    if n == 0.0:
        return np.eye(3, dtype=float)
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ],
        dtype=float,
    )


class LaserScanNode(Node):
    """Publish a 2D ``LaserScan`` by raycasting URDF box collisions.

    The obstacle world is loaded once from a URDF (either the ``robot_description``
    parameter or the ``/robot_description`` topic) and converted to oriented boxes in
    the ``fixed_frame``. On each timer tick the node looks up the sensor link pose
    from tf2, rotates a precomputed fan of rays into the fixed frame, computes ranges
    analytically, and publishes the result. Moving the sensor link in TF therefore
    moves the virtual laser.
    """

    def __init__(self) -> None:
        """Declare parameters, load the world, and start the publish timer."""
        super().__init__("urdf_raycast_laserscan")

        self.declare_parameter("fixed_frame", "world")
        self.declare_parameter("sensor_frame", "laser")
        self.declare_parameter("scan_topic", "scan")
        self.declare_parameter("angle_min", -math.pi)
        self.declare_parameter("angle_max", math.pi)
        self.declare_parameter("angle_increment", math.pi / 360.0)
        self.declare_parameter("range_min", 0.05)
        self.declare_parameter("range_max", 30.0)
        self.declare_parameter("rate_hz", 10.0)
        self.declare_parameter("robot_description", "")
        self.declare_parameter("range_on_miss", "max")  # "max" or "inf"
        self.declare_parameter("static_pose_epsilon", 1e-6)

        self.fixed_frame = self._str("fixed_frame")
        self.sensor_frame = self._str("sensor_frame")
        self.angle_min = self._dbl("angle_min")
        self.angle_max = self._dbl("angle_max")
        self.angle_increment = self._dbl("angle_increment")
        self.range_min = self._dbl("range_min")
        self.range_max = self._dbl("range_max")
        rate_hz = self._dbl("rate_hz")

        miss = self._str("range_on_miss").lower()
        self.range_on_miss = self.range_max if miss == "max" else float("inf")

        # Precompute the ray fan in the sensor's local XY plane. Kept in float32 so
        # the per-tick raycast runs in single precision (half the memory bandwidth).
        span = self.angle_max - self.angle_min
        self.ray_count = max(int(round(span / self.angle_increment)) + 1, 1)
        self.local_dirs = ray_directions_2d(
            self.angle_min, self.angle_increment, self.ray_count
        ).astype(np.float32)

        self.boxes: List[Box] = []

        # Cache the last scan so a stationary sensor can skip the raycast entirely and
        # only re-stamp the message. Invalidated whenever the obstacle world changes.
        self.static_pose_epsilon = self._dbl("static_pose_epsilon")
        self._last_origin: Optional[np.ndarray] = None
        self._last_rotation: Optional[np.ndarray] = None
        self._last_ranges: Optional[np.ndarray] = None

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        # Opt in to ROS 2 QoS overrides so scan reliability/history can be retuned from a
        # params file without editing this node.
        self.scan_pub = self.create_publisher(
            LaserScan,
            self._str("scan_topic"),
            10,
            qos_overriding_options=QoSOverridingOptions.with_default_policies(),
        )

        # Load the world from a parameter if given, else subscribe to the description
        # topic (latched/transient-local, as published by robot_state_publisher).
        description = self._str("robot_description")
        if description.strip():
            self._load_boxes(description)
        else:
            desc_qos = QoSProfile(
                depth=1,
                history=QoSHistoryPolicy.KEEP_LAST,
                reliability=QoSReliabilityPolicy.RELIABLE,
                durability=QoSDurabilityPolicy.TRANSIENT_LOCAL,
            )
            self.create_subscription(
                String, "robot_description", self._on_description, desc_qos
            )
            self.get_logger().info(
                "Waiting for URDF on 'robot_description' topic (no parameter set)."
            )

        self.timer = self.create_timer(1.0 / rate_hz, self._on_timer)
        self.scan_time = 1.0 / rate_hz

    # -- parameter helpers -------------------------------------------------
    def _str(self, name: str) -> str:
        """Return the string value of a declared parameter."""
        return self.get_parameter(name).get_parameter_value().string_value

    def _dbl(self, name: str) -> float:
        """Return the double value of a declared parameter."""
        return self.get_parameter(name).get_parameter_value().double_value

    # -- world loading -----------------------------------------------------
    def _on_description(self, msg: String) -> None:
        """Load boxes from the first URDF received on ``/robot_description``."""
        if not self.boxes:
            self._load_boxes(msg.data)

    def _load_boxes(self, urdf_xml: str) -> None:
        """Parse ``urdf_xml`` into obstacle boxes, excluding the sensor link."""
        try:
            self.boxes = boxes_from_urdf(urdf_xml, exclude_links=[self.sensor_frame])
        except Exception as exc:  # noqa: BLE001 - report and keep node alive
            self.get_logger().error(f"Failed to parse URDF: {exc}")
            return
        # Invalidate the static-pose cache: the world changed, so cached ranges
        # computed before the boxes were loaded are no longer valid.
        self._last_ranges = None
        self.get_logger().info(f"Loaded {len(self.boxes)} box obstacle(s) from URDF.")

    # -- main loop ---------------------------------------------------------
    def _lookup_sensor_pose(self):
        """Look up the sensor pose in the fixed frame from tf2.

        Returns
        -------
        tuple[numpy.ndarray, numpy.ndarray] | None
            ``(origin, rotation)`` where ``origin`` is ``(3,)`` and ``rotation`` is a
            ``(3, 3)`` matrix mapping sensor-local vectors into the fixed frame, or
            ``None`` if the transform is currently unavailable.
        """
        try:
            tf = self.tf_buffer.lookup_transform(
                self.fixed_frame, self.sensor_frame, rclpy.time.Time()
            )
        except (
            LookupException,
            ConnectivityException,
            ExtrapolationException,
        ) as exc:
            self.get_logger().warn(
                f"TF {self.fixed_frame} -> {self.sensor_frame} unavailable: {exc}",
                throttle_duration_sec=2.0,
            )
            return None
        t = tf.transform.translation
        q = tf.transform.rotation
        origin = np.array([t.x, t.y, t.z], dtype=float)
        rotation = _quat_to_matrix(q.x, q.y, q.z, q.w)
        return origin, rotation

    def _pose_is_static(self, origin: np.ndarray, rotation: np.ndarray) -> bool:
        """Return True if the pose matches the cached one within the epsilon."""
        if self._last_ranges is None or self._last_origin is None:
            return False
        eps = self.static_pose_epsilon
        if eps < 0.0:
            return False
        if np.max(np.abs(origin - self._last_origin)) > eps:
            return False
        return np.max(np.abs(rotation - self._last_rotation)) <= eps

    def _on_timer(self) -> None:
        """Cast the ray fan from the current sensor pose and publish a scan."""
        pose = self._lookup_sensor_pose()
        if pose is None:
            return
        origin, rotation = pose

        # If the sensor hasn't moved since the last tick, the ranges are identical:
        # reuse the cached array and only re-stamp the message.
        if self._pose_is_static(origin, rotation):
            self.scan_pub.publish(self._build_scan(self._last_ranges))
            return

        # Work in float32 so the whole cast stays single precision.
        rot32 = rotation.astype(np.float32, copy=False)
        origin32 = origin.astype(np.float32, copy=False)
        dirs_fixed = self.local_dirs @ rot32.T

        if self.boxes:
            ranges = cast(
                origin32,
                dirs_fixed,
                self.boxes,
                range_min=self.range_min,
                range_max=self.range_max,
                range_on_miss=self.range_on_miss,
            )
        else:
            ranges = np.full(self.ray_count, self.range_on_miss, dtype=np.float32)

        # Update the static-pose cache.
        self._last_origin = origin
        self._last_rotation = rotation
        self._last_ranges = ranges

        self.scan_pub.publish(self._build_scan(ranges))

    def _build_scan(self, ranges: np.ndarray) -> LaserScan:
        """Assemble a ``LaserScan`` message from the computed ``ranges``."""
        scan = LaserScan()
        scan.header.stamp = self.get_clock().now().to_msg()
        scan.header.frame_id = self.sensor_frame
        scan.angle_min = self.angle_min
        scan.angle_max = self.angle_max
        scan.angle_increment = self.angle_increment
        scan.time_increment = 0.0
        scan.scan_time = self.scan_time
        scan.range_min = self.range_min
        scan.range_max = self.range_max
        # Fill the float32 range array with a C-level memcpy (no per-element Python
        # loop): array('f') matches LaserScan.ranges' element type directly.
        buf = array.array("f")
        buf.frombytes(np.ascontiguousarray(ranges, dtype=np.float32).tobytes())
        scan.ranges = buf
        return scan


def main(args: Optional[List[str]] = None) -> None:
    """Spin the :class:`LaserScanNode` until interrupted."""
    rclpy.init(args=args)
    node = LaserScanNode()
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
