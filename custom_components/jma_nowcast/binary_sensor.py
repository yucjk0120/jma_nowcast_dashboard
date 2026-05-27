"""Binary sensor platform for JMA Nowcast."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import JmaNowcastCoordinator
from .entity import JmaNowcastEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: JmaNowcastCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([JmaNowcastRainSensor(coordinator, entry)])


class JmaNowcastRainSensor(JmaNowcastEntity, BinarySensorEntity):
    """現在の降水有無を示すバイナリセンサー。"""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_translation_key = "rain_detected"

    def __init__(self, coordinator: JmaNowcastCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_rain_detected"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("any_rain", False)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        data = self.coordinator.data
        return {
            "first_rain_in_minutes": data.get("first_rain_in_minutes"),
            "checked_at": data.get("checked_at"),
            "location": data.get("location"),
        }
