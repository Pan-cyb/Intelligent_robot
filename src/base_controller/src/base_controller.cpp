/******************************************************************
ROS2 Base Controller based on Serial Communication, functions:
1. Send ROS2 control data to lower controller via serial port to control robot movement
2. Subscribe to /cmd_vel topic to control robot movement
3. Publish odometry topic /odom
4. Auto patrol with Nav2 action

Serial Communication Protocol:
1. Send to serial: linear velocity and angular velocity, units m/s and rad/s
2. Read from serial: robot x,y position, yaw angle, linear velocity, angular velocity
*******************************************************************/
#include "base_controller/base_controller.h"
// ROS2核心头文件
#include "rclcpp/rclcpp.hpp"
#include "rclcpp_action/rclcpp_action.hpp"
// 消息类型头文件
#include "geometry_msgs/msg/twist.hpp"
#include "nav_msgs/msg/odometry.hpp"
#include "sensor_msgs/msg/joy.hpp"
#include "sensor_msgs/msg/laser_scan.hpp"
#include "geometry_msgs/msg/transform_stamped.hpp"
#include "geometry_msgs/msg/pose_with_covariance_stamped.hpp"
#include "std_msgs/msg/string.hpp"
// TF2相关
#include "tf2_ros/transform_broadcaster.h"
#include "tf2/LinearMath/Quaternion.h"
// 串口库（仅保留手动编译的serial库头文件，移除系统libserial）
#include <serial/serial.h>
// Nav2 action (替换ROS1的move_base为nav2的NavigateToPose)
#include "nav2_msgs/action/navigate_to_pose.hpp"
// 其他工具头文件
#include <string>
#include <iostream>
#include <cstdio>
#include <unistd.h>
#include <math.h>
#include <iomanip>
#include <bitset>
#include <numeric>
#include <memory>
#include <action_msgs/msg/goal_status.hpp>

#define PI 3.14159265358979323846

using std::string;
using std::exception;
using std::cout;
using std::cerr;
using std::endl;
using std::vector;
using namespace std;

// 串口对象（适配手动编译的serial库）
serial::Serial ROS_UART;

// ROS→STM32 数据结构
typedef struct __attribute__((packed))
{
    float cmd_vx;      // m/s
    float cmd_vy;      // m/s
    float cmd_womiga;  // rad/s
    uint32_t cmd_1;
    uint32_t cmd_2;
    uint32_t cmd_3;
    uint32_t cmd_4;
    uint32_t cmd_5;
}ROS_STM_TYPEDEF;

// STM32→ROS 数据结构
typedef struct __attribute__((packed))
{
    float odom_px;     // m
    float odom_py;     // m
    float odom_ang;    // rad
    float odom_vx;     // m/s
    float odom_vy;     // m/s
    float odom_womiga; // rad/s
    uint32_t state_1;
    uint32_t state_2;
}STM_ROS_TYPEDEF;

ROS_STM_TYPEDEF ROS_STM_DATA;
STM_ROS_TYPEDEF STM_ROS_DATA;

// ===================== 巡逻点配置 =====================
#define PATROL_POINT_NUM  10    // 巡逻点数量
#define WAIT_TIME         5.0   // 到达后停留时间(s)
#define FAIL_TIMEOUT      60.0  // 单点超时未到达则跳过(s)
// 巡逻点（地图坐标，按需修改）
float patrol_points[PATROL_POINT_NUM][3] = {
    {5.27, -2.5, -1},    // 点1
    {1.91, -1.36, 0.0},  // 点2
    {2.18, -6.58, 0.0},  // 点3
    {7.68, -4.77, 0.0},  // 点4
    {7.02, -9.24, 0.0},  // 点5
    {11.9, -7.16, 0.0},  // 点6
    {8.86, -10.6, 0.0},  // 点7
    {14.4, -8.56, 0.0},  // 点8
    {12.5, -12.4, 0.0},  // 点9
    {3.4, 0.82, -0.5}    // 点10
};

