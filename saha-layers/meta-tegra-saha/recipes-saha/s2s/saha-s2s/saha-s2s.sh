#!/bin/sh
set -eu

ENV_FILE=/etc/default/saha-s2s
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    . "$ENV_FILE"
fi
SAHA_S2S_COMPOSE_DIR=${SAHA_S2S_COMPOSE_DIR:-/opt/roban/s2s}
SAHA_S2S_COMPOSE_FILE=${SAHA_S2S_COMPOSE_FILE:-${SAHA_S2S_COMPOSE_DIR}/compose.yaml}
SAHA_S2S_PROJECT=${SAHA_S2S_PROJECT:-saha-s2s}
SAHA_S2S_IMAGE=${SAHA_S2S_IMAGE:-roban-s2s:20260831-media-control-fix-arm64}
SAHA_S2S_IMAGE_TAR=${SAHA_S2S_IMAGE_TAR:-/data/preload/s2s/image.tar}
SAHA_DOCKER_LOAD_LOCK=${SAHA_DOCKER_LOAD_LOCK:-/run/lock/saha-docker-load.lock}
SAHA_S2S_PORT=${SAHA_S2S_PORT:-8765}
SAHA_S2S_WAIT=${SAHA_S2S_WAIT:-120}
SAHA_COSYVOICE_IMAGE=${SAHA_COSYVOICE_IMAGE:-roban-cosyvoice:arm64}
SAHA_COSYVOICE_IMAGE_TAR=${SAHA_COSYVOICE_IMAGE_TAR:-/data/preload/cosyvoice/image.tar}
SAHA_COSYVOICE_PORT=${SAHA_COSYVOICE_PORT:-8766}
SAHA_COSYVOICE_WAIT=${SAHA_COSYVOICE_WAIT:-300}
ROBAN_S2S_MODEL_MANIFEST=${ROBAN_S2S_MODEL_MANIFEST:-/data/models/s2s/manifest.sha256}
export SAHA_S2S_IMAGE SAHA_S2S_PORT SAHA_COSYVOICE_IMAGE SAHA_COSYVOICE_PORT HF_ENDPOINT PIP_INDEX_URL ROBAN_S2S_ICE_SERVERS
export ROBAN_S2S_KWS_PROVIDER ROBAN_S2S_VAD_PROVIDER ROBAN_S2S_STT_PROVIDER ROBAN_S2S_TTS_PROVIDER
export ROBAN_S2S_PIPELINE_FACTORY

log() {
    logger -t saha-s2s "$*"
}

compose() {
    docker compose --project-name "$SAHA_S2S_PROJECT" -f "$SAHA_S2S_COMPOSE_FILE" "$@"
}

wait_for_docker() {
    waited=0
    while [ "$waited" -lt "$SAHA_S2S_WAIT" ]; do
        docker info >/dev/null 2>&1 && return 0
        sleep 2
        waited=$((waited + 2))
    done
    log "docker daemon not ready after ${SAHA_S2S_WAIT}s"
    return 1
}

ensure_named_image() {
    image=$1
    archive=$2
    if docker image inspect "$image" >/dev/null 2>&1; then
        return 0
    fi
    if [ ! -s "$archive" ]; then
        log "required offline image archive is missing: ${archive}"
        return 1
    fi
    # Serialize with saha-docker-compose: concurrent docker load races containerd ingest.
    mkdir -p "$(dirname "$SAHA_DOCKER_LOAD_LOCK")"
    flock "$SAHA_DOCKER_LOAD_LOCK" docker load -i "$archive" >/dev/null
    docker image inspect "$image" >/dev/null 2>&1
}

ensure_image() {
    ensure_named_image "$SAHA_S2S_IMAGE" "$SAHA_S2S_IMAGE_TAR"
}

verify_models() {
    if [ ! -s "$ROBAN_S2S_MODEL_MANIFEST" ]; then
        log "model manifest is not provisioned yet: ${ROBAN_S2S_MODEL_MANIFEST}"
        return 0
    fi
    model_root=$(dirname "$ROBAN_S2S_MODEL_MANIFEST")
    (cd "$model_root" && sha256sum -c "$(basename "$ROBAN_S2S_MODEL_MANIFEST")")
}

