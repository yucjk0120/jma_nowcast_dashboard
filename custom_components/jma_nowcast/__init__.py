"""JMA Nowcast integration."""
from __future__ import annotations

import logging
import math

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_FORECAST_MINUTES,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NO_RAIN_COOLDOWN_MIN,
    CONF_POST_RAIN_COOLDOWN_MIN,
    CONF_RADIUS_METERS,
    CONF_RADIUS_PIXELS,        # legacy (v1)
    CONF_SCAN_INTERVAL,
    CONF_THRESHOLD_MM,
    CONF_TRIGGER_COVERAGE,
    CONF_USE_HA_HOME,          # legacy (v1)
    DEFAULT_FORECAST_MINUTES,
    DEFAULT_RADIUS_METERS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_THRESHOLD_MM,
    DEFAULT_TRIGGER_COVERAGE,
    DOMAIN,
    MIGRATION_NO_RAIN_COOLDOWN_MIN,
    MIGRATION_POST_RAIN_COOLDOWN_MIN,
    ZOOM,
)
from .coordinator import JmaNowcastCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
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
        no_rain_cooldown_min=int(cfg.get(CONF_NO_RAIN_COOLDOWN_MIN, MIGRATION_NO_RAIN_COOLDOWN_MIN)),
        post_rain_cooldown_min=int(cfg.get(CONF_POST_RAIN_COOLDOWN_MIN, MIGRATION_POST_RAIN_COOLDOWN_MIN)),
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
    """ConfigEntry のバージョン・マイグレーション。

    - v1 → v2: use_ha_home / radius_pixels (旧) を
               latitude/longitude/radius_meters (新) に変換。
               trigger_coverage は any (旧挙動互換)。
    - v2 → v3: no_rain_cooldown_min / post_rain_cooldown_min を 0 で補完
               (既存ユーザーの挙動を壊さないため; 必要なら設定画面で上げる)。
    """
    _LOGGER.info("Migrating JMA Nowcast entry from v%s", entry.version)

    if entry.version >= 3:
        return True

    src = {**entry.data, **entry.options}

    # ── 緯度/経度/半径(m): v1 のみ変換が必要 ──
    if entry.version == 1:
        if src.get(CONF_USE_HA_HOME, True):
            lat = hass.config.latitude  or 35.0
            lon = hass.config.longitude or 135.0
        else:
            lat = src.get(CONF_LATITUDE,  hass.config.latitude  or 35.0)
            lon = src.get(CONF_LONGITUDE, hass.config.longitude or 135.0)

        # 旧 radius_pixels (zoom=10 のタイル px) → メートル概算
        meters_per_pixel = (
            40_075_016.686 / (2 ** ZOOM) / 256 * math.cos(math.radians(lat))
        )
        old_px = int(src.get(CONF_RADIUS_PIXELS, 3))
        new_meters = max(100, int(round(old_px * meters_per_pixel)))

        lat_lon_radius_coverage = {
            CONF_LATITUDE:         float(lat),
            CONF_LONGITUDE:        float(lon),
            CONF_RADIUS_METERS:    new_meters,
            CONF_TRIGGER_COVERAGE: DEFAULT_TRIGGER_COVERAGE,
        }
    else:
        # v2 の場合は既にこれらは入っている
        lat_lon_radius_coverage = {
            CONF_LATITUDE:         float(src.get(CONF_LATITUDE,  hass.config.latitude  or 35.0)),
            CONF_LONGITUDE:        float(src.get(CONF_LONGITUDE, hass.config.longitude or 135.0)),
            CONF_RADIUS_METERS:    int(src.get(CONF_RADIUS_METERS, DEFAULT_RADIUS_METERS)),
            CONF_TRIGGER_COVERAGE: str(src.get(CONF_TRIGGER_COVERAGE, DEFAULT_TRIGGER_COVERAGE)),
        }

    new_data = {
        **lat_lon_radius_coverage,
        CONF_FORECAST_MINUTES:       list(src.get(CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES)),
        CONF_THRESHOLD_MM:           float(src.get(CONF_THRESHOLD_MM, DEFAULT_THRESHOLD_MM)),
        # ── v3 新規: クールダウン (旧挙動を維持するため 0 で補完) ──
        CONF_NO_RAIN_COOLDOWN_MIN:   int(src.get(
            CONF_NO_RAIN_COOLDOWN_MIN,  MIGRATION_NO_RAIN_COOLDOWN_MIN
        )),
        CONF_POST_RAIN_COOLDOWN_MIN: int(src.get(
            CONF_POST_RAIN_COOLDOWN_MIN, MIGRATION_POST_RAIN_COOLDOWN_MIN
        )),
        CONF_SCAN_INTERVAL:          int(src.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    }

    hass.config_entries.async_update_entry(
        entry,
        data=new_data,
        options={},
        version=3,
    )
    _LOGGER.info("JMA Nowcast entry migrated to v3")
    return True
