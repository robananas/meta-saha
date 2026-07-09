#!/bin/sh
set -eu

dest_tar=$1
image=${MATTER_SERVER_CONTAINER_IMAGE:?}
runtime_image=${MATTER_SERVER_CONTAINER_RUNTIME_IMAGE:-ghcr.io/matter-js/python-matter-server:arm64}
image_os=${MATTER_SERVER_CONTAINER_IMAGE_OS:-linux}
image_arch=${MATTER_SERVER_CONTAINER_IMAGE_ARCH:-arm64}
local_tar=${MATTER_SERVER_CONTAINER_LOCAL_TAR:-}
dl_dir=${DL_DIR:-}
skopeo_bin=${SKOPEO_BIN:?}
cache_name=matter-server-container.tar

if [ -s "$dest_tar" ]; then
    echo "NOTE: Reusing existing Matter Server container archive: $dest_tar"
    exit 0
fi

try_local_tar() {
    candidate=$1
    if [ -n "$candidate" ] && [ -s "$candidate" ]; then
        echo "NOTE: Using local Matter Server container archive: $candidate"
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

save_runtime_image() {
    echo "NOTE: Exporting local Docker image as ${runtime_image}"
    docker save --output "$dest_tar" "$runtime_image"
    if [ -n "$dl_dir" ] && [ -d "$dl_dir" ]; then
        cp -- "$dest_tar" "${dl_dir}/${cache_name}" || true
    fi
}

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    if docker image inspect "$runtime_image" >/dev/null 2>&1; then
        save_runtime_image
        exit 0
    fi

    if docker image inspect "$image" >/dev/null 2>&1; then
        echo "NOTE: Tagging ${image} as ${runtime_image}"
        docker tag "$image" "$runtime_image"
        save_runtime_image
        exit 0
    fi
fi

echo "NOTE: Fetching $image for ${image_os}/${image_arch} from registry"
"$skopeo_bin" copy \
    --override-os "$image_os" \
    --override-arch "$image_arch" \
    "docker://${image}" \
    "docker-archive:${dest_tar}:${runtime_image}"

if [ -n "$dl_dir" ] && [ -d "$dl_dir" ]; then
    cp -- "$dest_tar" "${dl_dir}/${cache_name}" || true
fi
