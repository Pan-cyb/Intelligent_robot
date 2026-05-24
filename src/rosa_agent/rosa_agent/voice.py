import base64
from collections import deque
import audioop
import subprocess
import tempfile
import time
import wave
from pathlib import Path

from openai import OpenAI
import requests

from rosa_agent.config import ASRConfig, TTSConfig, asr_config, tts_config


def _record_raw_command(config: ASRConfig) -> list[str]:
    sample_rate = str(config.audio_sample_rate)
    channels = str(config.audio_channels)
    if config.audio_backend == "pulse":
        return [
            "parecord",
            f"--device={config.audio_input_device}",
            f"--rate={sample_rate}",
            f"--channels={channels}",
            "--format=s16le",
            "--raw",
        ]
    if config.audio_backend == "alsa":
        return [
            "arecord",
            "-D",
            config.audio_input_device,
            "-f",
            "S16_LE",
            "-r",
            sample_rate,
            "-c",
            channels,
            "-t",
            "raw",
        ]
    raise ValueError("AUDIO_BACKEND 仅支持 pulse 或 alsa")


def record_wav_vad(
    config: ASRConfig | None = None,
    prompt: str = "监听中...",
    listen_timeout_sec: int | None = None,
) -> Path | None:
    config = config or asr_config()
    sample_rate = int(config.audio_sample_rate)
    channels = int(config.audio_channels)
    sample_width = 2
    frame_ms = 100
    frame_bytes = int(sample_rate * channels * sample_width * frame_ms / 1000)
    warmup_frames = max(0, int(config.vad_warmup_ms / frame_ms))
    calibrate_frames = max(0, int(config.vad_calibrate_ms / frame_ms))
    silence_frames_needed = max(1, int(config.vad_silence_ms / frame_ms))
    pre_roll_frames = max(0, int(config.vad_pre_roll_ms / frame_ms))
    max_frames = max(1, int(config.vad_max_seconds * 1000 / frame_ms))
    listen_deadline = None
    timeout_sec = config.vad_listen_timeout_sec if listen_timeout_sec is None else listen_timeout_sec
    if timeout_sec > 0:
        listen_deadline = time.monotonic() + timeout_sec

    command = _record_raw_command(config)
    path = Path(tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name)
    process = None
    heard_frames: list[bytes] = []
    pre_roll: deque[bytes] = deque(maxlen=pre_roll_frames)
    speech_started = False
    loud_frames = 0
    silence_frames = 0
    warmup_seen = 0
    calibration_rms_values: list[int] = []
    noise_floor = 0
    start_threshold = config.vad_threshold
    release_threshold = config.vad_threshold

    print(prompt)
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError:
        print(f"\n未找到录音命令：{command[0]}。请安装对应音频工具或检查 AUDIO_BACKEND。")
        path.unlink(missing_ok=True)
        return None

    try:
        if process.stdout is None:
            path.unlink(missing_ok=True)
            return None

        while True:
            if listen_deadline is not None and not speech_started and time.monotonic() > listen_deadline:
                path.unlink(missing_ok=True)
                return None

            chunk = process.stdout.read(frame_bytes)
            if not chunk:
                break

            rms = audioop.rms(chunk, sample_width)

            if config.vad_adaptive and not speech_started and warmup_seen < warmup_frames:
                warmup_seen += 1
                if config.vad_debug:
                    print(f"VAD warmup: rms={rms}")
                continue

            if config.vad_adaptive and not speech_started and len(calibration_rms_values) < calibrate_frames:
                pre_roll.append(chunk)
                calibration_rms_values.append(rms)
                if len(calibration_rms_values) == calibrate_frames:
                    sorted_rms = sorted(calibration_rms_values)
                    floor_index = min(len(sorted_rms) - 1, max(0, len(sorted_rms) // 4))
                    noise_floor = sorted_rms[floor_index]
                    start_threshold = max(config.vad_threshold, noise_floor + config.vad_margin)
                    release_threshold = max(
                        config.vad_threshold,
                        noise_floor + config.vad_release_margin,
                    )
                    if config.vad_debug:
                        print(
                            "VAD calibration: "
                            f"noise_floor={noise_floor}, "
                            f"start_threshold={start_threshold}, "
                            f"release_threshold={release_threshold}"
                        )
                continue

            is_loud = rms >= start_threshold

            if not speech_started:
                pre_roll.append(chunk)
                if config.vad_debug:
                    print(f"VAD wait: rms={rms}, threshold={start_threshold}")
                if is_loud:
                    loud_frames += 1
                else:
                    loud_frames = 0

                if loud_frames >= config.vad_start_frames:
                    speech_started = True
                    heard_frames.extend(pre_roll)
                    pre_roll.clear()
                    print("检测到语音，录音中...")
                continue

            heard_frames.append(chunk)
            if config.vad_debug:
                print(f"VAD record: rms={rms}, release_threshold={release_threshold}")
            if rms >= release_threshold:
                silence_frames = 0
            else:
                silence_frames += 1

            if silence_frames >= silence_frames_needed:
                break
            if len(heard_frames) >= max_frames:
                break

        if not heard_frames:
            path.unlink(missing_ok=True)
            return None

        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(b"".join(heard_frames))

        print(f"录音完成：{path}")
        return path
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)


def record_wav(seconds: int | None = None, config: ASRConfig | None = None) -> Path:
    config = config or asr_config()
    duration = seconds or config.record_seconds
    path = Path(tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name)

    print(f"\n按回车开始录音，录 {duration} 秒。")
    input()
    print("录音中...")

    if config.audio_backend == "pulse":
        command = [
            "timeout",
            str(duration),
            "parecord",
            f"--device={config.audio_input_device}",
            f"--rate={config.audio_sample_rate}",
            f"--channels={config.audio_channels}",
            "--format=s16le",
            f"--file-format={config.audio_format}",
            str(path),
        ]
    elif config.audio_backend == "alsa":
        command = [
            "arecord",
            "-D",
            config.audio_input_device,
            "-d",
            str(duration),
            "-f",
            "S16_LE",
            "-r",
            config.audio_sample_rate,
            "-c",
            config.audio_channels,
            str(path),
        ]
    else:
        raise ValueError("AUDIO_BACKEND 仅支持 pulse 或 alsa")

    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        print(f"\n未找到录音命令：{command[0]}。请安装对应音频工具或检查 AUDIO_BACKEND。")
        return path

    if result.returncode != 0:
        stderr = result.stderr.strip()
        print(f"\n录音命令失败，退出码 {result.returncode}：{' '.join(command)}")
        if stderr:
            print(f"stderr:\n{stderr}")

    print(f"录音完成：{path}")
    return path


def transcribe(path: Path, config: ASRConfig | None = None) -> str:
    config = config or asr_config()
    client = OpenAI(api_key=config.api_key, base_url=config.base_url or None)

    with path.open("rb") as audio_file:
        audio_base64 = base64.b64encode(audio_file.read()).decode("utf-8")

    completion = client.chat.completions.create(
        model=config.model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": f"data:audio/wav;base64,{audio_base64}",
                            "format": "wav",
                        },
                    }
                ],
            }
        ],
        stream=False,
        extra_body={
            "asr_options": {
                "enable_itn": False,
            }
        },
    )

    return completion.choices[0].message.content


