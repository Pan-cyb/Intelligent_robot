# Task Manager 最小任务调度 Demo

## 版本

- 版本：v0.1.0
- 日期：2026-05-20
- 范围：养老陪伴机器人最小任务调度闭环。

## 当前变更

本版本实现了第一个“任务执行闭环”demo。机器人可以接收叫醒任务，读取命名地点坐标，调用 Nav2 导航，到达后发布固定语音播报文本，最后回到空闲状态。

主要变更：

- 新增 `task_manager` ROS2 Python 包。
- 新增 `RobotMode` 状态：
  - `IDLE`
  - `SCHEDULED_TASK`
  - `NAVIGATION`
  - `CONVERSATION`
  - `MANUAL`
  - `FAULT`
- 新增命名地点配置：
  - `bedroom`
  - `living_room`
  - `charger`
- 新增“去卧室叫醒”任务 demo：
  - 任务 ID：`wakeup_bedroom`
  - 目标地点：`bedroom`
  - 播报内容：`早上好，该起床了。`
- 在 `task_manager` 中新增 Nav2 `NavigateToPose` action 客户端。
- 新增任务取消 service。
- 新增导航超时处理。
- 新增导航失败重试处理。
- 新增失败处理，可进入 `FAULT` 状态。
- 给 `rosa_agent` 新增 ROS TTS 节点：
  - 订阅 `/tts_text`
  - 调用已有 `rosa_agent.voice.speak()`

## 相关文件

重要文件：

- `src/task_manager/task_manager/task_manager_node.py`
- `src/task_manager/config/named_locations.yaml`
- `src/task_manager/launch/wakeup_demo.launch.py`
- `src/rosa_agent/rosa_agent/tts_node.py`
- `src/rosa_agent/setup.py`
- `src/rosa_agent/package.xml`

## 构建

在工作区根目录执行：

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select rosa_agent task_manager
source install/setup.bash
```

## 启动导航系统

先启动已有导航系统：

```bash
source install/setup.bash
ros2 launch base_controller navigation.launch.py
```

等待 Nav2 lifecycle 节点进入 active 状态，并确认 `navigate_to_pose` action server 可用。

## 启动任务调度 Demo

另开一个终端执行：

```bash
source install/setup.bash
ros2 launch task_manager wakeup_demo.launch.py
```

默认情况下，`auto_start_demo` 为 `False`，所以启动后机器人不会立刻运动。

## 触发叫醒任务

使用 service 触发：

```bash
ros2 service call /trigger_wakeup_task std_srvs/srv/Trigger {}
```

也可以通过 topic 触发：

```bash
ros2 topic pub --once /task_command std_msgs/msg/String "{data: wakeup_bedroom}"
```

预期状态流转：

```text
IDLE
SCHEDULED_TASK
NAVIGATION
CONVERSATION
IDLE
```

机器人会导航到 `bedroom`，到达后发布以下 TTS 文本：

```text
早上好，该起床了。
```

## 取消任务

```bash
ros2 service call /cancel_task std_srvs/srv/Trigger {}
```

如果当前有 Nav2 目标正在执行，`task_manager` 会发送取消请求，并回到 `IDLE`。

## 清除故障

如果导航失败并超过重试次数，节点进入 `FAULT` 状态后，可执行：

```bash
ros2 service call /clear_fault std_srvs/srv/Trigger {}
```

## 查看机器人状态

```bash
ros2 topic echo /robot_mode
```

## 配置命名地点

编辑：

```text
src/task_manager/config/named_locations.yaml
```

示例：

```yaml
locations:
  bedroom:
    frame_id: map
    x: 1.91
    y: -1.36
    yaw: 0.0
```

`yaw` 使用弧度。

## TTS 说明

TTS 节点订阅 `/tts_text`。

如果 `TTS_ENABLED=0`，TTS 函数会直接返回，不会真实播放声音。若要启用真实语音播放，需要配置现有 `rosa_agent` 的 TTS 环境变量，例如：

```bash
export TTS_ENABLED=1
export TTS_API_KEY=your_key
export TTS_BASE_URL=https://api.xiaomimimo.com/v1
export TTS_MODEL=mimo-v2.5-tts
export TTS_VOICE=mimo_default
```

如果使用 ALSA 播放：

```bash
export AUDIO_BACKEND=alsa
export TTS_PLAYER=aplay
export AUDIO_OUTPUT_DEVICE=default
```

## Demo 参数

`src/task_manager/launch/wakeup_demo.launch.py` 中包含常用参数：

- `locations_file`
- `auto_start_demo`
- `demo_start_delay_sec`
- `navigation_timeout_sec`
- `navigation_retry_limit`
- `tts_topic`

如需启动后自动执行 demo，可将 launch 文件中的 `auto_start_demo` 改为 `True`。

## 已验证

已验证命令：

```bash
python3 -m compileall src/task_manager/task_manager src/rosa_agent/rosa_agent
source /opt/ros/humble/setup.bash
colcon build --packages-select rosa_agent task_manager
source install/setup.bash
ros2 run task_manager task_manager_node --ros-args -p locations_file:=/home/pan/Intelligent_robot/src/task_manager/config/named_locations.yaml
```

节点会以 `IDLE` 状态启动，并加载以下命名地点：

```text
bedroom
charger
living_room
```
