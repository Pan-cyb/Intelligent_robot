# base_controller 工作流程说明

本文档说明 `src/base_controller/src/base_controller.cpp` 的整体结构、函数职责、实际运行路径，以及 `serial` 和 `joy` 相关依赖。

## 1. serial 库来源和检查方式

代码中使用的是 C++ 串口库：

```cpp
#include <serial/serial.h>
serial::Serial ROS_UART;
```

这不是 Python 的 `pyserial`，也不是 ROS2 标准消息库。当前 `CMakeLists.txt` 写死了手动安装路径：

```cmake
include_directories(
  include
  /usr/local/include
)
link_directories(/usr/local/lib)

target_link_libraries(base_controller_node
  serial
  pthread
)
```

因此当前工程期望使用：

```bash
/usr/local/include/serial/serial.h
/usr/local/lib/libserial.so
```

可用以下命令检查环境中是否存在该库：

```bash
ls /usr/local/include/serial
ls /usr/local/lib | grep libserial
ldconfig -p | grep libserial
dpkg -l | grep -E 'libserial|python3-serial|serial-driver'
```

当前机器检查结果：

```text
/usr/local/include/serial/serial.h 存在
/usr/local/lib/libserial.so 存在
ldconfig 能找到 /usr/local/lib/libserial.so
apt 中也安装了 libserial-dev、libserial1、python3-serial、ros-humble-serial-driver
```

注意：`libserial-dev` 提供的是另一个 C++ POSIX 串口库，API 通常是 `LibSerial::SerialPort`；本代码使用的是 `serial::Serial` 和 `<serial/serial.h>`，更像 `wjwwood/serial` 这个库。由于 CMake 明确包含 `/usr/local/include` 并链接 `/usr/local/lib`，实际编译时优先匹配手动安装的 `serial` 库。

## 2. 节点整体职责

`base_controller_node` 是 ROS2 底盘控制节点，节点名为 `base_controller`。

主要职责：

1. 打开串口 `/dev/ttyS1`，波特率 `115200`。
2. 订阅 `cmd_vel`，接收导航或键盘控制输出的速度指令。
3. 订阅 `joy`，接收手柄输入，并转换为底盘控制字段。
4. 每 20ms 向 STM32 发送一次控制数据。
5. 每 20ms 从 STM32 读取一次里程计数据。
6. 串口解析成功后发布 `/odom`。
7. 串口解析成功后广播 `odom -> base_link` TF。
8. 代码中包含 Nav2 自动巡逻逻辑，但当前默认没有启用。

## 3. 数据结构

### ROS 发送给 STM32

```cpp
typedef struct __attribute__((packed))
{
    float cmd_vx;
    float cmd_vy;
    float cmd_womiga;
    uint32_t cmd_1;
    uint32_t cmd_2;
    uint32_t cmd_3;
    uint32_t cmd_4;
    uint32_t cmd_5;
} ROS_STM_TYPEDEF;
```

含义：

- `cmd_vx`：x 方向线速度，单位 m/s。
- `cmd_vy`：y 方向线速度，单位 m/s。
- `cmd_womiga`：z 轴角速度，单位 rad/s。
- `cmd_1` 到 `cmd_5`：扩展控制字段，当前主要由手柄回调赋值。

发送帧格式：

```text
ROS: + 32字节结构体 + >STM\r\n
```

总长度 42 字节。

### STM32 发送给 ROS

```cpp
typedef struct __attribute__((packed))
{
    float odom_px;
    float odom_py;
    float odom_ang;
    float odom_vx;
    float odom_vy;
    float odom_womiga;
    uint32_t state_1;
    uint32_t state_2;
} STM_ROS_TYPEDEF;
```

含义：

- `odom_px`：机器人 x 坐标，单位 m。
- `odom_py`：机器人 y 坐标，单位 m。
- `odom_ang`：机器人 yaw 角，单位 rad。
- `odom_vx`：x 方向线速度，单位 m/s。
- `odom_vy`：y 方向线速度，单位 m/s。
- `odom_womiga`：z 轴角速度，单位 rad/s。
- `state_1`、`state_2`：底层状态扩展字段，目前上层没有进一步使用。

接收帧格式：

```text
STM: + 32字节结构体 + >ROS\r\n
```

总长度 42 字节。

## 4. 启动后的运行流程

入口函数：

```cpp
int main(int argc, char **argv)
{
    rclcpp::init(argc, argv);
    auto node = std::make_shared<BaseControllerNode>();
    rclcpp::spin(node);
    rclcpp::shutdown();
    return 0;
}
```

启动流程：

