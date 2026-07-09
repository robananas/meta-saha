#!/usr/bin/env python3
"""BlueZ GATT server for Roban WiFi provisioning."""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

import dbus
import dbus.exceptions
import dbus.service

from wifi_manager import WifiError, decode_json, encode_json, get_wifi_status, handle_command

BLUEZ_SERVICE_NAME = "org.bluez"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"

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

logger = logging.getLogger("saha-bt-wifi-provision")


class InvalidArgsException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"


class NotSupportedException(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotSupported"


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
        return self.read_handler()

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

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature="", out_signature="")
    def Release(self) -> None:
        logger.info("advertisement released")

    @dbus.service.property(LE_ADVERTISEMENT_IFACE, "Type", in_signature="s", emit_constant=True)
    def Type(self) -> str:
        return "peripheral"

    @dbus.service.property(LE_ADVERTISEMENT_IFACE, "ServiceUUIDs", in_signature="as", emit_constant=True)
    def ServiceUUIDs(self) -> list[str]:
        return [SERVICE_UUID]

    @dbus.service.property(LE_ADVERTISEMENT_IFACE, "LocalName", in_signature="s", emit_constant=True)
    def LocalName(self) -> str:
        return self.local_name

    @dbus.service.property(LE_ADVERTISEMENT_IFACE, "IncludeTxPower", in_signature="b", emit_constant=True)
    def IncludeTxPower(self) -> bool:
        return False


class GattProvisioner:
    def __init__(self, local_name: str) -> None:
        self.local_name = local_name
        self.bus: dbus.SystemBus | None = None
        self.adapter_path: str | None = None
        self.event_characteristic: Characteristic | None = None
        self._event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._running = True

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
            reply_handler=lambda: logger.info("advertisement registered"),
            error_handler=self._register_error("advertisement"),
        )

    def _register_application(self) -> None:
        assert self.bus is not None and self.adapter_path is not None
        app = Application(self.bus)
        service = Service(self.bus, 0, SERVICE_UUID, True)

        status_char = Characteristic(
            self.bus,
            0,
            WIFI_STATUS_UUID,
            ["read"],
            service,
            read_handler=lambda: encode_json(get_wifi_status()),
        )
        command_char = Characteristic(
            self.bus,
            1,
            WIFI_COMMAND_UUID,
            ["write", "write-without-response"],
            service,
            write_handler=self._on_command,
        )
        event_char = Characteristic(
            self.bus,
            2,
            WIFI_EVENT_UUID,
            ["notify"],
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
            reply_handler=lambda: logger.info("GATT application registered"),
            error_handler=self._register_error("GATT application"),
        )

    def _register_error(self, label: str) -> Callable[[Any], None]:
        def handler(error: Any) -> None:
            logger.error("%s registration failed: %s", label, error)
            self._running = False

        return handler

    def _dispatch_pending_events(self) -> None:
        while True:
            try:
                response = self._event_queue.get_nowait()
            except queue.Empty:
                break
            if self.event_characteristic is not None:
                self.event_characteristic.send_notification(response)

    def run(self) -> None:
        self.bus = dbus.SystemBus()
        self.adapter_path = self._find_adapter()
        logger.info("using adapter %s", self.adapter_path)

        props = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE_NAME, self.adapter_path),
            DBUS_PROP_IFACE,
        )
        props.Set("org.bluez.Adapter1", "Powered", dbus.Boolean(True))
        props.Set("org.bluez.Adapter1", "Alias", self.local_name)

        self._register_application()
        self._register_advertisement()

        while self._running:
            self._dispatch_pending_events()
            if self.bus.connection.read_write_dispatch(timeout=200):
                continue
