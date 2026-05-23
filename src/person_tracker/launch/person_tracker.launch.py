from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        # Static TF: base_link → camera_link
        # Adjust xyz to match your camera's mounting position
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='base_to_camera',
            arguments=['0.1', '0', '0.2', '0', '0', '0', 'base_link', 'camera_link'],
        ),
        # Person tracker node
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
                'debug_window': False,
            }],
        ),
    ])
