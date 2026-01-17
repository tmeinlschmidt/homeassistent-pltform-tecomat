"""Sensor platform for Tecomat integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import TecoматEntity
from .const import CONF_SENSORS
from .coordinator import TecoматDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tecomat sensors from a config entry."""
    coordinator: TecoматDataUpdateCoordinator = entry.runtime_data

    # Get configured sensor variables from options
    sensor_vars = entry.options.get(CONF_SENSORS, [])

    entities = [TecoматSensor(coordinator, var_name) for var_name in sensor_vars]

    if entities:
        _LOGGER.info("Adding %d sensor entities", len(entities))
        async_add_entities(entities)


class TecoматSensor(TecoматEntity, SensorEntity):
    """Representation of a Tecomat sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: TecoматDataUpdateCoordinator,
        variable_name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, variable_name, "sensor")
        self._attr_name = variable_name

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self._variable_name)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
