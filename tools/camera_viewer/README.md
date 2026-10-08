# 三路相机本地预览

本机没有 ROS2，因此采用：

1. 机器人上运行 `robot_image_bridge.py`，订阅 3 个 `sensor_msgs/Image` 话题并提供 JPEG HTTP 快照
2. 本机运行 `local_triple_view.py`，用 OpenCV 开 3 个窗口显示

## 话题

| 窗口名 | ROS Topic | 实测编码 |
|---|---|---|
| camera_head | `/driver/camera/camera_head/image/Data` | `rgb8` 1280x720 |
| dual_fisheye_1 | `/driver/camera/dual_fisheye_1/image/Data` | `yuv422` 1920x1200 |
| dual_fisheye_2 | `/driver/camera/dual_fisheye_2/image/Data` | `yuv422` 1920x1200 |

## 启动

### 1. 机器人端（若未运行）

```bash
ssh orin@10.128.1.10
source /opt/ros/humble/setup.bash
python3 /tmp/robot_image_bridge.py --port 8090 --max-width 960
```

### 2. 本机端

```bash
cd /Users/zhuyikun/Downloads/meta-saha/tools/camera_viewer
.venv/bin/python local_triple_view.py --base-url http://10.128.1.10:8090
```

按 `q` 或 `ESC` 退出本机窗口。

## 检查桥接

```bash
curl http://10.128.1.10:8090/status
curl -o /tmp/head.jpg http://10.128.1.10:8090/snapshot/head
```