1. `main()` 初始化 ROS2。
2. 创建 `BaseControllerNode`。
3. 构造函数调用 `User_SerialInit()` 打开串口。
4. 构造函数创建 `cmd_vel` 订阅者。
5. 构造函数创建 `joy` 订阅者。
6. 构造函数创建 `/odom` 发布者。
7. 构造函数创建 `/initialpose` 发布者。
8. 构造函数创建 Nav2 `navigate_to_pose` action client。
9. 构造函数创建 20ms 定时器。
10. `rclcpp::spin(node)` 开始处理定时器和订阅回调。

定时器每 20ms 调用一次 `MainLoop()`：

```cpp
void MainLoop(void)
{
    User_RosToStmSend();

    if (User_StmToRosParas())
    {
        User_OdomTopicPublish();
    }

    //PatrolControl();
}
```

也就是说，当前实际主循环是：

```text
发送控制数据到 STM32
读取并解析 STM32 里程计数据
解析成功则发布 odom 和 TF
```

## 5. 函数作用表

| 函数 | 作用 | 是否启动后实际运行 |
| --- | --- | --- |
| `main()` | ROS2 程序入口，创建节点并 spin | 是 |
| `BaseControllerNode()` | 构造节点，初始化串口、订阅者、发布者、action client、定时器 | 是 |
| `~BaseControllerNode()` | 节点退出时关闭串口 | 退出时运行 |
| `User_SerialInit()` | 设置并打开 `/dev/ttyS1` 串口 | 是 |
| `User_CmdVelCallback()` | 接收 `geometry_msgs::msg::Twist`，更新速度控制字段 | 有 `cmd_vel` 消息时运行 |
| `User_JoystickCallback()` | 接收 `sensor_msgs::msg::Joy`，更新速度和扩展控制字段 | 有 `joy` 消息时运行 |
| `User_RosToStmSend()` | 打包 `ROS_STM_DATA` 并通过串口发送给 STM32 | 是，每 20ms |
| `User_StmToRosParas()` | 从串口读取并解析 STM32 回传数据 | 是，每 20ms |
| `User_OdomTopicPublish()` | 发布 `/odom` 并广播 `odom -> base_link` TF | 串口解析成功时运行 |
| `NavGoalResponseCallback()` | Nav2 目标点发送后的响应回调 | 当前默认不运行 |
| `SendNavGoal()` | 发送 Nav2 `navigate_to_pose` 目标点 | 当前默认不运行 |
| `PatrolControl()` | 自动巡逻状态机 | 当前默认不运行 |
| `tf_broadcaster_.sendTransform()` | 发布 `odom -> base_link` TF | 串口解析成功时运行 |

## 6. 常见 base controller 功能和扩展功能

### 基础底盘功能

这些是常见 base controller 的核心功能：

- `User_SerialInit()`：串口初始化。
- `User_CmdVelCallback()`：订阅速度指令。
- `User_RosToStmSend()`：发送速度到底层控制板。
- `User_StmToRosParas()`：接收底层里程计。
- `User_OdomTopicPublish()`：发布 `/odom` 和 TF。
- `MainLoop()`：周期性驱动收发逻辑。

### 扩展功能 1：手柄控制

`User_JoystickCallback()` 订阅 `joy` 话题，消息类型是：

```cpp
sensor_msgs::msg::Joy
```

对应 ROS2 官方消息包：

```text
sensor_msgs/msg/Joy
```

消息结构核心字段：

```text
float32[] axes
int32[] buttons
```

含义：

- `axes`：摇杆、扳机、方向键等模拟量。
- `buttons`：按键状态，通常 0 表示未按下，1 表示按下。

当前代码映射关系：

```cpp
ROS_STM_DATA.cmd_vx = joy.axes[0];
ROS_STM_DATA.cmd_vy = joy.axes[1];
ROS_STM_DATA.cmd_womiga = joy.axes[2];
ROS_STM_DATA.cmd_1 = joy.axes[3];
ROS_STM_DATA.cmd_2 = joy.axes[6];
ROS_STM_DATA.cmd_3 = joy.axes[7];
ROS_STM_DATA.cmd_4 = joy.buttons[6];
ROS_STM_DATA.cmd_5 = joy.buttons[7];
```

注意事项：

- 代码没有检查 `axes` 和 `buttons` 数组长度。如果手柄驱动发布的数组长度不足，可能越界崩溃。
- `joy.axes` 是浮点数组，但 `cmd_1`、`cmd_2`、`cmd_3` 是 `uint32_t`，这里存在隐式类型转换。
- 不同手柄的 axes/buttons 编号不一定相同，需要用 `ros2 topic echo /joy` 实测。

