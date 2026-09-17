"""Demo launch: raycast LaserScan against a URDF box world.

Runs:
  * robot_state_publisher  — publishes the static wall TF + /robot_description
  * a "mover"              — broadcasts the world -> laser transform
        mover:=circle  -> demo_mover drives the sensor in a circle (default)
        mover:=manual  -> pose_broadcaster reads live x/y/z/yaw parameters
        mover:=none    -> no mover (publish the transform yourself)
  * laserscan_node         — raycasts the URDF boxes and publishes /scan
  * foxglove_bridge        — optional (bridge:=true) so /scan + TF show in Lichtblick
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import Command, LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """Build the demo launch: robot_state_publisher, a mover, laserscan_node, bridge."""
    pkg_share = get_package_share_directory("urdf_raycast_sensors")
    default_urdf = os.path.join(pkg_share, "urdf", "demo_walls.urdf.xacro")

    arg_urdf = DeclareLaunchArgument(
        "urdf",
        default_value=default_urdf,
        description="Path to the URDF/xacro obstacle world.",
    )
    arg_tf_prefix = DeclareLaunchArgument(
        "tf_prefix",
        default_value="demo",
        description="Namespace prefix applied to the world links/joints.",
    )
    arg_fixed_frame = DeclareLaunchArgument(
        "fixed_frame",
        default_value=[LaunchConfiguration("tf_prefix"), "/world"],
        description="Frame the URDF obstacles are resolved in.",
    )
    arg_sensor_frame = DeclareLaunchArgument(
        "sensor_frame",
        default_value="laser",
        description="TF frame of the virtual laser (moved by the mover).",
    )
    arg_mover = DeclareLaunchArgument(
        "mover",
        default_value="circle",
        description="Sensor mover: 'circle' (auto), 'manual' (live params), or 'none'.",
    )
    arg_bridge = DeclareLaunchArgument(
        "bridge",
        default_value="true",
        description="Run foxglove_bridge so /scan + TF are visible in Lichtblick.",
    )
    arg_x = DeclareLaunchArgument(
        "x", default_value="0.0", description="Manual mover initial sensor X."
    )
    arg_y = DeclareLaunchArgument(
        "y", default_value="0.0", description="Manual mover initial sensor Y."
    )
    arg_z = DeclareLaunchArgument(
        "z", default_value="0.5", description="Manual mover initial sensor Z."
    )
    arg_yaw = DeclareLaunchArgument(
        "yaw", default_value="0.0", description="Manual mover initial sensor yaw (rad)."
    )

    urdf = LaunchConfiguration("urdf")
    tf_prefix = LaunchConfiguration("tf_prefix")
    fixed_frame = LaunchConfiguration("fixed_frame")
    sensor_frame = LaunchConfiguration("sensor_frame")
    mover = LaunchConfiguration("mover")

    robot_description = ParameterValue(
        Command(["xacro ", urdf, " tf_prefix:=", tf_prefix]), value_type=str
    )

    use_circle = IfCondition(PythonExpression(["'", mover, "' == 'circle'"]))
    use_manual = IfCondition(PythonExpression(["'", mover, "' == 'manual'"]))

    node_rsp = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        name="robot_state_publisher",
        output="screen",
        parameters=[{"robot_description": robot_description}],
    )

    node_mover_circle = Node(
        package="urdf_raycast_sensors",
        executable="demo_mover",
        name="demo_mover",
        output="screen",
        condition=use_circle,
        parameters=[
            {
                "fixed_frame": fixed_frame,
                "sensor_frame": sensor_frame,
            }
        ],
    )

    node_mover_manual = Node(
        package="urdf_raycast_sensors",
        executable="pose_broadcaster",
        name="urdf_raycast_pose_broadcaster",
        output="screen",
        condition=use_manual,
        parameters=[
            {
                "fixed_frame": fixed_frame,
                "sensor_frame": sensor_frame,
                "x": LaunchConfiguration("x"),
                "y": LaunchConfiguration("y"),
                "z": LaunchConfiguration("z"),
                "yaw": LaunchConfiguration("yaw"),
            }
        ],
    )

    node_laserscan = Node(
        package="urdf_raycast_sensors",
        executable="laserscan_node",
        name="urdf_raycast_laserscan",
        output="screen",
        parameters=[
            {
                "robot_description": robot_description,
                "fixed_frame": fixed_frame,
                "sensor_frame": sensor_frame,
            }
        ],
    )

    node_bridge = Node(
        package="foxglove_bridge",
        executable="foxglove_bridge",
        name="foxglove_bridge",
        output="screen",
        condition=IfCondition(LaunchConfiguration("bridge")),
        parameters=[{"port": 8765, "address": "0.0.0.0"}],
    )

    return LaunchDescription(
        [
            arg_urdf,
            arg_tf_prefix,
            arg_fixed_frame,
            arg_sensor_frame,
            arg_mover,
            arg_bridge,
            arg_x,
            arg_y,
            arg_z,
            arg_yaw,
            node_rsp,
            node_mover_circle,
            node_mover_manual,
            node_laserscan,
            node_bridge,
        ]
    )
