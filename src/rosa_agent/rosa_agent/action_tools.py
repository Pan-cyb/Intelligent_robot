import os
import shlex
import signal
import subprocess
from pathlib import Path

import requests
from langchain.tools import tool

from rosa_agent.config import RUNTIME_DIR, ros_setup_path, workspace_root


LOG_DIR = RUNTIME_DIR / "logs"
PID_DIR = RUNTIME_DIR / "pids"

LOG_DIR.mkdir(parents=True, exist_ok=True)
PID_DIR.mkdir(parents=True, exist_ok=True)

DENY_WORDS = [
    "sudo",
    "rm",
    "shutdown",
    "reboot",
    "mkfs",
    "dd",
    "chmod 777",
    ";",
    "&&",
    "|",
    "`",
    "$(",
]


def _has_dangerous_text(command: str) -> bool:
    return any(bad in command for bad in DENY_WORDS)


def _safe_name(parts):
    raw = "_".join(parts)
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in raw)
    return safe[:120] or "ros2_process"


def _ros_command(args) -> str:
    return f"source {shlex.quote(ros_setup_path())} && {shlex.join(args)}"


def _call_robot_start_task(task_type: str, target: str = "", text: str = "") -> str:
    yaml_text = (
        "{"
        f"task_type: {shlex.quote(task_type)}, "
        f"target: {shlex.quote(target)}, "
        f"text: {shlex.quote(text)}"
        "}"
    )
    return run_ros2_command.invoke(
        {
            "command": (
                "ros2 service call /robot_server/start_task "
                "task_manager_interfaces/srv/StartTask "
                f"{shlex.quote(yaml_text)}"
            )
        }
    )


def _call_robot_trigger(service_name: str) -> str:
    return run_ros2_command.invoke(
        {
            "command": (
                f"ros2 service call {service_name} "
                "std_srvs/srv/Trigger {}"
            )
        }
    )


def _call_robot_query_state() -> str:
    return run_ros2_command.invoke(
        {
            "command": (
                "ros2 service call /robot_server/query_robot_state "
                "task_manager_interfaces/srv/QueryRobotState {}"
            )
        }
    )


def _weather_code_text(code: int) -> str:
    weather_codes = {
        0: "晴",
        1: "大部晴朗",
        2: "局部多云",
        3: "阴",
        45: "雾",
        48: "雾凇",
        51: "小毛毛雨",
        53: "中等毛毛雨",
        55: "较强毛毛雨",
        56: "冻毛毛雨",
        57: "较强冻毛毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        66: "冻雨",
        67: "较强冻雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        77: "雪粒",
        80: "小阵雨",
        81: "中等阵雨",
        82: "强阵雨",
        85: "小阵雪",
        86: "强阵雪",
        95: "雷暴",
        96: "雷暴伴小冰雹",
        99: "雷暴伴强冰雹",
    }
    return weather_codes.get(code, "未知天气")


