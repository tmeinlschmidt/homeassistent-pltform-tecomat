"""DataUpdateCoordinator for Tecomat integration."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL
from .plccoms import PlcComSClient, PlcComSConnectionError

_LOGGER = logging.getLogger(__name__)


class TecoматDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching Tecomat data."""

    def __init__(
        self,
        hass: HomeAssistant,
        host: str,
        port: int,
        variables: list[str],
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance
            host: PLC hostname or IP
            port: PLC port
            variables: List of variable names to monitor
        """
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
            always_update=False,
        )
        self.host = host
        self.port = port
        self._variables = variables
        self._client = PlcComSClient(host, port, reconnect=True)
        self.plc_model: str | None = None
        self.plc_version: str | None = None
        self._monitoring_enabled = False

    @property
    def client(self) -> PlcComSClient:
        """Return the PlcComS client."""
        return self._client

    @property
    def monitored_variables(self) -> list[str]:
        """Return the list of monitored variables."""
        return self._variables.copy()

    async def _async_setup(self) -> None:
        """Set up the coordinator.

        This is called once during async_config_entry_first_refresh.
        """
        _LOGGER.debug("Setting up Tecomat coordinator for %s:%s", self.host, self.port)

        try:
            await self._client.connect()

            # Get PLC info
            try:
                self.plc_version = await self._client.get_info("version_plc")
            except Exception as err:
                _LOGGER.debug("Failed to get PLC version: %s", err)

            try:
                self.plc_model = await self._client.get_info("version")
            except Exception as err:
                _LOGGER.debug("Failed to get PLC model info: %s", err)

            # Enable monitoring for selected variables
            await self._enable_monitoring()

            # Register global callback for DIFF updates
            self._client.register_callback(self._on_variable_update)

        except PlcComSConnectionError as err:
            raise UpdateFailed(f"Failed to connect to PLC: {err}") from err

    async def _enable_monitoring(self) -> None:
        """Enable monitoring for all configured variables."""
        if self._monitoring_enabled:
            return

        for var_name in self._variables:
            try:
                await self._client.enable_monitoring(var_name)
                _LOGGER.debug("Enabled monitoring for %s", var_name)
            except Exception as err:
                _LOGGER.warning("Failed to enable monitoring for %s: %s", var_name, err)

        self._monitoring_enabled = True

    @callback
    def _on_variable_update(self, var_name: str, value: Any) -> None:
        """Handle variable update from PLC (DIFF response)."""
        if var_name in self._variables:
            _LOGGER.debug("Variable update: %s = %s", var_name, value)
            if self.data is None:
                self.data = {}
            self.data[var_name] = value
            self.async_set_updated_data(self.data)

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the Tecomat PLC."""
        if not self._client.is_connected:
            try:
                await self._client.connect()
                await self._enable_monitoring()
            except PlcComSConnectionError as err:
                raise UpdateFailed(f"Failed to reconnect: {err}") from err

        # Fetch current values for all monitored variables
        data: dict[str, Any] = {}

        for var_name in self._variables:
            try:
                value = await self._client.get_variable(var_name)
                data[var_name] = value
            except asyncio.TimeoutError:
                _LOGGER.warning("Timeout getting variable %s", var_name)
                if self.data and var_name in self.data:
                    data[var_name] = self.data[var_name]
            except Exception as err:
                _LOGGER.warning("Error getting variable %s: %s", var_name, err)
                if self.data and var_name in self.data:
                    data[var_name] = self.data[var_name]

        return data

    async def async_shutdown(self) -> None:
        """Shut down the coordinator and close connections."""
        await super().async_shutdown()
        await self._client.disconnect()

    async def async_set_variable(self, name: str, value: Any) -> None:
        """Set a variable value on the PLC."""
        await self._client.set_variable(name, value)
        await self.async_request_refresh()
