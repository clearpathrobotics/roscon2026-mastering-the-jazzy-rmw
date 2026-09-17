import tempfile
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _build_rviz_node(context):
    robot_namespace = LaunchConfiguration("robot_namespace").perform(context).strip("/")
    frame_id = LaunchConfiguration("frame_id").perform(context).strip("/")

    if not robot_namespace:
        raise RuntimeError("robot_namespace must not be empty")

    package_share = Path(get_package_share_directory("mock_robot_viz"))
    rviz_template_path = package_share / "rviz" / "mock_robot_viz_template.rviz"

    with rviz_template_path.open("r", encoding="utf-8") as template_file:
        template = template_file.read()

    rendered = template.replace("__ROBOT_NAMESPACE__", robot_namespace)
    rendered = rendered.replace("__FRAME_ID__", frame_id)

    temp_file = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".rviz",
        prefix=f"{robot_namespace}_",
        delete=False,
        encoding="utf-8",
    )
    temp_file.write(rendered)
    temp_file.flush()
    temp_file.close()

    return [
        Node(
            package="rviz2",
            executable="rviz2",
            name="mock_robot_rviz",
            output="screen",
            arguments=["-d", temp_file.name],
        )
    ]


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "robot_namespace",
                default_value="mock_robot_1",
                description="Mock robot namespace to visualize (for example: mock_robot_1)",
            ),
            DeclareLaunchArgument(
                "frame_id",
                default_value="robot1",
                description="TF frame prefix used by the selected robot (for example: robot1)",
            ),
            OpaqueFunction(function=_build_rviz_node),
        ]
    )
