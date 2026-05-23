import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import rclpy
import yaml
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import Quaternion
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.task import Future
from std_msgs.msg import String
from std_srvs.srv import Trigger


class RobotMode(Enum):
    IDLE = "IDLE"
    SCHEDULED_TASK = "SCHEDULED_TASK"
    NAVIGATION = "NAVIGATION"
    CONVERSATION = "CONVERSATION"
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

        self._mode = RobotMode.IDLE
        self._active_task: RobotTask | None = None
        self._active_location: NamedLocation | None = None
        self._goal_handle = None
        self._navigation_started_at = None
        self._navigation_retry_count = 0
        self._conversation_timer = None
        self._cancel_requested = False

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

        self.create_service(Trigger, "trigger_wakeup_task", self._on_trigger_wakeup)
        self.create_service(Trigger, "cancel_task", self._on_cancel_task)
        self.create_service(Trigger, "clear_fault", self._on_clear_fault)

        self._watchdog_timer = self.create_timer(1.0, self._watchdog)
        self._publish_mode()

        if bool(self.get_parameter("auto_start_demo").value):
            delay = float(self.get_parameter("demo_start_delay_sec").value)
            self._demo_timer = self.create_timer(delay, self._auto_start_demo_once)
        else:
            self._demo_timer = None

        self.get_logger().info(
            "Task manager ready. mode=IDLE, locations=%s, manual trigger: "
            "`ros2 service call /trigger_wakeup_task std_srvs/srv/Trigger {}` "
            "or publish `wakeup_bedroom` to %s"
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
        accepted, message = self._start_wakeup_task(source="service")
        response.success = accepted
        response.message = message
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

    def _on_task_command(self, msg: String) -> None:
        command = msg.data.strip().lower()
        if command in {"wakeup_bedroom", "wake_up_bedroom", "去卧室叫醒", "叫醒老人"}:
            self._start_wakeup_task(source=f"topic:{command}")
        elif command in {"cancel", "取消任务"}:
            self._cancel_current_task(f"topic:{command}")
        else:
            self.get_logger().warn("Unknown task command ignored: %s" % msg.data)

    def _start_wakeup_task(self, source: str) -> tuple[bool, str]:
        if self._mode != RobotMode.IDLE:
            message = "Reject wakeup task from %s: robot is %s" % (source, self._mode.value)
            self.get_logger().warn(message)
            return False, message

        task = RobotTask(
            task_id="wakeup_bedroom",
            location_name="bedroom_bedside",
            speech_text="早上好，该起床了。",
        )
        self._active_task = task
        self._navigation_retry_count = 0
        self._cancel_requested = False
        self._set_mode(RobotMode.SCHEDULED_TASK, "accepted task %s from %s" % (task.task_id, source))
        self._dispatch_task()
        return True, "Wakeup task accepted."

    def _dispatch_task(self) -> None:
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
        self._set_mode(
            RobotMode.NAVIGATION,
            "sending Nav2 goal to %s, attempt %d/%d"
            % (location.name, self._navigation_retry_count + 1, self._retry_limit + 1),
        )

        future = self._navigate_client.send_goal_async(goal)
        future.add_done_callback(self._on_goal_response)

    def _on_goal_response(self, future: Future) -> None:
        goal_handle = future.result()
        if not goal_handle.accepted:
            self._handle_navigation_failure("Nav2 rejected navigation goal.")
            return

        self._goal_handle = goal_handle
        self.get_logger().info("Nav2 accepted navigation goal.")
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._on_navigation_result)

    def _on_navigation_result(self, future: Future) -> None:
        if self._cancel_requested:
            self.get_logger().info("Navigation result received after cancellation; ignoring.")
            return

        result = future.result()
        self._goal_handle = None
        if result.status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info("Navigation succeeded.")
            self._start_conversation()
            return

        status_name = self._goal_status_name(result.status)
        self._handle_navigation_failure("Navigation finished with status=%s" % status_name)

    def _watchdog(self) -> None:
        if self._mode != RobotMode.NAVIGATION or self._navigation_started_at is None:
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

    def _start_conversation(self) -> None:
        if self._active_task is None:
            self._fail_task("Navigation succeeded but no active task exists.")
            return

        self._set_mode(RobotMode.CONVERSATION, "arrived, publishing TTS text")
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

        self._reset_task()
        self._set_mode(RobotMode.IDLE, "task cancelled by %s" % source)
        return True, "Task cancelled."

    def _fail_task(self, reason: str) -> None:
        self.get_logger().error("Task failed: %s" % reason)
        self._reset_task()
        self._set_mode(RobotMode.FAULT, reason)

    def _reset_task(self) -> None:
        self._active_task = None
        self._active_location = None
        self._goal_handle = None
        self._navigation_started_at = None
        self._navigation_retry_count = 0
        self._cancel_requested = False

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
