# rosa_agent

`rosa_agent` is the ROSA assistant package for this ROS2 workspace. It provides:

- text CLI: `ros2 run rosa_agent rosa_cli`
- voice CLI with ASR and TTS: `ros2 run rosa_agent rosa_voice_cli`
- always-on wake-word voice agent: `ros2 run rosa_agent rosa_always_listen`
- high-level robot action tools for task_manager robot server services

## Layout

- `rosa_agent/config.py`: environment loading and runtime paths
- `rosa_agent/agent.py`: LLM and ROSA agent factory
- `rosa_agent/action_tools.py`: LangChain tools exposed to ROSA
- `rosa_agent/voice.py`: microphone recording, ASR, and TTS playback
- `rosa_agent/cli.py`: text interface
- `rosa_agent/voice_cli.py`: voice interface
- `rosa_agent/always_listen_voice_cli.py`: always-on wake-word voice interface
- `launch/`: launch files the agent can run or inspect

Runtime logs and pid files are written under:

```bash
/home/pan/Intelligent_robot/runtime/rosa_agent/
```

## Setup

Copy `src/rosa_agent/.env.example` to `/home/pan/Intelligent_robot/.env` or `src/rosa_agent/.env`, then fill in API keys and model settings.

WSLg PulseAudio audio settings:

```bash
AUDIO_BACKEND=pulse
AUDIO_INPUT_DEVICE=RDPSource
AUDIO_OUTPUT_DEVICE=
AUDIO_SAMPLE_RATE=16000
AUDIO_CHANNELS=1
```

RDK X5 / Linux ALSA audio settings:

```bash
AUDIO_BACKEND=alsa
AUDIO_INPUT_DEVICE=plughw:1,0
AUDIO_OUTPUT_DEVICE=plughw:2,0
AUDIO_SAMPLE_RATE=16000
AUDIO_CHANNELS=1
TTS_PLAYER=aplay
```

RDK X5 has an onboard ES8326B audio codec/headphone audio interface, but not a complete built-in microphone and speaker setup. For first bring-up, use a USB microphone and USB speaker when possible.

RDK X5 audio device tests:

```bash
arecord -l
aplay -l
arecord -D plughw:1,0 -d 5 -f S16_LE -r 16000 -c 1 test.wav
aplay test.wav
aplay -D plughw:2,0 test.wav
```

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
ros2 run rosa_agent rosa_always_listen
```
