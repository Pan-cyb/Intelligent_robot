from pathlib import Path
import time

from rosa_agent.agent import create_agent, create_llm
from rosa_agent.action_tools import (
    cancel_current_task,
    navigate_to_named_place,
    query_robot_state,
    start_following_task,
    start_inspection_task,
    start_wakeup_task,
)
from rosa_agent.cli import reply_to_user
from rosa_agent.config import asr_config, tts_config
from rosa_agent.voice import PersistentAudioRecorder, speak, transcribe


WAKE_WORD = "小智"
WAKE_WORD_ALIASES = (WAKE_WORD, "小志")
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
QUICK_COMMANDS = [
    (("跟着我", "跟随我", "开始跟随"), "start_following_task", lambda: start_following_task.invoke({"_": ""}), "正在执行。"),
    (("停下", "停止", "取消任务", "别动"), "cancel_current_task", lambda: cancel_current_task.invoke({"_": ""}), "已停止。"),
    (("去厨房",), "navigate_to_named_place(kitchen)", lambda: navigate_to_named_place.invoke({"place_name": "kitchen"}), "正在执行。"),
    (("去沙发", "去客厅"), "navigate_to_named_place(livingroom_sofa)", lambda: navigate_to_named_place.invoke({"place_name": "livingroom_sofa"}), "正在执行。"),
    (("去卧室",), "navigate_to_named_place(bedroom_bedside)", lambda: navigate_to_named_place.invoke({"place_name": "bedroom_bedside"}), "正在执行。"),
    (("回充电", "去充电"), "navigate_to_named_place(charger)", lambda: navigate_to_named_place.invoke({"place_name": "charger"}), "正在执行。"),
    (("叫醒老人",), "start_wakeup_task", lambda: start_wakeup_task.invoke({"_": ""}), "正在执行。"),
    (("开始巡检", "开始巡航"), "start_inspection_task", lambda: start_inspection_task.invoke({"_": ""}), "正在执行。"),
    (("现在状态", "你在干什么"), "query_robot_state", lambda: query_robot_state.invoke({"_": ""}), "好的。"),
]


def _elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000.0


