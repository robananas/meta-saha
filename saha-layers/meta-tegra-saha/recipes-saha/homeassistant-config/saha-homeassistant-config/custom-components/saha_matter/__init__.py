"""Create the local Matter config entry on first boot."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

DOMAIN = "saha_matter"
DEFAULT_MATTER_SERVER_URL = "ws://127.0.0.1:5580/ws"
MATTER_WIFI_CREDENTIALS_PATH = Path("/run/saha/matter-wifi.json")
CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {vol.Optional(CONF_URL, default=DEFAULT_MATTER_SERVER_URL): str}
        )
    },
    extra=vol.ALLOW_EXTRA,
)
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Schedule Matter setup after Home Assistant has started."""
    server_url = config[DOMAIN][CONF_URL]

    async def ensure_matter_entry(_: object) -> None:
        if hass.config_entries.async_entries("matter"):
            return
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
            _LOGGER.exception(
                "Unable to bootstrap Matter integration with %s", server_url
            )
            return

        if result.get("type") == "create_entry":
            _LOGGER.info("Matter integration configured with %s", server_url)
        else:
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
                _LOGGER.warning("Matter entry is not loaded; WiFi credentials not synchronized")
                return False
            matter_client = matter_entries[0].runtime_data.adapter.matter_client
            await matter_client.set_wifi_credentials(ssid=ssid, credentials=password)
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
