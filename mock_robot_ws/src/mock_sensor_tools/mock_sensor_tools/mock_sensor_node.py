import os
import shlex
import subprocess
from typing import List

import rclpy
from rclpy.node import Node


class MockSensorNode(Node):
    def __init__(self) -> None:
        super().__init__("mock_sensor_node")

        self.declare_parameter("bag_path", "")
        self.declare_parameter("topics", [""])
        self.declare_parameter("loop", True)
        self.declare_parameter("rate", 1.0)
        self.declare_parameter("start_offset", 0.0)
        self.declare_parameter("publish_clock", False)

        bag_path = self.get_parameter("bag_path").get_parameter_value().string_value
        topics = self._normalize_topics(
            self.get_parameter("topics").get_parameter_value().string_array_value
        )
        loop = self.get_parameter("loop").get_parameter_value().bool_value
        rate = self.get_parameter("rate").get_parameter_value().double_value
        start_offset = self.get_parameter("start_offset").get_parameter_value().double_value
        publish_clock = self.get_parameter("publish_clock").get_parameter_value().bool_value

        if not bag_path:
            self.get_logger().error("Parameter 'bag_path' must be set")
            raise RuntimeError("bag_path is required")

        if not os.path.exists(bag_path):
            self.get_logger().error("MCAP file not found: %s", bag_path)
            raise RuntimeError("bag_path does not exist")

        cmd = ["ros2", "bag", "play", bag_path]
        if topics:
            cmd.extend(["--topics", *topics])
        if loop:
            cmd.append("--loop")
        if rate != 1.0:
            cmd.extend(["--rate", str(rate)])
        if start_offset > 0.0:
            cmd.extend(["--start-offset", str(start_offset)])
        if publish_clock:
            cmd.append("--clock")

        self.get_logger().info("Starting playback command: %s", shlex.join(cmd))
        self._process = subprocess.Popen(cmd)

        self._watchdog = self.create_timer(1.0, self._check_process)

    def _normalize_topics(self, topics: List[str]) -> List[str]:
        normalized = []
        for topic in topics:
            stripped = topic.strip()
            if stripped:
                normalized.append(stripped)
        return normalized

    def _check_process(self) -> None:
        if self._process.poll() is not None:
            self.get_logger().warn(
                "ros2 bag play exited with code %d", self._process.returncode
            )
            rclpy.shutdown()

    def shutdown(self) -> None:
        if hasattr(self, "_process") and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()


def main() -> None:
    rclpy.init()
    node = MockSensorNode()
    try:
        rclpy.spin(node)
    finally:
        node.shutdown()
        node.destroy_node()


if __name__ == "__main__":
    main()
