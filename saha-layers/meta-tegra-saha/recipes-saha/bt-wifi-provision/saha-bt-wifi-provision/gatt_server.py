#!/usr/bin/env python3
"""BlueZ GATT server for Roban Secure Protocol v2 provisioning."""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

import dbus
import dbus.exceptions
import dbus.service

from dbus_mainloop import iterate_main_loop, setup_dbus_main_loop
from device_identity import load_app_keyring, load_device_identity
from ha_credential_manager import HaCredentialError, get_credential_payload
from session_state import ProvisioningOwner, RequestTracker
from secure_protocol import (
    AEAD_TAG_BYTES,
    FINISHED_PAYLOAD,
    INNER_HEADER_SIZE,
    KIND_CLIENT_HELLO,
    KIND_ENCRYPTED,
    KIND_SERVER_HELLO,
    MSG_ERROR,
    MSG_FINISHED,
    MSG_PROGRESS,
    MSG_REQUEST,
    MSG_RESPONSE,
    ProtocolError,
    Reassembler,
    SecureChannel,
    ServerHandshake,
    TransportMetadata,
    fragment_message,
)
from wifi_manager import WifiError, decode_json, encode_json, get_wifi_status, handle_command

BLUEZ_SERVICE_NAME = "org.bluez"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"
DEVICE_IFACE = "org.bluez.Device1"
ADAPTER_IFACE = "org.bluez.Adapter1"

SERVICE_UUID = "a0a0ff10-0000-1000-8000-00805f9b34fb"
WIFI_STATUS_UUID = "a0a0ff11-0000-1000-8000-00805f9b34fb"
WIFI_COMMAND_UUID = "a0a0ff12-0000-1000-8000-00805f9b34fb"
WIFI_EVENT_UUID = "a0a0ff13-0000-1000-8000-00805f9b34fb"
APPLICATION_PATH = "/org/roban/bt_wifi"
ADVERTISEMENT_PATH = f"{APPLICATION_PATH}/advertisement0000"
PROTOCOL_DESCRIPTOR = b"Roban BLE Secure Protocol v2; all business data requires authenticated AEAD"
DEFAULT_MTU = 23
MAX_ATT_VALUE = 512
MAX_SESSIONS = 8
SESSION_IDLE_SECONDS = 300.0
MAX_WORKERS = 4
MAX_PENDING_WORK = 16
ERROR_BUSY = "BUSY"
ERROR_IN_PROGRESS = "IN_PROGRESS"
ERROR_REQUEST_ID_CONFLICT = "REQUEST_ID_CONFLICT"
logger = logging.getLogger("saha-bt-wifi-provision")


class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"


class NotSupportedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotSupported"


class InvalidValueLengthException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.InvalidValueLength"


class Application(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus) -> None:
        self.path = APPLICATION_PATH
        self.services: list[Service] = []
        super().__init__(bus, self.path)

    def get_path(self) -> dbus.ObjectPath:
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self) -> dict[Any, dict[str, dict[str, Any]]]:
        result: dict[Any, dict[str, dict[str, Any]]] = {}
        for service in self.services:
            result[service.get_path()] = service.get_properties()
            for characteristic in service.characteristics:
                result[characteristic.get_path()] = characteristic.get_properties()
        return result


class Service(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus, index: int, uuid: str) -> None:
        self.path = f"{APPLICATION_PATH}/service{index:04d}"
        self.uuid = uuid
        self.characteristics: list[Characteristic] = []
        super().__init__(bus, self.path)

    def get_path(self) -> dbus.ObjectPath:
        return dbus.ObjectPath(self.path)

    def get_properties(self) -> dict[str, dict[str, Any]]:
        return {GATT_SERVICE_IFACE: {"UUID": self.uuid, "Primary": True, "Characteristics": dbus.Array([c.get_path() for c in self.characteristics], signature="o")}}


