#!/bin/sh
set -eu

ENV_FILE="/etc/default/homeassistant-container"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    . "$ENV_FILE"
fi

SAHA_HOMEASSISTANT_CONFIG_DIR="${SAHA_HOMEASSISTANT_CONFIG_DIR:-/var/lib/homeassistant}"
SAHA_HOMEASSISTANT_IMAGE="${SAHA_HOMEASSISTANT_IMAGE:-ghcr.io/home-assistant/home-assistant:stable}"
SAHA_HOMEASSISTANT_CONTAINER_NAME="${SAHA_HOMEASSISTANT_CONTAINER_NAME:-homeassistant}"
SAHA_HOMEASSISTANT_TIMEZONE="${SAHA_HOMEASSISTANT_TIMEZONE:-UTC}"
SAHA_HOMEASSISTANT_PULL="${SAHA_HOMEASSISTANT_PULL:-1}"

container_exists() {
    docker inspect "$SAHA_HOMEASSISTANT_CONTAINER_NAME" >/dev/null 2>&1
}

ensure_image() {
    if [ "$SAHA_HOMEASSISTANT_PULL" = "1" ]; then
        docker pull "$SAHA_HOMEASSISTANT_IMAGE"
    fi
}

start_container() {
    mkdir -p "$SAHA_HOMEASSISTANT_CONFIG_DIR"
    ensure_image

    if container_exists; then
        docker start "$SAHA_HOMEASSISTANT_CONTAINER_NAME"
        return 0
    fi

    docker run -d \
        --name "$SAHA_HOMEASSISTANT_CONTAINER_NAME" \
        --restart unless-stopped \
        --privileged \
        --network host \
        -e "TZ=${SAHA_HOMEASSISTANT_TIMEZONE}" \
        -v "${SAHA_HOMEASSISTANT_CONFIG_DIR}:/config" \
        "$SAHA_HOMEASSISTANT_IMAGE"
}

stop_container() {
    if container_exists; then
        docker stop "$SAHA_HOMEASSISTANT_CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
}

case "${1:-}" in
    start)
        start_container
        ;;
    stop)
        stop_container
        ;;
    restart)
        stop_container
        start_container
        ;;
    *)
        echo "Usage: $0 {start|stop|restart}" >&2
        exit 2
        ;;
esac
