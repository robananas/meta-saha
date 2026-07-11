#!/bin/sh
set -eu

ENV_FILE="/etc/default/saha-bt-wifi-provision"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    . "$ENV_FILE"
fi

WAIT="${SAHA_BT_WIFI_ADAPTER_WAIT:-45}"
INTERVAL=2
elapsed=0

log() {
    logger -t saha-bt-wifi-provision "$*"
}

power_on_adapter() {
    if [ -e /sys/class/bluetooth/hci0 ]; then
        hciconfig hci0 up >/dev/null 2>&1 || true
    fi
    bluetoothctl power on >/dev/null 2>&1 || true
}

adapter_ready() {
    [ -e /sys/class/bluetooth/hci0 ] || return 1
    bluetoothctl show 2>/dev/null | grep -q "Powered: yes" || return 1
    dbus-send --system --print-reply --dest=org.bluez / \
        org.freedesktop.DBus.ObjectManager.GetManagedObjects 2>/dev/null |
        grep -q "org.bluez.GattManager1"
}

while [ "$elapsed" -lt "$WAIT" ]; do
    power_on_adapter
    if adapter_ready; then
        log "bluetooth adapter ready for GATT provisioning"
        exit 0
    fi
    sleep "$INTERVAL"
    elapsed=$((elapsed + INTERVAL))
done

log "bluetooth adapter not ready after ${WAIT}s (need hci0, power on, and GattManager1)"
exit 1
