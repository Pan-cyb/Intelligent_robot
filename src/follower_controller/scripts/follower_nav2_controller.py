#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from geometry_msgs.msg import PointStamped, PoseStamped
from std_msgs.msg import Float32, String
from nav2_msgs.action import NavigateToPose
from tf2_ros import Buffer, TransformListener
import tf2_geometry_msgs  # registers PointStamped with TF2
import math
import time


class FollowerNav2Controller(Node):
    """Nav2-based follow executor enabled only by robot_mode=FOLLOWING."""

    def __init__(self):
        super().__init__('follower_nav2_controller')

        # ========== Parameters ==========
        self.declare_parameter('follow_distance', 1.5)
        self.declare_parameter('approach_distance', 0.3)
        self.declare_parameter('goal_update_interval', 1.0)   # seconds between Nav2 goal updates
        self.declare_parameter('lost_timeout', 5.0)
        self.declare_parameter('camera_pitch', -0.35)         # radians, camera tilt angle

        self.follow_dist = self.get_parameter('follow_distance').value
        self.approach_dist = self.get_parameter('approach_distance').value
        self.goal_update_interval = self.get_parameter('goal_update_interval').value
        self.lost_timeout = self.get_parameter('lost_timeout').value
        self.camera_pitch = self.get_parameter('camera_pitch').value

        # ========== State ==========
        self.enabled = False
        self.person_distance = 0.0
        self.person_angle = 0.0
        self.person_visible = False
        self.person_position_msg = None   # full PointStamped from person_tracker
        self.last_person_time = 0.0
        self.last_goal_time = 0.0

        # ========== TF ==========
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        # ========== Nav2 Action Client ==========
        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.current_goal_handle = None

        # ========== Subscribers ==========
        self.create_subscription(PointStamped, '/person_position', self.person_callback, 10)
        self.create_subscription(Float32, '/person_distance', self.distance_callback, 10)
        self.create_subscription(String, '/robot_mode', self.robot_mode_callback, 10)

        # ========== Control Timer ==========
        self.create_timer(0.5, self.control_loop)  # 2 Hz

        self.get_logger().info('Follower Nav2 Controller started')

    # ---- Callbacks ----

    def person_callback(self, msg: PointStamped):
        self.person_visible = True
        self.person_position_msg = msg
        self.last_person_time = time.time()
        d = math.sqrt(msg.point.x**2 + msg.point.y**2)
        if d > 0.01:
            self.person_angle = math.atan2(msg.point.y, msg.point.x)

    def distance_callback(self, msg: Float32):
        self.person_distance = msg.data

    def robot_mode_callback(self, msg: String):
        should_enable = msg.data == 'FOLLOWING'
        if should_enable == self.enabled:
            return

        self.enabled = should_enable
        if self.enabled:
            self.person_visible = False
            self.person_position_msg = None
            self.last_goal_time = 0.0
            self.get_logger().info('Follower enabled by robot_mode=FOLLOWING')
        else:
            self.cancel_nav_goal()
            self.person_visible = False
            self.person_position_msg = None
            self.get_logger().info(f'Follower disabled by robot_mode={msg.data}')

    def yaw_to_quaternion(self, yaw: float):
        qz = math.sin(yaw / 2.0)
        qw = math.cos(yaw / 2.0)
        return qz, qw

    def transform_to_map(self, point_stamped: PointStamped):
        """Transform a PointStamped to map frame. Returns PointStamped or None."""
        try:
            return self.tf_buffer.transform(
                point_stamped,
                'map',
                timeout=rclpy.duration.Duration(seconds=0.5),
            )
        except Exception as e:
            self.get_logger().warn(f'TF transform failed: {e}')
            return None

    def make_follow_goal(self, target_map: PointStamped):
        """Build a Nav2 goal that stops follow_distance short of the target."""
        try:
            robot_pose = self.tf_buffer.lookup_transform(
                'map',
                'base_link',
                rclpy.time.Time(),
                timeout=rclpy.duration.Duration(seconds=0.5),
            )
        except Exception as e:
            self.get_logger().warn(f'Robot pose lookup failed: {e}')
            return None

        robot_x = robot_pose.transform.translation.x
        robot_y = robot_pose.transform.translation.y
        target_x = target_map.point.x
        target_y = target_map.point.y
        dx = target_x - robot_x
        dy = target_y - robot_y
        dist = math.hypot(dx, dy)
        if dist < 0.01:
            return None

        stop_distance = min(self.follow_dist, max(0.0, dist - 0.05))
        goal_x = target_x - dx / dist * stop_distance
        goal_y = target_y - dy / dist * stop_distance
        yaw = math.atan2(target_y - goal_y, target_x - goal_x)
        qz, qw = self.yaw_to_quaternion(yaw)

        pose = PoseStamped()
        pose.header = target_map.header
        pose.pose.position.x = goal_x
        pose.pose.position.y = goal_y
        pose.pose.position.z = 0.0
        pose.pose.orientation.z = qz
        pose.pose.orientation.w = qw
        return pose

    def send_nav_goal(self, pose_stamped: PoseStamped):
        """Send a NavigateToPose goal to Nav2."""
        now = time.time()
        if now - self.last_goal_time < self.goal_update_interval:
            return  # Rate limit goal updates
        self.last_goal_time = now

        if not self.nav_client.wait_for_server(timeout_sec=1.0):
            self.get_logger().warn('Nav2 action server not available')
            return

        goal = NavigateToPose.Goal()
        goal.pose = pose_stamped

        # Cancel previous goal if exists
        if self.current_goal_handle is not None:
            try:
                self.nav_client.cancel_goal_async(self.current_goal_handle)
            except Exception:
                pass

        send_goal_future = self.nav_client.send_goal_async(goal)
        send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if goal_handle.accepted:
            self.current_goal_handle = goal_handle
            self.get_logger().debug('Nav2 goal accepted')
        else:
            self.get_logger().warn('Nav2 goal rejected')
            self.current_goal_handle = None

    def control_loop(self):
        if not self.enabled:
            return

        # Check if person is lost
        if not self.person_visible or self.person_position_msg is None:
            if self.last_person_time > 0.0 and time.time() - self.last_person_time > self.lost_timeout:
                self.person_visible = False
                self.person_position_msg = None
                self.cancel_nav_goal()
                self.get_logger().warn('Person lost while following')
            return

        if time.time() - self.last_person_time > self.lost_timeout:
            self.person_visible = False
            self.person_position_msg = None
            self.cancel_nav_goal()
            self.get_logger().warn('Person lost while following')
            return

        person_map = self.transform_to_map(self.person_position_msg)
        if person_map is not None:
            follow_goal = self.make_follow_goal(person_map)
            if follow_goal is not None:
                self.send_nav_goal(follow_goal)
                self.get_logger().info(
                    f'Nav goal toward person, keeping {self.follow_dist:.2f}m; '
                    f'person distance {self.person_distance:.2f}m'
                )

    def cancel_nav_goal(self):
        if self.current_goal_handle is not None:
            try:
                self.nav_client.cancel_goal_async(self.current_goal_handle)
            except Exception:
                pass
            self.current_goal_handle = None

    def destroy_node(self):
        self.cancel_nav_goal()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = FollowerNav2Controller()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
