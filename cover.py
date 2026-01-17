"""Cover platform for Tecomat integration (blinds/jalousie)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .base import TecoматEntity
from .const import (
    CONF_COVERS,
    CONF_COVER_UP_SUFFIX,
    CONF_COVER_DOWN_SUFFIX,
    DEFAULT_COVER_UP_SUFFIX,
    DEFAULT_COVER_DOWN_SUFFIX,
)
from .coordinator import TecoматDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tecomat covers from a config entry."""
    coordinator: TecoматDataUpdateCoordinator = entry.runtime_data

    # Get configured cover bases and suffixes from options
    cover_bases = entry.options.get(CONF_COVERS, [])
    up_suffix = entry.options.get(CONF_COVER_UP_SUFFIX, DEFAULT_COVER_UP_SUFFIX)
    down_suffix = entry.options.get(CONF_COVER_DOWN_SUFFIX, DEFAULT_COVER_DOWN_SUFFIX)

    entities = [
        TecoматCover(coordinator, base, up_suffix, down_suffix)
        for base in cover_bases
    ]

    if entities:
        _LOGGER.info("Adding %d cover entities", len(entities))
        async_add_entities(entities)


class TecoматCover(TecoматEntity, CoverEntity):
    """Representation of a Tecomat cover (blinds/jalousie)."""

    _attr_device_class = CoverDeviceClass.BLIND
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )

    def __init__(
        self,
        coordinator: TecoматDataUpdateCoordinator,
        base_name: str,
        up_suffix: str,
        down_suffix: str,
    ) -> None:
        """Initialize the cover."""
        super().__init__(coordinator, base_name, "cover")

        self._up_var = f"{base_name}{up_suffix}"
        self._down_var = f"{base_name}{down_suffix}"
        self._attr_name = base_name

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        if self.coordinator.data is None:
            return None
        down_state = self.coordinator.data.get(self._down_var)
        up_state = self.coordinator.data.get(self._up_var)
        if not down_state and not up_state:
            return None
        return bool(down_state)

    @property
    def is_opening(self) -> bool:
        """Return if the cover is opening."""
        if self.coordinator.data is None:
            return False
        return bool(self.coordinator.data.get(self._up_var))

    @property
    def is_closing(self) -> bool:
        """Return if the cover is closing."""
        if self.coordinator.data is None:
            return False
        return bool(self.coordinator.data.get(self._down_var))

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover (move up)."""
        await self.coordinator.async_set_variable(self._down_var, False)
        await self.coordinator.async_set_variable(self._up_var, True)

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover (move down)."""
        await self.coordinator.async_set_variable(self._up_var, False)
        await self.coordinator.async_set_variable(self._down_var, True)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        await self.coordinator.async_set_variable(self._up_var, False)
        await self.coordinator.async_set_variable(self._down_var, False)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
