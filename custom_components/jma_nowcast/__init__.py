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
    # data と options を統合（options が優先）
    cfg = {**entry.data, **entry.options}

    if cfg.get(CONF_USE_HA_HOME, True):
        lat = hass.config.latitude
        lon = hass.config.longitude
    else:
        lat = float(cfg.get(CONF_LATITUDE, hass.config.latitude))
        lon = float(cfg.get(CONF_LONGITUDE, hass.config.longitude))

    coordinator = JmaNowcastCoordinator(
        hass=hass,
        lat=lat,
        lon=lon,
        forecast_minutes=cfg.get(CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES),
        threshold_mm=float(cfg.get(CONF_THRESHOLD_MM, DEFAULT_THRESHOLD_MM)),
        radius_pixels=int(cfg.get(CONF_RADIUS_PIXELS, DEFAULT_RADIUS_PIXELS)),
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
