# rosa_agent

`rosa_agent` is the ROSA assistant package for this ROS2 workspace. It provides:

- text CLI: `ros2 run rosa_agent rosa_cli`
- voice CLI with ASR and TTS: `ros2 run rosa_agent rosa_voice_cli`
- safe ROS2 action tools for short commands, background launch/node management, and workspace file access

## Layout

- `rosa_agent/config.py`: environment loading and runtime paths
- `rosa_agent/agent.py`: LLM and ROSA agent factory
- `rosa_agent/action_tools.py`: LangChain tools exposed to ROSA
- `rosa_agent/voice.py`: microphone recording, ASR, and TTS playback
- `rosa_agent/cli.py`: text interface
- `rosa_agent/voice_cli.py`: voice interface
- `launch/`: launch files the agent can run or inspect

Runtime logs and pid files are written under:

```bash
/home/pan/Intelligent_robot/runtime/rosa_agent/
```

## Setup

Copy `src/rosa_agent/.env.example` to `/home/pan/Intelligent_robot/.env` or `src/rosa_agent/.env`, then fill in API keys and model settings.

Build from the workspace root:

```bash
cd /home/pan/Intelligent_robot
source /opt/ros/humble/setup.bash
colcon build --packages-select rosa_agent
source install/setup.bash
```

Run:

```bash
ros2 run rosa_agent rosa_cli
ros2 run rosa_agent rosa_voice_cli
```

