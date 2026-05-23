# PROJECT_STATUS.md

本文件记录养老陪伴机器人项目当前阶段进度。长期规则放在顶层 `AGENTS.md`。

## 当前阶段

当前高层任务接口闭环已经完成。已跑通/可构建链路：

```text
ROSA / 命令端发高层任务
  -> /robot_server/start_task
  -> task_manager 接收 task_type/target/text
  -> 读取命名地点
  -> Nav2 导航
  -> 到达后发布 /tts_text
  -> rosa_agent tts_node 播放语音
  -> task_manager 回到 IDLE
```

ROSA 默认 action tools 现在只暴露高层任务工具，不直接调用 Nav2、`/cmd_vel` 或底层动作序列。

## 已完成

### 语音模块

`rosa_agent` 已支持 WSLg PulseAudio 和 RDK X5 / Linux ALSA。

配置文件：

```text
src/rosa_agent/.env.example
```

说明文档：

```text
src/rosa_agent/doc/voice_usage.md
```

主要能力：

```text
AUDIO_BACKEND=pulse 使用 parecord/paplay
AUDIO_BACKEND=alsa 使用 arecord/aplay
TTS 可通过 tts_node 订阅 /tts_text 播放
```

### 命名点标定

`base_controller` 已新增 `waypoint_manager`。

标定启动：

```bash
ros2 launch base_controller waypoint_calibration.launch.py
```

RViz 中 `2D Goal Pose` 发布到：

```text
/waypoint_goal
```

服务：

```text
/waypoint_manager/save_last_goal
/waypoint_manager/get_pose
/waypoint_manager/list_poses
/waypoint_manager/delete_pose
```

说明文档：

```text
src/base_controller/doc/waypoint_manager_usage.md
```

### 任务管理

`task_manager` 已升级为 robot 服务端高层任务状态机。

当前真实命名地点文件：

```text
src/task_manager/config/named_locations.yaml
```

当前包含真实标定点：

```text
bedroom_bedside
charger
kitchen
livingroom_sofa
```

`task_manager` 已兼容：

```text
x/y/yaw 旧格式
position/orientation 四元数格式
```

当前叫醒任务目标：

```text
bedroom_bedside
```

高层服务：

```text
/robot_server/start_task
/robot_server/start_wakeup_task
/robot_server/cancel_current_task
/robot_server/query_robot_state
```

接口包：

```text
src/task_manager_interfaces
```

`/robot_server/start_task` 使用：

```text
task_manager_interfaces/srv/StartTask
```

支持任务：

```text
task_type="wake_up"   target 默认为 bedroom_bedside，流程 SCHEDULED_TASK -> NAVIGATION -> CONVERSATION -> IDLE
task_type="navigate"  target 为命名点，流程 NAVIGATION -> IDLE
task_type="speak"     text 为播报内容，流程 CONVERSATION -> IDLE
```

### 完整服务端

已新增一键服务端 launch：

```text
src/task_manager/launch/robot_server.launch.py
```

启动：

```bash
cd /home/pan/Intelligent_robot
source install/setup.bash
ros2 launch task_manager robot_server.launch.py
```

该 launch 启动：

```text
base_controller/navigation.launch.py
task_manager_node
rosa_agent/tts_node
```

说明文档：

```text
src/task_manager/doc/robot_server_usage.md
```

### 项目上下文与交接

已在项目顶层建立长期上下文和阶段进度文档：

```text
AGENTS.md
docs/AGENT.md
docs/PROJECT_STATUS.md
```

已创建通用 Codex skill：

```text
/home/pan/.codex/skills/project-context-handoff/SKILL.md
```

该 skill 是普适性的，不绑定本项目。用途是维护任意项目中的：

```text
AGENTS.md
docs/PROJECT_STATUS.md
docs/handoff/
```

约定：

```text
长期规则写入 AGENTS.md
阶段进度写入 docs/PROJECT_STATUS.md
会话交接写入 docs/handoff/
```

## 当前最小闭环运行方式