def _weather_advice(hourly: dict, location_name: str) -> str:
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    precip_probs = hourly.get("precipitation_probability", [])
    precip = hourly.get("precipitation", [])
    weather_codes = hourly.get("weather_code", [])
    winds = hourly.get("wind_speed_10m", [])

    if not times:
        return f"没有查到 {location_name} 的逐小时天气。"

    window = min(6, len(times))
    max_rain_prob = max((precip_probs[i] or 0) for i in range(window)) if precip_probs else 0
    total_precip = sum((precip[i] or 0.0) for i in range(window)) if precip else 0.0
    max_wind = max((winds[i] or 0.0) for i in range(window)) if winds else 0.0
    min_temp = min((temps[i] for i in range(window) if temps[i] is not None), default=None)
    max_temp = max((temps[i] for i in range(window) if temps[i] is not None), default=None)
    current_code = int(weather_codes[0]) if weather_codes else -1

    suggestions = []
    if max_rain_prob >= 60 or total_precip >= 1.0:
        suggestions.append("接下来几小时有明显降雨风险，建议收衣服、关窗，老人尽量不要外出。")
    elif max_rain_prob >= 30:
        suggestions.append("接下来几小时可能有雨，外出建议带伞，阳台衣物最好提前收一下。")
    else:
        suggestions.append("短时间内降雨风险不高，可以正常安排室内外活动。")

    if min_temp is not None and min_temp <= 10:
        suggestions.append("气温偏低，提醒老人加衣保暖。")
    if max_temp is not None and max_temp >= 30:
        suggestions.append("气温偏高，注意补水，避免长时间户外活动。")
    if max_wind >= 30:
        suggestions.append("风比较大，外出要注意安全，阳台轻物需要固定。")

    temp_text = "未知"
    if min_temp is not None and max_temp is not None:
        temp_text = f"{min_temp:.0f}-{max_temp:.0f}℃"

    return (
        f"{location_name} 当前天气：{_weather_code_text(current_code)}。\n"
        f"未来 {window} 小时气温约 {temp_text}，最高降雨概率 {max_rain_prob:.0f}%，"
        f"累计降水约 {total_precip:.1f}mm，最大风速约 {max_wind:.0f}km/h。\n"
        f"建议：{' '.join(suggestions)}"
    )


def _resolve_workspace_path(path_text: str) -> Path:
    root = workspace_root()
    raw = Path(path_text).expanduser()

    if not raw.is_absolute():
        raw = root / raw

    resolved = raw.resolve()

    if os.path.commonpath([root, resolved]) != str(root):
        raise ValueError(f"Path outside workspace is not allowed: {resolved}")

    return resolved


