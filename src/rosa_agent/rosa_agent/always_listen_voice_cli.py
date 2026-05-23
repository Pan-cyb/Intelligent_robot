from pathlib import Path
import time

from rosa_agent.agent import create_agent
from rosa_agent.cli import route_high_level_command
from rosa_agent.config import asr_config, tts_config
from rosa_agent.voice import record_wav_vad, speak, transcribe


WAKE_WORD = "小金"
MIN_COMMAND_LENGTH = 2
NOISE_TEXTS = {
    "啊",
    "嗯",
    "呃",
    "额",
    "哦",
    "喂",
    "唉",
    "诶",
    "嗯嗯",
    "啊啊",
}


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


def _normalize_asr_text(text: str) -> str:
    return text.strip().strip(" 。！？!?，,：:")


def _is_noise_command(text: str) -> bool:
    normalized = _normalize_asr_text(text)
    if len(normalized) < MIN_COMMAND_LENGTH:
        return True
    return normalized in NOISE_TEXTS


def _listen_command_until_valid(asr) -> str:
    deadline = time.monotonic() + max(1, asr.command_window_sec)
    attempt = 1
    while time.monotonic() < deadline:
        remaining = max(1, int(deadline - time.monotonic()))
        timeout = min(asr.command_listen_timeout_sec, remaining)
        command_text = _listen_and_transcribe(
            f"LISTEN_COMMAND：请说命令... attempt={attempt}",
            asr,
            listen_timeout_sec=timeout,
        )
        normalized = _normalize_asr_text(command_text)
        if not normalized:
            attempt += 1
            continue
        if _is_noise_command(normalized):
            print(f"忽略疑似噪声命令：{normalized}")
            attempt += 1
            continue
        return normalized
    return ""


def main() -> None:
    agent = create_agent()
    asr = asr_config()
    tts = tts_config()

    print("ROSA 常驻语音代理已启动。等待唤醒词：小金。Ctrl+C 退出。")

    while True:
        try:
            wake_text = _listen_and_transcribe("WAIT_WAKE_WORD：监听唤醒词...", asr)
            if not wake_text:
                continue

            print(f"\n识别：{wake_text}")
            if WAKE_WORD not in wake_text:
                continue

            print(f"检测到唤醒词：{WAKE_WORD}")

            print("SPEAK_ACK：我在。")
            _speak_safely("我在。", tts)
            if asr.post_tts_cooldown_sec > 0:
                time.sleep(asr.post_tts_cooldown_sec)

            command_text = _listen_command_until_valid(asr)
            if not command_text:
                print("没有听清楚。")
                _speak_safely("没有听清楚。", tts)
                continue

            print(f"\n命令：{command_text}")
            reply = route_high_level_command(command_text)
            if reply is None:
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
