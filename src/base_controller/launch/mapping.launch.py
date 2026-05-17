#!/usr/bin/env python3
import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

def generate_launch_description():
    # 1. 基础参数声明
    use_sim_time = LaunchConfiguration('use_sim_time', default='false')
    scan_topic = LaunchConfiguration('scan_topic', default='/scan')
    odom_topic = LaunchConfiguration('odom_topic', default='/odom')

    # 2. 获取包路径
    base_controller_pkg = get_package_share_directory('base_controller')
    ldlidar_pkg = get_package_share_directory('ldlidar_ros2')

    # 3. 【关键】复用能成功的雷达启动逻辑（包含官方ld06.launch.py）
    ldlidar_launch = IncludeLaunchDescription(
        launch_description_source=PythonLaunchDescriptionSource([
            ldlidar_pkg,
            '/launch/ld06.launch.py'
        ]),
        # launch_arguments={'use_sim_time': use_sim_time}.items()
    )

    # 5. 底盘节点（发布/odom和odom→base_link TF）
    base_controller_node = Node(
        package='base_controller',
        executable='base_controller_node',
        name='base_controller',
        output='screen',
        # parameters=[{'use_sim_time': use_sim_time}]
    )

    # 6. SLAM建图节点
    slam_toolbox_node = Node(
        package='slam_toolbox',
        executable='async_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        remappings=[
            ('scan', scan_topic),
            ('odom', odom_topic),
        ],
        parameters=[{
            'mode': 'mapping',
            # 坐标系（你已有的，保持不动）
            'odom_frame': 'odom',
            'base_frame': 'base_link',
            'laser_frame': 'base_laser',
            'map_frame': 'map',
            # 地图质量：0.02m 比 0.05m 更精细，但 CPU/内存占用会更高。
            'resolution': 0.02,
            'max_laser_range': 12.0,    # 根据雷达实际可靠距离调整
            # ======================================
            # 【关键！让地图实时更新的参数】
            # ======================================
            'use_scan_matching': True,
            'use_odometry': True,        # 必须开启里程计
            'throttle_scans': 1,         # 每帧激光都参与建图
            'map_update_interval': 0.1,  # 每0.1秒更新一次地图
            'minimum_time_interval': 0.02,
            # 移动多少就更新（小车专用：更灵敏）
            'minimum_travel_distance': 0.01,   # 走 1厘米 就更新
            'minimum_travel_heading': 0.01,    # 转约 0.57度 就更新
            # TF 发布频率（让 odom 相对于 map 流畅动）
            'transform_publish_period': 0.05,  # 20Hz 高频发布
            'transform_timeout': 0.2,
            'tf_buffer_duration': 30.0,
            # 队列大小（防止数据丢包）
            'scan_queue_size': 30,
            'odom_queue_size': 30,
            # 建图稳定性
            'correction_alpha': 1.0,
            'max_correction': 0.1,
        }]
    )

    # 7. RViz节点（用你能看到雷达的rviz配置）
    rviz_node = Node(
        package='rviz2',
        executable='rviz2',
        name='rviz2',
        output='screen',
        arguments=['-d', os.path.join(base_controller_pkg, 'mapping.rviz')],  # 复用雷达官方RViz配置
        # parameters=[{'use_sim_time': use_sim_time}]
    )

    # 8. 组装所有节点
    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('scan_topic', default_value='/scan'),
        DeclareLaunchArgument('odom_topic', default_value='/odom'),
        # 启动顺序：TF → 底盘 → 雷达 → SLAM → RViz
        base_controller_node,
        ldlidar_launch,  # 复用成功的雷达启动逻辑  
        slam_toolbox_node,
        rviz_node
    ])
