from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
from task_manager_interfaces.srv import DispenseMedicine


@dataclass(frozen=True)
class MedicineBinding:
    key: str
    display_name: str
    aliases: tuple[str, ...]
    slot: int

    @property
    def angle(self) -> float:
        return float(self.slot * 90)


class ServoPwmDriver:
    def __init__(
        self,
        *,
        pin: int,
        frequency_hz: float,
        min_angle: float,
        max_angle: float,
        min_pulse_ms: float,
        max_pulse_ms: float,
        dry_run: bool,
        logger,
    ) -> None:
        self._pin = pin
        self._frequency_hz = frequency_hz
        self._min_angle = min_angle
        self._max_angle = max_angle
        self._min_pulse_ms = min_pulse_ms
        self._max_pulse_ms = max_pulse_ms
        self._dry_run = dry_run
        self._logger = logger
        self._pwm = None
        self._gpio = None

    def start(self) -> None:
        if self._dry_run:
            self._logger.info("Medicine box PWM driver is running in dry-run mode.")
            return

        try:
            import Hobot.GPIO as GPIO
        except ImportError as exc:
            self._dry_run = True
            self._logger.warning(
                f"Hobot.GPIO is unavailable, falling back to dry-run mode: {exc}"
            )
            return

        self._gpio = GPIO
        try:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BOARD)
            self._pwm = GPIO.PWM(self._pin, self._frequency_hz)
            self._pwm.ChangeDutyCycle(0.0)
            self._pwm.start(0.0)
        except Exception as exc:
            self._pwm = None
            self._dry_run = True
            try:
                GPIO.cleanup()
            except Exception:
                pass
            self._gpio = None
            self._logger.error(
                "Failed to start PWM on board pin "
                f"{self._pin}; falling back to dry-run mode: {exc}"
            )
            return

        self._logger.info(
            f"Started PWM on board pin {self._pin} at {self._frequency_hz:.1f} Hz."
        )

    def stop(self) -> None:
        if self._pwm is not None:
            self._pwm.stop()
            self._pwm = None
        if self._gpio is not None:
            self._gpio.cleanup()
            self._gpio = None

    def move_to(self, angle: float, hold_sec: float) -> float:
        clamped = max(self._min_angle, min(self._max_angle, angle))
        duty_cycle = self._angle_to_duty_cycle(clamped)

        if self._dry_run:
            self._logger.info(
                f"[dry-run] servo angle={clamped:.1f} duty={duty_cycle:.2f}%"
            )
            return clamped

        if self._pwm is None:
            raise RuntimeError("PWM driver has not been started.")

        self._pwm.ChangeDutyCycle(duty_cycle)
        time.sleep(max(0.0, hold_sec))
        self._pwm.ChangeDutyCycle(0.0)
        return clamped

    def _angle_to_duty_cycle(self, angle: float) -> float:
        angle_span = self._max_angle - self._min_angle
        if angle_span <= 0.0:
            raise ValueError("max_angle must be greater than min_angle.")

        ratio = (angle - self._min_angle) / angle_span
        pulse_ms = self._min_pulse_ms + ratio * (self._max_pulse_ms - self._min_pulse_ms)
        period_ms = 1000.0 / self._frequency_hz
        return pulse_ms / period_ms * 100.0


class MedicineBoxNode(Node):
    def __init__(self) -> None:
        super().__init__("medicine_box")

        self.declare_parameter("config_file", "")
        self.declare_parameter("pwm_pin", 33)
        self.declare_parameter("pwm_frequency_hz", 50.0)
        self.declare_parameter("dry_run", False)
        self.declare_parameter("min_angle", 0.0)
        self.declare_parameter("max_angle", 270.0)
        self.declare_parameter("min_pulse_ms", 0.5)
        self.declare_parameter("max_pulse_ms", 2.5)
        self.declare_parameter("hold_sec", 0.8)

        self._hold_sec = float(self.get_parameter("hold_sec").value)
        self._bindings = self._load_bindings()
        self._alias_index = self._build_alias_index(self._bindings)
        self._driver = ServoPwmDriver(
            pin=int(self.get_parameter("pwm_pin").value),
            frequency_hz=float(self.get_parameter("pwm_frequency_hz").value),
            min_angle=float(self.get_parameter("min_angle").value),
            max_angle=float(self.get_parameter("max_angle").value),
            min_pulse_ms=float(self.get_parameter("min_pulse_ms").value),
            max_pulse_ms=float(self.get_parameter("max_pulse_ms").value),
            dry_run=bool(self.get_parameter("dry_run").value),
            logger=self.get_logger(),
        )
        self._driver.start()

        self._service = self.create_service(
            DispenseMedicine,
            "/medicine_box/dispense",
            self._handle_dispense,
        )
        self.get_logger().info(
            "Medicine box ready. Bound medicines: "
            + ", ".join(binding.display_name for binding in self._bindings.values())
        )

    def destroy_node(self) -> bool:
        self._driver.stop()
        return super().destroy_node()

    def _handle_dispense(self, request, response):
        medicine_name = request.medicine_name.strip()
        binding = self._alias_index.get(self._normalize(medicine_name))

        if binding is None:
            response.success = False
            response.message = f"未找到药物绑定：{medicine_name}"
            response.canonical_name = ""
            response.angle = 0.0
            self.get_logger().warning(response.message)
            return response

        try:
            angle = self._driver.move_to(binding.angle, self._hold_sec)
        except Exception as exc:
            response.success = False
            response.message = f"药盒舵机动作失败：{exc}"
            response.canonical_name = binding.key
            response.angle = binding.angle
            self.get_logger().error(response.message)
            return response

        response.success = True
        response.message = f"已转到 {binding.display_name} 对应药格。"
        response.canonical_name = binding.key
        response.angle = float(angle)
        self.get_logger().info(
            f"Dispensed {binding.display_name} ({binding.key}) at {angle:.1f} degrees."
        )
        return response

    def _load_bindings(self) -> dict[str, MedicineBinding]:
        config_path = str(self.get_parameter("config_file").value).strip()
        if not config_path:
            config_path = str(
                Path(get_package_share_directory("medicine_box")) / "config" / "medicines.yaml"
            )

        data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        medicines = data.get("medicines", {})
        if not isinstance(medicines, dict) or not medicines:
            raise ValueError(f"No medicines configured in {config_path}")

        bindings = {}
        for key, raw in medicines.items():
            display_name = str(raw.get("display_name") or key)
            aliases = tuple(str(alias) for alias in raw.get("aliases", []))
            slot = int(raw["slot"])
            bindings[str(key)] = MedicineBinding(
                key=str(key),
                display_name=display_name,
                aliases=aliases,
                slot=slot,
            )
        return bindings

    def _build_alias_index(
        self, bindings: dict[str, MedicineBinding]
    ) -> dict[str, MedicineBinding]:
        alias_index = {}
        for binding in bindings.values():
            for alias in (binding.key, binding.display_name, *binding.aliases):
                alias_index[self._normalize(alias)] = binding
        return alias_index

    @staticmethod
    def _normalize(text: str) -> str:
        return text.strip().lower().replace(" ", "").replace("-", "_")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = MedicineBoxNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
