#!/bin/sh
set -eu

dest_tar=$1
image=${LIVEKIT_AGENT_IMAGE:?}
image_arch=${LIVEKIT_AGENT_IMAGE_ARCH:-arm64}
local_tar=${LIVEKIT_AGENT_LOCAL_TAR:-}
dl_dir=${DL_DIR:-}
cache_name=livekit-agent.tar

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
            echo "NOTE: Using validated local LiveKit Agent container archive: $candidate"
            cp -- "$candidate" "$dest_tar"
            exit 0
        fi
    fi
done

if [ -s "$dest_tar" ]; then
    if validate_archive "$dest_tar"; then
        echo "NOTE: Reusing validated LiveKit Agent container archive: $dest_tar"
        exit 0
    fi
    rm -f "$dest_tar"
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1 && docker image inspect "$image" >/dev/null 2>&1; then
    arch=$(docker image inspect "$image" --format '{{.Architecture}}' 2>/dev/null || true)
    case "$arch" in
        "$image_arch"|arm64|aarch64)
            docker save --output "$dest_tar" "$image"
            validate_archive "$dest_tar"
            if [ -n "$dl_dir" ] && [ -d "$dl_dir" ]; then cp -- "$dest_tar" "${dl_dir}/${cache_name}" || true; fi
            exit 0
            ;;
        *)
            echo "WARNING: Local Docker image $image is $arch, expected $image_arch; skipping docker save"
            ;;
    esac
fi

echo "ERROR: validated local image ${image} or ${cache_name} is required" >&2
exit 1
