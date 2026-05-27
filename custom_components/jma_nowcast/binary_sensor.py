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
    async_add_entities([
        JmaNowcastRainDetectedSensor(coordinator, entry),
        JmaNowcastRainObservedSensor(coordinator, entry),
    ])


class JmaNowcastRainDetectedSensor(JmaNowcastEntity, BinarySensorEntity):
    """ステートマシン管理の発報センサー。

    v1.1 以前はここに「予測の生値」を出していたが、v1.2 以降は
    クールダウンを含む発報判定を返す。READY/POST_RAIN_WAIT では OFF、
    ALERTED/RAINING では ON。
    """

    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_translation_key = "rain_detected"

    def __init__(self, coordinator: JmaNowcastCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_rain_detected"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("alert", False)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        data = self.coordinator.data
        return {
            # ── ステートマシン関連 ──
            "alert_state":            data.get("alert_state"),
            "alert_state_since":      data.get("alert_state_since"),
            "last_alert_at":          data.get("last_alert_at"),
            "last_rain_observed_at":  data.get("last_rain_observed_at"),
            "rain_ended_at":          data.get("rain_ended_at"),
            # ── 予測 / 実況 ──
            "forecast_any_rain":      data.get("any_rain"),
            "first_rain_in_minutes":  data.get("first_rain_in_minutes"),
            "rain_observed":          data.get("rain_observed"),
            "observed_mm":            data.get("observed_mm"),
            "observed_coverage":      data.get("observed_coverage"),
            "observed_at":            data.get("observed_at"),
            # ── メタ ──
            "checked_at":             data.get("checked_at"),
            "location":               data.get("location"),
        }


class JmaNowcastRainObservedSensor(JmaNowcastEntity, BinarySensorEntity):
    """JMA 実況タイル (N1) で現在降雨があるかを判定するセンサー。"""

    _attr_device_class = BinarySensorDeviceClass.MOISTURE
    _attr_translation_key = "rain_observed"

    def __init__(self, coordinator: JmaNowcastCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_rain_observed"

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get("rain_observed", False)

    @property
    def extra_state_attributes(self) -> dict:
        if not self.coordinator.data:
            return {}
        data = self.coordinator.data
        return {
            "observed_mm":           data.get("observed_mm"),
            "observed_coverage":     data.get("observed_coverage"),
            "observed_at":           data.get("observed_at"),
            "last_rain_observed_at": data.get("last_rain_observed_at"),
            "rain_ended_at":         data.get("rain_ended_at"),
        }
