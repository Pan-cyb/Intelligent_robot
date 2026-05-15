import os
from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    pkg_share = get_package_share_directory('base_controller')
    map_path = os.path.join(pkg_share, 'my_map1.yaml')
    params_file = os.path.join(pkg_share, 'my_nav2_params.yaml')
    rviz_config = os.path.join(pkg_share, 'navigation.rviz')

    common = {'use_sim_time': False}

    # 辅助函数：创建 Nav2 节点
    def nav2_node(package, executable, name):
        return Node(
            package=package,
            executable=executable,
            name=name,
            output='screen',
            parameters=[params_file, common]
        )

    return LaunchDescription([
        Node(
            package='ldlidar_ros2',
            executable='ldlidar_ros2_node',
            name='ldlidar_publisher_ld06',
            output='screen',
            parameters=[
                {'product_name': 'LDLiDAR_LD06'},
                {'laser_scan_topic_name': 'scan'},
                {'point_cloud_2d_topic_name': 'pointcloud2d'},
                {'frame_id': 'base_laser'},
                {'port_name': '/dev/ttyUSB0'},
                {'serial_baudrate': 230400},
                {'laser_scan_dir': True},
                {'enable_angle_crop_func': True},
                {'angle_crop_min': 320.0},
                {'angle_crop_max': 40.0},
                {'range_min': 0.2},
                {'range_max': 12.0}
            ]
        ),
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='static_tf_laser',
            arguments=['-0.01', '0', '0.1', '3.1415926', '0', '0', 'base_link', 'base_laser'],
        ),
        Node(
            package='base_controller',
            executable='base_controller_node',
            name='base_controller',
            output='screen',
            parameters=[common]
        ),
        Node(
            package='nav2_map_server',
            executable='map_server',
            name='map_server',
            output='screen',
            parameters=[{'yaml_filename': map_path}, common]
        ),
        nav2_node('nav2_amcl', 'amcl', 'amcl'),
        nav2_node('nav2_planner', 'planner_server', 'planner_server'),
        nav2_node('nav2_controller', 'controller_server', 'controller_server'),
        nav2_node('nav2_behaviors', 'behavior_server', 'behavior_server'),
        nav2_node('nav2_bt_navigator', 'bt_navigator', 'bt_navigator'),
        Node(
            package='nav2_lifecycle_manager',
            executable='lifecycle_manager',
            name='lifecycle_manager_navigation',
            output='screen',
            parameters=[
                common,
                {'autostart': True},
                {'node_names': [
                    'map_server',
                    'amcl',
                    'planner_server',
                    'controller_server',
                    'behavior_server',
                    'bt_navigator'
                ]}
            ]
        ),
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            output='screen',
            arguments=['-d', rviz_config],
            parameters=[common]
        )
    ])
