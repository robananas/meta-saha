# Roban Bluetooth WiFi Provisioning GATT API

This document describes the BLE GATT interface exposed by
`saha-bt-wifi-provision` for Android and other central devices.

## Adapter

- Local name: `Roban-Bluetooth` (override with `SAHA_BT_WIFI_LOCAL_NAME`)
- Transport: BLE (GATT client connects to the Jetson peripheral)

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
2. Connect GATT and discover service `a0a0ff10-...`
3. Enable notifications on `a0a0ff13-...`
4. Read `a0a0ff11-...` or write `{"cmd":"status"}` to check current WiFi
5. Write `{"cmd":"scan"}` and wait for scan event
6. Write `{"cmd":"connect",...}` and wait for connect event with IP details

## Notes

- WiFi operations use host `nmcli` / NetworkManager
- USB gadget networking (`l4tbr0`) is unchanged; only WiFi is managed
- Large scan results are capped at 30 networks
- JSON payloads should fit within the negotiated ATT MTU; keep commands compact
