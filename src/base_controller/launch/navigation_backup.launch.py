import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    # 参数文件路径
    map_path = os.path.join(get_package_share_directory('base_controller'), 'map.yaml')
    nav2_params_path = os.path.join(get_package_share_directory('base_controller'), 'my_nav2_params.yaml')
    rviz_config_path = os.path.join(get_package_share_directory('base_controller'), 'navigation.rviz')
    # nav2_params = os.path.join(get_package_share_directory('nav2_bringup'),'params','nav2_params.yaml')
    # 公共参数（use_sim_time）
    common_params = {'use_sim_time': False}

    return LaunchDescription([
        # 1. 激光雷达驱动
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
                {'angle_crop_min': 330.0},  # unit is degress
                {'angle_crop_max': 30.0},  # unit is degress
                {'range_min': 0.2}, # unit is meter
                {'range_max': 12.0}   # unit is meter
            ]
        ),

        # 2. 静态 TF：base_link -> base_laser（根据实际安装偏移修改）
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='static_tf_laser',
            arguments=['-0.01','0','0.1','3.1415926','0','0','base_link','base_laser'],
        ),

        # 3. 底盘控制器（必须发布 odom -> base_link 的 TF）
        Node(
            package='base_controller',
            executable='base_controller_node',
            name='base_controller',
            output='screen',
            parameters=[common_params]
        ),

        # 4. map_server（加载静态地图）
        Node(
            package='nav2_map_server',
            executable='map_server',
            name='map_server',
            output='screen',
            parameters=[{'yaml_filename': map_path}, common_params]
        ),

        # 5. amcl（定位）
        Node(
            package='nav2_amcl',
            executable='amcl',
            name='amcl',
            output='screen',
            parameters=[nav2_params_path, common_params]
        ),

        # 6. planner_server（全局规划器 + global_costmap）
        Node(
            package='nav2_planner',
            executable='planner_server',
            name='planner_server',
            output='screen',
            parameters=[nav2_params_path, common_params]
        ),

        # 7. controller_server（局部规划器 + local_costmap）
        Node(
            package='nav2_controller',
            executable='controller_server',
            name='controller_server',
            output='screen',
            parameters=[nav2_params_path, common_params]
        ),

        # 8. bt_navigator（行为树导航）
        Node(
            package='nav2_bt_navigator',
            executable='bt_navigator',
            name='bt_navigator',
            output='screen',
            parameters=[nav2_params_path, common_params]
        ),

        # 9. lifecycle_manager（管理所有生命周期节点）
        Node(
            package='nav2_lifecycle_manager',
            executable='lifecycle_manager',
            name='lifecycle_manager_navigation',
            output='screen',
            parameters=[
                common_params,
                {'autostart': True},
                {'node_names': [
                    'map_server',
                    'amcl',
                    'planner_server',
                    'controller_server',
                    'bt_navigator'
                ]}
            ]
        ),

        # 10. RViz2
        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            output='screen',
            arguments=['-d', rviz_config_path],
            parameters=[common_params]
        )
    ])