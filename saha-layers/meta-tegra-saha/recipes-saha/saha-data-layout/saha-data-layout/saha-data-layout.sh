#!/bin/sh
set -eu
mountpoint -q /data || exit 1
[ "$(cat /data/.saha-data-layout-version 2>/dev/null || true)" = 1 ] || exit 1
install -d -m 0700 /data/docker /data/containerd /data/swap /data/saha
for name in homeassistant homeassistant-mcp; do
    persistent="/data/saha/$name"
    legacy="/var/lib/saha/$name"
    install -d -m 0700 /var/lib/saha
    if [ -d "$legacy" ] && [ ! -L "$legacy" ]; then
        if [ -e "$persistent" ]; then
            [ -z "$(ls -A "$legacy")" ] || exit 1
            rmdir "$legacy"
        else
            mv "$legacy" "$persistent"
        fi
    fi
    install -d -m 0700 "$persistent"
    if [ ! -e "$legacy" ]; then
        ln -s "$persistent" "$legacy"
    fi
    [ "$(readlink -f "$legacy")" = "$persistent" ] || exit 1
    chmod 0700 "$persistent"
done
install -d -o 10002 -g 999 -m 0750 /data/models/s2s /data/models/s2s/stt /data/models/s2s/llm /data/models/s2s/tts /data/models/s2s/speaker /data/model-cache/s2s /data/tools
install -d -o 10003 -g 998 -m 0750 /data/model-cache/s2s/cosyvoice3
install -d /data/voiceprints /data/voiceprints/s2s
chown 10002:999 /data/voiceprints /data/voiceprints/s2s
chmod 0700 /data/voiceprints /data/voiceprints/s2s
install -d -o 0 -g 0 -m 0750 /data/model-cache/s2s-model-manager
install -d -o 0 -g 999 -m 2750 /data/model-config/s2s /data/model-config/s2s/voices
install -d -m 0755 /data/log/journal /data/log/ros /data/log/app /data/preload /run/log/journal
/usr/bin/saha-board-status emit data ready >/dev/null 2>&1 || true
