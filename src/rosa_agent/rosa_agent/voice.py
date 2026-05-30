import base64
from collections import deque
import hashlib
import audioop
import queue
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

from openai import OpenAI
import requests

from rosa_agent.config import ASRConfig, RUNTIME_DIR, TTSConfig, asr_config, tts_config


CACHEABLE_TTS_TEXTS = {
    "我在。",
    "好的。",
    "正在执行。",
    "已停止。",
    "没有听清楚。",
    "检测到异常，您是否需要帮助？",
}
TTS_CACHE_DIR = RUNTIME_DIR / "tts_cache"
FRAME_MS = 100
SAMPLE_WIDTH = 2


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


def _write_wav(path: Path, frames: list[bytes], sample_rate: int, channels: int) -> None:
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(SAMPLE_WIDTH)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"".join(frames))


class PersistentAudioRecorder:
    def __init__(self, config: ASRConfig | None = None) -> None:
        self.config = config or asr_config()
        self.sample_rate = int(self.config.audio_sample_rate)
        self.channels = int(self.config.audio_channels)
        self.frame_bytes = int(
            self.sample_rate * self.channels * SAMPLE_WIDTH * FRAME_MS / 1000
        )
        self._frames: queue.Queue[bytes] = queue.Queue(maxsize=200)
        self._stop_event = threading.Event()
        self._speaking_until = 0.0
        self._process: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._calibrated = False
        self._noise_floor = 0
        self._start_threshold = self.config.vad_threshold
        self._release_threshold = self.config.vad_threshold

    def __enter__(self) -> "PersistentAudioRecorder":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def start(self) -> None:
        if self._thread is not None:
            return
        command = _record_raw_command(self.config)
        self._process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop_event.set()
        if self._process is not None:
            self._process.terminate()
            try:
                self._process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=1)
        if self._thread is not None:
            self._thread.join(timeout=1)

    def suppress_for(self, seconds: float) -> None:
        self._speaking_until = max(self._speaking_until, time.monotonic() + max(0.0, seconds))

    def resume_after_tts(self, cooldown_sec: float) -> None:
        self._clear_buffer()
        self.suppress_for(cooldown_sec)

    def _is_suppressed(self) -> bool:
        return time.monotonic() < self._speaking_until

    def _read_loop(self) -> None:
        if self._process is None or self._process.stdout is None:
            return
        while not self._stop_event.is_set():
            chunk = self._process.stdout.read(self.frame_bytes)
            if not chunk:
                break
            try:
                self._frames.put_nowait(chunk)
            except queue.Full:
                try:
                    self._frames.get_nowait()
                except queue.Empty:
                    pass
                self._frames.put_nowait(chunk)

    def _clear_buffer(self) -> None:
        while True:
            try:
                self._frames.get_nowait()
            except queue.Empty:
                return

    def _next_frame(self, timeout: float = 0.1) -> bytes | None:
        try:
            return self._frames.get(timeout=timeout)
        except queue.Empty:
            return None

    def calibrate(self) -> None:
        if self._calibrated or not self.config.vad_adaptive:
            return
        warmup_frames = max(0, int(self.config.vad_warmup_ms / FRAME_MS))
        calibrate_frames = max(0, int(self.config.vad_calibrate_ms / FRAME_MS))
        rms_values: list[int] = []

        while warmup_frames > 0:
            chunk = self._next_frame()
            if chunk is None:
                continue
            warmup_frames -= 1
            if self.config.vad_debug:
                print(f"VAD persistent warmup: rms={audioop.rms(chunk, SAMPLE_WIDTH)}")

        while len(rms_values) < calibrate_frames:
            chunk = self._next_frame()
            if chunk is None:
                continue
            rms_values.append(audioop.rms(chunk, SAMPLE_WIDTH))

        if rms_values:
            sorted_rms = sorted(rms_values)
            floor_index = min(len(sorted_rms) - 1, max(0, len(sorted_rms) // 4))
            self._noise_floor = sorted_rms[floor_index]
            self._start_threshold = max(
                self.config.vad_threshold,
                self._noise_floor + self.config.vad_margin,
            )
            self._release_threshold = max(
                self.config.vad_threshold,
                self._noise_floor + self.config.vad_release_margin,
            )
        self._calibrated = True
        if self.config.vad_debug:
            print(
                "VAD persistent calibration: "
                f"noise_floor={self._noise_floor}, "
                f"start_threshold={self._start_threshold}, "
                f"release_threshold={self._release_threshold}"
            )

    def record_wav_vad(
        self,
        prompt: str = "监听中...",
        listen_timeout_sec: int | None = None,
    ) -> Path | None:
        self.calibrate()
        silence_frames_needed = max(1, int(self.config.vad_silence_ms / FRAME_MS))
        pre_roll_frames = max(0, int(self.config.vad_pre_roll_ms / FRAME_MS))
        max_frames = max(1, int(self.config.vad_max_seconds * 1000 / FRAME_MS))
        timeout_sec = self.config.vad_listen_timeout_sec if listen_timeout_sec is None else listen_timeout_sec
        listen_deadline = time.monotonic() + timeout_sec if timeout_sec > 0 else None

        path = Path(tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name)
        heard_frames: list[bytes] = []
        pre_roll: deque[bytes] = deque(maxlen=pre_roll_frames)
        speech_started = False
        loud_frames = 0
        silence_frames = 0

        print(prompt)
        while True:
            if listen_deadline is not None and not speech_started and time.monotonic() > listen_deadline:
                path.unlink(missing_ok=True)
                return None

            chunk = self._next_frame()
            if chunk is None:
                continue
            if self._is_suppressed():
                self._clear_buffer()
                continue

            rms = audioop.rms(chunk, SAMPLE_WIDTH)
            is_loud = rms >= self._start_threshold

            if not speech_started:
                pre_roll.append(chunk)
                if self.config.vad_debug:
                    print(f"VAD persistent wait: rms={rms}, threshold={self._start_threshold}")
                if is_loud:
                    loud_frames += 1
                else:
                    loud_frames = 0
                if loud_frames >= self.config.vad_start_frames:
                    speech_started = True
                    heard_frames.extend(pre_roll)
                    pre_roll.clear()
                    print("检测到语音，录音中...")
                continue

            heard_frames.append(chunk)
            if self.config.vad_debug:
                print(f"VAD persistent record: rms={rms}, release_threshold={self._release_threshold}")
            if rms >= self._release_threshold:
                silence_frames = 0
            else:
                silence_frames += 1

            if silence_frames >= silence_frames_needed or len(heard_frames) >= max_frames:
                break

        if not heard_frames:
            path.unlink(missing_ok=True)
            return None

        _write_wav(path, heard_frames, self.sample_rate, self.channels)
        print(f"录音完成：{path}")
        return path


def record_wav_vad(
    config: ASRConfig | None = None,
    prompt: str = "监听中...",
    listen_timeout_sec: int | None = None,
) -> Path | None:
    config = config or asr_config()
    sample_rate = int(config.audio_sample_rate)
    channels = int(config.audio_channels)
    frame_bytes = int(sample_rate * channels * SAMPLE_WIDTH * FRAME_MS / 1000)
    warmup_frames = max(0, int(config.vad_warmup_ms / FRAME_MS))
    calibrate_frames = max(0, int(config.vad_calibrate_ms / FRAME_MS))
    silence_frames_needed = max(1, int(config.vad_silence_ms / FRAME_MS))
    pre_roll_frames = max(0, int(config.vad_pre_roll_ms / FRAME_MS))
    max_frames = max(1, int(config.vad_max_seconds * 1000 / FRAME_MS))
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

            rms = audioop.rms(chunk, SAMPLE_WIDTH)

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

        _write_wav(path, heard_frames, sample_rate, channels)

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


def _tts_cache_path(text: str, config: TTSConfig) -> Path:
    key = "|".join([text, config.model, config.voice, config.audio_format])
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
    return TTS_CACHE_DIR / f"{digest}.{config.audio_format}"


def _tts_play_command(audio_path: Path, config: TTSConfig) -> list[str]:
    command = [config.player, str(audio_path)]
    if config.player == "aplay" and config.audio_output_device:
        command = [config.player, "-D", config.audio_output_device, str(audio_path)]
    return command


def _play_audio_file(audio_path: Path, config: TTSConfig) -> bool:
    command = _tts_play_command(audio_path, config)
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True)
    except FileNotFoundError:
        print(f"\n未找到播放器：{config.player}。可设置 TTS_PLAYER=aplay 或安装 {config.player}。")
        return False

    if result.returncode != 0:
        stderr = result.stderr.strip()
        print(f"\nTTS 播放命令失败，退出码 {result.returncode}：{' '.join(command)}")
        if stderr:
            print(f"stderr:\n{stderr}")
        return False
    return True


def speak(text: str, config: TTSConfig | None = None) -> None:
    config = config or tts_config()
    if not config.enabled or not text.strip():
        return
    if not config.api_key or not config.base_url or not config.model:
        print("\nTTS 未配置：请填写 TTS_API_KEY、TTS_BASE_URL、TTS_MODEL，或设置 TTS_ENABLED=0。")
        return

    normalized_text = text.strip()
    cache_path = _tts_cache_path(normalized_text, config)
    use_cache = normalized_text in CACHEABLE_TTS_TEXTS
    if use_cache and cache_path.exists():
        if _play_audio_file(cache_path, config):
            print(f"TTS 缓存命中：{cache_path}")
            return
        print("TTS 缓存播放失败，回退网络 TTS。")

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
        if use_cache:
            TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(audio_bytes)
            audio_path = cache_path
            print(f"TTS 缓存写入：{cache_path}")
        else:
            audio_path = Path(
                tempfile.NamedTemporaryFile(suffix=f".{config.audio_format}", delete=False).name
            )
            audio_path.write_bytes(audio_bytes)
        _play_audio_file(audio_path, config)
    except FileNotFoundError:
        print(f"\n未找到播放器：{config.player}。可设置 TTS_PLAYER=aplay 或安装 {config.player}。")
    except requests.RequestException as exc:
        print(f"\nTTS 请求失败：{exc}")
    except (KeyError, IndexError, ValueError) as exc:
        print(f"\nTTS 响应解析失败：{exc}")
    finally:
        if audio_path is not None and not (use_cache and audio_path == cache_path):
            try:
                audio_path.unlink(missing_ok=True)
            except OSError as exc:
                print(f"\nTTS 临时文件清理失败：{exc}")
