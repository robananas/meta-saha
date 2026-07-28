"""Create the local Matter config entry on first boot."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import socket
import time
from pathlib import Path

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

DOMAIN = "saha_matter"
DEFAULT_MATTER_SERVER_URL = "ws://127.0.0.1:5580/ws"
MATTER_WIFI_CREDENTIALS_PATH = Path("/run/saha/matter-wifi.json")
ADVERTISEMENT_CONTROL_PATH = Path("/run/saha/ble-advertisement-control.json")
ADVERTISEMENT_STATUS_PATH = Path("/run/saha/ble-advertisement-status.json")
BOARD_STATUS_SOCKET = "/run/saha/board-status/events.sock"
COMMISSION_COMMAND = "saha_matter/commission"
ADVERTISEMENT_LEASE_SECONDS = 90
ADVERTISEMENT_TRANSITION_TIMEOUT = 5.0
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {vol.Optional(CONF_URL, default=DEFAULT_MATTER_SERVER_URL): str}
        )
    },
    extra=vol.ALLOW_EXTRA,
)
_LOGGER = logging.getLogger(__name__)


def emit_board_status(state: str, *, level: str = "info", error_code: str | None = None) -> None:
    payload = {"component": "ha_matter", "state": state, "level": level, "errorCode": error_code}
    client = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        client.sendto(json.dumps(payload, separators=(",", ":")).encode("utf-8"), BOARD_STATUS_SOCKET)
    except OSError:
        pass
    finally:
        client.close()


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Schedule Matter setup after Home Assistant has started."""
    server_url = config[DOMAIN][CONF_URL]
    commission_lock = asyncio.Lock()

    async def write_advertisement_control(action: str, token: str) -> None:
        payload = {"action": action, "token": token}
        if action == "pause":
            payload["lease_seconds"] = ADVERTISEMENT_LEASE_SECONDS

        def write() -> None:
            temporary = ADVERTISEMENT_CONTROL_PATH.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
            os.replace(temporary, ADVERTISEMENT_CONTROL_PATH)

        await hass.async_add_executor_job(write)

    async def wait_for_advertising(expected: bool) -> None:
        deadline = time.monotonic() + ADVERTISEMENT_TRANSITION_TIMEOUT
        while time.monotonic() < deadline:
            try:
                status = await hass.async_add_executor_job(
                    lambda: json.loads(ADVERTISEMENT_STATUS_PATH.read_text(encoding="utf-8"))
                )
                if status.get("advertising") is expected:
                    return
            except (OSError, ValueError, json.JSONDecodeError):
                pass
            await asyncio.sleep(0.1)
        raise RuntimeError("BLE advertisement transition timed out")

    @websocket_api.websocket_command(
        {
            "type": COMMISSION_COMMAND,
            "code": str,
            vol.Optional("network_only", default=False): bool,
        }
    )
    @websocket_api.require_admin
    @websocket_api.async_response
    async def commission_matter_device(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict,
    ) -> None:
        """Commission while leasing the shared adapter exclusively to Matter BLE."""
        if commission_lock.locked():
            connection.send_error(msg["id"], "commission_in_progress", "Matter commissioning is already in progress")
            return
        matter_entries = hass.config_entries.async_loaded_entries("matter")
        if not matter_entries:
            connection.send_error(msg["id"], "matter_not_ready", "Matter integration is not loaded")
            return

        async with commission_lock:
            token = secrets.token_urlsafe(24)
            paused = False
            started_at = time.monotonic()
            try:
                if not await sync_wifi_credentials():
                    connection.send_error(
                        msg["id"],
                        "matter_wifi_not_ready",
                        "Matter WiFi credentials are not synchronized",
                    )
                    return
                matter_client = matter_entries[0].runtime_data.adapter.matter_client
                if not msg["network_only"]:
                    # A/B HCI traces showed the local peripheral advertisement can abort the
                    # first Matter central connection; only the advertisement is paused here,
                    # leaving the GATT application and Bluetooth service registered.
                    await write_advertisement_control("pause", token)
                    await wait_for_advertising(False)
                    paused = True
                _LOGGER.info("Matter commissioning prerequisites ready in %.2fs", time.monotonic() - started_at)
                node = await matter_client.commission_with_code(
                    code=msg["code"],
                    network_only=msg["network_only"],
                )
                elapsed = time.monotonic() - started_at
                _LOGGER.info("Matter commissioning completed in %.2fs for node %s", elapsed, node.node_id)
                connection.send_result(msg["id"], {"node_id": node.node_id, "elapsed_seconds": round(elapsed, 2)})
            except Exception as err:  # noqa: BLE001
                _LOGGER.exception("Unable to commission Matter device with BLE coordination")
                connection.send_error(msg["id"], "commission_failed", str(err))
            finally:
                if paused:
                    try:
                        await write_advertisement_control("resume", token)
                        await wait_for_advertising(True)
                    except Exception:  # noqa: BLE001
                        # The host lease independently restores advertising if this cleanup is interrupted.
                        _LOGGER.exception("Unable to immediately resume Roban BLE advertising")

    websocket_api.async_register_command(hass, commission_matter_device)

    async def ensure_matter_entry(_: object) -> None:
        if hass.config_entries.async_entries("matter"):
            emit_board_status("connected")
            return
        emit_board_status("configuring")
        if hass.config_entries.flow.async_progress_by_handler("matter"):
            return

        try:
            result = await hass.config_entries.flow.async_init(
                "matter", context={"source": SOURCE_USER}
            )
            if result.get("type") == "form" and result.get("step_id") == "manual":
                result = await hass.config_entries.flow.async_configure(
                    result["flow_id"], {CONF_URL: server_url}
                )
        except Exception:  # noqa: BLE001
            emit_board_status("error", level="error", error_code="CONFIGURATION_FAILED")
            _LOGGER.exception(
                "Unable to bootstrap Matter integration with %s", server_url
            )
            return

        if result.get("type") == "create_entry":
            emit_board_status("connected")
            _LOGGER.info("Matter integration configured with %s", server_url)
        else:
            emit_board_status("error", level="error", error_code="ENTRY_NOT_CREATED")
            _LOGGER.warning("Matter bootstrap did not create an entry: %s", result)

    async def sync_wifi_credentials() -> bool:
        if not MATTER_WIFI_CREDENTIALS_PATH.is_file():
            _LOGGER.warning("Board Matter WiFi credentials are not available")
            return False
        try:
            credentials = await hass.async_add_executor_job(
                lambda: json.loads(MATTER_WIFI_CREDENTIALS_PATH.read_text(encoding="utf-8"))
            )
            ssid = credentials.get("ssid")
            password = credentials.get("password", "")
            if not isinstance(ssid, str) or not ssid:
                raise ValueError("WiFi SSID is missing")

            matter_entries = hass.config_entries.async_loaded_entries("matter")
            if not matter_entries:
                emit_board_status("waiting_server", level="warning", error_code="ENTRY_NOT_LOADED")
                _LOGGER.warning("Matter entry is not loaded; WiFi credentials not synchronized")
                return False
            matter_client = matter_entries[0].runtime_data.adapter.matter_client
            await matter_client.set_wifi_credentials(ssid=ssid, credentials=password)
            emit_board_status("connected")
            _LOGGER.debug("Matter WiFi credentials synchronized for SSID %s", ssid)
            return True
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unable to synchronize board WiFi credentials to Matter Server")
            return False

    async def keep_wifi_credentials_synchronized() -> None:
        failures = 0
        while True:
            if await sync_wifi_credentials():
                failures = 0
            else:
                failures += 1
                if failures == 12:
                    _LOGGER.error(
                        "Matter WiFi credentials have not synchronized for 60 seconds; continuing to retry"
                    )
            await asyncio.sleep(5)

    async def initialize(_: object) -> None:
        await ensure_matter_entry(_)
        hass.async_create_task(
            keep_wifi_credentials_synchronized(),
            "keep Matter WiFi credentials synchronized",
        )

    hass.bus.async_listen_once("homeassistant_started", initialize)
    return True