### 扩展功能 2：Nav2 自动巡逻

代码内置了 10 个巡逻点：

```cpp
float patrol_points[PATROL_POINT_NUM][3] = {
    {5.27, -2.5, -1},
    ...
};
```

相关函数：

- `PatrolControl()`：巡逻状态机。
- `SendNavGoal()`：向 Nav2 发送目标点。
- `NavGoalResponseCallback()`：记录 Nav2 是否接受目标。

当前 `MainLoop()` 中的调用被注释：

```cpp
//PatrolControl();
```

所以默认启动后不会自动巡逻。

## 7. joy 是什么，是否需要 USB 接收器

`joy` 不是某一个具体手柄，而是 ROS 里常用的手柄输入话题名。这个文件订阅：

```cpp
sub_joystick_ = this->create_subscription<sensor_msgs::msg::Joy>(
    "joy", 20, std::bind(&BaseControllerNode::User_JoystickCallback, this, std::placeholders::_1));
```

消息类型是 ROS2 官方消息 `sensor_msgs::msg::Joy`，但 `/joy` 话题本身需要另一个驱动节点发布。

常见发布方式是安装并运行 ROS2 官方/常用的 `joy` 包：

```bash
ros2 run joy joy_node
```

硬件连接方式取决于手柄：

- USB 有线手柄：直接插到地瓜派 USB。
- 2.4G 无线手柄：把 USB 接收器插到地瓜派 USB。
- 蓝牙手柄：需要系统先完成蓝牙配对，然后 `joy_node` 才能读取输入设备。

插入后可先检查 Linux 是否识别：

```bash
ls /dev/input
```

常见会出现：

```text
/dev/input/js0
/dev/input/eventX
```

再检查 ROS2 是否有 joy 包：

```bash
ros2 pkg list | grep '^joy$'
```

运行手柄节点：

```bash
ros2 run joy joy_node
```

查看手柄数据：

```bash
ros2 topic echo /joy
```

如果能看到 `axes` 和 `buttons` 随手柄变化，说明 `/joy` 输入正常。

## 8. 目前代码中需要留意的问题

1. 串口设备写死为 `/dev/ttyS1`，换设备时需要改代码或改成 ROS 参数。
2. 波特率写死为 `115200`。
3. `ROS_STM_DATA` 和 `STM_ROS_DATA` 是全局变量，当前单线程 spin 下问题不大，多线程 executor 下需要考虑并发访问。
4. `User_StmToRosParas()` 每次读取后调用 `flushInput()`，可能丢弃尚未解析的后续数据。
5. `User_JoystickCallback()` 未检查数组长度。
6. `pub_initialpose_` 创建了，但当前没有发布初始位姿。
7. 自动巡逻相关代码存在，但当前没有启用。

## 9. 当前导航功能所需的最小 base controller

Nav2 要能控制真实底盘，base controller 至少需要提供三件事：

1. 订阅 `cmd_vel`，把 Nav2 输出的速度发给底层控制器。
2. 发布 `/odom`，让 Nav2 和定位模块知道机器人自身运动。
3. 发布 `odom -> base_link` TF，建立里程计坐标系到机器人底盘坐标系的变换。

因此，当前文件中手柄控制和自动巡逻都不是“能导航”的必要条件。一个最小版本已经放在：

```text
src/base_controller/examples/minimal_base_controller/minimal_base_controller.cpp
```

这个最小版保留：

- `serial::Serial` 串口通信。
- `/dev/ttyS1`、`115200` 参数。
- `cmd_vel` 订阅。
- ROS 到 STM32 的 42 字节发送协议。
- STM32 到 ROS 的 42 字节接收协议。
- `/odom` 发布。
- `odom -> base_link` TF 发布。

这个最小版删除：

- `joy` 手柄订阅。
- `/initialpose` 发布者。
- Nav2 `navigate_to_pose` action client。
- 巡逻点数组。
- `PatrolControl()` 自动巡逻状态机。

它只是参考代码，当前没有加入 `CMakeLists.txt`，不会影响现有工程编译和运行。

## 10. 打开巡航功能后的工作流

当前 `MainLoop()` 里巡逻调用被注释：

```cpp
//PatrolControl();
```

如果改成：

```cpp
PatrolControl();
```

那么每 20ms 主循环会变成：

```text
发送当前速度/控制字段到 STM32
读取 STM32 里程计
解析成功则发布 /odom 和 odom -> base_link TF
执行一次自动巡逻状态机 PatrolControl()
```

巡逻状态机有 4 个主要状态。

### 状态 0：等待 Nav2 action server

`PatrolControl()` 会检查 `navigate_to_pose` action server 是否在线：

