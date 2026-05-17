# Navigation Tuning Since `a73e069`

本文对比当前版本 `fc065fa` 与基准版本 `a73e06972d0001ab22a188a2505ce403fd9c7995`，梳理这段时间导航、雷达和速度链路的主要参数变化。

基准版本是提交：

```text
a73e069 docs: add elderly companion robot roadmap
```

当前版本是：

```text
fc065fa 修改限速
```

## 总体目标

这轮调参主要解决三个问题：

1. 局部规划器偶尔偏离全局路径，向左绕大弯并贴墙。
2. 速度输出不连续，小车走起来一顿一顿。
3. 雷达近距离数据被 20cm 阈值过滤，近处障碍和定位输入不够完整。

最终策略是：先弱化局部规划器的自由绕行能力，让小车更像“沿全局路径跟踪”；再接入速度平滑器，减少 `/cmd_vel` 跳变；最后放开过度保守的限速参数，使速度恢复到接近旧版本。

## 主要提交过程

从 `a73e069` 到当前版本，中间主要经历了这些导航相关提交：

```text
89a1e9f 修改代价地图膨胀半径
49d59f0 修改代价地图膨胀半径
6e56ca3 修改代价地图膨胀半径
a6df2af 修改代价地图膨胀半径
98a3de4 修改DWB
e488d24 调整导航参数
b97933f 修改fllowpath参数
e2bb0cd 修复报错
ec0c6ac 建图修改
1cf4a51 Revert "建图修改"
dc01c63 修改导航参数，轻量化版本
02ed68f 参数修改
e9243d3 修改雷达裁剪
1981e2e 调整导航局部控制参数
f547b00 接入速度平滑器改善导航卡顿
8ddd4a2 提高导航跟踪速度
fc065fa 修改限速
```

其中 `ec0c6ac` 的建图参数修改已经被 `1cf4a51` 撤回，因此当前导航行为主要由后续 Nav2 参数、雷达裁剪和速度平滑器决定。

## 局部控制器变化

基准版本使用 DWB：

```yaml
FollowPath:
  plugin: "dwb_core::DWBLocalPlanner"
  max_vel_x: 0.26
  max_vel_theta: 1.0
  vx_samples: 20
  vtheta_samples: 20
  sim_time: 1.7
  critics: ["RotateToGoal", "Oscillation", "BaseObstacle", "GoalAlign", "PathAlign", "PathDist", "GoalDist"]
  PathAlign.scale: 32.0
  PathDist.scale: 32.0
  GoalAlign.scale: 24.0
  GoalDist.scale: 24.0
  RotateToGoal.scale: 32.0
```

当前版本改成 Regulated Pure Pursuit：

```yaml
FollowPath:
  plugin: "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController"
  desired_linear_vel: 0.26
  lookahead_dist: 0.45
  min_lookahead_dist: 0.35
  max_lookahead_dist: 0.70
  lookahead_time: 0.6
  use_collision_detection: true
  allow_reversing: false
  use_regulated_linear_velocity_scaling: false
  use_cost_regulated_linear_velocity_scaling: false
  use_rotate_to_heading: false
```

### 为什么这样改

DWB 会在局部窗口内采样多条速度轨迹，然后用 critic 打分。全局路径没问题时，如果局部代价地图、障碍物膨胀、雷达噪声或 odom 有偏差，DWB 可能选中一条“看起来得分更低但实际绕很大”的轨迹。这就是之前出现“向左绕大弯，然后贴墙”的主要风险。

Regulated Pure Pursuit 的行为更接近路径跟踪：它在全局路径上找前视点，然后控制小车追这个点。它不会像 DWB 那样自由生成大范围绕行轨迹，因此更符合当前需求：全局路径可靠，局部控制器只需要老实跟着走。

### 关键参数含义

`desired_linear_vel: 0.26`

目标线速度。当前设为 0.26m/s，接近旧 DWB 的 `max_vel_x: 0.26`。

`lookahead_dist: 0.45`

前视距离。越小越贴路径，但容易频繁修正、速度慢；越大越平滑，但转弯可能切角。当前 0.45 是在“贴路径”和“不龟速”之间的折中。

`min_lookahead_dist` / `max_lookahead_dist`

前视距离上下限。当前关闭了速度缩放前视距离，但这些参数仍保留为安全范围。

`allow_reversing: false`

禁止倒车。避免局部控制器为了调整姿态产生倒车或奇怪轨迹。

