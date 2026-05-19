import base64
import subprocess
import tempfile
from pathlib import Path

from openai import OpenAI
import requests

from rosa_agent.config import ASRConfig, TTSConfig, asr_config, tts_config


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
