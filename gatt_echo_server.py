#!/usr/bin/env python3
"""BlueZ GATT compatibility server for communication testing."""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import signal
import sys
from typing import Any, Callable

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import dbus.service


BLUEZ_SERVICE = "org.bluez"
DBUS_OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
DBUS_PROPERTIES = "org.freedesktop.DBus.Properties"
GATT_MANAGER = "org.bluez.GattManager1"
GATT_SERVICE = "org.bluez.GattService1"
GATT_CHARACTERISTIC = "org.bluez.GattCharacteristic1"
ADVERTISING_MANAGER = "org.bluez.LEAdvertisingManager1"
ADVERTISEMENT = "org.bluez.LEAdvertisement1"

# DEVELOPMENT ONLY: these UUIDs intentionally do not overlap production Roban GATT.
ECHO_SERVICE_UUID = "7b7e0001-f3a0-4b6f-8a1e-4c70d2e2a001"
ECHO_UUID = "7b7e0002-f3a0-4b6f-8a1e-4c70d2e2a2ff"

LEGACY_SERVICE_UUID = "7b7e0010-f3a0-4b6f-8a1e-4c70d2e2a001"
LEGACY_STATUS_UUID = "7b7e0011-f3a0-4b6f-8a1e-4c70d2e2a001"
LEGACY_COMMAND_UUID = "7b7e0012-f3a0-4b6f-8a1e-4c70d2e2a001"
LEGACY_EVENT_UUID = "7b7e0013-f3a0-4b6f-8a1e-4c70d2e2a001"

LOCAL_NAME = "Roban-DEV-INSECURE"

APP_PATH = "/org/roban/gatt_test"
ECHO_SERVICE_PATH = f"{APP_PATH}/service0"
ECHO_CHARACTERISTIC_PATH = f"{ECHO_SERVICE_PATH}/char0"
LEGACY_SERVICE_PATH = f"{APP_PATH}/service1"
ADVERTISEMENT_PATH = f"{APP_PATH}/advertisement0"

LOG = logging.getLogger("roban-gatt-test")


class InvalidArgs(dbus.exceptions.DBusException):
    _dbus_error_name = "org.freedesktop.DBus.Error.InvalidArgs"


