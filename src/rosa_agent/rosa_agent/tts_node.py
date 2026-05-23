import threading

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import String

from rosa_agent.config import tts_config
from rosa_agent.voice import speak


class TTSNode(Node):
    def __init__(self) -> None:
        super().__init__("tts_node")
        self.declare_parameter("tts_topic", "/tts_text")
        self._tts_config = tts_config()
        self._lock = threading.Lock()

        topic = str(self.get_parameter("tts_topic").value)
        self.create_subscription(String, topic, self._on_tts_text, 10)
        self.get_logger().info("TTS node ready. listening on %s" % topic)

    def _on_tts_text(self, msg: String) -> None:
        text = msg.data.strip()
        if not text:
            self.get_logger().warn("Empty TTS text ignored.")
            return

        thread = threading.Thread(target=self._speak_once, args=(text,), daemon=True)
        thread.start()

    def _speak_once(self, text: str) -> None:
        if not self._lock.acquire(blocking=False):
            self.get_logger().warn("TTS is busy, ignoring new text: %s" % text)
            return

        try:
            self.get_logger().info("Speaking: %s" % text)
            speak(text, config=self._tts_config)
            self.get_logger().info("TTS playback finished.")
        except Exception as exc:
            self.get_logger().error("TTS playback failed: %s" % exc)
        finally:
            self._lock.release()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = TTSNode()
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