// 定义Nav2 NavigateToPose Action类型（替换原MoveBase）
using NavigateToPoseAction = nav2_msgs::action::NavigateToPose;
using NavigateToPoseClient = rclcpp_action::Client<NavigateToPoseAction>;
using GoalHandleNav = rclcpp_action::ClientGoalHandle<NavigateToPoseAction>;

// 主控制器类（ROS2推荐面向对象封装）
class BaseControllerNode : public rclcpp::Node
{
public:
    BaseControllerNode() : Node("base_controller"), 
                      tf_broadcaster_(this),
                      current_goal_handle_(nullptr),  // 先初始化（声明在前）
                      current_point_index_(0),
                      wait_start_time_(0.0),
                      nav_start_time_(0.0),
                      patrol_state_(0)  //  // 后初始化 patrol_state_（声明在后）
    {
        // 1. 初始化串口
        if(User_SerialInit() < 0)
        {
            RCLCPP_FATAL(this->get_logger(), "Serial port init failed!");
            rclcpp::shutdown();
            return;
        }

        // 2. 创建订阅者
        sub_cmd_vel_ = this->create_subscription<geometry_msgs::msg::Twist>(
            "cmd_vel", 20, std::bind(&BaseControllerNode::User_CmdVelCallback, this, std::placeholders::_1));
        
        sub_joystick_ = this->create_subscription<sensor_msgs::msg::Joy>(
    "joy", 20, std::bind(&BaseControllerNode::User_JoystickCallback, this, std::placeholders::_1));

        // 3. 创建发布者
        pub_odom_ = this->create_publisher<nav_msgs::msg::Odometry>("odom", 20);
        pub_initialpose_ = this->create_publisher<geometry_msgs::msg::PoseWithCovarianceStamped>("/initialpose", 10);

        // 4. 创建Nav2 Action客户端（替换move_base为navigate_to_pose）
        navigate_client_ = rclcpp_action::create_client<NavigateToPoseAction>(this, "navigate_to_pose");

        // 5. 创建定时器（替代ROS1的loop_rate，50Hz）
        timer_ = this->create_wall_timer(
            std::chrono::milliseconds(20), std::bind(&BaseControllerNode::MainLoop, this));

        RCLCPP_INFO(this->get_logger(), "BaseController node started!");
    }

    ~BaseControllerNode()
    {
        ROS_UART.close();
        RCLCPP_INFO(this->get_logger(), "BaseController node stopped!");
    }

private:
    // ROS2对象
    rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr sub_cmd_vel_;
    rclcpp::Subscription<sensor_msgs::msg::Joy>::SharedPtr sub_joystick_;
    rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr pub_odom_;
    rclcpp::Publisher<geometry_msgs::msg::PoseWithCovarianceStamped>::SharedPtr pub_initialpose_;
    std::shared_ptr<NavigateToPoseClient> navigate_client_;
    tf2_ros::TransformBroadcaster tf_broadcaster_;
    rclcpp::TimerBase::SharedPtr timer_;
    GoalHandleNav::SharedPtr current_goal_handle_; // 声明在前

    // 巡逻状态变量
    int current_point_index_;
    double wait_start_time_;
    double nav_start_time_;
    uint8_t patrol_state_; // 声明在后

    /****************************************************/
    /* 串口初始化（适配手动编译的serial库API） */
    int User_SerialInit(void)
    {
        try
        {
            ROS_UART.setPort("/dev/ttyS1");
            ROS_UART.setBaudrate(115200);
            serial::Timeout to = serial::Timeout::simpleTimeout(50);
            ROS_UART.setTimeout(to);
            ROS_UART.open();
        }
        catch (serial::IOException& e)
        {
            RCLCPP_ERROR(this->get_logger(), "Unable to open ROS_UART port ttyS1!");
            return -1;
        }

        if(ROS_UART.isOpen())
        {
            RCLCPP_INFO(this->get_logger(), "ROS_UART ttyS1 serial port opened!");
            return 1;
        }
        else
        {
            return -1;
        }
    }

