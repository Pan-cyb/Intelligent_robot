# 养老陪伴机器人最小闭环服务端使用说明

本文档说明如何把导航系统、`task_manager` 和语音播报节点整合为一个“服务端”，再通过高层 service 发布任务。

## 当前架构

最小闭环分成两侧：

```text
服务端：
  base_controller/navigation.launch.py
  task_manager_node
  rosa_agent/tts_node

命令端：
  ros2 service call /robot_server/start_task
  ros2 service call /robot_server/cancel_current_task
  ros2 service call /robot_server/query_robot_state
```

服务端负责：

```text
启动地图、定位、Nav2、底盘控制、RViz
启动 task_manager 状态机
启动 TTS 播报节点
```

命令端只负责发任务，不直接控制导航。

## task_manager 做什么

`task_manager` 是任务状态机。

当前状态包括：

```text
IDLE
SCHEDULED_TASK
NAVIGATION
CONVERSATION
MANUAL
FAULT
```

叫醒任务流程：

```text
收到 task_type=wake_up
  -> SCHEDULED_TASK
  -> 读取命名地点
  -> NAVIGATION
  -> 发送 Nav2 NavigateToPose
  -> 等待导航结果
  -> CONVERSATION
  -> 到达后发布 /tts_text
  -> TTS 播报
  -> 回到 IDLE
```

`task_manager` 不自己做路径规划，也不直接控制电机。真正导航仍然由 Nav2 和 `base_controller` 完成。

## 实际使用的命名点文件

当前任务运行使用：

```text
src/task_manager/config/named_locations.yaml
```

该文件会在 build 后安装到：

```text
install/task_manager/share/task_manager/config/named_locations.yaml
```

`robot_server.launch.py` 默认读取安装后的配置文件。如果你修改了源码目录下的 `named_locations.yaml`，需要重新 build：

```bash
colcon build --packages-select task_manager
source install/setup.bash
```

也可以启动时显式指定源码目录文件：

```bash
ros2 launch task_manager robot_server.launch.py \
  locations_file:=/home/pan/Intelligent_robot/src/task_manager/config/named_locations.yaml
```

当前 `task_manager` 同时支持两种地点格式。

旧格式：

```yaml
locations:
  bedroom:
    frame_id: map
    x: 1.0
    y: 2.0
    yaw: 0.0
```

新 waypoint 标定格式：

```yaml
locations:
  bedroom_bedside:
    frame_id: map
    position:
      x: 2.748
      y: 2.532
      z: 0.0
    orientation:
      x: 0.0
      y: 0.0
      z: 0.9999
      w: 0.0064
```

## 高层任务接口

`task_manager_interfaces` 提供 robot 服务端高层接口。

启动任务：

```text
/robot_server/start_task
task_manager_interfaces/srv/StartTask
```

请求字段：

```text
string task_type
string target
string text
```

任务类型：

```text
task_type="wake_up"   叫醒任务，默认目标 bedroom_bedside，到达后播报“早上好，该起床了。”
task_type="navigate"  导航到 target 指定的命名点
task_type="speak"     播放 text 指定文本
```

取消任务：

```text
/robot_server/cancel_current_task
std_srvs/srv/Trigger
```

查询状态：

```text
/robot_server/query_robot_state
task_manager_interfaces/srv/QueryRobotState
```

返回：

```text
mode
current_task
target
is_navigating
last_error
```

## 编译

```bash
cd /home/pan/Intelligent_robot
source /opt/ros/humble/setup.bash
colcon build --packages-select base_controller rosa_agent task_manager_interfaces task_manager
source install/setup.bash
```

## 启动完整服务端

一个终端启动：

```bash
cd /home/pan/Intelligent_robot
source install/setup.bash
ros2 launch task_manager robot_server.launch.py
```

这个 launch 会启动：

```text
base_controller/navigation.launch.py
task_manager_node
tts_node
```

默认不会自动执行任务。

## 命令端发布任务

另开一个终端：

```bash
cd /home/pan/Intelligent_robot
source install/setup.bash
```

用高层 service 触发叫醒任务：

```bash
ros2 service call /robot_server/start_task task_manager_interfaces/srv/StartTask "{task_type: 'wake_up', target: 'bedroom_bedside', text: ''}"
```

导航到命名点：

```bash
ros2 service call /robot_server/start_task task_manager_interfaces/srv/StartTask "{task_type: 'navigate', target: 'livingroom_sofa', text: ''}"
```

播放文本：

```bash
ros2 service call /robot_server/start_task task_manager_interfaces/srv/StartTask "{task_type: 'speak', target: '', text: '您好，我在这里。'}"
```

旧入口仍保留用于兼容历史 wakeup/cancel 测试，不作为新任务扩展入口：

```bash
ros2 service call /trigger_wakeup_task std_srvs/srv/Trigger {}
ros2 topic pub --once /task_command std_msgs/msg/String "{data: wakeup_bedroom}"
```

## 查看状态

查看机器人任务状态：

```bash
ros2 topic echo /robot_mode
```

查询完整状态：

```bash
ros2 service call /robot_server/query_robot_state task_manager_interfaces/srv/QueryRobotState {}
```

查看任务命令话题：

```bash
ros2 topic echo /task_command
```

查看 TTS 文本：

```bash
ros2 topic echo /tts_text
```

## 取消任务

```bash
ros2 service call /robot_server/cancel_current_task std_srvs/srv/Trigger {}
```

旧入口仍保留：

```bash
ros2 service call /cancel_task std_srvs/srv/Trigger {}
```

## 清除故障

如果任务失败后进入 `FAULT`：

```bash
ros2 service call /clear_fault std_srvs/srv/Trigger {}
```

## 常用启动参数

指定地点文件：

```bash
ros2 launch task_manager robot_server.launch.py \
  locations_file:=/home/pan/Intelligent_robot/src/task_manager/config/named_locations.yaml
```

启动后自动执行 demo：

```bash
ros2 launch task_manager robot_server.launch.py auto_start_demo:=true
```

修改导航超时：

```bash
ros2 launch task_manager robot_server.launch.py navigation_timeout_sec:=120.0
```

修改任务命令话题：

```bash
ros2 launch task_manager robot_server.launch.py task_command_topic:=/task_command
```

## 最小闭环验收

1. 服务端启动成功。
2. Nav2 可用，RViz 中地图正常。
3. `/robot_mode` 初始为 `IDLE`。
4. 命令端调用 `/robot_server/start_task`。
5. `task_manager` 进入 `SCHEDULED_TASK`，随后进入 `NAVIGATION`。
6. 机器人导航到命名点。
7. 到达后 `task_manager` 发布 `/tts_text`。
8. `tts_node` 播放语音。
9. `task_manager` 回到 `IDLE`。

## 和语音命令的关系

ROSA action tools 只暴露高层工具：

```text
start_wakeup_task()
navigate_to_named_place(place_name)
speak_text(text)
cancel_current_task()
query_robot_state()
```

这些工具内部只调用 robot 服务端高层 service。ROSA / LLM 不直接调用 Nav2，不直接发 `/cmd_vel`，不排列组合底层 service。
