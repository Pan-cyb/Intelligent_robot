#!/usr/bin/env python3
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from std_msgs.msg import Bool, String


class VelocityMux(Node):
    """Minimal robot_mode based velocity mux."""

    def __init__(self):
        super().__init__('velocity_mux')

        self.declare_parameter('source_timeout', 0.5)
        self.declare_parameter('max_linear_speed', 0.4)
        self.declare_parameter('max_angular_speed', 1.0)

        self.source_timeout = float(self.get_parameter('source_timeout').value)
        self.max_linear_speed = float(self.get_parameter('max_linear_speed').value)
        self.max_angular_speed = float(self.get_parameter('max_angular_speed').value)

        self.robot_mode = 'IDLE'
        self.safety_stop = False
        self.nav_cmd = None
        self.follow_cmd = None
        self.manual_cmd = None
        self.nav_time = 0.0
        self.follow_time = 0.0
        self.manual_time = 0.0

        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.create_subscription(String, '/robot_mode', self.robot_mode_callback, 10)
        self.create_subscription(Twist, '/cmd_vel_nav', self.nav_callback, 10)
        self.create_subscription(Twist, '/cmd_vel_follow', self.follow_callback, 10)
        self.create_subscription(Twist, '/cmd_vel_manual', self.manual_callback, 10)
        self.create_subscription(Bool, '/safety_stop', self.safety_callback, 10)
        self.create_timer(0.05, self.control_loop)

        self.get_logger().info('Velocity mux started')

    def robot_mode_callback(self, msg: String):
        self.robot_mode = msg.data

    def nav_callback(self, msg: Twist):
        self.nav_cmd = msg
        self.nav_time = time.time()

    def follow_callback(self, msg: Twist):
        self.follow_cmd = msg
        self.follow_time = time.time()

    def manual_callback(self, msg: Twist):
        self.manual_cmd = msg
        self.manual_time = time.time()

    def safety_callback(self, msg: Bool):
        self.safety_stop = msg.data

    def control_loop(self):
        if self.safety_stop:
            self.cmd_pub.publish(Twist())
            return

        now = time.time()
        if self.robot_mode == 'FOLLOWING':
            cmd = self.follow_cmd if now - self.follow_time <= self.source_timeout else None
        else:
            cmd = self.nav_cmd if now - self.nav_time <= self.source_timeout else None

        if cmd is None:
            self.cmd_pub.publish(Twist())
            return

        self.cmd_pub.publish(self.limit_cmd(cmd))

    def limit_cmd(self, cmd: Twist) -> Twist:
        limited = Twist()
        limited.linear.x = self.clamp(cmd.linear.x, -self.max_linear_speed, self.max_linear_speed)
        limited.linear.y = self.clamp(cmd.linear.y, -self.max_linear_speed, self.max_linear_speed)
        limited.linear.z = self.clamp(cmd.linear.z, -self.max_linear_speed, self.max_linear_speed)
        limited.angular.x = self.clamp(cmd.angular.x, -self.max_angular_speed, self.max_angular_speed)
        limited.angular.y = self.clamp(cmd.angular.y, -self.max_angular_speed, self.max_angular_speed)
        limited.angular.z = self.clamp(cmd.angular.z, -self.max_angular_speed, self.max_angular_speed)
        return limited

    @staticmethod
    def clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, value))

    def destroy_node(self):
        self.cmd_pub.publish(Twist())
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = VelocityMux()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
