# Roban Bluetooth WiFi Provisioning GATT API

This document describes the BLE GATT interface exposed by
`saha-bt-wifi-provision` for Android and other central devices.

## Adapter

- Local name: `Roban-Bluetooth` (override with `SAHA_BT_WIFI_LOCAL_NAME`)
- Transport: BLE-only (BR/EDR is disabled; a GATT client connects to the Jetson peripheral)
- Pairing: BlueZ `NoInputNoOutput` / Just Works bonding (no PIN entry)
- Security: characteristics require an encrypted, paired connection

## Device identity lifecycle

- The controller uses a locally generated Static Random BLE Identity Address.
- A full image flash creates a new identity on first boot because `/var/lib` is recreated.
- RPM/dnf package upgrades preserve `/var/lib/saha/ble-identity` and `/var/lib/bluetooth`, so the identity and bonds remain unchanged.
- Run `saha-bluetooth-factory-reset` as root to erase the identity and all BlueZ bond data, generate a new identity, and restart Bluetooth.
- The current project has no A/B rootfs OTA or separate persistent DATA partition; those upgrade modes require moving both state directories to persistent storage before they can preserve identity and bonds.

## Service

| Field | Value |
| --- | --- |
| Name | Roban WiFi Provision |
| UUID | `a0a0ff10-0000-1000-8000-00805f9b34fb` |

## Characteristics

### 1. WiFi Status (`a0a0ff11-0000-1000-8000-00805f9b34fb`)

- Properties: `read`
- Payload: UTF-8 JSON

```json
{
  "connected": true,
  "ssid": "MyWiFi",
  "interface": "wlan0",
  "ip": "192.168.1.42",
  "addresses": ["192.168.1.42"],
  "gateway": "192.168.1.1",
  "dns": ["192.168.1.1"],
  "signal": -48,
  "security": "WPA2"
}
```

### 2. WiFi Command (`a0a0ff12-0000-1000-8000-00805f9b34fb`)

- Properties: `write`, `write-without-response`
- Payload: UTF-8 JSON command object
- Responses are delivered on the WiFi Event characteristic

Commands:

```json
{"cmd":"status"}
```

```json
{"cmd":"scan","limit":20}
```

```json
{"cmd":"connect","ssid":"MyWiFi","password":"secret"}
```

Open networks:

```json
{"cmd":"connect","ssid":"GuestWiFi"}
```

### 3. WiFi Event (`a0a0ff13-0000-1000-8000-00805f9b34fb`)

- Properties: `notify`
- Subscribe with `StartNotify` before sending commands

#### Status event

Same fields as the WiFi Status characteristic plus `"event":"status"`.

#### Scan event

```json
{
  "event": "scan",
  "networks": [
    {"ssid": "MyWiFi", "signal": -42, "security": "WPA2", "frequency_mhz": 2437}
  ]
}
```

#### Connect event

```json
{
  "event": "connect",
  "state": "connected",
  "ssid": "MyWiFi",
  "ip": "192.168.1.42",
  "gateway": "192.168.1.1",
  "dns": ["192.168.1.1"],
  "signal": -45,
  "security": "WPA2",
  "error": ""
}
```

Failure example:

```json
{
  "event": "connect",
  "state": "failed",
  "ssid": "MyWiFi",
  "error": "Secrets were required, but not provided.",
  "connected": false,
  "ip": ""
}
```

#### Error event

```json
{"event":"error","error":"unsupported cmd: foo"}
```

## Recommended Android flow

1. Scan for BLE peripheral `Roban-Bluetooth`
2. Pair/bond using Just Works when Android prompts (no PIN)
3. Connect GATT and discover service `a0a0ff10-...`
4. Enable notifications on `a0a0ff13-...`
5. Read `a0a0ff11-...` or write `{"cmd":"status"}` to check current WiFi
6. Write `{"cmd":"scan"}` and wait for scan event
7. Write `{"cmd":"connect",...}` and wait for connect event with IP details

## Notes

- WiFi operations use host `nmcli` / NetworkManager
- USB gadget networking (`l4tbr0`) is unchanged; only WiFi is managed
- Large scan results are capped at 30 networks
- JSON payloads should fit within the negotiated ATT MTU; keep commands compact

## Home Assistant credential transfer (v1)

A bonded, encrypted client writes `{"cmd":"ha","id":N,"m":M}` to the encrypted Command characteristic. `id` is unsigned 16-bit and `m` is clamped to 20..180. Responses only use encrypted Event notifications and are never JSON events.

Each binary notification starts with a 14-byte big-endian header: `RH` magic (2), version (1), kind (1: 0=data, 1=digest), request id u16, chunk index u16, chunk count u16, total JSON payload bytes u32. Remaining bytes are the chunk body. Data frames precede digest frames without ordinary-event interleaving. Kind 1 contains exactly the 32-byte SHA-256 digest, split when needed. Payload is UTF-8 JSON, at most 16 KiB; indices are zero-based and duplicates must be byte-identical.

If notifications are not subscribed or credentials cannot be loaded/refreshed, firmware sends a secret-free ordinary error with code `HA_CREDENTIALS_UNAVAILABLE`. Older firmware may return unsupported or no response; clients must preserve normal BLE/WiFi operation.
