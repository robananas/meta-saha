#!/bin/sh
set -eu

ENV_FILE="/etc/default/saha-docker-compose"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    . "$ENV_FILE"
fi

SAHA_DOCKER_COMPOSE_DIR="${SAHA_DOCKER_COMPOSE_DIR:-/opt/roban/compose}"
SAHA_DOCKER_COMPOSE_FILE="${SAHA_DOCKER_COMPOSE_FILE:-${SAHA_DOCKER_COMPOSE_DIR}/compose.yaml}"
SAHA_DOCKER_COMPOSE_TZ="${SAHA_DOCKER_COMPOSE_TZ:-Asia/Shanghai}"
SAHA_DOCKER_COMPOSE_PULL="${SAHA_DOCKER_COMPOSE_PULL:-0}"
SAHA_DOCKER_COMPOSE_WAIT="${SAHA_DOCKER_COMPOSE_WAIT:-60}"
SAHA_CLOCK_WAIT="${SAHA_CLOCK_WAIT:-90}"
SAHA_CLOCK_MIN_YEAR="${SAHA_CLOCK_MIN_YEAR:-2024}"
SAHA_CLOCK_BOOTSTRAP_URLS="${SAHA_CLOCK_BOOTSTRAP_URLS:-https://ha.api.io.mi.com/ https://www.cloudflare.com/ https://www.google.com/}"
SAHA_HOMEASSISTANT_IMAGE="${SAHA_HOMEASSISTANT_IMAGE:-ghcr.io/home-assistant/home-assistant:2026.7.1}"
SAHA_HOMEASSISTANT_IMAGE_TAR="${SAHA_HOMEASSISTANT_IMAGE_TAR:-/data/preload/homeassistant/image.tar}"
SAHA_HOMEASSISTANT_MCP_IMAGE="${SAHA_HOMEASSISTANT_MCP_IMAGE:-roban-ha-mcp:arm64}"
SAHA_HOMEASSISTANT_MCP_IMAGE_TAR="${SAHA_HOMEASSISTANT_MCP_IMAGE_TAR:-/data/preload/homeassistant-mcp/image.tar}"
SAHA_HOMEASSISTANT_MCP_CREDENTIALS_FILE="${SAHA_HOMEASSISTANT_MCP_CREDENTIALS_FILE:-/data/saha/homeassistant-mcp/credentials.env}"
SAHA_MATTER_SERVER_IMAGE="${SAHA_MATTER_SERVER_IMAGE:-ghcr.io/matter-js/python-matter-server:arm64}"
SAHA_MATTER_SERVER_IMAGE_TAR="${SAHA_MATTER_SERVER_IMAGE_TAR:-/data/preload/matter-server/image.tar}"
SAHA_ROBAN_WORKFLOW_IMAGE="${SAHA_ROBAN_WORKFLOW_IMAGE:-roban-workflow-api:arm64}"
SAHA_ROBAN_WORKFLOW_IMAGE_TAR="${SAHA_ROBAN_WORKFLOW_IMAGE_TAR:-/data/preload/roban-workflow-api/image.tar}"
SAHA_WORKFLOW_MCP_IMAGE="${SAHA_WORKFLOW_MCP_IMAGE:-roban-workflow-mcp:arm64}"
SAHA_WORKFLOW_MCP_IMAGE_TAR="${SAHA_WORKFLOW_MCP_IMAGE_TAR:-/data/preload/workflow-mcp/image.tar}"
SAHA_WORKFLOW_MCP_CREDENTIALS_FILE="${SAHA_WORKFLOW_MCP_CREDENTIALS_FILE:-/data/saha/workflow-mcp/credentials.env}"
SAHA_LIVEKIT_SERVER_IMAGE="${SAHA_LIVEKIT_SERVER_IMAGE:-livekit/livekit-server:v1.13.4}"
SAHA_LIVEKIT_SERVER_IMAGE_TAR="${SAHA_LIVEKIT_SERVER_IMAGE_TAR:-/data/preload/livekit-server/image.tar}"
SAHA_LIVEKIT_AGENT_IMAGE="${SAHA_LIVEKIT_AGENT_IMAGE:-livekit-agent:arm64}"
SAHA_LIVEKIT_AGENT_IMAGE_TAR="${SAHA_LIVEKIT_AGENT_IMAGE_TAR:-/data/preload/livekit-agent/image.tar}"
SAHA_LIVEKIT_API_KEY="${SAHA_LIVEKIT_API_KEY:-roban-local}"
SAHA_LIVEKIT_API_SECRET="${SAHA_LIVEKIT_API_SECRET:-}"
SAHA_LIVEKIT_CREDENTIALS_FILE="${SAHA_LIVEKIT_CREDENTIALS_FILE:-/var/lib/saha/livekit/credentials.env}"
SAHA_DOCKER_LOAD_LOCK="${SAHA_DOCKER_LOAD_LOCK:-/run/lock/saha-docker-load.lock}"

