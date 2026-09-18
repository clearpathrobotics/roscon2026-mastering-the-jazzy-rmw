#!/usr/bin/env python3
"""Synthetic multi-class publisher — generates a temporary stand-in bag.

Publishes one topic per workshop class, named to match the `match` regexes in
benchmark.yaml, so a short MCAP recording of these can substitute for the real
dataset during a test drive:

  sensor  -> /camera/image_raw  (sensor_msgs/Image, ~37 KB, 10 Hz)
  control -> /cmd_vel           (geometry_msgs/Twist, 20 Hz)
  state   -> /tf                (tf2_msgs/TFMessage, 30 Hz)
"""
import math

import rclpy
from rclpy.node import Node

from sensor_msgs.msg import Image
from geometry_msgs.msg import Twist, TransformStamped
from tf2_msgs.msg import TFMessage


class Gen(Node):
    def __init__(self):
        super().__init__("bag_gen")
        self.img_pub = self.create_publisher(Image, "/camera/image_raw", 5)
        self.cmd_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.tf_pub = self.create_publisher(TFMessage, "/tf", 30)
        # 128x96 rgb8 = ~37 KB/frame (~25 UDP fragments) @ 10 Hz = ~3 Mbit/s per
        # publisher — a real sensor stream that degrades *gracefully* under mild
        # loss instead of dropping ~100% (a 160x240 frame fragments so heavily
        # that any single lost fragment kills the whole image -> total wipeout).
        self.width, self.height = 128, 96
        self.frame = bytes(self.width * self.height * 3)  # rgb8
        self.n = 0
        self.create_timer(0.1, self.on_img)        # 10 Hz
        self.create_timer(0.05, self.on_cmd)       # 20 Hz
        self.create_timer(1.0 / 30.0, self.on_tf)  # 30 Hz

    def on_img(self):
        m = Image()
        m.header.stamp = self.get_clock().now().to_msg()
        m.header.frame_id = "camera"
        m.height, m.width = self.height, self.width
        m.encoding = "rgb8"
        m.is_bigendian = 0
        m.step = self.width * 3
        m.data = self.frame
        self.img_pub.publish(m)

    def on_cmd(self):
        self.n += 1
        t = Twist()
        t.linear.x = 0.5
        t.angular.z = 0.2 * math.sin(self.n / 20.0)
        self.cmd_pub.publish(t)

    def on_tf(self):
        tf = TransformStamped()
        tf.header.stamp = self.get_clock().now().to_msg()
        tf.header.frame_id = "odom"
        tf.child_frame_id = "base_link"
        tf.transform.rotation.w = 1.0
        self.tf_pub.publish(TFMessage(transforms=[tf]))


def main():
    rclpy.init()
    node = Gen()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
