#!/bin/sh
set -eu

dest_tar=$1
image=${LIVEKIT_AGENT_IMAGE:?}
image_arch=${LIVEKIT_AGENT_IMAGE_ARCH:-arm64}
local_tar=${LIVEKIT_AGENT_LOCAL_TAR:-}
dl_dir=${DL_DIR:-}
cache_name=livekit-agent.tar

if [ -s "$dest_tar" ]; then exit 0; fi
for candidate in "$local_tar" "${dl_dir}/${cache_name}"; do
    if [ -n "$candidate" ] && [ -s "$candidate" ]; then
        cp -- "$candidate" "$dest_tar"
        exit 0
    fi
done

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 && docker image inspect "$image" >/dev/null 2>&1; then
    arch=$(docker image inspect "$image" --format '{{.Architecture}}' 2>/dev/null || true)
    case "$arch" in
        ""|"$image_arch"|arm64|aarch64)
            docker save --output "$dest_tar" "$image"
            if [ -n "$dl_dir" ] && [ -d "$dl_dir" ]; then cp -- "$dest_tar" "${dl_dir}/${cache_name}" || true; fi
            exit 0
            ;;
    esac
fi

echo "ERROR: local image ${image} or ${cache_name} is required" >&2
exit 1
