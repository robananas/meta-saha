import logging

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumEntityFeature,
    VacuumActivity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import MideaCoordinator
from .entity import MideaBaseEntity, iter_midea_device_configs

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    entities = []

    for coordinator, device_id, device_type, sn, sn8, device_name, model, device_mapping in iter_midea_device_configs(
        hass, entry
    ):
        entities_config = device_mapping.get("entities", {})
        vacuum_config = entities_config.get(Platform.VACUUM, {})

        if vacuum_config:
            for vacuum_id, config in vacuum_config.items():
                entities.append(
                    MideaVacuumEntity(
                        coordinator, device_id, device_type, sn, sn8, device_name,
                        vacuum_id, config, model
                    )
                )

    async_add_entities(entities)


class MideaVacuumEntity(MideaBaseEntity, StateVacuumEntity):
    def __init__(
        self,
        coordinator: MideaCoordinator,
        device_id: int,
        device_type: str,
        sn: str,
        sn8: str,
        device_name: str,
        vacuum_id: str,
        config: dict,
        model: str = None,
    ):
        super().__init__(
            coordinator, device_id, device_type, sn, sn8, device_name, vacuum_id, model,
            platform_name="vacuum", config=config
        )
        self._vacuum_id = vacuum_id
        self._key_control = self._config.get("control")
        self._key_fan_speeds = self._config.get("fan_speeds", {})
        self._control_actions = self._config.get("control_actions", {})

    @property
    def supported_features(self):
        features = VacuumEntityFeature.STATE
        features |= VacuumEntityFeature.STOP
        features |= VacuumEntityFeature.PAUSE
        features |= VacuumEntityFeature.START
        features |= VacuumEntityFeature.RETURN_HOME
        features |= VacuumEntityFeature.FAN_SPEED
        return features

    @property
    def status(self):
        if self._key_control:
            return self._get_nested_value(self._key_control)
        return None

    @property
    def activity(self):
        status = self.status
        if not status:
            return None

        status_mapping = {
            "work": VacuumActivity.CLEANING,
            "auto_clean": VacuumActivity.CLEANING,
            "charging_on_dock": VacuumActivity.DOCKED,
            "on_base": VacuumActivity.DOCKED,
            "charge_finish": VacuumActivity.DOCKED,
            "stop": VacuumActivity.IDLE,
            "sleep": VacuumActivity.IDLE,
            "clean_pause": VacuumActivity.PAUSED,
            "charge_pause": VacuumActivity.PAUSED,
            "charging": VacuumActivity.RETURNING,
            "error": VacuumActivity.ERROR,
        }

        return status_mapping.get(status, status)

    @property
    def fan_speed(self):
        return self._dict_get_selected(self._key_fan_speeds)

    @property
    def fan_speed_list(self):
        return [k for k in self._key_fan_speeds.keys() if k != "status_key"]

    async def async_start(self):
        if self._key_control:
            control_value = self._control_actions.get("start", "work")
            await self.coordinator.async_set_control(self._key_control, control_value)

    async def async_stop(self):
        if self._key_control:
            control_value = self._control_actions.get("stop", "stop")
            await self.coordinator.async_set_control(self._key_control, control_value)

    async def async_pause(self):
        if self._key_control:
            control_value = self._control_actions.get("pause", "pause")
            await self.coordinator.async_set_control(self._key_control, control_value)

    async def async_return_to_base(self):
        if self._key_control:
            control_value = self._control_actions.get("return", "charge")
            await self.coordinator.async_set_control(self._key_control, control_value)

    async def async_set_fan_speed(self, fan_speed: str):
        new_status = self._key_fan_speeds.get(fan_speed)
        if new_status is not None:
            status_key = self._key_fan_speeds.get("status_key")
            if status_key:
                value = self._extract_deepest_value(new_status)
                if value is not None:
                    await self.coordinator.async_set_controls({
                        status_key: value,
                        **new_status
                    })
                    return
            await self.coordinator.async_set_controls(new_status)
