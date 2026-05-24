from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    start_delay_sec = LaunchConfiguration("demo_start_delay_sec")
    wakeup_target = LaunchConfiguration("demo_wakeup_target")
    wakeup_text = LaunchConfiguration("demo_wakeup_text")
    companion_target = LaunchConfiguration("demo_companion_target")
    companion_text = LaunchConfiguration("demo_companion_text")

    return LaunchDescription(
        [
            DeclareLaunchArgument("demo_start_delay_sec", default_value="30.0"),
            DeclareLaunchArgument("demo_wakeup_target", default_value="bedroom_bedside"),
            DeclareLaunchArgument("demo_wakeup_text", default_value="早上好，该起床了。"),
            DeclareLaunchArgument("demo_companion_target", default_value="livingroom_sofa"),
            DeclareLaunchArgument(
                "demo_companion_text",
                default_value="我陪您到客厅坐一会儿，有需要可以随时叫我。",
            ),
            Node(
                package="demo_manager",
                executable="demo_manager_node",
                name="demo_manager",
                output="screen",
                parameters=[
                    {
                        "start_delay_sec": start_delay_sec,
                        "wakeup_target": wakeup_target,
                        "wakeup_text": wakeup_text,
                        "companion_target": companion_target,
                        "companion_text": companion_text,
                    }
                ],
            ),
        ]
    )
