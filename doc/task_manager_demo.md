# Task Manager Minimal Demo

## Version

- Version: v0.1.0
- Date: 2026-05-20
- Scope: Minimal elderly companion robot task scheduling loop.

## Current Changes

This version adds the first closed-loop task execution demo. The robot can accept a wake-up task, read a named target location, call Nav2 navigation, publish a fixed TTS sentence after arrival, and return to idle.

Main changes:

- Added `task_manager` ROS2 Python package.
- Added `RobotMode` states:
  - `IDLE`
  - `SCHEDULED_TASK`
  - `NAVIGATION`
  - `CONVERSATION`
  - `MANUAL`
  - `FAULT`
- Added named location config:
  - `bedroom`
  - `living_room`
  - `charger`
- Added wake-up task demo:
  - task id: `wakeup_bedroom`
  - target location: `bedroom`
  - speech text: `早上好，该起床了。`
- Added Nav2 `NavigateToPose` action client in `task_manager`.
- Added task cancellation service.
- Added navigation timeout handling.
- Added navigation retry handling.
- Added failure handling with optional `FAULT` mode.
- Added `rosa_agent` ROS TTS node:
  - subscribes to `/tts_text`
  - calls existing `rosa_agent.voice.speak()`

## Files

Important files:

- `src/task_manager/task_manager/task_manager_node.py`
- `src/task_manager/config/named_locations.yaml`
- `src/task_manager/launch/wakeup_demo.launch.py`
- `src/rosa_agent/rosa_agent/tts_node.py`
- `src/rosa_agent/setup.py`
- `src/rosa_agent/package.xml`

## Build

From workspace root:

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select rosa_agent task_manager
source install/setup.bash
```

## Start Navigation Stack

Start the existing navigation stack first:

```bash
source install/setup.bash
ros2 launch base_controller navigation.launch.py
```

Wait until Nav2 lifecycle nodes are active and `navigate_to_pose` action server is available.

## Start Task Manager Demo

In another terminal:

```bash
source install/setup.bash
ros2 launch task_manager wakeup_demo.launch.py
```

By default, `auto_start_demo` is `False`, so the robot will not move immediately after startup.

## Trigger Wake-Up Task

Use service trigger:

```bash
ros2 service call /trigger_wakeup_task std_srvs/srv/Trigger {}
```

Or publish a command:

```bash
ros2 topic pub --once /task_command std_msgs/msg/String "{data: wakeup_bedroom}"
```

Expected flow:

```text
IDLE
SCHEDULED_TASK
NAVIGATION
CONVERSATION
IDLE
```

The robot navigates to `bedroom`, then publishes this TTS text:

```text
早上好，该起床了。
```

## Cancel Task

```bash
ros2 service call /cancel_task std_srvs/srv/Trigger {}
```

If a Nav2 goal is active, `task_manager` sends a cancel request and returns to `IDLE`.

## Clear Fault

If navigation fails after retry limit and the node enters `FAULT`:

```bash
ros2 service call /clear_fault std_srvs/srv/Trigger {}
```

## Monitor State

```bash
ros2 topic echo /robot_mode
```

## Configure Named Locations

Edit:

```text
src/task_manager/config/named_locations.yaml
```

Example:

```yaml
locations:
  bedroom:
    frame_id: map
    x: 1.91
    y: -1.36
    yaw: 0.0
```

`yaw` uses radians.

## TTS Notes

The TTS node subscribes to `/tts_text`.

If `TTS_ENABLED=0`, the TTS function returns without playback. To enable real playback, configure the existing `rosa_agent` TTS environment variables, for example:

```bash
export TTS_ENABLED=1
export TTS_API_KEY=your_key
export TTS_BASE_URL=https://api.xiaomimimo.com/v1
export TTS_MODEL=mimo-v2.5-tts
export TTS_VOICE=mimo_default
```

For ALSA playback:

```bash
export AUDIO_BACKEND=alsa
export TTS_PLAYER=aplay
export AUDIO_OUTPUT_DEVICE=default
```

## Demo Parameters

`src/task_manager/launch/wakeup_demo.launch.py` exposes the common parameters:

- `locations_file`
- `auto_start_demo`
- `demo_start_delay_sec`
- `navigation_timeout_sec`
- `navigation_retry_limit`
- `tts_topic`

To auto-start the demo after launch, set `auto_start_demo` to `True` in the launch file.

## Verified

Commands verified:

```bash
python3 -m compileall src/task_manager/task_manager src/rosa_agent/rosa_agent
source /opt/ros/humble/setup.bash
colcon build --packages-select rosa_agent task_manager
source install/setup.bash
ros2 run task_manager task_manager_node --ros-args -p locations_file:=/home/pan/Intelligent_robot/src/task_manager/config/named_locations.yaml
```

The node starts in `IDLE` and loads:

```text
bedroom
charger
living_room
```
