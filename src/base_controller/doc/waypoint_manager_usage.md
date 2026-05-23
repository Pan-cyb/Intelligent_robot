# waypoint_manager 命名点标定使用说明

本文档说明如何用 RViz 的 `2D Goal Pose` 在地图上点选位置和朝向，并保存为 `bedroom_bedside`、`living_room_sofa`、`charger_front`、`medicine_box_front` 等命名导航点。

`waypoint_manager` 只负责标定、保存和读取命名点，不会直接控制底盘，也不会向 Nav2 发送导航目标。

## 功能概览

节点：

```bash
waypoint_manager
```

订阅话题：

```text
/waypoint_goal
geometry_msgs/msg/PoseStamped
```

服务：

```text
/waypoint_manager/save_last_goal
base_controller/srv/SavePose

/waypoint_manager/get_pose
base_controller/srv/GetPose

/waypoint_manager/list_poses
base_controller/srv/ListPoses

/waypoint_manager/delete_pose
base_controller/srv/DeletePose
```

默认保存文件：

```text
/home/pan/Intelligent_robot/src/base_controller/maps/named_poses.yaml
```

可以通过节点参数 `poses_file` 指定保存位置。

## 推荐命名方式

命名点应该表示机器人真正能停靠的位置，而不是房间语义中心。

推荐：

```text
bedroom_bedside
bedroom_door
living_room_sofa
charger_front
medicine_box_front
```

不推荐：

```text
bedroom
living_room
medicine_box
```

原因是房间中心点、柜子中心点可能不是机器人能安全停靠的位置。更好的方式是保存机器人实际应该到达的位置和朝向。

## 编译

在工作空间根目录执行：

```bash
cd /home/pan/Intelligent_robot
colcon build --packages-select base_controller
source install/setup.bash
```

如果当前终端还没有加载 ROS 2 环境，先执行：

```bash
source /opt/ros/humble/setup.bash
```

## 一键启动标定模式

推荐使用专门的标定启动文件：

```bash
cd /home/pan/Intelligent_robot
source install/setup.bash
ros2 launch base_controller waypoint_calibration.launch.py
```

这个启动文件只启动：

```text
map_server
lifecycle_manager
rviz2
waypoint_manager
```

不会启动：

```text
base_controller_node
雷达驱动
AMCL
planner_server
controller_server
bt_navigator
velocity_smoother
```

因此它不会控制底盘，也不会触发 Nav2 导航，适合单独做命名点标定。

当前 `waypoint_calibration.launch.py` 默认使用 `base_controller` 包内地图和 RViz 配置：

```text
maps/my_map1.yaml
rviz/waypoint_calibration.rviz
```

命名点 YAML 默认保存到源码目录：

```text
/home/pan/Intelligent_robot/src/base_controller/maps/named_poses.yaml
```

这样不会只写到 `install/` 构建产物里，后续 clean build 或迁移项目时不容易丢。

专用 RViz 配置已经把 `2D Goal Pose` 的输出话题设置为：

```text
/waypoint_goal
```

所以一键启动后，可以直接在 RViz 中用 `2D Goal Pose` 点选位置和朝向。

如果要指定其他地图：

```bash
ros2 launch base_controller waypoint_calibration.launch.py \
  map:=/home/pan/Intelligent_robot/src/base_controller/maps/my_map1.yaml
```

如果要指定命名点 YAML 保存路径：

```bash
ros2 launch base_controller waypoint_calibration.launch.py \
  poses_file:=/home/pan/Intelligent_robot/src/base_controller/maps/named_poses.yaml
```

## 单独启动 waypoint_manager

`waypoint_manager` 节点本身不依赖导航节点，也不依赖 Nav2。它只需要有人向 `/waypoint_goal` 发布 `geometry_msgs/msg/PoseStamped`，并且 `frame_id` 是 `map`。

如果不需要一键标定环境，也可以只启动节点：


```bash
cd /home/pan/Intelligent_robot
source install/setup.bash
ros2 run base_controller waypoint_manager
```

如果想指定 YAML 保存路径，例如保存到源码目录：

```bash
ros2 run base_controller waypoint_manager --ros-args \
  -p poses_file:=/home/pan/Intelligent_robot/src/base_controller/maps/named_poses.yaml
```

也可以指定点选话题和地图坐标系：

```bash
ros2 run base_controller waypoint_manager --ros-args \
  -p goal_topic:=/waypoint_goal \
  -p map_frame:=map
```

手动发布一个测试点：

```bash
ros2 topic pub --once /waypoint_goal geometry_msgs/msg/PoseStamped "{
  header: {frame_id: 'map'},
  pose: {
    position: {x: 1.0, y: 2.0, z: 0.0},
    orientation: {x: 0.0, y: 0.0, z: 0.0, w: 1.0}
  }
}"
```

## RViz 点选方式

1. 打开 RViz。
2. 找到工具栏中的 `2D Goal Pose`。
3. 如果使用 `waypoint_calibration.launch.py`，话题已经默认是 `/waypoint_goal`。
4. 如果使用其他 RViz 配置，不要让它发布到 Nav2 默认的 `/goal_pose`，需要手动改成：

```text
/waypoint_goal
```

5. 在地图上点击目标位置，拖动鼠标确定机器人到达后的朝向。
6. `waypoint_manager` 收到位姿后会打印日志。