class InvalidValueLength(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.InvalidValueLength"


class InvalidOffset(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.InvalidOffset"


class NotSupported(dbus.exceptions.DBusException):
    _dbus_error_name = "org.bluez.Error.NotSupported"


class GLibLoop:
    """Run the GLib main loop without requiring PyGObject/gi."""

    def __init__(self) -> None:
        library = ctypes.util.find_library("glib-2.0")
        if not library:
            raise RuntimeError("libglib-2.0 was not found")

        self._glib = ctypes.CDLL(library)
        self._glib.g_main_loop_new.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self._glib.g_main_loop_new.restype = ctypes.c_void_p
        self._glib.g_main_loop_run.argtypes = [ctypes.c_void_p]
        self._glib.g_main_loop_run.restype = None
        self._glib.g_main_loop_quit.argtypes = [ctypes.c_void_p]
        self._glib.g_main_loop_quit.restype = None
        self._glib.g_main_loop_unref.argtypes = [ctypes.c_void_p]
        self._glib.g_main_loop_unref.restype = None

        self._loop = self._glib.g_main_loop_new(None, False)
        if not self._loop:
            raise RuntimeError("failed to create GLib main loop")

    def run(self) -> None:
        self._glib.g_main_loop_run(self._loop)

    def quit(self) -> None:
        self._glib.g_main_loop_quit(self._loop)

    def close(self) -> None:
        if self._loop:
            self._glib.g_main_loop_unref(self._loop)
            self._loop = None


class Application(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus) -> None:
        self.path = APP_PATH
        self.services: list[Service] = []
        super().__init__(bus, self.path)

    def add_service(self, service: "Service") -> None:
        self.services.append(service)

    @dbus.service.method(DBUS_OBJECT_MANAGER, out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self) -> dict[Any, dict[str, dict[str, Any]]]:
        objects: dict[Any, dict[str, dict[str, Any]]] = {}
        for service in self.services:
            objects[service.path] = service.properties()
            for characteristic in service.characteristics:
                objects[characteristic.path] = characteristic.properties()
        return objects


class Service(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus, path: str, uuid: str) -> None:
        self.path = dbus.ObjectPath(path)
        self.uuid = uuid
        self.characteristics: list[Any] = []
        super().__init__(bus, self.path)

    def add_characteristic(self, characteristic: Any) -> None:
        self.characteristics.append(characteristic)

    def properties(self) -> dict[str, dict[str, Any]]:
        return {
            GATT_SERVICE: {
                "UUID": dbus.String(self.uuid),
                "Primary": dbus.Boolean(True),
                "Characteristics": dbus.Array(
                    [item.path for item in self.characteristics], signature="o"
                ),
            }
        }


class EchoCharacteristic(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus, service: Service) -> None:
        self.path = dbus.ObjectPath(ECHO_CHARACTERISTIC_PATH)
        self.service = service
        self.value = b"READY"
        self.notifying = False
        super().__init__(bus, self.path)

    def properties(self) -> dict[str, dict[str, Any]]:
        return {
            GATT_CHARACTERISTIC: {
                "Service": self.service.path,
                "UUID": dbus.String(ECHO_UUID),
                "Flags": dbus.Array(
                    ["read", "write", "write-without-response", "notify"],
                    signature="s",
                ),
                "Descriptors": dbus.Array([], signature="o"),
            }
        }

    @staticmethod
    def _byte_array(value: bytes) -> dbus.Array:
        return dbus.Array([dbus.Byte(item) for item in value], signature="y")

    def _notify(self) -> None:
        self.PropertiesChanged(
            GATT_CHARACTERISTIC,
            {"Value": self._byte_array(self.value)},
            dbus.Array([], signature="s"),
        )

    @dbus.service.method(GATT_CHARACTERISTIC, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options: dict[str, Any]) -> dbus.Array:  # noqa: ARG002
        LOG.info("read value: %d bytes", len(self.value))
        offset = int(options.get("offset", 0))
        if offset < 0 or offset > len(self.value):
            raise InvalidOffset("invalid read offset")
        return self._byte_array(self.value[offset:])

    @dbus.service.method(GATT_CHARACTERISTIC, in_signature="aya{sv}", out_signature="")
    def WriteValue(self, value: list[int], options: dict[str, Any]) -> None:
        payload = bytes(value)
        offset = int(options.get("offset", 0))
        if offset != 0:
            raise InvalidOffset("long/reliable writes are not supported by this test service")

        mtu = int(options.get("mtu", 23))
        maximum = min(512, max(0, mtu - 3))
        if len(payload) > maximum:
            raise InvalidValueLength(
                f"value is {len(payload)} bytes; maximum for MTU {mtu} is {maximum}"
            )

        self.value = payload
        write_type = str(options.get("type", "request"))
        device = str(options.get("device", "unknown"))
        preview = payload[:64].hex(" ")
        LOG.info(
            "rx: len=%d type=%s mtu=%d device=%s hex=%s%s",
            len(payload),
            write_type,
            mtu,
            device,
            preview,
            " ..." if len(payload) > 64 else "",
        )

        if self.notifying:
            self._notify()
            LOG.info("tx echo notification: %d bytes", len(payload))
        else:
            LOG.info("notification not enabled; value is available through read")

    @dbus.service.method(GATT_CHARACTERISTIC, in_signature="", out_signature="")
    def StartNotify(self) -> None:
        if self.notifying:
            return
        self.notifying = True
        LOG.info("notifications enabled")
        self._notify()

    @dbus.service.method(GATT_CHARACTERISTIC, in_signature="", out_signature="")
    def StopNotify(self) -> None:
        self.notifying = False
        LOG.info("notifications disabled")

    @dbus.service.signal(DBUS_PROPERTIES, signature="sa{sv}as")
    def PropertiesChanged(
        self,
        interface: str,
        changed: dict[str, Any],
        invalidated: list[str],
    ) -> None:
        pass


class LegacyCharacteristic(dbus.service.Object):
    """Open-access compatibility characteristic with no provisioning logic."""

    def __init__(
        self,
        bus: dbus.SystemBus,
        service: Service,
        index: int,
        uuid: str,
        flags: list[str],
    ) -> None:
        self.path = dbus.ObjectPath(f"{service.path}/char{index}")
        self.service = service
        self.uuid = uuid
        self.flags = flags
        self.value = b"ok"
        self.notifying = False
        super().__init__(bus, self.path)

    def properties(self) -> dict[str, dict[str, Any]]:
        return {
            GATT_CHARACTERISTIC: {
                "Service": self.service.path,
                "UUID": dbus.String(self.uuid),
                "Flags": dbus.Array(self.flags, signature="s"),
                "Descriptors": dbus.Array([], signature="o"),
            }
        }

    @staticmethod
    def _byte_array(value: bytes) -> dbus.Array:
        return dbus.Array([dbus.Byte(item) for item in value], signature="y")

    @dbus.service.method(GATT_CHARACTERISTIC, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options: dict[str, Any]) -> dbus.Array:
        if "read" not in self.flags:
            raise NotSupported()
        offset = int(options.get("offset", 0))
        if offset < 0 or offset > len(self.value):
            raise InvalidOffset("invalid read offset")
        device = str(options.get("device", "unknown"))
        LOG.info(
            "legacy read: uuid=%s device=%s value=%r",
            self.uuid,
            device,
            self.value,
        )
        return self._byte_array(self.value[offset:])

    @dbus.service.method(GATT_CHARACTERISTIC, in_signature="aya{sv}", out_signature="")
    def WriteValue(self, value: list[int], options: dict[str, Any]) -> None:
        if "write" not in self.flags and "write-without-response" not in self.flags:
            raise NotSupported()

        payload = bytes(value)
        offset = int(options.get("offset", 0))
        if offset != 0:
            raise InvalidOffset("long/reliable writes are not supported by this test service")

        mtu = int(options.get("mtu", 23))
        maximum = min(512, max(0, mtu - 3))
        if len(payload) > maximum:
            raise InvalidValueLength(
                f"value is {len(payload)} bytes; maximum for MTU {mtu} is {maximum}"
            )

        write_type = str(options.get("type", "request"))
        device = str(options.get("device", "unknown"))
        LOG.info(
            "legacy rx: uuid=%s len=%d type=%s mtu=%d device=%s",
            self.uuid,
            len(payload),
            write_type,
            mtu,
            device,
        )

    @dbus.service.method(GATT_CHARACTERISTIC, in_signature="", out_signature="")
    def StartNotify(self) -> None:
        if "notify" not in self.flags:
            raise NotSupported()
        if self.notifying:
            return
        self.notifying = True
        LOG.info("legacy notifications enabled: uuid=%s", self.uuid)

    @dbus.service.method(GATT_CHARACTERISTIC, in_signature="", out_signature="")
    def StopNotify(self) -> None:
        if "notify" not in self.flags:
            raise NotSupported()
        self.notifying = False
        LOG.info("legacy notifications disabled: uuid=%s", self.uuid)

    @dbus.service.signal(DBUS_PROPERTIES, signature="sa{sv}as")
    def PropertiesChanged(
        self,
        interface: str,
        changed: dict[str, Any],
        invalidated: list[str],
    ) -> None:
        pass


class Advertisement(dbus.service.Object):
    def __init__(self, bus: dbus.SystemBus) -> None:
        self.path = dbus.ObjectPath(ADVERTISEMENT_PATH)
        super().__init__(bus, self.path)

    @staticmethod
    def properties() -> dict[str, Any]:
        return {
            "Type": dbus.String("peripheral"),
            # Advertise the compatibility UUID exactly like the original
            # service. The echo service remains discoverable after connecting.
            "ServiceUUIDs": dbus.Array([LEGACY_SERVICE_UUID], signature="s"),
            "LocalName": dbus.String(LOCAL_NAME),
        }

    @dbus.service.method(DBUS_PROPERTIES, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface: str) -> dict[str, Any]:
        if interface != ADVERTISEMENT:
            raise InvalidArgs()
        return self.properties()

    @dbus.service.method(DBUS_PROPERTIES, in_signature="ss", out_signature="v")
    def Get(self, interface: str, prop: str) -> Any:
        if interface != ADVERTISEMENT:
            raise InvalidArgs()
        properties = self.properties()
        if prop not in properties:
            raise InvalidArgs()
        return properties[prop]

    @dbus.service.method(DBUS_PROPERTIES, in_signature="ssv", out_signature="")
    def Set(self, interface: str, prop: str, value: Any) -> None:  # noqa: ARG002
        raise NotSupported()

    @dbus.service.method(ADVERTISEMENT, in_signature="", out_signature="")
    def Release(self) -> None:
        LOG.info("advertisement released")


class EchoGattServer:
    def __init__(self) -> None:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.loop = GLibLoop()
        self.bus = dbus.SystemBus()
        self.adapter_path = self._find_adapter()
        self.fatal_error = False
        self.gatt_registered = False
        self.ad_registered = False

        self.application = Application(self.bus)
        self.echo_service = Service(
            self.bus, ECHO_SERVICE_PATH, ECHO_SERVICE_UUID
        )
        self.echo_characteristic = EchoCharacteristic(self.bus, self.echo_service)
        self.echo_service.add_characteristic(self.echo_characteristic)
        self.application.add_service(self.echo_service)

        self.legacy_service = Service(
            self.bus, LEGACY_SERVICE_PATH, LEGACY_SERVICE_UUID
        )
        self.legacy_status = LegacyCharacteristic(
            self.bus,
            self.legacy_service,
            0,
            LEGACY_STATUS_UUID,
            ["read"],
        )
        self.legacy_command = LegacyCharacteristic(
            self.bus,
            self.legacy_service,
            1,
            LEGACY_COMMAND_UUID,
            ["write", "write-without-response"],
        )
        self.legacy_event = LegacyCharacteristic(
            self.bus,
            self.legacy_service,
            2,
            LEGACY_EVENT_UUID,
            ["notify"],
        )
        self.legacy_service.add_characteristic(self.legacy_status)
        self.legacy_service.add_characteristic(self.legacy_command)
        self.legacy_service.add_characteristic(self.legacy_event)
        self.application.add_service(self.legacy_service)
        self.advertisement = Advertisement(self.bus)

        adapter = self.bus.get_object(BLUEZ_SERVICE, self.adapter_path)
        self.gatt_manager = dbus.Interface(adapter, GATT_MANAGER)
        self.advertising_manager = dbus.Interface(adapter, ADVERTISING_MANAGER)

        self.bus.add_signal_receiver(
            self._name_owner_changed,
            dbus_interface="org.freedesktop.DBus",
            signal_name="NameOwnerChanged",
            arg0=BLUEZ_SERVICE,
        )

    def _find_adapter(self) -> str:
        manager = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE, "/"), DBUS_OBJECT_MANAGER
        )
        for path, interfaces in manager.GetManagedObjects().items():
            if GATT_MANAGER in interfaces and ADVERTISING_MANAGER in interfaces:
                return str(path)
        raise RuntimeError("no adapter with GATT and advertising support")

    def _name_owner_changed(self, name: str, old_owner: str, new_owner: str) -> None:
        if name == BLUEZ_SERVICE and old_owner and not new_owner:
            LOG.error("bluetoothd disappeared")
            self.fatal_error = True
            self.loop.quit()

    def _gatt_ok(self) -> None:
        self.gatt_registered = True
        LOG.info("GATT application registered")
        self._log_ready()
        self.advertising_manager.RegisterAdvertisement(
            self.advertisement.path,
            {},
            reply_handler=self._ad_ok,
            error_handler=self._ad_error,
        )

    def _gatt_error(self, error: Any) -> None:
        LOG.error("GATT application registration failed: %s", error)
        self.fatal_error = True
        self.loop.quit()

    def _ad_ok(self) -> None:
        self.ad_registered = True
        LOG.info("advertisement registered")
        self._log_ready()

    def _ad_error(self, error: Any) -> None:
        LOG.warning(
            "advertisement registration failed: %s; connect through the existing "
            "Roban-Bluetooth advertisement instead",
            error,
        )

    def _log_ready(self) -> None:
        if self.gatt_registered:
            LOG.info(
                "ready: name=%s echo_service=%s echo_characteristic=%s "
                "legacy_service=%s legacy_characteristics=%s,%s,%s advertising=%s",
                LOCAL_NAME,
                ECHO_SERVICE_UUID,
                ECHO_UUID,
                LEGACY_SERVICE_UUID,
                LEGACY_STATUS_UUID,
                LEGACY_COMMAND_UUID,
                LEGACY_EVENT_UUID,
                self.ad_registered,
            )

    def stop(self, signum: int | None = None, frame: Any = None) -> None:  # noqa: ARG002
        if signum is not None:
            LOG.info("received signal %d, stopping", signum)
        self.loop.quit()

    def run(self) -> int:
        LOG.info("using adapter %s", self.adapter_path)
        self.gatt_manager.RegisterApplication(
            dbus.ObjectPath(APP_PATH),
            {},
            reply_handler=self._gatt_ok,
            error_handler=self._gatt_error,
        )

        self.loop.run()
        self.loop.close()
        return 1 if self.fatal_error else 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        server = EchoGattServer()
        signal.signal(signal.SIGINT, server.stop)
        signal.signal(signal.SIGTERM, server.stop)
        return server.run()
    except Exception:
        LOG.exception("server failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
