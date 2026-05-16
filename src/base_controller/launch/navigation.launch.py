import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    pkg_share = get_package_share_directory('base_controller')
    ldlidar_pkg = get_package_share_directory('ldlidar_ros2')
    map_path = os.path.join(pkg_share, 'my_map1.yaml')
    params_file = os.path.join(pkg_share, 'my_nav2_params.yaml')
    rviz_config = os.path.join(pkg_share, 'navigation.rviz')

    common = {'use_sim_time': False}
    ldlidar_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            ldlidar_pkg,
            '/launch/ld06.launch.py'
        ])
    )

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
        ldlidar_launch,
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