log() {
    logger -t saha-docker-compose "$*"
}

status_emit() {
    state=$1
    level=${2:-}
    error_code=${3:-}
    set -- emit docker "$state"
    [ -z "$level" ] || set -- "$@" --level "$level"
    [ -z "$error_code" ] || set -- "$@" --error-code "$error_code"
    python3 /usr/bin/saha-board-status "$@" >/dev/null 2>&1 || true
}

clock_is_valid() {
    year=$(date -u +%Y 2>/dev/null || printf '0')
    [ "$year" -ge "$SAHA_CLOCK_MIN_YEAR" ] 2>/dev/null
}

bootstrap_clock_from_https() {
    for url in $SAHA_CLOCK_BOOTSTRAP_URLS; do
        remote_date=$(
            curl -kfsSI --connect-timeout 10 --max-time 15 "$url" 2>/dev/null |
                sed -n 's/^[Dd]ate:[[:space:]]*//p' |
                tail -1 |
                tr -d '\r'
        )
        [ -n "$remote_date" ] || continue
        remote_epoch=$(
            python3 -c 'import email.utils, sys; print(int(email.utils.parsedate_to_datetime(sys.argv[1]).timestamp()))' \
                "$remote_date" 2>/dev/null || true
        )
        [ -n "$remote_epoch" ] || continue
        remote_year=$(date -u -d "@${remote_epoch}" +%Y 2>/dev/null || printf '0')
        if [ "$remote_year" -lt "$SAHA_CLOCK_MIN_YEAR" ] 2>/dev/null ||
            [ "$remote_year" -gt 2100 ] 2>/dev/null; then
            continue
        fi
        if date -u -s "@${remote_epoch}" >/dev/null 2>&1; then
            hwclock --systohc >/dev/null 2>&1 || true
            log "system clock bootstrapped from HTTPS response"
            return 0
        fi
    done
    return 1
}

wait_for_valid_clock() {
    if clock_is_valid; then
        return 0
    fi

    log "system clock is invalid; trying immediate HTTPS bootstrap"
    if bootstrap_clock_from_https && clock_is_valid; then
        return 0
    fi

    waited=0
    while [ "$waited" -lt "$SAHA_CLOCK_WAIT" ]; do
        sleep 2
        waited=$((waited + 2))
        if clock_is_valid; then
            return 0
        fi
        if [ $((waited % 10)) -eq 0 ] && bootstrap_clock_from_https && clock_is_valid; then
            return 0
        fi
    done

    log "refusing to start application stack with invalid system clock after ${SAHA_CLOCK_WAIT}s"
    return 1
}

wait_for_docker() {
    waited=0
    while [ "$waited" -lt "$SAHA_DOCKER_COMPOSE_WAIT" ]; do
        if docker info >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
        waited=$((waited + 2))
    done

    log "docker daemon not ready after ${SAHA_DOCKER_COMPOSE_WAIT}s"
    return 1
}

image_loaded() {
    docker image inspect "$1" >/dev/null 2>&1
}

