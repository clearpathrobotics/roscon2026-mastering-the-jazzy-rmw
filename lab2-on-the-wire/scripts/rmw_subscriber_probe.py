#!/usr/bin/env python3
# rmw_subscriber_probe.py - LAYER 1 observability (rmw subscriber, app-level; NOT tshark).
# Sustained best-effort subscriber to each robot's compressed camera AND 2D scan topics; logs
# every arrival to CSV as `t_epoch,robot,topic` (topic = camera|scan). The layer-3 tshark
# pipeline reads the SAME sweep off the wire and emits the SAME schema for side-by-side compare.
# Runs in the observer (the AP vantage that sees all robots). Transport-agnostic delivery
# measurement: it counts messages that actually arrived, so it works the same for Cyclone,
# Fast DDS, and Zenoh. A sustained subscriber (vs one-shot `ros2 topic hz`) discovers once and
# stays matched, and it also wakes the lazy image_transport republisher on each robot. Two
# payloads on one sweep so both see identical impairment: camera = large fragmented frame
# (~40KB, ~30 UDP fragments), scan = small single-packet LaserScan (~0.8KB). The contrast is
# the lesson, because the payload decides whether loss hurts.
import sys
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
from sensor_msgs.msg import CompressedImage, LaserScan


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    out = sys.argv[2] if len(sys.argv) > 2 else "/captures/bench_arrivals.csv"

    rclpy.init()
    node = Node("bench_probe")
    qos = QoSProfile(depth=10,
                     reliability=ReliabilityPolicy.BEST_EFFORT,
                     history=HistoryPolicy.KEEP_LAST)

    f = open(out, "w")
    f.write("t_epoch,robot,topic\n")
    f.flush()

    def make_cb(i, topic):
        def cb(_msg):
            f.write(f"{time.time():.6f},{i},{topic}\n")
            f.flush()
        return cb

    for i in range(1, n + 1):
        node.create_subscription(
            CompressedImage,
            f"/robot_{i}/sensor_0/camera/image_comp/compressed",
            make_cb(i, "camera"), qos)
        node.create_subscription(
            LaserScan,
            f"/robot_{i}/scan",
            make_cb(i, "scan"), qos)

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        f.close()


if __name__ == "__main__":
    main()
