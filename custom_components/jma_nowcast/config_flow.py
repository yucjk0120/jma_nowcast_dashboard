"""Config flow for JMA Nowcast."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    LocationSelector,
    LocationSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    ALL_COVERAGE_OPTIONS,
    ALL_FORECAST_MINUTES,
    CONF_ALERT_10_ENABLED,
    CONF_ALERT_10_MESSAGE,
    CONF_ALERT_20_ENABLED,
    CONF_ALERT_20_MESSAGE,
    CONF_ALERT_30_ENABLED,
    CONF_ALERT_30_MESSAGE,
    CONF_ALERT_60_ENABLED,
    CONF_ALERT_60_MESSAGE,
    CONF_ALERT_TARGETS,
    CONF_ALERT_TTS_ENTITY,
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
    DEFAULT_ALERT_10_ENABLED,
    DEFAULT_ALERT_10_MESSAGE,
    DEFAULT_ALERT_20_ENABLED,
    DEFAULT_ALERT_20_MESSAGE,
    DEFAULT_ALERT_30_ENABLED,
    DEFAULT_ALERT_30_MESSAGE,
    DEFAULT_ALERT_60_ENABLED,
    DEFAULT_ALERT_60_MESSAGE,
    DEFAULT_ALERT_TARGETS,
    DEFAULT_ALERT_TTS_ENTITY,
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


# ── 基本設定フォーム (既存項目) ─────────────────────────────────────────

def _build_basic_schema(
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
    """ConfigFlow / OptionsFlow で共通に使う基本設定スキーマ。"""
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


def _split_basic_input(
    user_input: dict[str, Any],
    *,
    fallback_location: dict[str, float],
) -> dict[str, Any]:
    """基本フォーム入力 → 保存用 dict。LocationSelector を分解。"""
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


# ── アラート音声設定フォーム ───────────────────────────────────────────

def _build_alert_audio_schema(
    *,
    tts_entity: str,
    targets: list[str],
    a10_enabled: bool, a10_msg: str,
    a20_enabled: bool, a20_msg: str,
    a30_enabled: bool, a30_msg: str,
    a60_enabled: bool, a60_msg: str,
) -> vol.Schema:
    """TTS 発報のバケット別メッセージ設定スキーマ。"""
    text_multiline = TextSelector(
        TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)
    )
    return vol.Schema({
        vol.Optional(CONF_ALERT_TTS_ENTITY, default=tts_entity): EntitySelector(
            EntitySelectorConfig(domain="tts")
        ),
        vol.Optional(CONF_ALERT_TARGETS, default=targets): EntitySelector(
            EntitySelectorConfig(domain="media_player", multiple=True)
        ),
        vol.Optional(CONF_ALERT_10_ENABLED, default=a10_enabled): BooleanSelector(),
        vol.Optional(CONF_ALERT_10_MESSAGE, default=a10_msg): text_multiline,
        vol.Optional(CONF_ALERT_20_ENABLED, default=a20_enabled): BooleanSelector(),
        vol.Optional(CONF_ALERT_20_MESSAGE, default=a20_msg): text_multiline,
        vol.Optional(CONF_ALERT_30_ENABLED, default=a30_enabled): BooleanSelector(),
        vol.Optional(CONF_ALERT_30_MESSAGE, default=a30_msg): text_multiline,
        vol.Optional(CONF_ALERT_60_ENABLED, default=a60_enabled): BooleanSelector(),
        vol.Optional(CONF_ALERT_60_MESSAGE, default=a60_msg): text_multiline,
    })


def _split_alert_audio_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """アラート音声フォーム入力 → 保存用 dict。"""
    return {
        CONF_ALERT_TTS_ENTITY: str(user_input.get(CONF_ALERT_TTS_ENTITY, DEFAULT_ALERT_TTS_ENTITY) or ""),
        CONF_ALERT_TARGETS:    list(user_input.get(CONF_ALERT_TARGETS, DEFAULT_ALERT_TARGETS) or []),
        CONF_ALERT_10_ENABLED: bool(user_input.get(CONF_ALERT_10_ENABLED, DEFAULT_ALERT_10_ENABLED)),
        CONF_ALERT_10_MESSAGE: str(user_input.get(CONF_ALERT_10_MESSAGE, DEFAULT_ALERT_10_MESSAGE) or ""),
        CONF_ALERT_20_ENABLED: bool(user_input.get(CONF_ALERT_20_ENABLED, DEFAULT_ALERT_20_ENABLED)),
        CONF_ALERT_20_MESSAGE: str(user_input.get(CONF_ALERT_20_MESSAGE, DEFAULT_ALERT_20_MESSAGE) or ""),
        CONF_ALERT_30_ENABLED: bool(user_input.get(CONF_ALERT_30_ENABLED, DEFAULT_ALERT_30_ENABLED)),
        CONF_ALERT_30_MESSAGE: str(user_input.get(CONF_ALERT_30_MESSAGE, DEFAULT_ALERT_30_MESSAGE) or ""),
        CONF_ALERT_60_ENABLED: bool(user_input.get(CONF_ALERT_60_ENABLED, DEFAULT_ALERT_60_ENABLED)),
        CONF_ALERT_60_MESSAGE: str(user_input.get(CONF_ALERT_60_MESSAGE, DEFAULT_ALERT_60_MESSAGE) or ""),
    }


# ── ConfigFlow (初回セットアップ) ─────────────────────────────────────

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
            stored = _split_basic_input(user_input, fallback_location=ha_location)
            # 初回は alert 設定はデフォルトのまま (OFF) で登録し、後で
            # OptionsFlow から編集してもらう方針。項目が多くなり過ぎない。
            return self.async_create_entry(title="JMA Nowcast", data=stored)

        schema = _build_basic_schema(
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


# ── OptionsFlow (再設定) ──────────────────────────────────────────────

class JmaNowcastOptionsFlow(OptionsFlow):
    """メニュー式の設定変更フロー。

    - init: 「基本設定」「アラート音声設定」の 2 択メニュー
    - basic: 監視位置・半径・発報条件・クールダウン等
    - alert_audio: TTS + media_player + バケット別メッセージ

    保存は各サブステップ完了時に既存 options とマージして create_entry する。
    ユーザーが片方だけ変更してももう片方の設定が失われない。
    """

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["basic", "alert_audio"],
        )

    # ── 基本設定サブステップ ──
    async def async_step_basic(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        current = {**self._config_entry.data, **self._config_entry.options}
        ha_location = {
            "latitude":  float(self.hass.config.latitude or 35.0),
            "longitude": float(self.hass.config.longitude or 135.0),
            "radius":    float(DEFAULT_RADIUS_METERS),
        }

        if user_input is not None:
            new_basic = _split_basic_input(user_input, fallback_location=ha_location)
            merged = self._merge_with_current(new_basic)
            return self.async_create_entry(title="", data=merged)

        default_location = {
            "latitude":  float(current.get(CONF_LATITUDE,  ha_location["latitude"])),
            "longitude": float(current.get(CONF_LONGITUDE, ha_location["longitude"])),
            "radius":    float(current.get(CONF_RADIUS_METERS, DEFAULT_RADIUS_METERS)),
        }
        default_minutes = [
            str(m) for m in current.get(CONF_FORECAST_MINUTES, DEFAULT_FORECAST_MINUTES)
        ]
        schema = _build_basic_schema(
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
        return self.async_show_form(step_id="basic", data_schema=schema)

    # ── アラート音声サブステップ ──
    async def async_step_alert_audio(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        current = {**self._config_entry.data, **self._config_entry.options}

        if user_input is not None:
            new_alert = _split_alert_audio_input(user_input)
            merged = self._merge_with_current(new_alert)
            return self.async_create_entry(title="", data=merged)

        schema = _build_alert_audio_schema(
            tts_entity=str(current.get(CONF_ALERT_TTS_ENTITY, DEFAULT_ALERT_TTS_ENTITY) or ""),
            targets=list(current.get(CONF_ALERT_TARGETS, DEFAULT_ALERT_TARGETS) or []),
            a10_enabled=bool(current.get(CONF_ALERT_10_ENABLED, DEFAULT_ALERT_10_ENABLED)),
            a10_msg=str(current.get(CONF_ALERT_10_MESSAGE, DEFAULT_ALERT_10_MESSAGE) or ""),
            a20_enabled=bool(current.get(CONF_ALERT_20_ENABLED, DEFAULT_ALERT_20_ENABLED)),
            a20_msg=str(current.get(CONF_ALERT_20_MESSAGE, DEFAULT_ALERT_20_MESSAGE) or ""),
            a30_enabled=bool(current.get(CONF_ALERT_30_ENABLED, DEFAULT_ALERT_30_ENABLED)),
            a30_msg=str(current.get(CONF_ALERT_30_MESSAGE, DEFAULT_ALERT_30_MESSAGE) or ""),
            a60_enabled=bool(current.get(CONF_ALERT_60_ENABLED, DEFAULT_ALERT_60_ENABLED)),
            a60_msg=str(current.get(CONF_ALERT_60_MESSAGE, DEFAULT_ALERT_60_MESSAGE) or ""),
        )
        return self.async_show_form(step_id="alert_audio", data_schema=schema)

    # ── 内部ヘルパ ──
    def _merge_with_current(self, new_partial: dict[str, Any]) -> dict[str, Any]:
        """OptionsFlow の create_entry は options 全体を置換するため、
        既存 options に new_partial を重ねて返す。"""
        return {**self._config_entry.options, **new_partial}
