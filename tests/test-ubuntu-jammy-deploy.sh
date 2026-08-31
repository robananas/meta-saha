#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
entry="$root/scripts/saha-ubuntu-jammy-deploy"
noble="$root/scripts/saha-ubuntu-deploy"
compat="$root/scripts/ubuntu-deploy/host-compat.sh"
dir="$root/scripts/ubuntu-deploy"

fail() { echo "FAIL: $*" >&2; exit 1; }
assert_contains() { grep -Fq -- "$2" "$1" || fail "$1 missing $2"; }
assert_not_contains() { ! grep -Fiq -- "$2" "$1" || fail "$1 unexpectedly contains $2"; }

for file in "$entry" "$noble" "$compat" "$dir/launcher.sh"; do bash -n "$file"; done
for file in "$dir"/*.py; do python3 -m py_compile "$file"; done

assert_contains "$entry" 'ROBAN_EXPECTED_VERSION_ID=22.04'
assert_contains "$entry" 'ROBAN_EXPECTED_CODENAME=jammy'
assert_contains "$entry" 'ROBAN_SERVICE_PREFIX=roban-jammy'
assert_contains "$entry" 'ROBAN_COMPOSE_PROJECT=roban-jammy'
assert_contains "$entry" '/opt/roban-jammy'
assert_contains "$noble" 'ROBAN_EXPECTED_VERSION_ID:-24.04'
assert_contains "$compat" 'ROBAN_DOCKER_APT_BASE_URL:-https://download.docker.com/linux/ubuntu'
assert_contains "$compat" '%s jammy stable'
assert_contains "$compat" 'simulation=$("$apt_get" -s install docker-ce'
assert_contains "$compat" 'Docker CE installation would remove, downgrade, or replace protected host packages'
assert_contains "$compat" 'ROBAN_MIN_FREE_BYTES'
assert_contains "$entry" '19327352832'
assert_contains "$entry" 'deploy)'
assert_contains "$entry" 'roban_prepare_docker_ce_jammy'
assert_contains "$compat" 'protected process stopped'
assert_contains "$compat" 'required TCP port is already in use'
assert_not_contains "$compat" 'nvidia-ctk runtime configure'
assert_not_contains "$compat" 'data-root'
assert_not_contains "$compat" 'nvidia-ctk runtime configure'
assert_not_contains "$compat" '--allow-downgrades'
assert_not_contains "$compat" '--force-'
assert_contains "$dir/compose.yaml" '${ROBAN_STATE_DIR}'
assert_contains "$dir/compose.yaml" '${ROBAN_ETC_DIR}'
assert_contains "$dir/compose.yaml" 'workflow-mcp:'
assert_contains "$dir/compose.yaml" 'ROBAN_S2S_HA_MCP_CREDENTIALS_PATH: /mcp-secrets/homeassistant.env'
assert_contains "$dir/compose.yaml" 'ROBAN_S2S_WORKFLOW_MCP_CREDENTIALS_PATH: /mcp-secrets/workflow.env'
assert_contains "$dir/compose.yaml" '${ROBAN_ETC_DIR}/home-assistant-mcp-credentials.env:/mcp-secrets/homeassistant.env:ro'
assert_contains "$dir/compose.yaml" '${ROBAN_ETC_DIR}/workflow-mcp-credentials.env:/mcp-secrets/workflow.env:ro'
assert_contains "$noble" 'roban-workflow-mcp'
assert_contains "$noble" 'ROBAN_WORKFLOW_IMAGE_TAG:-20260825-arm64'
assert_contains "$noble" 'ROBAN_WORKFLOW_MCP_IMAGE_TAG:-20260825-domain-arm64'
assert_contains "$noble" 'ROBAN_HA_MCP_IMAGE_TAG:-20260831-token-cache-fix-arm64'
assert_contains "$noble" 'ROBAN_S2S_IMAGE_TAG:-20260831-primary-card-fix-arm64'
assert_contains "$root/scripts/saha-jammy-app-temp-deploy" 'roban-workflow-mcp'
assert_contains "$root/scripts/saha-jammy-app-temp-deploy" 'ROBAN_WORKFLOW_IMAGE_TAG:-20260825-arm64'
assert_contains "$root/scripts/saha-jammy-app-temp-deploy" 'ROBAN_WORKFLOW_MCP_IMAGE_TAG:-20260825-domain-arm64'
assert_contains "$root/scripts/saha-jammy-app-temp-deploy" 'ROBAN_HA_MCP_IMAGE_TAG:-20260831-token-cache-fix-arm64'
assert_contains "$root/scripts/saha-jammy-app-temp-deploy" 'ROBAN_S2S_IMAGE_TAG:-20260831-primary-card-fix-arm64'
assert_contains "$root/scripts/jammy-app-temp/compose.yaml" '${IMAGE_WORKFLOW_MCP}'
assert_contains "$root/scripts/jammy-app-temp/launcher.sh" 'WORKFLOW_MCP_ACCESS_TOKEN='
assert_contains "$dir/launcher.sh" 'service_prefix=${ROBAN_SERVICE_PREFIX'
assert_not_contains "$dir/compose.yaml" 'ollama'
assert_not_contains "$dir/compose.yaml" 'cosyvoice'
assert_not_contains "$dir/compose.yaml" '.gguf'

sandbox=$(mktemp -d)
trap 'rm -rf "$sandbox"' EXIT
mkdir -p "$sandbox/bin" "$sandbox/root"
cat >"$sandbox/os-release" <<'EOF'
ID=ubuntu
VERSION_ID=22.04
VERSION_CODENAME=jammy
EOF

cat >"$sandbox/bin/uname" <<'EOF'
#!/bin/sh
[ "$1" = -m ] && echo aarch64 || /usr/bin/uname "$@"
EOF
cat >"$sandbox/bin/systemctl" <<'EOF'
#!/bin/sh
exit 0
EOF
cat >"$sandbox/bin/nmcli" <<'EOF'
#!/bin/sh
exit 0
EOF
cat >"$sandbox/bin/bluetoothctl" <<'EOF'
#!/bin/sh
exit 0
EOF
cat >"$sandbox/bin/dbus-send" <<'EOF'
#!/bin/sh
exit 0
EOF
cat >"$sandbox/bin/ss" <<'EOF'
#!/bin/sh
exit 0
EOF
cat >"$sandbox/bin/df" <<'EOF'
#!/bin/sh
printf 'Filesystem 1B-blocks Used Available Use%% Mounted on\nmock 99999999999 1 99999999998 1%% /\n'
EOF
cat >"$sandbox/bin/docker" <<'EOF'
#!/bin/sh
exit 127
EOF
chmod +x "$sandbox/bin"/*
: >"$sandbox/gpg"

before=$(find "$sandbox/root" -mindepth 1 -print | sort)
output=$(PATH="$sandbox/bin:$PATH" ROBAN_DOCKER_GPG_FILE="$sandbox/gpg" ROBAN_DPKG_ARCHITECTURE=arm64 ROBAN_FORCE_DOCKER_MISSING=1 ROBAN_SKIP_PYTHON_MODULE_CHECK=1 ROBAN_OS_RELEASE_FILE="$sandbox/os-release" ROBAN_PREFIX="$sandbox/root/opt" ROBAN_ETC_DIR="$sandbox/root/etc" ROBAN_STATE_DIR="$sandbox/root/state" ROBAN_UNIT_DIR="$sandbox/root/units" ROBAN_LIBEXEC="$sandbox/root/launcher" "$entry" prepare-host --dry-run 2>&1)
[[ $output == *'install Docker CE official Jammy repository and packages'* ]] || fail "Jammy prepare-host dry-run did not describe Docker installation"
after=$(find "$sandbox/root" -mindepth 1 -print | sort)
[[ $before == "$after" ]] || fail "Jammy dry-run modified deployment root"

set +e
PATH="$sandbox/bin:$PATH" ROBAN_OS_RELEASE_FILE="$sandbox/os-release" "$noble" install --dry-run >/tmp/noble-on-jammy.out 2>&1
rc=$?
set -e
((rc != 0)) || fail "Noble entry accepted Jammy"
grep -Eq 'Ubuntu 24.04 noble required|run as root' /tmp/noble-on-jammy.out || fail "Noble rejection message missing"
rm -f /tmp/noble-on-jammy.out

set +e
ROBAN_OS_RELEASE_FILE="$sandbox/os-release" ROBAN_EXPECTED_VERSION_ID=24.04 ROBAN_EXPECTED_CODENAME=noble bash -c 'source "$1"; roban_require_platform' _ "$compat" >/tmp/noble-profile.out 2>&1
noble_profile_rc=$?
ROBAN_OS_RELEASE_FILE="$sandbox/os-release" ROBAN_EXPECTED_VERSION_ID=22.04 ROBAN_EXPECTED_CODENAME=jammy bash -c 'source "$1"; roban_require_platform' _ "$compat" >/tmp/jammy-profile.out 2>&1
jammy_profile_rc=$?
set -e
((noble_profile_rc != 0)) || fail "Noble profile accepted Jammy"
((jammy_profile_rc == 0)) || fail "Jammy profile rejected Jammy"
rm -f /tmp/noble-profile.out /tmp/jammy-profile.out

cat >"$sandbox/bin/apt-get-safe" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >>"$ROBAN_APT_LOG"
case " $* " in *" -s "*) echo 'Inst docker-ce (1.0 Docker:stable [arm64])';; esac
EOF
cat >"$sandbox/bin/apt-get-unsafe" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" >>"$ROBAN_APT_LOG"
case " $* " in *" -s "*) echo 'Remv ros-humble-core [1.0]' ;; esac
EOF
chmod +x "$sandbox/bin/apt-get-safe" "$sandbox/bin/apt-get-unsafe"
export ROBAN_APT_LOG="$sandbox/apt.log"
ROBAN_FORCE_DOCKER_MISSING=1 ROBAN_ALLOW_DOCKER_INSTALL=1 ROBAN_SKIP_GPG_FINGERPRINT_CHECK=1 ROBAN_SKIP_DOCKER_POSTCHECK=1 ROBAN_DPKG_ARCHITECTURE=arm64 ROBAN_APT_ROOT="$sandbox/apt" ROBAN_DOCKER_GPG_FILE="$sandbox/gpg" ROBAN_APT_GET="$sandbox/bin/apt-get-safe" bash -c 'source "$1"; roban_prepare_docker_ce_jammy' _ "$compat"
grep -q '^-s install docker-ce' "$sandbox/apt.log" || fail "Docker install did not simulate first"
grep -q '^install -y --no-install-recommends docker-ce' "$sandbox/apt.log" || fail "Docker install did not execute after safe simulation"
: >"$sandbox/apt.log"
set +e
ROBAN_FORCE_DOCKER_MISSING=1 ROBAN_ALLOW_DOCKER_INSTALL=1 ROBAN_SKIP_GPG_FINGERPRINT_CHECK=1 ROBAN_SKIP_DOCKER_POSTCHECK=1 ROBAN_DPKG_ARCHITECTURE=arm64 ROBAN_APT_ROOT="$sandbox/apt-unsafe" ROBAN_DOCKER_GPG_FILE="$sandbox/gpg" ROBAN_APT_GET="$sandbox/bin/apt-get-unsafe" bash -c 'source "$1"; roban_prepare_docker_ce_jammy' _ "$compat" >/tmp/jammy-unsafe.out 2>&1
unsafe_rc=$?
set -e
((unsafe_rc != 0)) || fail "Unsafe apt simulation was accepted"
! grep -q '^install -y' "$sandbox/apt.log" || fail "Unsafe apt simulation reached install"
grep -q 'protected host packages' /tmp/jammy-unsafe.out || fail "Unsafe apt rejection missing"
[[ ! -e $sandbox/apt-unsafe/sources.list.d/docker.list && ! -e $sandbox/apt-unsafe/keyrings/docker.gpg ]] || fail "Unsafe apt simulation left repository files"
rm -f /tmp/jammy-unsafe.out

python3 - <<'PY'
import ast
from pathlib import Path
paths = list(Path('scripts/ubuntu-deploy').glob('*.py'))
paths += [Path('saha-layers/meta-tegra-saha/recipes-saha/homeassistant-bootstrap/files/saha-homeassistant-bootstrap.py')]
paths += list(Path('saha-layers/meta-tegra-saha/recipes-saha/board-status/saha-board-status').glob('*.py'))
paths += list(Path('saha-layers/meta-tegra-saha/recipes-saha/bt-wifi-provision/saha-bt-wifi-provision').glob('*.py'))
for path in paths:
    tree=ast.parse(path.read_text(), filename=str(path), feature_version=(3,10))
    assert not any(isinstance(node, ast.Match) for node in ast.walk(tree)), path
PY

echo "Jammy deployment contract tests passed"
