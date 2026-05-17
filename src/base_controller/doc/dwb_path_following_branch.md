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
  vx_samples: 24
  vy_samples: 1
  vtheta_samples: 32
  sim_time: 1.0
  critics: ["RotateToGoal", "Oscillation", "BaseObstacle", "PathAlign", "PathDist", "GoalAlign", "GoalDist"]
  BaseObstacle.scale: 0.08
  PathAlign.scale: 40.0
  PathAlign.forward_point_distance: 0.20
  PathDist.scale: 44.0
  GoalAlign.scale: 12.0
  GoalAlign.forward_point_distance: 0.20
  GoalDist.scale: 10.0
  RotateToGoal.scale: 32.0
```

## 参数含义和调参思路

`min_vel_x: 0.0`

禁止倒车。旧版本中有过负速度尝试时，局部规划器容易出现奇怪的倒退调整。本分支坚持不倒车。

`max_vel_x: 0.26`

保留旧版本最大线速度，避免切回 DWB 后速度明显下降。

`max_vel_theta: 1.0`

允许足够的角速度做原地旋转和终点姿态调整。

`vx_samples: 24`

线速度采样数。比旧版本 20 略多，让速度选择更细。

`vtheta_samples: 32`

角速度采样数。比旧版本 20 更多，让旋转和转弯控制更细。

`vy_samples: 1`

差速小车不需要横向速度采样。

`sim_time: 1.0`

旧版本是 1.7。预测时间太长时，DWB 会看到更远的局部轨迹，可能为了目标点选择更大弯。本分支缩短到 1.0，让局部规划更关注眼前路径跟踪。

`PathAlign.scale: 40.0`

提高对齐全局路径的权重。这个 critic 鼓励机器人朝全局路径方向走。

`PathDist.scale: 44.0`

提高距离全局路径的惩罚。这个值高，局部轨迹偏离全局路径会更吃亏。

`GoalAlign.scale: 12.0`

降低朝目标方向抄近路的冲动。旧版本是 24.0，本分支减半。

`GoalDist.scale: 10.0`

降低单纯追目标点距离的权重。旧版本是 24.0，本分支明显降低，避免为了离目标更近而偏离全局路径。

`BaseObstacle.scale: 0.08`

提高避障代价。旧版本是 0.02，当前更重视离墙和障碍物远一点。

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
