#!/bin/sh
set -eu

dest_tar=$1
image=${ROBAN_WORKFLOW_IMAGE:?}
image_os=${ROBAN_WORKFLOW_IMAGE_OS:-linux}
image_arch=${ROBAN_WORKFLOW_IMAGE_ARCH:-arm64}
local_tar=${ROBAN_WORKFLOW_LOCAL_TAR:-}
dl_dir=${DL_DIR:-}
cache_name=roban-workflow-api.tar

if [ -s "$dest_tar" ]; then
    echo "NOTE: Reusing existing Roban workflow container archive: $dest_tar"
    exit 0
fi

try_local_tar() {
    candidate=$1
    if [ -n "$candidate" ] && [ -s "$candidate" ]; then
        echo "NOTE: Using local Roban workflow container archive: $candidate"
        cp -- "$candidate" "$dest_tar"
        return 0
    fi
    return 1
}

if try_local_tar "$local_tar"; then
    exit 0
fi

if try_local_tar "${dl_dir}/${cache_name}"; then
    exit 0
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    if docker image inspect "$image" >/dev/null 2>&1; then
        arch=$(docker image inspect "$image" --format '{{.Architecture}}' 2>/dev/null || true)
        case "$arch" in
            ""|"$image_arch"|arm64|aarch64)
                echo "NOTE: Exporting local Docker image: $image"
                docker save --output "$dest_tar" "$image"
                if [ -n "$dl_dir" ] && [ -d "$dl_dir" ]; then
                    cp -- "$dest_tar" "${dl_dir}/${cache_name}" || true
                fi
                exit 0
                ;;
            *)
                echo "WARNING: Local Docker image $image is $arch, expected $image_arch; skipping docker save"
                ;;
        esac
    fi
fi

echo "ERROR: Local image ${image} or archive ${cache_name} is required for roban-workflow-api"
exit 1
