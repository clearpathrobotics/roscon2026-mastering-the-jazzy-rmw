# SLAM (slam_toolbox) bring-up for a mock robot.
#
# slam_toolbox runs under the robot namespace (so `scan`/`map` resolve to
# /<robot_name>/...), while /tf is kept GLOBAL to match the mock. A static
# world -> <frame_id>/map transform anchors the SLAM map to the shared `world`
# frame so the synthetic wall world and the map coincide.
import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    OpaqueFunction,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node, PushRosNamespace, SetRemap

from nav2_common.launch import RewrittenYaml

from mock_robot_nav2.launch_utils import render_params


ARGUMENTS = [
    DeclareLaunchArgument('robot_name', default_value='mock_robot',
                          description='Robot namespace for the SLAM node'),
    DeclareLaunchArgument('frame_id', default_value='robot',
                          description='TF prefix injected into frame params'),
    DeclareLaunchArgument('use_sim_time', default_value='false',
                          choices=['true', 'false'],
                          description='Use sim time'),
    DeclareLaunchArgument('autostart', default_value='true',
                          choices=['true', 'false'],
                          description='Automatically start slam_toolbox'),
    DeclareLaunchArgument('use_lifecycle_manager', default_value='false',
                          choices=['true', 'false'],
                          description='Enable bond connection during node activation'),
    DeclareLaunchArgument('sync', default_value='true',
                          choices=['true', 'false'],
                          description='Use synchronous SLAM'),
]


def launch_setup(context, *args, **kwargs):
    pkg = get_package_share_directory('mock_robot_nav2')
    pkg_slam_toolbox = get_package_share_directory('slam_toolbox')

    robot_name = LaunchConfiguration('robot_name').perform(context)
    frame_id = LaunchConfiguration('frame_id').perform(context)
    use_sim_time = LaunchConfiguration('use_sim_time')
    autostart = LaunchConfiguration('autostart')
    use_lifecycle_manager = LaunchConfiguration('use_lifecycle_manager')
    sync = LaunchConfiguration('sync')

    rendered = render_params(
        os.path.join(pkg, 'config', 'slam.template.yaml'),
        {'frame_id': frame_id},
        name_hint=robot_name,
    )
    # slam_toolbox's launch does not nest params under the namespace, so nest the
    # already-rendered file under the robot namespace for the node to match it.
    slam_params = RewrittenYaml(
        source_file=rendered,
        root_key=robot_name,
        param_rewrites={},
        convert_types=True,
    )

    launch_sync = PathJoinSubstitution(
        [pkg_slam_toolbox, 'launch', 'online_sync_launch.py'])
    launch_async = PathJoinSubstitution(
        [pkg_slam_toolbox, 'launch', 'online_async_launch.py'])

    world_to_map = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='world_to_map',
        arguments=['--frame-id', 'world', '--child-frame-id', frame_id + '/map'],
        output='screen',
    )

    slam = GroupAction([
        PushRosNamespace(robot_name),
        SetRemap('/tf', '/tf'),
        SetRemap('/tf_static', '/tf_static'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(launch_sync),
            launch_arguments=[
                ('use_sim_time', use_sim_time),
                ('autostart', autostart),
                ('use_lifecycle_manager', use_lifecycle_manager),
                ('slam_params_file', slam_params),
            ],
            condition=IfCondition(sync),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(launch_async),
            launch_arguments=[
                ('use_sim_time', use_sim_time),
                ('autostart', autostart),
                ('use_lifecycle_manager', use_lifecycle_manager),
                ('slam_params_file', slam_params),
            ],
            condition=UnlessCondition(sync),
        ),
    ])

    return [world_to_map, slam]


def generate_launch_description():
    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(OpaqueFunction(function=launch_setup))
    return ld
