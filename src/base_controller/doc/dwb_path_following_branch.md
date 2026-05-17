# DWB Path Following Branch

分支：

```text
tune/dwb-path-following
```

本分支基于当前 `main`，把局部控制器从 Regulated Pure Pursuit 切回 DWB，并按“尽量贴全局路径，不要局部乱绕”的目标重新调参。

## 背景

旧仓库里的 DWB 版本大约能满足 70% 的导航需求，但存在一个严重风险：局部规划器偶尔会向左绕一个大弯，甚至一直贴墙或撞墙。

DWB 的优点是：

1. 支持原地旋转和终点姿态调整。
2. 对 Nav2 默认导航流程兼容成熟。
3. 可以通过 critic 权重调出“贴全局路径”的行为。

DWB 的风险是：

1. 它会采样多条局部速度轨迹。
2. 如果 critic 权重不合适，它可能选择一条局部看似得分不错、但整体偏离全局路径的轨迹。
3. 在墙边或障碍膨胀区，GoalDist/GoalAlign 权重过高时可能出现抄近路、绕弯贴墙。

## 修改内容

当前 main 使用 RPP：

```yaml
plugin: "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController"
```

本分支改回 DWB：

```yaml
plugin: "dwb_core::DWBLocalPlanner"
```

同时保留 main 中已经验证较好的部分：

1. `velocity_smoother` 速度平滑链路。
2. `xy_goal_tolerance: 0.20` 和 `yaw_goal_tolerance: 0.20`。
3. 雷达近距 5cm。
4. 局部代价地图 4m x 4m。
5. 局部 `ObstacleLayer + InflationLayer`。

## 当前 DWB 参数

```yaml
FollowPath:
  plugin: "dwb_core::DWBLocalPlanner"
  min_vel_x: 0.0
  max_vel_x: 0.26
  max_vel_theta: 1.0
  vx_samples: 12
  vy_samples: 1
  vtheta_samples: 20
  sim_time: 0.8
  critics: ["RotateToGoal", "Oscillation", "BaseObstacle", "PathAlign", "PathDist", "GoalAlign", "GoalDist"]
  BaseObstacle.scale: 0.04
  PathAlign.scale: 24.0
  PathAlign.forward_point_distance: 0.20
  PathDist.scale: 28.0
  GoalAlign.scale: 14.0
  GoalAlign.forward_point_distance: 0.20
  GoalDist.scale: 14.0
  RotateToGoal.scale: 32.0
```

## 参数含义和调参思路

`min_vel_x: 0.0`

禁止倒车。旧版本中有过负速度尝试时，局部规划器容易出现奇怪的倒退调整。本分支坚持不倒车。

`max_vel_x: 0.26`

保留旧版本最大线速度，避免切回 DWB 后速度明显下降。

`max_vel_theta: 1.0`

允许足够的角速度做原地旋转和终点姿态调整。

`vx_samples: 12`

线速度采样数。实测 24 个采样在机器人上容易导致 `Control loop missed its desired rate`，因此降到 12，优先保证控制循环稳定。

`vtheta_samples: 20`

角速度采样数。保持旧版本 20，减少 DWB 计算量。

`vy_samples: 1`

差速小车不需要横向速度采样。

`sim_time: 0.8`

旧版本是 1.7。预测时间太长时，DWB 会看到更远的局部轨迹，可能为了目标点选择更大弯。本分支缩短到 0.8，让局部规划更关注眼前路径跟踪，同时降低计算量。

`PathAlign.scale: 24.0`

提高对齐全局路径的权重。这个 critic 鼓励机器人朝全局路径方向走。

`PathDist.scale: 28.0`

提高距离全局路径的惩罚。这个值高，局部轨迹偏离全局路径会更吃亏。

`GoalAlign.scale: 14.0`

降低朝目标方向抄近路的冲动。旧版本是 24.0，本分支减半。

`GoalDist.scale: 14.0`

