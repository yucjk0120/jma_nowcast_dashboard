"""JMA Nowcast data coordinator."""
from __future__ import annotations

import asyncio
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
UTC = timezone.utc

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
    """JMA API のタイムスタンプ (YYYYMMDDHHMMSS) を JST-aware datetime に変換。

    重要: JMA の bosai API は文字列上ローカル無指定だが **実体は UTC** で
    ある。以前は素朴に JST として tzinfo を付けており、_find_best_entry の
    比較で 9 時間ぶんズレて常に「一番未来寄りの (=+60min) エントリ」を
    掴んでしまう潜在バグがあった (obs だけは entries_n1[0] を直参照する
    ので影響を受けなかった)。ここで UTC → JST に正しく変換することで、
    downstream の strftime/isoformat が JST 表示になる従来挙動も維持する。
    """
    return (
        datetime.strptime(s[:14], "%Y%m%d%H%M%S")
        .replace(tzinfo=UTC)
        .astimezone(JST)
    )


def _find_best_entry(target_dt: datetime, entries: list[dict]) -> dict | None:
    valid = [e for e in entries if isinstance(e, dict) and "validtime" in e]
    if not valid:
        return None
    return min(
        valid,
        key=lambda e: abs((_parse_jma_dt(e["validtime"]) - target_dt).total_seconds()),
    )


# ── PIL 処理（同期・Executor で実行） ────────────────────────────────────