load_tarball() {
    image=$1
    tar=$2

    if image_loaded "$image"; then
        log "image already loaded: ${image}"
        return 0
    fi

    if [ ! -f "$tar" ]; then
        log "preload tar missing: ${tar}"
        return 0
    fi

    log "loading preload tar for ${image}: ${tar}"
    # Serialize offline docker load: concurrent ingest races containerd.
    mkdir -p "$(dirname "$SAHA_DOCKER_LOAD_LOCK")"
    set +e
    load_output=$(flock "$SAHA_DOCKER_LOAD_LOCK" docker load -i "$tar" 2>&1)
    load_status=$?
    set -e

    if [ "$load_status" -ne 0 ]; then
        log "docker load failed for ${image}: ${load_output}"
        return 1
    fi

    if ! image_loaded "$image"; then
        loaded_ref=$(printf '%s\n' "$load_output" | sed -n 's/^Loaded image: //p' | tail -1)
        if [ -n "$loaded_ref" ]; then
            log "tagging ${loaded_ref} as ${image}"
            docker tag "$loaded_ref" "$image"
        fi
    fi
}

tag_if_present() {
    source_image=$1
    target_image=$2

    if image_loaded "$target_image"; then
        return 0
    fi

    if image_loaded "$source_image"; then
        log "tagging ${source_image} as ${target_image}"
        docker tag "$source_image" "$target_image"
    fi
}

ensure_images() {
    load_tarball "$SAHA_HOMEASSISTANT_IMAGE" "$SAHA_HOMEASSISTANT_IMAGE_TAR"
    load_tarball "$SAHA_HOMEASSISTANT_MCP_IMAGE" "$SAHA_HOMEASSISTANT_MCP_IMAGE_TAR"
    load_tarball "$SAHA_MATTER_SERVER_IMAGE" "$SAHA_MATTER_SERVER_IMAGE_TAR"
    load_tarball "$SAHA_ROBAN_WORKFLOW_IMAGE" "$SAHA_ROBAN_WORKFLOW_IMAGE_TAR"
    load_tarball "$SAHA_WORKFLOW_MCP_IMAGE" "$SAHA_WORKFLOW_MCP_IMAGE_TAR"
    load_tarball "$SAHA_LIVEKIT_SERVER_IMAGE" "$SAHA_LIVEKIT_SERVER_IMAGE_TAR"
    load_tarball "$SAHA_LIVEKIT_AGENT_IMAGE" "$SAHA_LIVEKIT_AGENT_IMAGE_TAR"

    tag_if_present "ghcr.io/matter-js/python-matter-server:stable" "$SAHA_MATTER_SERVER_IMAGE"

    if ! image_loaded "$SAHA_HOMEASSISTANT_IMAGE" && [ "$SAHA_DOCKER_COMPOSE_PULL" = "1" ]; then
        log "pulling ${SAHA_HOMEASSISTANT_IMAGE}"
        docker pull "$SAHA_HOMEASSISTANT_IMAGE"
    fi

    if ! image_loaded "$SAHA_MATTER_SERVER_IMAGE"; then
        log "offline Matter Server image is unavailable: ${SAHA_MATTER_SERVER_IMAGE}"
        return 1
    fi

    if ! image_loaded "$SAHA_ROBAN_WORKFLOW_IMAGE" && [ "$SAHA_DOCKER_COMPOSE_PULL" = "1" ]; then
        log "pulling ${SAHA_ROBAN_WORKFLOW_IMAGE}"
        docker pull "$SAHA_ROBAN_WORKFLOW_IMAGE"
    fi

    if ! image_loaded "$SAHA_LIVEKIT_SERVER_IMAGE" && [ "$SAHA_DOCKER_COMPOSE_PULL" = "1" ]; then
        log "pulling ${SAHA_LIVEKIT_SERVER_IMAGE}"
        docker pull "$SAHA_LIVEKIT_SERVER_IMAGE"
    fi
}

ensure_livekit_credentials() {
    credentials_dir=$(dirname "$SAHA_LIVEKIT_CREDENTIALS_FILE")
    mkdir -p "$credentials_dir"
    chmod 0700 "$credentials_dir"
    if [ -s "$SAHA_LIVEKIT_CREDENTIALS_FILE" ]; then
        return 0
    fi
    if [ -z "$SAHA_LIVEKIT_API_SECRET" ]; then
        SAHA_LIVEKIT_API_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')
    fi
    umask 077
    {
        printf 'LIVEKIT_API_KEY=%s\n' "$SAHA_LIVEKIT_API_KEY"
        printf 'LIVEKIT_API_SECRET=%s\n' "$SAHA_LIVEKIT_API_SECRET"
        printf 'LIVEKIT_KEYS=%s: %s\n' "$SAHA_LIVEKIT_API_KEY" "$SAHA_LIVEKIT_API_SECRET"
    } >"$SAHA_LIVEKIT_CREDENTIALS_FILE"
}

