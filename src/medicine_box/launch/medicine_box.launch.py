from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pwm_pin = LaunchConfiguration("pwm_pin")
    pwm_frequency_hz = LaunchConfiguration("pwm_frequency_hz")
    dry_run = LaunchConfiguration("dry_run")
    config_file = LaunchConfiguration("config_file")

    return LaunchDescription(
        [
            DeclareLaunchArgument("pwm_pin", default_value="33"),
            DeclareLaunchArgument("pwm_frequency_hz", default_value="50.0"),
            DeclareLaunchArgument("dry_run", default_value="false"),
            DeclareLaunchArgument(
                "config_file",
                default_value="",
                description="Optional medicine binding YAML path.",
            ),
            Node(
                package="medicine_box",
                executable="medicine_box_node",
                name="medicine_box",
                output="screen",
                parameters=[
                    {
                        "pwm_pin": pwm_pin,
                        "pwm_frequency_hz": pwm_frequency_hz,
                        "dry_run": dry_run,
                        "config_file": config_file,
                    }
                ],
            ),
        ]
    )
