"""Demo launch: live top-down world view with the robot sprite at its tf2 pose.

Standalone bring-up used to test/profile ``dynamic_image_node`` without the full mock
robot stack. It supplies the ``world -> <frame_id>/base_link`` transform the node needs
(reusing the movers from ``urdf_raycast_sensors``) and runs the compositing node itself.

Runs:
  * a "mover"          — broadcasts the world -> <frame_id>/base_link transform
        mover:=circle  -> demo_mover drives the robot in a circle (default)
        mover:=manual  -> pose_broadcaster reads live x/y/z/yaw parameters
        mover:=none    -> no mover (publish the transform yourself)
  * dynamic_image_node — composites the sprite onto the world map and publishes image
  * foxglove_bridge    — optional (bridge:=true) so the image + TF show in Lichtblick

Use ``mover:=manual`` when profiling with ``profile_node --compare/--move``: the
profiler drives the pose_broadcaster's x/y/yaw parameters to move the robot.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():
    """Build the demo launch: a mover, dynamic_image_node, and an optional bridge."""
    pkg_share = get_package_share_directory("dynamic_image_publisher")
    include_node = os.path.join(pkg_share, "launch", "dynamic_image.launch.py")

    arg_robot_model = DeclareLaunchArgument(
        "robot_model",
        default_value="a300",
        description="Robot model whose sprite to overlay: a300, j100, or r100.",
    )
    arg_frame_id = DeclareLaunchArgument(
        "frame_id",
        default_value="robot",
        description="tf prefix of the robot (its base_link is <frame_id>/base_link).",
    )
    arg_world_frame = DeclareLaunchArgument(
        "world_frame",
        default_value="world",
        description="Fixed frame the top-down map is anchored to.",
    )
    arg_world_name = DeclareLaunchArgument(
        "world_name",
        default_value="world",
        description="Basename of the world map assets (world.npy/.json).",
    )
    arg_publish_rate = DeclareLaunchArgument(
        "publish_rate",
        default_value="10.0",
        description="Rate (Hz) at which the composited image is published.",
    )
    arg_mover = DeclareLaunchArgument(
        "mover",
        default_value="circle",
        description="Robot mover: 'circle' (auto), 'manual' (live params), or 'none'.",
    )
    arg_bridge = DeclareLaunchArgument(
        "bridge",
        default_value="true",
        description="Run foxglove_bridge so the image + TF are visible in Lichtblick.",
    )
    arg_x = DeclareLaunchArgument(
        "x", default_value="0.0", description="Manual mover initial robot X."
    )
    arg_y = DeclareLaunchArgument(
        "y", default_value="0.0", description="Manual mover initial robot Y."
    )
    arg_z = DeclareLaunchArgument(
        "z", default_value="0.0", description="Manual mover initial robot Z."
    )
    arg_yaw = DeclareLaunchArgument(
        "yaw", default_value="0.0", description="Manual mover initial robot yaw (rad)."
    )

    robot_model = LaunchConfiguration("robot_model")
    frame_id = LaunchConfiguration("frame_id")
    world_frame = LaunchConfiguration("world_frame")
    world_name = LaunchConfiguration("world_name")
    publish_rate = LaunchConfiguration("publish_rate")
    mover = LaunchConfiguration("mover")

    base_frame = PythonExpression(["'", frame_id, "' + '/base_link'"])

    use_circle = IfCondition(PythonExpression(["'", mover, "' == 'circle'"]))
    use_manual = IfCondition(PythonExpression(["'", mover, "' == 'manual'"]))

    node_mover_circle = Node(
        package="urdf_raycast_sensors",
        executable="demo_mover",
        name="dynamic_image_demo_mover",
        output="screen",
        condition=use_circle,
        parameters=[
            {
                "fixed_frame": world_frame,
                "sensor_frame": base_frame,
                "height": 0.0,
            }
        ],
    )

    node_mover_manual = Node(
        package="urdf_raycast_sensors",
        executable="pose_broadcaster",
        name="dynamic_image_pose_broadcaster",
        output="screen",
        condition=use_manual,
        parameters=[
            {
                "fixed_frame": world_frame,
                "sensor_frame": base_frame,
                "x": LaunchConfiguration("x"),
                "y": LaunchConfiguration("y"),
                "z": LaunchConfiguration("z"),
                "yaw": LaunchConfiguration("yaw"),
            }
        ],
    )

    include_dynamic_image = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(include_node),
        launch_arguments={
            "robot_model": robot_model,
            "frame_id": frame_id,
            "world_frame": world_frame,
            "world_name": world_name,
            "publish_rate": publish_rate,
        }.items(),
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
            arg_robot_model,
            arg_frame_id,
            arg_world_frame,
            arg_world_name,
            arg_publish_rate,
            arg_mover,
            arg_bridge,
            arg_x,
            arg_y,
            arg_z,
            arg_yaw,
            node_mover_circle,
            node_mover_manual,
            include_dynamic_image,
            node_bridge,
        ]
    )
