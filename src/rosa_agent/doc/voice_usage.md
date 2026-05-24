# ROSA Agent 语音使用说明

本文档说明 `rosa_agent` 语音部分的常见使用方法，包括 WSLg PulseAudio 和 RDK X5 / Linux ALSA 两套音频配置。
python3 -m pip install --user jpl-rosa python-dotenv langchain-openai openai requests 记得先装依赖
## 环境变量文件

先从示例文件复制一份 `.env`：

```bash
cd /home/pan/Intelligent_robot
cp src/rosa_agent/.env.example .env
```

`rosa_agent` 会读取以下位置的环境变量：

```text
/home/pan/Intelligent_robot/.env
/home/pan/Intelligent_robot/src/rosa_agent/.env
```

一般建议使用工作空间根目录下的 `.env`，也就是：

```text
/home/pan/Intelligent_robot/.env
```

## 模型相关配置

根据实际使用的模型服务填写 LLM 和 ASR 配置：

```bash
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=gpt-4o-mini

LLM_API_KEY=
LLM_BASE_URL=
LLM_MODEL=

ASR_API_KEY=
ASR_BASE_URL=
ASR_MODEL=whisper-1
ASR_RECORD_SECONDS=5
```

说明：

- `LLM_*` 用于 ROSA 对话和 tool calling。
- `ASR_*` 用于语音识别。
- 如果 `LLM_*` 或 `ASR_*` 为空，代码会按现有逻辑尝试使用 `OPENAI_*` 配置。
- `ASR_RECORD_SECONDS` 是每次按回车后录音的秒数。

## TTS 配置

TTS 用于把 ROSA 回复播放成语音。建议先跑通文字 CLI 和 ASR，再打开 TTS。

```bash
TTS_API_KEY=
TTS_BASE_URL=https://api.xiaomimimo.com/v1
TTS_MODEL=mimo-v2.5-tts
TTS_VOICE=mimo_default
TTS_FORMAT=wav
TTS_ENABLED=1
```

如果不需要语音播放，关闭 TTS：

```bash
TTS_ENABLED=0
```

## WSLg PulseAudio 配置

在 WSLg 环境中使用 PulseAudio 后端：

```bash
AUDIO_BACKEND=pulse
AUDIO_INPUT_DEVICE=RDPSource
AUDIO_OUTPUT_DEVICE=
AUDIO_SAMPLE_RATE=16000
AUDIO_CHANNELS=1
AUDIO_FORMAT=wav
TTS_PLAYER=paplay
```

录音时实际调用形式：

```bash
timeout <seconds> parecord --device=RDPSource --rate=16000 --channels=1 --format=s16le --file-format=wav <path>
```

播放时实际调用形式：

```bash
paplay <wav_path>
```

WSLg 中的音频通常是：

```text
Linux 程序 -> PulseAudio/PipeWire -> Windows 音频设备
```

所以 WSLg 下使用 `parecord` 和 `paplay`。

## RDK X5 / Linux ALSA 配置

在 RDK X5 或普通 Linux ALSA 环境中使用 ALSA 后端：

```bash
AUDIO_BACKEND=alsa
AUDIO_INPUT_DEVICE=plughw:1,0
AUDIO_OUTPUT_DEVICE=plughw:2,0
AUDIO_SAMPLE_RATE=16000
AUDIO_CHANNELS=1
AUDIO_FORMAT=wav
TTS_PLAYER=aplay
```

注意：`plughw:1,0` 和 `plughw:2,0` 只是示例，不要写死在代码里。实际设备编号需要在 RDK 上通过 `arecord -l` 和 `aplay -l` 查看，然后写入 `.env`。

RDK X5 有板载 ES8326B 音频 Codec/耳机音频接口，但不是自带完整麦克风和扬声器。实际项目建议先用 USB 麦克风 + USB 音箱跑通，再考虑板载 Codec 或其他音频硬件。

录音时实际调用形式：

```bash
arecord -D <AUDIO_INPUT_DEVICE> -d <seconds> -f S16_LE -r 16000 -c 1 <path>
```

播放时如果没有设置 `AUDIO_OUTPUT_DEVICE`：

```bash
aplay <wav_path>
```

播放时如果设置了 `AUDIO_OUTPUT_DEVICE`：

```bash
aplay -D <AUDIO_OUTPUT_DEVICE> <wav_path>
```

RDK/Linux 中的音频通常是：

```text
Linux 程序 -> ALSA -> 板载声卡 / USB 麦克风 / USB 音箱
```

所以 RDK/Linux 下使用 `arecord` 和 `aplay`。

## RDK 音频设备测试命令

查看录音设备：

```bash
arecord -l
```

查看播放设备：

```bash
aplay -l
```

录制 5 秒测试音频：

```bash
arecord -D plughw:1,0 -d 5 -f S16_LE -r 16000 -c 1 test.wav
```

使用默认输出播放：

```bash
aplay test.wav
```

指定输出设备播放：

```bash
aplay -D plughw:2,0 test.wav
```

如果命令失败，查看终端打印的 `stderr`，通常可以看到设备不存在、设备被占用、格式不支持等原因。根据错误信息调整 `.env` 中的：

```bash
AUDIO_INPUT_DEVICE=
AUDIO_OUTPUT_DEVICE=
```

## 编译

在工作空间根目录编译 `rosa_agent`：

```bash
cd /home/pan/Intelligent_robot
colcon build --packages-select rosa_agent
source install/setup.bash
```

