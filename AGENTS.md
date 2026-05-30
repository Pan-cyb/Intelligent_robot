# AGENTS.md

本文件记录本项目中长期有效的协作规则、架构约定和工程边界。阶段性进度、已完成事项和下一步计划放在 `docs/PROJECT_STATUS.md`。

## 项目定位

本项目是养老陪伴机器人 ROS 2 工作空间，当前核心目标是逐步打通：

```text
语音交互
任务调度
命名点导航
Nav2 移动
到达后语音播报
```

当前主要包：

```text
base_controller  底盘、地图、Nav2、RViz、命名点标定
rosa_agent       文字/语音交互、ASR、LLM、TTS
task_manager     任务状态机和任务执行编排
ldlidar_ros2     雷达驱动
```

## 长期架构规则

`task_manager` 是机器人任务执行总入口。语音、大模型、定时器、传感器事件等模块不应直接控制 Nav2 或底盘，而应把任务意图交给 `task_manager`。

推荐链路：

```text
语音 / 大模型 / 定时器 / 传感器事件
        ↓
任务意图
        ↓
task_manager
        ↓
Nav2 / TTS / 其他功能模块
```

模块职责：

```text
rosa_agent:
  负责 ASR、LLM、TTS、语音/文字交互。

person_tracker:
  只负责视觉感知和检测结果发布，不控制 Nav2、底盘、/cmd_vel 或 robot_mode。

follower_controller:
  只负责在 task_manager 允许 FOLLOWING 时执行跟随控制，不拥有整机状态机。

task_manager:
  负责机器人任务状态机、任务准入、导航调用、超时、重试、取消、故障处理。

waypoint_manager:
  负责 RViz 命名点标定、保存和读取命名点。

base_controller:
  负责底盘控制、Nav2 相关启动、地图、RViz 配置。

Nav2:
  负责路径规划、控制和 NavigateToPose action。
```

## 坐标系规则

ROS 车体/相机坐标约定应统一为：

```text
x 前
y 左
z 上
```

深度相机或视觉算法常见 optical frame 为：

```text
x 右
y 下
z 前
```

如果视觉算法直接用像素和深度反投影，发布到 `camera_link` 前必须转换为 ROS body frame：

```text
camera_link.x = optical_z
camera_link.y = -optical_x
camera_link.z = -optical_y
```

不要把 optical frame 的 `z 前方距离` 直接作为 `camera_link.z` 发布，否则 TF 转到 `map` 后会导致目标方向约 90 度偏转。

## 命名点规则

导航目标点应表示机器人真正能停靠的位置，不要使用房间语义中心。

推荐命名：

```text
bedroom_bedside
bedroom_door
livingroom_sofa
charger
charger_front
medicine_box_front
kitchen
```

长期任务运行使用：

```text
src/task_manager/config/named_locations.yaml
```

该文件可使用旧格式：

```yaml
locations:
  bedroom:
    frame_id: map
    x: 1.0
    y: 2.0
    yaw: 0.0
```

也可使用 waypoint 标定生成的新格式：

```yaml
locations:
  bedroom_bedside:
    frame_id: map
    position:
      x: 2.7
      y: 2.5
      z: 0.0
    orientation:
      x: 0.0
      y: 0.0
      z: 0.999
      w: 0.006
```

`task_manager` 应保持兼容这两种格式。

## 音频规则

音频底层通过 `.env` 配置切换，不应在代码里硬编码设备编号。

WSLg 使用 PulseAudio：

```bash
AUDIO_BACKEND=pulse
AUDIO_INPUT_DEVICE=RDPSource
AUDIO_OUTPUT_DEVICE=
AUDIO_SAMPLE_RATE=16000
AUDIO_CHANNELS=1
TTS_PLAYER=paplay
```

RDK X5 / Linux ALSA 使用：

```bash
AUDIO_BACKEND=alsa
AUDIO_INPUT_DEVICE=plughw:1,0
AUDIO_OUTPUT_DEVICE=plughw:2,0
AUDIO_SAMPLE_RATE=16000
AUDIO_CHANNELS=1
TTS_PLAYER=aplay
```

设备编号必须通过 `arecord -l` 和 `aplay -l` 在目标机器上确认。

常驻语音监听应优先复用常驻录音流，不要每轮命令都停止/重启麦克风。原因是每次重启录音设备都会重新经历启动瞬态、warmup 和底噪校准，明显增加交互延迟。推荐做法：

