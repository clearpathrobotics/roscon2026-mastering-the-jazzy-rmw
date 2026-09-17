import os
import tempfile

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    GroupAction,
    IncludeLaunchDescription,
    OpaqueFunction,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, PushRosNamespace
from launch_ros.parameter_descriptions import ParameterValue
from launch.substitutions import Command
from math import pi


# Mapping of selectable robot models to their xacro description file.
ROBOT_MODEL_URDF = {
    "a300": "a300_mock_robot.urdf.xacro",
    "r100": "r100_mock_robot.urdf.xacro",
    "j100": "j100_mock_robot.urdf.xacro",
}


def _to_topic_list(raw: str):
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _build_runtime_nodes(context):
    robot_name = LaunchConfiguration("robot_name").perform(context)
    frame_id = LaunchConfiguration("frame_id").perform(context)
    sensor_count = int(LaunchConfiguration("sensor_count").perform(context))
    use_mecanum = LaunchConfiguration("use_mecanum").perform(context).lower() == "true"
    robot_model = LaunchConfiguration("robot_model").perform(context).lower()
    half_scan = os.environ.get("HALF_SCAN") == "1"
    sensor_qos_file = LaunchConfiguration("sensor_qos_file").perform(context).strip()
    # Appended after the node's own dict so a QoS override file always wins.
    sensor_qos_params = [sensor_qos_file] if sensor_qos_file else []

    if robot_model not in ROBOT_MODEL_URDF:
        valid = ", ".join(sorted(ROBOT_MODEL_URDF))
        raise RuntimeError(
            f"Unknown robot_model '{robot_model}'. Valid choices are: {valid}."
        )

    description_share = get_package_share_directory("mock_robot_description")
    urdf_path = os.path.join(description_share, "urdf", ROBOT_MODEL_URDF[robot_model])

    bringup_share = get_package_share_directory("mock_robot_bringup")
    use_nav2 = LaunchConfiguration("use_nav2").perform(context)
    robot_description = ParameterValue(
        Command(
            [
                "xacro ",
                urdf_path,
                " robot_name:=",
                robot_name,
                " tf_prefix:=",
                frame_id,
                " use_nav2:=",
                use_nav2,
            ]
        ),
        value_type=str,
    )

    controller_file = "controllers_mecanum.yaml" if use_mecanum else "controllers_diff.yaml"
    controller_path = os.path.join(bringup_share, "config", controller_file)
    velocity_controller = "mecanum_controller" if use_mecanum else "diff_drive_controller"
    controller_frame_override_path = os.path.join(
        tempfile.gettempdir(),
        f"{robot_name}_{velocity_controller}_frames.yaml",
    )
    with open(controller_frame_override_path, "w", encoding="utf-8") as override_file:
        override_file.write(
            "\n".join(
                [
                    f"/**/{velocity_controller}:",
                    "  ros__parameters:",
                    f"    odom_frame_id: {frame_id}/odom",
                    f"    base_frame_id: {frame_id}/base_link",
                    "    tf_frame_prefix_enable: false",
                    "",
                ]
            )
        )

    ekf_path = os.path.join(bringup_share, "config", "ekf.yaml")

    nodes = [
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            namespace=robot_name,
            name="robot_state_publisher",
            parameters=[{"robot_description": robot_description}],
            output="screen",
        ),
        Node(
            package="controller_manager",
            executable="ros2_control_node",
            namespace=robot_name,
            parameters=[
                {"robot_description": robot_description},
                controller_path,
                controller_frame_override_path,
            ],
            output="screen",
        ),
        Node(
            package="controller_manager",
            executable="spawner",
            namespace=robot_name,
            arguments=[
                "joint_state_broadcaster",
                "--controller-manager",
                f"/{robot_name}/controller_manager",
                "--param-file",
                controller_path,
            ],
            output="screen",
        ),
    ]

    velocity_spawner_args = [
        velocity_controller,
        "--controller-manager",
        f"/{robot_name}/controller_manager",
        "--param-file",
        controller_path,
        "--param-file",
        controller_frame_override_path,
    ]
    # The mecanum controller subscribes to `~/reference`, but twist_mux publishes
    # to `<controller>/cmd_vel`. Remap the controller's reference topic to cmd_vel.
    if use_mecanum:
        velocity_spawner_args += [
            "--controller-ros-args",
            "-r ~/reference:=~/cmd_vel",
        ]
    nodes.append(
        Node(
            package="controller_manager",
            executable="spawner",
            namespace=robot_name,
            arguments=velocity_spawner_args,
            output="screen",
        )
    )

    twist_mux_path = os.path.join(bringup_share, "config", "twist_mux.yaml")
    teleop_config = (
        "teleop_twist_joy_mecanum.yaml" if use_mecanum else "teleop_twist_joy.yaml"
    )
    teleop_twist_joy_path = os.path.join(bringup_share, "config", teleop_config)

    nodes.append(
        Node(
            package="teleop_twist_joy",
            executable="teleop_node",
            namespace=robot_name,
            name="teleop_twist_joy_node",
            parameters=[
                teleop_twist_joy_path,
                {"publish_stamped_twist": True},
            ],
            remappings=[
                ("cmd_vel", "joy_teleop/cmd_vel"),
            ],
            output="screen",
        )
    )

    nodes.append(
        Node(
            package="twist_mux",
            executable="twist_mux",
            namespace=robot_name,
            name="twist_mux",
            parameters=[twist_mux_path],
            remappings=[
                ("cmd_vel_out", f"{velocity_controller}/cmd_vel"),
            ],
            output="screen",
        )
    )

    ekf_overrides = {
        "odom_frame": f"{frame_id}/odom",
        "base_link_frame": f"{frame_id}/base_link",
        "world_frame": f"{frame_id}/odom",
    }
    # The mecanum controller publishes odometry on `<controller>/odometry`,
    # whereas the diff_drive controller (the ekf.yaml default) uses `.../odom`.
    if use_mecanum:
        ekf_overrides["odom0"] = "mecanum_controller/odometry"

    nodes.append(
        Node(
            package="robot_localization",
            executable="ekf_node",
            namespace=robot_name,
            name="ekf_localization",
            parameters=[
                ekf_path,
                ekf_overrides,
            ],
            output="screen",
        )
    )

    for index in range(sensor_count):
        dynamic_image_share = get_package_share_directory("dynamic_image_publisher")
        dynamic_image_launch = os.path.join(
            dynamic_image_share, "launch", "dynamic_image.launch.py"
        )
        # Fully-qualified compressed output topic: image_transport reads the QoS
        # override by resolved name, so the parameter key can't be namespace-relative.
        comp_base = f"/{robot_name}/sensor_{index}/camera/image_comp"
        nodes.append(
            GroupAction(
                actions=[
                    PushRosNamespace(f"{robot_name}/sensor_{index}"),
                    IncludeLaunchDescription(
                        PythonLaunchDescriptionSource(dynamic_image_launch),
                        launch_arguments={
                            "robot_model": robot_model,
                            "frame_id": frame_id,
                            "world_frame": f"{frame_id}/world",
                            "publish_rate": "10.0",
                        }.items(),
                    ),
                    # Lazy JPEG republisher: subscribes to the raw camera stream only
                    # once a subscriber attaches to its compressed output. best_effort so
                    # a lossy link drops frames instead of retransmitting + HOL-blocking.
                    # The base `out` remap does not reach the compressed sub-topic, so
                    # `out/compressed` is remapped explicitly (image_transport 5.x).
                    Node(
                        package="image_transport",
                        executable="republish",
                        name="image_comp_republish",
                        arguments=["raw"],
                        remappings=[
                            ("in", "camera/image_raw"),
                            ("out", "camera/image_comp"),
                            ("out/compressed", "camera/image_comp/compressed"),
                        ],
                        parameters=[
                            {
                                f"qos_overrides.{comp_base}/compressed.publisher.reliability": "best_effort",
                            }
                        ],
                        output="screen",
                    ),
                ]
            )
        )

    # ------------------------------------------------------------------
    # Obstacle world + synthetic lidar (urdf_raycast_sensors)
    # ------------------------------------------------------------------
    world_share = get_package_share_directory("urdf_raycast_sensors")
    world_path = os.path.join(world_share, "urdf", "demo_walls.urdf.xacro")
    world_description = ParameterValue(
        Command(["xacro ", world_path, " tf_prefix:=", frame_id]),
        value_type=str,
    )

    # Publish the wall world on `world_description` (renamed from the default
    # `robot_description`) so it does not clash with the robot's own description.
    nodes.append(
        Node(
            package="robot_state_publisher",
            executable="robot_state_publisher",
            namespace=robot_name,
            name="world_state_publisher",
            parameters=[{"robot_description": world_description}],
            remappings=[("robot_description", "world_description")],
            output="screen",
        )
    )

    # Anchor the wall world. Plain mock: pin to the global `world`. With Nav2
    # (use_nav2=true) pin to `<frame_id>/odom` instead, so the synthetic scan's
    # world->lidar lookup resolves via odom and does NOT depend on the SLAM/AMCL
    # map->odom transform (otherwise: scan needs map->odom, map->odom needs scan).
    world_anchor = f"{frame_id}/odom" if use_nav2.lower() == "true" else "world"
    nodes.append(
        Node(
            package="tf2_ros",
            executable="static_transform_publisher",
            namespace=robot_name,
            name="world_to_world",
            arguments=["--frame-id", world_anchor, "--child-frame-id", f"{frame_id}/world"],
            output="screen",
        )
    )

    # Synthesize a LaserScan by raycasting the wall world from the lidar frame.
    nodes.append(
        Node(
            package="urdf_raycast_sensors",
            executable="laserscan_node",
            namespace=robot_name,
            name="urdf_raycast_laserscan",
            parameters=[
                {
                    "robot_description": world_description,
                    "fixed_frame": f"{frame_id}/world",
                    "sensor_frame": f"{frame_id}/lidar_link",
                    "angle_min": -pi/2 if half_scan else -pi,
                    "angle_max": pi/2 if half_scan else pi,
                    "angle_increment": pi/180,
                    "rate_hz": 10.0
                }
            ] + sensor_qos_params,
            output="screen",
        )
    )

    return nodes


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("robot_name", default_value="mock_robot"),
            DeclareLaunchArgument("frame_id", default_value="robot"),
            DeclareLaunchArgument(
                "robot_model",
                default_value="a300",
                choices=sorted(ROBOT_MODEL_URDF),
                description="Robot model to load. Supported: 'a300', 'r100', 'j100'.",
            ),
            DeclareLaunchArgument("sensor_topics", default_value="/camera/image_raw,/scan"),
            DeclareLaunchArgument("sensor_count", default_value="1"),
            DeclareLaunchArgument(
                "sensor_qos_file",
                default_value="",
                description="Optional params file with qos_overrides for the sensor publishers.",
            ),
            DeclareLaunchArgument("use_mecanum", default_value="false"),
            DeclareLaunchArgument(
                "use_nav2",
                default_value="false",
                description="Re-root the robot at base_link so Nav2/AMCL/SLAM can own map->odom.",
            ),
            OpaqueFunction(function=_build_runtime_nodes),
        ]
    )
