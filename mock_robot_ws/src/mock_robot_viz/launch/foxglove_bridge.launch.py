from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    namespace = LaunchConfiguration("namespace")
    parameters = LaunchConfiguration("parameters")

    arg_namespace = DeclareLaunchArgument(
        "namespace",
        default_value="",
        description="Robot namespace for the bridge node; leave empty to bridge the full graph",
    )

    arg_parameters = DeclareLaunchArgument(
        "parameters",
        default_value=PathJoinSubstitution(
            [FindPackageShare("mock_robot_viz"), "config", "foxglove_bridge.yaml"]
        ),
        description="Foxglove Bridge node parameters",
    )

    # Foxglove sees the full ROS graph here because the mock robots already use
    # distinct namespaces for their topics, services, and actions.
    node_bridge = Node(
        package="foxglove_bridge",
        executable="foxglove_bridge",
        namespace=namespace,
        output="screen",
        parameters=[parameters],
        additional_env={"ROS_SUPER_CLIENT": "True"},
    )

    return LaunchDescription([arg_namespace, arg_parameters, node_bridge])
