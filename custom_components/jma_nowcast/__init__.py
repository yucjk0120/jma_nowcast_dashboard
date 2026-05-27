"""JMA Nowcast integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_FORECAST_MINUTES,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS_METERS,
    CONF_RADIUS_PIXELS,  # legacy
    CONF_SCAN_INTERVAL,
    CONF_THRESHOLD_MM,
    CONF_TRIGGER_COVERAGE,
    CONF_USE_HA_HOME,    # legacy
    DEFAULT_FORECAST_MINUTES,
    DEFAULT_RADIUS_METERS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_THRESHOLD_MM,
    DEFAULT_TRIGGER_COVERAGE,
    DOMAIN,
    ZOOM,
)
from .coordinator import JmaNowcastCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    cfg = {**entry.data, **entry.options}

    lat = float(cfg.get(CONF_LATITUDE,  hass.config.latitude  or 35.0))
    lon = float(cfg.get(CONF_LONGITUDE, hass.config.longitude or 135.0))

    coordinator = JmaNowcastCoordinator(
        hass=hass,
        lat=lat,
        lon=lon,
        forecast_minutes=cfg.get(CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES),
        threshold_mm=float(cfg.get(CONF_THRESHOLD_MM, DEFAULT_THRESHOLD_MM)),
        radius_meters=int(cfg.get(CONF_RADIUS_METERS, DEFAULT_RADIUS_METERS)),
        trigger_coverage=str(cfg.get(CONF_TRIGGER_COVERAGE, DEFAULT_TRIGGER_COVERAGE)),
        update_interval_minutes=int(cfg.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """v1 → v2 マイグレーション。

    v1 では use_ha_home / radius_pixels を使っていたため、v2 形式
    (latitude/longitude/radius_meters/trigger_coverage) に書き換える。
    """
    _LOGGER.info("Migrating JMA Nowcast entry from v%s", entry.version)

    if entry.version >= 2:
        return True

    # data と options を統合した辞書をベースに新スキーマを構築
    src = {**entry.data, **entry.options}

    if src.get(CONF_USE_HA_HOME, True):
        lat = hass.config.latitude  or 35.0
        lon = hass.config.longitude or 135.0
    else:
        lat = src.get(CONF_LATITUDE,  hass.config.latitude  or 35.0)
        lon = src.get(CONF_LONGITUDE, hass.config.longitude or 135.0)

    # 旧 radius_pixels (zoom=10 のタイル px) → メートル概算
    # 1 px ≒ (40,075,016 / 2^ZOOM / 256) * cos(lat) m
    import math
    meters_per_pixel = (
        40_075_016.686 / (2 ** ZOOM) / 256 * math.cos(math.radians(lat))
    )
    old_px = int(src.get(CONF_RADIUS_PIXELS, 3))
    new_meters = max(100, int(round(old_px * meters_per_pixel)))

    new_data = {
        CONF_LATITUDE:         float(lat),
        CONF_LONGITUDE:        float(lon),
        CONF_RADIUS_METERS:    new_meters,
        CONF_FORECAST_MINUTES: list(src.get(CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES)),
        CONF_THRESHOLD_MM:     float(src.get(CONF_THRESHOLD_MM, DEFAULT_THRESHOLD_MM)),
        CONF_TRIGGER_COVERAGE: DEFAULT_TRIGGER_COVERAGE,  # v1 は max 方式 = "any" と等価
        CONF_SCAN_INTERVAL:    int(src.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    }

    hass.config_entries.async_update_entry(
        entry,
        data=new_data,
        options={},
        version=2,
    )
    _LOGGER.info(
        "JMA Nowcast entry migrated to v2 (radius %s px -> %s m)",
        old_px, new_meters,
    )
    return True