class Characteristic(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus, index: int, uuid: str, flags: list[str], service: Service, *, read_handler: Callable[[dict[str, Any]], bytes] | None = None, write_handler: Callable[[bytes, dict[str, Any]], None] | None = None) -> None:
        self.path = f"{service.path}/char{index:04d}"
        self.uuid, self.flags, self.service = uuid, flags, service
        self.read_handler, self.write_handler = read_handler, write_handler
        self.notifying = False
        super().__init__(bus, self.path)

    def get_path(self) -> dbus.ObjectPath:
        return dbus.ObjectPath(self.path)

    def get_properties(self) -> dict[str, dict[str, Any]]:
        return {GATT_CHRC_IFACE: {"Service": self.service.get_path(), "UUID": self.uuid, "Flags": self.flags, "Descriptors": dbus.Array([], signature="o")}}

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options: dict[str, Any]) -> list[int]:
        if not self.read_handler:
            raise NotSupportedException()
        return list(self.read_handler(options))

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value: list[int], options: dict[str, Any]) -> None:
        if not self.write_handler:
            raise NotSupportedException()
        mtu = int(options.get("mtu", DEFAULT_MTU))
        if len(value) > min(MAX_ATT_VALUE, max(0, mtu - 3)):
            raise InvalidValueLengthException()
        self.write_handler(bytes(value), options)

    def send_raw_notification(self, value: bytes) -> None:
        if self.notifying:
            self.PropertiesChanged(GATT_CHRC_IFACE, {"Value": dbus.Array(list(value), signature="y")}, [])

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self) -> None:
        self.notifying = True

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self) -> None:
        self.notifying = False

    @dbus.service.signal(DBUS_PROP_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface: str, changed: dict[str, Any], invalidated: list[str]) -> None:
        pass


class Advertisement(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus, local_name: str) -> None:
        self.path, self.local_name = ADVERTISEMENT_PATH, local_name
        super().__init__(bus, self.path)

    def get_path(self) -> dbus.ObjectPath:
        return dbus.ObjectPath(self.path)

    def _properties(self) -> dict[str, Any]:
        return {"Type": "peripheral", "ServiceUUIDs": dbus.Array([SERVICE_UUID], signature="s"), "LocalName": self.local_name, "IncludeTxPower": False}

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface: str) -> dict[str, Any]:
        if interface != LE_ADVERTISEMENT_IFACE:
            raise InvalidArgsException()
        return self._properties()

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface: str, prop: str) -> Any:
        if interface != LE_ADVERTISEMENT_IFACE or prop not in self._properties():
            raise InvalidArgsException()
        return self._properties()[prop]

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="ssv")
    def Set(self, interface: str, prop: str, value: Any) -> None:
        raise NotSupportedException()

    @dbus.service.method(LE_ADVERTISEMENT_IFACE)
    def Release(self) -> None:
        logger.info("advertisement released")


@dataclass
class EventBatch:
    device: str
    frames: list[bytes]
    close_after: bool = False


@dataclass
class DeviceSession:
    device: str
    reassembler: Reassembler = field(default_factory=Reassembler)
    channel: SecureChannel | None = None
    authenticated: bool = False
    mtu: int = DEFAULT_MTU
    last_seen: float = field(default_factory=time.monotonic)
    requests: RequestTracker = field(default_factory=RequestTracker)
    awaiting_ha_ack: set[int] = field(default_factory=set)
    tx_lock: threading.Lock = field(default_factory=threading.Lock)


