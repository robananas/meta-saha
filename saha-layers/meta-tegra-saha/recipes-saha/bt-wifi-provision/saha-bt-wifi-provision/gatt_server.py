#!/usr/bin/env python3
"""BlueZ GATT server for Roban WiFi provisioning."""

from __future__ import annotations

import copy
import logging
import queue
import threading
import time
from typing import Any, Callable

import dbus
import dbus.exceptions
import dbus.service

from dbus_mainloop import iterate_main_loop, setup_dbus_main_loop
from wifi_manager import WifiError, decode_json, encode_json, get_wifi_status, handle_command

BLUEZ_SERVICE_NAME = "org.bluez"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"
AGENT_MANAGER_IFACE = "org.bluez.AgentManager1"
AGENT_IFACE = "org.bluez.Agent1"

SERVICE_UUID = "a0a0ff10-0000-1000-8000-00805f9b34fb"
WIFI_STATUS_UUID = "a0a0ff11-0000-1000-8000-00805f9b34fb"
WIFI_COMMAND_UUID = "a0a0ff12-0000-1000-8000-00805f9b34fb"
WIFI_EVENT_UUID = "a0a0ff13-0000-1000-8000-00805f9b34fb"

APPLICATION_PATH = "/org/roban/bt_wifi"
SERVICE_PATH = f"{APPLICATION_PATH}/service0000"
STATUS_PATH = f"{SERVICE_PATH}/char0000"
COMMAND_PATH = f"{SERVICE_PATH}/char0001"
EVENT_PATH = f"{SERVICE_PATH}/char0002"
ADVERTISEMENT_PATH = f"{APPLICATION_PATH}/advertisement0000"
AGENT_PATH = f"{APPLICATION_PATH}/agent"

logger = logging.getLogger("saha-bt-wifi-provision")


def _unavailable_wifi_status(error: str = "WiFi status has not been refreshed") -> dict[str, Any]:
    return {
        "connected": False,
        "ssid": "",
        "interface": "",
        "ip": "",
        "addresses": [],
        "gateway": "",
        "dns": [],
        "signal": 0,
        "security": "",
        "available": False,
        "error": error,
    }


class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"


class NotSupportedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotSupported"


class PairingAgent(dbus.service.Object):
    """BlueZ NoInputNoOutput agent for Just Works bonding."""

    def __init__(self, bus: dbus.SystemBus) -> None:
        self.path = AGENT_PATH
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self) -> dbus.ObjectPath:
        return dbus.ObjectPath(self.path)

    @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
    def Release(self) -> None:
        logger.info("pairing agent released")

    @dbus.service.method(AGENT_IFACE, in_signature="ou", out_signature="")
    def RequestConfirmation(self, device: dbus.ObjectPath, passkey: int) -> None:
        logger.info("accepting Just Works pairing from %s (passkey %06d)", device, passkey)

    @dbus.service.method(AGENT_IFACE, in_signature="o", out_signature="")
    def RequestAuthorization(self, device: dbus.ObjectPath) -> None:
        logger.info("authorizing Just Works pairing from %s", device)

    @dbus.service.method(AGENT_IFACE, in_signature="os", out_signature="")
    def AuthorizeService(self, device: dbus.ObjectPath, uuid: str) -> None:
        logger.info("authorizing service %s for %s", uuid, device)

    @dbus.service.method(AGENT_IFACE, in_signature="", out_signature="")
    def Cancel(self) -> None:
        logger.info("pairing request cancelled")


class Application(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus) -> None:
        self.path = APPLICATION_PATH
        self.services: list[Service] = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self) -> str:
        return dbus.ObjectPath(self.path)

    def add_service(self, service: "Service") -> None:
        self.services.append(service)

    @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self) -> dict[Any, dict[str, dict[str, Any]]]:
        response: dict[Any, dict[str, dict[str, Any]]] = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            for characteristic in service.characteristics:
                response[characteristic.get_path()] = characteristic.get_properties()
        return response


