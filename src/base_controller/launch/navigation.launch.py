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
        Node(
            package='slam_toolbox',
            executable='localization_slam_toolbox_node',
            name='slam_toolbox',
            output='screen',
            parameters=[{
                'use_sim_time': False,
                'solver_plugin': 'solver_plugins::CeresSolver',
                'ceres_linear_solver': 'SPARSE_NORMAL_CHOLESKY',
                'ceres_preconditioner': 'SCHUR_JACOBI',
                'ceres_trust_strategy': 'LEVENBERG_MARQUARDT',
                'ceres_dogleg_type': 'TRADITIONAL_DOGLEG',
                'ceres_loss_function': 'None',
                'mode': 'localization',
                'map_file_name': map_path,
                'map_start_pose': [0.0, 0.0, 0.0],
                'map_frame': 'map',
                'odom_frame': 'odom',
                'base_frame': 'base_link',
                'laser_frame': 'base_laser',
                'scan_topic': '/scan',
                'debug_logging': False,
                'throttle_scans': 1,
                'use_scan_matching': True,
                'use_odometry': True,
                'transform_publish_period': 0.05,
                'map_update_interval': 0.2,
                'minimum_travel_distance': 0.02,
                'minimum_travel_heading': 0.02,
                'minimum_time_interval': 0.2,
                'transform_timeout': 0.2,
                'tf_buffer_duration': 30.0,
                'scan_queue_size': 10,
                'odom_queue_size': 10,
                'scan_buffer_size': 3,
                'scan_buffer_maximum_scan_distance': 10.0,
                'max_laser_range': 12.0,
                'min_laser_range': 0.0,
                'resolution': 0.05,
                'do_loop_closing': False,
                'correlation_search_space_dimension': 0.5,
                'correlation_search_space_resolution': 0.01,
                'correlation_search_space_smear_deviation': 0.1,
                'distance_variance_penalty': 0.5,
                'angle_variance_penalty': 1.0,
                'fine_search_angle_offset': 0.00349,
                'coarse_search_angle_offset': 0.349,
                'coarse_angle_resolution': 0.0349,
                'minimum_angle_penalty': 0.9,
                'minimum_distance_penalty': 0.5,
                'use_response_expansion': True,
                'min_pass_through': 2,
                'occupancy_threshold': 0.1,
            }]
        ),
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
