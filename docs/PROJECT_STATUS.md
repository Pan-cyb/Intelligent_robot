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

2026-05-25 开始优化视觉跟随执行方式：

```text
follower_controller 新增 cmd_vel 后端：
  /person_position + /person_distance
    -> follower_cmd_vel_controller
    -> /cmd_vel_follow

Nav2 速度输出：
  controller_server
    -> /cmd_vel_nav_raw
    -> nav2_velocity_smoother
    -> /cmd_vel_nav

velocity_mux:
  FOLLOWING 时使用 /cmd_vel_follow
  其他模式默认使用 /cmd_vel_nav
  最终只由 velocity_mux 输出 /cmd_vel
```

主线服务端新增跟随后端参数：

```bash
ros2 launch task_manager robot_server.launch.py follow_backend:=nav2
ros2 launch task_manager robot_server.launch.py follow_backend:=cmd_vel
```

当前默认仍为 `nav2`，用于保守回退；测试实时跟随时使用 `follow_backend:=cmd_vel`。

2026-05-24 最终综合 demo 已调整为轻量 VSCode 终端启动方案：

```text
robot_server.launch.py
  默认启动摄像头、person_tracker 和 follower_controller。
  默认关闭 RViz 和 debug window，减少图形窗口负载。

demo_manager
  独立负责最终 demo 流程编排。
  不直接控制 Nav2、不发布 /cmd_vel、不执行单任务内部逻辑。
  只通过 /robot_server/start_task 和 /robot_server/query_robot_state 驱动 task_manager。

最终轻量 demo 流程：
  WAKE_UP
    -> task_type="wake_up", target="bedroom_bedside"
  COMPANION_NAVIGATE
    -> task_type="navigate", target="livingroom_sofa"
  COMPANION_DIALOGUE
    -> task_type="speak"
  WAIT_FOR_FOLLOW_TRIGGER
    -> 等 ROSA 语音触发 task_type="follow"
```

为降低卡顿，最终 demo 当前不再自动触发 inspection 巡航；`inspection` 单任务能力仍保留在 `task_manager`，可通过 `/robot_server/start_task` 手动触发。

轻量启动：

```bash
ros2 launch task_manager robot_server.launch.py enable_demo_manager:=true enable_rosa_always_listen:=true
```

如需 RViz：

```bash
ros2 launch task_manager robot_server.launch.py \
  enable_demo_manager:=true \
  enable_rosa_always_listen:=true \
  use_rviz:=true
```

2026-05-23 ROSA action tools 新增联网天气建议能力：

```text
get_weather_advice(location)
```

该工具使用 Open-Meteo 免 key API 查询地点天气和未来几小时预报，返回中文天气摘要和养老陪护建议，例如降雨时提醒收衣服、关窗、减少外出，高温时提醒补水，低温时提醒加衣。该工具只做信息查询和建议，不直接控制机器人底盘、Nav2 或 task_manager 状态。

已修复 ROSA CLI 未调用天气工具的问题：

```text
根因：
  get_weather_advice 已实现，但没有加入 DEFAULT_TOOLS。
  rosa_cli 的直连路由也没有识别“天气/下雨/气温”等关键词。

修复：
  DEFAULT_TOOLS 加入 get_weather_advice、start_following_task、start_inspection_task。
  rosa_cli 识别天气问题并直接调用 get_weather_advice(location)。
```

同日 `task_manager` 修复 Nav2 action 异步回调污染状态机风险：Nav2 goal response/result 现在绑定 generation token，取消、EMERGENCY、任务重置后旧回调会被忽略；INSPECTION 导航也纳入 watchdog 超时检查。

2026-05-23 已完成视觉跟随架构职责重构：

```text
person_tracker:
  只做视觉感知，发布 /person_position /person_distance /person_hand_position /fall_detected。

follower_controller:
  只做 FOLLOWING 模式下的 Nav2 跟随执行器。
  只有 /robot_mode == FOLLOWING 时才发送跟随 goal。
  /robot_mode 退出 FOLLOWING 时取消 goal 并空闲。

task_manager / robot_server:
  是唯一整机状态机和任务调度中心。
  支持 wake_up / navigate / speak / follow / inspection。
  订阅 /fall_detected 做连续帧确认后进入 EMERGENCY。
```