```cpp
navigate_client_->wait_for_action_server(...)
```

如果 Nav2 没启动好，就每隔一段时间打印等待日志。

一旦 Nav2 可用：

```text
Navigation is ready
```

然后设置：

```cpp
current_point_index_ = PATROL_POINT_NUM - 1;
patrol_state_++;
```

这样下一步会从第 0 个巡逻点开始。

### 状态 1：发送下一个巡逻点

状态 1 会把 `current_point_index_` 加 1，并从 `patrol_points` 中取出目标点：

```cpp
float x = patrol_points[current_point_index_][0];
float y = patrol_points[current_point_index_][1];
float yaw = patrol_points[current_point_index_][2];
SendNavGoal(x, y, yaw);
```

`SendNavGoal()` 会构造 `nav2_msgs::action::NavigateToPose` 目标：

```text
frame_id = map
position.x = x
position.y = y
orientation = yaw 转四元数
```

然后调用：

```cpp
navigate_client_->async_send_goal(...)
```

也就是向 Nav2 的 `navigate_to_pose` action server 发送目标点。

### 状态 2：等待到达或超时

状态 2 会检查当前 action goal 的状态：

```cpp
current_goal_handle_->get_status()
```

如果状态是：

```cpp
STATUS_SUCCEEDED
```

说明 Nav2 判断已经到达目标点。此时：

```cpp
wait_start_time_ = now;
current_goal_handle_.reset();
patrol_state_++;
```

然后进入状态 3。

如果超过 `FAIL_TIMEOUT`，当前是 60 秒，还没有成功，则：

```cpp
navigate_client_->async_cancel_goal(current_goal_handle_);
current_goal_handle_.reset();
patrol_state_ = 1;
```

也就是取消当前目标，跳到下一个巡逻点。

### 状态 3：到达后等待

状态 3 会等待 `WAIT_TIME`，当前是 5 秒。

等待结束后：

```cpp
patrol_state_ = 1;
```

重新进入状态 1，发送下一个巡逻点。这样就形成循环巡逻。

## 11. 巡航过程中外部发布目标点会发生什么

这里要区分两种“发布目标点”。

### 情况 A：外部发布普通 Pose 话题

如果只是向某个普通 topic 发布目标点，例如发布到 `/goal_pose`，当前 `base_controller` 本身不会订阅这个话题，所以 `base_controller` 不会直接感知。

但是 RViz 的 Nav2 Goal 工具通常不是给 `base_controller` 发消息，而是给 Nav2 的 `navigate_to_pose` action server 发目标。这个时候就属于情况 B。

### 情况 B：RViz 或命令行给 Nav2 发送 NavigateToPose 目标

当前巡逻代码和 RViz/Nav2 Goal 使用的是同一个 action server：

```text
navigate_to_pose
```

如果打开巡航后，`base_controller` 会周期性向 `navigate_to_pose` 发送巡逻目标。此时你又从 RViz 发布一个新的 Nav2 目标，会出现“两个客户端同时给 Nav2 发目标”的情况：

- 一个客户端是 `base_controller` 内部的 `navigate_client_`。
- 另一个客户端是 RViz 或命令行 action client。

Nav2 对新目标的处理取决于 Nav2 action server 的行为和当前状态。常见结果是：新目标会抢占或替换正在执行的旧目标，机器人转去执行最新目标。

但这里有一个重要问题：`base_controller` 的巡逻状态机不知道外部目标已经介入。

可能发生的现象：

1. 巡逻目标 A 正在执行。
2. 你从 RViz 发了目标 B。
3. Nav2 可能转去执行目标 B。
4. `base_controller` 仍然持有自己当初发送目标 A 时保存的 `current_goal_handle_`。
5. 如果目标 A 被 Nav2 取消、终止或抢占，当前代码只检查 `STATUS_SUCCEEDED`，没有完整处理 canceled、aborted 等状态。
6. 到了 60 秒超时后，`base_controller` 可能取消自己保存的 goal handle，然后发送下一个巡逻点。
7. 结果就是：外部目标 B 可能只临时生效，之后巡逻状态机会继续接管导航。

所以，如果打开巡航，最好不要同时手动发布 Nav2 目标点，除非你明确希望“手动目标临时打断巡逻，然后巡逻继续接管”。

更稳妥的设计是增加巡逻开关，例如：

- 增加 `/patrol_enable` 参数或 topic。
- 手动发目标前先关闭巡逻。
- 手动目标完成后再打开巡逻。
- 或者让 `base_controller` 订阅外部目标事件，一旦检测到人工目标，就暂停巡逻状态机。

当前代码没有这些保护机制。
