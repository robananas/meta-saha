#!/bin/sh
set -eu

ENV_FILE=/etc/default/saha-s2s
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    . "$ENV_FILE"
fi
OLLAMA_MODEL_ENV=/data/model-config/s2s/ollama.env
if [ -f "$OLLAMA_MODEL_ENV" ]; then
    # shellcheck disable=SC1090
    . "$OLLAMA_MODEL_ENV"
fi

SAHA_S2S_COMPOSE_DIR=${SAHA_S2S_COMPOSE_DIR:-/opt/roban/s2s}
SAHA_S2S_COMPOSE_FILE=${SAHA_S2S_COMPOSE_FILE:-${SAHA_S2S_COMPOSE_DIR}/compose.yaml}
SAHA_S2S_PROJECT=${SAHA_S2S_PROJECT:-saha-s2s}
SAHA_S2S_IMAGE=${SAHA_S2S_IMAGE:-roban-s2s:arm64}
SAHA_S2S_IMAGE_TAR=${SAHA_S2S_IMAGE_TAR:-/data/preload/s2s/image.tar}
SAHA_S2S_PORT=${SAHA_S2S_PORT:-8765}
SAHA_S2S_WAIT=${SAHA_S2S_WAIT:-120}
ROBAN_S2S_MODEL_MANIFEST=${ROBAN_S2S_MODEL_MANIFEST:-/data/models/s2s/manifest.sha256}
export SAHA_S2S_IMAGE SAHA_S2S_PORT HF_ENDPOINT PIP_INDEX_URL ROBAN_S2S_ICE_SERVERS
export ROBAN_S2S_KWS_PROVIDER ROBAN_S2S_VAD_PROVIDER ROBAN_S2S_STT_PROVIDER ROBAN_S2S_TTS_PROVIDER
export ROBAN_S2S_STT_BACKEND ROBAN_S2S_LLM_BACKEND ROBAN_S2S_LLM_MODEL
export ROBAN_S2S_LLM_BASE_URL ROBAN_S2S_TTS_BACKEND ROBAN_S2S_PIPELINE_FACTORY

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

ensure_image() {
    if docker image inspect "$SAHA_S2S_IMAGE" >/dev/null 2>&1; then
        return 0
    fi
    if [ ! -s "$SAHA_S2S_IMAGE_TAR" ]; then
        log "required offline image archive is missing: ${SAHA_S2S_IMAGE_TAR}"
        return 1
    fi
    docker load -i "$SAHA_S2S_IMAGE_TAR" >/dev/null
    docker image inspect "$SAHA_S2S_IMAGE" >/dev/null 2>&1
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
    mkdir -p /data/models/s2s /data/model-cache/s2s
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

case ${1:-} in
    wait-docker) wait_for_docker ;;
    start) wait_for_docker; start_service ;;
    stop) stop_service ;;
    restart) stop_service; wait_for_docker; start_service ;;
    status) curl -fsS "http://127.0.0.1:${SAHA_S2S_PORT}/ready" ;;
    *) echo "Usage: $0 {wait-docker|start|stop|restart|status}" >&2; exit 2 ;;
esac
