#!/bin/sh
set -eu
mountpoint -q /data || exit 1
[ "$(cat /data/.saha-data-layout-version 2>/dev/null || true)" = 1 ] || exit 1
install -d -m 0700 /data/docker /data/models/s2s /data/model-cache/s2s
install -d -m 0755 /data/log/journal /data/log/ros /data/log/app /data/preload
/usr/bin/saha-board-status emit data ready >/dev/null 2>&1 || true
