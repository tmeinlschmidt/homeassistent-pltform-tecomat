"""Light platform for Tecomat integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import TecoматEntity
from .const import CONF_LIGHTS
from .coordinator import TecoматDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tecomat lights from a config entry."""
    coordinator: TecoматDataUpdateCoordinator = entry.runtime_data

    # Get configured light variables from options
    light_vars = entry.options.get(CONF_LIGHTS, [])

    entities = [TecoматLight(coordinator, var_name) for var_name in light_vars]

    if entities:
        _LOGGER.info("Adding %d light entities", len(entities))
        async_add_entities(entities)


class TecoматLight(TecoматEntity, LightEntity):
    """Representation of a Tecomat light (relay output)."""

    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(
        self,
        coordinator: TecoматDataUpdateCoordinator,
        variable_name: str,
    ) -> None:
        """Initialize the light."""
        super().__init__(coordinator, variable_name, "light")
        # Use variable name as entity name (user can customize in HA)
        self._attr_name = variable_name

    @property
    def is_on(self) -> bool | None:
        """Return true if the light is on."""
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

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        await self.coordinator.async_set_variable(self._variable_name, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self.coordinator.async_set_variable(self._variable_name, False)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
