#!/usr/bin/env python3
from dataclasses import dataclass
import math
import time

import cv2
from cv_bridge import CvBridge
from geometry_msgs.msg import PointStamped
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, Float32


def _as_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", ""}
    return bool(value)


@dataclass
class PersonDetection:
    bbox: tuple
    score: float
    class_id: int = 0
    label: str = "person"

    @property
    def area(self):
        x1, y1, x2, y2 = self.bbox
        return max(0, x2 - x1) * max(0, y2 - y1)


class PersonDetector:
    def detect(self, image):
        raise NotImplementedError


class MockPersonDetector(PersonDetector):
    """Lightweight ROS-chain test detector.

    When enabled, it emits one centered person-like bbox. This is meant for
    validating image/depth subscription, depth projection, topic publishing,
    launch wiring, and follower/task_manager compatibility before BPU YOLO is
    connected.
    """

    def __init__(self, enable_center_bbox=True, score=0.9):
        self.enable_center_bbox = enable_center_bbox
        self.score = score

    def detect(self, image):
        if not self.enable_center_bbox:
            return []
        h, w = image.shape[:2]
        box_w = int(w * 0.28)
        box_h = int(h * 0.62)
        cx = w // 2
        y2 = int(h * 0.92)
        x1 = max(0, cx - box_w // 2)
        x2 = min(w - 1, cx + box_w // 2)
        y1 = max(0, y2 - box_h)
        return [PersonDetection((x1, y1, x2, y2), self.score)]


class BpuYoloPersonDetector(PersonDetector):
    """RDK X5 BPU YOLO detector using D-Robotics pyeasy_dnn.

    This keeps ROS IO outside the detector. It expects a D-Robotics converted
    YOLO model and decodes common YOLOv8-style outputs shaped like
    [1, 84, 8400] or [1, 8400, 84]. If the deployed model uses a different
    head layout, only this class should need adjustment.
    """

    def __init__(
        self,
        logger,
        model_path,
        input_width=640,
        input_height=640,
        score_threshold=0.4,
        nms_threshold=0.45,
    ):
        self.logger = logger
        self.model_path = model_path
        self.input_width = int(input_width)
        self.input_height = int(input_height)
        self.score_threshold = float(score_threshold)
        self.nms_threshold = float(nms_threshold)
        self.model = self._load_model()

    def _load_model(self):
        if not self.model_path:
            raise RuntimeError("bpu_yolo_model_path is empty")
        try:
            from hobot_dnn import pyeasy_dnn as dnn
        except Exception as exc:
            raise RuntimeError(
                "Failed to import hobot_dnn.pyeasy_dnn. Install/enable the "
                "D-Robotics RDK X5 runtime before using vision_backend:=bpu_yolo."
            ) from exc
        models = dnn.load(self.model_path)
        if not models:
            raise RuntimeError(f"No model loaded from {self.model_path}")
        self.logger.info(f"Loaded BPU YOLO model: {self.model_path}")
        return models[0]

    def detect(self, image):
        input_tensor, scale, pad_x, pad_y = self._preprocess(image)
        outputs = self.model.forward(input_tensor)
        arrays = [self._output_to_array(out) for out in outputs]
        return self._decode_yolov8(arrays, image.shape[1], image.shape[0], scale, pad_x, pad_y)

    def _preprocess(self, image):
        h, w = image.shape[:2]
        scale = min(self.input_width / w, self.input_height / h)
        new_w = int(round(w * scale))
        new_h = int(round(h * scale))
        resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        canvas = np.full((self.input_height, self.input_width, 3), 114, dtype=np.uint8)
        pad_x = (self.input_width - new_w) // 2
        pad_y = (self.input_height - new_h) // 2
        canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
        rgb = cv2.cvtColor(canvas, cv2.COLOR_BGR2RGB)
        return np.expand_dims(rgb, axis=0), scale, pad_x, pad_y

    def _output_to_array(self, output):
        data = output.buffer if hasattr(output, "buffer") else output
        return np.array(data)

    def _decode_yolov8(self, outputs, image_w, image_h, scale, pad_x, pad_y):
        if not outputs:
            return []

        pred = outputs[0]
        pred = np.squeeze(pred)
        if pred.ndim != 2:
            pred = pred.reshape((-1, pred.shape[-1]))
        if pred.shape[0] < pred.shape[1] and pred.shape[0] in (84, 85, 116):
            pred = pred.T
        if pred.shape[1] < 6:
            return []

        boxes = []
        scores = []
        for row in pred:
            # YOLOv8 export is usually cx, cy, w, h, class scores...
            class_scores = row[4:]
            if class_scores.size == 0:
                continue
            class_id = int(np.argmax(class_scores))
            if class_id != 0:
                continue
            score = float(class_scores[class_id])
            if score < self.score_threshold:
                continue
            cx, cy, bw, bh = [float(v) for v in row[:4]]
            x1 = (cx - bw / 2.0 - pad_x) / scale
            y1 = (cy - bh / 2.0 - pad_y) / scale
            x2 = (cx + bw / 2.0 - pad_x) / scale
            y2 = (cy + bh / 2.0 - pad_y) / scale
            x1 = max(0.0, min(image_w - 1.0, x1))
            y1 = max(0.0, min(image_h - 1.0, y1))
            x2 = max(0.0, min(image_w - 1.0, x2))
            y2 = max(0.0, min(image_h - 1.0, y2))
            if x2 <= x1 or y2 <= y1:
                continue
            boxes.append([int(x1), int(y1), int(x2 - x1), int(y2 - y1)])
            scores.append(score)

        if not boxes:
            return []
        keep = cv2.dnn.NMSBoxes(boxes, scores, self.score_threshold, self.nms_threshold)
        detections = []
        for idx in np.array(keep).reshape(-1):
            x, y, w, h = boxes[int(idx)]
            detections.append(
                PersonDetection((x, y, x + w, y + h), float(scores[int(idx)]), 0, "person")
            )
        return detections


class PersonTrackerBpuNode(Node):
    """YOLO/BPU-ready person perception with depth localization."""

    def __init__(self):
        super().__init__("person_tracker_bpu")

        self.declare_parameter("vision_backend", "mock")
        self.declare_parameter("rgb_topic", "/ascamera_hp60c/camera_publisher/rgb0/image")
        self.declare_parameter("depth_topic", "/ascamera_hp60c/camera_publisher/depth0/image_raw")
        self.declare_parameter("camera_frame_id", "camera_link")
        self.declare_parameter("depth_scale", 0.001)
        self.declare_parameter("depth_window_size", 11)
        self.declare_parameter("min_depth_m", 0.3)
        self.declare_parameter("max_depth_m", 5.0)
        self.declare_parameter("inference_every_n_frames", 3)
        self.declare_parameter("max_publish_rate_hz", 10.0)
        self.declare_parameter("hfov_deg", 73.8)
        self.declare_parameter("vfov_deg", 58.8)
        self.declare_parameter("ema_alpha", 0.35)
        self.declare_parameter("mock_enable_center_bbox", True)
        self.declare_parameter("bpu_yolo_model_path", "")
        self.declare_parameter("bpu_yolo_input_width", 640)
        self.declare_parameter("bpu_yolo_input_height", 640)
        self.declare_parameter("bpu_yolo_score_threshold", 0.4)
        self.declare_parameter("bpu_yolo_nms_threshold", 0.45)
        self.declare_parameter("enable_bbox_fall_detection", False)
        self.declare_parameter("fall_aspect_ratio_threshold", 1.5)
        self.declare_parameter("fall_confirm_frames", 5)
        self.declare_parameter("stats_log_period_sec", 2.0)

        self.vision_backend = self.get_parameter("vision_backend").value
        self.rgb_topic = self.get_parameter("rgb_topic").value
        self.depth_topic = self.get_parameter("depth_topic").value
        self.camera_frame_id = self.get_parameter("camera_frame_id").value
        self.depth_scale = float(self.get_parameter("depth_scale").value)
        self.depth_window_size = int(self.get_parameter("depth_window_size").value)
        self.min_depth_m = float(self.get_parameter("min_depth_m").value)
        self.max_depth_m = float(self.get_parameter("max_depth_m").value)
        self.inference_every_n_frames = max(1, int(self.get_parameter("inference_every_n_frames").value))
        self.max_publish_rate_hz = float(self.get_parameter("max_publish_rate_hz").value)
        self.hfov_deg = float(self.get_parameter("hfov_deg").value)
        self.vfov_deg = float(self.get_parameter("vfov_deg").value)
        self.ema_alpha = float(self.get_parameter("ema_alpha").value)
        self.enable_bbox_fall_detection = _as_bool(
            self.get_parameter("enable_bbox_fall_detection").value
        )
        self.fall_aspect_ratio_threshold = float(
            self.get_parameter("fall_aspect_ratio_threshold").value
        )
        self.fall_confirm_frames = max(1, int(self.get_parameter("fall_confirm_frames").value))
        self.stats_log_period_sec = float(self.get_parameter("stats_log_period_sec").value)

        self.bridge = CvBridge()
        self.latest_depth = None
        self.depth_stamp = None
        self.img_w = None
        self.img_h = None
        self.frame_count = 0
        self.last_publish_time = 0.0
        self.last_log_time = time.time()
        self.publish_count = 0
        self.invalid_depth_count = 0
        self.valid_depth_count = 0
        self.last_inference_ms = 0.0
        self.last_detection_count = 0
        self.last_selected_bbox = None
        self.fall_candidate_frames = 0
        self.ema_initialized = False
        self.person_x = 0.0
        self.person_y = 0.0
        self.person_z = 0.0
        self.person_distance = 0.0

        self.detector = self._make_detector()

        self.create_subscription(Image, self.rgb_topic, self.rgb_callback, 10)
        self.create_subscription(Image, self.depth_topic, self.depth_callback, 10)
        self.pos_pub = self.create_publisher(PointStamped, "/person_position", 10)
        self.dist_pub = self.create_publisher(Float32, "/person_distance", 10)
        self.fall_pub = self.create_publisher(Bool, "/fall_detected", 10)

        self.get_logger().info(
            f"Person Tracker BPU-ready node started: backend={self.vision_backend}, "
            f"rgb={self.rgb_topic}, depth={self.depth_topic}"
        )

    def _make_detector(self):
        if self.vision_backend == "mock":
            return MockPersonDetector(
                enable_center_bbox=_as_bool(self.get_parameter("mock_enable_center_bbox").value)
            )
        if self.vision_backend == "bpu_yolo":
            return BpuYoloPersonDetector(
                self.get_logger(),
                self.get_parameter("bpu_yolo_model_path").value,
                self.get_parameter("bpu_yolo_input_width").value,
                self.get_parameter("bpu_yolo_input_height").value,
                self.get_parameter("bpu_yolo_score_threshold").value,
                self.get_parameter("bpu_yolo_nms_threshold").value,
            )
        self.get_logger().warn(
            f"Unsupported backend '{self.vision_backend}', falling back to mock detector"
        )
        return MockPersonDetector()

    def depth_callback(self, msg):
        try:
            self.latest_depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding="passthrough")
            self.depth_stamp = msg.header.stamp
            if self.img_w is None:
                self.img_h, self.img_w = self.latest_depth.shape[:2]
        except Exception as exc:
            self.get_logger().warn(f"Depth decode failed: {exc}")

    def rgb_callback(self, msg):
        self.frame_count += 1
        if self.latest_depth is None:
            self._publish_fall(False)
            return
        if self.frame_count % self.inference_every_n_frames != 0:
            return
        if not self._publish_rate_allows():
            return

        try:
            image = self.bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
        except Exception as exc:
            self.get_logger().warn(f"RGB decode failed: {exc}")
            return

        self.img_h, self.img_w = image.shape[:2]
        t0 = time.perf_counter()
        detections = self.detector.detect(image)
        self.last_inference_ms = (time.perf_counter() - t0) * 1000.0
        self.last_detection_count = len(detections)
        selected = self.select_person(detections)
        self.last_selected_bbox = selected.bbox if selected else None

        if selected is None:
            self._publish_fall(False)
            self._log_stats()
            return

        depth_result = self.depth_for_bbox(self.latest_depth, selected.bbox)
        if depth_result is None:
            self.invalid_depth_count += 1
            self._publish_fall(self.update_fall_state(selected.bbox))
            self._log_stats()
            return

        u, v, depth_m = depth_result
        x, y, z = self.pixel_to_body_3d(u, v, depth_m)
        self.update_ema(x, y, z, depth_m)
        self.publish_person(msg.header.stamp)
        self._publish_fall(self.update_fall_state(selected.bbox))
        self.valid_depth_count += 1
        self.publish_count += 1
        self.last_publish_time = time.time()
        self._log_stats()

    def _publish_rate_allows(self):
        if self.max_publish_rate_hz <= 0.0:
            return True
        return time.time() - self.last_publish_time >= 1.0 / self.max_publish_rate_hz

    def select_person(self, detections):
        people = [d for d in detections if d.label == "person" or d.class_id == 0]
        if not people:
            return None
        return max(people, key=lambda d: d.area)

    def depth_for_bbox(self, depth_img, bbox):
        x1, y1, x2, y2 = [int(v) for v in bbox]
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        candidates = [
            (cx, cy, self.depth_window_size),
            (cx, int(y1 + (y2 - y1) * 0.65), self.depth_window_size),
            (cx, cy, self.depth_window_size * 2 + 1),
            (cx, int(y1 + (y2 - y1) * 0.75), self.depth_window_size * 2 + 1),
        ]
        for u, v, window in candidates:
            depth_m = self.depth_window_median(depth_img, u, v, window)
            if depth_m is not None:
                return u, v, depth_m
        return None

    def depth_window_median(self, depth_img, u, v, window_size):
        h, w = depth_img.shape[:2]
        if u < 0 or u >= w or v < 0 or v >= h:
            return None
        radius = max(1, int(window_size) // 2)
        y0, y1 = max(0, v - radius), min(h, v + radius + 1)
        x0, x1 = max(0, u - radius), min(w, u + radius + 1)
        region = depth_img[y0:y1, x0:x1].astype(np.float32)
        valid = region[np.isfinite(region) & (region > 0)]
        if valid.size == 0:
            return None
        depth_m = float(np.median(valid) * self.depth_scale)
        if self.min_depth_m <= depth_m <= self.max_depth_m:
            return depth_m
        return None

    def pixel_to_body_3d(self, u, v, depth_m):
        cx = self.img_w / 2.0
        cy = self.img_h / 2.0
        fx = self.img_w / (2.0 * math.tan(math.radians(self.hfov_deg) / 2.0))
        fy = self.img_h / (2.0 * math.tan(math.radians(self.vfov_deg) / 2.0))
        optical_x = (u - cx) * depth_m / fx
        optical_y = (v - cy) * depth_m / fy
        optical_z = depth_m
        return optical_z, -optical_x, -optical_y

    def update_ema(self, x, y, z, depth_m):
        if not self.ema_initialized:
            self.person_x = x
            self.person_y = y
            self.person_z = z
            self.person_distance = depth_m
            self.ema_initialized = True
            return
        a = self.ema_alpha
        self.person_x = a * x + (1.0 - a) * self.person_x
        self.person_y = a * y + (1.0 - a) * self.person_y
        self.person_z = a * z + (1.0 - a) * self.person_z
        self.person_distance = a * depth_m + (1.0 - a) * self.person_distance

    def publish_person(self, stamp):
        point = PointStamped()
        point.header.stamp = stamp
        point.header.frame_id = self.camera_frame_id
        point.point.x = float(self.person_x)
        point.point.y = float(self.person_y)
        point.point.z = float(self.person_z)
        self.pos_pub.publish(point)

        dist = Float32()
        dist.data = float(self.person_distance)
        self.dist_pub.publish(dist)

    def update_fall_state(self, bbox):
        if not self.enable_bbox_fall_detection:
            self.fall_candidate_frames = 0
            return False
        x1, y1, x2, y2 = bbox
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        if width / height > self.fall_aspect_ratio_threshold:
            self.fall_candidate_frames += 1
        else:
            self.fall_candidate_frames = 0
        return self.fall_candidate_frames >= self.fall_confirm_frames

    def _publish_fall(self, is_fallen):
        msg = Bool()
        msg.data = bool(is_fallen)
        self.fall_pub.publish(msg)

    def _log_stats(self):
        now = time.time()
        if now - self.last_log_time < self.stats_log_period_sec:
            return
        elapsed = max(1e-6, now - self.last_log_time)
        fps = self.publish_count / elapsed
        self.get_logger().info(
            "vision stats: "
            f"backend={self.vision_backend}, infer={self.last_inference_ms:.1f}ms, "
            f"publish_fps={fps:.1f}, detections={self.last_detection_count}, "
            f"selected_bbox={self.last_selected_bbox}, "
            f"valid_depth={self.valid_depth_count}, invalid_depth={self.invalid_depth_count}"
        )
        self.publish_count = 0
        self.valid_depth_count = 0
        self.invalid_depth_count = 0
        self.last_log_time = now


def main(args=None):
    rclpy.init(args=args)
    node = PersonTrackerBpuNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