如果当前终端还没有 source ROS 2 环境，先执行：

```bash
source /opt/ros/humble/setup.bash
```

## 常用运行命令

文字 CLI：

```bash
ros2 run rosa_agent rosa_cli
```

语音 CLI：

```bash
ros2 run rosa_agent rosa_voice_cli
```

常驻语音代理：

```bash
ros2 run rosa_agent rosa_always_listen
```

交互流程：

```text
WAIT_WAKE_WORD  监听“小智”，并兼容 ASR 常见同音结果“小志”
SPEAK_ACK       检测到唤醒词后播放“我在。”
LISTEN_COMMAND  播放结束后监听下一句话
PROCESS_COMMAND 根据意图分流到高层任务、普通聊天或 ROSA tool agent，再播放 ROSA 回复
```

常驻语音代理使用 RMS 音量 VAD，默认启用环境底噪自适应。启动每轮监听时会先采样短时间环境音，实际启动阈值为 `max(ASR_VAD_THRESHOLD, noise_floor + ASR_VAD_MARGIN)`，录音结束阈值为 `max(ASR_VAD_THRESHOLD, noise_floor + ASR_VAD_RELEASE_MARGIN)`。

可在 `.env` 中调节：

```bash
ASR_VAD_THRESHOLD=700
ASR_VAD_ADAPTIVE=1
ASR_VAD_WARMUP_MS=500
ASR_VAD_CALIBRATE_MS=1000
ASR_VAD_MARGIN=900
ASR_VAD_RELEASE_MARGIN=400
ASR_VAD_DEBUG=0
ASR_VAD_START_FRAMES=2
ASR_VAD_SILENCE_MS=900
ASR_VAD_PRE_ROLL_MS=300
ASR_VAD_MAX_SECONDS=8
ASR_VAD_LISTEN_TIMEOUT_SEC=0
ASR_COMMAND_LISTEN_TIMEOUT_SEC=8
```

`ASR_VAD_LISTEN_TIMEOUT_SEC=0` 表示等待唤醒词时一直监听。`ASR_COMMAND_LISTEN_TIMEOUT_SEC` 控制唤醒后等待命令的时间窗口。

`ASR_VAD_WARMUP_MS` 用于丢弃录音设备刚启动时的瞬态噪声，避免把启动噪声算进底噪。

如果现场底噪接近人声，先设置 `ASR_VAD_DEBUG=1` 观察 `noise_floor`、`start_threshold` 和说话时 RMS。误触发环境音时优先增大 `ASR_VAD_MARGIN`；人声触发不了时优先减小 `ASR_VAD_MARGIN` 或检查麦克风增益。`ASR_VAD_RELEASE_MARGIN` 应低于 `ASR_VAD_MARGIN`，用于让一句话中短暂停顿不立刻截断。

常驻语音代理在命令窗口中会忽略极短 ASR 文本和常见噪声词，例如“啊”“嗯”“呃”。如果被噪声误触发，它会继续在命令窗口内等待下一句话，直到收到有效命令或窗口超时。

常见机器人命令会先走本地高层路由，不要求用户逐字说固定命令。例如包含“充电”“回充”“充电桩”的命令都会映射到当前地图中的 `charger`；包含“客厅”或“沙发”的命令会映射到 `livingroom_sofa`。

ASR 测试入口：

```bash
ros2 run rosa_agent test_asr
```

TTS ROS 节点：

```bash
ros2 run rosa_agent tts_node
```

向 TTS 节点发布文本：

```bash
ros2 topic pub --once /tts_text std_msgs/msg/String "{data: '你好，我是 ROSA。'}"
```

## 常见使用流程

1. 复制 `.env.example` 到工作空间根目录 `.env`。
2. 填写 LLM、ASR、TTS 相关 API key 和模型配置。
3. 在 WSLg 中设置 `AUDIO_BACKEND=pulse`。
4. 在 RDK X5 / Linux 中设置 `AUDIO_BACKEND=alsa`。
5. 在 RDK/Linux 上先执行 `arecord -l` 和 `aplay -l`，确认真实设备编号。
6. 把麦克风设备写入 `AUDIO_INPUT_DEVICE`。
7. 把扬声器或声卡输出设备写入 `AUDIO_OUTPUT_DEVICE`。
8. 编译 `rosa_agent`。
9. 运行 `ros2 run rosa_agent rosa_voice_cli`。

## 常见问题排查

WSLg 录音失败时，先检查：

```bash
which parecord
```

并确认：

```bash
AUDIO_BACKEND=pulse
AUDIO_INPUT_DEVICE=RDPSource
```

RDK/Linux 录音失败时，先检查：

```bash
arecord -l
```

并确认 `.env` 中的输入设备：

```bash
AUDIO_INPUT_DEVICE=plughw:1,0
```

RDK/Linux 播放失败时，先检查：

```bash
aplay -l
```

并确认 `.env` 中的输出设备：

```bash
AUDIO_OUTPUT_DEVICE=plughw:2,0
```

如果没有 TTS 声音，检查：

```bash
TTS_ENABLED=1
TTS_API_KEY=
TTS_PLAYER=paplay
```

如果使用 ALSA 播放，确认：

```bash
TTS_PLAYER=aplay
```

如果语音 CLI 能识别文字但没有播放声音，通常是 TTS 配置、播放器命令或输出设备编号问题。