注意：用于标定时，`2D Goal Pose` 必须发到 `/waypoint_goal`，不要发到 Nav2 的 `/goal_pose`，避免机器人误启动导航。

## 保存最近一次点选

点选完成后，调用服务保存最近一次收到的位姿：

```bash
ros2 service call /waypoint_manager/save_last_goal base_controller/srv/SavePose "{name: 'bedroom_bedside'}"
```

再保存客厅沙发点：

```bash
ros2 service call /waypoint_manager/save_last_goal base_controller/srv/SavePose "{name: 'living_room_sofa'}"
```

再保存充电桩前方点：

```bash
ros2 service call /waypoint_manager/save_last_goal base_controller/srv/SavePose "{name: 'charger_front'}"
```

如果同名点已经存在，会覆盖原来的点，并在日志中提示。

命名只能使用字母、数字和下划线，例如：

```text
bedroom_bedside
living_room_sofa
charger_front
medicine_box_front
```

## 查看已有命名点

```bash
ros2 service call /waypoint_manager/list_poses base_controller/srv/ListPoses "{}"
```

返回示例：

```text
names:
- bedroom_bedside
- charger_front
- living_room_sofa
```

## 读取指定命名点

```bash
ros2 service call /waypoint_manager/get_pose base_controller/srv/GetPose "{name: 'bedroom_bedside'}"
```

返回中会包含：

```text
success
message
pose
```

其中 `pose` 是 `geometry_msgs/msg/PoseStamped`，后续 `task_manager` 可以直接把它转发给 Nav2 的 `NavigateToPose` action。

## 删除命名点

```bash
ros2 service call /waypoint_manager/delete_pose base_controller/srv/DeletePose "{name: 'bedroom_bedside'}"
```

删除后会重新写入 YAML 文件。

## YAML 文件格式

保存后的 YAML 类似：

```yaml
bedroom_bedside:
  frame_id: map
  position:
    x: 2.31
    y: -1.42
    z: 0.0
  orientation:
    x: 0.0
    y: 0.0
    z: 0.707
    w: 0.707

living_room_sofa:
  frame_id: map
  position:
    x: 0.45
    y: 1.8
    z: 0.0
  orientation:
    x: 0.0
    y: 0.0
    z: 0.0
    w: 1.0
```

当前版本保存四元数，不单独保存 yaw。`waypoint_manager/get_pose` 会直接返回 `PoseStamped`，可以直接用于 Nav2。

如果后续代码需要 yaw，也可以由四元数转换得到：

```text
yaw = atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
```

当前 `task_manager` 已兼容两种格式：

```yaml
locations:
  bedroom:
    frame_id: map
    x: 1.0
    y: 2.0
    yaw: 0.0
```

以及 waypoint 标定生成的格式：

```yaml
locations:
  bedroom_bedside:
    frame_id: map
    position:
      x: 2.31
      y: -1.42
      z: 0.0
    orientation:
      x: 0.0
      y: 0.0
      z: 0.707
      w: 0.707
```

## 坐标系要求

当前版本只接受 `map` 坐标系。

如果收到的 `PoseStamped.header.frame_id` 不是 `map`，`waypoint_manager` 会拒绝保存并打印错误日志。

这样做是为了避免误保存 `base_link`、`odom` 等坐标系下的点。导航目标点必须是地图坐标系下的固定位置。

## 典型标定流程

1. 启动一键标定模式：

```bash
ros2 launch base_controller waypoint_calibration.launch.py
```

2. 在 RViz 中使用 `2D Goal Pose` 点击并拖动，选择目标位置和朝向。
3. 保存命名点：

```bash
ros2 service call /waypoint_manager/save_last_goal base_controller/srv/SavePose "{name: 'bedroom_bedside'}"
```

4. 查看已保存点：

```bash
ros2 service call /waypoint_manager/list_poses base_controller/srv/ListPoses "{}"
```

5. 读取指定点：

```bash
ros2 service call /waypoint_manager/get_pose base_controller/srv/GetPose "{name: 'bedroom_bedside'}"
```

## 给 task_manager 的后续接入方式

后续 `task_manager` 不需要自己解析 RViz 点选，也不需要读取 `base_link` 坐标。

推荐流程：

1. 用户说“去卧室床边”。
2. `task_manager` 把语义名称映射成 `bedroom_bedside`。
3. 调用：

```text
/waypoint_manager/get_pose
```

4. 拿到 `PoseStamped`。
5. 发送给 Nav2 `NavigateToPose` action。

这样语义任务和地图坐标可以解耦，后续重标定某个点时只需要重新保存 YAML，不需要改任务代码。

## 常见问题

如果保存时提示“还没有收到 /waypoint_goal”，说明还没有在 RViz 中点选，或者 RViz 的 `2D Goal Pose` 没有改到 `/waypoint_goal`。

如果日志提示 `frame_id` 不是 `map`，说明 RViz 或上游发布的位姿坐标系不符合要求。当前版本不会做 TF 转换，后续可以再扩展。

如果 YAML 写入失败，检查 `poses_file` 所在目录是否存在、当前用户是否有写权限。

如果调用服务时提示服务类型不存在，重新编译并 source：

```bash
colcon build --packages-select base_controller
source install/setup.bash
```
