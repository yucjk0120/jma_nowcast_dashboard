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
    DOMAIN,
    JMA_PALETTE,
    JMA_TARGET_TIMES_URL,
    JMA_TILE_URL,
    ZOOM,
)

_LOGGER = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))


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
    radius: int,
    threshold_mm: float,
) -> tuple[bool, float]:
    """タイル画像を解析して降水強度を返す（ブロッキング処理）。"""
    img = Image.open(BytesIO(img_bytes)).convert("RGBA")
    pixels = img.load()
    w, h = img.size
    max_mm = 0.0
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            ppx, ppy = px + dx, py + dy
            if 0 <= ppx < w and 0 <= ppy < h:
                red, grn, blu, alpha = pixels[ppx, ppy]
                if alpha < 50:
                    continue  # 透明 = データなし
                max_mm = max(max_mm, rgb_to_intensity(red, grn, blu))
    return max_mm >= threshold_mm, round(max_mm, 1)


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
        radius_pixels: int,
        update_interval_minutes: int = 5,
    ) -> None:
        self.lat = lat
        self.lon = lon
        self.forecast_minutes = forecast_minutes
        self.threshold_mm = threshold_mm
        self.radius_pixels = radius_pixels

        self._tile_x, self._tile_y, self._px, self._py = lat_lon_to_tile_pixel(
            lat, lon, ZOOM
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=update_interval_minutes),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # ① 利用可能な予報時刻を取得
                async with session.get(JMA_TARGET_TIMES_URL) as resp:
                    resp.raise_for_status()
                    entries: list[dict] = await resp.json(content_type=None)

                now = datetime.now(JST)
                result: dict[str, Any] = {
                    "any_rain": False,
                    "first_rain_in_minutes": None,
                    "checked_at": now.strftime("%H:%M"),
                    "location": {
                        "lat": round(self.lat, 4),
                        "lon": round(self.lon, 4),
                        "tile": f"{ZOOM}/{self._tile_x}/{self._tile_y}",
                    },
                    "forecasts": {},
                }

                # ② 各時間帯のタイルを取得・解析
                for mins in sorted(self.forecast_minutes):
                    entry = _find_best_entry(now + timedelta(minutes=mins), entries)
                    if entry is None:
                        result["forecasts"][mins] = {
                            "rain": False, "mm": 0.0, "error": "no_data"
                        }
                        continue

                    basetime  = entry.get("basetime", entry["validtime"])
                    validtime = entry["validtime"]
                    tile_url  = JMA_TILE_URL.format(
                        basetime=basetime, validtime=validtime,
                        z=ZOOM, x=self._tile_x, y=self._tile_y,
                    )

                    try:
                        async with session.get(tile_url) as tr:
                            tr.raise_for_status()
                            img_bytes = await tr.read()
                    except aiohttp.ClientError as exc:
                        _LOGGER.warning("Tile fetch failed (%s min): %s", mins, exc)
                        result["forecasts"][mins] = {
                            "rain": False, "mm": 0.0, "error": str(exc)
                        }
                        continue

                    # PIL 解析は Executor で実行（ブロッキング回避）
                    has_rain, intensity = await self.hass.async_add_executor_job(
                        _sync_check_tile,
                        img_bytes,
                        self._px, self._py,
                        self.radius_pixels,
                        self.threshold_mm,
                    )

                    vt_dt = _parse_jma_dt(validtime)
                    result["forecasts"][mins] = {
                        "rain": has_rain,
                        "mm": intensity,
                        "forecast_time": vt_dt.strftime("%H:%M"),
                    }

                    if has_rain:
                        result["any_rain"] = True
                        if result["first_rain_in_minutes"] is None:
                            result["first_rain_in_minutes"] = mins

            return result

        except aiohttp.ClientError as exc:
            raise UpdateFailed(f"JMA API error: {exc}") from exc
