# RDK X5 YOLOPose BPU 部署记录

本文档记录从 D-Robotics `rdk_model_zoo` 准备 YOLOPose `.bin`，到后续接入本项目 `person_tracker` 的步骤。

## 当前结论

- 推荐先用官方默认模型：`yolo11n_pose_bayese_640x640_nv12.bin`
- 如果必须用 YOLOv8，可以用：`yolov8n_pose_bayese_640x640_nv12.bin`
- 官方模型目录：
  `https://archive.d-robotics.cc/downloads/rdk_model_zoo/rdk_x5/ultralytics_YOLO/`
- 官方样例目录：
  `samples/vision/ultralytics_yolo`
- YOLOPose 是姿态估计模型，不是普通检测模型。它输出 bbox 和 17 个 COCO keypoints。
- 本项目现有 `person_tracker_bpu_node.py` 当前只按普通 YOLO 检测模型解码，不能直接解 YOLOPose `.bin`。

## 第一阶段：在 RDK X5 上跑通官方 YOLOPose

在 RDK X5 板端执行：

```bash
cd ~
git clone -b rdk_x5 https://github.com/D-Robotics/rdk_model_zoo.git
cd rdk_model_zoo/samples/vision/ultralytics_yolo/runtime/python
```

安装依赖：

```bash
pip install numpy opencv-python hbm-runtime scipy
```

下载并运行官方默认 pose 模型：

```bash
chmod +x run.sh
./run.sh pose \
  --model-path ../../model/yolo11n_pose_bayese_640x640_nv12.bin \
  --test-img ../../test_data/pose-estimation-examples.jpg \
  --img-save-path ../../test_data/result_pose.jpg
```

如果只想下载模型：

```bash
cd ~/rdk_model_zoo/samples/vision/ultralytics_yolo/model
chmod +x download_model.sh
./download_model.sh
ls -lh *pose*.bin
```

也可以手动下载：

```bash
mkdir -p ~/Intelligent_robot/runtime/models
wget -O ~/Intelligent_robot/runtime/models/yolo11n_pose_bayese_640x640_nv12.bin \
  https://archive.d-robotics.cc/downloads/rdk_model_zoo/rdk_x5/ultralytics_YOLO/yolo11n_pose_bayese_640x640_nv12.bin
```

验证 BPU 运行状态：

```bash
hrut_bpuprofile -b 0
cat /sys/devices/system/bpu/bpu0/ratio
```

成功标准：

```text
1. main.py 能正常加载 .bin
2. 日志里能看到 model info、pre-process、forward、post-process
3. ../../test_data/result_pose.jpg 中能看到人体骨架关键点
```

## 第二阶段：先跑通本项目普通 BPU 检测链路

本项目当前已经有 BPU-ready 节点：

```text
src/person_tracker/scripts/person_tracker_bpu_node.py
```

它当前适合接普通检测模型，比如：

```bash
mkdir -p ~/Intelligent_robot/runtime/models
wget -O ~/Intelligent_robot/runtime/models/yolo11n_detect_bayese_640x640_nv12.bin \
  https://archive.d-robotics.cc/downloads/rdk_model_zoo/rdk_x5/ultralytics_YOLO/yolo11n_detect_bayese_640x640_nv12.bin
```

构建并启动：

```bash
cd ~/Intelligent_robot
colcon build --packages-select person_tracker task_manager
source install/setup.bash

ros2 launch task_manager robot_server.launch.py \
  vision_backend:=bpu_yolo \
  bpu_yolo_model_path:=/home/pan/Intelligent_robot/runtime/models/yolo11n_detect_bayese_640x640_nv12.bin
```

检查 ROS 输出：

```bash
ros2 topic hz /person_position
ros2 topic echo /person_distance
ros2 topic echo /fall_detected
```

## 第三阶段：把官方 YOLOPose 解码接入 ROS

官方 YOLOPose wrapper 位于：

```text
rdk_model_zoo/samples/vision/ultralytics_yolo/runtime/python/ultralytics_yolo_pose.py
```

关键点：

```text
X5 YOLOPose .bin 输出协议是 [cls, box, keypoints] * 3
classes_num = 1
nkpt = 17
strides = 8,16,32
输入格式是 packed NV12
```

接入本项目时，不要改 `task_manager` 或 `follower_controller`。优先只改：

```text
src/person_tracker/scripts/person_tracker_bpu_node.py
```

建议新增一个 backend：

```text
vision_backend:=bpu_yolopose
```

并新增一个 detector：

```text
BpuYoloPosePersonDetector.detect(image) -> list[PersonDetection]
```

第一版可以只使用 YOLOPose 输出的 bbox，保持现有 `/person_position`、`/person_distance`、`/fall_detected` 不变。第二版再发布关键点 topic，例如：

```text
/person_pose_keypoints
```

## 常见坑

- `yolo11n_pose_bayese_640x640_nv12.bin` 不能直接传给当前 `vision_backend:=bpu_yolo`，因为当前代码按普通检测 head 解码。
- `pose` 模型类别数是 `1`，不是 COCO 检测的 `80`。
- model zoo 的 runtime 使用 `hbm_runtime`，本项目当前 BPU 检测节点使用 `hobot_dnn.pyeasy_dnn`。最终以 RDK X5 板端实际可 import 的运行库为准。
- 如果 `pip install opencv-python` 在板端太慢或失败，先检查系统是否已有 `cv2`，不要急着重装系统包。
- 模型路径建议统一放在 `~/Intelligent_robot/runtime/models/`，不要放在 `build/` 或 `install/`。