降低单纯追目标点距离的权重。旧版本是 24.0，本分支明显降低，避免为了离目标更近而偏离全局路径。

`BaseObstacle.scale: 0.04`

提高避障代价。旧版本是 0.02，当前更重视离墙和障碍物远一点，但不再设到 0.08，避免在窄通道中过度保守。

## 日志反馈后的修正

实车日志中出现大量：

```text
Control loop missed its desired rate of 20.0000Hz
Failed to make progress
```

这说明第一版 DWB 分支计算负载过高，控制器在 20Hz 下跑不稳，后续行为树开始清 costmap、spin、backup，表现为卡住。

因此本分支后续把：

```yaml
controller_frequency: 10.0
vx_samples: 12
vtheta_samples: 20
sim_time: 0.8
```

先保证控制循环能按频率跑起来。DWB 调参时，控制循环稳定比采样精细更重要。

同一轮日志还显示雷达角度裁剪本身是生效的：

```text
crop=true min=45.0 max=280.0
```

但驱动原来只把 `range_min/range_max` 写进 LaserScan 元数据，并没有真正过滤小于 `range_min` 或大于 `range_max` 的点。因此 RViz 或 costmap 中仍可能看到靠近坐标轴的短小噪声点。本分支在 `ldlidar_ros2/src/demo.cpp` 中补充了实际范围过滤，超出 `[range_min, range_max]` 的点会被置为 NaN。

第三轮实车日志确认 RViz 中 `/scan` 仍能看到靠近坐标系的小短线，说明 0.05 m 对当前安装和 LD06 近距离噪声仍偏低。因此本分支把雷达发布端、AMCL 和 costmap 障碍层的最小有效距离统一提高到 0.12 m：

```yaml
ld06.range_min: 0.12
amcl.laser_min_range: 0.12
local_costmap.obstacle_layer.scan.obstacle_min_range: 0.12
global_costmap.obstacle_layer.scan.obstacle_min_range: 0.12
```

`raytrace_min_range` 暂时保留 0.0，避免额外收窄清障范围；真正小于 0.12 m 的 scan 点会在雷达发布端被置为 NaN。

## 窄通道失败后的修正

第二轮实车日志中，控制循环已经基本稳定，但小车在狭窄路径中过不去，最终：

```text
Failed to make progress
```

这更像局部代价地图和 DWB 权重过保守，而不是 CPU 跑不动。

当局部膨胀半径较大、PathDist/PathAlign 权重也较高时，DWB 会同时受到两类约束：

1. 不愿靠墙，因为障碍膨胀区代价高。
2. 不愿离开全局路径，因为 PathDist/PathAlign 惩罚高。

在窄通道里，这两者叠加就会让可行轨迹很少，表现为停住、反复重规划，最后进度检查失败。

因此本分支进一步调整为：

```yaml
local_costmap.inflation_layer.inflation_radius: 0.25
local_costmap.inflation_layer.cost_scaling_factor: 5.0
global_costmap.inflation_layer.inflation_radius: 0.35
global_costmap.inflation_layer.cost_scaling_factor: 2.5
PathAlign.scale: 24.0
PathDist.scale: 28.0
GoalAlign.scale: 14.0
GoalDist.scale: 14.0
BaseObstacle.scale: 0.04
```

这个调整的意图是：保留贴全局路径倾向，但不要把局部规划器锁死在全局路径线上；同时缩小膨胀半径，让窄路中仍有可行空间。

第三轮日志中仍然出现狭窄路径附近 `Failed to make progress`，但同时有两类信号需要分开看：

1. `STM communicate lost...` 多次出现，这会直接影响 `/odom` 更新和 Nav2 的进度判断。即使局部规划器继续发速度，进度检查器也可能认为机器人没有移动。
2. `Planner loop missed its desired rate of 20.0000 Hz` 偶发出现，说明 20 Hz 的 planner 期望频率对当前板子偏激进。本分支把 `expected_planner_frequency` 降到 5 Hz，减少行为树因为规划器超时而进入清图/恢复的概率。

