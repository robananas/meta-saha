#!/usr/bin/env python3
"""ROS2 Image -> HTTP JPEG bridge for local camera preview.

Run on the robot (with ROS2 sourced):
  python3 robot_image_bridge.py --port 8090
"""

from __future__ import annotations

import argparse
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, Optional

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image


CAMERAS = {
    "head": "/driver/camera/camera_head/image/Data",
    "fisheye1": "/driver/camera/dual_fisheye_1/image/Data",
    "fisheye2": "/driver/camera/dual_fisheye_2/image/Data",
    "chest": "/driver/camera/fisheye_chest/image/Data",
}


def image_to_bgr(msg: Image) -> Optional[np.ndarray]:
    h, w = msg.height, msg.width
    enc = (msg.encoding or "").lower()
    buf = np.frombuffer(msg.data, dtype=np.uint8)

    if enc in ("rgb8", "bgr8"):
        if buf.size < h * w * 3:
            return None
        img = buf[: h * w * 3].reshape(h, w, 3)
        return cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if enc == "rgb8" else img

    if enc in ("yuv422", "yuyv", "yuv422_yuy2"):
        # ROS yuv422 is commonly YUYV packed, 2 bytes/pixel.
        if buf.size < h * w * 2:
            return None
        yuyv = buf[: h * w * 2].reshape(h, w, 2)
        return cv2.cvtColor(yuyv, cv2.COLOR_YUV2BGR_YUY2)

    if enc in ("mono8", "8uc1"):
        if buf.size < h * w:
            return None
        gray = buf[: h * w].reshape(h, w)
        return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    return None


class CameraBridge(Node):
    def __init__(self, max_width: int, jpeg_quality: int):
        super().__init__("local_camera_bridge")
        self.max_width = max_width
        self.jpeg_quality = jpeg_quality
        self._lock = threading.Lock()
        self._frames: Dict[str, bytes] = {}
        self._meta: Dict[str, str] = {}

        for name, topic in CAMERAS.items():
            self.create_subscription(
                Image,
                topic,
                self._make_cb(name),
                qos_profile_sensor_data,
            )
            self.get_logger().info(f"subscribe {name}: {topic}")

    def _make_cb(self, name: str):
        def _cb(msg: Image):
            bgr = image_to_bgr(msg)
            if bgr is None:
                self.get_logger().warning(
                    f"{name}: unsupported encoding={msg.encoding} "
                    f"size={msg.width}x{msg.height}"
                )
                return
            if self.max_width > 0 and bgr.shape[1] > self.max_width:
                scale = self.max_width / float(bgr.shape[1])
                bgr = cv2.resize(
                    bgr,
                    (self.max_width, int(bgr.shape[0] * scale)),
                    interpolation=cv2.INTER_AREA,
                )
            ok, encoded = cv2.imencode(
                ".jpg",
                bgr,
                [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality],
            )
            if not ok:
                return
            with self._lock:
                self._frames[name] = encoded.tobytes()
                self._meta[name] = (
                    f"{msg.encoding} {msg.width}x{msg.height} -> "
                    f"{bgr.shape[1]}x{bgr.shape[0]}"
                )

        return _cb

    def get_jpeg(self, name: str) -> Optional[bytes]:
        with self._lock:
            return self._frames.get(name)

    def status_text(self) -> str:
        with self._lock:
            lines = ["camera bridge ok"]
            for name, topic in CAMERAS.items():
                meta = self._meta.get(name, "waiting")
                lines.append(f"{name}: {topic} | {meta}")
            return "\n".join(lines) + "\n"


def make_handler(bridge: CameraBridge):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/status"):
                body = bridge.status_text().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if path.startswith("/snapshot/"):
                name = path[len("/snapshot/") :]
                if name not in CAMERAS:
                    self.send_error(404, "unknown camera")
                    return
                jpeg = bridge.get_jpeg(name)
                if jpeg is None:
                    self.send_error(503, "no frame yet")
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(jpeg)))
                self.end_headers()
                self.wfile.write(jpeg)
                return

            self.send_error(404)

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--max-width", type=int, default=960)
    parser.add_argument("--jpeg-quality", type=int, default=70)
    args = parser.parse_args()

    rclpy.init()
    bridge = CameraBridge(args.max_width, args.jpeg_quality)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(bridge))

    def spin():
        rclpy.spin(bridge)

    t = threading.Thread(target=spin, daemon=True)
    t.start()
    bridge.get_logger().info(f"HTTP on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        bridge.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
