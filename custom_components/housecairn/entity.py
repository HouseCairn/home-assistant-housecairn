"""What the entities of a home share: their device."""

from __future__ import annotations

from homeassistant.const import CONF_URL
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import HouseCairnCoordinator


class HouseCairnEntity(CoordinatorEntity[HouseCairnCoordinator]):
    """An entity of a home: one device per home, unavailable while an update failed."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: HouseCairnCoordinator) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.home_id)},
            name=entry.title,
            manufacturer="Housecairn",
            model="Home",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=entry.data[CONF_URL],
        )
