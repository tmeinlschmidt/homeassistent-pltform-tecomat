"""Base entity for Tecomat integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TecoматDataUpdateCoordinator


class TecoматEntity(CoordinatorEntity[TecoматDataUpdateCoordinator]):
    """Base class for Tecomat entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TecoматDataUpdateCoordinator,
        variable_name: str,
        entity_type: str,
    ) -> None:
        """Initialize the entity.

        Args:
            coordinator: Data update coordinator
            variable_name: PLC variable name
            entity_type: Entity type prefix for unique ID
        """
        super().__init__(coordinator)
        self._variable_name = variable_name
        self._attr_unique_id = f"{coordinator.host}_{entity_type}_{variable_name}"
        self._attr_translation_key = variable_name.lower().replace(".", "_")

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.host)},
            name=f"Tecomat Foxtrot ({self.coordinator.host})",
            manufacturer="Teco a.s.",
            model=self.coordinator.plc_model or "Foxtrot",
            sw_version=self.coordinator.plc_version,
            configuration_url=f"http://{self.coordinator.host}",
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self.coordinator.client.is_connected
