"""Cover platform for Tecomat integration (blinds/jalousie)."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
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
    CONF_COVER_NAME,
    CONF_COVER_UP_VAR,
    CONF_COVER_DOWN_VAR,
    CONF_COVER_POSITION_VAR,
    CONF_COVER_TILT_UP_VAR,
    CONF_COVER_TILT_DOWN_VAR,
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

    # Get configured covers from options (list of cover config dicts)
    cover_configs = entry.options.get(CONF_COVERS, [])

    entities = []
    for cover_config in cover_configs:
        if isinstance(cover_config, dict):
            # New format: dict with individual variable assignments
            entities.append(TecoматCover(coordinator, cover_config))
        elif isinstance(cover_config, str):
            # Legacy format: base name string (for backwards compatibility)
            # This shouldn't happen with new installations but handle gracefully
            _LOGGER.warning(
                "Legacy cover config format detected for '%s'. Please reconfigure covers.",
                cover_config,
            )

    if entities:
        _LOGGER.info("Adding %d cover entities", len(entities))
        async_add_entities(entities)


class TecoматCover(TecoматEntity, CoverEntity):
    """Representation of a Tecomat cover (blinds/jalousie)."""

    _attr_device_class = CoverDeviceClass.BLIND

    def __init__(
        self,
        coordinator: TecoматDataUpdateCoordinator,
        cover_config: dict[str, str],
    ) -> None:
        """Initialize the cover."""
        name = cover_config.get(CONF_COVER_NAME, "Unknown Cover")
        super().__init__(coordinator, name, "cover")

        self._up_var = cover_config.get(CONF_COVER_UP_VAR, "")
        self._down_var = cover_config.get(CONF_COVER_DOWN_VAR, "")
        self._position_var = cover_config.get(CONF_COVER_POSITION_VAR)
        self._tilt_up_var = cover_config.get(CONF_COVER_TILT_UP_VAR)
        self._tilt_down_var = cover_config.get(CONF_COVER_TILT_DOWN_VAR)

        self._attr_name = name
        self._position_task: asyncio.Task | None = None
        self._target_position: int | None = None

        # Build supported features based on configured variables
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP

        if self._tilt_up_var and self._tilt_down_var:
            features |= CoverEntityFeature.OPEN_TILT | CoverEntityFeature.CLOSE_TILT | CoverEntityFeature.STOP_TILT

        if self._position_var:
            features |= CoverEntityFeature.SET_POSITION

        self._attr_supported_features = features

    @property
    def current_cover_position(self) -> int | None:
        """Return current position of cover (0=closed, 100=open)."""
        if not self._position_var or self.coordinator.data is None:
            return None
        position = self.coordinator.data.get(self._position_var)
        if position is None:
            return None
        # POSIT is typically 0-100 where 0=open, 100=closed
        # HA expects 0=closed, 100=open, so we invert
        try:
            return 100 - int(position)
        except (ValueError, TypeError):
            return None

    @property
    def is_closed(self) -> bool | None:
        """Return if the cover is closed."""
        position = self.current_cover_position
        if position is not None:
            return position == 0

        # Fall back to checking down/up state
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
        """Stop the cover by sending the opposite direction command."""
        # To stop, we send the opposite direction command briefly
        if self.is_opening:
            # Currently opening - send down to stop
            await self.coordinator.async_set_variable(self._down_var, True)
        elif self.is_closing:
            # Currently closing - send up to stop
            await self.coordinator.async_set_variable(self._up_var, True)
        else:
            # Not moving - just ensure both are off
            await self.coordinator.async_set_variable(self._up_var, False)
            await self.coordinator.async_set_variable(self._down_var, False)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Move the cover to a specific position and stop when reached."""
        position = kwargs.get(ATTR_POSITION)
        if position is None:
            return

        # Cancel any existing position task
        if self._position_task and not self._position_task.done():
            self._position_task.cancel()
            try:
                await self._position_task
            except asyncio.CancelledError:
                pass

        current = self.current_cover_position
        if current is None:
            return

        if position == current:
            return  # Already at target

        self._target_position = position
        opening = position > current

        # Start movement
        if opening:
            await self.async_open_cover()
        else:
            await self.async_close_cover()

        # Start monitoring task
        self._position_task = asyncio.create_task(
            self._monitor_position(position, opening)
        )

    async def _monitor_position(self, target: int, opening: bool) -> None:
        """Monitor position and stop when target is reached."""
        tolerance = 2  # Stop within 2% of target
        timeout = 120  # Max 2 minutes
        poll_interval = 0.5  # Check every 500ms

        try:
            elapsed = 0.0
            while elapsed < timeout:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                # Refresh data from coordinator
                await self.coordinator.async_request_refresh()

                current = self.current_cover_position
                if current is None:
                    continue

                # Check if we've reached or passed target
                if opening:
                    # Opening: stop when current >= target
                    if current >= target - tolerance:
                        _LOGGER.debug(
                            "Cover %s reached target %d (current: %d), stopping",
                            self._attr_name, target, current
                        )
                        await self._send_stop_signal(opening)
                        break
                else:
                    # Closing: stop when current <= target
                    if current <= target + tolerance:
                        _LOGGER.debug(
                            "Cover %s reached target %d (current: %d), stopping",
                            self._attr_name, target, current
                        )
                        await self._send_stop_signal(opening)
                        break

                # Check if movement stopped (no longer opening/closing)
                if not self.is_opening and not self.is_closing:
                    _LOGGER.debug("Cover %s stopped moving", self._attr_name)
                    break

        except asyncio.CancelledError:
            _LOGGER.debug("Position monitoring cancelled for %s", self._attr_name)
            raise
        finally:
            self._target_position = None

    async def _send_stop_signal(self, was_opening: bool) -> None:
        """Send stop signal by pulsing the opposite direction."""
        if was_opening:
            # Was opening, send down to stop
            await self.coordinator.async_set_variable(self._down_var, True)
            await asyncio.sleep(0.1)
            await self.coordinator.async_set_variable(self._down_var, False)
        else:
            # Was closing, send up to stop
            await self.coordinator.async_set_variable(self._up_var, True)
            await asyncio.sleep(0.1)
            await self.coordinator.async_set_variable(self._up_var, False)

    async def async_open_cover_tilt(self, **kwargs: Any) -> None:
        """Open the cover tilt (rotate slats up)."""
        if not self._tilt_up_var or not self._tilt_down_var:
            return
        await self.coordinator.async_set_variable(self._tilt_down_var, False)
        await self.coordinator.async_set_variable(self._tilt_up_var, True)

    async def async_close_cover_tilt(self, **kwargs: Any) -> None:
        """Close the cover tilt (rotate slats down)."""
        if not self._tilt_up_var or not self._tilt_down_var:
            return
        await self.coordinator.async_set_variable(self._tilt_up_var, False)
        await self.coordinator.async_set_variable(self._tilt_down_var, True)

    async def async_stop_cover_tilt(self, **kwargs: Any) -> None:
        """Stop the cover tilt."""
        if not self._tilt_up_var or not self._tilt_down_var:
            return
        await self.coordinator.async_set_variable(self._tilt_up_var, False)
        await self.coordinator.async_set_variable(self._tilt_down_var, False)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
