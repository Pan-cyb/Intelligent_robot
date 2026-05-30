# 养老陪护机器人性能优化与大换血路线

本文档用于补充 `elderly_companion_robot_roadmap.md`。当前系统已经完成了从语音/文字命令到 `task_manager`、Nav2、TTS、视觉感知、跟随和应急状态的功能闭环，但综合 demo 存在明显卡顿。下一阶段目标不是继续堆功能，而是把现有原型系统改造成可长期运行的实时系统。

## 1. 当前问题判断

当前系统大致分为三条主链路：

```text
导航链路：
  base_controller + ldlidar_ros2 + Nav2 + task_manager

语音链路：
  always_listen_voice_cli.py + ASR + LLM/agent tools + TTS

视觉链路：
  ascamera + person_tracker(MediaPipe) + follower_controller + task_manager emergency
```

从现有联调表现看，导航链路相对稳定，主要卡顿来自语音链路和视觉链路。

### 1.1 导航链路现状

导航链路目前是项目中最稳定的部分：

- Nav2 可以执行命名点导航。
- `task_manager` 可以发起 `wake_up`、`navigate`、`inspection` 等任务。
- `robot_server.launch.py` 已经作为整机服务端入口。

后续导航链路主要需要做的是稳定性和安全层增强，而不是重写。

### 1.2 语音链路现状

当前语音链路是：

```text
VAD 录音
  -> 网络 ASR
  -> LLM/agent tools
  -> 网络 TTS
  -> 播放
  -> cooldown
  -> 重新监听
```

问题：

- ASR 和 TTS 依赖网络，请求延迟不稳定。
- 唤醒词识别依赖完整录音后再转写，不是真正低延迟本地唤醒。
- 为避免机器人把自己的 TTS 录进去，播放后加入 cooldown，导致人机对话中间有空窗。
- 简单命令也会进入较长链路，导致“说几次小智才有反应”的体验。

优点：

- API 和 agent tools 已经配置完成。
- 高层动作调用已经走 `robot_server`，安全边界是对的。

### 1.3 视觉链路现状

当前视觉链路是：

```text
RGBD 相机
  -> cv_bridge
  -> MediaPipe Holistic CPU 推理
  -> /person_position /person_distance /fall_detected
  -> follower_controller
```

问题：

- MediaPipe Holistic 跑在 CPU 上，模型较重。
- 联调时 CPU 还要承担 ROS2、Nav2、语音流程、Python 节点等工作。
- 视觉帧率低且抖动，导致 `/person_position` 更新不稳定。
- 跟随控制当前基于频繁发送 Nav2 `NavigateToPose` goal，不适合连续跟随。
- TF 转换与 Nav2 goal 更新叠加后，跟随效果容易一卡一卡。

优点：

- 已经完成了人体位置、手部位置、摔倒候选等 ROS topic 接口。
- `follower_controller` 已经被收敛为只在 `FOLLOWING` 下工作，架构边界正确。

## 2. RDK X5 的正确使用方式

RDK X5 不应该只当普通 Ubuntu 卡片机使用。它的关键优势是有 D-Robotics 的 BPU 推理能力和机器人视觉生态。

建议重新分工：

```text
CPU：
  ROS2
  task_manager
  Nav2
  base_controller
  语音流程调度
  agent tools
  状态机和业务逻辑

BPU：
  人体检测
  姿态估计
  YOLO/YOLOPose 推理
  摔倒检测前端模型

多媒体/相机链路：
  相机采集
  图像预处理
  视频流输入
```

下一阶段要避免把所有视觉 AI 都压到 CPU 上。

## 3. 总体优化目标

下一阶段目标：

```text
视觉实时化
跟随平滑化
语音低延迟化
状态机保持集中
安全监护本地可运行
```

目标指标建议：

```text
导航：
  命名点导航成功率稳定
  普通任务取消后无旧回调污染

视觉：
  人体检测稳定达到 10Hz 以上
  摔倒候选检测延迟小于 1 秒
  BPU 有明确占用，CPU 负载下降

跟随：
  控制频率 10-20Hz
  不再每秒反复发 Nav2 全局目标
  人在 1-3 米范围内移动时跟随平滑

语音：
  唤醒词响应明显变快
  简单命令不必全部走大模型
  TTS 不阻塞下一次监听太久
```

