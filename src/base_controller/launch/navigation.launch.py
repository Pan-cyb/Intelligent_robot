import os
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    pkg_share = get_package_share_directory('base_controller')
    ldlidar_pkg = get_package_share_directory('ldlidar_ros2')
    map_path = os.path.join(pkg_share, 'my_map1.yaml')
    params_file = os.path.join(pkg_share, 'my_nav2_params.yaml')
    rviz_config = os.path.join(pkg_share, 'navigation.rviz')
    use_rviz = LaunchConfiguration('use_rviz')

    common = {'use_sim_time': False}
    ldlidar_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([
            ldlidar_pkg,
            '/launch/ld06.launch.py'
        ])
    )

    # 辅助函数：创建 Nav2 节点
    def nav2_node(package, executable, name, remappings=None):
        return Node(
            package=package,
            executable=executable,
            name=name,
            output='screen',
            parameters=[params_file, common],
            remappings=remappings or []
        )

    return LaunchDescription([
        DeclareLaunchArgument('use_rviz', default_value='false'),
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
        nav2_node(
            'nav2_controller',
            'controller_server',
            'controller_server',
            remappings=[('cmd_vel', 'cmd_vel_nav')]
        ),
        nav2_node('nav2_behaviors', 'behavior_server', 'behavior_server'),
        nav2_node('nav2_bt_navigator', 'bt_navigator', 'bt_navigator'),
        Node(
            package='nav2_velocity_smoother',
            executable='velocity_smoother',
            name='velocity_smoother',
            output='screen',
            parameters=[params_file, common],
            remappings=[
                ('cmd_vel', 'cmd_vel_nav'),
                ('cmd_vel_smoothed', 'cmd_vel')
            ]
        ),
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
                    'bt_navigator',
                    'velocity_smoother'
                ]}
            ]
        ),
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            output='screen',
            arguments=['-d', rviz_config],
            parameters=[common],
            condition=IfCondition(use_rviz),
        )
    ])
