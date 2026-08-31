#!/bin/sh
set -eu

output=$1
image=${MCP_IMAGE:-roban-ha-mcp:20260831-token-cache-fix-arm64}
image_arch=${MCP_IMAGE_ARCH:-arm64}
archive=${MCP_LOCAL_TAR:-}

validate_archive() {
    candidate=$1
    python3 - "$candidate" "$image_arch" "$image" <<'PY'
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
    architecture = config.get("architecture")
    if architecture not in {expected_arch, "arm64", "aarch64"}:
        raise ValueError(f"architecture is {architecture!r}, expected {expected_arch!r}")
    if expected_tag not in (entry.get("RepoTags") or []):
        raise ValueError(f"archive does not contain expected tag {expected_tag!r}")
except Exception as error:
    print(f"Rejecting MCP container archive {path}: {error}", file=sys.stderr)
    raise SystemExit(1)
PY
}

if [ -z "$archive" ] || [ ! -s "$archive" ]; then
    echo "Missing validated local MCP image archive: $archive" >&2
    exit 1
fi
validate_archive "$archive"
cp -- "$archive" "$output"