def _cleanup_audio(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        print(f"\n录音临时文件清理失败：{exc}")


def _listen_and_transcribe(
    label: str,
    asr,
    recorder: PersistentAudioRecorder,
    listen_timeout_sec: int | None = None,
) -> str:
    audio_path: Path | None = None
    try:
        record_start = time.monotonic()
        audio_path = recorder.record_wav_vad(
            prompt=label,
            listen_timeout_sec=listen_timeout_sec,
        )
        print(f"VAD 录音耗时：{_elapsed_ms(record_start):.0f} ms")
        if audio_path is None:
            return ""
        asr_start = time.monotonic()
        text = transcribe(audio_path, config=asr).strip()
        print(f"ASR 请求耗时：{_elapsed_ms(asr_start):.0f} ms")
        return text
    finally:
        _cleanup_audio(audio_path)


def _speak_safely(text: str, tts, recorder: PersistentAudioRecorder | None = None) -> None:
    try:
        start = time.monotonic()
        if recorder is not None:
            recorder.suppress_for(0.2)
        speak(text, config=tts)
        if recorder is not None:
            recorder.resume_after_tts(tts_post_cooldown_sec)
        print(f"TTS 播放/生成耗时：{_elapsed_ms(start):.0f} ms")
    except Exception as exc:
        print(f"\nTTS 播放失败：{exc}")


def _normalize_asr_text(text: str) -> str:
    return text.strip().strip(" 。！？!?，,：:")


def _is_noise_command(text: str) -> bool:
    normalized = _normalize_asr_text(text)
    if len(normalized) < MIN_COMMAND_LENGTH:
        return True
    return normalized in NOISE_TEXTS


def _matched_wake_word(text: str) -> str | None:
    for word in WAKE_WORD_ALIASES:
        if word in text:
            return word
    return None


def _command_after_wake_word(text: str, wake_word: str) -> str:
    _, _, command = text.partition(wake_word)
    return _normalize_asr_text(command)


def _compact_command_text(text: str) -> str:
    separators = " 。！？!?，,：:；;、\t\r\n"
    return "".join(ch for ch in text.strip() if ch not in separators)


tts_post_cooldown_sec = 0.0


def _try_handle_quick_command(
    command_text: str,
    tts,
    recorder: PersistentAudioRecorder,
) -> bool:
    start = time.monotonic()
    compact = _compact_command_text(command_text)
    matched = None
    for phrases, name, action, tts_reply in QUICK_COMMANDS:
        if any(phrase in compact for phrase in phrases):
            matched = (name, action, tts_reply)
            break

    print(f"快速命令匹配耗时：{_elapsed_ms(start):.0f} ms")
    if matched is None:
        return False

    name, action, tts_reply = matched
    print(f"快速命令命中：{name}")
    try:
        result = action()
        print(f"快速命令结果：{result}")
        _speak_safely(tts_reply, tts, recorder)
    except Exception as exc:
        print(f"快速命令执行失败：{exc}")
        _speak_safely("没有听清楚。", tts, recorder)
    return True


def _listen_command_until_valid(asr, recorder: PersistentAudioRecorder) -> str:
    return _listen_command_until_valid_for(asr, recorder, max(1, asr.command_window_sec))


def _listen_command_until_valid_for(
    asr,
    recorder: PersistentAudioRecorder,
    window_sec: float,
) -> str:
    deadline = time.monotonic() + max(1, window_sec)
    attempt = 1
    while time.monotonic() < deadline:
        remaining = max(1, int(deadline - time.monotonic()))
        timeout = min(asr.command_listen_timeout_sec, remaining)
        command_text = _listen_and_transcribe(
            "请说命令...",
            asr,
            recorder,
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


def _handle_command(
    command_text: str,
    agent,
    llm,
    tts,
    recorder: PersistentAudioRecorder,
) -> None:
    print(f"\n命令：{command_text}")
    if _try_handle_quick_command(command_text, tts, recorder):
        return
    llm_start = time.monotonic()
    reply = reply_to_user(command_text, agent=agent, llm=llm)
    print(f"LLM 调用耗时：{_elapsed_ms(llm_start):.0f} ms")
    print(f"\nROSA：{reply}")
    _speak_safely(str(reply), tts, recorder)


def main() -> None:
    global tts_post_cooldown_sec
    agent = create_agent()
    llm = create_llm()
    asr = asr_config()
    tts = tts_config()
    tts_post_cooldown_sec = asr.post_tts_cooldown_sec

    print(f"ROSA 常驻语音代理已启动。等待唤醒词：{WAKE_WORD}。Ctrl+C 退出。")

    try:
        recorder = PersistentAudioRecorder(asr)
        recorder.start()
    except FileNotFoundError:
        print(f"\n未找到录音命令。请安装对应音频工具或检查 AUDIO_BACKEND={asr.audio_backend}。")
        return

    with recorder:
        while True:
            try:
                wake_text = _listen_and_transcribe("等待唤醒词...", asr, recorder)
                if not wake_text:
                    continue

                print(f"\n识别：{wake_text}")
                matched_wake_word = _matched_wake_word(wake_text)
                if matched_wake_word is None:
                    continue

                print(f"检测到唤醒词：{matched_wake_word}")
                command_text = _command_after_wake_word(wake_text, matched_wake_word)
                if command_text and _is_noise_command(command_text):
                    command_text = ""

                if not command_text:
                    print("我在。")
                    _speak_safely("我在。", tts, recorder)

                    command_text = _listen_command_until_valid(asr, recorder)
                if not command_text:
                    print("没有听清楚。")
                    _speak_safely("没有听清楚。", tts, recorder)
                    continue

                while command_text:
                    _handle_command(command_text, agent, llm, tts, recorder)
                    command_text = _listen_command_until_valid_for(
                        asr,
                        recorder,
                        asr.session_idle_timeout_sec,
                    )

                print("会话超时，重新等待唤醒词。")

            except KeyboardInterrupt:
                print("\n退出")
                break
            except Exception as exc:
                print(f"\n出错：{exc}")


if __name__ == "__main__":
    main()
