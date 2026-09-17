import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():
    default_assets = os.path.join(
        get_package_share_directory("dynamic_image_publisher"), "assets"
    )

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
    arg_image_frame_id = DeclareLaunchArgument(
        "image_frame_id",
        default_value="camera",
        description="Frame ID stamped on the published image and camera info.",
    )
    arg_assets_dir = DeclareLaunchArgument(
        "assets_dir",
        default_value=default_assets,
        description="Directory containing world/ and sprites/ assets.",
    )

    base_frame = PythonExpression(
        ["'", LaunchConfiguration("frame_id"), "' + '/base_link'"]
    )

    node = Node(
        package="dynamic_image_publisher",
        executable="dynamic_image_node",
        name="dynamic_image_publisher",
        output="screen",
        parameters=[
            {
                "assets_dir": LaunchConfiguration("assets_dir"),
                "robot_model": LaunchConfiguration("robot_model"),
                "world_name": LaunchConfiguration("world_name"),
                "world_frame": LaunchConfiguration("world_frame"),
                "base_frame": base_frame,
                "image_frame_id": LaunchConfiguration("image_frame_id"),
                "publish_rate": LaunchConfiguration("publish_rate"),
            }
        ],
        remappings=[
            ("image_raw", "camera/image_raw"),
            ("camera_info", "camera/camera_info"),
        ],
    )

    return LaunchDescription(
        [
            arg_robot_model,
            arg_frame_id,
            arg_world_frame,
            arg_world_name,
            arg_publish_rate,
            arg_image_frame_id,
            arg_assets_dir,
            node,
        ]
    )
