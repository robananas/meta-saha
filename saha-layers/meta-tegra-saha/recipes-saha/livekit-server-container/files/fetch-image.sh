#!/bin/sh
set -eu

dest_tar=$1
image=${LIVEKIT_SERVER_IMAGE:?}
image_os=${LIVEKIT_SERVER_IMAGE_OS:-linux}
image_arch=${LIVEKIT_SERVER_IMAGE_ARCH:-arm64}
local_tar=${LIVEKIT_SERVER_LOCAL_TAR:-}
dl_dir=${DL_DIR:-}
skopeo_bin=${SKOPEO_BIN:-skopeo}
cache_name=livekit-server-container.tar

if [ -s "$dest_tar" ]; then exit 0; fi
for candidate in "$local_tar" "${dl_dir}/${cache_name}"; do
    if [ -n "$candidate" ] && [ -s "$candidate" ]; then
        cp -- "$candidate" "$dest_tar"
        exit 0
    fi
done

"$skopeo_bin" copy --override-os "$image_os" --override-arch "$image_arch" \
    "docker://${image}" "docker-archive:${dest_tar}:${image}"
if [ -n "$dl_dir" ] && [ -d "$dl_dir" ]; then
    cp -- "$dest_tar" "${dl_dir}/${cache_name}" || true
fi
