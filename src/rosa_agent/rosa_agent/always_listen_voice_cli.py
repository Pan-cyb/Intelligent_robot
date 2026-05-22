from pathlib import Path

from rosa_agent.agent import create_agent
from rosa_agent.config import asr_config, tts_config
from rosa_agent.voice import record_wav_vad, speak, transcribe


WAKE_WORD = "小金"
MIN_COMMAND_LENGTH = 2


def _cleanup_audio(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"\n录音临时文件清理失败：{exc}")


def _listen_and_transcribe(label: str, asr, listen_timeout_sec: int | None = None) -> str:
    audio_path: Path | None = None
    try:
        audio_path = record_wav_vad(
            config=asr,
            prompt=label,
            listen_timeout_sec=listen_timeout_sec,
        )
        if audio_path is None:
            return ""
        return transcribe(audio_path, config=asr).strip()
    finally:
        _cleanup_audio(audio_path)


def _speak_safely(text: str, tts) -> None:
    try:
        speak(text, config=tts)
    except Exception as exc:
        print(f"\nTTS 播放失败：{exc}")


def main() -> None:
    agent = create_agent()
    asr = asr_config()
    tts = tts_config()

    print("ROSA 常驻语音代理已启动。等待唤醒词：小金。Ctrl+C 退出。")

    while True:
        try:
            wake_text = _listen_and_transcribe("WAIT_WAKE_WORD：监听唤醒词...")
            if not wake_text:
                continue

            print(f"\n识别：{wake_text}")
            if WAKE_WORD not in wake_text:
                continue

            print(f"检测到唤醒词：{WAKE_WORD}")

            print("SPEAK_ACK：我在。")
            _speak_safely("我在。", tts)

            command_text = _listen_and_transcribe(
                "LISTEN_COMMAND：请说命令...",
                asr,
                listen_timeout_sec=asr.command_listen_timeout_sec,
            )
            if len(command_text.strip()) < MIN_COMMAND_LENGTH:
                print("没有听清楚。")
                _speak_safely("没有听清楚。", tts)
                continue

            print(f"\n命令：{command_text}")
            reply = agent.invoke(command_text)
            print(f"\nROSA：{reply}")
            _speak_safely(str(reply), tts)

        except KeyboardInterrupt:
            print("\n退出")
            break
        except Exception as exc:
            print(f"\n出错：{exc}")


if __name__ == "__main__":
    main()
