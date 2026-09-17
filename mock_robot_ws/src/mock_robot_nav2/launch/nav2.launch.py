# Nav2 (planning + control) bring-up for a mock robot.
#
# The mock uses namespaced topics (/<robot_name>/scan, .../cmd_vel, ...) but a
# GLOBAL /tf. Nav2's launch files remap ('/tf','tf'), which would namespace tf;
# the group-level SetRemap('/tf','/tf') forces it back to global to match the mock.
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
from launch_ros.actions import PushRosNamespace, SetRemap

from mock_robot_nav2.launch_utils import footprint_for, motion_model_for, render_params


ARGUMENTS = [
    DeclareLaunchArgument('robot_name', default_value='mock_robot',
                          description='Robot namespace for the Nav2 nodes'),
    DeclareLaunchArgument('frame_id', default_value='robot',
                          description='TF prefix injected into frame params'),
    DeclareLaunchArgument('robot_model', default_value='a300',
                          choices=['a300', 'j100', 'r100'],
                          description='Mock robot model (selects footprint)'),
    DeclareLaunchArgument('use_mecanum', default_value='false',
                          choices=['true', 'false'],
                          description='Mecanum/omni drivetrain (selects motion model)'),
    DeclareLaunchArgument('use_sim_time', default_value='false',
                          choices=['true', 'false'],
                          description='Use sim time'),
    DeclareLaunchArgument('autostart', default_value='true',
                          choices=['true', 'false'],
                          description='Automatically start the Nav2 lifecycle'),
]


def launch_setup(context, *args, **kwargs):
    pkg = get_package_share_directory('mock_robot_nav2')
    pkg_nav2_bringup = get_package_share_directory('nav2_bringup')

    robot_name = LaunchConfiguration('robot_name').perform(context)
    frame_id = LaunchConfiguration('frame_id').perform(context)
    robot_model = LaunchConfiguration('robot_model').perform(context)
    use_mecanum = LaunchConfiguration('use_mecanum').perform(context)

    params = render_params(
        os.path.join(pkg, 'config', 'nav2.template.yaml'),
        {
            'frame_id': frame_id,
            'footprint': footprint_for(robot_model),
            'motion_model': motion_model_for(use_mecanum),
        },
        name_hint=robot_name,
    )

    navigation_launch = PathJoinSubstitution(
        [pkg_nav2_bringup, 'launch', 'navigation_launch.py'])

    nav2 = GroupAction([
        PushRosNamespace(robot_name),
        SetRemap('/tf', '/tf'),
        SetRemap('/tf_static', '/tf_static'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(navigation_launch),
            launch_arguments=[
                ('namespace', robot_name),
                ('use_sim_time', LaunchConfiguration('use_sim_time')),
                ('autostart', LaunchConfiguration('autostart')),
                ('params_file', params),
                ('use_composition', 'False'),
            ],
        ),
    ])

    return [nav2]


def generate_launch_description():
    ld = LaunchDescription(ARGUMENTS)
    ld.add_action(OpaqueFunction(function=launch_setup))
    return ld
