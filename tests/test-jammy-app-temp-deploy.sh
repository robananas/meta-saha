#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
entry="$root/scripts/saha-jammy-app-temp-deploy"
dir="$root/scripts/jammy-app-temp"

fail() { echo "FAIL: $*" >&2; exit 1; }
contains() { grep -Fq -- "$2" "$1" || fail "$1 missing $2"; }
not_contains() { ! grep -Fiq -- "$2" "$1" || fail "$1 unexpectedly contains $2"; }

bash -n "$entry" "$dir/launcher.sh"
for file in "$dir"/*.service; do grep -q '^\[Unit\]' "$file"; grep -q '^\[Service\]' "$file"; done
contains "$entry" '10.30.0.41'
contains "$entry" '/home/nvidia/workspace/roban-app-temp'
contains "$entry" 'data-root'
contains "$entry" 'roban-temp-'
contains "$entry" 'home-assistant python-matter-server roban-workflow-api roban-ha-mcp'
contains "$entry" 'roban-s2s'
contains "$entry" 'IMAGE_S2S=${resolved[roban-s2s]}'
contains "$entry" 'roban_temp_cleanup_failed_deploy'
contains "$entry" 'systemctl stop roban-temp-bt-wifi-provision roban-temp-mcp roban-temp-core roban-temp-board-status'
contains "$entry" 'ROBAN_REQUIRED_TCP_PORTS="5580 8000 8001 8080 8123 8765"'
contains "$entry" 'https://mirrors.aliyun.com/docker-ce/linux/ubuntu'
contains "$root/scripts/ubuntu-deploy/host-compat.sh" '9DC858229FC7DD38854AE2D88D81803C0EBFCD88'
contains "$entry" '--registry-auth-file'
contains "$entry" 'DOCKER_CONFIG="$secrets/docker-config" docker pull'
contains "$entry" 'ADVERTISEMENT_CONTROL_PATH = "/run/saha/ble-advertisement-control.json"'
contains "$entry" 'ADVERTISEMENT_STATUS_PATH = "/run/saha/ble-advertisement-status.json"'
contains "$entry" 'SAHA_MATTER_WIFI_PROFILE_UUID'
contains "$entry" 'def sync_matter_wifi_credentials() -> bool:'
contains "$dir/roban-temp-bt-wifi-provision.service" 'matter-wifi.env'
contains "$dir/compose.yaml" 'matter-server:'
contains "$dir/compose.yaml" 'homeassistant:'
contains "$dir/compose.yaml" 'workflow-api:'
contains "$dir/compose.yaml" 'homeassistant-mcp:'
contains "$dir/compose.yaml" 'roban-s2s:'
contains "$dir/compose.yaml" 'ROBAN_S2S_HA_MCP_CREDENTIALS_PATH: /mcp-secrets/homeassistant.env'
contains "$dir/compose.yaml" 'ROBAN_S2S_WORKFLOW_MCP_CREDENTIALS_PATH: /mcp-secrets/workflow.env'
contains "$dir/compose.yaml" '${TEMP_SECRETS_DIR}/home-assistant-mcp-credentials.env:/mcp-secrets/homeassistant.env:ro'
contains "$dir/compose.yaml" '${TEMP_SECRETS_DIR}/workflow-mcp-credentials.env:/mcp-secrets/workflow.env:ro'
contains "$dir/compose.yaml" 'ROBAN_S2S_HA_MCP_URL: http://127.0.0.1:8000/mcp'
contains "$dir/compose.yaml" 'ROBAN_S2S_WORKFLOW_MCP_URL: http://127.0.0.1:8001/mcp'
not_contains "$dir/compose.yaml" 'ROBAN_S2S_HA_MCP_TOKEN:'
not_contains "$dir/compose.yaml" 'ROBAN_S2S_WORKFLOW_MCP_TOKEN:'
not_contains "$dir/compose.yaml" 'livekit'
not_contains "$dir/compose.yaml" 'ollama'
not_contains "$dir/compose.yaml" 'cosyvoice'
not_contains "$entry" 'rm -rf /data'
not_contains "$entry" 'systemctl reboot'
not_contains "$entry" 'docker system prune'
not_contains "$entry" 'docker image prune'

sandbox=$(mktemp -d)
trap 'rm -rf "$sandbox"' EXIT
mkdir -p "$sandbox/bin" "$sandbox/workspace" "$sandbox/root"
cat >"$sandbox/os-release" <<'EOF'
ID=ubuntu
VERSION_ID=22.04
VERSION_CODENAME=jammy
EOF
cat >"$sandbox/bin/uname" <<'EOF'
#!/bin/sh
echo aarch64
EOF
cat >"$sandbox/bin/ip" <<'EOF'
#!/bin/sh
case "$*" in
  *"address show scope global"*) echo 'wlP1p1s0 UP 10.30.0.41/20' ;;
  *"route show default"*) echo 'default via 10.30.0.1 dev wlP1p1s0' ;;
esac
EOF
cat >"$sandbox/bin/systemctl" <<'EOF'
#!/bin/sh
exit 0
EOF
cat >"$sandbox/bin/ss" <<'EOF'
#!/bin/sh
exit 0
EOF
cat >"$sandbox/bin/df" <<'EOF'
#!/bin/sh
printf 'Filesystem 1B-blocks Used Available Use%% Mounted on\nmock 999999999999 1 999999999998 1%% /workspace\n'
EOF
for command in nmcli bluetoothctl dbus-send; do cat >"$sandbox/bin/$command" <<'EOF'
#!/bin/sh
exit 0
EOF
done
chmod +x "$sandbox/bin"/*

before=$(find "$sandbox/root" -mindepth 1 -print | sort)
output=$(PATH="$sandbox/bin:$PATH" ROBAN_SKIP_PYTHON_MODULE_CHECK=1 ROBAN_OS_RELEASE_FILE="$sandbox/os-release" ROBAN_TEMP_WORKSPACE="$sandbox/root/temp" ROBAN_STORAGE_PATH="$sandbox/workspace" "$entry" audit)
[[ $output == *'Target: 10.30.0.41'* ]] || fail "audit target missing"
[[ $output == *'Home Assistant, Matter Server, Workflow API, Home Assistant MCP, Workflow MCP, S2S'* ]] || fail "audit service list missing"
after=$(find "$sandbox/root" -mindepth 1 -print | sort)
[[ $before == "$after" ]] || fail "audit modified filesystem"

set +e
PATH="$sandbox/bin:$PATH" ROBAN_SKIP_PYTHON_MODULE_CHECK=1 ROBAN_OS_RELEASE_FILE="$sandbox/os-release" ROBAN_TEMP_TARGET_IP=10.30.0.99 ROBAN_STORAGE_PATH="$sandbox/workspace" "$entry" audit >/tmp/temp-target.out 2>&1
rc=$?
set -e
((rc != 0)) || fail "wrong target IP was accepted"
grep -q 'restricted to 10.30.0.99' /tmp/temp-target.out || fail "target rejection missing"
rm -f /tmp/temp-target.out

python3 - "$dir/docker-daemon.json" <<'PY'
import json,sys
text=open(sys.argv[1]).read().replace('@DOCKER_ROOT@','/home/nvidia/workspace/roban-app-temp/docker')
value=json.loads(text)
assert value['data-root']=='/home/nvidia/workspace/roban-app-temp/docker'
assert value['log-opts']=={'max-size':'20m','max-file':'5'}
PY
contains "$dir/temp-lib.sh" 'different content; refusing to overwrite'

cat >"$sandbox/bin/systemctl" <<'EOF'
#!/bin/sh
printf 'systemctl %s\n' "$*" >>"$ROBAN_TEMP_CLEANUP_LOG"
exit 0
EOF
cat >"$sandbox/launcher" <<'EOF'
#!/bin/sh
printf 'launcher %s\n' "$*" >>"$ROBAN_TEMP_CLEANUP_LOG"
EOF
chmod +x "$sandbox/bin/systemctl" "$sandbox/launcher"
export ROBAN_TEMP_CLEANUP_LOG="$sandbox/cleanup.log"
PATH="$sandbox/bin:$PATH" ROBAN_TEMP_LAUNCHER="$sandbox/launcher" bash -c 'source "$1"; roban_temp_cleanup_failed_deploy' _ "$dir/temp-lib.sh"
grep -q 'systemctl disable --now roban-temp-' "$sandbox/cleanup.log" || fail "failure cleanup did not disable temporary units"
grep -q 'launcher down' "$sandbox/cleanup.log" || fail "failure cleanup did not tear down compose"

ROBAN_TEMP_LAUNCHER="$sandbox/launcher" bash -c 'source "$1"; roban_temp_write_daemon_config "$2" "$3" "$4"' _ "$dir/temp-lib.sh" "$sandbox/root/daemon-real.json" "$sandbox/root/temp/docker" "$dir/docker-daemon.json"
python3 - "$sandbox/root/daemon-real.json" <<'PY'
import json,sys
value=json.load(open(sys.argv[1])); assert value['data-root'].endswith('/temp/docker')
PY
bash -c 'source "$1"; roban_temp_write_daemon_config "$2" "$3" "$4"' _ "$dir/temp-lib.sh" "$sandbox/root/daemon-real.json" "$sandbox/root/temp/docker" "$dir/docker-daemon.json"
set +e
bash -c 'source "$1"; roban_temp_write_daemon_config "$2" "$3" "$4"' _ "$dir/temp-lib.sh" "$sandbox/root/daemon-real.json" "$sandbox/root/other/docker" "$dir/docker-daemon.json" >/tmp/temp-daemon.out 2>&1
rc=$?
set -e
((rc != 0)) || fail "different daemon config overwrite was accepted"
grep -q 'different content; refusing to overwrite' /tmp/temp-daemon.out || fail "daemon overwrite rejection missing"
rm -f /tmp/temp-daemon.out

mkdir -p "$sandbox/secrets" "$sandbox/state" "$sandbox/runtime" "$sandbox/release"
: >"$sandbox/secrets/home-assistant-mcp.env"
: >"$sandbox/secrets/home-assistant-mcp-credentials.env"
: >"$sandbox/secrets/workflow-mcp.env"
: >"$sandbox/secrets/workflow-mcp-credentials.env"
cat >"$sandbox/images.env" <<EOF
TEMP_RELEASE_DIR=$sandbox/release
TEMP_STATE_DIR=$sandbox/state
TEMP_SECRETS_DIR=$sandbox/secrets
TEMP_RUNTIME_DIR=$sandbox/runtime
TEMP_WIFI_INTERFACE=wlP1p1s0
IMAGE_HOME_ASSISTANT=x/ha@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
IMAGE_MATTER=x/matter@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
IMAGE_WORKFLOW=x/workflow@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
IMAGE_HA_MCP=x/mcp@sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
IMAGE_WORKFLOW_MCP=x/workflow-mcp@sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
IMAGE_S2S=x/s2s@sha256:ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff
EOF
docker compose --env-file "$sandbox/images.env" -f "$dir/compose.yaml" config --quiet
python3 - "$dir/compose.yaml" <<'PY'
import sys
text=open(sys.argv[1]).read()
app=text.split('\n  roban-s2s:\n',1)[1]
depends=app.split('\n    depends_on:\n',1)[1].split('\n    init:',1)[0]
environment=app.split('\n    environment:\n',1)[1].split('\n    volumes:',1)[0]
assert 'network_mode: host' in app
assert 'homeassistant-mcp:' in depends and 'workflow-mcp:' in depends
assert depends.count('condition: service_started') == 2
assert 'TOKEN:' not in environment and 'ACCESS_TOKEN:' not in environment
PY

python3 - <<'PY'
import ast
from pathlib import Path
paths=[Path('saha-layers/meta-tegra-saha/recipes-saha/homeassistant-bootstrap/files/saha-homeassistant-bootstrap.py'),Path('saha-layers/meta-tegra-saha/recipes-saha/board-status/saha-board-status/saha-board-status.py')]
paths += list(Path('saha-layers/meta-tegra-saha/recipes-saha/bt-wifi-provision/saha-bt-wifi-provision').glob('*.py'))
for path in paths: ast.parse(path.read_text(),filename=str(path),feature_version=(3,10))
PY

echo "Jammy temporary App stack contract tests passed"
