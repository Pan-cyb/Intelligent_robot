import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import rclpy
import yaml
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PointStamped, Quaternion
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.task import Future
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger
from task_manager_interfaces.srv import QueryRobotState, StartTask


class RobotMode(Enum):
    IDLE = "IDLE"
    SCHEDULED_TASK = "SCHEDULED_TASK"
    NAVIGATION = "NAVIGATION"
    CONVERSATION = "CONVERSATION"
    FOLLOWING = "FOLLOWING"
    INSPECTION = "INSPECTION"
    EMERGENCY = "EMERGENCY"
    MANUAL = "MANUAL"
    FAULT = "FAULT"


@dataclass(frozen=True)
class NamedLocation:
    name: str
    frame_id: str
    x: float
    y: float
    yaw: float


@dataclass(frozen=True)
class RobotTask:
    task_id: str
    task_type: str
    location_name: str
    speech_text: str


class TaskManagerNode(Node):
    def __init__(self) -> None:
        super().__init__("task_manager")

        self.declare_parameter("locations_file", "")
        self.declare_parameter("navigate_action_name", "navigate_to_pose")
        self.declare_parameter("tts_topic", "/tts_text")
        self.declare_parameter("task_command_topic", "/task_command")
        self.declare_parameter("mode_topic", "/robot_mode")
        self.declare_parameter("navigation_timeout_sec", 90.0)
        self.declare_parameter("navigation_retry_limit", 1)
        self.declare_parameter("tts_wait_sec", 5.0)
        self.declare_parameter("auto_start_demo", False)
        self.declare_parameter("demo_start_delay_sec", 10.0)
        self.declare_parameter("fault_on_navigation_failure", True)
        self.declare_parameter("fall_confirm_frames", 5)
        self.declare_parameter("observe_duration_sec", 5.0)
        self.declare_parameter("person_seen_timeout_sec", 1.0)
        self.declare_parameter(
            "inspection_points",
            ["livingroom_sofa", "bedroom_bedside", "kitchen"],
        )

        self._mode = RobotMode.IDLE
        self._active_task: RobotTask | None = None
        self._active_location: NamedLocation | None = None
        self._goal_handle = None
        self._nav_goal_generation = 0
        self._active_nav_goal_generation = 0
        self._navigation_started_at = None
        self._navigation_retry_count = 0
        self._conversation_timer = None
        self._inspection_observe_timer = None
        self._cancel_requested = False
        self._last_error = ""
        self._emergency_reason = ""
        self._fall_true_count = 0
        self._fall_confirm_frames = int(self.get_parameter("fall_confirm_frames").value)
        self._observe_duration_sec = float(self.get_parameter("observe_duration_sec").value)
        self._person_seen_timeout_sec = float(self.get_parameter("person_seen_timeout_sec").value)
        self._last_person_seen_at = None
        self._inspection_points = [
            str(name)
            for name in self.get_parameter("inspection_points").value
        ]
        self._inspection_index = 0

        self._locations = self._load_locations()
        self._nav_timeout = Duration(
            seconds=float(self.get_parameter("navigation_timeout_sec").value)
        )
        self._retry_limit = int(self.get_parameter("navigation_retry_limit").value)
        self._fault_on_navigation_failure = bool(
            self.get_parameter("fault_on_navigation_failure").value
        )

        action_name = str(self.get_parameter("navigate_action_name").value)
        self._navigate_client = ActionClient(self, NavigateToPose, action_name)

        tts_topic = str(self.get_parameter("tts_topic").value)
        self._tts_pub = self.create_publisher(String, tts_topic, 10)

        mode_topic = str(self.get_parameter("mode_topic").value)
        self._mode_pub = self.create_publisher(String, mode_topic, 10)

        command_topic = str(self.get_parameter("task_command_topic").value)
        self.create_subscription(String, command_topic, self._on_task_command, 10)
        self.create_subscription(Bool, "/fall_detected", self._on_fall_detected, 10)
        self.create_subscription(PointStamped, "/person_position", self._on_person_position, 10)

        self.create_service(Trigger, "trigger_wakeup_task", self._on_trigger_wakeup)
        self.create_service(Trigger, "cancel_task", self._on_cancel_task)
        self.create_service(Trigger, "clear_fault", self._on_clear_fault)
        self.create_service(Trigger, "clear_emergency", self._on_clear_emergency)
        self.create_service(StartTask, "/robot_server/start_task", self._on_start_task)
        self.create_service(Trigger, "/robot_server/start_wakeup_task", self._on_robot_start_wakeup)
        self.create_service(Trigger, "/robot_server/cancel_current_task", self._on_cancel_task)
        self.create_service(Trigger, "/robot_server/clear_emergency", self._on_clear_emergency)
        self.create_service(QueryRobotState, "/robot_server/query_robot_state", self._on_query_robot_state)

        self._watchdog_timer = self.create_timer(1.0, self._watchdog)
        self._publish_mode()

        if bool(self.get_parameter("auto_start_demo").value):
            delay = float(self.get_parameter("demo_start_delay_sec").value)
            self._demo_timer = self.create_timer(delay, self._auto_start_demo_once)
        else:
            self._demo_timer = None

        self.get_logger().info(
            "Task manager ready. mode=IDLE, locations=%s, high-level API: "
            "`ros2 service call /robot_server/start_task "
            "task_manager_interfaces/srv/StartTask "
            "\"{task_type: 'wake_up', target: 'bedroom_bedside', text: ''}\"`. "
            "Legacy command topic still subscribed at %s."
            % (sorted(self._locations.keys()), command_topic)
        )

    def _load_locations(self) -> dict[str, NamedLocation]:
        locations_file = str(self.get_parameter("locations_file").value)
        if not locations_file:
            raise RuntimeError("Parameter locations_file is required.")

        path = Path(locations_file).expanduser()
        if not path.exists():
            raise RuntimeError(f"Named locations file does not exist: {path}")

        with path.open("r", encoding="utf-8") as file:
            raw = yaml.safe_load(file) or {}

        locations_raw: dict[str, Any] = raw.get("locations", {})
        if not locations_raw:
            raise RuntimeError(f"No locations found in {path}")

        locations: dict[str, NamedLocation] = {}
        for name, value in locations_raw.items():
            x, y, yaw = self._parse_location_pose(name, value)
            locations[name] = NamedLocation(
                name=name,
                frame_id=str(value.get("frame_id", "map")),
                x=x,
                y=y,
                yaw=yaw,
            )
        return locations

    def _parse_location_pose(self, name: str, value: dict[str, Any]) -> tuple[float, float, float]:
        if "position" in value:
            position = value["position"]
            orientation = value.get("orientation", {})
            return (
                float(position["x"]),
                float(position["y"]),
                self._quaternion_to_yaw(
                    float(orientation.get("x", 0.0)),
                    float(orientation.get("y", 0.0)),
                    float(orientation.get("z", 0.0)),
                    float(orientation.get("w", 1.0)),
                ),
            )

        if "x" in value and "y" in value:
            return (
                float(value["x"]),
                float(value["y"]),
                float(value.get("yaw", 0.0)),
            )

        raise RuntimeError(
            "Invalid location format for %s. Expected x/y/yaw or position/orientation."
            % name
        )

    def _auto_start_demo_once(self) -> None:
        if self._demo_timer is not None:
            self._demo_timer.cancel()
            self._demo_timer = None
        self._start_wakeup_task(source="demo_timer")

    def _on_trigger_wakeup(self, _request, response):
        accepted, message = self._start_wakeup_task(source="legacy_service")
        response.success = accepted
        response.message = message
        return response

    def _on_robot_start_wakeup(self, _request, response):
        accepted, message = self._start_wakeup_task(source="service:/robot_server/start_wakeup_task")
        response.success = accepted
        response.message = message
        return response

    def _on_start_task(self, request, response):
        accepted, message = self._start_task(
            task_type=request.task_type,
            target=request.target,
            text=request.text,
            source="service:/robot_server/start_task",
        )
        response.success = accepted
        response.message = message
        return response

    def _on_query_robot_state(self, _request, response):
        response.mode = self._mode.value
        response.current_task = self._active_task.task_id if self._active_task else ""
        response.target = self._active_task.location_name if self._active_task else ""
        response.is_navigating = self._mode == RobotMode.NAVIGATION and self._goal_handle is not None
        response.last_error = self._last_error
        return response

    def _on_cancel_task(self, _request, response):
        accepted, message = self._cancel_current_task("service")
        response.success = accepted
        response.message = message
        return response

    def _on_clear_fault(self, _request, response):
        if self._mode != RobotMode.FAULT:
            response.success = False
            response.message = f"Robot is not in FAULT, current mode={self._mode.value}"
            return response
        self._reset_task()
        self._set_mode(RobotMode.IDLE, "fault cleared by service")
        response.success = True
        response.message = "Fault cleared."
        return response

    def _on_clear_emergency(self, _request, response):
        if self._mode not in {RobotMode.EMERGENCY, RobotMode.FAULT}:
            response.success = False
            response.message = f"Robot is not in EMERGENCY/FAULT, current mode={self._mode.value}"
            return response
        self._reset_task()
        self._last_error = ""
        self._emergency_reason = ""
        self._fall_true_count = 0
        self._set_mode(RobotMode.IDLE, "emergency cleared by service")
        response.success = True
        response.message = "Emergency cleared."
        return response

    def _on_person_position(self, _msg: PointStamped) -> None:
        self._last_person_seen_at = self.get_clock().now()

    def _on_fall_detected(self, msg: Bool) -> None:
        if msg.data:
            self._fall_true_count += 1
        else:
            self._fall_true_count = 0
            return

        if self._fall_true_count < self._fall_confirm_frames:
            return

        self._fall_true_count = 0
        self._enter_emergency("fall_detected confirmed")

    def _on_task_command(self, msg: String) -> None:
        # Legacy compatibility only. New ROSA/LLM control should call
        # /robot_server/start_task so task_type/target/text stay explicit.
        command = msg.data.strip().lower()
        if command in {"wakeup_bedroom", "wake_up_bedroom", "去卧室叫醒", "叫醒老人"}:
            self._start_wakeup_task(source=f"topic:{command}")
        elif command in {"cancel", "取消任务"}:
            self._cancel_current_task(f"topic:{command}")
        else:
            self.get_logger().warn(
                "Unknown legacy task command ignored: %s. Use /robot_server/start_task "
                "for wake_up, navigate, and speak tasks." % msg.data
            )

    def _start_wakeup_task(self, source: str) -> tuple[bool, str]:
        return self._start_task(
            task_type="wake_up",
            target="bedroom_bedside",
            text="",
            source=source,
        )

    def _start_task(
        self, task_type: str, target: str = "", text: str = "", source: str = "unknown"
    ) -> tuple[bool, str]:
        if self._mode != RobotMode.IDLE:
            message = "Reject %s task from %s: robot is busy, mode=%s, current_task=%s" % (
                task_type,
                source,
                self._mode.value,
                self._active_task.task_id if self._active_task else "",
            )
            self.get_logger().warn(message)
            return False, message

        task_type = task_type.strip().lower()
        target = target.strip()
        text = text.strip()

        if task_type in {"wake_up", "wakeup"}:
            target = target or "bedroom_bedside"
            if target not in self._locations:
                return self._reject_invalid_task("Unknown named location: %s" % target)
            task = RobotTask(
                task_id="wake_up",
                task_type="wake_up",
                location_name=target,
                speech_text=text or "早上好，该起床了。",
            )
            self._accept_task(task, RobotMode.SCHEDULED_TASK, source)
            self._dispatch_navigation_task()
            return True, "Wakeup task accepted."

        if task_type == "navigate":
            if not target:
                return self._reject_invalid_task("Navigate task requires target.")
            if target not in self._locations:
                return self._reject_invalid_task("Unknown named location: %s" % target)
            task = RobotTask(
                task_id="navigate:%s" % target,
                task_type="navigate",
                location_name=target,
                speech_text="",
            )
            self._accept_task(task, RobotMode.NAVIGATION, source)
            self._dispatch_navigation_task()
            return True, "Navigate task accepted: %s" % target

        if task_type == "speak":
            if not text:
                return self._reject_invalid_task("Speak task requires text.")
            task = RobotTask(
                task_id="speak",
                task_type="speak",
                location_name="",
                speech_text=text,
            )
            self._accept_task(task, RobotMode.CONVERSATION, source)
            self._start_conversation()
            return True, "Speak task accepted."

        if task_type == "follow":
            task = RobotTask(
                task_id="follow",
                task_type="follow",
                location_name="",
                speech_text="",
            )
            self._accept_task(task, RobotMode.FOLLOWING, source)
            return True, "Follow task accepted."

        if task_type == "inspection":
            task = RobotTask(
                task_id="inspection",
                task_type="inspection",
                location_name="",
                speech_text="",
            )
            self._accept_task(task, RobotMode.INSPECTION, source)
            if not self._inspection_points:
                self._finish_inspection(False)
                return True, "Inspection task accepted, but no inspection points configured."
            self._inspection_index = 0
            self._dispatch_next_inspection_point()
            return True, "Inspection task accepted."

        return self._reject_invalid_task("Unknown task_type: %s" % task_type)

    def _accept_task(self, task: RobotTask, initial_mode: RobotMode, source: str) -> None:
        task = RobotTask(
            task_id=task.task_id,
            task_type=task.task_type,
            location_name=task.location_name,
            speech_text=task.speech_text,
        )
        self._active_task = task
        self._navigation_retry_count = 0
        self._cancel_requested = False
        self._last_error = ""
        self._set_mode(initial_mode, "accepted task %s from %s" % (task.task_id, source))

    def _reject_invalid_task(self, message: str) -> tuple[bool, str]:
        self._last_error = message
        self.get_logger().warn(message)
        return False, message

    def _dispatch_navigation_task(self) -> None:
        if self._active_task is None:
            self._fail_task("No active task to dispatch.")
            return

        location = self._locations.get(self._active_task.location_name)
        if location is None:
            self._fail_task("Unknown named location: %s" % self._active_task.location_name)
            return

        self._active_location = location
        self.get_logger().info(
            "Task %s target=%s pose=(%.2f, %.2f, yaw=%.2f rad, frame=%s)"
            % (
                self._active_task.task_id,
                location.name,
                location.x,
                location.y,
                location.yaw,
                location.frame_id,
            )
        )
        self._send_navigation_goal(location)

    def _send_navigation_goal(self, location: NamedLocation) -> None:
        if not self._navigate_client.wait_for_server(timeout_sec=2.0):
            self._handle_navigation_failure("NavigateToPose action server is not available.")
            return

        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = location.frame_id
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = location.x
        goal.pose.pose.position.y = location.y
        goal.pose.pose.orientation = self._yaw_to_quaternion(location.yaw)

        self._navigation_started_at = self.get_clock().now()
        if self._mode != RobotMode.INSPECTION:
            self._set_mode(
                RobotMode.NAVIGATION,
                "sending Nav2 goal to %s, attempt %d/%d"
                % (location.name, self._navigation_retry_count + 1, self._retry_limit + 1),
            )
        else:
            self._publish_mode()

        self._nav_goal_generation += 1
        goal_generation = self._nav_goal_generation
        self._active_nav_goal_generation = goal_generation
        future = self._navigate_client.send_goal_async(goal)
        future.add_done_callback(
            lambda future, generation=goal_generation: self._on_goal_response(future, generation)
        )

    def _on_goal_response(self, future: Future, generation: int) -> None:
        if generation != self._active_nav_goal_generation:
            self.get_logger().info("Stale Nav2 goal response ignored.")
            return
        if self._active_task is None and self._mode not in {
            RobotMode.INSPECTION,
            RobotMode.NAVIGATION,
            RobotMode.SCHEDULED_TASK,
        }:
            self.get_logger().info("Nav2 goal response ignored with no active navigation task.")
            return

        goal_handle = future.result()
        if not goal_handle.accepted:
            self._handle_navigation_failure("Nav2 rejected navigation goal.")
            return

        self._goal_handle = goal_handle
        self.get_logger().info("Nav2 accepted navigation goal.")
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            lambda future, generation=generation: self._on_navigation_result(future, generation)
        )

    def _on_navigation_result(self, future: Future, generation: int) -> None:
        if generation != self._active_nav_goal_generation:
            self.get_logger().info("Stale Nav2 result ignored.")
            return
        if self._active_task is None:
            self.get_logger().info("Navigation result received with no active task; ignoring.")
            return

        result = future.result()
        self._goal_handle = None
        if result.status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info("Navigation succeeded.")
            if self._active_task and self._active_task.task_type == "inspection":
                self._start_inspection_observation()
                return
            if self._active_task and self._active_task.task_type == "navigate":
                task_id = self._active_task.task_id
                self._reset_task()
                self._set_mode(RobotMode.IDLE, "navigation task %s completed" % task_id)
            else:
                self._start_conversation()
            return

        status_name = self._goal_status_name(result.status)
        self._handle_navigation_failure("Navigation finished with status=%s" % status_name)

    def _watchdog(self) -> None:
        if self._mode not in {RobotMode.NAVIGATION, RobotMode.INSPECTION}:
            return
        if self._goal_handle is None or self._navigation_started_at is None:
            return

        elapsed = self.get_clock().now() - self._navigation_started_at
        if elapsed <= self._nav_timeout:
            return

        self.get_logger().warn(
            "Navigation timeout after %.1fs." % (elapsed.nanoseconds / 1e9)
        )
        if self._goal_handle is not None:
            self._goal_handle.cancel_goal_async()
            self._goal_handle = None
        self._handle_navigation_failure("Navigation timed out.")

    def _handle_navigation_failure(self, reason: str) -> None:
        self.get_logger().warn("%s retry=%d/%d" % (reason, self._navigation_retry_count, self._retry_limit))
        if self._active_task and self._active_task.task_type == "inspection":
            self.get_logger().warn("Inspection point failed, continuing: %s" % reason)
            self._navigation_retry_count = 0
            self._inspection_index += 1
            self._dispatch_next_inspection_point()
            return

        if self._active_location is not None and self._navigation_retry_count < self._retry_limit:
            self._navigation_retry_count += 1
            self._send_navigation_goal(self._active_location)
            return

        if self._fault_on_navigation_failure:
            self._fail_task(reason)
        else:
            self.get_logger().warn("Task failed, returning to IDLE: %s" % reason)
            self._reset_task()
            self._set_mode(RobotMode.IDLE, "navigation failed")

    def _dispatch_next_inspection_point(self) -> None:
        while self._inspection_index < len(self._inspection_points):
            location_name = self._inspection_points[self._inspection_index]
            if location_name not in self._locations:
                self.get_logger().warn("Unknown inspection point skipped: %s" % location_name)
                self._inspection_index += 1
                continue

            self._active_location = self._locations[location_name]
            self._navigation_retry_count = 0
            self.get_logger().info(
                "Inspection navigating to %s (%d/%d)"
                % (location_name, self._inspection_index + 1, len(self._inspection_points))
            )
            self._send_navigation_goal(self._active_location)
            return

        self._finish_inspection(False)

    def _start_inspection_observation(self) -> None:
        self._set_mode(RobotMode.INSPECTION, "observing inspection point")
        point_name = self._inspection_points[self._inspection_index]
        self.get_logger().info(
            "Observing inspection point %s for %.1fs"
            % (point_name, self._observe_duration_sec)
        )
        if self._inspection_observe_timer is not None:
            self._inspection_observe_timer.cancel()
        self._inspection_observe_timer = self.create_timer(
            self._observe_duration_sec,
            self._finish_inspection_observation_once,
        )

    def _finish_inspection_observation_once(self) -> None:
        if self._inspection_observe_timer is not None:
            self._inspection_observe_timer.cancel()
            self._inspection_observe_timer = None
        if self._mode != RobotMode.INSPECTION:
            return
        if self._person_seen_recently():
            self._finish_inspection(True)
            return
        self._inspection_index += 1
        self._dispatch_next_inspection_point()

    def _person_seen_recently(self) -> bool:
        if self._last_person_seen_at is None:
            return False
        elapsed = self.get_clock().now() - self._last_person_seen_at
        return elapsed <= Duration(seconds=self._person_seen_timeout_sec)

    def _finish_inspection(self, found_person: bool) -> None:
        text = "我看到您了。" if found_person else "我没有找到您。"
        self._tts_pub.publish(String(data=text))
        self.get_logger().info("Inspection finished. found_person=%s" % found_person)
        self._reset_task()
        self._set_mode(RobotMode.IDLE, "inspection finished")

    def _start_conversation(self) -> None:
        if self._active_task is None:
            self._fail_task("Conversation requested but no active task exists.")
            return

        self._set_mode(RobotMode.CONVERSATION, "publishing TTS text")
        self._tts_pub.publish(String(data=self._active_task.speech_text))
        self.get_logger().info("Published TTS text: %s" % self._active_task.speech_text)

        wait_sec = float(self.get_parameter("tts_wait_sec").value)
        self._conversation_timer = self.create_timer(wait_sec, self._finish_conversation_once)

    def _finish_conversation_once(self) -> None:
        if self._conversation_timer is not None:
            self._conversation_timer.cancel()
            self._conversation_timer = None
        if self._mode != RobotMode.CONVERSATION:
            return
        self.get_logger().info("Task %s completed." % self._active_task.task_id)
        self._reset_task()
        self._set_mode(RobotMode.IDLE, "conversation finished")

    def _cancel_current_task(self, source: str) -> tuple[bool, str]:
        if self._mode == RobotMode.IDLE:
            return False, "No active task to cancel."

        self._cancel_requested = True
        if self._goal_handle is not None:
            self._goal_handle.cancel_goal_async()
            self._goal_handle = None
            self.get_logger().info("Cancel requested by %s; Nav2 goal cancelled." % source)
        else:
            self.get_logger().info("Cancel requested by %s." % source)

        if self._conversation_timer is not None:
            self._conversation_timer.cancel()
            self._conversation_timer = None
        if self._inspection_observe_timer is not None:
            self._inspection_observe_timer.cancel()
            self._inspection_observe_timer = None

        self._reset_task()
        self._last_error = ""
        self._set_mode(RobotMode.IDLE, "task cancelled by %s" % source)
        return True, "Task cancelled."

    def _enter_emergency(self, reason: str) -> None:
        if self._mode == RobotMode.EMERGENCY:
            return

        self.get_logger().error("Emergency confirmed: %s" % reason)
        self._cancel_requested = True
        if self._goal_handle is not None:
            self._goal_handle.cancel_goal_async()
            self._goal_handle = None
            self.get_logger().info("Active Nav2 goal cancelled for emergency.")
        if self._conversation_timer is not None:
            self._conversation_timer.cancel()
            self._conversation_timer = None
        if self._inspection_observe_timer is not None:
            self._inspection_observe_timer.cancel()
            self._inspection_observe_timer = None

        self._reset_task()
        self._emergency_reason = reason
        self._last_error = reason
        self._set_mode(RobotMode.EMERGENCY, reason)
        self._tts_pub.publish(String(data="检测到异常，您是否需要帮助？"))

    def _fail_task(self, reason: str) -> None:
        self.get_logger().error("Task failed: %s" % reason)
        self._last_error = reason
        self._reset_task()
        self._set_mode(RobotMode.FAULT, reason)

    def _reset_task(self) -> None:
        self._active_task = None
        self._active_location = None
        self._goal_handle = None
        self._active_nav_goal_generation = 0
        self._navigation_started_at = None
        self._navigation_retry_count = 0
        self._cancel_requested = False
        self._inspection_index = 0

    def _set_mode(self, mode: RobotMode, reason: str) -> None:
        if self._mode == mode:
            self.get_logger().info("Mode remains %s: %s" % (mode.value, reason))
            self._publish_mode()
            return
        old = self._mode
        self._mode = mode
        self.get_logger().info("Mode %s -> %s: %s" % (old.value, mode.value, reason))
        self._publish_mode()

    def _publish_mode(self) -> None:
        self._mode_pub.publish(String(data=self._mode.value))

    @staticmethod
    def _yaw_to_quaternion(yaw: float) -> Quaternion:
        q = Quaternion()
        q.z = math.sin(yaw / 2.0)
        q.w = math.cos(yaw / 2.0)
        return q

    @staticmethod
    def _quaternion_to_yaw(x: float, y: float, z: float, w: float) -> float:
        siny_cosp = 2.0 * (w * z + x * y)
        cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
        return math.atan2(siny_cosp, cosy_cosp)

    @staticmethod
    def _goal_status_name(status: int) -> str:
        names = {
            GoalStatus.STATUS_UNKNOWN: "UNKNOWN",
            GoalStatus.STATUS_ACCEPTED: "ACCEPTED",
            GoalStatus.STATUS_EXECUTING: "EXECUTING",
            GoalStatus.STATUS_CANCELING: "CANCELING",
            GoalStatus.STATUS_SUCCEEDED: "SUCCEEDED",
            GoalStatus.STATUS_CANCELED: "CANCELED",
            GoalStatus.STATUS_ABORTED: "ABORTED",
        }
        return names.get(status, str(status))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = TaskManagerNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