def _sync_check_tile_grid(
    tiles_data: dict[tuple[int, int], bytes | None],
    tx0: int, ty0: int, n_tiles_x: int, n_tiles_y: int,
    center_gx: int, center_gy: int,
    radius_px: int,
    threshold_mm: float,
    coverage_ratio: float,
    coverage_preset: str,
) -> tuple[bool, float, float]:
    """複数タイルを合成した画像に対して発報判定＋強度算出を行う。

    tiles_data: (tx, ty) → PNG bytes | None
    tx0, ty0, n_tiles_x, n_tiles_y: 合成グリッドの左上タイルとサイズ
    center_gx, center_gy: 監視位置のグローバルピクセル座標
      (= tile_x * 256 + px, tile_y * 256 + py)

    半径矩形がタイル境界を跨いでいても、必要なタイル全部を渡せば
    正しく評価される (v1.5.4 以前の単一タイル方式ではエッジで欠落した)。
    """
    stitched_w = n_tiles_x * 256
    stitched_h = n_tiles_y * 256
    canvas = Image.new("RGBA", (stitched_w, stitched_h), (255, 255, 255, 0))
    for (tx, ty), data in tiles_data.items():
        if data is None:
            continue
        try:
            tile = Image.open(BytesIO(data)).convert("RGBA")
        except Exception as exc:  # noqa: BLE001 — PIL の例外は多種
            _LOGGER.debug("analysis tile decode failed (%s,%s): %s", tx, ty, exc)
            continue
        canvas.paste(tile, ((tx - tx0) * 256, (ty - ty0) * 256), tile)

    pixels = canvas.load()
    w, h = canvas.size
    # 監視位置の合成画像内相対座標
    cx = center_gx - tx0 * 256
    cy = center_gy - ty0 * 256

    max_mm = 0.0
    wet = 0
    total = 0
    for dy in range(-radius_px, radius_px + 1):
        for dx in range(-radius_px, radius_px + 1):
            ppx, ppy = cx + dx, cy + dy
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
        show_grid: bool = False,
        # ── Alert audio ──
        alert_tts_entity: str = "",
        alert_targets: list[str] | None = None,
        alert_configs: dict[int, tuple[bool, str]] | None = None,
    ) -> None:
        self.lat = lat
        self.lon = lon
        self.forecast_minutes = forecast_minutes
        self.threshold_mm = threshold_mm
        self.radius_meters = radius_meters
        self.trigger_coverage = trigger_coverage
        self.no_rain_cooldown_sec  = int(no_rain_cooldown_min)  * 60
        self.post_rain_cooldown_sec = int(post_rain_cooldown_min) * 60
        # 監視範囲タイル camera 専用フラグ (発報ロジックには影響しない)
        self.show_grid = bool(show_grid)

        # ── アラート音声設定 ──
        # alert_configs: {minutes: (enabled, message_template)}
        self.alert_tts_entity: str = alert_tts_entity or ""
        self.alert_targets: list[str] = list(alert_targets or [])
        self.alert_configs: dict[int, tuple[bool, str]] = dict(alert_configs or {})

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

        # ── 最新観測タイル (camera エンティティが参照) ──
        self.latest_observation_image:     bytes | None = None
        self.latest_observation_at:        datetime | None = None
        # 監視範囲タイル camera 用: 同じ basetime/validtime で広域タイルを再取得する
        self.latest_observation_basetime:  str | None = None
        self.latest_observation_validtime: str | None = None
        # 予報タイル用: バケット分 (10/20/30/60) → (basetime, validtime, target_dt)。
        # analysis は forecast_minutes に絞るが、camera 表示は forecast_minutes に
        # 関わらず 4 バケット全部持っておくことで tile_x4_XXmin が常に描画できる。
        self.latest_forecast_snapshots: dict[int, tuple[str, str, datetime]] = {}

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
    async def _fetch_tile_bytes(
        self,
        session: aiohttp.ClientSession,
        basetime: str,
        validtime: str,
        tx: int | None = None,
        ty: int | None = None,
    ) -> bytes | None:
        """z=ZOOM で 1 タイル取得。tx/ty 省略時は監視位置を含むタイル。"""
        if tx is None: tx = self._tile_x
        if ty is None: ty = self._tile_y
        url = JMA_TILE_URL.format(
            basetime=basetime, validtime=validtime,
            z=ZOOM, x=tx, y=ty,
        )
        try:
            async with session.get(url) as tr:
                tr.raise_for_status()
                return await tr.read()
        except aiohttp.ClientError as exc:
            _LOGGER.warning("Tile fetch failed (%s): %s", url, exc)
            return None

    def _analysis_tile_range(self) -> tuple[int, int, int, int]:
        """半径 (radius_px) を覆うのに必要なタイル範囲 (tx0, ty0, tx1, ty1)。

        監視位置のグローバル px からラジアス分だけ広げた矩形をタイル整数
        座標に丸めた結果。半径がタイル境界を跨いでも取りこぼしなく解析
        できるように、必要枚数分すべて取得する。
        """
        r = self._radius_pixels
        gx = self._tile_x * 256 + self._px
        gy = self._tile_y * 256 + self._py
        tx0 = (gx - r) // 256
        ty0 = (gy - r) // 256
        tx1 = (gx + r) // 256
        ty1 = (gy + r) // 256
        return tx0, ty0, tx1, ty1

    async def _fetch_and_check_tile(
        self,
        session: aiohttp.ClientSession,
        basetime: str,
        validtime: str,
    ) -> tuple[bool, float, float] | None:
        """半径を覆うタイルグリッドを並列取得 → 合成 → 発報判定。"""
        tx0, ty0, tx1, ty1 = self._analysis_tile_range()
        n_x = tx1 - tx0 + 1
        n_y = ty1 - ty0 + 1
        n_grid = 2 ** ZOOM

        coords: list[tuple[int, int]] = []
        for tx in range(tx0, tx1 + 1):
            for ty in range(ty0, ty1 + 1):
                if not (0 <= ty < n_grid):
                    continue
                coords.append((tx, ty))

        async def _one(tx: int, ty: int) -> tuple[tuple[int, int], bytes | None]:
            wx = tx % n_grid
            return (tx, ty), await self._fetch_tile_bytes(
                session, basetime, validtime, tx=wx, ty=ty,
            )

        results = await asyncio.gather(*(_one(tx, ty) for tx, ty in coords))
        tiles_data: dict[tuple[int, int], bytes | None] = dict(results)

        # 少なくとも中央タイルが取れなかったら失敗扱い
        center_key = (self._tile_x, self._tile_y)
        if tiles_data.get(center_key) is None:
            return None

        gx = self._tile_x * 256 + self._px
        gy = self._tile_y * 256 + self._py
        return await self.hass.async_add_executor_job(
            _sync_check_tile_grid,
            tiles_data, tx0, ty0, n_x, n_y,
            gx, gy, self._radius_pixels,
            self.threshold_mm, self._coverage_ratio, self.trigger_coverage,
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

                # ②-a 全 4 バケットの (basetime, validtime) を先に確定させておく
                # → tile_x4_XXmin camera が forecast_minutes に含まれない
                #    バケットでも画像を表示できるように。analysis は forecast_minutes
                #    に絞るのは従来通り。
                #
                # ターゲット時刻は wall-clock now ではなく **N2 basetime + N min**
                # で計算する。JMA の N2 予報は basetime から 5 分刻みに +5..+60
                # のエントリを提供しているので、N2 basetime を基準にした方が:
                #  - 5 分刻みエントリと完全一致し、ズレなく確定的に選べる
                #  - 「10 分後」ラベルの意味が「予報基準時刻 + 10 分」で明確
                #  - coordinator の更新間隔 (5 分) の間ずっと同じ entry を返し
                #    安定 (wall-clock だと 5 分経つと +10 → +5 のエントリに切替)
                new_snapshots: dict[int, tuple[str, str, datetime]] = {}
                if entries_n2:
                    n2_base_str = entries_n2[0].get("basetime")
                    if n2_base_str:
                        n2_base_dt = _parse_jma_dt(n2_base_str)
                        for mins in (10, 20, 30, 60):
                            target = n2_base_dt + timedelta(minutes=mins)
                            entry = _find_best_entry(target, entries_n2)
                            if entry is None:
                                continue
                            bt = entry.get("basetime", entry["validtime"])
                            vt = entry["validtime"]
                            new_snapshots[mins] = (bt, vt, _parse_jma_dt(vt))
                if new_snapshots:
                    self.latest_forecast_snapshots = new_snapshots

                # ②-b 各予報時刻のタイルを取得・解析 (forecast_minutes のみ)
                for mins in sorted(self.forecast_minutes):
                    snap = self.latest_forecast_snapshots.get(mins)
                    if snap is None:
                        result["forecasts"][mins] = {
                            "rain": False, "mm": 0.0, "coverage": 0.0,
                            "error": "no_data",
                        }
                        continue

                    basetime, validtime, vt_dt = snap
                    checked = await self._fetch_and_check_tile(session, basetime, validtime)
                    if checked is None:
                        result["forecasts"][mins] = {
                            "rain": False, "mm": 0.0, "coverage": 0.0,
                            "error": "tile_fetch_failed",
                        }
                        continue
                    has_rain, intensity, coverage_ratio = checked
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

                # ③ 実況タイル (N1 の最新) を _fetch_and_check_tile (グリッド解析)
                # で評価。旧: 単一タイル取得 & 単一タイル解析 → 半径が
                # タイル境界を跨ぐケースで取りこぼしがあった。
                if entries_n1:
                    obs_entry = entries_n1[0]  # 最も新しい観測時刻
                    obs_basetime  = obs_entry.get("basetime",  obs_entry["validtime"])
                    obs_validtime = obs_entry.get("validtime", obs_basetime)
                    checked_obs = await self._fetch_and_check_tile(
                        session, obs_basetime, obs_validtime,
                    )
                    if checked_obs is not None:
                        obs_triggered, obs_mm, obs_cov = checked_obs
                        # 中央タイルは _fetch_and_check_tile 内で取得済み。
                        # camera 側は独自にタイル取得するので単純に basetime/validtime
                        # だけ持っておけば良い (latest_observation_image は legacy)。
                        self.latest_observation_at        = _parse_jma_dt(obs_validtime)
                        self.latest_observation_basetime  = obs_basetime
                        self.latest_observation_validtime = obs_validtime
                        result["rain_observed"]     = obs_triggered
                        result["observed_mm"]       = obs_mm
                        result["observed_coverage"] = obs_cov
                        result["observed_at"]      = self.latest_observation_at.strftime("%H:%M")

                # ④ ステートマシン更新
                self._tick_state_machine(
                    forecast_triggered=result["any_rain"],
                    rain_observed=result["rain_observed"],
                    first_rain_min=result.get("first_rain_in_minutes"),
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

    # ── アラート音声再生 ─────────────────────────────────────────────
    class _SafePlaceholders(dict):
        """format_map 用に、未定義プレースホルダを '?key?' で残す dict."""
        def __missing__(self, key: str) -> str:
            return f"?{key}?"

    def _placeholders_for(self, minutes: int, is_test: bool) -> dict[str, Any]:
        """メッセージテンプレートに差し込むプレースホルダ dict を作る。

        数値は float / bool として提供する (Jinja の {% if %} 条件で
        比較しやすくするため)。旧 str.format_map 記法でも str() 経由で
        自然に描画される。
        """
        data = self.data or {}
        forecasts = data.get("forecasts", {}) if isinstance(data, dict) else {}

        def _mm(key: int) -> float:
            info = forecasts.get(key) or {}
            v = info.get("mm")
            return round(float(v), 1) if isinstance(v, (int, float)) else 0.0

        def _rain(key: int) -> bool:
            info = forecasts.get(key) or {}
            return bool(info.get("rain", False))

        first_min_raw = (
            data.get("first_rain_in_minutes") if isinstance(data, dict) else None
        )
        first_min = first_min_raw if first_min_raw is not None else minutes

        # first_min 以降で最初に「雨が止む」バケット。無ければ None。
        stops_at: int | None = None
        for m in (10, 20, 30, 60):
            if m > first_min and not _rain(m):
                stops_at = m
                break

        observed_raw = (
            data.get("observed_mm") if isinstance(data, dict) else None
        )
        observed_mm = (
            round(float(observed_raw), 1)
            if isinstance(observed_raw, (int, float)) else 0.0
        )

        return {
            "minutes":          minutes,
            "mm":               _mm(minutes),
            "mm_10":            _mm(10),
            "mm_20":            _mm(20),
            "mm_30":            _mm(30),
            "mm_60":            _mm(60),
            "rain_10":          _rain(10),
            "rain_20":          _rain(20),
            "rain_30":          _rain(30),
            "rain_60":          _rain(60),
            "first_min":        first_min,
            "observed_mm":      observed_mm,
            "stops_at":         stops_at,
            "still_raining_60": _rain(60),
            "test":             is_test,
        }

    def _render_alert_message(self, minutes: int, is_test: bool) -> str | None:
        """バケットのテンプレートを埋めた文字列を返す。

        テンプレートに `{{` または `{%` が含まれれば **Jinja2** として
        評価する (HA 標準の Template クラス。{% if %} 等の条件分岐可)。
        そうでなければ従来の str.format_map スタイル (単一 {key})。

        - 未設定/空 かつ非テスト → None
        - 未設定/空 かつテスト   → 既定文言「N分後アラートのテスト再生です。」
        - レンダリング失敗       → テンプレート原文をそのまま返し WARN を残す
        """
        cfg = self.alert_configs.get(minutes)
        template = cfg[1] if cfg else ""
        if not template and not is_test:
            return None
        if not template and is_test:
            template = f"{minutes}分後アラートのテスト再生です。"

        ph = self._placeholders_for(minutes, is_test)

        if "{{" in template or "{%" in template:
            # 遅延 import: helpers.template は HA コアに含まれるが、
            # 単体テスト等では import できないケースがあるため。
            try:
                from homeassistant.helpers.template import Template
                tpl = Template(template, self.hass)
                return tpl.async_render(ph, parse_result=False)
            except Exception as exc:  # noqa: BLE001 — Jinja は多種例外を投げる
                _LOGGER.warning(
                    "Jinja render failed (bucket=%s): %s", minutes, exc
                )
                return template

        try:
            return template.format_map(self._SafePlaceholders(ph))
        except (ValueError, IndexError) as exc:
            _LOGGER.warning(
                "format_map failed (bucket=%s): %s", minutes, exc
            )
            return template

    async def async_play_alert(self, minutes: int, *, is_test: bool = False) -> None:
        """指定バケットのアラート音声を再生する。

        本番発報 (is_test=False): 設定が無効/未設定なら何もしない。
        テスト再生   (is_test=True):  設定が無効でも既定文言で再生する。
                                      ただし TTS entity と targets は必須。
        """
        if not self.alert_tts_entity or not self.alert_targets:
            _LOGGER.debug(
                "Alert skipped: tts_entity=%r targets=%r",
                self.alert_tts_entity, self.alert_targets,
            )
            return
        if not is_test:
            cfg = self.alert_configs.get(minutes)
            if not cfg or not cfg[0]:  # enabled=False or missing
                return
        message = self._render_alert_message(minutes, is_test=is_test)
        if not message:
            return
        _LOGGER.info(
            "Playing alert (bucket=%s, test=%s): %s -> %s",
            minutes, is_test, message, self.alert_targets,
        )
        try:
            await self.hass.services.async_call(
                "tts", "speak",
                {
                    "entity_id":               self.alert_tts_entity,
                    "media_player_entity_id":  self.alert_targets,
                    "message":                 message,
                },
                blocking=False,
            )
        except Exception as exc:  # noqa: BLE001 — TTS の失敗で HA を止めない
            _LOGGER.warning("Alert TTS call failed: %s", exc)

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
        first_rain_min: int | None,
        now: datetime,
    ) -> None:
        # 観測タイムスタンプの更新
        if rain_observed:
            self._last_rain_observed_at = now

        if self._state == ALERT_STATE_READY:
            if forecast_triggered:
                self._set_state(ALERT_STATE_ALERTED, now)
                self._last_alert_at = now
                # READY → ALERTED 遷移時にアラート音声を再生 (最初に降る
                # バケットの設定を使用)。fire-and-forget でメイン更新
                # フローをブロックしない。
                if first_rain_min in (10, 20, 30, 60):
                    self.hass.async_create_task(
                        self.async_play_alert(first_rain_min)
                    )
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
