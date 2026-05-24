# demo_manager

`demo_manager` is a high-level demo flow orchestrator. It does not control Nav2,
publish `/cmd_vel`, or execute single robot tasks. It only calls task_manager's
high-level robot server services.

## Architecture Boundary

```text
demo_manager
  -> /robot_server/start_task
  -> /robot_server/query_robot_state
  -> /robot_server/cancel_current_task
  -> /robot_server/clear_emergency
  -> task_manager executes one task at a time
```

`task_manager` remains responsible for:

```text
wake_up / navigate / speak / follow / inspection / emergency
RobotMode state machine
Nav2 interaction
TTS publish
cancel / failure / emergency handling
```

## Demo Flow

The default final demo flow is:

```text
INIT
  -> WAKE_UP
  -> COMPANION_NAVIGATE
  -> COMPANION_DIALOGUE
  -> WAIT_FOR_INSPECTION_TIMER
  -> INSPECTION
  -> WAIT_FOR_FOLLOW_TRIGGER
```

Detailed behavior:

```text
1. Call task_type="wake_up", target="bedroom_bedside".
2. Wait until task_manager returns to IDLE.
3. Call task_type="navigate", target="livingroom_sofa".
4. Wait until task_manager returns to IDLE.
5. Call task_type="speak" with companion text.
6. Wait until task_manager returns to IDLE.
7. After demo start + 300 seconds, call task_type="inspection".
8. Wait until inspection completes and task_manager returns to IDLE.
9. Leave follow to ROSA voice command, for example "小智，跟着我".
```

Fall detection remains owned by `task_manager`: if `/fall_detected` is confirmed,
task_manager enters `EMERGENCY` and cancels the active task.

## Standalone Launch

```bash
ros2 launch demo_manager demo_manager.launch.py
```

Useful arguments:

```bash
ros2 launch demo_manager demo_manager.launch.py \
  demo_start_delay_sec:=5.0 \
  demo_auto_inspection_after_sec:=300.0 \
  demo_wakeup_target:=bedroom_bedside \
  demo_companion_target:=livingroom_sofa
```

## Full Robot Server Launch

```bash
ros2 launch task_manager robot_server.launch.py \
  enable_demo_manager:=true \
  enable_rosa_always_listen:=true
```

This starts the normal robot server stack, optional demo manager, and optional
ROSA always-listen voice entrypoint in one launch.
