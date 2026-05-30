import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import IfElseSubstitution, LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():
    base_controller_share = get_package_share_directory("base_controller")
    task_manager_share = get_package_share_directory("task_manager")
    ascamera_share = get_package_share_directory("ascamera")

    navigation_launch = os.path.join(base_controller_share, "navigation.launch.py")
    ascamera_launch = os.path.join(ascamera_share, "launch", "hp60c.launch.py")
    default_locations_file = os.path.join(task_manager_share, "config", "named_locations.yaml")

    locations_file = LaunchConfiguration("locations_file")
    auto_start_demo = LaunchConfiguration("auto_start_demo")
    navigation_timeout_sec = LaunchConfiguration("navigation_timeout_sec")
    navigation_retry_limit = LaunchConfiguration("navigation_retry_limit")
    tts_topic = LaunchConfiguration("tts_topic")
    task_command_topic = LaunchConfiguration("task_command_topic")
    enable_camera = LaunchConfiguration("enable_camera")
    enable_person_tracker = LaunchConfiguration("enable_person_tracker")
    vision_backend = LaunchConfiguration("vision_backend")
    enable_bpu_vision = LaunchConfiguration("enable_bpu_vision")
    bpu_yolo_model_path = LaunchConfiguration("bpu_yolo_model_path")
    enable_follower_controller = LaunchConfiguration("enable_follower_controller")
    follow_backend = LaunchConfiguration("follow_backend")
    use_rviz = LaunchConfiguration("use_rviz")
    debug_window = LaunchConfiguration("debug_window")
    fall_confirm_frames = LaunchConfiguration("fall_confirm_frames")
    observe_duration_sec = LaunchConfiguration("observe_duration_sec")
    person_seen_timeout_sec = LaunchConfiguration("person_seen_timeout_sec")
    enable_demo_manager = LaunchConfiguration("enable_demo_manager")
    demo_start_delay_sec = LaunchConfiguration("demo_start_delay_sec")
    demo_wakeup_target = LaunchConfiguration("demo_wakeup_target")
    demo_wakeup_text = LaunchConfiguration("demo_wakeup_text")
    demo_companion_target = LaunchConfiguration("demo_companion_target")
    demo_companion_text = LaunchConfiguration("demo_companion_text")
    enable_rosa_always_listen = LaunchConfiguration("enable_rosa_always_listen")
    separate_demo_terminals = LaunchConfiguration("separate_demo_terminals")
    separate_terminal_prefix = IfElseSubstitution(
        separate_demo_terminals,
        "xterm -hold -e",
        "",
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument("locations_file", default_value=default_locations_file),
            DeclareLaunchArgument("auto_start_demo", default_value="false"),
            DeclareLaunchArgument("navigation_timeout_sec", default_value="90.0"),
            DeclareLaunchArgument("navigation_retry_limit", default_value="1"),
            DeclareLaunchArgument("tts_topic", default_value="/tts_text"),
            DeclareLaunchArgument("task_command_topic", default_value="/task_command"),
            DeclareLaunchArgument("enable_camera", default_value="false"),
            DeclareLaunchArgument("enable_person_tracker", default_value="true"),
            DeclareLaunchArgument("vision_backend", default_value="mediapipe"),
            DeclareLaunchArgument("enable_bpu_vision", default_value="false"),
            DeclareLaunchArgument("bpu_yolo_model_path", default_value=""),
            DeclareLaunchArgument("enable_follower_controller", default_value="true"),
            DeclareLaunchArgument("follow_backend", default_value="nav2"),
            DeclareLaunchArgument("use_rviz", default_value="false"),
            DeclareLaunchArgument("debug_window", default_value="false"),
            DeclareLaunchArgument("fall_confirm_frames", default_value="5"),
            DeclareLaunchArgument("observe_duration_sec", default_value="5.0"),
            DeclareLaunchArgument("person_seen_timeout_sec", default_value="1.0"),
            DeclareLaunchArgument("enable_demo_manager", default_value="false"),
            DeclareLaunchArgument("demo_start_delay_sec", default_value="30.0"),
            DeclareLaunchArgument("demo_wakeup_target", default_value="bedroom_bedside"),
            DeclareLaunchArgument("demo_wakeup_text", default_value="早上好，该起床了。"),
            DeclareLaunchArgument("demo_companion_target", default_value="livingroom_sofa"),
            DeclareLaunchArgument(
                "demo_companion_text",
                default_value="我陪您到客厅坐一会儿，有需要可以随时叫我。",
            ),
            DeclareLaunchArgument("enable_rosa_always_listen", default_value="false"),
            DeclareLaunchArgument("separate_demo_terminals", default_value="false"),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(navigation_launch),
                launch_arguments={"use_rviz": use_rviz}.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(ascamera_launch),
                condition=IfCondition(
                    PythonExpression([
                        "'",
                        enable_camera,
                        "' == 'true' or '",
                        enable_person_tracker,
                        "' == 'true' or '",
                        enable_bpu_vision,
                        "' == 'true'",
                    ])
                ),
            ),
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="base_to_camera",
                arguments=["0.1", "0", "0.2", "0", "-0.35", "0", "base_link", "camera_link"],
                condition=IfCondition(
                    PythonExpression([
                        "'",
                        enable_person_tracker,
                        "' == 'true' or '",
                        enable_bpu_vision,
                        "' == 'true'",
                    ])
                ),
            ),
            Node(
                package="person_tracker",
                executable="person_tracker_node.py",
                name="person_tracker",
                output="screen",
                parameters=[
                    {
                        "depth_scale": 0.001,
                        "fall_tilt_threshold": 50.0,
                        "detection_confidence": 0.6,
                        "tracking_confidence": 0.5,
                        "debug_window": debug_window,
                    }
                ],
                condition=IfCondition(
                    PythonExpression([
                        "'",
                        enable_person_tracker,
                        "' == 'true' and '",
                        vision_backend,
                        "' == 'mediapipe'",
                    ])
                ),
            ),
            Node(
                package="person_tracker",
                executable="person_tracker_bpu_node.py",
                name="person_tracker_bpu",
                output="screen",
                parameters=[
                    {
                        "vision_backend": vision_backend,
                        "depth_scale": 0.001,
                        "depth_window_size": 11,
                        "min_depth_m": 0.3,
                        "max_depth_m": 5.0,
                        "inference_every_n_frames": 3,
                        "max_publish_rate_hz": 10.0,
                        "debug_window": debug_window,
                        "bpu_yolo_model_path": bpu_yolo_model_path,
                        "bpu_yolo_input_width": 640,
                        "bpu_yolo_input_height": 640,
                        "bpu_yolo_score_threshold": 0.25,
                        "bpu_yolo_nms_threshold": 0.70,
                        "bpu_yolopose_reg": 16,
                        "bpu_yolopose_nkpt": 17,
                        "bpu_yolopose_resize_type": 1,
                        "bpu_yolopose_priority": 0,
                        "bpu_yolopose_bpu_cores": [0],
                        "enable_bbox_fall_detection": False,
                        "fall_aspect_ratio_threshold": 1.5,
                        "fall_confirm_frames": 5,
                    }
                ],
                condition=IfCondition(
                    PythonExpression([
                        "('",
                        enable_person_tracker,
                        "' == 'true' or '",
                        enable_bpu_vision,
                        "' == 'true') and ('",
                        vision_backend,
                        "' == 'mock' or '",
                        vision_backend,
                        "' == 'bpu_yolo' or '",
                        vision_backend,
                        "' == 'bpu_yolopose')",
                    ])
                ),
            ),
            Node(
                package="follower_controller",
                executable="follower_nav2_controller.py",
                name="follower_nav2_controller",
                output="screen",
                parameters=[
                    {
                        "follow_distance": 1.5,
                        "approach_distance": 0.3,
                        "goal_update_interval": 1.0,
                        "lost_timeout": 5.0,
                        "camera_pitch": -0.35,
                    }
                ],
                condition=IfCondition(
                    PythonExpression([
                        "'",
                        enable_follower_controller,
                        "' == 'true' and '",
                        follow_backend,
                        "' == 'nav2'",
                    ])
                ),
            ),
            Node(
                package="follower_controller",
                executable="follower_cmd_vel_controller.py",
                name="follower_cmd_vel_controller",
                output="screen",
                parameters=[
                    {
                        "follow_distance": 1.2,
                        "min_safe_distance": 0.6,
                        "max_linear_speed": 0.25,
                        "max_angular_speed": 0.6,
                        "linear_kp": 0.5,
                        "angular_kp": 1.2,
                        "distance_deadband": 0.15,
                        "angle_deadband": 0.08,
                        "lost_timeout": 1.0,
                        "control_rate_hz": 10.0,
                    }
                ],
                condition=IfCondition(
                    PythonExpression([
                        "'",
                        enable_follower_controller,
                        "' == 'true' and '",
                        follow_backend,
                        "' == 'cmd_vel'",
                    ])
                ),
            ),
            Node(
                package="follower_controller",
                executable="velocity_mux.py",
                name="velocity_mux",
                output="screen",
                parameters=[
                    {
                        "source_timeout": 0.5,
                        "max_linear_speed": 0.4,
                        "max_angular_speed": 1.0,
                    }
                ],
                condition=IfCondition(enable_follower_controller),
            ),
            Node(
                package="task_manager",
                executable="task_manager_node",
                name="task_manager",
                output="screen",
                prefix=separate_terminal_prefix,
                parameters=[
                    {
                        "locations_file": locations_file,
                        "auto_start_demo": auto_start_demo,
                        "navigation_timeout_sec": navigation_timeout_sec,
                        "navigation_retry_limit": navigation_retry_limit,
                        "tts_topic": tts_topic,
                        "task_command_topic": task_command_topic,
                        "fall_confirm_frames": fall_confirm_frames,
                        "observe_duration_sec": observe_duration_sec,
                        "person_seen_timeout_sec": person_seen_timeout_sec,
                    }
                ],
            ),
            Node(
                package="rosa_agent",
                executable="tts_node",
                name="tts_node",
                output="screen",
                parameters=[{"tts_topic": tts_topic}],
            ),
            Node(
                package="demo_manager",
                executable="demo_manager_node",
                name="demo_manager",
                output="screen",
                prefix=separate_terminal_prefix,
                parameters=[
                    {
                        "start_delay_sec": demo_start_delay_sec,
                        "wakeup_target": demo_wakeup_target,
                        "wakeup_text": demo_wakeup_text,
                        "companion_target": demo_companion_target,
                        "companion_text": demo_companion_text,
                    }
                ],
                condition=IfCondition(enable_demo_manager),
            ),
            Node(
                package="rosa_agent",
                executable="rosa_always_listen",
                name="rosa_always_listen",
                output="screen",
                prefix=separate_terminal_prefix,
                condition=IfCondition(enable_rosa_always_listen),
            ),
        ]
    )
