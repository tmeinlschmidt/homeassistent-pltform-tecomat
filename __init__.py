"""The Tecomat Foxtrot integration."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    DEFAULT_PORT,
    PLATFORMS,
    CONF_LIGHTS,
    CONF_COVERS,
    CONF_COVER_UP_SUFFIX,
    CONF_COVER_DOWN_SUFFIX,
    CONF_BINARY_SENSORS,
    CONF_SENSORS,
    CONF_SWITCHES,
    CONF_BUTTONS,
    DEFAULT_COVER_UP_SUFFIX,
    DEFAULT_COVER_DOWN_SUFFIX,
)
from .coordinator import TecoматDataUpdateCoordinator
from .plccoms import PlcComSConnectionError

if TYPE_CHECKING:
    from typing import TypeAlias

_LOGGER = logging.getLogger(__name__)

TecoматConfigEntry: TypeAlias = ConfigEntry[TecoматDataUpdateCoordinator]


def _collect_variables_from_options(options: dict) -> list[str]:
    """Collect all variable names from configuration options."""
    variables = set()

    # Add simple variable lists
    for key in (CONF_LIGHTS, CONF_BINARY_SENSORS, CONF_SENSORS, CONF_SWITCHES, CONF_BUTTONS):
        variables.update(options.get(key, []))

    # Add cover variables (need UP and DN suffixes)
    up_suffix = options.get(CONF_COVER_UP_SUFFIX, DEFAULT_COVER_UP_SUFFIX)
    down_suffix = options.get(CONF_COVER_DOWN_SUFFIX, DEFAULT_COVER_DOWN_SUFFIX)
    for cover_base in options.get(CONF_COVERS, []):
        variables.add(f"{cover_base}{up_suffix}")
        variables.add(f"{cover_base}{down_suffix}")

    return list(variables)


async def async_setup_entry(hass: HomeAssistant, entry: TecoматConfigEntry) -> bool:
    """Set up Tecomat from a config entry."""
    host = entry.data[CONF_HOST]
    port = entry.data.get(CONF_PORT, DEFAULT_PORT)

    # Collect variables to monitor from options
    variables = _collect_variables_from_options(entry.options)

    _LOGGER.debug(
        "Setting up Tecomat integration for %s:%s with %d variables",
        host,
        port,
        len(variables),
    )

    # Create the coordinator
    coordinator = TecoматDataUpdateCoordinator(hass, host, port, variables)

    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        raise
    except PlcComSConnectionError as err:
        raise ConfigEntryNotReady(f"Failed to connect to PLC: {err}") from err

    # Store coordinator in runtime_data
    entry.runtime_data = coordinator

    # Forward setup to all platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: TecoматConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Tecomat integration")

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        await entry.runtime_data.async_shutdown()

    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: TecoматConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.debug("Options updated, reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)


async def async_remove_entry(hass: HomeAssistant, entry: TecoматConfigEntry) -> None:
    """Handle removal of an entry."""
    _LOGGER.debug("Removing Tecomat integration")
