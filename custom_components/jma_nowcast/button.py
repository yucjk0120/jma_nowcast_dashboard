"""Button platform for JMA Nowcast."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
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
    entities: list[ButtonEntity] = [JmaNowcastRefreshButton(coordinator, entry)]
    for minutes in (10, 20, 30, 60):
        entities.append(JmaNowcastTestAlertButton(coordinator, entry, minutes))
    async_add_entities(entities)


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


class JmaNowcastTestAlertButton(JmaNowcastEntity, ButtonEntity):
    """アラート音声のテスト再生ボタン (バケット別)。

    設定 UI (OptionsFlow の「アラート音声設定」) で選んだ TTS entity と
    media_player を使い、そのバケットのメッセージテンプレートを実際に
    再生する。バケットが無効化されている場合は既定文言で再生される
    ため、設定確認や到達確認に使える。

    実運用では邪魔にならないよう EntityCategory.CONFIG に分類する
    (通常の Controls セクションには表示されず、Configuration に入る)。
    """

    _attr_icon = "mdi:volume-high"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        coordinator: JmaNowcastCoordinator,
        entry: ConfigEntry,
        minutes: int,
    ) -> None:
        super().__init__(coordinator, entry)
        self._minutes = minutes
        self._attr_translation_key = f"test_alert_{minutes}min"
        self._attr_unique_id = f"{entry.entry_id}_test_alert_{minutes}min"

    async def async_press(self) -> None:
        await self.coordinator.async_play_alert(self._minutes, is_test=True)