`use_collision_detection: true`

保留碰撞检测。虽然关闭了部分限速机制，但仍会检查前视路径上的碰撞风险。

`use_regulated_linear_velocity_scaling: false`

关闭曲率限速。之前开启时，小车在弯道、路径局部角度变化处会主动降速，实车体感很慢。

`use_cost_regulated_linear_velocity_scaling: false`

关闭代价场限速。之前开启时，小车靠近墙或障碍膨胀区会频繁降速，容易造成一顿一顿。

`use_rotate_to_heading: false`

关闭起步/路径跟踪阶段的“先原地转向”。这样可以避免小车在路径跟踪中频繁停下来转头，提高连续性。

## 目标附近不愿意原地转向的问题

你观察到“到达目标附近时，小车似乎不愿意原地转圈调整位姿”，这个确实和当前局部控制器参数有关。

当前版本里：

```yaml
use_rotate_to_heading: false
```

这会让 RPP 更偏向连续跟踪路径，而不是在目标附近停下来原地旋转对准最终 yaw。这样做的好处是移动过程更流畅、不龟速；代价是最终姿态调整能力会弱一些。

另外，目标检查器仍然要求：

```yaml
xy_goal_tolerance: 0.25
yaw_goal_tolerance: 0.25
```

`yaw_goal_tolerance: 0.25` 大约是 14.3 度。如果目标要求的朝向和实际朝向差得比较多，而控制器又不启用原地旋转，就可能表现为“位置到了，但姿态不太愿意精调”。

后续如果需要增强终点姿态对齐，可以优先尝试：

```yaml
use_rotate_to_heading: true
rotate_to_heading_angular_vel: 1.0
rotate_to_heading_min_angle: 0.5
```

但这个修改可能重新带来“停顿感”。更稳妥的折中是只在最终阶段放开旋转，或者把 `yaw_goal_tolerance` 放宽到 `0.35~0.5`，如果业务上不强制要求最终朝向精确。

## 速度平滑链路变化

基准版本中虽然有 `velocity_smoother` 参数，但 `navigation.launch.py` 没有启动速度平滑器。控制器直接输出 `/cmd_vel` 给底盘。

当前版本把速度链路改成：

```text
controller_server -> /cmd_vel_nav -> velocity_smoother -> /cmd_vel -> base_controller
```

对应 launch 修改：

```python
remappings=[('cmd_vel', 'cmd_vel_nav')]

Node(
    package='nav2_velocity_smoother',
    executable='velocity_smoother',
    name='velocity_smoother',
    remappings=[
        ('cmd_vel', 'cmd_vel_nav'),
        ('cmd_vel_smoothed', 'cmd_vel')
    ]
)
```

### 为什么这样改

局部控制器输出的速度可能因为路径曲率、障碍物、TF 抖动或目标接近而跳变。底盘直接吃这些跳变时，实车会表现为一顿一顿。

速度平滑器把原始导航速度 `/cmd_vel_nav` 变成更连续的 `/cmd_vel`，再发给底盘。这样可以保留导航响应，同时降低速度突变。

当前参数：

```yaml
velocity_smoother:
  smoothing_frequency: 30.0
  feedback: "OPEN_LOOP"
  max_velocity: [0.26, 0.0, 1.0]
  min_velocity: [0.0, 0.0, -1.0]
  max_accel: [2.5, 0.0, 3.2]
  max_decel: [-2.5, 0.0, -3.2]
```

`smoothing_frequency: 30.0`

平滑器以 30Hz 输出速度，比原来的 20Hz 更细。

`max_velocity`

限制最大速度。当前线速度最大 0.26m/s，角速度最大 1.0rad/s。

`min_velocity: [0.0, 0.0, -1.0]`

禁止负线速度，即不允许倒车；角速度允许正反转。

`max_accel` / `max_decel`

限制速度变化率。之前一度调得太小，导致小车起步和加速过慢；当前恢复到接近旧 DWB 的响应能力。

## 代价地图变化

局部代价地图从基准版本：

```yaml
width: 3
height: 3
plugins: ["voxel_layer", "inflation_layer"]
inflation_radius: 0.25
cost_scaling_factor: 3.0
```

改为当前版本：

```yaml
width: 4
height: 4
plugins: ["obstacle_layer", "inflation_layer"]
inflation_radius: 0.35
cost_scaling_factor: 4.0
```

全局代价地图膨胀从：

