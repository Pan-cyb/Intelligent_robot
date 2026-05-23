"""Unified launch file for the full caregiving robot stack.

Launches everything in one command:
  camera + lidar + base_controller + Nav2 + person_tracker + follower + task_manager + TTS

Usage:
  ros2 launch follower_controller caregiving.launch.py
  ros2 launch follower_controller caregiving.launch.py rviz:=true
  ros2 launch follower_controller caregiving.launch.py debug_window:=true
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    # ---- Package paths ----
    base_controller_share = get_package_share_directory('base_controller')
    ldlidar_share = get_package_share_directory('ldlidar_ros2')
    task_manager_share = get_package_share_directory('task_manager')

    # ---- Config files ----
    map_path = os.path.join(base_controller_share, 'my_map1.yaml')
    params_file = os.path.join(base_controller_share, 'my_nav2_params.yaml')
    rviz_config = os.path.join(base_controller_share, 'navigation.rviz')
    locations_file = os.path.join(task_manager_share, 'config', 'named_locations.yaml')

    # ---- Camera driver ----
    ascamera_share = get_package_share_directory('ascamera')
    ascamera_launch = os.path.join(ascamera_share, 'launch', 'hp60c.launch.py')

    # ---- Launch arguments ----
    rviz = LaunchConfiguration('rviz')
    debug_window = LaunchConfiguration('debug_window')
    auto_start_demo = LaunchConfiguration('auto_start_demo')

    common = {'use_sim_time': False}

    # ---- Nav2 node helper ----
    def nav2_node(package, executable, name, remappings=None):
        return Node(
            package=package,
            executable=executable,
            name=name,
            output='screen',
            parameters=[params_file, common],
            remappings=remappings or [],
        )

    return LaunchDescription([
        DeclareLaunchArgument('rviz', default_value='false'),
        DeclareLaunchArgument('debug_window', default_value='false'),
        DeclareLaunchArgument('auto_start_demo', default_value='false'),

        # ========== Hardware drivers ==========

        # Camera
        IncludeLaunchDescription(PythonLaunchDescriptionSource(ascamera_launch)),

        # LiDAR
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(ldlidar_share, 'launch/ld06.launch.py'))
        ),

        # Base controller (STM32 serial bridge)
        Node(
            package='base_controller',
            executable='base_controller_node',
            name='base_controller',
            output='screen',
            parameters=[common],
        ),

        # ========== Static TF ==========

        # Static TF: base_link → camera_link
        # args: x y z roll pitch yaw parent child
        # Camera pitch calibration: place robot facing a wall at known distance,
        # compare /person_position.z with actual distance, adjust pitch until error < 5%.
        # Current -0.35 rad ≈ -20° (camera tilted up). Positive pitch = tilted down.
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='base_to_camera',
            arguments=['0.1', '0', '0.2', '0', '-0.35', '0', 'base_link', 'camera_link'],
        ),

        # ========== Nav2 stack ==========

        Node(
            package='nav2_map_server',
            executable='map_server',
            name='map_server',
            output='screen',
            parameters=[{'yaml_filename': map_path}, common],
        ),
        nav2_node('nav2_amcl', 'amcl', 'amcl'),
        nav2_node('nav2_planner', 'planner_server', 'planner_server'),
        nav2_node(
            'nav2_controller', 'controller_server', 'controller_server',
            remappings=[('cmd_vel', 'cmd_vel_nav')],
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
                ('cmd_vel_smoothed', 'cmd_vel'),
            ],
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
                    'map_server', 'amcl', 'planner_server',
                    'controller_server', 'behavior_server',
                    'bt_navigator', 'velocity_smoother',
                ]},
            ],
        ),

        # ========== Perception ==========

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
                'debug_window': debug_window,
            }],
        ),

        # ========== Control ==========

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

        # ========== Task & TTS ==========

        Node(
            package='task_manager',
            executable='task_manager_node',
            name='task_manager',
            output='screen',
            parameters=[{
                'locations_file': locations_file,
                'auto_start_demo': auto_start_demo,
                'navigation_timeout_sec': 90.0,
                'navigation_retry_limit': 1,
                'tts_topic': '/tts_text',
                'task_command_topic': '/task_command',
            }],
        ),
        Node(
            package='rosa_agent',
            executable='tts_node',
            name='tts_node',
            output='screen',
            parameters=[{'tts_topic': '/tts_text'}],
        ),

        # ========== RViz (optional) ==========

        Node(
            package='rviz2',
            executable='rviz2',
            name='rviz2',
            output='screen',
            arguments=['-d', rviz_config],
            parameters=[common],
            condition=IfCondition(rviz),
        ),
    ])
