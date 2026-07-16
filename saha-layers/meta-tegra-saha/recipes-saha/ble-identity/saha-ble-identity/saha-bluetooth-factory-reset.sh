#!/bin/sh
set -eu

GATT_SERVICE="saha-bt-wifi-provision.service"
BLUETOOTH_SERVICE="bluetooth.service"
IDENTITY_SERVICE="saha-ble-identity.service"
BLUEZ_STATE_DIR="/var/lib/bluetooth"
IDENTITY_STATE_DIR="/var/lib/saha/ble-identity"

systemctl stop "$GATT_SERVICE" "$BLUETOOTH_SERVICE" "$IDENTITY_SERVICE"

# These are fixed absolute paths, deliberately not caller-configurable.
rm -rf -- "$BLUEZ_STATE_DIR" "$IDENTITY_STATE_DIR"

# A oneshot service remains active after success, so explicitly restart it.
systemctl reset-failed "$IDENTITY_SERVICE" "$BLUETOOTH_SERVICE" "$GATT_SERVICE"
systemctl restart "$IDENTITY_SERVICE"
systemctl start "$BLUETOOTH_SERVICE"
