"""Camera platform for JMA Nowcast — 監視範囲タイル (4 スケール)。

各カメラエンティティは 1024×1024 px の PNG を返す:
  - 下層: 国土地理院 (GSI) 淡色地図
  - 上層: JMA HRPNS 降水ナウキャストの最新観測タイル (半透明オーバーレイ)
  - 監視位置の半径円と中心マーカーをその上に描画

監視位置は常に画像中央 (512, 512)。複数タイルをまたぐ場合は連結して
クロップし、必要なら BICUBIC で 1024px に拡縮する。

スケール R = 4 / 8 / 16 / 32 で 4 つのカメラを生成する。
R は「監視範囲の円が画像幅の 1/R」を表す（R が大きい = より広域）。
"""
from __future__ import annotations

import asyncio
import logging
import math
from io import BytesIO
from typing import Any, Callable

import aiohttp
from PIL import Image, ImageDraw

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    DOMAIN,
    GSI_MAX_ZOOM,
    GSI_PALE_TILE_URL,
    JMA_TILE_URL,
    TILE_CAMERA_OUTPUT_PX,
    TILE_CAMERA_OVERLAY_ALPHA,
    TILE_CAMERA_SCALES,
)
from .coordinator import JmaNowcastCoordinator
from .entity import JmaNowcastEntity

_LOGGER = logging.getLogger(__name__)

# ── タイル / Mercator 定数 ────────────────────────────────────────────
_TILE_PX = 256
_EARTH_CIRCUMFERENCE_M = 40_075_016.686
# JMA HRPNS のタイルが提供されるズーム域
_JMA_ZOOM_MIN, _JMA_ZOOM_MAX = 4, 10
# 1 レイヤあたりタイル枚数の上限 (一辺)。R=32 × 大半径でも 12×12 で収まる。
_MAX_TILES_PER_SIDE = 12
# 1 回の grid 取得で同時に走らせる aiohttp リクエスト数
_FETCH_CONCURRENCY = 8

# ── 装飾色 (RGBA) ────────────────────────────────────────────────────
_BG_FALLBACK_COLOR  = (245, 245, 245, 255)
_RADIUS_COLOR       = (220,  20,  20, 235)
_RADIUS_HALO_COLOR  = (255, 255, 255, 200)
_CENTER_FILL        = (220,  20,  20, 255)
_CENTER_OUTLINE     = (255, 255, 255, 255)

# ── プロセスワイド タイルキャッシュ ─────────────────────────────────
# GSI 淡色地図は実質不変なので無期限に保持する (キーは zoom/x/y)。
_GSI_CACHE: dict[tuple[int, int, int], bytes] = {}
# JMA タイルはスナップショット (basetime, validtime) が変わると無価値になる。
# 5 分おきに更新されるため、現スナップショット以外をソフトキャップで掃除する。
_JMA_CACHE: dict[tuple[str, str, int, int, int], bytes] = {}
_JMA_CACHE_SOFT_CAP = 256


# ── Web Mercator ヘルパ ───────────────────────────────────────────────