@tool
def run_ros2_command(command: str) -> str:
    """
    Run a short, safe ROS2 command and return its output.

    Allowed examples:
    ros2 service call <service> <type> <yaml>
    ros2 topic pub --once <topic> <type> <yaml>
    ros2 param set <node> <param> <value>
    ros2 node list
    ros2 topic list

    Do not use this for long-running commands such as ros2 run or ros2 launch.
    For long-running launch files, use launch_ros2_file instead.
    """
    if _has_dangerous_text(command):
        return f"Rejected unsafe command: {command}"

    args = shlex.split(command)

    if not args or args[0] != "ros2":
        return "Rejected. Command must start with ros2."

    short_allowed = [
        ["ros2", "node"],
        ["ros2", "topic"],
        ["ros2", "service"],
        ["ros2", "param"],
        ["ros2", "action"],
        ["ros2", "doctor"],
        ["ros2", "interface"],
    ]

    if not any(args[:len(prefix)] == prefix for prefix in short_allowed):
        return (
            "Rejected. run_ros2_command only supports short ROS2 inspection/control commands. "
            "Use launch_ros2_file for ros2 launch."
        )

    try:
        result = subprocess.run(
            ["bash", "-lc", _ros_command(args)],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return (
            f"exit_code={result.returncode}\n"
            f"stdout:\n{result.stdout[-4000:]}\n"
            f"stderr:\n{result.stderr[-4000:]}"
        )
    except subprocess.TimeoutExpired:
        return (
            "Command timed out after 20 seconds. "
            "For long-running processes, use launch_ros2_file."
        )


@tool
def start_wakeup_task(_: str = "") -> str:
    """
    Start the high-level wake-up task through the robot server.

    The robot server owns the state machine, named-place lookup, Nav2 call,
    and arrival speech.
    """
    return _call_robot_start_task("wake_up", "bedroom_bedside", "")


@tool
def navigate_to_named_place(place_name: str) -> str:
    """
    Ask the robot server to navigate to a named place.

    Valid place_name values in the current map:
    bedroom_bedside, livingroom_sofa, charger, kitchen.

    Use charger for requests such as returning to charge or going back to the
    charging dock. Do not invent names such as charger_front unless the map
    contains that exact key.
    """
    return _call_robot_start_task("navigate", place_name.strip(), "")


@tool
def speak_text(text: str) -> str:
    """
    Ask the robot server to speak one sentence.
    """
    return _call_robot_start_task("speak", "", text.strip())


@tool
def start_following_task(_: str = "") -> str:
    """
    Ask the robot server to enter FOLLOWING mode.

    The follower_controller only executes following while robot_mode is FOLLOWING.
    """
    return _call_robot_start_task("follow", "", "")


@tool
def start_inspection_task(_: str = "") -> str:
    """
    Ask the robot server to start the active inspection task.
    """
    return _call_robot_start_task("inspection", "", "")


@tool
def cancel_current_task(_: str = "") -> str:
    """
    Cancel the robot server's current high-level task.
    """
    return _call_robot_trigger("/robot_server/cancel_current_task")


@tool
def query_robot_state(_: str = "") -> str:
    """
    Query the robot server mode, active task, target, navigation flag, and last error.
    """
    return _call_robot_query_state()


@tool
def get_weather_advice(location: str) -> str:
    """
    Query current and near-term weather for a location, then give caregiving advice.

    Input should be a city or district name, for example:
    Beijing
    Shanghai
    Hangzhou
    """
    query = location.strip() or "Beijing"
    try:
        geo_response = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": query, "count": 1, "language": "zh", "format": "json"},
            timeout=8,
        )
        geo_response.raise_for_status()
        results = geo_response.json().get("results", [])
        if not results:
            return f"没有找到地点：{query}。请换一个城市或区县名称。"

        place = results[0]
        latitude = place["latitude"]
        longitude = place["longitude"]
        location_name = place.get("name", query)
        admin = place.get("admin1")
        country = place.get("country")
        if admin and admin != location_name:
            location_name = f"{admin}{location_name}"
        if country:
            location_name = f"{country}{location_name}"

        forecast_response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "hourly": [
                    "temperature_2m",
                    "precipitation_probability",
                    "precipitation",
                    "weather_code",
                    "wind_speed_10m",
                ],
                "forecast_days": 1,
                "timezone": "auto",
            },
            timeout=8,
        )
        forecast_response.raise_for_status()
        hourly = forecast_response.json().get("hourly", {})
        return _weather_advice(hourly, location_name)
    except requests.RequestException as exc:
        return f"天气查询失败：{exc}"


@tool
def launch_ros2_file(command: str) -> str:
    """
    Start a ROS2 launch command in the background.

    Input must be a ros2 launch command, for example:
    ros2 launch base_controller mapping.launch.py
    ros2 launch /home/pan/Intelligent_robot/src/rosa_agent/launch/demo_with_rviz.launch.py
    """
    if _has_dangerous_text(command):
        return f"Rejected unsafe command: {command}"

    args = shlex.split(command)

    if len(args) < 3 or args[0:2] != ["ros2", "launch"]:
        return "Rejected. Command must start with: ros2 launch"

    return _start_background_process(args, "Started launch command.")


@tool
def start_ros2_node(command: str) -> str:
    """
    Start a long-running ROS2 node in the background.

    Input must be a ros2 run command, for example:
    ros2 run demo_nodes_cpp talker
    ros2 run turtlesim turtlesim_node
    """
    if _has_dangerous_text(command):
        return f"Rejected unsafe command: {command}"

    args = shlex.split(command)

    if len(args) < 4 or args[0:2] != ["ros2", "run"]:
        return "Rejected. Command must start with: ros2 run"

    return _start_background_process(args, "Started ROS2 node.")


