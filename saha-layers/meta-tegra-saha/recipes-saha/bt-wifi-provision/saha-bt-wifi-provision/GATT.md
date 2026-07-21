# Roban BLE Secure Protocol v2

This is the normative device-side GATT and wire contract. Version 2 is a hard cutover: there is no legacy plaintext mode and no BlueZ pairing/bonding. The adapter is `Pairable=false`. App and device authentication uses global Ed25519 identities; every business request and response is protected by ChaCha20-Poly1305.

## GATT

Service `a0a0ff10-0000-1000-8000-00805f9b34fb`:

- Status `a0a0ff11-0000-1000-8000-00805f9b34fb`, read: before authentication returns only ASCII `Roban BLE Secure Protocol v2; all business data requires authenticated AEAD`. It never exposes Wi-Fi state.
- Command `a0a0ff12-0000-1000-8000-00805f9b34fb`, write/write-without-response: transport fragments from the central.
- Event `a0a0ff13-0000-1000-8000-00805f9b34fb`, notify: transport fragments from the device. Subscribe before ClientHello.

`WriteValue` uses BlueZ `options.device` as the client identity/session key and preserves `options.mtu` for response sizing. A disconnect clears that device's handshake, keys, reassembly, sequences, and active request IDs.

## Transport fragment

All integers are unsigned big-endian. The 10-byte outer header is:

| Offset | Bytes | Field |
| --- | ---: | --- |
| 0 | 2 | magic ASCII `R2` |
| 2 | 1 | version `0x02` |
| 3 | 1 | kind: 1 ClientHello, 2 ServerHello, 3 encrypted record |
| 4 | 2 | message id |
| 6 | 1 | zero-based fragment index |
| 7 | 1 | fragment count, 1..255 |
| 8 | 2 | total complete-message bytes, 1..16384 |
| 10 | remaining | non-empty fragment body |

The body budget is `ATT_MTU - 3 - 10`; therefore MTU 23 carries 10 body bytes. A complete handshake message or complete AEAD ciphertext is fragmented. Reassembly permits out-of-order and byte-identical duplicate fragments, rejects conflicting duplicates/metadata, and has limits of 8 incomplete messages, 16 KiB/message, 255 fragments, 509 body bytes/fragment, and 10 seconds. **Fragments do not have independent authentication tags.** Kind 3 is reassembled first and then authenticated once.

Canonical transport AAD excludes index and is exactly `magic[2] || version[u8] || kind[u8] || message_id[u16] || count[u8] || total[u16]` (9 bytes). This binds the complete ciphertext to stable transport metadata while allowing reordered fragments.

## Fixed handshake messages

### ClientHello, kind 1, exactly 162 bytes

`version[u8]=2 || flags[u8]=0 || app_key_id[32] || client_ephemeral_X25519[32] || client_nonce[32] || signature[64]`.

`app_key_id` is the raw trusted App Ed25519 public key. Signature input is ASCII `R2-ClientHello` followed by the first 98 ClientHello bytes (`version` through `client_nonce`).

### ServerHello, kind 2, exactly 170 bytes

`version[u8]=2 || flags[u8]=0 || session_id[u64] || device_key_id[32] || server_ephemeral_X25519[32] || server_nonce[32] || signature[64]`.

`device_key_id` is the raw device Ed25519 public key. Signature input is ASCII `R2-ServerHello` followed by the complete 162-byte ClientHello and then ServerHello fields `session_id || device_key_id || server_ephemeral || server_nonce`.

Both peers compute X25519 shared secret, then HKDF-SHA256 with `salt = client_nonce || server_nonce`, `info = ASCII "Roban BLE Secure Protocol v2"`, output 64 bytes. First 32 bytes are client-to-device key; last 32 are device-to-client key.

## Encrypted record

The complete kind-3 body is `ChaCha20-Poly1305(ciphertext || 16-byte tag)`. Nonce is 12 bytes: first 7 bytes of big-endian session id, direction u8, sequence u32. Each direction starts at sequence 0 and accepts exactly the next value; no gaps/replay/wrap.

After decrypting, plaintext is:

