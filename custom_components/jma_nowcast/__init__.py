"""JMA Nowcast integration."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_FORECAST_MINUTES,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_RADIUS_PIXELS,
    CONF_SCAN_INTERVAL,
    CONF_THRESHOLD_MM,
    CONF_USE_HA_HOME,
    DEFAULT_FORECAST_MINUTES,
    DEFAULT_RADIUS_PIXELS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_THRESHOLD_MM,
    DOMAIN,
)
from .coordinator import JmaNowcastCoordinator

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.BUTTON,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """ConfigEntry からインテグレーションをセットアップ。"""
    options = entry.options

    # 位置情報を解決
    if options.get(CONF_USE_HA_HOME, True):
        lat = hass.config.latitude
        lon = hass.config.longitude
    else:
        lat = float(options.get(CONF_LATITUDE, hass.config.latitude))
        lon = float(options.get(CONF_LONGITUDE, hass.config.longitude))

    coordinator = JmaNowcastCoordinator(
        hass=hass,
        lat=lat,
        lon=lon,
        forecast_minutes=options.get(CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES),
        threshold_mm=float(options.get(CONF_THRESHOLD_MM, DEFAULT_THRESHOLD_MM)),
        radius_pixels=int(options.get(CONF_RADIUS_PIXELS, DEFAULT_RADIUS_PIXELS)),
        update_interval_minutes=int(options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
    )

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Options 変更時に再ロード
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Options が変更されたらエントリーをリロード。"""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """エントリーのアンロード。"""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
