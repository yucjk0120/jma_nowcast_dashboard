"""Config flow for JMA Nowcast."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    ALL_FORECAST_MINUTES,
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
    DEFAULT_USE_HA_HOME,
    DOMAIN,
)


class JmaNowcastConfigFlow(ConfigFlow, domain=DOMAIN):
    """JMA Nowcast 初期セットアップフロー。"""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """最初のセットアップステップ。"""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            return self.async_create_entry(
                title="JMA Nowcast",
                data={},
                options={
                    CONF_USE_HA_HOME: user_input.get(CONF_USE_HA_HOME, DEFAULT_USE_HA_HOME),
                    CONF_LATITUDE:    user_input.get(CONF_LATITUDE, 35.0),
                    CONF_LONGITUDE:   user_input.get(CONF_LONGITUDE, 135.0),
                    CONF_FORECAST_MINUTES: DEFAULT_FORECAST_MINUTES,
                    CONF_THRESHOLD_MM:     DEFAULT_THRESHOLD_MM,
                    CONF_RADIUS_PIXELS:    DEFAULT_RADIUS_PIXELS,
                    CONF_SCAN_INTERVAL:    DEFAULT_SCAN_INTERVAL,
                },
            )

        # HA のホーム座標をデフォルト値として表示
        ha_lat = self.hass.config.latitude or 35.0
        ha_lon = self.hass.config.longitude or 135.0

        schema = vol.Schema({
            vol.Required(CONF_USE_HA_HOME, default=True): BooleanSelector(),
            vol.Optional(CONF_LATITUDE,  default=round(ha_lat, 4)): NumberSelector(
                NumberSelectorConfig(min=24, max=46, step=0.0001, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(CONF_LONGITUDE, default=round(ha_lon, 4)): NumberSelector(
                NumberSelectorConfig(min=122, max=154, step=0.0001, mode=NumberSelectorMode.BOX)
            ),
        })

        return self.async_show_form(step_id="user", data_schema=schema)

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
        options = self._config_entry.options

        if user_input is not None:
            # multi-select は文字列リストで返るので int に変換
            mins = [int(m) for m in user_input.get(CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES)]
            return self.async_create_entry(
                title="",
                data={**user_input, CONF_FORECAST_MINUTES: mins},
            )

        current_mins = [str(m) for m in options.get(CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES)]

        schema = vol.Schema({
            # ── 位置 ──────────────────────────────────────────────────────
            vol.Required(
                CONF_USE_HA_HOME,
                default=options.get(CONF_USE_HA_HOME, DEFAULT_USE_HA_HOME),
            ): BooleanSelector(),
            vol.Optional(
                CONF_LATITUDE,
                default=round(options.get(CONF_LATITUDE, self.hass.config.latitude or 35.0), 4),
            ): NumberSelector(
                NumberSelectorConfig(min=24, max=46, step=0.0001, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_LONGITUDE,
                default=round(options.get(CONF_LONGITUDE, self.hass.config.longitude or 135.0), 4),
            ): NumberSelector(
                NumberSelectorConfig(min=122, max=154, step=0.0001, mode=NumberSelectorMode.BOX)
            ),
            # ── 監視する分後 ───────────────────────────────────────────────
            vol.Required(
                CONF_FORECAST_MINUTES,
                default=current_mins,
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[str(m) for m in ALL_FORECAST_MINUTES],
                    multiple=True,
                    translation_key="forecast_minutes",
                )
            ),
            # ── 降水閾値 ────────────────────────────────────────────────────
            vol.Required(
                CONF_THRESHOLD_MM,
                default=options.get(CONF_THRESHOLD_MM, DEFAULT_THRESHOLD_MM),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0.5, max=30.0, step=0.5,
                    unit_of_measurement="mm/h",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            # ── チェック半径 ────────────────────────────────────────────────
            vol.Required(
                CONF_RADIUS_PIXELS,
                default=options.get(CONF_RADIUS_PIXELS, DEFAULT_RADIUS_PIXELS),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=1, max=10, step=1,
                    unit_of_measurement="px",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
            # ── 更新間隔 ────────────────────────────────────────────────────
            vol.Required(
                CONF_SCAN_INTERVAL,
                default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=5, max=30, step=5,
                    unit_of_measurement="分",
                    mode=NumberSelectorMode.SLIDER,
                )
            ),
        })

        return self.async_show_form(step_id="init", data_schema=schema)
