# RPP Goal Rotation Branch

分支：

```text
tune/rpp-goal-rotation
```

基于当前 `main`，继续使用 `nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController`。

## 目标

当前 RPP 方案已经明显改善了沿全局路径跟踪的问题，但还有一个现象：出发或到达目标点附近时，小车不够愿意原地旋转调整位姿，有时会尝试走一个小弧线或绕一段路来满足姿态。

这个分支的目标是：保留 RPP 的贴路径优势，同时让终点附近更容易进入原地旋转调整。

## 修改内容

当前 main 已经有：

```yaml
use_rotate_to_heading: true
rotate_to_heading_angular_vel: 1.0
rotate_to_heading_min_angle: 0.5
max_angular_accel: 2.0
xy_goal_tolerance: 0.20
yaw_goal_tolerance: 0.20
```

本分支改为：

```yaml
use_rotate_to_heading: true
rotate_to_heading_angular_vel: 1.0
rotate_to_heading_min_angle: 0.20
max_angular_accel: 3.2
xy_goal_tolerance: 0.20
yaw_goal_tolerance: 0.20
```

## 参数含义

`use_rotate_to_heading`

允许控制器在需要调整朝向时进行旋转行为。关闭时，小车更倾向连续沿路径追踪，终点 yaw 精调能力较弱。

`rotate_to_heading_min_angle`

触发旋转行为的角度阈值。原来是 `0.5rad`，约 28.6 度。这个阈值偏大，只有朝向误差很明显时才触发旋转。本分支改成 `0.20rad`，约 11.5 度，让小车更早进入旋转调整。

`max_angular_accel`

角加速度限制。原来 `2.0` 偏保守，旋转响应慢。本分支恢复到 `3.2`，接近旧 DWB 配置里的角加速度水平。

`xy_goal_tolerance` / `yaw_goal_tolerance`

位置和朝向到达容忍范围。当前维持 `0.20m` 和 `0.20rad`，没有继续收得太紧。原因是 LD06、odom 和 AMCL 都有误差，容忍范围过小可能导致终点附近反复调整。

## 为什么可能改善

RPP 的核心行为是追踪全局路径上的前视点。它天然更适合“沿线走”，不是特别擅长在终点附近做复杂的姿态规划。

把 `rotate_to_heading_min_angle` 从 `0.5` 降到 `0.20` 后，小车不用等到朝向偏差很大才旋转；把 `max_angular_accel` 提高后，旋转动作不会显得拖泥带水。

这个分支的预期表现是：

1. 行进时仍然贴全局路径。
2. 终点附近更容易原地转向。
3. 比 main 更愿意修正 yaw，但可能比 main 稍微多一点停顿感。

## 风险

如果路径中间局部朝向变化较大，阈值降低后可能在路径中段也更容易触发旋转，表现为短暂停顿。

如果实车出现这种情况，可以把阈值回调到：

```yaml
rotate_to_heading_min_angle: 0.30
```

或者保留 `0.20`，但把 `yaw_goal_tolerance` 放宽到：

```yaml
yaw_goal_tolerance: 0.25
```

## 实车验证建议

观察两个话题：

```bash
ros2 topic echo /cmd_vel_nav
ros2 topic echo /cmd_vel
```

终点附近如果 `/cmd_vel_nav.angular.z` 明显输出，而 `/cmd_vel.angular.z` 也跟随输出，说明控制器已经在尝试旋转。如果 `/cmd_vel_nav.angular.z` 不输出，说明 RPP 仍未触发旋转逻辑。
