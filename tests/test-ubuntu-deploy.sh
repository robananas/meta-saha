#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
entry="$root/scripts/saha-ubuntu-deploy"
dir="$root/scripts/ubuntu-deploy"

fail() { echo "FAIL: $*" >&2; exit 1; }
assert_contains() { grep -Fq -- "$2" "$1" || fail "$1 missing $2"; }
assert_not_contains() { ! grep -Fiq -- "$2" "$1" || fail "$1 unexpectedly contains $2"; }

for file in "$entry" "$dir/launcher.sh"; do bash -n "$file"; done
for file in "$dir"/*.py; do python3 -m py_compile "$file"; done

assert_contains "$root/scripts/ubuntu-deploy/host-compat.sh" 'Ubuntu %s %s required'
assert_contains "$entry" 'ROBAN_EXPECTED_VERSION_ID'
assert_contains "$root/scripts/ubuntu-deploy/host-compat.sh" 'ARM64 required'
assert_contains "$entry" 'docker pull --platform linux/arm64'
assert_contains "$entry" 'RepoDigests'
assert_contains "$entry" 'current.new'
assert_contains "$entry" 'if [[ -L $prefix/current ]]'
assert_contains "$entry" 'roban-bluetooth.conf'
assert_contains "$dir/roban-bluetooth.conf" 'MinAdvertisementInterval=0x00a0'
assert_contains "$dir/roban-bluetooth.conf" 'MaxAdvertisementInterval=0x00f0'
assert_contains "$dir/roban-bluetooth-config.conf" '--configfile=/etc/roban-ubuntu/bluetooth.conf'
assert_not_contains "$dir/roban-bluetooth-config.conf" '--experimental'
assert_contains "$entry" 'uninstalled; data retained'
assert_contains "$entry" '--dry-run'
assert_contains "$dir/launcher.sh" '--pull never'
assert_contains "$dir/launcher.sh" 'board-status.py" daemon'
assert_contains "$dir/compose.yaml" 'WORKFLOW_DATABASE_PATH: /data/workflows.db'
assert_contains "$dir/compose.yaml" 'workflow-mcp:'
assert_contains "$dir/compose.yaml" '${IMAGE_WORKFLOW_MCP}'
assert_contains "$entry" 'WORKFLOW_MCP_ACCESS_TOKEN='
assert_contains "$entry" 'WORKFLOW_MCP_PORT=8001'
assert_contains "$entry" 'ROBAN_WORKFLOW_IMAGE_TAG:-20260825-arm64'
assert_contains "$entry" 'ROBAN_WORKFLOW_MCP_IMAGE_TAG:-20260825-domain-arm64'
assert_contains "$entry" 'ROBAN_HA_MCP_IMAGE_TAG:-20260831-token-cache-fix-arm64'
assert_contains "$entry" 'ROBAN_S2S_IMAGE_TAG:-20260831-mcp-url-fix-arm64'
assert_contains "$dir/compose.yaml" 'ROBAN_S2S_IMAGE_PROFILE: realtime-cpu'
assert_contains "$dir/compose.yaml" 'ROBAN_S2S_KWS_PROVIDER: cpu'
assert_contains "$dir/compose.yaml" 'ROBAN_S2S_HA_MCP_CREDENTIALS_PATH: /mcp-secrets/homeassistant.env'
assert_contains "$dir/compose.yaml" 'ROBAN_S2S_WORKFLOW_MCP_CREDENTIALS_PATH: /mcp-secrets/workflow.env'
assert_contains "$dir/compose.yaml" '${ROBAN_ETC_DIR}/home-assistant-mcp-credentials.env:/mcp-secrets/homeassistant.env:ro'
assert_contains "$dir/compose.yaml" '${ROBAN_ETC_DIR}/workflow-mcp-credentials.env:/mcp-secrets/workflow.env:ro'
assert_contains "$dir/compose.yaml" 'ROBAN_S2S_HA_MCP_URL: http://127.0.0.1:${ROBAN_HA_MCP_PORT:-8000}/mcp'
assert_contains "$entry" 'ROBAN_HA_MCP_PORT'
assert_contains "$entry" 'MCP_PORT=$ha_mcp_port'
assert_contains "$entry" 'ip -4 route get 1.1.1.1'
assert_contains "$dir/compose.yaml" 'ROBAN_S2S_WORKFLOW_MCP_URL: http://127.0.0.1:8001/mcp'
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
assert_not_contains "$dir/compose.yaml" 'ROBAN_S2S_HA_MCP_TOKEN:'
assert_not_contains "$dir/compose.yaml" 'ROBAN_S2S_WORKFLOW_MCP_TOKEN:'
assert_contains "$dir/compose.yaml" '${ROBAN_WIFI_INTERFACE}'
assert_not_contains "$dir/compose.yaml" 'ollama'
assert_not_contains "$dir/compose.yaml" 'llama.cpp'
assert_not_contains "$dir/compose.yaml" '.gguf'
assert_not_contains "$dir/compose.yaml" 'cosyvoice'
assert_not_contains "$entry" 'daemon.json'
assert_not_contains "$entry" 'nvidia-ctk runtime configure'
assert_contains "$dir/realtime_manager.py" 'Only Qwen Realtime is installed'
assert_contains "$dir/realtime_manager.py" 'Local models, speakers, and custom voices are not installed'

sandbox=$(mktemp -d)
trap 'rm -rf "$sandbox"' EXIT
mkdir -p "$sandbox/etc" "$sandbox/state" "$sandbox/opt" "$sandbox/units"
output=$(ROBAN_PREFIX="$sandbox/opt" ROBAN_ETC_DIR="$sandbox/etc" ROBAN_STATE_DIR="$sandbox/state" ROBAN_UNIT_DIR="$sandbox/units" ROBAN_LIBEXEC="$sandbox/launcher" "$entry" install --dry-run 2>&1 || true)
[[ $output == *'would install'* || $output == *'Ubuntu 24.04 noble required'* || $output == *'run as root'* ]] || fail "dry-run did not report a plan or host guard"
[[ -z $(find "$sandbox" -type f -print -quit) ]] || fail "dry-run modified sandbox"

echo "Ubuntu deployment contract tests passed"
