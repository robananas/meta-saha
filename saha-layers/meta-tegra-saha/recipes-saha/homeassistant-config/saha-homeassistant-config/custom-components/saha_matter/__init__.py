"""Create the local Matter config entry on first boot."""

from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

DOMAIN = "saha_matter"
DEFAULT_MATTER_SERVER_URL = "ws://127.0.0.1:5580/ws"
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

    hass.bus.async_listen_once("homeassistant_started", ensure_matter_entry)
    return True
