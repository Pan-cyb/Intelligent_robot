import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.substitutions import LaunchConfiguration
from launch.actions import DeclareLaunchArgument
from launch_ros.actions import Node


def generate_launch_description():
    pkg_share = get_package_share_directory("base_controller")
    map_path = os.path.join(pkg_share, "my_map1.yaml")
    rviz_config = os.path.join(pkg_share, "waypoint_calibration.rviz")
    workspace_root = os.path.abspath(os.path.join(pkg_share, "..", "..", "..", ".."))
    source_poses_file = os.path.join(workspace_root, "src", "base_controller", "maps", "named_poses.yaml")
    poses_file = (
        source_poses_file
        if os.path.exists(os.path.dirname(source_poses_file))
        else os.path.join(pkg_share, "named_poses.yaml")
    )

    use_sim_time = LaunchConfiguration("use_sim_time")
    map_file = LaunchConfiguration("map")
    poses_file_arg = LaunchConfiguration("poses_file")

    common = {"use_sim_time": use_sim_time}

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("map", default_value=map_path),
            DeclareLaunchArgument("poses_file", default_value=poses_file),
            Node(
                package="nav2_map_server",
                executable="map_server",
                name="map_server",
                output="screen",
                parameters=[{"yaml_filename": map_file}, common],
            ),
            Node(
                package="nav2_lifecycle_manager",
                executable="lifecycle_manager",
                name="lifecycle_manager_waypoint_calibration",
                output="screen",
                parameters=[
                    common,
                    {"autostart": True},
                    {"node_names": ["map_server"]},
                ],
            ),
            Node(
                package="base_controller",
                executable="waypoint_manager",
                name="waypoint_manager",
                output="screen",
                parameters=[
                    common,
                    {
                        "goal_topic": "/waypoint_goal",
                        "map_frame": "map",
                        "poses_file": poses_file_arg,
                    },
                ],
            ),
            Node(
                package="rviz2",
                executable="rviz2",
                name="rviz2_waypoint_calibration",
                output="screen",
                arguments=["-d", rviz_config],
                parameters=[common],
            ),
        ]
    )