def _global_pixel(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """緯度経度 → そのズームでのグローバルピクセル座標 (小数可)。"""
    n = 2 ** zoom
    px = (lon + 180.0) / 360.0 * n * _TILE_PX
    lat_r = math.radians(lat)
    py = (
        (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi)
        / 2.0 * n * _TILE_PX
    )
    return px, py


def _mpp(lat: float, zoom: int) -> float:
    """その緯度・ズームでの 1 ピクセルあたりメートル。"""
    return (
        _EARTH_CIRCUMFERENCE_M / (2 ** zoom) / _TILE_PX
        * math.cos(math.radians(lat))
    )


def _pick_zoom(
    lat: float,
    image_extent_m: float,
    *,
    z_min: int,
    z_max: int,
    max_tiles_per_side: int,
) -> int:
    """タイル枚数予算に収まる最大のズームを返す。

    ズームが高いほど解像度が上がるがタイル数も増える。
    image_extent_m は最終画像が地理的にカバーする一辺の長さ。
    """
    if image_extent_m <= 0:
        return z_min
    cos_lat = max(math.cos(math.radians(lat)), 1e-6)
    # tiles_per_side(z) = extent * 2^z / (C * cos_lat)
    # tiles_per_side <= budget  ⇔  2^z <= budget * C * cos_lat / extent
    z_budget = int(math.floor(math.log2(
        max_tiles_per_side * _EARTH_CIRCUMFERENCE_M * cos_lat / image_extent_m
    )))
    return max(z_min, min(z_max, z_budget))


def _tile_range(
    cx: float, cy: float, src_window_px: float
) -> tuple[int, int, int, int]:
    """中心 (cx, cy) を含む src_window_px 四方の窓を覆うタイル範囲。"""
    half = src_window_px / 2
    tx0 = math.floor((cx - half) / _TILE_PX)
    ty0 = math.floor((cy - half) / _TILE_PX)
    tx1 = math.floor((cx + half) / _TILE_PX)
    ty1 = math.floor((cy + half) / _TILE_PX)
    return tx0, ty0, tx1, ty1


# ── タイル取得 ────────────────────────────────────────────────────────

async def _fetch_grid(
    session: aiohttp.ClientSession,
    url_fn: Callable[[int, int, int], str],
    cache: dict,
    cache_key: Callable[[int, int, int], tuple],
    zoom: int,
    tx0: int, ty0: int, tx1: int, ty1: int,
) -> dict[tuple[int, int], bytes | None]:
    """指定範囲のタイルを並列取得。cache にヒットしたものはスキップする。

    戻り値は (tx, ty) → タイル PNG バイト列 (取得失敗時は None)。
    """
    n = 2 ** zoom
    sem = asyncio.Semaphore(_FETCH_CONCURRENCY)

    async def _one(wx: int, ty: int, ck: tuple) -> None:
        url = url_fn(zoom, wx, ty)
        try:
            async with sem, session.get(url) as resp:
                resp.raise_for_status()
                cache[ck] = await resp.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            _LOGGER.debug("tile fetch %s/%s/%s failed: %s", zoom, wx, ty, exc)

    to_fetch: list[tuple[int, int, tuple]] = []
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            if not (0 <= ty < n):
                continue  # 極を越える領域は存在しない
            wx = tx % n   # 経度は周回
            ck = cache_key(zoom, wx, ty)
            if ck not in cache:
                to_fetch.append((wx, ty, ck))

    if to_fetch:
        await asyncio.gather(*(_one(*args) for args in to_fetch))

    out: dict[tuple[int, int], bytes | None] = {}
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            if not (0 <= ty < n):
                out[(tx, ty)] = None
                continue
            out[(tx, ty)] = cache.get(cache_key(zoom, tx % n, ty))
    return out


def _evict_old_jma_entries(basetime: str, validtime: str) -> None:
    """JMA キャッシュをソフトキャップで掃除する。

    現スナップショット以外のエントリは使い回されないので削る。
    """
    if len(_JMA_CACHE) <= _JMA_CACHE_SOFT_CAP:
        return
    keep = (basetime, validtime)
    for key in list(_JMA_CACHE.keys()):
        if (key[0], key[1]) != keep:
            del _JMA_CACHE[key]


# ── 合成 (Executor で同期実行) ────────────────────────────────────────

def _layer_image(
    tiles: dict[tuple[int, int], bytes | None],
    tx0: int, ty0: int, tx1: int, ty1: int,
    cx: float, cy: float,
    src_window_px: float,
    output_px: int,
    *,
    resample: int = Image.BICUBIC,
) -> Image.Image:
    """タイルを連結 → 中心 (cx, cy) を画像中心に src_window_px 四方をクロップ
    → output_px 四方にリサイズ。"""
    grid_w = (tx1 - tx0 + 1) * _TILE_PX
    grid_h = (ty1 - ty0 + 1) * _TILE_PX
    canvas = Image.new("RGBA", (grid_w, grid_h), (255, 255, 255, 0))
    for (tx, ty), data in tiles.items():
        if data is None:
            continue
        try:
            tile = Image.open(BytesIO(data)).convert("RGBA")
        except Exception as exc:  # noqa: BLE001 — PIL は多種多様な例外を出す
            _LOGGER.debug("tile decode failed: %s", exc)
            continue
        canvas.paste(tile, ((tx - tx0) * _TILE_PX, (ty - ty0) * _TILE_PX), tile)

    rel_cx = cx - tx0 * _TILE_PX
    rel_cy = cy - ty0 * _TILE_PX
    half = src_window_px / 2
    crop = canvas.crop((
        int(round(rel_cx - half)), int(round(rel_cy - half)),
        int(round(rel_cx + half)), int(round(rel_cy + half)),
    ))
    if crop.size != (output_px, output_px):
        crop = crop.resize((output_px, output_px), resample)
    return crop


def _render(
    base_tiles: dict | None,
    base_tx0: int, base_ty0: int, base_tx1: int, base_ty1: int,
    base_cx: float, base_cy: float, base_window_px: float,
    overlay_tiles: dict | None,
    ovl_tx0: int, ovl_ty0: int, ovl_tx1: int, ovl_ty1: int,
    ovl_cx: float, ovl_cy: float, ovl_window_px: float,
    output_px: int,
    overlay_alpha: int,
    circle_radius_px: int,
) -> bytes:
    """ベース → オーバーレイ → 半径円 / 中心マーカー の順に重ねて PNG にする。"""

    if base_tiles is not None:
        base = _layer_image(
            base_tiles, base_tx0, base_ty0, base_tx1, base_ty1,
            base_cx, base_cy, base_window_px, output_px,
            resample=Image.BICUBIC,  # 地図ラベルが滑らかになる
        )
    else:
        base = Image.new("RGBA", (output_px, output_px), _BG_FALLBACK_COLOR)

    if overlay_tiles is not None:
        # JMA HRPNS は 250 m メッシュなのでズーム時はピクセルがそのまま見える
        # ことに価値がある。NEAREST でアップサンプルしてエッジを保つ。
        overlay = _layer_image(
            overlay_tiles, ovl_tx0, ovl_ty0, ovl_tx1, ovl_ty1,
            ovl_cx, ovl_cy, ovl_window_px, output_px,
            resample=Image.NEAREST,
        )
        # JMA タイルは無降水域が既に半透明 (alpha < 255) なので、
        # 上書きせず乗算してベース地図を透かす。
        a = overlay.getchannel("A").point(
            lambda v: int(v * overlay_alpha / 255)
        )
        overlay.putalpha(a)
        base = Image.alpha_composite(base, overlay)

    draw = ImageDraw.Draw(base)
    cx = cy = output_px // 2

    # 半径円: 暗いタイルでも視認できるよう白いハロー + 赤本体の二重描き。
    halo_w = max(6, output_px // 600)
    line_w = max(3, output_px // 1200)
    r = circle_radius_px
    draw.ellipse(
        [(cx - r, cy - r), (cx + r, cy + r)],
        outline=_RADIUS_HALO_COLOR, width=halo_w,
    )
    draw.ellipse(
        [(cx - r, cy - r), (cx + r, cy + r)],
        outline=_RADIUS_COLOR, width=line_w,
    )

    # 中心マーカー: 白い縁取りクロスヘア + 赤い芯 + 中央ドット。
    arm = max(20, output_px // 80)
    draw.line([(cx - arm, cy), (cx + arm, cy)], fill=_CENTER_OUTLINE, width=line_w * 3)
    draw.line([(cx, cy - arm), (cx, cy + arm)], fill=_CENTER_OUTLINE, width=line_w * 3)
    draw.line([(cx - arm, cy), (cx + arm, cy)], fill=_CENTER_FILL, width=line_w)
    draw.line([(cx, cy - arm), (cx, cy + arm)], fill=_CENTER_FILL, width=line_w)
    dot = max(6, output_px // 250)
    draw.ellipse(
        [(cx - dot - 2, cy - dot - 2), (cx + dot + 2, cy + dot + 2)],
        fill=_CENTER_OUTLINE,
    )
    draw.ellipse(
        [(cx - dot, cy - dot), (cx + dot, cy + dot)],
        fill=_CENTER_FILL,
    )

    out = BytesIO()
    # RGB に落として PNG 出力 (~40% ファイルサイズ削減)。
    base.convert("RGB").save(out, format="PNG")
    return out.getvalue()


# ── Camera エンティティ ───────────────────────────────────────────────

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: JmaNowcastCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        JmaNowcastScaledTileCamera(coordinator, entry, scale)
        for scale in TILE_CAMERA_SCALES
    )


class JmaNowcastScaledTileCamera(JmaNowcastEntity, Camera):
    """GSI 淡色地図 + JMA 降水オーバーレイの監視範囲タイル (固定スケール)。

    監視範囲の円は常に画像幅の 1/scale を占める。scale が大きいほど
    広域が映る（円は相対的に小さく見える）。
    """

    _attr_should_poll = False
    _attr_icon = "mdi:map"
    _attr_brand = "JMA"
    content_type = "image/png"

    def __init__(
        self,
        coordinator: JmaNowcastCoordinator,
        entry: ConfigEntry,
        scale: int,
    ) -> None:
        Camera.__init__(self)
        JmaNowcastEntity.__init__(self, coordinator, entry)
        self._scale = scale
        self._attr_translation_key = f"tile_x{scale}"
        self._attr_unique_id = f"{entry.entry_id}_tile_x{scale}"
        self._attr_model = f"HRPNS tile ×{scale}"
        # 直近の合成結果をキャッシュ (coordinator 更新で破棄)。
        self._cached_png: bytes | None = None
        self._cache_token: tuple | None = None

    def _handle_coordinator_update(self) -> None:
        # JMA スナップショットが進んだ → 合成キャッシュを捨てて、
        # HA に再描画タイミングを通知する。
        self._cached_png = None
        self._cache_token = None
        super()._handle_coordinator_update()

    async def async_camera_image(
        self,
        width: int | None = None,
        height: int | None = None,
    ) -> bytes | None:
        coord = self.coordinator
        token = (
            coord.lat, coord.lon, coord.radius_meters,
            coord.latest_observation_basetime,
            coord.latest_observation_validtime,
        )
        if self._cache_token == token and self._cached_png is not None:
            return self._cached_png

        png = await self._build_png()
        if png is not None:
            self._cached_png = png
            self._cache_token = token
        return png

    async def _build_png(self) -> bytes | None:
        coord = self.coordinator
        lat, lon = coord.lat, coord.lon
        radius_m = max(1, int(coord.radius_meters))
        out_px = TILE_CAMERA_OUTPUT_PX

        # 円の直径 = image_width / scale → image_extent_m = 2 × scale × radius
        image_extent_m = 2 * self._scale * radius_m
        circle_radius_px = out_px // (2 * self._scale)

        # ── ベース地図 (GSI 淡色) ──
        base_z = _pick_zoom(
            lat, image_extent_m,
            z_min=0, z_max=GSI_MAX_ZOOM,
            max_tiles_per_side=_MAX_TILES_PER_SIDE,
        )
        base_cx, base_cy = _global_pixel(lat, lon, base_z)
        base_window_px = image_extent_m / _mpp(lat, base_z)
        base_tx0, base_ty0, base_tx1, base_ty1 = _tile_range(
            base_cx, base_cy, base_window_px,
        )

        # ── オーバーレイ (JMA HRPNS) ──
        ovl_z = _pick_zoom(
            lat, image_extent_m,
            z_min=_JMA_ZOOM_MIN, z_max=_JMA_ZOOM_MAX,
            max_tiles_per_side=_MAX_TILES_PER_SIDE,
        )
        ovl_cx, ovl_cy = _global_pixel(lat, lon, ovl_z)
        ovl_window_px = image_extent_m / _mpp(lat, ovl_z)
        ovl_tx0, ovl_ty0, ovl_tx1, ovl_ty1 = _tile_range(
            ovl_cx, ovl_cy, ovl_window_px,
        )

        session = async_get_clientsession(self.hass)

        base_tiles = await _fetch_grid(
            session,
            url_fn=lambda z, x, y: GSI_PALE_TILE_URL.format(z=z, x=x, y=y),
            cache=_GSI_CACHE,
            cache_key=lambda z, x, y: (z, x, y),
            zoom=base_z,
            tx0=base_tx0, ty0=base_ty0, tx1=base_tx1, ty1=base_ty1,
        )

        basetime  = coord.latest_observation_basetime
        validtime = coord.latest_observation_validtime
        overlay_tiles: dict | None = None
        if basetime and validtime:
            overlay_tiles = await _fetch_grid(
                session,
                url_fn=lambda z, x, y: JMA_TILE_URL.format(
                    basetime=basetime, validtime=validtime, z=z, x=x, y=y,
                ),
                cache=_JMA_CACHE,
                cache_key=lambda z, x, y: (basetime, validtime, z, x, y),
                zoom=ovl_z,
                tx0=ovl_tx0, ty0=ovl_ty0, tx1=ovl_tx1, ty1=ovl_ty1,
            )
            _evict_old_jma_entries(basetime, validtime)

        return await self.hass.async_add_executor_job(
            _render,
            base_tiles,
            base_tx0, base_ty0, base_tx1, base_ty1,
            base_cx, base_cy, base_window_px,
            overlay_tiles,
            ovl_tx0, ovl_ty0, ovl_tx1, ovl_ty1,
            ovl_cx, ovl_cy, ovl_window_px,
            out_px,
            TILE_CAMERA_OVERLAY_ALPHA,
            circle_radius_px,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        coord = self.coordinator
        return {
            "scale":                    self._scale,
            "circle_fraction_of_width": f"1/{self._scale}",
            "image_extent_m":           2 * self._scale * coord.radius_meters,
            "image_resolution_px":      TILE_CAMERA_OUTPUT_PX,
            "observed_at": (
                coord.latest_observation_at.isoformat()
                if coord.latest_observation_at else None
            ),
            "center_lat":               coord.lat,
            "center_lon":               coord.lon,
            "radius_m":                 coord.radius_meters,
            "attribution":              "JMA / 国土地理院",
        }
