"""Support for Gree cloud tower fans."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.percentage import ordered_list_item_to_percentage, percentage_to_ordered_list_item

from .const import (
    DISPATCH_DEVICE_DISCOVERED,
    TOWER_FAN_SPEED_COUNT,
    is_tower_fan_hid,
)
from .coordinator import CloudDeviceDataUpdateCoordinator, GreeCloudConfigEntry
from .entity import GreeCloudEntity
from .greeclimate_cloud.device import HorizontalSwing

_LOGGER = logging.getLogger(__name__)
_SPEEDS = list(range(1, TOWER_FAN_SPEED_COUNT + 1))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeCloudConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up supported Gree tower fans."""

    @callback
    def init_device(coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        if is_tower_fan_hid(coordinator.device.hid):
            async_add_entities([GreeCloudTowerFanEntity(coordinator)])

    for coordinator in entry.runtime_data.coordinators:
        init_device(coordinator)

    entry.async_on_unload(
        async_dispatcher_connect(hass, DISPATCH_DEVICE_DISCOVERED, init_device)
    )


class GreeCloudTowerFanEntity(GreeCloudEntity, FanEntity):
    """Representation of a Gree U-T710 tower fan."""

    _attr_name = None
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.OSCILLATE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    _attr_speed_count = TOWER_FAN_SPEED_COUNT

    def __init__(self, coordinator: CloudDeviceDataUpdateCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device.device_info.mac}_fan"

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.device.power

    @property
    def percentage(self) -> int | None:
        speed = self.coordinator.device.fan_speed
        if speed is None:
            return None
        if int(speed) <= 0:
            return 0
        return ordered_list_item_to_percentage(_SPEEDS, int(speed))

    @property
    def oscillating(self) -> bool | None:
        swing = self.coordinator.device.horizontal_swing
        if swing is None:
            return None
        return swing == HorizontalSwing.FullSwing

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "gree_hid": self.coordinator.device.hid,
            "gree_raw_properties": dict(self.coordinator.device.raw_properties),
        }

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.coordinator.device.power = True
        if percentage is not None:
            self.coordinator.device.fan_speed = percentage_to_ordered_list_item(
                _SPEEDS, percentage
            )
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.coordinator.device.power = False
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    async def async_set_percentage(self, percentage: int) -> None:
        if percentage <= 0:
            await self.async_turn_off()
            return
        self.coordinator.device.fan_speed = percentage_to_ordered_list_item(
            _SPEEDS, percentage
        )
        await self.coordinator.push_state_update()
        self.async_write_ha_state()

    async def async_oscillate(self, oscillating: bool) -> None:
        self.coordinator.device.horizontal_swing = (
            HorizontalSwing.FullSwing if oscillating else HorizontalSwing.Center
        )
        await self.coordinator.push_state_update()
        self.async_write_ha_state()
