"""Config flow for JMA Nowcast."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    LocationSelector,
    LocationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    ALL_COVERAGE_OPTIONS,
    ALL_FORECAST_MINUTES,
    CONF_FORECAST_MINUTES,
    CONF_LATITUDE,
    CONF_LOCATION,
    CONF_LONGITUDE,
    CONF_NO_RAIN_COOLDOWN_MIN,
    CONF_POST_RAIN_COOLDOWN_MIN,
    CONF_RADIUS_METERS,
    CONF_RESET_TO_HOME,
    CONF_SCAN_INTERVAL,
    CONF_SHOW_GRID,
    CONF_THRESHOLD_MM,
    CONF_TRIGGER_COVERAGE,
    DEFAULT_FORECAST_MINUTES,
    DEFAULT_NO_RAIN_COOLDOWN_MIN,
    DEFAULT_POST_RAIN_COOLDOWN_MIN,
    DEFAULT_RADIUS_METERS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SHOW_GRID,
    DEFAULT_THRESHOLD_MM,
    DEFAULT_TRIGGER_COVERAGE,
    DOMAIN,
    MAX_COOLDOWN_MIN,
    MIN_COOLDOWN_MIN,
)

_MINUTE_OPTIONS = [str(m) for m in ALL_FORECAST_MINUTES]


def _build_form_schema(
    *,
    default_location: dict[str, float],
    default_minutes: list[str],
    default_threshold: float,
    default_coverage: str,
    default_no_rain_cooldown: int,
    default_post_rain_cooldown: int,
    default_interval: int,
    default_show_grid: bool,
    include_reset: bool,
) -> vol.Schema:
    """ConfigFlow / OptionsFlow 共通のスキーマを組み立てる。"""
    fields: dict = {
        vol.Required(CONF_LOCATION, default=default_location): LocationSelector(
            LocationSelectorConfig(radius=True)
        ),
    }
    if include_reset:
        fields[
            vol.Optional(CONF_RESET_TO_HOME, default=False)
        ] = BooleanSelector()

    fields.update({
        vol.Required(CONF_FORECAST_MINUTES, default=default_minutes): SelectSelector(
            SelectSelectorConfig(options=_MINUTE_OPTIONS, multiple=True)
        ),
        vol.Required(CONF_THRESHOLD_MM, default=default_threshold): NumberSelector(
            NumberSelectorConfig(min=0.5, max=30.0, step=0.5, mode=NumberSelectorMode.SLIDER)
        ),
        vol.Required(CONF_TRIGGER_COVERAGE, default=default_coverage): SelectSelector(
            SelectSelectorConfig(
                options=ALL_COVERAGE_OPTIONS,
                translation_key="trigger_coverage",
            )
        ),
        vol.Required(
            CONF_NO_RAIN_COOLDOWN_MIN, default=default_no_rain_cooldown
        ): NumberSelector(
            NumberSelectorConfig(
                min=MIN_COOLDOWN_MIN, max=MAX_COOLDOWN_MIN, step=5,
                mode=NumberSelectorMode.SLIDER, unit_of_measurement="分",
            )
        ),
        vol.Required(
            CONF_POST_RAIN_COOLDOWN_MIN, default=default_post_rain_cooldown
        ): NumberSelector(
            NumberSelectorConfig(
                min=MIN_COOLDOWN_MIN, max=MAX_COOLDOWN_MIN, step=5,
                mode=NumberSelectorMode.SLIDER, unit_of_measurement="分",
            )
        ),
        vol.Required(CONF_SCAN_INTERVAL, default=default_interval): NumberSelector(
            NumberSelectorConfig(min=5, max=30, step=5, mode=NumberSelectorMode.SLIDER)
        ),
        vol.Optional(CONF_SHOW_GRID, default=default_show_grid): BooleanSelector(),
    })
    return vol.Schema(fields)


def _split_user_input(
    user_input: dict[str, Any],
    *,
    fallback_location: dict[str, float],
) -> dict[str, Any]:
    """フォーム入力 → 保存用 dict に変換。

    LocationSelector の返却 dict を lat/lon/radius_meters に分解する。
    reset_to_home が True なら fallback_location で上書き。
    """
    location = dict(user_input.get(CONF_LOCATION, fallback_location))
    if user_input.get(CONF_RESET_TO_HOME):
        location = dict(fallback_location)

    minutes = [int(m) for m in user_input.get(CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES)]

    return {
        CONF_LATITUDE:               float(location["latitude"]),
        CONF_LONGITUDE:              float(location["longitude"]),
        CONF_RADIUS_METERS:          int(round(float(location.get("radius", DEFAULT_RADIUS_METERS)))),
        CONF_FORECAST_MINUTES:       minutes,
        CONF_THRESHOLD_MM:           float(user_input.get(CONF_THRESHOLD_MM, DEFAULT_THRESHOLD_MM)),
        CONF_TRIGGER_COVERAGE:       user_input.get(CONF_TRIGGER_COVERAGE, DEFAULT_TRIGGER_COVERAGE),
        CONF_NO_RAIN_COOLDOWN_MIN:   int(user_input.get(CONF_NO_RAIN_COOLDOWN_MIN, DEFAULT_NO_RAIN_COOLDOWN_MIN)),
        CONF_POST_RAIN_COOLDOWN_MIN: int(user_input.get(CONF_POST_RAIN_COOLDOWN_MIN, DEFAULT_POST_RAIN_COOLDOWN_MIN)),
        CONF_SCAN_INTERVAL:          int(user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        CONF_SHOW_GRID:              bool(user_input.get(CONF_SHOW_GRID, DEFAULT_SHOW_GRID)),
    }


class JmaNowcastConfigFlow(ConfigFlow, domain=DOMAIN):
    """JMA Nowcast 初期セットアップフロー。"""

    VERSION = 3

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        ha_location = self._ha_home_location()

        if user_input is not None:
            stored = _split_user_input(user_input, fallback_location=ha_location)
            return self.async_create_entry(title="JMA Nowcast", data=stored)

        schema = _build_form_schema(
            default_location=ha_location,
            default_minutes=[str(m) for m in DEFAULT_FORECAST_MINUTES],
            default_threshold=DEFAULT_THRESHOLD_MM,
            default_coverage=DEFAULT_TRIGGER_COVERAGE,
            default_no_rain_cooldown=DEFAULT_NO_RAIN_COOLDOWN_MIN,
            default_post_rain_cooldown=DEFAULT_POST_RAIN_COOLDOWN_MIN,
            default_interval=DEFAULT_SCAN_INTERVAL,
            default_show_grid=DEFAULT_SHOW_GRID,
            include_reset=False,  # 初回はリセット不要（既にHAホームが初期値）
        )
        return self.async_show_form(step_id="user", data_schema=schema)

    def _ha_home_location(self) -> dict[str, float]:
        return {
            "latitude":  float(self.hass.config.latitude or 35.0),
            "longitude": float(self.hass.config.longitude or 135.0),
            "radius":    float(DEFAULT_RADIUS_METERS),
        }

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return JmaNowcastOptionsFlow(config_entry)


class JmaNowcastOptionsFlow(OptionsFlow):
    """セットアップ後の設定変更フロー。"""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        current = {**self._config_entry.data, **self._config_entry.options}
        ha_location = {
            "latitude":  float(self.hass.config.latitude or 35.0),
            "longitude": float(self.hass.config.longitude or 135.0),
            "radius":    float(DEFAULT_RADIUS_METERS),
        }

        if user_input is not None:
            stored = _split_user_input(user_input, fallback_location=ha_location)
            return self.async_create_entry(title="", data=stored)

        default_location = {
            "latitude":  float(current.get(CONF_LATITUDE,  ha_location["latitude"])),
            "longitude": float(current.get(CONF_LONGITUDE, ha_location["longitude"])),
            "radius":    float(current.get(CONF_RADIUS_METERS, DEFAULT_RADIUS_METERS)),
        }
        default_minutes = [
            str(m) for m in current.get(CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES)
        ]
        schema = _build_form_schema(
            default_location=default_location,
            default_minutes=default_minutes,
            default_threshold=float(current.get(CONF_THRESHOLD_MM, DEFAULT_THRESHOLD_MM)),
            default_coverage=str(current.get(CONF_TRIGGER_COVERAGE, DEFAULT_TRIGGER_COVERAGE)),
            default_no_rain_cooldown=int(current.get(
                CONF_NO_RAIN_COOLDOWN_MIN, DEFAULT_NO_RAIN_COOLDOWN_MIN)),
            default_post_rain_cooldown=int(current.get(
                CONF_POST_RAIN_COOLDOWN_MIN, DEFAULT_POST_RAIN_COOLDOWN_MIN)),
            default_interval=int(current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
            default_show_grid=bool(current.get(CONF_SHOW_GRID, DEFAULT_SHOW_GRID)),
            include_reset=True,
        )
        return self.async_show_form(step_id="init", data_schema=schema)
