from enum import Enum

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger
from task_manager_interfaces.srv import QueryRobotState, StartTask


class DemoStage(Enum):
    INIT = "INIT"
    WAKE_UP = "WAKE_UP"
    COMPANION_NAVIGATE = "COMPANION_NAVIGATE"
    COMPANION_DIALOGUE = "COMPANION_DIALOGUE"
    WAIT_FOR_FOLLOW_TRIGGER = "WAIT_FOR_FOLLOW_TRIGGER"
    DONE = "DONE"


class DemoManagerNode(Node):
    """Orchestrates demo-level task sequence through task_manager services only."""

    def __init__(self) -> None:
        super().__init__("demo_manager")

        self.declare_parameter("start_delay_sec", 30.0)
        self.declare_parameter("wakeup_target", "bedroom_bedside")
        self.declare_parameter("wakeup_text", "早上好，该起床了。")
        self.declare_parameter("companion_target", "livingroom_sofa")
        self.declare_parameter(
            "companion_text",
            "我陪您到客厅坐一会儿，有需要可以随时叫我。",
        )
        self.declare_parameter("service_wait_timeout_sec", 1.0)
        self.declare_parameter("retry_interval_sec", 2.0)
        self.declare_parameter("tick_interval_sec", 1.0)

        self._stage = DemoStage.INIT
        self._task_in_progress = False
        self._demo_started_at = self.get_clock().now()
        self._stage_started_at = self._demo_started_at
        self._robot_mode = ""
        self._last_error = ""
        self._fall_detected = False

        self._start_task_client = self.create_client(StartTask, "/robot_server/start_task")
        self._query_state_client = self.create_client(
            QueryRobotState,
            "/robot_server/query_robot_state",
        )
        self._cancel_task_client = self.create_client(
            Trigger,
            "/robot_server/cancel_current_task",
        )
        self._clear_emergency_client = self.create_client(
            Trigger,
            "/robot_server/clear_emergency",
        )

        self.create_subscription(String, "/robot_mode", self._on_robot_mode, 10)
        self.create_subscription(Bool, "/fall_detected", self._on_fall_detected, 10)

        start_delay = float(self.get_parameter("start_delay_sec").value)
        tick_interval = float(self.get_parameter("tick_interval_sec").value)
        self._start_timer = self.create_timer(start_delay, self._start_once)
        self._tick_timer = self.create_timer(tick_interval, self._tick)

        self.get_logger().info(
            "Demo manager ready. It will orchestrate tasks via /robot_server services only."
        )

    def _start_once(self) -> None:
        if self._start_timer is not None:
            self._start_timer.cancel()
            self._start_timer = None
        self._demo_started_at = self.get_clock().now()
        self._set_stage(DemoStage.WAKE_UP, "start delay elapsed")
        self._start_task(
            "wake_up",
            str(self.get_parameter("wakeup_target").value),
            str(self.get_parameter("wakeup_text").value),
        )

    def _tick(self) -> None:
        self._refresh_robot_state()

        if self._robot_mode == "EMERGENCY":
            self.get_logger().warn("Robot is in EMERGENCY; demo manager is waiting.")
            return

        if self._stage == DemoStage.WAKE_UP and self._task_completed():
            self._set_stage(DemoStage.COMPANION_NAVIGATE, "wake_up completed")
            self._start_task(
                "navigate",
                str(self.get_parameter("companion_target").value),
                "",
            )
            return

        if self._stage == DemoStage.COMPANION_NAVIGATE and self._task_completed():
            self._set_stage(DemoStage.COMPANION_DIALOGUE, "companion navigation completed")
            self._start_task(
                "speak",
                "",
                str(self.get_parameter("companion_text").value),
            )
            return

        if self._stage == DemoStage.COMPANION_DIALOGUE and self._task_completed():
            self._set_stage(
                DemoStage.WAIT_FOR_FOLLOW_TRIGGER,
                "companion dialogue completed; ROSA may trigger follow",
            )
            self.get_logger().info(
                "Demo scripted flow complete. Waiting for user voice command to trigger follow."
            )

    def _refresh_robot_state(self) -> None:
        if not self._query_state_client.service_is_ready():
            self._query_state_client.wait_for_service(
                timeout_sec=float(self.get_parameter("service_wait_timeout_sec").value)
            )
            return

        future = self._query_state_client.call_async(QueryRobotState.Request())
        future.add_done_callback(self._on_query_state_result)

    def _on_query_state_result(self, future) -> None:
        try:
            response = future.result()
        except Exception as exc:
            self.get_logger().warn("Query robot state failed: %s" % exc)
            return
        self._robot_mode = response.mode
        self._last_error = response.last_error

    def _start_task(self, task_type: str, target: str, text: str) -> None:
        if not self._start_task_client.service_is_ready():
            if not self._start_task_client.wait_for_service(
                timeout_sec=float(self.get_parameter("service_wait_timeout_sec").value)
            ):
                self.get_logger().warn(
                    "Waiting for /robot_server/start_task before starting %s." % task_type
                )
                self._retry_later(lambda: self._start_task(task_type, target, text))
                return

        request = StartTask.Request()
        request.task_type = task_type
        request.target = target
        request.text = text
        self.get_logger().info(
            "Request task: type=%s target=%s text=%s" % (task_type, target, text)
        )
        future = self._start_task_client.call_async(request)
        future.add_done_callback(lambda future: self._on_start_task_result(future, task_type))

    def _on_start_task_result(self, future, task_type: str) -> None:
        try:
            response = future.result()
        except Exception as exc:
            self.get_logger().warn("Start task %s failed: %s" % (task_type, exc))
            self._retry_current_stage_later()
            return

        if response.success:
            self._task_in_progress = True
            self.get_logger().info("Task accepted: %s" % response.message)
            return

        self.get_logger().warn("Task rejected: %s" % response.message)
        self._retry_current_stage_later()

    def _retry_current_stage_later(self) -> None:
        if self._robot_mode == "EMERGENCY":
            return
        if self._stage == DemoStage.WAKE_UP:
            self._retry_later(
                lambda: self._start_task(
                    "wake_up",
                    str(self.get_parameter("wakeup_target").value),
                    str(self.get_parameter("wakeup_text").value),
                )
            )
        elif self._stage == DemoStage.COMPANION_NAVIGATE:
            self._retry_later(
                lambda: self._start_task(
                    "navigate",
                    str(self.get_parameter("companion_target").value),
                    "",
                )
            )
        elif self._stage == DemoStage.COMPANION_DIALOGUE:
            self._retry_later(
                lambda: self._start_task(
                    "speak",
                    "",
                    str(self.get_parameter("companion_text").value),
                )
            )

    def _retry_later(self, callback) -> None:
        retry_interval = float(self.get_parameter("retry_interval_sec").value)

        def _once():
            timer.cancel()
            callback()

        timer = self.create_timer(retry_interval, _once)

    def _task_completed(self) -> bool:
        if not self._task_in_progress:
            return False
        if self._robot_mode != "IDLE":
            return False
        self._task_in_progress = False
        return True

    def _elapsed_since_demo_start(self) -> float:
        elapsed = self.get_clock().now() - self._demo_started_at
        return elapsed.nanoseconds / 1e9

    def _set_stage(self, stage: DemoStage, reason: str) -> None:
        if self._stage == stage:
            return
        old = self._stage
        self._stage = stage
        self._stage_started_at = self.get_clock().now()
        self._task_in_progress = False
        self.get_logger().info("Demo stage %s -> %s: %s" % (old.value, stage.value, reason))

    def _on_robot_mode(self, msg: String) -> None:
        self._robot_mode = msg.data

    def _on_fall_detected(self, msg: Bool) -> None:
        self._fall_detected = msg.data


def main(args=None) -> None:
    rclpy.init(args=args)
    node = DemoManagerNode()
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
