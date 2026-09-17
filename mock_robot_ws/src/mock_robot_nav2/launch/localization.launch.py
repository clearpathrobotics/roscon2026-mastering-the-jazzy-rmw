# AMCL localization (on a saved map) bring-up for a mock robot.
#
# nav2_bringup's localization_launch runs map_server + amcl under the robot
# namespace; /tf is forced GLOBAL to match the mock. A static
# world -> <frame_id>/map transform anchors the map to the shared `world` frame.
import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    OpaqueFunction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node, PushRosNamespace, SetRemap

from mock_robot_nav2.launch_utils import amcl_motion_model_for, render_params


ARGUMENTS = [
    DeclareLaunchArgument('robot_name', default_value='mock_robot',
                          description='Robot namespace for the localization nodes'),
    DeclareLaunchArgument('frame_id', default_value='robot',
                          description='TF prefix injected into frame params'),
    DeclareLaunchArgument('use_mecanum', default_value='false',
                          choices=['true', 'false'],
                          description='Mecanum/omni drivetrain (selects AMCL motion model)'),
    DeclareLaunchArgument('use_sim_time', default_value='false',
                          choices=['true', 'false'],
                          description='Use sim time'),
]


def launch_setup(context, *args, **kwargs):
    pkg = get_package_share_directory('mock_robot_nav2')
    pkg_nav2_bringup = get_package_share_directory('nav2_bringup')

    robot_name = LaunchConfiguration('robot_name').perform(context)
    frame_id = LaunchConfiguration('frame_id').perform(context)
    use_mecanum = LaunchConfiguration('use_mecanum').perform(context)
    use_sim_time = LaunchConfiguration('use_sim_time')
    map_yaml = LaunchConfiguration('map')

    params = render_params(
        os.path.join(pkg, 'config', 'localization.template.yaml'),
        {
            'frame_id': frame_id,
            'amcl_motion_model': amcl_motion_model_for(use_mecanum),
        },
        name_hint=robot_name,
    )

    localization_launch = PathJoinSubstitution(
        [pkg_nav2_bringup, 'launch', 'localization_launch.py'])

    world_to_map = Node(
        package='tf2_ros',
        executable='static_transform_publisher',
        name='world_to_map',
        arguments=['--frame-id', 'world', '--child-frame-id', frame_id + '/map'],
        output='screen',
    )

    localization = GroupAction([
        PushRosNamespace(robot_name),
        SetRemap('/tf', '/tf'),
        SetRemap('/tf_static', '/tf_static'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(localization_launch),
            launch_arguments=[
                ('namespace', robot_name),
                ('map', map_yaml),
                ('use_sim_time', use_sim_time),
                ('params_file', params),
            ],
        ),
    ])

    return [world_to_map, localization]


def generate_launch_description():
    pkg = get_package_share_directory('mock_robot_nav2')
    map_arg = DeclareLaunchArgument(
        'map',
        default_value=PathJoinSubstitution([pkg, 'maps', 'demo_walls.yaml']),
        description='Full path to map yaml file to load')

    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(map_arg)
    ld.add_action(OpaqueFunction(function=launch_setup))
    return ld
