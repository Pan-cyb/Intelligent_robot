import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    base_controller_share = get_package_share_directory("base_controller")
    task_manager_share = get_package_share_directory("task_manager")

    navigation_launch = os.path.join(base_controller_share, "navigation.launch.py")
    default_locations_file = os.path.join(task_manager_share, "config", "named_locations.yaml")

    locations_file = LaunchConfiguration("locations_file")
    auto_start_demo = LaunchConfiguration("auto_start_demo")
    navigation_timeout_sec = LaunchConfiguration("navigation_timeout_sec")
    navigation_retry_limit = LaunchConfiguration("navigation_retry_limit")
    tts_topic = LaunchConfiguration("tts_topic")
    task_command_topic = LaunchConfiguration("task_command_topic")

    return LaunchDescription(
        [
            DeclareLaunchArgument("locations_file", default_value=default_locations_file),
            DeclareLaunchArgument("auto_start_demo", default_value="false"),
            DeclareLaunchArgument("navigation_timeout_sec", default_value="90.0"),
            DeclareLaunchArgument("navigation_retry_limit", default_value="1"),
            DeclareLaunchArgument("tts_topic", default_value="/tts_text"),
            DeclareLaunchArgument("task_command_topic", default_value="/task_command"),
            IncludeLaunchDescription(PythonLaunchDescriptionSource(navigation_launch)),
            Node(
                package="task_manager",
                executable="task_manager_node",
                name="task_manager",
                output="screen",
                parameters=[
                    {
                        "locations_file": locations_file,
                        "auto_start_demo": auto_start_demo,
                        "navigation_timeout_sec": navigation_timeout_sec,
                        "navigation_retry_limit": navigation_retry_limit,
                        "tts_topic": tts_topic,
                        "task_command_topic": task_command_topic,
                    }
                ],
            ),
            Node(
                package="rosa_agent",
                executable="tts_node",
                name="tts_node",
                output="screen",
                parameters=[{"tts_topic": tts_topic}],
            ),
        ]
    )
