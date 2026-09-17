# Convenience wrapper: bring up Nav2 plus a localization source for a mock robot.
#   slam:=true  -> slam.launch.py + nav2.launch.py (build a map live)
#   slam:=false -> localization.launch.py + nav2.launch.py (AMCL on a saved map)
import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    IncludeLaunchDescription,
    LogInfo,
    OpaqueFunction,
    RegisterEventHandler,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node


ARGUMENTS = [
    DeclareLaunchArgument('robot_name', default_value='mock_robot',
                          description='Robot namespace'),
    DeclareLaunchArgument('frame_id', default_value='robot',
                          description='TF prefix'),
    DeclareLaunchArgument('robot_model', default_value='a300',
                          choices=['a300', 'j100', 'r100'],
                          description='Mock robot model'),
    DeclareLaunchArgument('use_mecanum', default_value='false',
                          choices=['true', 'false'],
                          description='Mecanum/omni drivetrain'),
    DeclareLaunchArgument('use_sim_time', default_value='false',
                          choices=['true', 'false'],
                          description='Use sim time'),
    DeclareLaunchArgument('slam', default_value='false',
                          choices=['true', 'false'],
                          description='true: SLAM (build map); false: AMCL (saved map)'),
    DeclareLaunchArgument('sync', default_value='true',
                          choices=['true', 'false'],
                          description='Use synchronous SLAM (slam:=true only)'),
    DeclareLaunchArgument('tf_wait_timeout', default_value='30.0',
                          description='Seconds to wait for odom->base_link before '
                                       'failing this bringup'),
]


def on_tf_wait_exit(event, context, *, nav2_include):
    """Start navigation only on success, and never during launch shutdown."""
    if context.is_shutdown:
        return []
    if event.returncode == 0:
        return [nav2_include]
    reason = (f'TF startup gate failed (exit {event.returncode}); Nav2 was not started. '
              'Check the helper output, robot bringup and configured TF frames.')
    return [LogInfo(msg=reason), EmitEvent(event=Shutdown(reason=reason))]


def launch_setup(context, *args, **kwargs):
    pkg = get_package_share_directory('mock_robot_nav2')
    launch_dir = os.path.join(pkg, 'launch')

    robot_name = LaunchConfiguration('robot_name')
    frame_id = LaunchConfiguration('frame_id').perform(context)
    robot_model = LaunchConfiguration('robot_model')
    use_mecanum = LaunchConfiguration('use_mecanum')
    use_sim_time = LaunchConfiguration('use_sim_time')
    slam = LaunchConfiguration('slam')
    sync = LaunchConfiguration('sync')

    map_arg = DeclareLaunchArgument(
        'map',
        default_value=PathJoinSubstitution([pkg, 'maps', 'demo_walls.yaml']),
        description='Map yaml for AMCL (slam:=false)')

    slam_include = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(launch_dir, 'slam.launch.py')),
        launch_arguments=[
            ('robot_name', robot_name),
            ('frame_id', frame_id),
            ('use_sim_time', use_sim_time),
            ('sync', sync),
        ],
        condition=IfCondition(slam),
    )

    localization_include = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(launch_dir, 'localization.launch.py')),
        launch_arguments=[
            ('robot_name', robot_name),
            ('frame_id', frame_id),
            ('use_mecanum', use_mecanum),
            ('use_sim_time', use_sim_time),
            ('map', LaunchConfiguration('map')),
        ],
        condition=UnlessCondition(slam),
    )

    nav2_include = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(launch_dir, 'nav2.launch.py')),
        launch_arguments=[
            ('robot_name', robot_name),
            ('frame_id', frame_id),
            ('robot_model', robot_model),
            ('use_mecanum', use_mecanum),
            ('use_sim_time', use_sim_time),
        ],
    )

    # Robot bringup runs in a separate launch tree. Gate navigation on initial
    # odom->base_link availability, with a bounded timeout that fails closed.
    # This does not establish publisher identity or readiness of other inputs.
    #
    # /tf and /tf_static stay global (not namespace-pushed), matching nav2.launch.py's
    # own SetRemap('/tf', '/tf') for the same reason: the mock fleet shares one /tf.
    wait_for_tf = Node(
        package='mock_robot_nav2',
        executable='wait_for_tf',
        name=f'wait_for_tf_{frame_id}',
        output='screen',
        parameters=[{
            'target_frame': f'{frame_id}/odom',
            'source_frame': f'{frame_id}/base_link',
            'timeout_sec': float(LaunchConfiguration('tf_wait_timeout').perform(context)),
        }],
    )

    nav2_after_tf = RegisterEventHandler(
        OnProcessExit(
            target_action=wait_for_tf,
            on_exit=lambda event, context: on_tf_wait_exit(
                event, context, nav2_include=nav2_include),
        )
    )

    return [map_arg, slam_include, localization_include, nav2_after_tf, wait_for_tf]


def generate_launch_description():
    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(OpaqueFunction(function=launch_setup))
    return ld