| Offset | Bytes | Field |
| --- | ---: | --- |
| 0 | 8 | session id u64 |
| 8 | 1 | direction: 0 App-to-device, 1 device-to-App |
| 9 | 4 | sequence u32 |
| 13 | 2 | message type u16 |
| 15 | 4 | request id u32 |
| 19 | remaining | payload |

Message types: `1 Finished`, `16 Request`, `17 Response`, `18 Error`, `19 Progress` (reserved). The App's first encrypted record must be type 1, request id 0, payload ASCII `finished-v2`. The device replies with encrypted type 1 JSON `{"ok":true}`. No business command is accepted earlier.

Business request payloads are compact UTF-8 JSON (`status`, `scan`, `connect`, and existing `ha`). Every request uses nonzero request id. The device admits exactly one authenticated provisioning owner. Per-device handshake/reassembly contexts remain isolated, but another device receives encrypted `BUSY` after Finished and its context is closed. Ownership is released on BlueZ disconnect, explicit successful close, or 300 seconds of owner inactivity.

Device-to-App encrypted transport message ids are derived from the random session id and transmit sequence, while the App seeds its outgoing message-id counter from the random ClientHello nonce. This reduces cross-session fragment-key collisions on BlueZ's shared notification stream; the id remains authenticated by AAD.

A bounded per-session tombstone cache retains 32 completed requests for 300 seconds. It binds request id to SHA-256 of the exact request payload and the unique terminal response. Repeating an active id with the same payload returns non-terminal `IN_PROGRESS` (and never executes twice); repeating a completed id with the same payload replays the cached terminal; any same-id/different-payload request returns terminal `REQUEST_ID_CONFLICT`. Exactly one original terminal type 17 or 18 response is generated for an accepted request. If the bounded notification queue cannot accept a terminal, the device closes and clears the session rather than silently losing the terminal or leaking a worker slot. All responses use one encrypted record and the common transport fragmenter.

`connect` accepts optional integer `deadline_seconds`, clamped to 5..120. It emits encrypted non-terminal type-19 progress stages `associating` before invoking nmcli and `obtainingIp` after nmcli succeeds while waiting for IPv4. It does not claim an `authenticating` stage because nmcli does not expose that transition reliably. Success requires the requested SSID to be active and IPv4 assigned before the monotonic deadline. Wi-Fi `signal` and `signal_percent` are NetworkManager percentages (0..100), not dBm.

A successful `ha` request first sends credentials as encrypted non-terminal type 19 with `awaiting_ack:true`; the request stays active and has no terminal yet. After safely persisting credentials, the App sends `{"cmd":"close","ack_request_id":N}` using the same request id `N`. The device then emits the request's sole terminal type-17 `close` response, queues every transport fragment, and only afterward clears keys/session and releases ownership. Missing or mismatched ACK returns non-terminal `INVALID_ACK` and never produces a false HA success terminal. Disconnect/idle/close destroys the channel keys; disconnect while waiting for HA ACK also abandons that active request and releases its bounded worker slot.

## Identity provisioning

The current bring-up image intentionally bundles a shared development device private key and App public-key keyring so the end-to-end flow works immediately. The recipe installs the private key root-owned with mode 0600. These committed development credentials are not production-safe and must be replaced by per-device manufacturing/CI injection before production. The loader accepts PEM PKCS8 or 32-byte raw hex/base64. The 32-byte raw Ed25519 public key carried in ClientHello is also its key id, so no wire-layout change is required for rotation. App keys may be a legacy JSON object of `key-id: public-key`, or a versioned manifest `{"version":3,"minimum_accepted_version":2,"keys":{"<raw-key-id>":"<public-key>"}}`, supplied through `ROBAN_APP_KEYRING_FILE` or `ROBAN_APP_KEYRING_JSON`. Deployment atomically replaces the manifest to overlap old/new keys, then removes retired keys; manifests whose `version` is below `minimum_accepted_version` are rejected.

Tests alone may set both `ROBAN_ALLOW_DEV_KEYS=1` and `ROBAN_DEV_IDENTITY_FILE`; this path is explicitly non-production and is not enabled by the recipe defaults. The implementation uses `python3-cryptography`.
