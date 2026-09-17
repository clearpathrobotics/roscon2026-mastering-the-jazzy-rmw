"""ROS-backed regression tests; run with python3 -m unittest discover -s test."""

import importlib.util
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest

from launch import LaunchDescription, LaunchService
from launch.actions import (
    EmitEvent, ExecuteProcess, OpaqueFunction, RegisterEventHandler, TimerAction,
)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from types import SimpleNamespace


PACKAGE = Path(__file__).resolve().parents[1]
HELPER = PACKAGE / 'mock_robot_nav2' / 'wait_for_tf.py'
spec = importlib.util.spec_from_file_location(
    'bringup', PACKAGE / 'launch' / 'nav2_bringup.launch.py')
bringup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bringup)


class TfStartupTest(unittest.TestCase):
    def helper_command(self, *params):
        return [sys.executable, str(HELPER), '--ros-args',
                '-p', 'target_frame:=gate_test/odom',
                '-p', 'source_frame:=gate_test/base_link', *params]

    def run_gate(self, command, *, interrupt=False):
        """Exercise real process exit events with a sentinel Nav2 include."""
        started = []
        sentinel = OpaqueFunction(function=lambda context: started.append(True))
        helper = ExecuteProcess(cmd=command, output='screen')
        handler = RegisterEventHandler(OnProcessExit(
            target_action=helper,
            on_exit=lambda event, context: bringup.on_tf_wait_exit(
                event, context, nav2_include=sentinel)))
        service = LaunchService()
        actions = [handler, helper]
        if interrupt:
            actions.append(TimerAction(period=1.0, actions=[
                EmitEvent(event=Shutdown(reason='Test user interruption'))]))
        service.include_launch_description(LaunchDescription(actions))
        service.run()
        return started

    def test_timeout_with_frozen_sim_time(self):
        started = time.monotonic()
        result = subprocess.run(self.helper_command(
            '-p', 'timeout_sec:=0.5', '-p', 'use_sim_time:=true'),
            capture_output=True, text=True, timeout=8)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('gate_test/odom <- gate_test/base_link', result.stderr)
        self.assertLess(time.monotonic() - started, 8)

    def test_invalid_parameters(self):
        for parameter in ('timeout_sec:=0.0', 'timeout_sec:=-1.0', 'poll_hz:=0.0'):
            with self.subTest(parameter=parameter):
                result = subprocess.run(self.helper_command('-p', parameter),
                                        capture_output=True, text=True, timeout=8)
                self.assertEqual(result.returncode, 2, result.stderr)

    def test_timeout_does_not_start_navigation(self):
        self.assertEqual(self.run_gate(self.helper_command(
            '-p', 'timeout_sec:=0.5')), [])

    def test_crash_does_not_start_navigation(self):
        self.assertEqual(self.run_gate([sys.executable, '-c', 'raise RuntimeError()']), [])

    def test_shutdown_ignores_success(self):
        self.assertEqual(bringup.on_tf_wait_exit(
            SimpleNamespace(returncode=0), SimpleNamespace(is_shutdown=True),
            nav2_include=object()), [])

    def test_launch_shutdown_does_not_start_navigation(self):
        self.assertEqual(self.run_gate(self.helper_command(), interrupt=True), [])

    def test_interrupt(self):
        process = subprocess.Popen(self.helper_command(), stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(1)
            process.send_signal(signal.SIGINT)
            _, stderr = process.communicate(timeout=8)
            self.assertNotEqual(process.returncode, 0)
            self.assertNotIn('Traceback', stderr)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_existing_and_delayed_tf_start_navigation(self):
        # A real dynamic broadcaster exercises subscription/discovery and buffering.
        publisher_code = '''
import sys, time
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformBroadcaster
rclpy.init()
node = Node('gate_test_publisher')
broadcaster = TransformBroadcaster(node)
time.sleep(float(sys.argv[1]))
while rclpy.ok():
    msg = TransformStamped()
    msg.header.stamp = node.get_clock().now().to_msg()
    msg.header.frame_id = 'gate_test/odom'
    msg.child_frame_id = 'gate_test/base_link'
    msg.transform.rotation.w = 1.0
    broadcaster.sendTransform(msg)
    rclpy.spin_once(node, timeout_sec=0.05)
'''
        for delay in (0, 2):
            with self.subTest(delay=delay):
                publisher = subprocess.Popen(
                    [sys.executable, '-c', publisher_code, str(delay)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    if delay == 0:
                        time.sleep(1)
                    started = time.monotonic()
                    self.assertEqual(self.run_gate(self.helper_command(
                        '-p', 'timeout_sec:=5.0')), [True])
                    if delay:
                        self.assertGreaterEqual(time.monotonic() - started, delay)
                finally:
                    publisher.terminate()
                    publisher.wait(timeout=5)


if __name__ == '__main__':
    unittest.main()