class Service(dbus.service.Object):
    PATH_BASE = f"{APPLICATION_PATH}/service"

    def __init__(self, bus: dbus.SystemBus, index: int, uuid: str, primary: bool) -> None:
        self.path = f"{self.PATH_BASE}{index:04d}"
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics: list[Characteristic] = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self) -> dbus.ObjectPath:
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic: "Characteristic") -> None:
        self.characteristics.append(characteristic)

    def get_properties(self) -> dict[str, dict[str, Any]]:
        return {
            GATT_SERVICE_IFACE: {
                "UUID": self.uuid,
                "Primary": self.primary,
                "Characteristics": dbus.Array(
                    [char.get_path() for char in self.characteristics],
                    signature="o",
                ),
            }
        }


class Characteristic(dbus.service.Object):
    def __init__(
        self,
        bus: dbus.SystemBus,
        index: int,
        uuid: str,
        flags: list[str],
        service: Service,
        *,
        read_handler: Callable[[], list[int]] | None = None,
        write_handler: Callable[[bytes], None] | None = None,
    ) -> None:
        self.path = f"{service.path}/char{index:04d}"
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.read_handler = read_handler
        self.write_handler = write_handler
        self.notifying = False
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self) -> dbus.ObjectPath:
        return dbus.ObjectPath(self.path)

    def get_properties(self) -> dict[str, dict[str, Any]]:
        return {
            GATT_CHRC_IFACE: {
                "Service": self.service.get_path(),
                "UUID": self.uuid,
                "Flags": self.flags,
                "Descriptors": dbus.Array([], signature="o"),
            }
        }

    def send_notification(self, payload: dict[str, Any]) -> None:
        if not self.notifying:
            return
        value = encode_json(payload)
        self.PropertiesChanged(GATT_CHRC_IFACE, {"Value": dbus.Array(value, signature="y")}, [])

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options: dict[str, Any]) -> list[int]:  # noqa: ARG002
        if not self.read_handler:
            raise NotSupportedException()
        try:
            return self.read_handler()
        except Exception as exc:  # noqa: BLE001
            logger.exception("characteristic read handler failed for %s", self.uuid)
            return encode_json(_unavailable_wifi_status(str(exc) or "status read failed"))

    @dbus.service.method(GATT_CHRC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value: list[int], options: dict[str, Any]) -> None:  # noqa: ARG002
        if not self.write_handler:
            raise NotSupportedException()
        self.write_handler(bytes(value))

    @dbus.service.method(GATT_CHRC_IFACE)
    def StartNotify(self) -> None:
        self.notifying = True

    @dbus.service.method(GATT_CHRC_IFACE)
    def StopNotify(self) -> None:
        self.notifying = False

    @dbus.service.signal(DBUS_PROP_IFACE, signature="sa{sv}as")
    def PropertiesChanged(
        self,
        interface: str,
        changed: dict[str, Any],
        invalidated: list[str],
    ) -> None:
        pass


class Advertisement(dbus.service.Object):
    PATH_BASE = f"{APPLICATION_PATH}/advertisement"

    def __init__(self, bus: dbus.SystemBus, index: int, local_name: str) -> None:
        self.path = f"{self.PATH_BASE}{index:04d}"
        self.local_name = local_name
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self) -> dbus.ObjectPath:
        return dbus.ObjectPath(self.path)

    def _advertisement_properties(self) -> dict[str, Any]:
        return {
            "Type": "peripheral",
            "ServiceUUIDs": dbus.Array([SERVICE_UUID], signature="s"),
            "LocalName": self.local_name,
            "IncludeTxPower": dbus.Boolean(False),
        }

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface: str) -> dict[str, Any]:
        if interface != LE_ADVERTISEMENT_IFACE:
            raise InvalidArgsException()
        return self._advertisement_properties()

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface: str, prop: str) -> Any:
        if interface != LE_ADVERTISEMENT_IFACE:
            raise InvalidArgsException()
        props = self._advertisement_properties()
        if prop not in props:
            raise InvalidArgsException()
        return props[prop]

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="ssv")
    def Set(self, interface: str, prop: str, value: Any) -> None:  # noqa: ARG002
        raise NotSupportedException()

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature="", out_signature="")
    def Release(self) -> None:
        logger.info("advertisement released")


