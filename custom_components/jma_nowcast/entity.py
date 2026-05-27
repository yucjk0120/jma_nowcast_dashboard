"""Base entity for JMA Nowcast."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import JmaNowcastCoordinator


class JmaNowcastEntity(CoordinatorEntity[JmaNowcastCoordinator]):
    """JMA Nowcast エンティティの基底クラス。"""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: JmaNowcastCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="JMA Nowcast",
            manufacturer="気象庁",
            model="高解像度降水ナウキャスト",
            configuration_url="https://www.jma.go.jp/bosai/nowc/",
        )
