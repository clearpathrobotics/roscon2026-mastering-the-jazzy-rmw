from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    package_share = Path(get_package_share_directory("mock_robot_viz"))
    rviz_config = package_share / "rviz" / "mock_robot_viz_dual.rviz"

    return LaunchDescription(
        [
            Node(
                package="rviz2",
                executable="rviz2",
                name="mock_robot_rviz_dual",
                output="screen",
                arguments=["-d", str(rviz_config)],
            )
        ]
    )