class GattProvisioner:
    def __init__(self, local_name: str, adapter_wait: int = 30) -> None:
        self.local_name = local_name
        self.adapter_wait = adapter_wait
        self.bus: dbus.SystemBus | None = None
        self.adapter_path: str | None = None
        self.event_characteristic: Characteristic | None = None
        self._event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._running = True
        self._gatt_registered = False
        self._ad_registered = False
        self._registration_failed = False
        self._loop_mode = "null"
        self._pairing_agent: PairingAgent | None = None
        self._status_lock = threading.Lock()
        self._status_cache = _unavailable_wifi_status()
        self._status_has_success = False
        self._status_stop = threading.Event()
        self._status_thread: threading.Thread | None = None

    def _refresh_status(self) -> None:
        try:
            status = get_wifi_status()
        except Exception as exc:  # noqa: BLE001
            error = str(exc) or exc.__class__.__name__
            logger.warning("failed to refresh WiFi status cache: %s", error)
            with self._status_lock:
                if self._status_has_success:
                    status = copy.deepcopy(self._status_cache)
                    status["available"] = False
                    status["error"] = error
                    self._status_cache = status
                else:
                    self._status_cache = _unavailable_wifi_status(error)
            return

        cached = copy.deepcopy(status)
        cached["available"] = True
        cached["error"] = ""
        with self._status_lock:
            self._status_cache = cached
            self._status_has_success = True

    def _status_refresh_worker(self) -> None:
        while not self._status_stop.is_set():
            self._refresh_status()
            if self._status_stop.wait(2.5):
                return

    def _start_status_refresh(self) -> None:
        self._status_thread = threading.Thread(
            target=self._status_refresh_worker,
            name="wifi-status-refresh",
            daemon=True,
        )
        self._status_thread.start()

    def _read_cached_status(self) -> list[int]:
        with self._status_lock:
            status = copy.deepcopy(self._status_cache)
        return encode_json(status)

    def _list_adapters(self) -> None:
        assert self.bus is not None
        remote_om = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            DBUS_OM_IFACE,
        )
        objects = remote_om.GetManagedObjects()
        for path, interfaces in objects.items():
            if "org.bluez.Adapter1" in interfaces:
                logger.info(
                    "adapter %s interfaces: %s",
                    path,
                    ", ".join(sorted(interfaces.keys())),
                )

    def _find_adapter(self) -> str:
        assert self.bus is not None
        remote_om = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            DBUS_OM_IFACE,
        )
        objects = remote_om.GetManagedObjects()
        for path, interfaces in objects.items():
            if GATT_MANAGER_IFACE in interfaces and LE_ADVERTISING_MANAGER_IFACE in interfaces:
                return str(path)
        raise RuntimeError("no BLE adapter with GATT and advertising support found")

    def _wait_for_adapter(self) -> str:
        assert self.bus is not None
        deadline = time.time() + self.adapter_wait
        while time.time() < deadline:
            try:
                return self._find_adapter()
            except RuntimeError:
                iterate_main_loop(self.bus, self._loop_mode)
        self._list_adapters()
        raise RuntimeError(
            "no BLE adapter with GATT and advertising support found after "
            f"{self.adapter_wait}s"
        )

    def _on_command(self, data: bytes) -> None:
        def worker() -> None:
            try:
                payload = decode_json(data)
                response = handle_command(payload)
            except WifiError as exc:
                response = {"event": "error", "error": str(exc)}
            except Exception as exc:  # noqa: BLE001
                logger.exception("command failed")
                response = {"event": "error", "error": str(exc)}
            self._event_queue.put(response)

        threading.Thread(target=worker, daemon=True).start()

    def _register_pairing_agent(self) -> None:
        assert self.bus is not None
        self._pairing_agent = PairingAgent(self.bus)
        manager = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE_NAME, "/org/bluez"),
            AGENT_MANAGER_IFACE,
        )
        manager.RegisterAgent(self._pairing_agent.get_path(), "NoInputNoOutput")
        manager.RequestDefaultAgent(self._pairing_agent.get_path())
        logger.info("registered NoInputNoOutput pairing agent")

    def _register_advertisement(self) -> None:
        assert self.bus is not None and self.adapter_path is not None
        ad_manager = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path),
            LE_ADVERTISING_MANAGER_IFACE,
        )
        advertisement = Advertisement(self.bus, 0, self.local_name)
        ad_manager.RegisterAdvertisement(
            advertisement.get_path(),
            {},
            reply_handler=lambda: self._mark_ad_registered(),
            error_handler=self._register_error("advertisement"),
        )

    def _mark_gatt_registered(self) -> None:
        self._gatt_registered = True
        logger.info("GATT application registered")

    def _mark_ad_registered(self) -> None:
        self._ad_registered = True
        logger.info("advertisement registered")

    def _register_application(self) -> None:
        assert self.bus is not None and self.adapter_path is not None
        app = Application(self.bus)
        service = Service(self.bus, 0, SERVICE_UUID, True)

        status_char = Characteristic(
            self.bus,
            0,
            WIFI_STATUS_UUID,
            ["read", "encrypt-read"],
            service,
            read_handler=self._read_cached_status,
        )
        command_char = Characteristic(
            self.bus,
            1,
            WIFI_COMMAND_UUID,
            ["write", "write-without-response", "encrypt-write"],
            service,
            write_handler=self._on_command,
        )
        event_char = Characteristic(
            self.bus,
            2,
            WIFI_EVENT_UUID,
            ["notify", "encrypt-read"],
            service,
        )
        self.event_characteristic = event_char

        service.add_characteristic(status_char)
        service.add_characteristic(command_char)
        service.add_characteristic(event_char)
        app.add_service(service)

        gatt_manager = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path),
            GATT_MANAGER_IFACE,
        )
        gatt_manager.RegisterApplication(
            app.get_path(),
            {},
            reply_handler=lambda: self._mark_gatt_registered(),
            error_handler=self._register_error("GATT application"),
        )

    def _register_error(self, label: str) -> Callable[[Any], None]:
        def handler(error: Any) -> None:
            logger.error("%s registration failed: %s", label, error)
            self._registration_failed = True
            self._running = False

        return handler

    def _wait_for_registration(self) -> None:
        assert self.bus is not None
        for _ in range(100):
            if self._registration_failed:
                raise RuntimeError("GATT or advertisement registration failed")
            if self._gatt_registered and self._ad_registered:
                return
            iterate_main_loop(self.bus, self._loop_mode)
        raise RuntimeError("timed out waiting for GATT registration")

    def _dispatch_pending_events(self) -> None:
        while True:
            try:
                response = self._event_queue.get_nowait()
            except queue.Empty:
                break
            if self.event_characteristic is not None:
                self.event_characteristic.send_notification(response)

    def run(self) -> None:
        self._loop_mode = setup_dbus_main_loop()
        self.bus = dbus.SystemBus()
        self.adapter_path = self._wait_for_adapter()
        logger.info("using adapter %s", self.adapter_path)

        props = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path),
            DBUS_PROP_IFACE,
        )
        props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
        props.Set("org.bluez.Adapter1", "Discoverable", dbus.Boolean(False))
        props.Set("org.bluez.Adapter1", "Pairable", dbus.Boolean(True))
        props.Set("org.bluez.Adapter1", "Alias", self.local_name)

        self._register_pairing_agent()
        self._start_status_refresh()
        try:
            self._register_application()
            self._register_advertisement()
            self._wait_for_registration()
            logger.info("BLE WiFi provisioning active as %s", self.local_name)

            while self._running:
                self._dispatch_pending_events()
                iterate_main_loop(self.bus, self._loop_mode)

            if self._registration_failed:
                raise RuntimeError("GATT or advertisement registration failed")
        finally:
            self._status_stop.set()
            if self._status_thread is not None:
                self._status_thread.join(timeout=1.0)
