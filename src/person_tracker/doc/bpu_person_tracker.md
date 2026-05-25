# BPU-ready Person Tracker

`person_tracker_bpu_node.py` is the lightweight vision backend for the first
optimization phase. It keeps the existing ROS interface:

```text
/person_position   geometry_msgs/msg/PointStamped
/person_distance   std_msgs/msg/Float32
/fall_detected     std_msgs/msg/Bool
```

The node subscribes to:

```text
/ascamera_hp60c/camera_publisher/rgb0/image
/ascamera_hp60c/camera_publisher/depth0/image_raw
```

## Launch

Old MediaPipe fallback:

```bash
ros2 launch task_manager robot_server.launch.py vision_backend:=mediapipe
```

Mock detector for ROS link and depth localization testing:

```bash
ros2 launch task_manager robot_server.launch.py vision_backend:=mock
```

BPU YOLO detector on RDK X5:

```bash
ros2 launch task_manager robot_server.launch.py \
  vision_backend:=bpu_yolo \
  bpu_yolo_model_path:=/path/to/yolov8_person.bin
```

`bpu_yolo` imports `hobot_dnn.pyeasy_dnn`, loads a D-Robotics converted `.bin`
model, runs BPU inference, and decodes common YOLOv8-style outputs. If your
model has a different output head layout, keep ROS logic unchanged and adjust
only `BpuYoloPersonDetector`.

## Depth Localization

The selected person is the largest person bbox. Depth is sampled by median
filtering around the bbox center, then around lower-body fallback points. Invalid
depths are filtered:

```text
depth_scale: 0.001
depth_window_size: 11
min_depth_m: 0.3
max_depth_m: 5.0
```

The pixel/depth projection first computes optical-frame coordinates:

```text
x right, y down, z forward
```

and publishes `camera_link` body-frame coordinates:

```text
body_x = optical_z
body_y = -optical_x
body_z = -optical_y
```

## Test Commands

Build and source:

```bash
cd /home/pan/Intelligent_robot
colcon build --packages-select person_tracker task_manager
source install/setup.bash
```

Mock backend validation without BPU:

```bash
ros2 launch task_manager robot_server.launch.py vision_backend:=mock
```

In another terminal:

```bash
source /home/pan/Intelligent_robot/install/setup.bash
ros2 topic hz /person_position
ros2 topic echo /person_distance
ros2 topic echo /fall_detected
```

RDK X5 BPU backend validation with a real D-Robotics `.bin` model:

```bash
ros2 launch task_manager robot_server.launch.py \
  vision_backend:=bpu_yolo \
  bpu_yolo_model_path:=/path/to/yolov8_person.bin
```

RDK X5 BPU observation:

```bash
hrut_bpuprofile -b 0
cat /sys/devices/system/bpu/bpu0/ratio
```

Quick failure checks on RDK X5:

```bash
python3 -c "from hobot_dnn import pyeasy_dnn; print('hobot_dnn ok')"
ls -l /path/to/yolov8_person.bin
ros2 topic hz /ascamera_hp60c/camera_publisher/rgb0/image
ros2 topic hz /ascamera_hp60c/camera_publisher/depth0/image_raw
```

## Next BPU Integration Point

Keep ROS publish/subscription logic in `PersonTrackerBpuNode`. If a different
D-Robotics Model Zoo sample uses another output tensor layout, change only:

```text
BpuYoloPersonDetector.detect(image) -> list[PersonDetection]
```

Required launch parameter:

```text
bpu_yolo_model_path: path to a D-Robotics converted YOLO .bin model
```