```text
启动一次 parecord/arecord
后台持续读取 PCM 到缓冲区
VAD 从缓冲区截取语音片段
TTS 播放期间通过 speaking/cooldown 门控忽略麦克风触发
TTS 后清空残留缓冲，避免喇叭尾音进入下一轮识别
```

常驻语音延迟调参优先顺序：

```text
ASR_VAD_SILENCE_MS        控制说完后等待多少静音才结束录音
ASR_POST_TTS_COOLDOWN_SEC 控制 TTS 播放后忽略麦克风多久以避开回声
ASR_VAD_MARGIN            误触发/触发不了时再调整
```

## 启动约定

完整服务端优先使用：

```bash
ros2 launch task_manager robot_server.launch.py
```

完整服务端默认启动视觉感知和跟随执行器，但默认不启动 RViz 或 debug window：

```bash
ros2 launch task_manager robot_server.launch.py
```

如需关闭视觉跟随：

```bash
ros2 launch task_manager robot_server.launch.py enable_person_tracker:=false enable_follower_controller:=false
```

如需打开 RViz 或 person_tracker debug window：

```bash
ros2 launch task_manager robot_server.launch.py use_rviz:=true
ros2 launch task_manager robot_server.launch.py debug_window:=true
```

`src/follower_controller/launch/caregiving.launch.py` 仅作为 follower 联调/历史测试入口，主线整机服务端入口是 `task_manager/launch/robot_server.launch.py`。

命令端发布高层任务：

```bash
ros2 service call /robot_server/start_task task_manager_interfaces/srv/StartTask "{task_type: 'wake_up', target: 'bedroom_bedside', text: ''}"
ros2 service call /robot_server/start_task task_manager_interfaces/srv/StartTask "{task_type: 'navigate', target: 'livingroom_sofa', text: ''}"
ros2 service call /robot_server/start_task task_manager_interfaces/srv/StartTask "{task_type: 'speak', target: '', text: '您好，我在这里。'}"
ros2 service call /robot_server/start_task task_manager_interfaces/srv/StartTask "{task_type: 'follow', target: '', text: ''}"
ros2 service call /robot_server/start_task task_manager_interfaces/srv/StartTask "{task_type: 'inspection', target: '', text: ''}"
```

旧兼容入口仅用于历史 wakeup/cancel 测试，不作为新功能扩展入口：

```bash
ros2 service call /trigger_wakeup_task std_srvs/srv/Trigger {}
ros2 topic pub --once /task_command std_msgs/msg/String "{data: wakeup_bedroom}"
```

命名点标定使用：

```bash
ros2 launch base_controller waypoint_calibration.launch.py
```

标定 RViz 的 `2D Goal Pose` 应发布到：

```text
/waypoint_goal
```

不要在标定时发布到 Nav2 的 `/goal_pose`。

## 工程约定

修改代码前先读现有实现，优先沿用当前包结构和命名。

不要把构建产物当作长期配置来源。长期配置应放在 `src/` 内，例如：

```text
src/task_manager/config/named_locations.yaml
src/base_controller/maps/
```

修改源码配置后需要重新 build 并 source：

```bash
cd /home/pan/Intelligent_robot
colcon build --packages-select <package_name>
source install/setup.bash
```

避免重构无关逻辑。新增功能应尽量小步、可验证、可回退。

## 文档约定

长期规则放在：

```text
AGENTS.md
```

阶段进度放在：

```text
docs/PROJECT_STATUS.md
```

具体功能文档可放在对应包内：

```text
src/base_controller/doc/
src/rosa_agent/doc/
src/task_manager/doc/
```

## 会话交接约定

会话结束前应更新：

```text
AGENTS.md
docs/PROJECT_STATUS.md
```

并在以下目录生成新的 handoff 文档：

```text
docs/handoff/
```

新会话开始时，先读取：

```text
AGENTS.md
docs/PROJECT_STATUS.md
docs/handoff/ 中最新的 handoff 文档
```

如果用户要求“直接继续干活”，读取以上文档后直接继续实现下一步，不需要重新解释背景。

当前已安装一个通用 Codex skill 用于该流程：

```text
/home/pan/.codex/skills/project-context-handoff/SKILL.md
```

该 skill 是普适性的，不绑定本项目。