def speak(text: str, config: TTSConfig | None = None) -> None:
    config = config or tts_config()
    if not config.enabled or not text.strip():
        return
    if not config.api_key or not config.base_url or not config.model:
        print("\nTTS 未配置：请填写 TTS_API_KEY、TTS_BASE_URL、TTS_MODEL，或设置 TTS_ENABLED=0。")
        return

    audio_path = None
    try:
        response = requests.post(
            f"{config.base_url.rstrip('/')}/chat/completions",
            headers={
                "Content-Type": "application/json",
                "api-key": config.api_key,
            },
            json={
                "model": config.model,
                "messages": [
                    {
                        "role": "assistant",
                        "content": text,
                    }
                ],
                "modalities": ["audio"],
                "audio": {
                    "voice": config.voice,
                    "format": config.audio_format,
                },
            },
            timeout=60,
        )
        response.raise_for_status()
        audio_base64 = response.json()["choices"][0]["message"]["audio"]["data"]
        audio_bytes = base64.b64decode(audio_base64)
        audio_path = Path(
            tempfile.NamedTemporaryFile(suffix=f".{config.audio_format}", delete=False).name
        )
        audio_path.write_bytes(audio_bytes)
        command = [config.player, str(audio_path)]
        if config.player == "aplay" and config.audio_output_device:
            command = [config.player, "-D", config.audio_output_device, str(audio_path)]
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            print(f"\nTTS 播放命令失败，退出码 {result.returncode}：{' '.join(command)}")
            if stderr:
                print(f"stderr:\n{stderr}")
    except FileNotFoundError:
        print(f"\n未找到播放器：{config.player}。可设置 TTS_PLAYER=aplay 或安装 {config.player}。")
    except requests.RequestException as exc:
        print(f"\nTTS 请求失败：{exc}")
    except (KeyError, IndexError, ValueError) as exc:
        print(f"\nTTS 响应解析失败：{exc}")
    finally:
        if audio_path is not None:
            try:
                audio_path.unlink(missing_ok=True)
            except OSError as exc:
                print(f"\nTTS 临时文件清理失败：{exc}")