class GattProvisioner:
    def __init__(self, local_name: str, adapter_wait: int = 30) -> None:
        self.local_name, self.adapter_wait = local_name, adapter_wait
        self.bus: dbus.SystemBus | None = None
        self.adapter_path: str | None = None
        self.event_characteristic: Characteristic | None = None
        self._sessions: dict[str, DeviceSession] = {}
        self._sessions_lock = threading.RLock()
        self._owner = ProvisioningOwner(SESSION_IDLE_SECONDS)
        self._events: queue.Queue[EventBatch] = queue.Queue(maxsize=64)
        self._executor = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="secure-command")
        self._work_slots = threading.BoundedSemaphore(MAX_PENDING_WORK)
        self._running, self._gatt_registered, self._ad_registered, self._registration_failed = True, False, False, False
        self._loop_mode = "null"
        self._handshake = ServerHandshake(load_device_identity(), load_app_keyring())

    @staticmethod
    def _device(options: dict[str, Any]) -> str:
        device = str(options.get("device", ""))
        if not device.startswith("/org/bluez/"):
            raise InvalidArgsException("BlueZ device option is required")
        return device

    def _session(self, device: str, mtu: int) -> DeviceSession:
        now = time.monotonic()
        with self._sessions_lock:
            for key in [key for key, value in self._sessions.items() if now - value.last_seen > SESSION_IDLE_SECONDS]:
                self._drop_device(key)
            session = self._sessions.get(device)
            if session is None:
                if len(self._sessions) >= MAX_SESSIONS:
                    raise ProtocolError("too many device sessions")
                session = DeviceSession(device=device)
                self._sessions[device] = session
            session.mtu, session.last_seen = max(DEFAULT_MTU, min(mtu, 512)), now
            return session

    def _drop_device(self, device: str) -> None:
        with self._sessions_lock:
            session = self._sessions.pop(str(device), None)
            if session is not None:
                self._owner.release(str(device))
                session.channel = None
                session.authenticated = False
                for request_id in tuple(session.awaiting_ha_ack):
                    session.requests.abandon(request_id)
                    self._work_slots.release()
                session.awaiting_ha_ack.clear()
                logger.info("cleared secure session for disconnected device %s", device)

    def _properties_changed(self, interface: str, changed: dict[str, Any], invalidated: list[str], path: str | None = None) -> None:
        if interface == DEVICE_IFACE and changed.get("Connected") is False and path:
            self._drop_device(path)

    def _read_descriptor(self, options: dict[str, Any]) -> bytes:
        self._device(options)
        return PROTOCOL_DESCRIPTOR

    def _queue_plain(
        self,
        session: DeviceSession,
        message_type: int,
        request_id: int,
        payload: dict[str, Any],
        *,
        close_after: bool = False,
    ) -> bool:
        if not session.channel:
            return False
        raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("ascii")
        total = INNER_HEADER_SIZE + len(raw) + AEAD_TAG_BYTES
        body_size = max(1, session.mtu - 3 - 10)
        count = (total + body_size - 1) // body_size
        with session.tx_lock:
            message_id = (session.channel.session_id ^ session.channel.tx_sequence) & 0xFFFF
            metadata = TransportMetadata(KIND_ENCRYPTED, message_id, count, total)
            ciphertext = session.channel.encrypt(message_type, request_id, raw, metadata)
            frames = fragment_message(KIND_ENCRYPTED, message_id, ciphertext, session.mtu - 3)
        try:
            self._events.put_nowait(EventBatch(session.device, frames, close_after))
            return True
        except queue.Full:
            logger.error("event queue full; closing session %s rather than losing terminal", session.device)
            self._drop_device(session.device)
            return False

    def _terminal(
        self,
        session: DeviceSession,
        request_id: int,
        message_type: int,
        payload: dict[str, Any],
        *,
        close_after: bool = False,
    ) -> None:
        queued = False
        try:
            with self._sessions_lock:
                session.requests.complete(request_id, message_type, payload)
            queued = self._queue_plain(
                session, message_type, request_id, payload, close_after=close_after
            )
        finally:
            self._work_slots.release()
        if not queued:
            with self._sessions_lock:
                session.requests.clear()

    def _progress(self, session: DeviceSession, request_id: int, stage: str) -> None:
        self._queue_plain(
            session,
            MSG_PROGRESS,
            request_id,
            {"event": "connect", "request_id": request_id, "terminal": False, "stage": stage},
        )

    def _run_request(self, session: DeviceSession, request_id: int, data: bytes) -> None:
        try:
            command = decode_json(data)
            cmd = str(command.get("cmd", "")).strip().lower()
            if cmd == "ha":
                response = {
                    "event": "ha",
                    "credentials": json.loads(get_credential_payload()),
                    "request_id": request_id,
                    "terminal": False,
                    "awaiting_ack": True,
                }
                session.awaiting_ha_ack.add(request_id)
                self._queue_plain(session, MSG_PROGRESS, request_id, response)
                return
            response = handle_command(
                command, lambda stage: self._progress(session, request_id, stage)
            )
            response["request_id"] = request_id
            response["terminal"] = True
            self._terminal(session, request_id, MSG_RESPONSE, response)
        except (HaCredentialError, WifiError, ValueError) as exc:
            self._terminal(session, request_id, MSG_ERROR, {"event": "error", "request_id": request_id, "terminal": True, "error": str(exc)})
        except Exception:
            logger.exception("secure command failed")
            self._terminal(session, request_id, MSG_ERROR, {"event": "error", "request_id": request_id, "terminal": True, "error": "command failed"})

    def _on_command(self, data: bytes, options: dict[str, Any]) -> None:
        device = self._device(options)
        session = self._session(device, int(options.get("mtu", DEFAULT_MTU)))
        try:
            result = session.reassembler.feed(data)
            if result is None:
                return
            metadata, message = result
            if metadata.kind == KIND_CLIENT_HELLO:
                server_hello, channel = self._handshake.accept(message)
                session.channel, session.authenticated = channel, False
                try:
                    self._events.put_nowait(
                        EventBatch(
                            device,
                            fragment_message(
                                KIND_SERVER_HELLO,
                                metadata.message_id,
                                server_hello,
                                session.mtu - 3,
                            ),
                        )
                    )
                except queue.Full:
                    self._drop_device(device)
                return
            if metadata.kind != KIND_ENCRYPTED or not session.channel:
                raise ProtocolError("encrypted record required")
            record = session.channel.decrypt(message, metadata)
            if not session.authenticated:
                if record.message_type != MSG_FINISHED or record.request_id != 0 or record.payload != FINISHED_PAYLOAD:
                    raise ProtocolError("valid encrypted Finished required")
                with self._sessions_lock:
                    if not self._owner.claim(device):
                        self._queue_plain(
                            session,
                            MSG_ERROR,
                            0,
                            {"event": "error", "terminal": True, "code": ERROR_BUSY},
                            close_after=True,
                        )
                        return
                session.authenticated = True
                self._queue_plain(session, MSG_FINISHED, 0, {"ok": True})
                return
            if record.message_type != MSG_REQUEST or record.request_id == 0:
                raise ProtocolError("authenticated request required")
            with self._sessions_lock:
                if not self._owner.touch(device):
                    self._queue_plain(
                        session,
                        MSG_ERROR,
                        record.request_id,
                        {"event": "error", "request_id": record.request_id, "terminal": True, "code": ERROR_BUSY},
                        close_after=True,
                    )
                    return
            command = decode_json(record.payload)
            if str(command.get("cmd", "")).strip().lower() == "close":
                acknowledged = command.get("ack_request_id")
                if (
                    isinstance(acknowledged, bool)
                    or not isinstance(acknowledged, int)
                    or record.request_id != acknowledged
                ):
                    raise ProtocolError("close request id must equal integer ack_request_id")
                with self._sessions_lock:
                    if acknowledged not in session.awaiting_ha_ack:
                        self._queue_plain(
                            session,
                            MSG_PROGRESS,
                            record.request_id,
                            {"event": "error", "request_id": record.request_id, "terminal": False, "code": "INVALID_ACK"},
                        )
                        return
                    session.awaiting_ha_ack.remove(acknowledged)
                self._terminal(
                    session,
                    acknowledged,
                    MSG_RESPONSE,
                    {"event": "close", "request_id": acknowledged, "ack_request_id": acknowledged, "terminal": True},
                    close_after=True,
                )
                return
            with self._sessions_lock:
                state, cached = session.requests.inspect(record.request_id, record.payload)
                if state == "in_progress":
                    self._queue_plain(
                        session,
                        MSG_PROGRESS,
                        record.request_id,
                        {"event": "request", "request_id": record.request_id, "terminal": False, "code": ERROR_IN_PROGRESS},
                    )
                    return
                if state == "conflict":
                    self._queue_plain(
                        session,
                        MSG_ERROR,
                        record.request_id,
                        {"event": "error", "request_id": record.request_id, "terminal": True, "code": ERROR_REQUEST_ID_CONFLICT},
                    )
                    return
                if state == "completed" and cached is not None:
                    self._queue_plain(session, cached.message_type, record.request_id, cached.payload)
                    return
                if not self._work_slots.acquire(blocking=False):
                    session.requests.abandon(record.request_id)
                    self._queue_plain(session, MSG_ERROR, record.request_id, {"event": "error", "request_id": record.request_id, "terminal": True, "code": ERROR_BUSY})
                    return
            try:
                self._executor.submit(self._run_request, session, record.request_id, record.payload)
            except RuntimeError:
                with self._sessions_lock:
                    session.requests.abandon(record.request_id)
                self._work_slots.release()
                self._queue_plain(session, MSG_ERROR, record.request_id, {"event": "error", "request_id": record.request_id, "terminal": True, "code": ERROR_BUSY})
        except ProtocolError as exc:
            logger.warning("rejected protocol input from %s: %s", device, exc)
            self._drop_device(device)

    def _find_adapter(self) -> str:
        assert self.bus is not None
        objects = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, "/"), DBUS_OM_IFACE).GetManagedObjects()
        for path, interfaces in objects.items():
            if GATT_MANAGER_IFACE in interfaces and LE_ADVERTISING_MANAGER_IFACE in interfaces:
                return str(path)
        raise RuntimeError("no BLE adapter with GATT and advertising support found")

    def _wait_for_adapter(self) -> str:
        deadline = time.monotonic() + self.adapter_wait
        while time.monotonic() < deadline:
            try:
                return self._find_adapter()
            except RuntimeError:
                assert self.bus is not None
                iterate_main_loop(self.bus, self._loop_mode)
        raise RuntimeError("timed out waiting for BLE adapter")

    def _register_error(self, label: str) -> Callable[[Any], None]:
        def handler(error: Any) -> None:
            logger.error("%s registration failed: %s", label, error)
            self._registration_failed, self._running = True, False
        return handler

    def _register(self) -> None:
        assert self.bus is not None and self.adapter_path is not None
        app, service = Application(self.bus), Service(self.bus, 0, SERVICE_UUID)
        status = Characteristic(self.bus, 0, WIFI_STATUS_UUID, ["read"], service, read_handler=self._read_descriptor)
        command = Characteristic(self.bus, 1, WIFI_COMMAND_UUID, ["write", "write-without-response"], service, write_handler=self._on_command)
        event = Characteristic(self.bus, 2, WIFI_EVENT_UUID, ["notify"], service)
        service.characteristics.extend([status, command, event]); app.services.append(service)
        self.event_characteristic = event
        manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path), GATT_MANAGER_IFACE)
        manager.RegisterApplication(app.get_path(), {}, reply_handler=lambda: setattr(self, "_gatt_registered", True), error_handler=self._register_error("GATT"))
        ad = Advertisement(self.bus, self.local_name)
        ad_manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path), LE_ADVERTISING_MANAGER_IFACE)
        ad_manager.RegisterAdvertisement(ad.get_path(), {}, reply_handler=lambda: setattr(self, "_ad_registered", True), error_handler=self._register_error("advertisement"))

    def run(self) -> None:
        self._loop_mode = setup_dbus_main_loop(); self.bus = dbus.SystemBus(); self.adapter_path = self._wait_for_adapter()
        props = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path), DBUS_PROP_IFACE)
        props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(True)); props.Set(ADAPTER_IFACE, "Discoverable", dbus.Boolean(False)); props.Set(ADAPTER_IFACE, "Pairable", dbus.Boolean(False)); props.Set(ADAPTER_IFACE, "Alias", self.local_name)
        self.bus.add_signal_receiver(self._properties_changed, dbus_interface=DBUS_PROP_IFACE, signal_name="PropertiesChanged", path_keyword="path")
        self._register()
        try:
            while self._running:
                if self._registration_failed:
                    raise RuntimeError("GATT registration failed")
                try:
                    batch = self._events.get_nowait()
                    if self.event_characteristic:
                        for frame in batch.frames:
                            self.event_characteristic.send_raw_notification(frame)
                    if batch.close_after:
                        self._drop_device(batch.device)
                except queue.Empty:
                    pass
                iterate_main_loop(self.bus, self._loop_mode)
        finally:
            self._executor.shutdown(wait=False, cancel_futures=True)
