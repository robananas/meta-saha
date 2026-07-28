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

validate_archive() {
    archive=$1
    python3 - "$archive" "$image_arch" "$runtime_image" <<'PY'
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

try_local_tar() {
    candidate=$1
    if [ -n "$candidate" ] && [ -s "$candidate" ]; then
        if ! validate_archive "$candidate"; then
            return 1
        fi
        echo "NOTE: Using validated local Matter Server container archive: $candidate"
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

if [ -s "$dest_tar" ]; then
    if validate_archive "$dest_tar"; then
        echo "NOTE: Reusing validated Matter Server container archive: $dest_tar"
        exit 0
    fi
    rm -f "$dest_tar"
fi

save_runtime_image() {
    echo "NOTE: Exporting local Docker image as ${runtime_image}"
    docker save --output "$dest_tar" "$runtime_image"
    validate_archive "$dest_tar"
    if [ -n "$dl_dir" ] && [ -d "$dl_dir" ]; then
        cp -- "$dest_tar" "${dl_dir}/${cache_name}" || true
    fi
}

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    if docker image inspect "$runtime_image" >/dev/null 2>&1; then
        arch=$(docker image inspect "$runtime_image" --format '{{.Architecture}}' 2>/dev/null || true)
        case "$arch" in
            "$image_arch"|arm64|aarch64)
                save_runtime_image
                exit 0
                ;;
            *)
                echo "WARNING: Local Docker image $runtime_image is $arch, expected $image_arch; skipping docker save"
                ;;
        esac
    fi

    if docker image inspect "$image" >/dev/null 2>&1; then
        arch=$(docker image inspect "$image" --format '{{.Architecture}}' 2>/dev/null || true)
        case "$arch" in
            "$image_arch"|arm64|aarch64)
                echo "NOTE: Tagging ${image} as ${runtime_image}"
                docker tag "$image" "$runtime_image"
                save_runtime_image
                exit 0
                ;;
            *)
                echo "WARNING: Local Docker image $image is $arch, expected $image_arch; skipping docker save"
                ;;
        esac
    fi
fi

echo "NOTE: Fetching $image for ${image_os}/${image_arch} from registry"
"$skopeo_bin" copy \
    --override-os "$image_os" \
    --override-arch "$image_arch" \
    "docker://${image}" \
    "docker-archive:${dest_tar}:${runtime_image}"
validate_archive "$dest_tar"

if [ -n "$dl_dir" ] && [ -d "$dl_dir" ]; then
    cp -- "$dest_tar" "${dl_dir}/${cache_name}" || true
fi