    /****************************************************/
    /* /cmd_vel回调函数 */
    void User_CmdVelCallback(const geometry_msgs::msg::Twist & cmd_input)
    {
        ROS_STM_DATA.cmd_vx = cmd_input.linear.x;
        ROS_STM_DATA.cmd_vy = cmd_input.linear.y;
        ROS_STM_DATA.cmd_womiga = cmd_input.angular.z;
    }

    /****************************************************/
    /* 手柄回调函数 */
    void User_JoystickCallback(const sensor_msgs::msg::Joy& joy)
    {
        ROS_STM_DATA.cmd_vx = joy.axes[0];    // 去掉->，改用.访问成员
        ROS_STM_DATA.cmd_vy = joy.axes[1];
        ROS_STM_DATA.cmd_womiga = joy.axes[2];
        ROS_STM_DATA.cmd_1 = joy.axes[3];
        ROS_STM_DATA.cmd_2 = joy.axes[6];
        ROS_STM_DATA.cmd_3 = joy.axes[7];
        ROS_STM_DATA.cmd_4 = joy.buttons[6];
        ROS_STM_DATA.cmd_5 = joy.buttons[7];

        RCLCPP_INFO(this->get_logger(), "Joystick vx:%.1f vy:%.1f wo:%.1f",
            ROS_STM_DATA.cmd_vx, ROS_STM_DATA.cmd_vy, ROS_STM_DATA.cmd_womiga);
    }
    /****************************************************/
    /* ROS→STM32 数据发送 */
    void User_RosToStmSend(void)
    {
        uint8_t data_buf[110]={0};
        data_buf[0] = 'R';
        data_buf[1] = 'O';
        data_buf[2] = 'S';
        data_buf[3] = ':';
        data_buf[36] = '>';
        data_buf[37] = 'S';
        data_buf[38] = 'T';
        data_buf[39] = 'M';
        data_buf[40] = '\r';
        data_buf[41] = '\n';

        memcpy(&data_buf[4], &ROS_STM_DATA, 32);

        ROS_UART.write(data_buf, 42);
    }

    /****************************************************/
    /* STM32→ROS 数据接收解析 */
    uint8_t User_StmToRosParas(void)
    {
        uint8_t rec_buffer[84] = {0};

        int len = ROS_UART.read(rec_buffer, 83);
        ROS_UART.flushInput();
        
        for(int i=0; i < len-41; i++)
        {
            if( (rec_buffer[i+0] == 'S') &&
                (rec_buffer[i+1] == 'T') &&
                (rec_buffer[i+2] == 'M') &&
                (rec_buffer[i+3] == ':') &&
                (rec_buffer[i+36] == '>') &&
                (rec_buffer[i+37] == 'R') &&
                (rec_buffer[i+38] == 'O') &&
                (rec_buffer[i+39] == 'S') &&
                (rec_buffer[i+40] == '\r') &&
                (rec_buffer[i+41] == '\n') )
            {
                memcpy(&STM_ROS_DATA, &rec_buffer[i+4], 32);
                // ========== 新增：打印串口接收的里程计数据 ==========
                // RCLCPP_INFO(this->get_logger(), 
                //     "串口接收里程数据：x=%.3fm, y=%.3fm, 角度=%.3frad, 线速度=%.3fm/s, 角速度=%.3frad/s",
                //     STM_ROS_DATA.odom_px,    // x坐标
                //     STM_ROS_DATA.odom_py,    // y坐标
                //     STM_ROS_DATA.odom_ang,   // 偏航角（弧度）
                //     STM_ROS_DATA.odom_vx,    // 线速度x
                //     STM_ROS_DATA.odom_womiga // 角速度z
                // );
                // ====================================================
                return 1;
            }
        }
        RCLCPP_WARN_THROTTLE(this->get_logger(), *this->get_clock(), 1000, "STM communicate lost...");
        return 0;
    }

