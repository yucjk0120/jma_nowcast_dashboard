"""Sensor platform for JMA Nowcast."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ALL_FORECAST_MINUTES, CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES, DOMAIN
from .coordinator import JmaNowcastCoordinator
from .entity import JmaNowcastEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: JmaNowcastCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        JmaNowcastFirstRainSensor(coordinator, entry),
        JmaNowcastSummarySensor(coordinator, entry),
    ]
    # 全分後センサーを生成（設定外は unavailable になる）
    for mins in ALL_FORECAST_MINUTES:
        entities.append(JmaNowcastForecastSensor(coordinator, entry, mins))

    async_add_entities(entities)


class JmaNowcastFirstRainSensor(JmaNowcastEntity, SensorEntity):
    """最初に雨が来るまでの分数センサー。"""

    _attr_translation_key = "first_rain_minutes"
    _attr_native_unit_of_measurement = "分"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:clock-alert-outline"

    def __init__(self, coordinator: JmaNowcastCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_first_rain_minutes"

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("first_rain_in_minutes")


class JmaNowcastSummarySensor(JmaNowcastEntity, SensorEntity):
    """全予報をまとめたサマリーセンサー。"""

    _attr_translation_key = "summary"
    _attr_icon = "mdi:weather-cloudy-clock"

    def __init__(self, coordinator: JmaNowcastCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_summary"

    @property
    def native_value(self) -> str:
        if not self.coordinator.data:
            return "不明"
        fc = self.coordinator.data.get("forecasts", {})
        if not fc:
            return "データなし"
        parts = []
        for mins, info in sorted(fc.items()):
            if info.get("rain"):
                parts.append(f"{mins}分後 ☔{info['mm']}mm")
            else:
                parts.append(f"{mins}分後 ☀")
        return " / ".join(parts)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        return {
            "forecasts": self.coordinator.data.get("forecasts", {}),
            "checked_at": self.coordinator.data.get("checked_at"),
        }


class JmaNowcastForecastSensor(JmaNowcastEntity, SensorEntity):
    """各時間帯（10/20/30/60分後）の予報センサー。"""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "mm/h"

    def __init__(
        self,
        coordinator: JmaNowcastCoordinator,
        entry: ConfigEntry,
        minutes: int,
    ) -> None:
        super().__init__(coordinator, entry)
        self._minutes = minutes
        self._attr_unique_id = f"{entry.entry_id}_forecast_{minutes}min"
        self._attr_translation_key = f"forecast_{minutes}min"
        self._attr_icon = "mdi:weather-rainy" if minutes <= 20 else "mdi:weather-cloudy"

    @property
    def available(self) -> bool:
        """設定で有効な分後のみ available にする。"""
        if not self.coordinator.data:
            return False
        configured = self.coordinator.forecast_minutes
        return self._minutes in configured

    @property
    def native_value(self) -> float | None:
        if not self.coordinator.data:
            return None
        fc = self.coordinator.data.get("forecasts", {})
        info = fc.get(self._minutes)
        if info is None:
            return None
        return info.get("mm", 0.0)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        fc = self.coordinator.data.get("forecasts", {})
        info = fc.get(self._minutes, {})
        return {
            "rain":          info.get("rain", False),
            "forecast_time": info.get("forecast_time"),
        }
