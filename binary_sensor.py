"""Binary sensor platform for Tecomat integration."""
from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import TecoматEntity
from .const import CONF_BINARY_SENSORS
from .coordinator import TecoматDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tecomat binary sensors from a config entry."""
    coordinator: TecoматDataUpdateCoordinator = entry.runtime_data

    # Get configured binary sensor variables from options
    sensor_vars = entry.options.get(CONF_BINARY_SENSORS, [])

    entities = [TecoматBinarySensor(coordinator, var_name) for var_name in sensor_vars]

    if entities:
        _LOGGER.info("Adding %d binary sensor entities", len(entities))
        async_add_entities(entities)


class TecoматBinarySensor(TecoматEntity, BinarySensorEntity):
    """Representation of a Tecomat binary sensor."""

    def __init__(
        self,
        coordinator: TecoматDataUpdateCoordinator,
        variable_name: str,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, variable_name, "binary_sensor")
        self._attr_name = variable_name

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        if self.coordinator.data is None:
            return None
        value = self.coordinator.data.get(self._variable_name)
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.lower() in ("true", "1", "on")
        return bool(value)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