    /****************************************************/
    /* 发布里程计和TF变换 */
    void User_OdomTopicPublish(void)
    {
        nav_msgs::msg::Odometry odom;
        geometry_msgs::msg::TransformStamped odom_trans;

        // 协方差矩阵
        float covariance[36] = {0.01, 0, 0, 0, 0, 0,
                                0, 0.01, 0, 0, 0, 0,
                                0, 0, 99999, 0, 0, 0,
                                0, 0, 0, 99999, 0, 0,
                                0, 0, 0, 0, 99999, 0,
                                0, 0, 0, 0, 0, 0.01};
        for (int i = 0; i < 36; i++)
        {
            odom.pose.covariance[i] = covariance[i];
        }

        // TF变换（odom→base_link）
        odom_trans.header.stamp = this->now();
        odom_trans.header.frame_id = "odom";
        odom_trans.child_frame_id = "base_link";
        odom_trans.transform.translation.x = STM_ROS_DATA.odom_px;
        odom_trans.transform.translation.y = STM_ROS_DATA.odom_py;
        odom_trans.transform.translation.z = 0.0;
        
        // 四元数（从yaw角转换）
        tf2::Quaternion q;
        q.setRPY(0, 0, STM_ROS_DATA.odom_ang);
        odom_trans.transform.rotation.x = q.x();
        odom_trans.transform.rotation.y = q.y();
        odom_trans.transform.rotation.z = q.z();
        odom_trans.transform.rotation.w = q.w();
        tf_broadcaster_.sendTransform(odom_trans);

        // 里程计消息
        odom.header.stamp = this->now();
        odom.header.frame_id = "odom";
        odom.child_frame_id = "base_link";

        odom.pose.pose.position.x = STM_ROS_DATA.odom_px;
        odom.pose.pose.position.y = STM_ROS_DATA.odom_py;
        odom.pose.pose.position.z = 0.0;
        odom.pose.pose.orientation = odom_trans.transform.rotation;

        odom.twist.twist.linear.x = STM_ROS_DATA.odom_vx;
        odom.twist.twist.linear.y = STM_ROS_DATA.odom_vy;
        odom.twist.twist.angular.z = STM_ROS_DATA.odom_womiga;

        pub_odom_->publish(odom);
    }

    /****************************************************/
    /* 导航结果回调函数 */
    void NavGoalResponseCallback(const GoalHandleNav::SharedPtr& goal_handle)
    {
        if (!goal_handle)
        {
            RCLCPP_ERROR(this->get_logger(), "Navigation goal was rejected by server");
        }
        else
        {
            current_goal_handle_ = goal_handle;
            RCLCPP_INFO(this->get_logger(), "Navigation goal accepted by server, waiting for result");
        }
    }

    /****************************************************/
    /* 发送Nav2导航目标点（替换原MoveBase） */
    void SendNavGoal(float x, float y, float yaw_deg)
    {
        if(!navigate_client_->wait_for_action_server(std::chrono::seconds(1)))
        {
            RCLCPP_WARN(this->get_logger(), "NavigateToPose action server not available!");
            return;
        }

        auto goal_msg = NavigateToPoseAction::Goal();
        goal_msg.pose.header.frame_id = "map";
        goal_msg.pose.header.stamp = this->now();
        
        goal_msg.pose.pose.position.x = x;
        goal_msg.pose.pose.position.y = y;
        
        // 角度转换（度→弧度 + 四元数）
        float yaw_rad = yaw_deg * PI / 180.0;
        tf2::Quaternion q;
        q.setRPY(0, 0, yaw_rad);
        goal_msg.pose.pose.orientation.x = q.x();
        goal_msg.pose.pose.orientation.y = q.y();
        goal_msg.pose.pose.orientation.z = q.z();
        goal_msg.pose.pose.orientation.w = q.w();

        // 发送目标（异步，通过回调判断结果）
        auto send_goal_options = rclcpp_action::Client<NavigateToPoseAction>::SendGoalOptions();
        send_goal_options.goal_response_callback = 
            std::bind(&BaseControllerNode::NavGoalResponseCallback, this, std::placeholders::_1);
        navigate_client_->async_send_goal(goal_msg, send_goal_options);
        RCLCPP_INFO(this->get_logger(), "Send goal to (%.2f, %.2f), yaw: %.1f°", x, y, yaw_deg);
    }

