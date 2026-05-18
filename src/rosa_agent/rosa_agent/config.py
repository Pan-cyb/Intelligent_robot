import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _workspace_root() -> Path:
    explicit = os.getenv("ROSA_WORKSPACE")
    if explicit:
        return Path(explicit).expanduser().resolve()

    cwd = Path.cwd().resolve()
    if (cwd / "src" / "rosa_agent").exists():
        return cwd

    for parent in Path(__file__).resolve().parents:
        if (parent / "src" / "rosa_agent").exists():
            return parent

    return cwd


PROJECT_ROOT = _workspace_root()
RUNTIME_DIR = Path(os.getenv("ROSA_RUNTIME_DIR", PROJECT_ROOT / "runtime" / "rosa_agent"))


def _load_env_files() -> None:
    explicit = os.getenv("ROSA_ENV_FILE")
    if explicit:
        load_dotenv(Path(explicit).expanduser().resolve(), override=False)

    for env_file in (
        PROJECT_ROOT / ".env",
        PROJECT_ROOT / "src" / "rosa_agent" / ".env",
        PACKAGE_ROOT / ".env",
    ):
        load_dotenv(env_file, override=False)

    load_dotenv(override=False)


_load_env_files()

@dataclass(frozen=True)
class LLMConfig:
    api_key: str | None
    base_url: str | None
    model: str
    temperature: float = 0


@dataclass(frozen=True)
class ASRConfig:
    api_key: str | None
    base_url: str | None
    model: str
    record_device: str
    record_seconds: int


@dataclass(frozen=True)
class TTSConfig:
    api_key: str | None
    base_url: str | None
    model: str
    voice: str
    audio_format: str
    player: str
    enabled: bool


def env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() not in {"0", "false", "no", "off"}


def llm_config() -> LLMConfig:
    return LLMConfig(
        api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
        model=os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    )


def asr_config() -> ASRConfig:
    return ASRConfig(
        api_key=os.getenv("ASR_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("ASR_BASE_URL") or os.getenv("OPENAI_BASE_URL"),
        model=os.getenv("ASR_MODEL", "whisper-1"),
        record_device=os.getenv("ASR_RECORD_DEVICE", "RDPSource"),
        record_seconds=int(os.getenv("ASR_RECORD_SECONDS", "5")),
    )


def tts_config() -> TTSConfig:
    return TTSConfig(
        api_key=os.getenv("TTS_API_KEY"),
        base_url=os.getenv("TTS_BASE_URL", "https://api.xiaomimimo.com/v1"),
        model=os.getenv("TTS_MODEL", "mimo-v2.5-tts"),
        voice=os.getenv("TTS_VOICE", "mimo_default"),
        audio_format=os.getenv("TTS_FORMAT", "wav"),
        player=os.getenv("TTS_PLAYER", "paplay"),
        enabled=env_bool("TTS_ENABLED", False),
    )


def ros_setup_path() -> str:
    return os.getenv("ROS_SETUP", "/opt/ros/humble/setup.bash")


def workspace_root() -> Path:
    return Path(os.getenv("ROSA_WORKSPACE", str(PROJECT_ROOT))).expanduser().resolve()