seed_matter_certificates() {
    template="${SAHA_MATTER_PAA_TEMPLATE:-/usr/share/saha/matter-server/paa-root-certs}"
    credentials_dir="/var/lib/matter-server/credentials"

    if [ ! -d "$template" ]; then
        log "offline Matter PAA certificate template missing: ${template}"
        return 1
    fi

    mkdir -p "$credentials_dir"
    for certificate in "$template"/*; do
        [ -f "$certificate" ] || continue
        cp "$certificate" "$credentials_dir/$(basename "$certificate")"
    done
    printf 'offline\n' >"${credentials_dir}/.version"
    chmod 0644 "$credentials_dir"/* "${credentials_dir}/.version"
    log "seeded offline Matter PAA certificate trust store"
}

seed_homeassistant_config() {
    template="${SAHA_HOMEASSISTANT_CONFIG_TEMPLATE:-/usr/share/saha/homeassistant/config-default}"
    config_dir="/var/lib/homeassistant"

    if [ -f "${config_dir}/configuration.yaml" ]; then
        return 0
    fi

    if [ ! -d "$template" ]; then
        log "homeassistant config template missing: ${template}"
        return 0
    fi

    log "seeding homeassistant config from ${template} to ${config_dir}"
    mkdir -p "$config_dir"
    cp -a "${template}/." "${config_dir}/"
}

start_stack() {
    mountpoint -q /data
    mkdir -p /var/lib/homeassistant /var/lib/matter-server /data/saha/homeassistant-mcp /data/saha/workflow-mcp
    test -s "$SAHA_HOMEASSISTANT_MCP_CREDENTIALS_FILE"
    test -s "$SAHA_WORKFLOW_MCP_CREDENTIALS_FILE"
    seed_matter_certificates
    seed_homeassistant_config
    ensure_livekit_credentials
    export TZ="$SAHA_DOCKER_COMPOSE_TZ"
    export SAHA_HOMEASSISTANT_MCP_IMAGE SAHA_HOMEASSISTANT_MCP_CREDENTIALS_FILE
    export SAHA_WORKFLOW_MCP_IMAGE SAHA_WORKFLOW_MCP_CREDENTIALS_FILE
    export SAHA_LIVEKIT_SERVER_IMAGE SAHA_LIVEKIT_AGENT_IMAGE
    export SAHA_LIVEKIT_AGENT_NAME="${SAHA_LIVEKIT_AGENT_NAME:-roban-agent}"
    export OPENAI_API_KEY="${OPENAI_API_KEY:-}"
    export SAHA_LIVEKIT_CREDENTIALS_FILE
    cd "$SAHA_DOCKER_COMPOSE_DIR"
    docker compose -f "$SAHA_DOCKER_COMPOSE_FILE" up -d
}

stop_stack() {
    cd "$SAHA_DOCKER_COMPOSE_DIR"
    docker compose -f "$SAHA_DOCKER_COMPOSE_FILE" down
}

case "${1:-}" in
    wait-docker)
        wait_for_docker
        ;;
    start)
        status_emit waiting_for_network
        wait_for_docker
        wait_for_valid_clock
        status_emit loading_images
        if ! ensure_images; then
            status_emit image_load_failed error IMAGE_LOAD_FAILED
            exit 1
        fi
        status_emit creating_containers
        if ! start_stack; then
            status_emit compose_failed error COMPOSE_FAILED
            exit 1
        fi
        status_emit ready
        ;;
    stop)
        stop_stack
        ;;
    restart)
        stop_stack
        wait_for_docker
        wait_for_valid_clock
        ensure_images
        start_stack
        ;;
    *)
        echo "Usage: $0 {wait-docker|start|stop|restart}" >&2
        exit 2
        ;;
esac
