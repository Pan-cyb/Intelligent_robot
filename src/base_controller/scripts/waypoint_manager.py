#!/usr/bin/env python3

from pathlib import Path
import re
from typing import Any

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node

from base_controller.srv import DeletePose, GetPose, ListPoses, SavePose


class WaypointManager(Node):
    def __init__(self) -> None:
        super().__init__("waypoint_manager")
        default_yaml = str(Path(get_package_share_directory("base_controller")) / "named_poses.yaml")

        self.declare_parameter("goal_topic", "/waypoint_goal")
        self.declare_parameter("map_frame", "map")
        self.declare_parameter("poses_file", default_yaml)

        self._goal_topic = str(self.get_parameter("goal_topic").value)
        self._map_frame = str(self.get_parameter("map_frame").value)
        self._poses_file = Path(str(self.get_parameter("poses_file").value)).expanduser()
        self._last_goal: PoseStamped | None = None
        self._poses = self._load_poses()

        self.create_subscription(PoseStamped, self._goal_topic, self._on_goal, 10)
        self.create_service(SavePose, "/waypoint_manager/save_last_goal", self._save_last_goal)
        self.create_service(GetPose, "/waypoint_manager/get_pose", self._get_pose)
        self.create_service(ListPoses, "/waypoint_manager/list_poses", self._list_poses)
        self.create_service(DeletePose, "/waypoint_manager/delete_pose", self._delete_pose)

        self.get_logger().info(f"Waypoint manager started. goal_topic={self._goal_topic}")
        self.get_logger().info(f"Named poses file: {self._poses_file}")
        self.get_logger().info(f"Loaded {len(self._poses)} named poses.")

    def _load_poses(self) -> dict[str, Any]:
        if not self._poses_file.exists():
            self.get_logger().warn(f"Named poses file does not exist yet: {self._poses_file}")
            return {}

        try:
            with self._poses_file.open("r", encoding="utf-8") as file:
                data = yaml.safe_load(file) or {}
        except OSError as exc:
            self.get_logger().error(f"Failed to read named poses file: {exc}")
            return {}
        except yaml.YAMLError as exc:
            self.get_logger().error(f"Failed to parse named poses YAML: {exc}")
            return {}

        if not isinstance(data, dict):
            self.get_logger().error("Named poses YAML root must be a mapping.")
            return {}
        return data

    def _write_poses(self) -> tuple[bool, str]:
        try:
            self._poses_file.parent.mkdir(parents=True, exist_ok=True)
            with self._poses_file.open("w", encoding="utf-8") as file:
                yaml.safe_dump(
                    self._poses,
                    file,
                    allow_unicode=True,
                    sort_keys=True,
                    default_flow_style=False,
                )
        except OSError as exc:
            message = f"保存 named poses 文件失败：{exc}"
            self.get_logger().error(message)
            return False, message
        return True, f"已写入 {self._poses_file}"

    def _on_goal(self, msg: PoseStamped) -> None:
        frame_id = msg.header.frame_id.strip()
        if frame_id != self._map_frame:
            self.get_logger().error(
                f"忽略非 {self._map_frame} 坐标系的点选位姿：frame_id={frame_id or '<empty>'}"
            )
            return

        self._last_goal = msg
        self.get_logger().info(
            "收到标定位姿：frame_id=%s x=%.3f y=%.3f z=%.3f qz=%.3f qw=%.3f"
            % (
                frame_id,
                msg.pose.position.x,
                msg.pose.position.y,
                msg.pose.position.z,
                msg.pose.orientation.z,
                msg.pose.orientation.w,
            )
        )

    def _save_last_goal(self, request: SavePose.Request, response: SavePose.Response) -> SavePose.Response:
        name = request.name.strip()
        if not self._valid_name(name):
            response.success = False
            response.message = "命名点名称无效，请使用字母、数字和下划线，例如 bedroom_bedside"
            self.get_logger().warn(response.message)
            return response

        if self._last_goal is None:
            response.success = False
            response.message = "还没有收到 /waypoint_goal，请先在 RViz 中点选 2D Goal Pose"
            self.get_logger().warn(response.message)
            return response

        existed = name in self._poses
        self._poses[name] = self._pose_to_yaml(self._last_goal)
        ok, message = self._write_poses()
        response.success = ok
        if ok:
            action = "覆盖" if existed else "保存"
            response.message = f"已{action}命名点 {name}。{message}"
            self.get_logger().info(response.message)
        else:
            response.message = message
        return response

    def _get_pose(self, request: GetPose.Request, response: GetPose.Response) -> GetPose.Response:
        name = request.name.strip()
        data = self._poses.get(name)
        if data is None:
            response.success = False
            response.message = f"未找到命名点：{name}"
            self.get_logger().warn(response.message)
            return response

        try:
            response.pose = self._yaml_to_pose(data)
        except (KeyError, TypeError, ValueError) as exc:
            response.success = False
            response.message = f"命名点 {name} 数据格式错误：{exc}"
            self.get_logger().error(response.message)
            return response

        response.success = True
        response.message = f"已读取命名点：{name}"
        self.get_logger().info(response.message)
        return response

    def _list_poses(self, request: ListPoses.Request, response: ListPoses.Response) -> ListPoses.Response:
        del request
        response.names = sorted(self._poses.keys())
        self.get_logger().info(f"当前命名点数量：{len(response.names)}")
        return response

    def _delete_pose(self, request: DeletePose.Request, response: DeletePose.Response) -> DeletePose.Response:
        name = request.name.strip()
        if name not in self._poses:
            response.success = False
            response.message = f"未找到命名点：{name}"
            self.get_logger().warn(response.message)
            return response

        del self._poses[name]
        ok, message = self._write_poses()
        response.success = ok
        response.message = f"已删除命名点 {name}。{message}" if ok else message
        if ok:
            self.get_logger().info(response.message)
        return response

    @staticmethod
    def _valid_name(name: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9_]+", name))

    @staticmethod
    def _pose_to_yaml(msg: PoseStamped) -> dict[str, Any]:
        return {
            "frame_id": msg.header.frame_id,
            "position": {
                "x": float(msg.pose.position.x),
                "y": float(msg.pose.position.y),
                "z": float(msg.pose.position.z),
            },
            "orientation": {
                "x": float(msg.pose.orientation.x),
                "y": float(msg.pose.orientation.y),
                "z": float(msg.pose.orientation.z),
                "w": float(msg.pose.orientation.w),
            },
        }

    def _yaml_to_pose(self, data: dict[str, Any]) -> PoseStamped:
        pose = PoseStamped()
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.header.frame_id = str(data["frame_id"])
        if pose.header.frame_id != self._map_frame:
            raise ValueError(f"frame_id 必须是 {self._map_frame}，当前是 {pose.header.frame_id}")

        position = data["position"]
        orientation = data["orientation"]
        pose.pose.position.x = float(position["x"])
        pose.pose.position.y = float(position["y"])
        pose.pose.position.z = float(position["z"])
        pose.pose.orientation.x = float(orientation["x"])
        pose.pose.orientation.y = float(orientation["y"])
        pose.pose.orientation.z = float(orientation["z"])
        pose.pose.orientation.w = float(orientation["w"])
        return pose


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = WaypointManager()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
