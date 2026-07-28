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

validate_archive() {
    archive=$1
    python3 - "$archive" "$image_arch" "$image" <<'PY'
import json
import sys
import tarfile

path, expected_arch, expected_tag = sys.argv[1:]
try:
    with tarfile.open(path) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        if len(manifest) != 1:
            raise ValueError(f"expected one image, found {len(manifest)}")
        entry = manifest[0]
        config = json.load(archive.extractfile(entry["Config"]))
    arch = config.get("architecture")
    if arch not in {expected_arch, "arm64", "aarch64"}:
        raise ValueError(f"architecture is {arch!r}, expected {expected_arch!r}")
    tags = entry.get("RepoTags") or []
    if expected_tag not in tags:
        raise ValueError(f"tags {tags!r} do not contain {expected_tag!r}")
except Exception as err:
    print(f"WARNING: Rejecting container archive {path}: {err}", file=sys.stderr)
    raise SystemExit(1)
PY
}

for candidate in "$local_tar" "${dl_dir}/${cache_name}"; do
    if [ -n "$candidate" ] && [ -s "$candidate" ]; then
        if validate_archive "$candidate"; then
            echo "NOTE: Using validated local LiveKit Server container archive: $candidate"
            cp -- "$candidate" "$dest_tar"
            exit 0
        fi
    fi
done

if [ -s "$dest_tar" ]; then
    if validate_archive "$dest_tar"; then
        echo "NOTE: Reusing validated LiveKit Server container archive: $dest_tar"
        exit 0
    fi
    rm -f "$dest_tar"
fi

"$skopeo_bin" copy --override-os "$image_os" --override-arch "$image_arch" \
    "docker://${image}" "docker-archive:${dest_tar}:${image}"
validate_archive "$dest_tar"
if [ -n "$dl_dir" ] && [ -d "$dl_dir" ]; then
    cp -- "$dest_tar" "${dl_dir}/${cache_name}" || true
fi
