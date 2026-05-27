# BPU 人体跟踪后端说明

`person_tracker_bpu_node.py` 是视觉优化阶段新增的轻量人体检测后端。它用于在 RDK X5 上接入 BPU YOLO 人体检测，同时保持现有 ROS 接口不变。

节点继续发布：

```text
/person_position   geometry_msgs/msg/PointStamped
/person_distance   std_msgs/msg/Float32
/fall_detected     std_msgs/msg/Bool
```

节点订阅相机话题：

```text
/ascamera_hp60c/camera_publisher/rgb0/image
/ascamera_hp60c/camera_publisher/depth0/image_raw
```

## 后端选择

旧版 MediaPipe 后端，作为稳定 fallback：

```bash
ros2 launch task_manager robot_server.launch.py vision_backend:=mediapipe
```

Mock 后端，用于没有 BPU 模型时验证 ROS 链路和深度定位流程：

```bash
ros2 launch task_manager robot_server.launch.py vision_backend:=mock
```

RDK X5 上使用 BPU YOLO 后端：

```bash
ros2 launch task_manager robot_server.launch.py \
  vision_backend:=bpu_yolo \
  bpu_yolo_model_path:=/path/to/yolov8_person.bin
```

`bpu_yolo` 会导入 `hobot_dnn.pyeasy_dnn`，加载 D-Robotics 转换后的 `.bin` 模型，在 BPU 上推理，并按常见 YOLOv8 输出格式做后处理。

如果你使用的模型输出 head 和当前实现不同，不要改 ROS 订阅、发布和跟随链路，只需要调整：

```text
BpuYoloPersonDetector.detect(image) -> list[PersonDetection]
```

## 深度定位

当前策略：

```text
1. 从检测结果中选择面积最大的人体 bbox
2. 优先在 bbox 中心附近取深度中位数
3. 如果中心深度无效，再尝试下半身附近的 fallback 点
4. 过滤过近、过远和无效深度
```

相关参数：

```text
depth_scale: 0.001
depth_window_size: 11
min_depth_m: 0.3
max_depth_m: 5.0
```

像素和深度反投影后，先得到 optical frame 坐标：

```text
x 右
y 下
z 前
```

发布到 `camera_link` 前会转换为 ROS body frame：

```text
body_x = optical_z
body_y = -optical_x
body_z = -optical_y
```

这和项目长期约定保持一致，避免人物在相机前方时被错误转成侧方目标。

## 构建

```bash
cd /home/pan/Intelligent_robot
colcon build --packages-select person_tracker task_manager
source install/setup.bash
```

如果实机路径是 `/home/sunrise/Myproj`，请在实机工作区执行：

```bash
cd /home/sunrise/Myproj
colcon build --packages-select person_tracker task_manager
source install/setup.bash
```

## Mock 后端验证

启动：

```bash
ros2 launch task_manager robot_server.launch.py vision_backend:=mock
```

另开终端检查输出：

```bash
source /home/pan/Intelligent_robot/install/setup.bash
ros2 topic hz /person_position
ros2 topic echo /person_distance
ros2 topic echo /fall_detected
```

实机工作区对应改为：

```bash
source /home/sunrise/Myproj/install/setup.bash
```

## BPU 后端验证

在 RDK X5 上准备好真实 D-Robotics `.bin` 模型后启动：

```bash
ros2 launch task_manager robot_server.launch.py \
  vision_backend:=bpu_yolo \
  bpu_yolo_model_path:=/path/to/yolov8_person.bin
```

观察 BPU 占用：

```bash
hrut_bpuprofile -b 0
cat /sys/devices/system/bpu/bpu0/ratio
```

快速排查命令：

```bash
python3 -c "from hobot_dnn import pyeasy_dnn; print('hobot_dnn ok')"
ls -l /path/to/yolov8_person.bin
ros2 topic hz /ascamera_hp60c/camera_publisher/rgb0/image
ros2 topic hz /ascamera_hp60c/camera_publisher/depth0/image_raw
```

## 必要参数

```text
bpu_yolo_model_path
```

含义：

```text
D-Robotics 转换后的 YOLO .bin 模型路径。
```

如果没有传入该参数，`bpu_yolo` 后端无法加载真实模型。

## 当前限制

当前 BPU 后端是在非最终 RDK X5 实机环境中先完成的代码结构，开发环境没有真实 BPU 模型和 `hobot_dnn` 运行库。因此：

```text
1. mock 后端可用于验证 ROS topic 链路
2. bpu_yolo 后端必须在 RDK X5 上用真实 .bin 模型验收
3. 如果模型输出格式不同，优先只调整 BpuYoloPersonDetector
4. 不要因为模型输出不匹配去改 task_manager 或 follower_controller
```
