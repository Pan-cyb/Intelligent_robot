# 2026-05-27 23:05 YOLOPose BPU Handoff

## Current Goal

YOLOPose BPU deployment has moved from model preparation to validated ROS runtime integration. The next goal is to validate robot behavior that consumes the BPU visual perception output, especially `follow`.

## Path Convention

Use this convention in future work:

```text
Local Windows/WSL development workspace:
  /home/pan/Intelligent_robot

RDK X5 runtime workspace:
  /home/sunrise/Myproj
```

Do not use `/home/sunrise/Intelligent_robot` for RDK runtime commands unless the user explicitly says that workspace is active again.

## Completed

- Downloaded and validated D-Robotics RDK X5 YOLOPose model:

```text
yolo11n_pose_bayese_640x640_nv12.bin
```

- Official model zoo sample successfully ran on RDK X5 with BPU runtime:

```text
BPU Platform Version ... soc info(x5)
DNN Runtime version ...
Load Model time ...
Forward time ...
Post Process time ...
```

- Added `vision_backend:=bpu_yolopose` support to:

```text
src/person_tracker/scripts/person_tracker_bpu_node.py
src/task_manager/launch/robot_server.launch.py
```

- `bpu_yolopose` decodes the official RDK X5 YOLOPose 9-output protocol:

```text
[cls, box, keypoints] * 3
strides = 8,16,32
classes_num = 1
nkpt = 17
input = packed NV12
```

- First ROS integration has been validated on RDK X5:

```text
/person_position publishes at about 2 Hz
/person_distance publishes
debug_window:=true opens and shows BPU YOLOPose bbox/keypoints/depth overlay
```

- BPU model file is deployed on the RDK runtime workspace:

```text
/home/sunrise/Myproj/runtime/models/yolo11n_pose_bayese_640x640_nv12.bin
```

## Verified Launch

On the RDK X5:

```bash
cd /home/sunrise/Myproj
colcon build --packages-select person_tracker task_manager
source install/setup.bash

ros2 launch task_manager robot_server.launch.py \
  vision_backend:=bpu_yolopose \
  bpu_yolo_model_path:=/home/sunrise/Myproj/runtime/models/yolo11n_pose_bayese_640x640_nv12.bin \
  debug_window:=true
```

Useful checks:

```bash
ros2 param get /person_tracker_bpu vision_backend
ros2 param get /person_tracker_bpu debug_window
ros2 param get /person_tracker_bpu bpu_yolo_model_path
ros2 topic hz /person_position
ros2 topic echo /person_distance --once
watch -n 0.5 cat /sys/devices/system/bpu/bpu0/ratio
hrut_bpuprofile -b 0
```

## Important Notes

- `runtime/` remains intentionally gitignored. Model files are deployment artifacts and should stay on the RDK runtime machine unless a future decision explicitly introduces Git LFS or a model download script.
- The current BPU YOLOPose node uses YOLOPose bbox for existing depth localization and stores keypoints in `PersonDetection`, but does not yet publish a dedicated keypoint ROS topic.
- Existing compatibility topics are preserved:

```text
/person_position
/person_distance
/fall_detected
```

- `task_manager` and `follower_controller` should not be changed just because the visual backend changed. Only change them if integration testing exposes a real consumer-side issue.

## Known Risks

- `/person_position` is currently about 2 Hz. This may be enough for navigation-level following, but it must be tested with a moving person.
- Fall detection is still bbox-style and disabled by default. If fall detection must use YOLOPose, implement keypoint-based fall logic.
- Debug window requires a graphical environment on the RDK. It is not a substitute for topic-level verification.

## Next Recommended Steps

1. Validate BPU YOLOPose during `follow`:

```bash
ros2 service call /robot_server/start_task task_manager_interfaces/srv/StartTask \
  "{task_type: 'follow', target: '', text: ''}"
```

2. Watch follow-related outputs:

```bash
ros2 topic echo /robot_mode
ros2 topic hz /person_position
ros2 topic echo /person_distance
```

3. If following jitters, tune in this order:

```text
person_tracker_bpu_node.py:
  inference_every_n_frames
  max_publish_rate_hz
  ema_alpha

follower_controller:
  goal_update_interval
  follow_distance
  lost_timeout
```

4. Decide whether to add a dedicated keypoints topic, for example:

```text
/person_pose_keypoints
```

5. If demo stability is good, update demo launch/docs to recommend:

```bash
vision_backend:=bpu_yolopose
bpu_yolo_model_path:=/home/sunrise/Myproj/runtime/models/yolo11n_pose_bayese_640x640_nv12.bin
```

## Resume Instructions

On resume, read:

```text
AGENTS.md
docs/PROJECT_STATUS.md
docs/handoff/2026-05-27_2305_yolopose_bpu_handoff.md
```

Then continue with RDK behavior integration, not model setup.