状态：已完成并可按以下流程复现。

编译：

```bash
cd /home/pan/Intelligent_robot
source /opt/ros/humble/setup.bash
colcon build --packages-select base_controller rosa_agent task_manager_interfaces task_manager
source install/setup.bash
```

服务端：

```bash
ros2 launch task_manager robot_server.launch.py
```

命令端：

```bash
ros2 service call /trigger_wakeup_task std_srvs/srv/Trigger {}
```

推荐新接口：

```bash
ros2 service call /robot_server/start_task task_manager_interfaces/srv/StartTask "{task_type: 'wake_up', target: 'bedroom_bedside', text: ''}"
ros2 service call /robot_server/start_task task_manager_interfaces/srv/StartTask "{task_type: 'navigate', target: 'livingroom_sofa', text: ''}"
ros2 service call /robot_server/start_task task_manager_interfaces/srv/StartTask "{task_type: 'speak', target: '', text: '您好，我在这里。'}"
```

查看状态：

```bash
ros2 topic echo /robot_mode
```

或：

```bash
ros2 service call /robot_server/query_robot_state task_manager_interfaces/srv/QueryRobotState {}
```

取消任务：

```bash
ros2 service call /robot_server/cancel_current_task std_srvs/srv/Trigger {}
```

旧兼容取消入口：

```bash
ros2 service call /cancel_task std_srvs/srv/Trigger {}
```

清除故障：

```bash
ros2 service call /clear_fault std_srvs/srv/Trigger {}
```

## 当前架构理解

`task_manager_node` 是任务状态机，不直接控制底盘。

核心流程：

```text
/robot_server/start_task
  -> _on_start_task
  -> _start_task
  -> 根据 task_type 选择 wake_up / navigate / speak
  -> _dispatch_navigation_task 或 _start_conversation
  -> _send_navigation_goal
  -> Nav2 NavigateToPose
  -> _on_navigation_result
  -> _start_conversation
  -> 发布 /tts_text
```

`_on_trigger_wakeup` 和 `_on_task_command` 仅作为旧兼容入口保留，不再作为新增任务的扩展入口。

`rosa_agent` 默认 action tools 已改为调用 robot 服务端高层 service。自然语言语音输入应选择高层工具，不应发布 `/cmd_vel`、调用 Nav2 或拼接底层 service。

## 重要文件

```text
src/task_manager/task_manager/task_manager_node.py
src/task_manager_interfaces/srv/StartTask.srv
src/task_manager_interfaces/srv/QueryRobotState.srv
src/task_manager/config/named_locations.yaml
src/task_manager/launch/robot_server.launch.py
src/base_controller/launch/navigation.launch.py
src/base_controller/launch/waypoint_calibration.launch.py
src/rosa_agent/rosa_agent/voice.py
src/rosa_agent/rosa_agent/tts_node.py
```

## 下一步建议

1. 新会话开始时先读 `AGENTS.md`、`docs/PROJECT_STATUS.md` 和最新 handoff 文档。
2. 启动 robot 服务端后，用 `/robot_server/start_task` 做真实 Nav2/TTS 端到端验证。
3. 从 ROSA 语音入口验证高层工具调用：

```text
start_wakeup_task()
navigate_to_named_place(place_name)
speak_text(text)
cancel_current_task()
query_robot_state()
```

4. 后续再考虑增加新高层任务类型，例如回充、取药提醒，而不是扩展 `/task_command` 字符串协议。
5. 继续完善异常处理，例如导航失败后的播报、低电量回充、任务优先级。

## 注意事项

`wakeup_demo.launch.py` 仍可作为轻量 demo 保留，它只启动：

```text
task_manager_node
tts_node
```

完整服务端请优先使用：

```bash
ros2 launch task_manager robot_server.launch.py
```

命名点标定不要使用 `/goal_pose`，应使用 `/waypoint_goal`。

修改 `src/task_manager/config/named_locations.yaml` 后，如果使用默认安装路径运行，需要重新 build。
