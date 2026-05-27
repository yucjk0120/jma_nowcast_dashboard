"""JMA Nowcast data coordinator."""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any

import aiohttp
from PIL import Image

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    ALERT_STATE_ALERTED,
    ALERT_STATE_POST_RAIN_WAIT,
    ALERT_STATE_RAINING,
    ALERT_STATE_READY,
    COVERAGE_ANY,
    COVERAGE_RATIOS,
    DEFAULT_NO_RAIN_COOLDOWN_MIN,
    DEFAULT_POST_RAIN_COOLDOWN_MIN,
    DEFAULT_TRIGGER_COVERAGE,
    DOMAIN,
    JMA_OBSERVATION_TARGET_URL,
    JMA_PALETTE,
    JMA_TARGET_TIMES_URL,
    JMA_TILE_URL,
    ZOOM,
)

_LOGGER = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))

# 地球の赤道周長 (m)。Web Mercator のピクセル解像度計算に使う。
_EARTH_CIRCUMFERENCE_M = 40_075_016.686


# ── 座標変換 ───────────────────────────────────────────────────────────────

def lat_lon_to_tile_pixel(
    lat: float, lon: float, zoom: int
) -> tuple[int, int, int, int]:
    """緯度経度 → タイル座標 & タイル内ピクセル (Web Mercator)。"""
    n = 2 ** zoom
    x_f = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y_f = (
        (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi)
        / 2.0 * n
    )
    tx, ty = int(x_f), int(y_f)
    px = int((x_f - tx) * 256)
    py = int((y_f - ty) * 256)
    return tx, ty, px, py


def meters_per_pixel(lat: float, zoom: int) -> float:
    """Web Mercator 上での 1 ピクセルあたりのメートル (緯度依存)。"""
    return _EARTH_CIRCUMFERENCE_M / (2 ** zoom) / 256 * math.cos(math.radians(lat))


# ── カラー → 降水強度 ───────────────────────────────────────────────────────

def rgb_to_intensity(r: int, g: int, b: int) -> float:
    """最近傍マッチングで RGB → mm/h を返す。"""
    best_mm, best_d = 0.0, float("inf")
    for (pr, pg, pb), mm in JMA_PALETTE:
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if d < best_d:
            best_d, best_mm = d, mm
    return best_mm


# ── JMA 時刻ユーティリティ ────────────────────────────────────────────────

def _parse_jma_dt(s: str) -> datetime:
    return datetime.strptime(s[:14], "%Y%m%d%H%M%S").replace(tzinfo=JST)


def _find_best_entry(target_dt: datetime, entries: list[dict]) -> dict | None:
    valid = [e for e in entries if isinstance(e, dict) and "validtime" in e]
    if not valid:
        return None
    return min(
        valid,
        key=lambda e: abs((_parse_jma_dt(e["validtime"]) - target_dt).total_seconds()),
    )


# ── PIL 処理（同期・Executor で実行） ────────────────────────────────────

def _sync_check_tile(
    img_bytes: bytes,
    px: int,
    py: int,
    radius_px: int,
    threshold_mm: float,
    coverage_ratio: float,
    coverage_preset: str,
) -> tuple[bool, float, float]:
    """タイル画像を解析。

    戻り値:
        (triggered, max_mm, coverage_ratio_observed)
    """
    img = Image.open(BytesIO(img_bytes)).convert("RGBA")
    pixels = img.load()
    w, h = img.size

    max_mm = 0.0
    wet = 0
    total = 0

    for dy in range(-radius_px, radius_px + 1):
        for dx in range(-radius_px, radius_px + 1):
            ppx, ppy = px + dx, py + dy
            if 0 <= ppx < w and 0 <= ppy < h:
                red, grn, blu, alpha = pixels[ppx, ppy]
                if alpha < 50:
                    continue
                total += 1
                mm = rgb_to_intensity(red, grn, blu)
                if mm > max_mm:
                    max_mm = mm
                if mm >= threshold_mm:
                    wet += 1

    if total == 0:
        return False, 0.0, 0.0

    ratio = wet / total

    if coverage_preset == COVERAGE_ANY:
        triggered = wet > 0
    else:
        triggered = ratio >= coverage_ratio

    return triggered, round(max_mm, 1), round(ratio, 3)


# ── コーディネーター ───────────────────────────────────────────────────────

class JmaNowcastCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """JMA Nowcast のデータ取得・管理コーディネーター。"""

    def __init__(
        self,
        hass: HomeAssistant,
        lat: float,
        lon: float,
        forecast_minutes: list[int],
        threshold_mm: float,
        radius_meters: int,
        trigger_coverage: str = DEFAULT_TRIGGER_COVERAGE,
        no_rain_cooldown_min: int = DEFAULT_NO_RAIN_COOLDOWN_MIN,
        post_rain_cooldown_min: int = DEFAULT_POST_RAIN_COOLDOWN_MIN,
        update_interval_minutes: int = 5,
    ) -> None:
        self.lat = lat
        self.lon = lon
        self.forecast_minutes = forecast_minutes
        self.threshold_mm = threshold_mm
        self.radius_meters = radius_meters
        self.trigger_coverage = trigger_coverage
        self.no_rain_cooldown_sec  = int(no_rain_cooldown_min)  * 60
        self.post_rain_cooldown_sec = int(post_rain_cooldown_min) * 60

        self._tile_x, self._tile_y, self._px, self._py = lat_lon_to_tile_pixel(
            lat, lon, ZOOM
        )
        m_per_px = meters_per_pixel(lat, ZOOM)
        self._radius_pixels = max(1, int(round(radius_meters / m_per_px)))
        self._coverage_ratio = COVERAGE_RATIOS.get(trigger_coverage, 0.0)

        # ── ステートマシン状態（揮発） ──
        self._state: str = ALERT_STATE_READY
        self._state_entered_at: datetime | None = None
        self._last_alert_at:     datetime | None = None
        self._rain_ended_at:     datetime | None = None
        self._last_rain_observed_at: datetime | None = None

        _LOGGER.debug(
            "Coordinator init: tile=%s/%s/%s px=%s,%s radius=%sm (%spx) coverage=%s cooldowns=%s/%s min",
            ZOOM, self._tile_x, self._tile_y, self._px, self._py,
            radius_meters, self._radius_pixels, trigger_coverage,
            no_rain_cooldown_min, post_rain_cooldown_min,
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=update_interval_minutes),
        )

    # ── タイル取得・解析の共通ヘルパ ──
    async def _fetch_and_check_tile(
        self,
        session: aiohttp.ClientSession,
        basetime: str,
        validtime: str,
    ) -> tuple[bool, float, float] | None:
        url = JMA_TILE_URL.format(
            basetime=basetime, validtime=validtime,
            z=ZOOM, x=self._tile_x, y=self._tile_y,
        )
        try:
            async with session.get(url) as tr:
                tr.raise_for_status()
                img_bytes = await tr.read()
        except aiohttp.ClientError as exc:
            _LOGGER.warning("Tile fetch failed (%s): %s", url, exc)
            return None
        return await self.hass.async_add_executor_job(
            _sync_check_tile,
            img_bytes,
            self._px, self._py,
            self._radius_pixels,
            self.threshold_mm,
            self._coverage_ratio,
            self.trigger_coverage,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # ① 利用可能な予報・実況時刻リストを取得
                async with session.get(JMA_TARGET_TIMES_URL) as resp:
                    resp.raise_for_status()
                    entries_n2: list[dict] = await resp.json(content_type=None)

                entries_n1: list[dict] = []
                try:
                    async with session.get(JMA_OBSERVATION_TARGET_URL) as resp:
                        resp.raise_for_status()
                        entries_n1 = await resp.json(content_type=None)
                except aiohttp.ClientError as exc:
                    _LOGGER.warning("Observation target fetch failed: %s", exc)

                now = datetime.now(JST)

                result: dict[str, Any] = {
                    "checked_at": now.strftime("%H:%M"),
                    "location": {
                        "lat": round(self.lat, 4),
                        "lon": round(self.lon, 4),
                        "radius_m": self.radius_meters,
                        "radius_px": self._radius_pixels,
                        "tile": f"{ZOOM}/{self._tile_x}/{self._tile_y}",
                    },
                    "coverage": self.trigger_coverage,
                    "forecasts": {},
                    # forecast 集約
                    "any_rain": False,
                    "first_rain_in_minutes": None,
                    # 実況
                    "rain_observed":     False,
                    "observed_mm":       0.0,
                    "observed_coverage": 0.0,
                    "observed_at":       None,
                    # ステートマシン由来
                    "alert":             False,
                    "alert_state":       self._state,
                    "alert_state_since": (
                        self._state_entered_at.isoformat()
                        if self._state_entered_at else None
                    ),
                    "last_alert_at": (
                        self._last_alert_at.isoformat() if self._last_alert_at else None
                    ),
                    "last_rain_observed_at": (
                        self._last_rain_observed_at.isoformat()
                        if self._last_rain_observed_at else None
                    ),
                    "rain_ended_at": (
                        self._rain_ended_at.isoformat()
                        if self._rain_ended_at else None
                    ),
                }

                # ② 各予報時刻のタイルを取得・解析
                for mins in sorted(self.forecast_minutes):
                    entry = _find_best_entry(now + timedelta(minutes=mins), entries_n2)
                    if entry is None:
                        result["forecasts"][mins] = {
                            "rain": False, "mm": 0.0, "coverage": 0.0,
                            "error": "no_data",
                        }
                        continue

                    basetime  = entry.get("basetime", entry["validtime"])
                    validtime = entry["validtime"]
                    checked = await self._fetch_and_check_tile(session, basetime, validtime)
                    if checked is None:
                        result["forecasts"][mins] = {
                            "rain": False, "mm": 0.0, "coverage": 0.0,
                            "error": "tile_fetch_failed",
                        }
                        continue
                    has_rain, intensity, coverage_ratio = checked
                    vt_dt = _parse_jma_dt(validtime)
                    result["forecasts"][mins] = {
                        "rain":          has_rain,
                        "mm":            intensity,
                        "coverage":      coverage_ratio,
                        "forecast_time": vt_dt.strftime("%H:%M"),
                    }
                    if has_rain:
                        result["any_rain"] = True
                        if result["first_rain_in_minutes"] is None:
                            result["first_rain_in_minutes"] = mins

                # ③ 実況タイル取得（N1 の最新）
                if entries_n1:
                    obs_entry = entries_n1[0]  # 最も新しい観測時刻
                    obs_basetime  = obs_entry.get("basetime",  obs_entry["validtime"])
                    obs_validtime = obs_entry.get("validtime", obs_basetime)
                    checked = await self._fetch_and_check_tile(session, obs_basetime, obs_validtime)
                    if checked is not None:
                        obs_triggered, obs_mm, obs_cov = checked
                        result["rain_observed"]     = obs_triggered
                        result["observed_mm"]       = obs_mm
                        result["observed_coverage"] = obs_cov
                        result["observed_at"]      = _parse_jma_dt(obs_validtime).strftime("%H:%M")

                # ④ ステートマシン更新
                self._tick_state_machine(
                    forecast_triggered=result["any_rain"],
                    rain_observed=result["rain_observed"],
                    now=now,
                )
                result["alert"]             = self._is_alert_active()
                result["alert_state"]       = self._state
                result["alert_state_since"] = (
                    self._state_entered_at.isoformat()
                    if self._state_entered_at else None
                )
                result["last_alert_at"] = (
                    self._last_alert_at.isoformat() if self._last_alert_at else None
                )
                result["last_rain_observed_at"] = (
                    self._last_rain_observed_at.isoformat()
                    if self._last_rain_observed_at else None
                )
                result["rain_ended_at"] = (
                    self._rain_ended_at.isoformat() if self._rain_ended_at else None
                )

            return result

        except aiohttp.ClientError as exc:
            raise UpdateFailed(f"JMA API error: {exc}") from exc

    # ── ステートマシン ────────────────────────────────────────────────────
    def _set_state(self, new_state: str, now: datetime) -> None:
        if new_state != self._state:
            _LOGGER.info("Alert state: %s -> %s", self._state, new_state)
            self._state = new_state
            self._state_entered_at = now

    def _is_alert_active(self) -> bool:
        return self._state in (ALERT_STATE_ALERTED, ALERT_STATE_RAINING)

    def _tick_state_machine(
        self,
        *,
        forecast_triggered: bool,
        rain_observed: bool,
        now: datetime,
    ) -> None:
        # 観測タイムスタンプの更新
        if rain_observed:
            self._last_rain_observed_at = now

        if self._state == ALERT_STATE_READY:
            if forecast_triggered:
                self._set_state(ALERT_STATE_ALERTED, now)
                self._last_alert_at = now
            return

        if self._state == ALERT_STATE_ALERTED:
            if rain_observed:
                self._set_state(ALERT_STATE_RAINING, now)
                return
            cooldown = self.no_rain_cooldown_sec
            assert self._last_alert_at is not None
            elapsed = (now - self._last_alert_at).total_seconds()
            if cooldown == 0:
                # 旧挙動互換: forecast が解消したら即 READY
                if not forecast_triggered:
                    self._set_state(ALERT_STATE_READY, now)
            elif elapsed >= cooldown:
                # 空振りクールダウン経過 → READY
                self._set_state(ALERT_STATE_READY, now)
            return

        if self._state == ALERT_STATE_RAINING:
            if not rain_observed:
                self._set_state(ALERT_STATE_POST_RAIN_WAIT, now)
                self._rain_ended_at = now
            return

        if self._state == ALERT_STATE_POST_RAIN_WAIT:
            if rain_observed:
                # 雨が再開した → RAINING に戻る
                self._set_state(ALERT_STATE_RAINING, now)
                return
            cooldown = self.post_rain_cooldown_sec
            if cooldown == 0:
                self._set_state(ALERT_STATE_READY, now)
                return
            assert self._rain_ended_at is not None
            elapsed = (now - self._rain_ended_at).total_seconds()
            if elapsed >= cooldown:
                self._set_state(ALERT_STATE_READY, now)
            return
