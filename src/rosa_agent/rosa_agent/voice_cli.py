from pathlib import Path

from rosa_agent.agent import create_agent
from rosa_agent.config import asr_config, tts_config
from rosa_agent.voice import record_wav, speak, transcribe


def main() -> None:
    agent = create_agent()
    asr = asr_config()
    tts = tts_config()

    while True:
        audio_path: Path | None = None
        try:
            audio_path = record_wav(config=asr)
            text = transcribe(audio_path, config=asr).strip()

            print(f"\n你说：{text}")

            if text.lower() in {"exit", "quit"} or text in {"退出", "结束"}:
                break

            reply = agent.invoke(text)
            print(f"\nROSA：{reply}")
            try:
                speak(str(reply), config=tts)
            except Exception as exc:
                print(f"\nTTS 播放失败：{exc}")

        except KeyboardInterrupt:
            print("\n退出")
            break
        except Exception as exc:
            print(f"\n出错：{exc}")
        finally:
            if audio_path is not None:
                try:
                    audio_path.unlink(missing_ok=True)
                except OSError as exc:
                    print(f"\n录音临时文件清理失败：{exc}")


if __name__ == "__main__":
    main()
