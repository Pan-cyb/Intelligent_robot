import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    config_path = os.path.join(
        get_package_share_directory('ascamera'), 'configurationfiles'
    )

    ascamera_node = Node(
        namespace='ascamera_hp60c',
        package='ascamera',
        executable='ascamera_node',
        respawn=True,
        output='both',
        parameters=[
            {'usb_bus_no': -1},
            {'usb_path': 'null'},
            {'confiPath': config_path},
            {'color_pcl': False},
            {'pub_tfTree': True},
            {'depth_width': 640},
            {'depth_height': 480},
            {'rgb_width': 640},
            {'rgb_height': 480},
            {'fps': 25},
        ],
        remappings=[],
    )

    return LaunchDescription([ascamera_node])
