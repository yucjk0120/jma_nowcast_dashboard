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

# SelectSelector に渡すオプション（文字列リスト — 最も互換性が高い）
_MINUTE_OPTIONS = [str(m) for m in ALL_FORECAST_MINUTES]


class JmaNowcastConfigFlow(ConfigFlow, domain=DOMAIN):
    """JMA Nowcast 初期セットアップフロー。"""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            return self.async_create_entry(
                title="JMA Nowcast",
                data={
                    CONF_USE_HA_HOME:      user_input.get(CONF_USE_HA_HOME, DEFAULT_USE_HA_HOME),
                    CONF_LATITUDE:         float(user_input.get(CONF_LATITUDE, self.hass.config.latitude or 35.0)),
                    CONF_LONGITUDE:        float(user_input.get(CONF_LONGITUDE, self.hass.config.longitude or 135.0)),
                    CONF_FORECAST_MINUTES: DEFAULT_FORECAST_MINUTES,
                    CONF_THRESHOLD_MM:     DEFAULT_THRESHOLD_MM,
                    CONF_RADIUS_PIXELS:    DEFAULT_RADIUS_PIXELS,
                    CONF_SCAN_INTERVAL:    DEFAULT_SCAN_INTERVAL,
                },
            )

        ha_lat = round(self.hass.config.latitude or 35.0, 4)
        ha_lon = round(self.hass.config.longitude or 135.0, 4)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_USE_HA_HOME, default=True): BooleanSelector(),
                vol.Optional(CONF_LATITUDE,  default=ha_lat): NumberSelector(
                    NumberSelectorConfig(min=24, max=46, step=0.001, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_LONGITUDE, default=ha_lon): NumberSelector(
                    NumberSelectorConfig(min=122, max=154, step=0.001, mode=NumberSelectorMode.BOX)
                ),
            }),
        )

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
        # data と options を統合して現在値を取得（options が優先）
        current = {**self._config_entry.data, **self._config_entry.options}

        if user_input is not None:
            mins = [int(m) for m in user_input.get(CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES)]
            return self.async_create_entry(
                title="",
                data={**user_input, CONF_FORECAST_MINUTES: mins},
            )

        current_mins = [
            str(m) for m in current.get(CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES)
        ]
        ha_lat = round(current.get(CONF_LATITUDE, self.hass.config.latitude or 35.0), 4)
        ha_lon = round(current.get(CONF_LONGITUDE, self.hass.config.longitude or 135.0), 4)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                # ── 位置 ──────────────────────────────────────────────────
                vol.Required(
                    CONF_USE_HA_HOME,
                    default=current.get(CONF_USE_HA_HOME, DEFAULT_USE_HA_HOME),
                ): BooleanSelector(),
                vol.Optional(CONF_LATITUDE,  default=ha_lat): NumberSelector(
                    NumberSelectorConfig(min=24, max=46, step=0.001, mode=NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_LONGITUDE, default=ha_lon): NumberSelector(
                    NumberSelectorConfig(min=122, max=154, step=0.001, mode=NumberSelectorMode.BOX)
                ),
                # ── 監視する分後（文字列リストで渡す） ──────────────────────
                vol.Required(
                    CONF_FORECAST_MINUTES,
                    default=current_mins,
                ): SelectSelector(
                    SelectSelectorConfig(options=_MINUTE_OPTIONS, multiple=True)
                ),
                # ── 閾値 ────────────────────────────────────────────────────
                vol.Required(
                    CONF_THRESHOLD_MM,
                    default=float(current.get(CONF_THRESHOLD_MM, DEFAULT_THRESHOLD_MM)),
                ): NumberSelector(
                    NumberSelectorConfig(min=0.5, max=30.0, step=0.5, mode=NumberSelectorMode.SLIDER)
                ),
                # ── チェック半径 ─────────────────────────────────────────────
                vol.Required(
                    CONF_RADIUS_PIXELS,
                    default=int(current.get(CONF_RADIUS_PIXELS, DEFAULT_RADIUS_PIXELS)),
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=10, step=1, mode=NumberSelectorMode.SLIDER)
                ),
                # ── 更新間隔 ────────────────────────────────────────────────
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=int(current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
                ): NumberSelector(
                    NumberSelectorConfig(min=5, max=30, step=5, mode=NumberSelectorMode.SLIDER)
                ),
            }),
        )