## 4. 架构重构方向

### 4.1 视觉模块重构

当前：

```text
person_tracker
  MediaPipe Holistic CPU
  输出 /person_position /fall_detected
```

目标：

```text
vision_perception_bpu
  RDK X5 BPU YOLO / YOLOPose
  输出 /person_detection
       /person_position
       /person_keypoints

risk_detector
  根据 bbox/keypoints/depth/time window 判断摔倒
  输出 /fall_detected 或 /emergency_event
```

推荐分阶段：

1. 先用 BPU YOLO 做人体框检测，替代 MediaPipe 的人体检测。
2. 结合深度相机输出人体相对位置。
3. 再上 YOLOPose/keypoint 模型，替代 MediaPipe 姿态点。
4. 摔倒检测从单帧姿态角度，升级为时间窗口判断。

摔倒检测建议依据：

```text
人体框宽高比变化
人体框中心高度下降
关键点躯干角度
髋部/肩部高度变化
持续低姿态时间
深度距离稳定性
```

不要单帧触发，应继续保留 `task_manager` 中的确认逻辑。

### 4.2 跟随模块重构

当前：

```text
follower_controller
  /person_position -> map
  计算跟随点
  反复发送 NavigateToPose goal
```

问题是 Nav2 action 适合去固定目标点，不适合实时跟人。

目标：

```text
person_following
  /person_position
  -> 局部控制律
  -> /cmd_vel_follow

velocity_mux
  /cmd_vel_nav
  /cmd_vel_follow
  /cmd_vel_manual
  /safety_stop
  -> /cmd_vel
```

推荐跟随控制：

```text
距离误差:
  error_d = person_distance - follow_distance
  linear_x = Kd * error_d

角度误差:
  error_yaw = atan2(person_y, person_x)
  angular_z = Kyaw * error_yaw

安全限制:
  max_linear
  max_angular
  min_distance_stop
  obstacle_stop
```

Nav2 后续只用于：

- 去命名点。
- 巡检。
- 老人丢失后导航到最后已知位置。

### 4.3 语音模块重构

当前：

```text
always_listen_voice_cli.py
  VAD -> 网络 ASR -> LLM -> 网络 TTS
```

目标：

```text
voice_agent
  本地唤醒词
  本地或低延迟 ASR
  简单命令关键词直达
  复杂对话再走 LLM
  TTS 缓存常用语音
```

建议分层：

```text
本地快速层：
  小智
  跟着我
  停止
  去厨房
  回充电
  现在状态
  救命

LLM 层：
  陪伴聊天
  天气建议
  日程解释
  复杂自然语言理解
```

常用 TTS 建议预生成或缓存：

```text
我在。
好的。
正在执行。
我没有听清楚。
检测到异常，您是否需要帮助？
我看到您了。
我没有找到您。
```

这样可以减少网络 TTS 的等待时间。

### 4.4 状态机保持不变

重构时不要破坏已有正确边界：

```text
task_manager:
  唯一整机状态机中心

person_tracker / vision_perception:
  只发布感知结果

person_following:
  只在 FOLLOWING 下输出跟随速度

ROSA / voice_agent:
  只调用高层 service

demo_manager:
  只做流程编排
```

## 5. 推荐实施路线

### 阶段 0：保住当前 demo

目标：让现有 demo 尽量不卡。

任务：

1. 关闭 RViz 和所有 debug window。
2. MediaPipe 降频，例如每 3-5 帧处理一次。
3. MediaPipe `model_complexity` 改为 0。
4. 暂时关闭手部检测，只保留人体位置和摔倒候选。
5. 降低相机分辨率或推理输入尺寸。
6. 减少 follower 日志频率。
7. 简单语音命令绕过 LLM，直接调用 tools。

验收：

- 综合 demo 可连续跑通。
- CPU 占用下降。
- 视觉 topic 频率可测。

### 阶段 1：跟随控制换成局部速度

目标：解决跟随一卡一卡的问题。

任务：

1. 新建或改造 `person_following`。
2. 根据 `/person_position` 直接输出 `/cmd_vel_follow`。
3. 新建 `velocity_mux`。
4. Nav2 输出 remap 到 `/cmd_vel_nav`。
5. `velocity_mux` 根据 `/robot_mode` 选择输出。
6. 保留旧 `follower_nav2_controller` 作为备份。

