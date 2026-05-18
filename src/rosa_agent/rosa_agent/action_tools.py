import os
import shlex
import signal
import subprocess
from pathlib import Path

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
    run_ros2_command,
    launch_ros2_file,
    start_ros2_node,
    stop_ros2_process,
    list_started_ros2_processes,
    write_workspace_file,
    read_workspace_file,
    list_workspace_files,
]

