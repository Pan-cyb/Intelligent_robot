import os
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource


def generate_launch_description():
    # Camera driver (in ascam_ros2_ws, same machine)
    ascamera_launch = os.path.expanduser(
        '~/robot_ws/src/ascam_ros2_ws/src/ascamera/launch/hp60c.launch.py'
    )

    return LaunchDescription([

        # 1. Camera driver
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(ascamera_launch),
        ),

        # 2. Static TF: base_link → camera_link (camera mounted tilted up)
        # Adjust xyz and rpy to match your camera mounting
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='base_to_camera',
            arguments=['0.1', '0', '0.2', '0', '-0.35', '0', 'base_link', 'camera_link'],
        ),

        # 3. Person tracker (MediaPipe Holistic)
        Node(
            package='person_tracker',
            executable='person_tracker_node.py',
            name='person_tracker',
            output='screen',
            parameters=[{
                'depth_scale': 0.001,
                'fall_tilt_threshold': 50.0,
                'detection_confidence': 0.6,
                'tracking_confidence': 0.5,
                'debug_window': True,
            }],
        ),

        # 4. Follower controller (Nav2-based)
        Node(
            package='follower_controller',
            executable='follower_nav2_controller.py',
            name='follower_nav2_controller',
            output='screen',
            parameters=[{
                'follow_distance': 1.5,
                'approach_distance': 0.3,
                'goal_update_interval': 1.0,
                'lost_timeout': 5.0,
                'camera_pitch': -0.35,
            }],
        ),
    ])