验收：

- `FOLLOWING` 模式下不再频繁发送 Nav2 goal。
- 人在前方移动时底盘跟随更平滑。
- 退出 FOLLOWING 时速度立即归零。

### 阶段 2：视觉迁移到 BPU

目标：用 RDK X5 的 BPU 替代 CPU MediaPipe 主链路。

任务：

1. 跑通 D-Robotics 官方 BPU YOLO 示例。
2. 确认 `hrut_bpuprofile -b 0` 能看到 BPU 占用。
3. 新建 `vision_perception_bpu` 包。
4. 使用 BPU YOLO 输出人体框。
5. 结合深度图输出 `/person_position`。
6. 保持输出接口兼容旧 `person_tracker`：

```text
/person_position
/person_distance
/fall_detected
```

7. 后续再加入 YOLOPose/keypoints。

验收：

- BPU 有稳定占用。
- CPU 占用明显下降。
- 人体位置输出稳定达到 10Hz 以上。

### 阶段 3：摔倒检测升级

目标：降低误报，提高稳定性。

任务：

1. 新建 `risk_detector`。
2. 输入 `/person_detection`、`/person_keypoints`、`/person_position`。
3. 使用时间窗口确认摔倒。
4. 输出 `/fall_detected` 或 `/emergency_event`。
5. `task_manager` 只接收确认后的风险事件。

验收：

- 正常坐下、弯腰不频繁误报。
- 模拟摔倒能在 1-2 秒内触发。
- 应急抢占稳定。

### 阶段 4：语音链路优化

目标：让语音交互从“能用”变成“顺手”。

任务：

1. 本地唤醒词替代网络转写唤醒。
2. 简单命令关键词直达：

```text
跟着我 -> start_following_task
停下 -> cancel_current_task
去厨房 -> navigate_to_named_place(kitchen)
回充电 -> navigate_to_named_place(charger)
救命 -> emergency
```

3. 常用 TTS 语音缓存。
4. LLM 只处理复杂对话。
5. 将语音 agent 改成 ROS2 节点，发布 `/asr_text`、`/dialogue_event`。

验收：

- 唤醒后 1 秒内有反馈。
- 简单命令不依赖 LLM。
- 网络波动时基本控制命令仍可用。

## 6. 新模块建议

建议未来模块结构：

```text
vision_perception_bpu
  BPU YOLO / YOLOPose 推理

risk_detector
  摔倒、静止、异常行为判断

person_following
  局部跟随速度控制

velocity_mux
  多速度源仲裁

voice_agent
  本地唤醒、ASR、命令直达、LLM 对话

demo_manager
  演示流程编排
```

旧模块保留策略：

```text
person_tracker
  保留为 CPU fallback 和对照测试

follower_nav2_controller
  保留为 Nav2-based 备份方案

always_listen_voice_cli.py
  保留为 CLI 调试入口
```

## 7. 性能观测指标

每次优化都要记录指标，不要只凭体感。

建议命令：

```bash
top
htop
mpstat -P ALL 1
ros2 topic hz /person_position
ros2 topic hz /fall_detected
ros2 topic hz /cmd_vel
ros2 run tf2_ros tf2_echo map base_link
hrut_bpuprofile -b 0
cat /sys/devices/system/bpu/bpu0/ratio
```

建议记录：

```text
CPU 总占用
单进程 CPU 占用
BPU 占用
/person_position 频率
follow 控制频率
语音唤醒到响应时间
TTS 生成到播放时间
Nav2 成功率
```

## 8. 最终目标架构

最终理想结构：

```text
robot_server.launch.py
  启动整机能力

task_manager
  统一状态机

demo_manager
  场景编排

voice_agent
  本地唤醒 + 快速命令 + LLM 对话

vision_perception_bpu
  BPU 人体/姿态识别

risk_detector
  风险确认

person_following
  局部跟随控制

velocity_mux
  速度仲裁

Nav2
  命名点导航、巡检、回充、丢失重定位

base_controller
  底盘控制
```

核心原则：

```text
功能可以多，但控制权不能乱。
AI 可以强，但安全决策必须本地可运行。
视觉必须实时，跟随必须局部闭环，语音必须分层响应。
```
