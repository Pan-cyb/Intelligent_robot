#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from geometry_msgs.msg import PointStamped, PoseStamped
from std_msgs.msg import Bool, Float32, String
from sensor_msgs.msg import LaserScan
from nav2_msgs.action import NavigateToPose
from tf2_ros import Buffer, TransformListener
import math
import time


class FollowerNav2Controller(Node):
    """Nav2-based person follower: transform person position to map, send NavigateToPose goals."""

    IDLE = 0
    FOLLOWING = 1
    APPROACH_HAND = 2
    MEDICINE_READY = 3
    STATE_NAMES = ['IDLE', 'FOLLOWING', 'APPROACH_HAND', 'MEDICINE_READY']

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
        self.state = self.IDLE
        self.person_distance = 0.0
        self.person_angle = 0.0
        self.hand_distance = 0.0
        self.hand_angle = 0.0
        self.is_fallen = False
        self.person_visible = False
        self.hand_visible = False
        self.person_position_msg = None   # full PointStamped from person_tracker
        self.hand_position_msg = None     # full PointStamped from person_tracker
        self.last_person_time = 0.0
        self.last_goal_time = 0.0
        self.task_manager_active = False  # True when task_manager is not IDLE

        # ========== TF ==========
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        # ========== Nav2 Action Client ==========
        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.current_goal_handle = None

        # ========== Subscribers ==========
        self.create_subscription(PointStamped, '/person_position', self.person_callback, 10)
        self.create_subscription(Float32, '/person_distance', self.distance_callback, 10)
        self.create_subscription(Bool, '/fall_detected', self.fall_callback, 10)
        self.create_subscription(PointStamped, '/person_hand_position', self.hand_callback, 10)
        self.create_subscription(String, '/robot_mode', self.robot_mode_callback, 10)

        # ========== Control Timer ==========
        self.create_timer(0.5, self.control_loop)  # 2 Hz

        self.get_logger().info('Follower Nav2 Controller started')

    # ---- Callbacks ----

    def person_callback(self, msg: PointStamped):
        self.person_visible = True
        self.person_position_msg = msg
        self.last_person_time = time.time()
        d = math.sqrt(msg.point.x**2 + msg.point.z**2)
        if d > 0.01:
            self.person_angle = math.atan2(msg.point.x, msg.point.z)

    def distance_callback(self, msg: Float32):
        self.person_distance = msg.data

    def fall_callback(self, msg: Bool):
        self.is_fallen = msg.data
        if self.is_fallen and self.state == self.FOLLOWING:
            self.set_state(self.APPROACH_HAND)
            self.get_logger().info('Fall detected! Approaching hand...')

    def hand_callback(self, msg: PointStamped):
        self.hand_visible = True
        self.hand_position_msg = msg
        d = math.sqrt(msg.point.x**2 + msg.point.z**2)
        if d > 0.01:
            self.hand_distance = d
            self.hand_angle = math.atan2(msg.point.x, msg.point.z)

    def robot_mode_callback(self, msg: String):
        self.task_manager_active = msg.data != 'IDLE'

    # ---- State Machine ----

    def set_state(self, new_state):
        if new_state != self.state:
            self.get_logger().info(f'State: {self.STATE_NAMES[self.state]} → {self.STATE_NAMES[new_state]}')
            self.state = new_state

    def transform_to_map(self, point_stamped: PointStamped):
        """Transform a PointStamped from camera_link to map frame. Returns PoseStamped or None."""
        try:
            transformed = self.tf_buffer.transform(point_stamped, 'map', timeout=rclpy.duration.Duration(seconds=0.5))
            pose = PoseStamped()
            pose.header = transformed.header
            pose.pose.position = transformed.point
            pose.pose.orientation.w = 1.0
            return pose
        except Exception as e:
            self.get_logger().warn(f'TF transform failed: {e}')
            return None

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
        # Yield to task_manager when it's active
        if self.task_manager_active:
            if self.state != self.IDLE:
                self.cancel_nav_goal()
                self.set_state(self.IDLE)
            return

        # Check if person is lost
        if self.state != self.IDLE and not self.person_visible:
            if time.time() - self.last_person_time > self.lost_timeout:
                self.set_state(self.IDLE)
                self.cancel_nav_goal()
                self.get_logger().info('Person lost, going IDLE')
            return

        if self.state == self.IDLE:
            if self.person_visible:
                self.set_state(self.FOLLOWING)

        elif self.state == self.FOLLOWING:
            if not self.person_visible or self.person_position_msg is None:
                return

            person_map = self.transform_to_map(self.person_position_msg)
            if person_map is not None:
                self.send_nav_goal(person_map)
                self.get_logger().info(f'Nav goal to person at distance {self.person_distance:.2f}m')

        elif self.state == self.APPROACH_HAND:
            if self.hand_visible and self.hand_position_msg is not None:
                hand_map = self.transform_to_map(self.hand_position_msg)
                if hand_map is not None:
                    self.send_nav_goal(hand_map)
                    self.get_logger().info(f'Nav goal to hand at distance {self.hand_distance:.2f}m')

                if self.hand_distance <= self.approach_dist * 1.5:
                    self.set_state(self.MEDICINE_READY)
            elif self.person_visible and self.person_position_msg is not None:
                # Fallback: approach body
                person_map = self.transform_to_map(self.person_position_msg)
                if person_map is not None:
                    self.send_nav_goal(person_map)

        elif self.state == self.MEDICINE_READY:
            self.cancel_nav_goal()
            if self.person_visible and not self.is_fallen:
                self.set_state(self.IDLE)

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