    /****************************************************/
    /* 巡逻主逻辑 */
    void PatrolControl(void)
    {
        switch(patrol_state_)
        {
            case 0: // 检查Nav2服务是否在线
            {   
                if (!navigate_client_->wait_for_action_server(std::chrono::milliseconds(100)))
                { 
                    RCLCPP_INFO_THROTTLE(this->get_logger(), *this->get_clock(), 1000, "Waiting for navigate_to_pose action server...");
                    return;
                }
                RCLCPP_INFO(this->get_logger(), "=====================================");
                RCLCPP_INFO(this->get_logger(), "Navigation is ready!");
                RCLCPP_INFO(this->get_logger(), "====================================="); 
                current_point_index_ = PATROL_POINT_NUM - 1;
                patrol_state_++;
            }break;

            case 1: // 发布下一个导航目标点
            {
                current_point_index_++;
                if(current_point_index_ >= PATROL_POINT_NUM)
                    current_point_index_ = 0;
                
                float x = patrol_points[current_point_index_][0];
                float y = patrol_points[current_point_index_][1];
                float yaw = patrol_points[current_point_index_][2];
                SendNavGoal(x, y, yaw);
                
                nav_start_time_ = this->now().seconds();
                RCLCPP_INFO(this->get_logger(), "Moving to point %d: (%.2f, %.2f)", current_point_index_, x, y); 
                patrol_state_++; 
            }break;

            case 2: // 检查是否到达目标/超时
            { 
                // 检查Action状态
                if (current_goal_handle_)
                {
                    auto goal_status = current_goal_handle_->get_status();
                    if (goal_status == action_msgs::msg::GoalStatus::STATUS_SUCCEEDED)
                    {
                        wait_start_time_ = this->now().seconds();
                        RCLCPP_INFO(this->get_logger(), "Arrive Point %d, Waiting for %.1fs", current_point_index_, WAIT_TIME);
                        current_goal_handle_.reset();
                        patrol_state_++;
                    }
                }

                // 检查超时
                double now = this->now().seconds();
                if(now - nav_start_time_ > FAIL_TIMEOUT)
                {
                    if (current_goal_handle_)
                    {
                        navigate_client_->async_cancel_goal(current_goal_handle_);
                        current_goal_handle_.reset();
                    }
                    RCLCPP_WARN(this->get_logger(), "Point %d timeout, jump it!!", current_point_index_);
                    patrol_state_ = 1;
                }
            }break;

            case 3: // 到达目标后停留
            {
                double now = this->now().seconds();
                if(now - wait_start_time_ >= WAIT_TIME)
                {
                    patrol_state_ = 1; // 跳转到下一个点
                }
            }break;

            default: 
                patrol_state_ = 0; 
                break;
        }
    }

    /****************************************************/
    /* 主循环（替代ROS1的spin+loop_rate） */
    void MainLoop(void)
    {
        // 1. 发送数据到STM32
        User_RosToStmSend();

        // 2. 接收并解析STM32数据，发布里程计
        if (User_StmToRosParas())
        {
            User_OdomTopicPublish();
        }

        // 3. 执行自动巡逻逻辑
        //PatrolControl();
    }
};

/****************************************************/
/* 主函数 */
int main(int argc, char **argv)
{
    // 初始化ROS2
    rclcpp::init(argc, argv);
    
    // 创建节点并运行
    auto node = std::make_shared<BaseControllerNode>();
    rclcpp::spin(node);
    
    // 关闭ROS2
    rclcpp::shutdown();
    return 0;
}