start_service() {
    mountpoint -q /data
    mkdir -p /data/models/s2s/stt /data/models/s2s/llm /data/models/s2s/tts /data/model-cache/s2s /data/model-config/s2s /data/model-secrets/s2s
    chown root:999 /data/model-secrets /data/model-secrets/s2s
    chmod 0750 /data/model-secrets /data/model-secrets/s2s
    for secret in sub2api.token dashscope-api-key; do
        path="/data/model-secrets/s2s/$secret"
        if [ -e "$path" ]; then
            test -f "$path" && test ! -L "$path"
            chown root:999 "$path"
            chmod 0640 "$path"
        fi
    done
    workspace=/data/model-config/s2s/dashscope-workspace-id
    if [ -e "$workspace" ]; then
        test -f "$workspace" && test ! -L "$workspace"
        workspace_id=$(dd if="$workspace" bs=129 count=1 2>/dev/null)
        test -n "$workspace_id" && test "${#workspace_id}" -le 128
        case "$workspace_id" in *[!A-Za-z0-9_-]* ) log "invalid DashScope workspace ID"; return 1 ;; esac
        case "$workspace_id" in [A-Za-z0-9]* ) ;; * ) log "invalid DashScope workspace ID"; return 1 ;; esac
        chown root:999 "$workspace"
        chmod 0640 "$workspace"
    fi
    verify_models
    ensure_image
    cd "$SAHA_S2S_COMPOSE_DIR"
    compose up -d --pull never
    log "S2S started on TCP ${SAHA_S2S_PORT}; host networking permits aiortc ICE UDP candidates"
}

stop_service() {
    cd "$SAHA_S2S_COMPOSE_DIR"
    compose down
}

restart_service() {
    cd "$SAHA_S2S_COMPOSE_DIR"
    compose stop roban-s2s
    compose rm -f roban-s2s
    wait_for_docker
    verify_models
    ensure_image
    compose up -d --pull never --no-deps roban-s2s
    log "S2S restarted without changing optional sidecars"
}

wait_http() {
    url=$1
    limit=$2
    waited=0
    while [ "$waited" -lt "$limit" ]; do
        curl -fsS "$url" >/dev/null 2>&1 && return 0
        sleep 2
        waited=$((waited + 2))
    done
    log "health endpoint not ready after ${limit}s: ${url}"
    return 1
}

start_cosyvoice() {
    mountpoint -q /data
    ensure_named_image "$SAHA_COSYVOICE_IMAGE" "$SAHA_COSYVOICE_IMAGE_TAR"
    cosy_model_dir=/data/models/s2s/tts/cosyvoice3/Fun-CosyVoice3-0.5B-2512
    test -s "$cosy_model_dir/manifest.sha256"
    (cd "$cosy_model_dir" && sha256sum -c manifest.sha256)
    mkdir -p /data/model-cache/s2s/cosyvoice3 /data/model-config/s2s/voices
    chmod 0755 /data/model-config/s2s
    chmod 2750 /data/model-config/s2s/voices
    for voice_dir in /data/model-config/s2s/voices/user-*; do
        test -d "$voice_dir" || continue
        chmod 2750 "$voice_dir"
        chmod 0640 "$voice_dir/profile.json" "$voice_dir/reference.wav"
    done
    cd "$SAHA_S2S_COMPOSE_DIR"
    compose --profile cosyvoice up -d --pull never --no-deps roban-cosyvoice
    if ! wait_http "http://127.0.0.1:${SAHA_COSYVOICE_PORT}/health" "$SAHA_COSYVOICE_WAIT"; then
        compose --profile cosyvoice stop roban-cosyvoice >/dev/null 2>&1 || true
        return 1
    fi
    log "CosyVoice sidecar ready on loopback TCP ${SAHA_COSYVOICE_PORT}"
}

stop_cosyvoice() {
    cd "$SAHA_S2S_COMPOSE_DIR"
    compose --profile cosyvoice stop roban-cosyvoice
    compose --profile cosyvoice rm -f roban-cosyvoice
    log "CosyVoice sidecar stopped; GPU allocation released"
}

case ${1:-} in
    wait-docker) wait_for_docker ;;
    start) wait_for_docker; start_service ;;
    stop) stop_service ;;
    restart) restart_service ;;
    status) curl -fsS "http://127.0.0.1:${SAHA_S2S_PORT}/ready" ;;
    cosy-start) wait_for_docker; start_cosyvoice ;;
    cosy-stop) stop_cosyvoice ;;
    cosy-status) curl -fsS "http://127.0.0.1:${SAHA_COSYVOICE_PORT}/health" ;;
    *) echo "Usage: $0 {wait-docker|start|stop|restart|status|cosy-start|cosy-stop|cosy-status}" >&2; exit 2 ;;
esac
