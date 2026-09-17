"""ROS 2 node: publish a live top-down world view with the robot sprite overlaid.

Loads a pre-rendered top-down world map (background) and the selected robot's
pre-rendered top-down sprite (both as ``.npy`` + JSON, produced offline by the tools in
``tools/``). Each tick it looks up the robot pose from tf2 (``world_frame`` ->
``base_frame``), maps it to a map pixel, rotates the sprite by the robot yaw, blits it
onto the map (dirty-rectangle), and publishes the result as ``sensor_msgs/Image`` (plus
a matching ``CameraInfo``). This replaces the static-jpg image publisher with a dynamic,
video-like stream that reflects the robot moving through the pseudo-simulated world.

The image message is built directly from the numpy frame, so the node needs no OpenCV /
PIL / cv_bridge at runtime — only rclpy, numpy, tf2_ros and sensor_msgs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
from rclpy.qos_overriding_options import QoSOverridingOptions
from sensor_msgs.msg import CameraInfo, Image
from tf2_ros import (
    Buffer,
    ConnectivityException,
    ExtrapolationException,
    LookupException,
    TransformListener,
)

from .compositor import (
    Compositor,
    SpriteAtlas,
    load_meta,
    load_rgb,
    load_rgba,
    world_to_pixel,
    yaw_from_quaternion,
)


class DynamicImageNode(Node):
    """Publish a top-down map with the robot sprite overlaid at its tf2 pose."""

    def __init__(self) -> None:
        super().__init__("dynamic_image_node")

        share = Path(get_package_share_directory("dynamic_image_publisher"))
        self.declare_parameter("assets_dir", str(share / "assets"))
        self.declare_parameter("robot_model", "a300")
        self.declare_parameter("world_name", "world")
        self.declare_parameter("world_frame", "world")
        self.declare_parameter("base_frame", "base_link")
        self.declare_parameter("image_frame_id", "camera")
        self.declare_parameter("publish_rate", 10.0)
        # Perf knobs: bake N rotations into a lookup atlas; skip re-publishing an
        # unchanged pose; still emit a low-rate keepalive so late subscribers get a
        # frame while the robot is idle.
        self.declare_parameter("sprite_angle_steps", 256)
        self.declare_parameter("position_epsilon_px", 0.5)
        self.declare_parameter("keepalive_period", 1.0)

        assets_dir = Path(self._str("assets_dir"))
        robot_model = self._str("robot_model")
        world_name = self._str("world_name")
        self.world_frame = self._str("world_frame")
        self.base_frame = self._str("base_frame")
        self.image_frame_id = self._str("image_frame_id")
        rate_hz = self._dbl("publish_rate")
        angle_steps = self._int("sprite_angle_steps")
        position_eps = self._dbl("position_epsilon_px")
        self.keepalive_period = self._dbl("keepalive_period")

        # -- load assets --------------------------------------------------
        world_npy = assets_dir / "world" / f"{world_name}.npy"
        world_json = assets_dir / "world" / f"{world_name}.json"
        sprite_npy = assets_dir / "sprites" / f"{robot_model}.npy"
        sprite_json = assets_dir / "sprites" / f"{robot_model}.json"

        self.world_meta = load_meta(world_json)
        background = load_rgb(world_npy)
        self.sprite = load_rgba(sprite_npy)
        self.sprite_meta = load_meta(sprite_json)
        self.sprite_origin_col, self.sprite_origin_row = self.sprite_meta["origin_px"]

        if abs(
            float(self.world_meta["meters_per_pixel"])
            - float(self.sprite_meta["meters_per_pixel"])
        ) > 1e-9:
            self.get_logger().warn(
                "World and sprite meters_per_pixel differ "
                f"({self.world_meta['meters_per_pixel']} vs "
                f"{self.sprite_meta['meters_per_pixel']}); sprite scale may be off."
            )

        # Rotation atlas: rotate the sprite once per orientation bucket at startup so
        # each frame is a table lookup + blit (no per-frame trig/resampling).
        atlas = SpriteAtlas(
            self.sprite,
            self.sprite_origin_col,
            self.sprite_origin_row,
            num_angles=angle_steps,
        )
        self.compositor = Compositor(
            background, atlas=atlas, position_epsilon=position_eps
        )
        height, width = self.compositor.size

        # -- publishers ---------------------------------------------------
        # Raw frames are the heaviest thing this robot emits; allow a params file to
        # retune their QoS without editing this node.
        self.image_pub = self.create_publisher(
            Image,
            "image_raw",
            10,
            qos_overriding_options=QoSOverridingOptions.with_default_policies(),
        )
        self.info_pub = self.create_publisher(CameraInfo, "camera_info", 10)
        self.camera_info = self._make_camera_info(width, height)
        self.camera_info.header.frame_id = self.image_frame_id

        # Reuse one Image message; only its stamp + data change per publish.
        self._image_msg = Image()
        self._image_msg.height = height
        self._image_msg.width = width
        self._image_msg.encoding = "rgb8"
        self._image_msg.is_bigendian = 0
        self._image_msg.step = width * 3
        self._image_msg.header.frame_id = self.image_frame_id
        self._cached_data: Optional[bytes] = None
        self._last_publish_ns = 0

        # -- tf2 ----------------------------------------------------------
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.get_logger().info(
            f"Top-down view: model='{robot_model}', world='{world_name}' "
            f"({width}x{height}), {angle_steps} angle steps, "
            f"tf {self.world_frame} -> {self.base_frame}"
        )
        self.timer = self.create_timer(1.0 / rate_hz, self._on_timer)

    # -- parameter helpers ------------------------------------------------
    def _str(self, name: str) -> str:
        return self.get_parameter(name).get_parameter_value().string_value

    def _dbl(self, name: str) -> float:
        return self.get_parameter(name).get_parameter_value().double_value

    def _int(self, name: str) -> int:
        return self.get_parameter(name).get_parameter_value().integer_value

    # -- camera info ------------------------------------------------------
    def _make_camera_info(self, width: int, height: int) -> CameraInfo:
        info = CameraInfo()
        info.width = width
        info.height = height
        info.distortion_model = "plumb_bob"
        info.d = [0.0, 0.0, 0.0, 0.0, 0.0]
        fx = fy = float(max(width, height))
        cx, cy = width / 2.0, height / 2.0
        info.k = [fx, 0.0, cx, 0.0, fy, cy, 0.0, 0.0, 1.0]
        info.r = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
        info.p = [fx, 0.0, cx, 0.0, 0.0, fy, cy, 0.0, 0.0, 0.0, 1.0, 0.0]
        return info

    # -- main loop --------------------------------------------------------
    def _lookup_pose(self):
        """Return ``(x, y, yaw)`` of ``base_frame`` in ``world_frame`` or ``None``."""
        try:
            tf = self.tf_buffer.lookup_transform(
                self.world_frame, self.base_frame, rclpy.time.Time()
            )
        except (LookupException, ConnectivityException, ExtrapolationException) as exc:
            self.get_logger().warn(
                f"TF {self.world_frame} -> {self.base_frame} unavailable: {exc}",
                throttle_duration_sec=2.0,
            )
            return None
        t = tf.transform.translation
        q = tf.transform.rotation
        return t.x, t.y, yaw_from_quaternion(q.x, q.y, q.z, q.w)

    def _on_timer(self) -> None:
        pose = self._lookup_pose()
        if pose is None:
            return
        x, y, yaw = pose
        robot_col, robot_row = world_to_pixel(self.world_meta, x, y)
        changed = self.compositor.render_pose(robot_col, robot_row, yaw)

        now_ns = self.get_clock().now().nanoseconds
        if changed or self._cached_data is None:
            # Serialize the frame only when it actually changed.
            self._cached_data = self.compositor.frame.tobytes()
        self._publish(self._cached_data, now_ns)

    def _publish(self, data: bytes, now_ns: int) -> None:
        stamp = self.get_clock().now().to_msg()
        msg = self._image_msg
        msg.header.stamp = stamp
        msg.data = data
        self.image_pub.publish(msg)

        self.camera_info.header.stamp = stamp
        self.info_pub.publish(self.camera_info)
        self._last_publish_ns = now_ns


def main() -> None:
    rclpy.init()
    node = DynamicImageNode()
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
