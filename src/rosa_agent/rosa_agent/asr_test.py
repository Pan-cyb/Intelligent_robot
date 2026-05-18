from pathlib import Path

from rosa_agent.voice import transcribe


def main() -> None:
    audio_path = Path("test.wav")
    print(transcribe(audio_path))


if __name__ == "__main__":
    main()

