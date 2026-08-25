#!/usr/bin/env bash
set -euo pipefail

root=${ROBAN_TEMP_ROOT:-/home/nvidia/workspace/roban-app-temp}
release=${ROBAN_TEMP_RELEASE_DIR:-$root/current}
state=${ROBAN_TEMP_STATE_DIR:-$root/state}
secrets=${ROBAN_TEMP_SECRETS_DIR:-$root/secrets}
runtime=${ROBAN_TEMP_RUNTIME_DIR:-$root/runtime}
env_file=${ROBAN_TEMP_ENV_FILE:-$root/config/images.env}
project=${ROBAN_TEMP_PROJECT:-roban-app-temp}
compose=(docker compose --project-name "$project" --env-file "$env_file" -f "$release/compose.yaml")

wait_tcp() {
  local host=$1 port=$2 timeout=${3:-60} elapsed=0
  until timeout 1 bash -c "</dev/tcp/$host/$port" 2>/dev/null; do
    ((elapsed >= timeout)) && return 1
    sleep 1
    elapsed=$((elapsed + 1))
  done
}

wait_http() {
  local url=$1 timeout=${2:-180} elapsed=0
  until curl -fsS "$url" >/dev/null 2>&1; do
    ((elapsed >= timeout)) && return 1
    sleep 2
    elapsed=$((elapsed + 2))
  done
}

case "${1:-}" in
  data-layout)
    install -d -m 0755 "$root" "$state" "$state/homeassistant-config" "$state/matter-server/credentials" "$state/workflow" "$state/models/s2s" "$state/model-config/s2s" "$state/model-cache/s2s" "$state/voiceprints" "$runtime" "$runtime/board-status" "$root/config"
    install -d -m 0700 "$state/homeassistant-credentials" "$state/workflow-mcp" "$secrets"
    ;;
  core-start)
    "${compose[@]}" up -d --pull never matter-server homeassistant workflow-api
    wait_http http://127.0.0.1:8123/ 300
    wait_http http://127.0.0.1:8080/health 120
    ;;
  core-stop)
    "${compose[@]}" stop workflow-api homeassistant matter-server
    ;;
  bootstrap)
    exec python3 "$release/ha-bootstrap.py"
    ;;
  mcp-start)
    test -s "$state/homeassistant-credentials/app-credentials.json"
    test -s "$secrets/workflow-mcp-credentials.env"
    "${compose[@]}" up -d --pull never homeassistant-mcp workflow-mcp
    wait_tcp 127.0.0.1 8000 60
    wait_tcp 127.0.0.1 8001 60
    "${compose[@]}" up -d --pull never roban-s2s
    wait_http http://127.0.0.1:8765/health 120
    ;;
  mcp-stop)
    "${compose[@]}" stop roban-s2s workflow-mcp homeassistant-mcp
    ;;
  board-status)
    exec env SAHA_BOARD_STATUS_DIR="$runtime/board-status" python3 "$release/board-status.py" daemon
    ;;
  ble)
    export PYTHONPATH="$release/ble"
    export SAHA_MATTER_WIFI_CREDENTIALS="$runtime/matter-wifi.json"
    exec python3 "$release/ble/saha-bt-wifi-provision.py"
    ;;
  verify)
    "${compose[@]}" config --quiet
    wait_http http://127.0.0.1:8123/ 30
    wait_http http://127.0.0.1:8080/health 30
    timeout 3 bash -c '</dev/tcp/127.0.0.1/5580'
    test -s "$state/homeassistant-credentials/app-credentials.json"
    test -S "$runtime/board-status/events.sock"
    test -s "$runtime/matter-wifi.json"
    test -d "$state/homeassistant-config/custom_components/xiaomi_home"
    test -d "$state/homeassistant-config/custom_components/saha_matter"
    unauth=
    token=
    auth_code=
    unauth=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8000/mcp || true)
    [[ $unauth == 401 ]]
    token=$(sed -n 's/^MCP_ACCESS_TOKEN=//p' "$secrets/home-assistant-mcp-credentials.env")
    auth_code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 -H "Authorization: Bearer $token" http://127.0.0.1:8000/mcp || true)
    [[ $auth_code == 200 ]]
    unauth=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8001/mcp || true)
    [[ $unauth == 401 ]]
    token=$(sed -n 's/^WORKFLOW_MCP_ACCESS_TOKEN=//p' "$secrets/workflow-mcp-credentials.env")
    auth_code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 3 -H "Authorization: Bearer $token" http://127.0.0.1:8001/mcp || true)
    [[ $auth_code == 200 ]]
    python3 - <<'PY'
import json, os, urllib.request
root=os.environ.get('ROBAN_TEMP_ROOT','/home/nvidia/workspace/roban-app-temp')
credential=json.load(open(root+'/state/homeassistant-credentials/app-credentials.json'))
assert credential['version']==1 and credential['tokenType']=='Bearer'
request=urllib.request.Request('http://127.0.0.1:8123/api/',headers={'Authorization':'Bearer '+credential['accessToken']})
assert urllib.request.urlopen(request,timeout=5).status==200
workflow=json.load(urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=5))
assert workflow['ok'] and workflow['databasePath']=='/data/workflows.db'
PY
    echo TEMP_STACK_VERIFIED
    ;;
  status)
    "${compose[@]}" ps
    ;;
  start)
    systemctl start roban-temp-data-layout roban-temp-board-status roban-temp-core roban-temp-ha-bootstrap roban-temp-mcp roban-temp-bt-wifi-provision
    ;;
  stop)
    systemctl stop roban-temp-bt-wifi-provision roban-temp-mcp roban-temp-ha-bootstrap roban-temp-core roban-temp-board-status
    ;;
  restart)
    systemctl restart roban-temp-core roban-temp-ha-bootstrap roban-temp-mcp roban-temp-bt-wifi-provision
    ;;
  down)
    "${compose[@]}" down --remove-orphans
    ;;
  *)
    echo "usage: $0 {data-layout|core-start|core-stop|bootstrap|mcp-start|mcp-stop|board-status|ble|verify|status|start|stop|restart|down}" >&2
    exit 2
    ;;
esac