这次没有继续缩小膨胀半径。当前 local inflation 已经是 0.25 m，结合 footprint 半宽约 0.12 m，再继续缩小会更容易贴墙，可能把真实碰撞风险转移给局部控制器。若 0.12 m 雷达过滤后窄通道仍失败，下一步应优先确认 `/odom` 是否连续，再决定是否把 local inflation 试探性降到 0.20 m。

第四轮日志确认近距离雷达触手已经消失，但原目标仍会在狭窄段 `Failed to make progress`，而换目标点可成功。这说明主要问题不是雷达近场噪声，而是 DWB 的局部轨迹评分仍可能选择偏离全局路径的局部最优。DWB 没有“硬跟踪全局路径”的开关，只能通过 critic 权重逼近这个行为，因此本分支进一步进入强路径跟随模式：

```yaml
PathAlign.scale: 48.0
PathAlign.forward_point_distance: 0.10
PathDist.scale: 72.0
GoalAlign.scale: 6.0
GoalAlign.forward_point_distance: 0.10
GoalDist.scale: 6.0
```

这个配置会明显提高偏离全局路径的代价，并降低直接朝目标点抄近路的诱惑。副作用是局部避障会更保守，如果全局路径本身贴墙或穿过窄门中心线不准，DWB 更容易停住而不是主动绕开。

如果全局路径在 RViz 中确认正常、居中且连续，但 DWB 仍在窄段卡住，那么更可能是局部代价地图把通道算得过窄，或者障碍物 critic 对膨胀区过敏。因此本分支进一步只放松 local costmap，不动 global costmap：

```yaml
local_costmap.inflation_layer.inflation_radius: 0.20
local_costmap.inflation_layer.cost_scaling_factor: 8.0
BaseObstacle.scale: 0.02
```

这里 `inflation_radius` 变小让局部可行空间增加，`cost_scaling_factor` 变大让膨胀代价更快衰减，`BaseObstacle.scale` 降低让 DWB 不会因为贴近膨胀区就完全放弃前进。风险是小车会更敢靠近墙面，所以实测时需要重点看局部 costmap 和实体距离。

`RotateToGoal.scale: 32.0`

保留较强终点旋转能力。DWB 在终点附近通常比 RPP 更自然地做原地转向，这也是本分支需要验证的点。

## 为什么可能改善

之前 DWB 容易乱绕，核心不是 DWB 不能用，而是 critic 权重让它在“贴全局路径”和“追目标点”之间过度偏向后者。

本分支做了三个动作：

1. 提高 `PathAlign` 和 `PathDist`，让局部轨迹必须更贴全局路径。
2. 降低 `GoalAlign` 和 `GoalDist`，减少抄近路和绕大弯冲动。
3. 缩短 `sim_time`，减少长预测轨迹带来的大弯选择。

因此预期行为是：DWB 仍然可以原地转向，但不会为了局部最优主动偏离全局路径太远。

## 风险

如果 PathDist/PathAlign 太高，小车可能在局部障碍物前不愿意绕开，表现为保守或停顿。

如果 GoalDist 太低，靠近终点时可能走得不够积极。

如果 BaseObstacle 太高，在窄通道里可能离墙过于谨慎，速度下降。

## 后续实验建议

如果仍然绕大弯：

```yaml
PathDist.scale: 56.0
GoalDist.scale: 6.0
sim_time: 0.8
```

如果太保守、不愿绕过小障碍：

```yaml
PathDist.scale: 32.0
GoalDist.scale: 16.0
BaseObstacle.scale: 0.05
```

如果终点旋转抖动：

```yaml
RotateToGoal.scale: 24.0
RotateToGoal.slowing_factor: 8.0
```

实车验证时建议同时观察：

```bash
ros2 topic echo /cmd_vel_nav
ros2 topic echo /cmd_vel
```

以及 RViz 中的 global path、local costmap 和 local trajectory。