主线服务端入口现在是：

```bash
ros2 launch task_manager robot_server.launch.py
```

当前默认启动视觉感知和跟随执行器，但不启动 RViz 或 debug window；如需关闭视觉跟随：

```bash
ros2 launch task_manager robot_server.launch.py enable_person_tracker:=false enable_follower_controller:=false
```

`src/follower_controller/launch/caregiving.launch.py` 保留为 follower 联调/历史测试入口。

2026-05-23 新增检查并修复 `caregiving.launch.py` 人物跟随链路：

```text
camera
  -> person_tracker 发布 /person_position /person_hand_position /person_distance
  -> follower_nav2_controller 转到 map
  -> NavigateToPose 发送跟随目标
  -> Nav2 控制小车
```

本次问题表现：人物在相机前方时，Nav2 端收到的人物方向目标点疑似偏转约 90 度。

根因：`person_tracker` 使用像素和深度反投影得到的是 optical frame 坐标：

```text
x 右
y 下
z 前
```

但节点把该点标成 `camera_link` 直接发布。工作空间中的 `camera_link`/`base_link` 约定应是 ROS body frame：

```text
x 前
y 左
z 上
```

因此“前方距离”被错误放在 `camera_link.z` 上，TF 转到 `map` 后会造成目标方向约 90 度偏转。

已修复：

```text
src/person_tracker/scripts/person_tracker_node.py
  - 发布 /person_position 前将 optical frame 转为 ROS camera_link body frame。
  - 人体位置 EMA 从 x/y 扩展为 x/y/z，/person_distance 继续单独发布真实深度距离。

src/follower_controller/scripts/follower_nav2_controller.py
  - 角度计算改为使用 ROS 平面 x/y。
  - 不再直接把人物点作为 Nav2 目标。
  - 根据 map->base_link 和人物 map 坐标生成保留 follow_distance 的跟随停靠点。
  - 目标朝向人物或手部。

src/follower_controller/launch/caregiving.launch.py
  - 注释改为用 /person_distance 校准距离，不再参考 /person_position.z。
```

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
task_type="follow"    流程 FOLLOWING，follower_controller 收到 /robot_mode 后执行跟随
task_type="inspection" 流程 INSPECTION，依次巡检配置点并观察 /person_position
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
colcon build --packages-select base_controller rosa_agent task_manager_interfaces task_manager demo_manager
source install/setup.bash
```

轻量综合 demo 服务端：

```bash
ros2 launch task_manager robot_server.launch.py enable_demo_manager:=true enable_rosa_always_listen:=true
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
src/demo_manager/demo_manager/demo_manager_node.py
src/demo_manager/launch/demo_manager.launch.py
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
start_following_task()
start_inspection_task()
get_weather_advice(location)
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

## 人物跟随运行方式

编译：

```bash
cd /home/pan/Intelligent_robot
source /opt/ros/humble/setup.bash
colcon build --packages-select person_tracker follower_controller
source install/setup.bash
```

启动 caregiving 全链路：

```bash
ros2 launch follower_controller caregiving.launch.py rviz:=true
```

调试重点：

```bash
ros2 topic echo /person_position
ros2 topic echo /person_distance
```

人在相机正前方时，`/person_position.point.x` 应接近实际距离，`point.y` 应接近 0，`point.z` 表示上下方向偏移；`/person_distance` 是用于距离校准的标量距离。

当前已做静态验证：

```bash
python3 -m py_compile src/person_tracker/scripts/person_tracker_node.py src/follower_controller/scripts/follower_nav2_controller.py src/follower_controller/launch/caregiving.launch.py src/follower_controller/launch/follower_nav2.launch.py
```

仍需在真实机器人上验证：

```text
1. RViz 中人物目标方向是否不再偏转 90 度。
2. follower 是否保持 follow_distance，而不是直冲人体中心。
3. 任务管理器非 IDLE 时 follower 是否正确让出 Nav2。
```
