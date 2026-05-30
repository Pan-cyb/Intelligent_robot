#!/usr/bin/env python3
import math
import time

import rclpy
from geometry_msgs.msg import PointStamped, Twist
from rclpy.node import Node
from std_msgs.msg import Float32, String


class FollowerCmdVelController(Node):
    """Local velocity follower enabled only by robot_mode=FOLLOWING."""

    def __init__(self):
        super().__init__('follower_cmd_vel_controller')

        self.declare_parameter('follow_distance', 1.2)
        self.declare_parameter('min_safe_distance', 0.6)
        self.declare_parameter('max_linear_speed', 0.25)
        self.declare_parameter('max_angular_speed', 0.6)
        self.declare_parameter('linear_kp', 0.5)
        self.declare_parameter('angular_kp', 1.2)
        self.declare_parameter('distance_deadband', 0.15)
        self.declare_parameter('angle_deadband', 0.08)
        self.declare_parameter('lost_timeout', 1.0)
        self.declare_parameter('control_rate_hz', 10.0)

        self.follow_distance = float(self.get_parameter('follow_distance').value)
        self.min_safe_distance = float(self.get_parameter('min_safe_distance').value)
        self.max_linear_speed = float(self.get_parameter('max_linear_speed').value)
        self.max_angular_speed = float(self.get_parameter('max_angular_speed').value)
        self.linear_kp = float(self.get_parameter('linear_kp').value)
        self.angular_kp = float(self.get_parameter('angular_kp').value)
        self.distance_deadband = float(self.get_parameter('distance_deadband').value)
        self.angle_deadband = float(self.get_parameter('angle_deadband').value)
        self.lost_timeout = float(self.get_parameter('lost_timeout').value)
        control_rate_hz = max(1.0, float(self.get_parameter('control_rate_hz').value))

        self.enabled = False
        self.person_position = None
        self.person_distance = None
        self.last_person_time = 0.0
        self.zero_sent = True
        self.person_lost_logged = False

        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel_follow', 10)
        self.create_subscription(String, '/robot_mode', self.robot_mode_callback, 10)
        self.create_subscription(PointStamped, '/person_position', self.person_callback, 10)
        self.create_subscription(Float32, '/person_distance', self.distance_callback, 10)
        self.create_timer(1.0 / control_rate_hz, self.control_loop)

        self.get_logger().info('Follower cmd_vel controller started')

    def robot_mode_callback(self, msg: String):
        should_enable = msg.data == 'FOLLOWING'
        if should_enable == self.enabled:
            return

        self.enabled = should_enable
        if self.enabled:
            self.zero_sent = False
            self.person_lost_logged = False
            self.get_logger().info('Follower cmd_vel enabled by robot_mode=FOLLOWING')
        else:
            self.person_position = None
            self.publish_zero_once()
            self.get_logger().info(f'Follower cmd_vel disabled by robot_mode={msg.data}')

    def person_callback(self, msg: PointStamped):
        self.person_position = msg
        self.last_person_time = time.time()
        self.zero_sent = False
        self.person_lost_logged = False

    def distance_callback(self, msg: Float32):
        self.person_distance = msg.data

    def control_loop(self):
        if not self.enabled:
            return

        now = time.time()
        if self.person_position is None or now - self.last_person_time > self.lost_timeout:
            self.publish_zero_once()
            if not self.person_lost_logged:
                self.get_logger().warn('Person lost while cmd_vel following')
                self.person_lost_logged = True
            return

        point = self.person_position.point
        distance = math.hypot(point.x, point.y)
        if distance < 0.01:
            self.publish_zero_once()
            return

        angle = math.atan2(point.y, point.x)
        distance_error = distance - self.follow_distance

        linear_x = self.linear_kp * distance_error
        angular_z = self.angular_kp * angle

        if abs(distance_error) < self.distance_deadband:
            linear_x = 0.0
        if abs(angle) < self.angle_deadband:
            angular_z = 0.0

        if distance < self.min_safe_distance:
            linear_x = min(linear_x, 0.0)

        linear_x = self.clamp(linear_x, -self.max_linear_speed, self.max_linear_speed)
        angular_z = self.clamp(angular_z, -self.max_angular_speed, self.max_angular_speed)

        cmd = Twist()
        cmd.linear.x = linear_x
        cmd.angular.z = angular_z
        self.cmd_pub.publish(cmd)
        self.zero_sent = False

    def publish_zero_once(self):
        if self.zero_sent:
            return
        self.cmd_pub.publish(Twist())
        self.zero_sent = True

    @staticmethod
    def clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def destroy_node(self):
        self.cmd_pub.publish(Twist())
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = FollowerCmdVelController()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
