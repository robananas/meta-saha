#!/usr/bin/env bash
set -euo pipefail
prefix=${ROBAN_PREFIX:-/opt/roban-ubuntu}
etc_dir=${ROBAN_ETC_DIR:-/etc/roban-ubuntu}
state_dir=${ROBAN_STATE_DIR:-/var/lib/roban-ubuntu}
compose_project=${ROBAN_COMPOSE_PROJECT:-roban-ubuntu}
service_prefix=${ROBAN_SERVICE_PREFIX:-roban}
compose=(docker compose --project-name "$compose_project" --env-file "$etc_dir/images.env" -f "$prefix/current/compose.yaml")

wait_http() {
  local url=$1 timeout=${2:-180} elapsed=0
  until curl -fsS "$url" >/dev/null 2>&1; do
    ((elapsed >= timeout)) && return 1
    sleep 2; elapsed=$((elapsed+2))
  done
}

case "${1:-}" in
  data-layout)
    install -d -m 0755 /run/saha/board-status /data/saha "$state_dir" "$state_dir/workflow" "$state_dir/models/s2s" "$state_dir/model-config/s2s" "$state_dir/model-cache/s2s" "$state_dir/voiceprints" /var/lib/homeassistant /var/lib/matter-server
    install -d -m 0700 "$state_dir/homeassistant"
    install -d -m 0750 -o root -g 999 "$etc_dir/s2s-secrets"
    test ! -f "$etc_dir/s2s-secrets/dashscope-api-key" || { chown root:999 "$etc_dir/s2s-secrets/dashscope-api-key"; chmod 0640 "$etc_dir/s2s-secrets/dashscope-api-key"; }
    ln -sfn "$state_dir/homeassistant" /data/saha/homeassistant
    ;;
  core-start)
    "${compose[@]}" up -d --pull never matter-server homeassistant roban-workflow-api livekit-server livekit-agent
    wait_http http://127.0.0.1:8123/ 300
    wait_http http://127.0.0.1:8080/health 120
    ;;
  core-stop) "${compose[@]}" stop livekit-agent livekit-server roban-workflow-api homeassistant matter-server ;;
  bootstrap)
    mkdir -p "$state_dir/homeassistant"
    SAHA_HOMEASSISTANT_STATE_DIR="$state_dir/homeassistant" python3 "$prefix/current/ha-bootstrap.py"
    ;;
  edge-start)
    test -s "$state_dir/homeassistant/app-credentials.json"
    "${compose[@]}" up -d --pull never homeassistant-mcp roban-s2s
    wait_http http://127.0.0.1:8765/ready 120
    ;;
  edge-stop) "${compose[@]}" stop roban-s2s homeassistant-mcp ;;
  manager)
    exec env ROBAN_EDGE_SERVICE="$service_prefix-edge.service" SAHA_MODEL_ROOT="$state_dir/models/s2s" SAHA_MODEL_SELECTION="$state_dir/model-config/s2s/selection.json" SAHA_PIPELINE_MODE="$state_dir/model-config/s2s/pipeline-mode.json" SAHA_REALTIME_SETTINGS="$state_dir/model-config/s2s/realtime-settings.json" SAHA_DASHSCOPE_API_KEY_PATH="$etc_dir/s2s-secrets/dashscope-api-key" SAHA_DASHSCOPE_WORKSPACE_ID_PATH="$state_dir/model-config/s2s/dashscope-workspace-id" SAHA_MODEL_MANAGER_HOST=0.0.0.0 SAHA_MODEL_MANAGER_PORT=11435 python3 "$prefix/current/realtime-manager.py"
    ;;
  board-status) exec python3 "$prefix/current/board-status.py" daemon ;;
  ble)
    export PYTHONPATH="$prefix/current/ble"
    exec python3 "$prefix/current/ble/saha-bt-wifi-provision.py"
    ;;
  start) systemctl start "$service_prefix-data-layout" "$service_prefix-board-status" "$service_prefix-core" "$service_prefix-ha-bootstrap" "$service_prefix-edge" "$service_prefix-realtime-manager" "$service_prefix-bt-wifi-provision" ;;
  stop) systemctl stop "$service_prefix-bt-wifi-provision" "$service_prefix-realtime-manager" "$service_prefix-edge" "$service_prefix-ha-bootstrap" "$service_prefix-core" "$service_prefix-board-status" ;;
  restart) systemctl restart "$service_prefix-core" "$service_prefix-ha-bootstrap" "$service_prefix-edge" "$service_prefix-realtime-manager" "$service_prefix-bt-wifi-provision" ;;
  status)
    systemctl --no-pager --full status "$service_prefix-board-status" "$service_prefix-core" "$service_prefix-ha-bootstrap" "$service_prefix-edge" "$service_prefix-realtime-manager" "$service_prefix-bt-wifi-provision" || true
    "${compose[@]}" ps
    ;;
  verify)
    source "$etc_dir/images.env"
    docker compose --project-name roban-ubuntu --env-file "$etc_dir/images.env" -f "$prefix/current/compose.yaml" config --quiet
    [[ $(uname -m) == aarch64 ]]
    for url in http://127.0.0.1:8123/ http://127.0.0.1:8080/health http://127.0.0.1:8765/ready http://127.0.0.1:11435/health; do wait_http "$url" 30; done
    python3 - <<'PY'
import json, urllib.request
ready=json.load(urllib.request.urlopen('http://127.0.0.1:8765/ready'))
assert ready['ready'] and ready['effectiveMode']=='realtime' and ready['effectiveProvider']=='qwen', ready
PY
    echo VERIFIED
    ;;
  *) echo "usage: $0 {data-layout|core-start|core-stop|bootstrap|edge-start|edge-stop|manager|board-status|ble|start|stop|restart|status|verify}" >&2; exit 2 ;;
esac
