import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    task_manager_share = get_package_share_directory("task_manager")
    locations_file = os.path.join(task_manager_share, "config", "named_locations.yaml")

    return LaunchDescription(
        [
            Node(
                package="task_manager",
                executable="task_manager_node",
                name="task_manager",
                output="screen",
                parameters=[
                    {
                        "locations_file": locations_file,
                        "auto_start_demo": False,
                        "demo_start_delay_sec": 10.0,
                        "navigation_timeout_sec": 90.0,
                        "navigation_retry_limit": 1,
                        "tts_topic": "/tts_text",
                    }
                ],
            ),
            Node(
                package="rosa_agent",
                executable="tts_node",
                name="tts_node",
                output="screen",
                parameters=[{"tts_topic": "/tts_text"}],
            ),
        ]
    )
