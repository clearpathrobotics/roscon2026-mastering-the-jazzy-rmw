import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    default_image_path = os.path.join(
        get_package_share_directory("mock_sensor_tools"),
        "images",
        "image.jpg",
    )

    arg_image_path = DeclareLaunchArgument(
        "image_path",
        default_value=default_image_path,
        description="Path to the image file to publish.",
    )

    arg_publish_rate = DeclareLaunchArgument(
        "publish_rate",
        default_value="10.0",
        description="Rate (Hz) at which the image is published.",
    )

    arg_frame_id = DeclareLaunchArgument(
        "frame_id",
        default_value="camera",
        description="Frame ID stamped on the published image and camera info.",
    )

    image_path = LaunchConfiguration("image_path")
    publish_rate = LaunchConfiguration("publish_rate")
    frame_id = LaunchConfiguration("frame_id")

    node_image_publisher = Node(
        package="image_publisher",
        executable="image_publisher_node",
        name="image_publisher",
        output="screen",
        arguments=[image_path],
        parameters=[
            {
                "publish_rate": publish_rate,
                "frame_id": frame_id,
            }
        ],
        remappings=[
            ("image_raw", "camera/image_raw"),
            ("camera_info", "camera/camera_info"),
        ],
    )

    return LaunchDescription(
        [
            arg_image_path,
            arg_publish_rate,
            arg_frame_id,
            node_image_publisher,
        ]
    )
