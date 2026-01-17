"""Button platform for Tecomat integration (momentary triggers)."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import TecoматEntity
from .const import CONF_BUTTONS
from .coordinator import TecoматDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tecomat buttons from a config entry."""
    coordinator: TecoматDataUpdateCoordinator = entry.runtime_data

    # Get configured button variables from options
    button_vars = entry.options.get(CONF_BUTTONS, [])

    entities = [TecoматButton(coordinator, var_name) for var_name in button_vars]

    if entities:
        _LOGGER.info("Adding %d button entities", len(entities))
        async_add_entities(entities)


class TecoматButton(TecoматEntity, ButtonEntity):
    """Representation of a Tecomat button (momentary trigger)."""

    def __init__(
        self,
        coordinator: TecoматDataUpdateCoordinator,
        variable_name: str,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, variable_name, "button")
        self._attr_name = variable_name

    async def async_press(self) -> None:
        """Handle the button press (set variable to True)."""
        await self.coordinator.async_set_variable(self._variable_name, True)
