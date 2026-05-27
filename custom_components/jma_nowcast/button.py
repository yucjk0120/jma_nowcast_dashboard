"""Button platform for JMA Nowcast."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
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
    async_add_entities([JmaNowcastRefreshButton(coordinator, entry)])


class JmaNowcastRefreshButton(JmaNowcastEntity, ButtonEntity):
    """手動で今すぐ降水確認をトリガーするボタン。"""

    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: JmaNowcastCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_refresh"

    async def async_press(self) -> None:
        """ボタンが押されたらコーディネーターを即時更新。"""
        await self.coordinator.async_request_refresh()
