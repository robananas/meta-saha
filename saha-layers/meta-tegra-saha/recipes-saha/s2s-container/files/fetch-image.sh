#!/bin/sh
set -eu

dest_tar=$1
image=${S2S_IMAGE:?}
image_arch=${S2S_IMAGE_ARCH:-arm64}
local_tar=${S2S_LOCAL_TAR:-}
dl_dir=${DL_DIR:-}
cache_name=roban-s2s.tar

validate_archive() {
    archive=$1
    python3 - "$archive" "$image_arch" "$image" <<'PY'
import json
import sys
import tarfile

path, expected_arch, expected_tag = sys.argv[1:]
try:
    with tarfile.open(path) as archive:
        manifest_file = archive.extractfile("manifest.json")
        if manifest_file is None:
            raise ValueError("manifest.json is missing")
        manifest = json.load(manifest_file)
        if len(manifest) != 1:
            raise ValueError(f"expected one image, found {len(manifest)}")
        entry = manifest[0]
        config_file = archive.extractfile(entry["Config"])
        if config_file is None:
            raise ValueError("image config is missing")
        config = json.load(config_file)
    arch = config.get("architecture")
    if arch not in {expected_arch, "arm64", "aarch64"}:
        raise ValueError(f"architecture is {arch!r}, expected {expected_arch!r}")
    tags = entry.get("RepoTags") or []
    if expected_tag not in tags:
        raise ValueError(f"tags {tags!r} do not contain {expected_tag!r}")
except Exception as err:
    print(f"WARNING: Rejecting S2S container archive {path}: {err}", file=sys.stderr)
    raise SystemExit(1)
PY
}

for candidate in "$local_tar" "${dl_dir}/${cache_name}"; do
    if [ -n "$candidate" ] && [ -s "$candidate" ] && validate_archive "$candidate"; then
        echo "NOTE: Using validated local S2S container archive: $candidate"
        cp -- "$candidate" "$dest_tar"
        exit 0
    fi
done

if [ -s "$dest_tar" ]; then
    if validate_archive "$dest_tar"; then
        echo "NOTE: Reusing validated S2S container archive: $dest_tar"
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
            if [ -n "$dl_dir" ] && [ -d "$dl_dir" ]; then
                cp -- "$dest_tar" "${dl_dir}/${cache_name}" || true
            fi
            exit 0
            ;;
        *)
            echo "WARNING: Local Docker image $image is $arch, expected $image_arch; skipping docker save" >&2
            ;;
    esac
fi

echo "ERROR: validated local image ${image} or ${cache_name} is required; network pulls are disabled" >&2
exit 1