```yaml
inflation_radius: 0.25
cost_scaling_factor: 3.0
```

改为：

```yaml
inflation_radius: 0.45
cost_scaling_factor: 2.0
```

### 为什么这样改

局部窗口从 3m 扩到 4m，可以让控制器提前看到更多障碍信息，减少快贴到墙边才反应的情况。

局部代价地图从 `VoxelLayer` 改为 `ObstacleLayer`，更符合当前 2D LaserScan 的输入。LD06 是 2D 雷达，不需要维护 3D voxel 结构，使用 `ObstacleLayer` 更直接。

膨胀半径增大后，墙和障碍物周围的代价区更明显，小车不容易贴墙走。局部 `cost_scaling_factor: 4.0` 让近障碍的代价变化更陡，帮助控制器更明确地区分安全区和贴墙区。

全局膨胀半径增大到 0.45，则全局路径会更倾向离墙一点。`cost_scaling_factor: 2.0` 让全局代价衰减更平缓，有助于生成更自然的离墙路径。

## 雷达裁剪和近距变化

LD06 当前仍启用角度裁剪：

```python
{'enable_angle_crop_func': True},
{'angle_crop_min': 45.0},
{'angle_crop_max': 280.0},
```

这表示只保留 45 到 280 度之间的扫描数据，范围外置为 NaN。

近距从 20cm 改成 5cm：

```python
{'range_min': 0.05}
```

AMCL 也同步改成：

```yaml
laser_min_range: 0.05
```

### 为什么这样改

原来的 20cm 会丢弃较近的有效激光点。对小车来说，近处障碍和墙边信息很重要，尤其是贴墙、窄通道、终点附近微调时。改成 5cm 后，雷达驱动和 AMCL 对近距离数据的认识一致，避免驱动发布了数据但定位层又忽略掉。

同时，`navigation_backup.launch.py` 中旧的 `range_min: 0.2` 也改成了 0.05，避免以后误用备份 launch 时表现不一致。

## 进度检查器变化

基准版本：

```yaml
required_movement_radius: 0.5
movement_time_allowance: 10.0
failure_tolerance: 0.3
```

当前版本：

```yaml
required_movement_radius: 0.05
movement_time_allowance: 25.0
failure_tolerance: 0.5
```

### 为什么这样改

原来的进度检查要求 10 秒内至少移动 0.5m。对小车在窄空间、终点附近、低速贴路径调整时，这个要求偏激进，容易误判卡住。

当前改成 25 秒内移动 0.05m，更宽松。这样 Nav2 不会在微调、慢速避障或终点附近频繁判定失败。

代价是：真正卡住时，系统发现失败会更慢。因此后续如果需要更强的故障检测，可以再收紧到例如：

```yaml
required_movement_radius: 0.10
movement_time_allowance: 15.0
```

## 当前版本的取舍

当前版本更偏向：

1. 严格跟随全局路径。
2. 不倒车。
3. 移动过程尽量连续。
4. 保持接近旧版本的速度上限。
5. 降低局部规划器自由绕大弯的概率。

当前版本相对弱一点的是：

1. 终点 yaw 精准对齐能力可能弱，因为 `use_rotate_to_heading` 关闭。
2. 遇到动态障碍物时，RPP 不像 DWB 那样主动采样复杂绕行轨迹。
3. 进度检查更宽松，真实卡死的报警会慢一些。

## 后续建议

如果“终点附近不愿意原地转向”影响使用，优先做小步实验：

方案 A：放宽终点角度要求，适合不关心最终朝向的任务。

```yaml
yaw_goal_tolerance: 0.35
```

方案 B：重新启用终点旋转，适合必须对准姿态的任务。

```yaml
use_rotate_to_heading: true
rotate_to_heading_angular_vel: 1.0
rotate_to_heading_min_angle: 0.5
```

方案 C：如果启用旋转后又变卡顿，可以保留 `use_rotate_to_heading: false`，在上层任务里把目标点前方留出距离，让全局路径本身带出最终朝向。

实车定位慢/快问题时，建议同时看：

```bash
ros2 topic echo /cmd_vel_nav
ros2 topic echo /cmd_vel
```

如果 `/cmd_vel_nav` 已经很小，是控制器在降速；如果 `/cmd_vel_nav` 正常而 `/cmd_vel` 小，是速度平滑器限速；如果 `/cmd_vel` 正常而车慢，是底盘或下位机限速。