def _start_background_process(args, message: str) -> str:
    name = _safe_name(args[2:])
    log_path = LOG_DIR / f"{name}.log"
    pid_path = PID_DIR / f"{name}.pid"

    log_file = open(log_path, "a", encoding="utf-8")
    process = subprocess.Popen(
        ["bash", "-lc", _ros_command(args)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )

    pid_path.write_text(str(process.pid), encoding="utf-8")

    return (
        f"{message}\n"
        f"Name: {name}\n"
        f"PID: {process.pid}\n"
        f"Log: {log_path}\n"
        f"Command: {shlex.join(args)}"
    )


@tool
def stop_ros2_process(name_or_pid: str) -> str:
    """
    Stop a ROS2 process previously started by launch_ros2_file or start_ros2_node.

    Input can be:
    - a PID number
    - a process name returned by the start tool
    - part of a PID filename under runtime/rosa_agent/pids
    """
    target = name_or_pid.strip()

    if target.isdigit():
        pid = int(target)
    else:
        candidates = list(PID_DIR.glob(f"*{target}*.pid"))
        if not candidates:
            known = ", ".join(path.stem for path in PID_DIR.glob("*.pid")) or "none"
            return f"No PID file found for: {target}\nKnown processes: {known}"
        pid = int(candidates[0].read_text(encoding="utf-8").strip())

    try:
        os.killpg(pid, signal.SIGTERM)
        return f"Stop requested for process group PID: {pid}"
    except ProcessLookupError:
        try:
            os.kill(pid, signal.SIGTERM)
            return f"Stop requested for PID: {pid}"
        except ProcessLookupError:
            return f"Process is not running: {pid}"
    except PermissionError as exc:
        return f"Permission denied stopping PID {pid}: {exc}"


@tool
def list_started_ros2_processes(_: str = "") -> str:
    """
    List ROS2 launch files or nodes started by this toolset.
    """
    entries = []
    for pid_file in sorted(PID_DIR.glob("*.pid")):
        pid = pid_file.read_text(encoding="utf-8").strip()
        log_path = LOG_DIR / f"{pid_file.stem}.log"
        alive = subprocess.run(
            ["bash", "-lc", f"kill -0 {shlex.quote(pid)}"],
            capture_output=True,
            text=True,
        ).returncode == 0
        entries.append(
            f"name={pid_file.stem}\npid={pid}\nalive={alive}\nlog={log_path}"
        )

    return "\n\n".join(entries) if entries else "No ROS2 processes started by this toolset."


@tool
def write_workspace_file(path_and_content: str) -> str:
    """
    Write a file inside the ROSA workspace.

    Input format:
    First line: file path relative to workspace, or absolute path under workspace.
    Remaining lines: file content.
    """
    lines = path_and_content.splitlines()

    if len(lines) < 2:
        return "Rejected. Input must contain a path on the first line and file content after it."

    try:
        path = _resolve_workspace_path(lines[0].strip())
    except ValueError as exc:
        return str(exc)

    content = "\n".join(lines[1:]) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    return f"Wrote file: {path}"


@tool
def read_workspace_file(path_text: str) -> str:
    """
    Read a text file inside the ROSA workspace.
    """
    try:
        path = _resolve_workspace_path(path_text.strip())
    except ValueError as exc:
        return str(exc)

    if not path.exists():
        return f"File does not exist: {path}"

    if path.is_dir():
        return f"Path is a directory: {path}"

    return path.read_text(encoding="utf-8")[-8000:]


@tool
def list_workspace_files(path_text: str = ".") -> str:
    """
    List files inside the ROSA workspace.
    """
    try:
        path = _resolve_workspace_path(path_text.strip() or ".")
    except ValueError as exc:
        return str(exc)

    if not path.exists():
        return f"Path does not exist: {path}"

    if path.is_file():
        return str(path)

    entries = []
    for child in sorted(path.iterdir()):
        kind = "dir " if child.is_dir() else "file"
        entries.append(f"{kind} {child}")

    return "\n".join(entries) if entries else f"Directory is empty: {path}"


DEFAULT_TOOLS = [
    start_wakeup_task,
    navigate_to_named_place,
    speak_text,
    start_following_task,
    start_inspection_task,
    get_weather_advice,
    cancel_current_task,
    query_robot_state,
]
