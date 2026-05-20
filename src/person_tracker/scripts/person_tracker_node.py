#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from geometry_msgs.msg import PointStamped
from std_msgs.msg import Bool, Float32
from cv_bridge import CvBridge
import cv2
import numpy as np
import mediapipe as mp


class PersonTrackerNode(Node):
    """Detect person, measure distance, detect falls, and locate hands using MediaPipe Holistic."""

    # Pose landmarks
    LEFT_SHOULDER = 11
    RIGHT_SHOULDER = 12
    LEFT_HIP = 23
    RIGHT_HIP = 24

    def __init__(self):
        super().__init__('person_tracker')

        # ========== Parameters ==========
        self.declare_parameter('depth_scale', 0.001)
        self.declare_parameter('fall_tilt_threshold', 50.0)
        self.declare_parameter('detection_confidence', 0.6)
        self.declare_parameter('tracking_confidence', 0.5)
        self.declare_parameter('debug_window', True)

        self.depth_scale = self.get_parameter('depth_scale').value
        self.fall_tilt_threshold = self.get_parameter('fall_tilt_threshold').value
        self.detection_conf = self.get_parameter('detection_confidence').value
        self.tracking_conf = self.get_parameter('tracking_confidence').value
        self.debug_window = self.get_parameter('debug_window').value

        # ========== CV Bridge ==========
        self.bridge = CvBridge()

        # ========== MediaPipe Holistic ==========
        self.get_logger().info('Loading MediaPipe Holistic...')
        self.mp_holistic = mp.solutions.holistic
        self.mp_draw = mp.solutions.drawing_utils
        self.holistic = self.mp_holistic.Holistic(
            static_image_mode=False,
            model_complexity=1,
            smooth_landmarks=True,
            min_detection_confidence=self.detection_conf,
            min_tracking_confidence=self.tracking_conf,
        )
        self.get_logger().info('MediaPipe Holistic loaded')

        # ========== Camera Info ==========
        self.hfov = 73.8
        self.vfov = 58.8
        self.img_w = None
        self.img_h = None

        # ========== State ==========
        self.latest_depth = None
        self.person_distance = 0.0
        self.person_detected = False
        self.is_fallen = False
        self.hand_position = None  # (x, y, z) in camera frame or None

        # ========== Subscribers ==========
        self.rgb_sub = self.create_subscription(
            Image, '/ascamera_hp60c/camera_publisher/rgb0/image', self.rgb_callback, 10)
        self.depth_sub = self.create_subscription(
            Image, '/ascamera_hp60c/camera_publisher/depth0/image_raw', self.depth_callback, 10)

        # ========== Publishers ==========
        self.pos_pub = self.create_publisher(PointStamped, '/person_position', 10)
        self.hand_pub = self.create_publisher(PointStamped, '/person_hand_position', 10)
        self.dist_pub = self.create_publisher(Float32, '/person_distance', 10)
        self.fall_pub = self.create_publisher(Bool, '/fall_detected', 10)

        self.get_logger().info('Person Tracker Node (Holistic) started')

    def depth_callback(self, msg: Image):
        try:
            self.latest_depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')
            if self.img_w is None:
                self.img_h, self.img_w = self.latest_depth.shape[:2]
        except Exception as e:
            self.get_logger().warn(f'Depth decode failed: {e}')

    def get_depth_at(self, depth_img, u, v):
        h, w = depth_img.shape[:2]
        if u < 0 or u >= w or v < 0 or v >= h:
            return 0.0
        d = float(depth_img[v, u])
        if d > 0 and not np.isnan(d):
            return d
        y0, y1 = max(0, v - 5), min(h, v + 6)
        x0, x1 = max(0, u - 5), min(w, u + 6)
        region = depth_img[y0:y1, x0:x1]
        valid = region[(region > 0) & (~np.isnan(region))]
        return float(np.median(valid)) if len(valid) > 0 else 0.0

    def pixel_to_3d(self, u, v, depth):
        """Convert pixel (u,v) + depth (m) to 3D point in camera frame."""
        cx = self.img_w / 2.0
        cy = self.img_h / 2.0
        fx = self.img_w / (2.0 * np.tan(np.radians(self.hfov) / 2.0))
        fy = self.img_h / (2.0 * np.tan(np.radians(self.vfov) / 2.0))
        x = (u - cx) * depth / fx
        y = (v - cy) * depth / fy
        return x, y, depth  # z = forward

    def make_pointstamped(self, x, y, z, frame_id='camera_link'):
        p = PointStamped()
        p.header.stamp = self.get_clock().now().to_msg()
        p.header.frame_id = frame_id
        p.point.x = float(x)
        p.point.y = float(y)
        p.point.z = float(z)
        return p

    def calc_torso_tilt(self, landmarks, h, w):
        """Torso tilt from vertical (0=standing, 90=lying)."""
        ls = landmarks[self.LEFT_SHOULDER]
        rs = landmarks[self.RIGHT_SHOULDER]
        lh = landmarks[self.LEFT_HIP]
        rh = landmarks[self.RIGHT_HIP]
        shoulder_cx = (ls.x + rs.x) * w / 2
        shoulder_cy = (ls.y + rs.y) * h / 2
        hip_cx = (lh.x + rh.x) * w / 2
        hip_cy = (lh.y + rh.y) * h / 2
        dx = abs(shoulder_cx - hip_cx)
        dy = abs(shoulder_cy - hip_cy)
        if dy < 1e-6:
            return 90.0
        return float(np.degrees(np.arctan2(dx, dy)))

    def get_hand_center(self, hand_landmarks, w, h):
        """Get average (u, v) of all hand landmarks, or None."""
        if not hand_landmarks:
            return None
        u_sum = sum(lm.x for lm in hand_landmarks.landmark)
        v_sum = sum(lm.y for lm in hand_landmarks.landmark)
        n = len(hand_landmarks.landmark)
        return int(u_sum / n * w), int(v_sum / n * h)

    def rgb_callback(self, msg: Image):
        if self.latest_depth is None:
            return

        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, 'bgr8')
        except Exception as e:
            self.get_logger().warn(f'RGB decode failed: {e}')
            return

        if self.img_w is None:
            self.img_h, self.img_w = cv_image.shape[:2]

        h, w = cv_image.shape[:2]

        # MediaPipe Holistic on RGB
        rgb = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
        results = self.holistic.process(rgb)

        self.person_detected = False
        self.is_fallen = False
        self.hand_position = None

        if results.pose_landmarks:
            lm = results.pose_landmarks.landmark

            # ---- Body reference (hip center) ----
            hip_l = lm[self.LEFT_HIP]
            hip_r = lm[self.RIGHT_HIP]
            ref_x = int((hip_l.x + hip_r.x) * w / 2)
            ref_y = int((hip_l.y + hip_r.y) * h / 2)

            # Fallback to nose
            nose = lm[0]
            depth_raw = self.get_depth_at(self.latest_depth, ref_x, ref_y)
            if depth_raw <= 0:
                ref_x, ref_y = int(nose.x * w), int(nose.y * h)
                depth_raw = self.get_depth_at(self.latest_depth, ref_x, ref_y)

            if depth_raw > 0:
                self.person_distance = depth_raw * self.depth_scale
                self.person_detected = True

                # Publish body position
                bx, by, bz = self.pixel_to_3d(ref_x, ref_y, self.person_distance)
                self.pos_pub.publish(self.make_pointstamped(bx, by, bz))

                # Publish distance
                d = Float32()
                d.data = self.person_distance
                self.dist_pub.publish(d)

                # Fall detection
                tilt = self.calc_torso_tilt(lm, h, w)
                self.is_fallen = tilt > self.fall_tilt_threshold

                # ---- Hand detection (when fallen or always) ----
                # Get center of visible hands
                hand_uv = self.get_hand_center(results.left_hand_landmarks, w, h)
                if hand_uv is None:
                    hand_uv = self.get_hand_center(results.right_hand_landmarks, w, h)
                if hand_uv is None and results.pose_landmarks:
                    # Fallback: use wrist landmarks (15=left, 16=right)
                    for idx in [15, 16]:
                        l = lm[idx]
                        if l and l.visibility > 0.5:
                            hand_uv = (int(l.x * w), int(l.y * h))
                            break

                if hand_uv:
                    hu, hv = hand_uv
                    hd = self.get_depth_at(self.latest_depth, hu, hv)
                    if hd > 0:
                        hd_m = hd * self.depth_scale
                        hx, hy, hz = self.pixel_to_3d(hu, hv, hd_m)
                        self.hand_position = (hx, hy, hz)
                        self.hand_pub.publish(self.make_pointstamped(hx, hy, hz))
                        if self.debug_window:
                            cv2.circle(cv_image, (hu, hv), 8, (255, 0, 255), -1)
                            cv2.putText(cv_image, 'HAND', (hu + 10, hv),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 2)

                # Fall status publish
                f = Bool()
                f.data = self.is_fallen
                self.fall_pub.publish(f)

                # ---- Debug Draw ----
                if self.debug_window:
                    self.mp_draw.draw_landmarks(
                        cv_image, results.pose_landmarks, self.mp_holistic.POSE_CONNECTIONS,
                        self.mp_draw.DrawingSpec(color=(0, 255, 0), thickness=2, circle_radius=2),
                        self.mp_draw.DrawingSpec(color=(0, 255, 0), thickness=2))
                    if results.left_hand_landmarks:
                        self.mp_draw.draw_landmarks(cv_image, results.left_hand_landmarks,
                                                    self.mp_holistic.HAND_CONNECTIONS)
                    if results.right_hand_landmarks:
                        self.mp_draw.draw_landmarks(cv_image, results.right_hand_landmarks,
                                                    self.mp_holistic.HAND_CONNECTIONS)

                    cv2.circle(cv_image, (ref_x, ref_y), 6, (255, 0, 0), -1)
                    color = (0, 0, 255) if self.is_fallen else (0, 255, 0)
                    label = f'Dist: {self.person_distance:.2f}m | Tilt: {tilt:.0f}deg'
                    if self.is_fallen:
                        label += ' [FALLEN!]'
                    cv2.putText(cv_image, label, (30, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            else:
                # Person detected but depth invalid
                if self.debug_window:
                    self.mp_draw.draw_landmarks(
                        cv_image, results.pose_landmarks, self.mp_holistic.POSE_CONNECTIONS,
                        self.mp_draw.DrawingSpec(color=(128, 128, 128), thickness=2, circle_radius=2),
                        self.mp_draw.DrawingSpec(color=(128, 128, 128), thickness=2))
                    cv2.putText(cv_image, 'Person detected (no depth)', (30, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (128, 128, 128), 2)
        else:
            if hasattr(self, 'person_detected') and self.person_detected:
                self.get_logger().info('Person lost')
            if self.debug_window:
                cv2.putText(cv_image, 'No person detected', (30, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (128, 128, 128), 2)

        if self.debug_window:
            cv2.imshow('Person Tracker (Holistic)', cv_image)
            cv2.waitKey(1)

    def destroy_node(self):
        self.holistic.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PersonTrackerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        cv2.destroyAllWindows()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
