from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    pwm_pin = LaunchConfiguration("pwm_pin")
    dry_run = LaunchConfiguration("dry_run")
    config_file = LaunchConfiguration("config_file")
    initial_angle = LaunchConfiguration("initial_angle")
    move_step_delay = LaunchConfiguration("move_step_delay")
    hold_sec = LaunchConfiguration("hold_sec")

    return LaunchDescription(
        [
            DeclareLaunchArgument("pwm_pin", default_value="33"),
            DeclareLaunchArgument("dry_run", default_value="false"),
            DeclareLaunchArgument("initial_angle", default_value="0.0"),
            DeclareLaunchArgument("move_step_delay", default_value="0.03"),
            DeclareLaunchArgument("hold_sec", default_value="0.8"),
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
                        "dry_run": dry_run,
                        "config_file": config_file,
                        "initial_angle": initial_angle,
                        "move_step_delay": move_step_delay,
                        "hold_sec": hold_sec,
                    }
                ],
            ),
        ]
    )
