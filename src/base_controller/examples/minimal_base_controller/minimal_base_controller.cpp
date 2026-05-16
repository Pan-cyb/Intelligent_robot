#include "geometry_msgs/msg/transform_stamped.hpp"
#include "geometry_msgs/msg/twist.hpp"
#include "nav_msgs/msg/odometry.hpp"
#include "rclcpp/rclcpp.hpp"
#include "tf2/LinearMath/Quaternion.h"
#include "tf2_ros/transform_broadcaster.h"

#include <chrono>
#include <cstdint>
#include <cstring>
#include <serial/serial.h>

namespace
{
constexpr auto kSerialPort = "/dev/ttyS1";
constexpr uint32_t kBaudrate = 115200;
constexpr std::chrono::milliseconds kLoopPeriod(20);

struct __attribute__((packed)) RosToStm
{
  float cmd_vx;
  float cmd_vy;
  float cmd_womiga;
  uint32_t cmd_1;
  uint32_t cmd_2;
  uint32_t cmd_3;
  uint32_t cmd_4;
  uint32_t cmd_5;
};

struct __attribute__((packed)) StmToRos
{
  float odom_px;
  float odom_py;
  float odom_ang;
  float odom_vx;
  float odom_vy;
  float odom_womiga;
  uint32_t state_1;
  uint32_t state_2;
};
}  // namespace

class MinimalBaseController : public rclcpp::Node
{
public:
  MinimalBaseController()
  : Node("minimal_base_controller"),
    tf_broadcaster_(this)
  {
    openSerial();

    cmd_vel_sub_ = create_subscription<geometry_msgs::msg::Twist>(
      "cmd_vel", 20,
      std::bind(&MinimalBaseController::onCmdVel, this, std::placeholders::_1));

    odom_pub_ = create_publisher<nav_msgs::msg::Odometry>("odom", 20);

    timer_ = create_wall_timer(
      kLoopPeriod, std::bind(&MinimalBaseController::loop, this));

    RCLCPP_INFO(get_logger(), "Minimal base controller started");
  }

  ~MinimalBaseController() override
  {
    if (serial_.isOpen()) {
      serial_.close();
    }
  }

private:
  void openSerial()
  {
    try {
      serial_.setPort(kSerialPort);
      serial_.setBaudrate(kBaudrate);
      serial_.setTimeout(serial::Timeout::simpleTimeout(50));
      serial_.open();
    } catch (const serial::IOException & ex) {
      RCLCPP_FATAL(get_logger(), "Failed to open serial port %s: %s", kSerialPort, ex.what());
      rclcpp::shutdown();
      return;
    }

    if (!serial_.isOpen()) {
      RCLCPP_FATAL(get_logger(), "Serial port %s is not open", kSerialPort);
      rclcpp::shutdown();
      return;
    }

    RCLCPP_INFO(get_logger(), "Serial port %s opened at %u", kSerialPort, kBaudrate);
  }

  void onCmdVel(const geometry_msgs::msg::Twist & msg)
  {
    ros_to_stm_.cmd_vx = msg.linear.x;
    ros_to_stm_.cmd_vy = msg.linear.y;
    ros_to_stm_.cmd_womiga = msg.angular.z;
  }

  void loop()
  {
    sendCommand();

    if (readOdom()) {
      publishOdom();
    }
  }

  void sendCommand()
  {
    uint8_t data[42] = {};
    data[0] = 'R';
    data[1] = 'O';
    data[2] = 'S';
    data[3] = ':';
    std::memcpy(&data[4], &ros_to_stm_, sizeof(ros_to_stm_));
    data[36] = '>';
    data[37] = 'S';
    data[38] = 'T';
    data[39] = 'M';
    data[40] = '\r';
    data[41] = '\n';

    serial_.write(data, sizeof(data));
  }

  bool readOdom()
  {
    uint8_t data[84] = {};
    const int len = serial_.read(data, 83);
    serial_.flushInput();

    for (int i = 0; i < len - 41; ++i) {
      const bool frame_ok =
        data[i] == 'S' &&
        data[i + 1] == 'T' &&
        data[i + 2] == 'M' &&
        data[i + 3] == ':' &&
        data[i + 36] == '>' &&
        data[i + 37] == 'R' &&
        data[i + 38] == 'O' &&
        data[i + 39] == 'S' &&
        data[i + 40] == '\r' &&
        data[i + 41] == '\n';

      if (frame_ok) {
        std::memcpy(&stm_to_ros_, &data[i + 4], sizeof(stm_to_ros_));
        return true;
      }
    }

    RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 1000, "STM communicate lost");
    return false;
  }

  void publishOdom()
  {
    const auto stamp = now();

    tf2::Quaternion q;
    q.setRPY(0.0, 0.0, stm_to_ros_.odom_ang);

    geometry_msgs::msg::TransformStamped tf_msg;
    tf_msg.header.stamp = stamp;
    tf_msg.header.frame_id = "odom";
    tf_msg.child_frame_id = "base_link";
    tf_msg.transform.translation.x = stm_to_ros_.odom_px;
    tf_msg.transform.translation.y = stm_to_ros_.odom_py;
    tf_msg.transform.translation.z = 0.0;
    tf_msg.transform.rotation.x = q.x();
    tf_msg.transform.rotation.y = q.y();
    tf_msg.transform.rotation.z = q.z();
    tf_msg.transform.rotation.w = q.w();
    tf_broadcaster_.sendTransform(tf_msg);

    nav_msgs::msg::Odometry odom;
    odom.header.stamp = stamp;
    odom.header.frame_id = "odom";
    odom.child_frame_id = "base_link";
    odom.pose.pose.position.x = stm_to_ros_.odom_px;
    odom.pose.pose.position.y = stm_to_ros_.odom_py;
    odom.pose.pose.position.z = 0.0;
    odom.pose.pose.orientation = tf_msg.transform.rotation;
    odom.twist.twist.linear.x = stm_to_ros_.odom_vx;
    odom.twist.twist.linear.y = stm_to_ros_.odom_vy;
    odom.twist.twist.angular.z = stm_to_ros_.odom_womiga;

    constexpr double covariance[36] = {
      0.01, 0.0, 0.0, 0.0, 0.0, 0.0,
      0.0, 0.01, 0.0, 0.0, 0.0, 0.0,
      0.0, 0.0, 99999.0, 0.0, 0.0, 0.0,
      0.0, 0.0, 0.0, 99999.0, 0.0, 0.0,
      0.0, 0.0, 0.0, 0.0, 99999.0, 0.0,
      0.0, 0.0, 0.0, 0.0, 0.0, 0.01};
    std::memcpy(odom.pose.covariance.data(), covariance, sizeof(covariance));

    odom_pub_->publish(odom);
  }

  serial::Serial serial_;
  RosToStm ros_to_stm_{};
  StmToRos stm_to_ros_{};
  tf2_ros::TransformBroadcaster tf_broadcaster_;
  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr cmd_vel_sub_;
  rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr odom_pub_;
  rclcpp::TimerBase::SharedPtr timer_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<MinimalBaseController>());
  rclcpp::shutdown();
  return 0;
}
