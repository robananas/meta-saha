#!/usr/bin/env python3
"""Local 3-window camera preview.

Pulls JPEG snapshots from the robot-side bridge and shows three OpenCV windows.
"""

from __future__ import annotations

import argparse
import threading
import time
from typing import Dict, Optional, Tuple

import cv2
import numpy as np
import requests


WINDOWS = {
    "chest": "fisheye_chest",
}


class FrameStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._frames: Dict[str, np.ndarray] = {}
        self._errors: Dict[str, str] = {}

    def set_ok(self, name: str, frame: np.ndarray):
        with self._lock:
            self._frames[name] = frame
            self._errors.pop(name, None)

    def set_err(self, name: str, msg: str):
        with self._lock:
            self._errors[name] = msg

    def get(self, name: str) -> Tuple[Optional[np.ndarray], Optional[str]]:
        with self._lock:
            return self._frames.get(name), self._errors.get(name)


def placeholder(text: str, size=(640, 360)) -> np.ndarray:
    img = np.zeros((size[1], size[0], 3), dtype=np.uint8)
    cv2.putText(
        img,
        text,
        (20, size[1] // 2),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 200, 255),
        2,
        cv2.LINE_AA,
    )
    return img


def poller(base: str, name: str, store: FrameStore, interval: float, stop: threading.Event):
    url = f"{base.rstrip('/')}/snapshot/{name}"
    session = requests.Session()
    while not stop.is_set():
        try:
            resp = session.get(url, timeout=2.0)
            if resp.status_code != 200:
                store.set_err(name, f"HTTP {resp.status_code}")
            else:
                arr = np.frombuffer(resp.content, dtype=np.uint8)
                frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if frame is None:
                    store.set_err(name, "decode failed")
                else:
                    store.set_ok(name, frame)
        except Exception as exc:  # noqa: BLE001
            store.set_err(name, str(exc))
        stop.wait(interval)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--base-url",
        default="http://10.128.1.10:8090",
        help="robot image bridge base URL",
    )
    parser.add_argument("--interval", type=float, default=0.05)
    args = parser.parse_args()

    store = FrameStore()
    stop = threading.Event()
    threads = []
    for name in WINDOWS:
        t = threading.Thread(
            target=poller,
            args=(args.base_url, name, store, args.interval, stop),
            daemon=True,
        )
        t.start()
        threads.append(t)
        cv2.namedWindow(WINDOWS[name], cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOWS[name], 800, 450)

    print(f"preview from {args.base_url}")
    print("press q / ESC to quit")
    try:
        while True:
            for name, title in WINDOWS.items():
                frame, err = store.get(name)
                if frame is None:
                    frame = placeholder(err or f"waiting {name}...")
                cv2.imshow(title, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
            time.sleep(0.01)
    finally:
        stop.set()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
