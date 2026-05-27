"""Camera platform for JMA Nowcast.

最新の JMA 観測タイル（N1）に
  - ピクセル格子線
  - 中心マーカー（監視位置）
  - 半径円
をオーバーレイした PNG を返す Camera エンティティ。
Dashboard の Picture / Picture Entity カードに配置すると、
自分の監視範囲が今どうなっているかが視覚的に分かる。
"""
from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image, ImageDraw

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import JmaNowcastCoordinator
from .entity import JmaNowcastEntity

# 描画サイズ（タイル 256px を整数倍に upscale）
_UPSCALE = 2
_OUT_SIZE = 256 * _UPSCALE

# オーバーレイ色（RGBA）
_GRID_COLOR        = (110, 110, 110, 90)
_RADIUS_COLOR      = (255, 0, 0, 220)
_CENTER_COLOR      = (255, 0, 0, 255)
_BG_FALLBACK_COLOR = (240, 240, 240, 255)


def _render_overlay(
    tile_bytes: bytes | None,
    center_px: int,
    center_py: int,
    radius_px: int,
) -> bytes:
    """タイル PNG + オーバーレイ を合成して PNG バイト列を返す。

    tile_bytes が None なら、薄灰の背景に注意文を描画して返す
    （初回起動直後や fetch 失敗時用）。
    """
    if tile_bytes is None:
        img = Image.new("RGBA", (_OUT_SIZE, _OUT_SIZE), _BG_FALLBACK_COLOR)
        draw = ImageDraw.Draw(img)
        draw.text((10, _OUT_SIZE // 2 - 8), "No tile yet", fill=(80, 80, 80, 255))
    else:
        src = Image.open(BytesIO(tile_bytes)).convert("RGBA")
        # nearest neighbor で 2 倍化（ピクセル境界がはっきりする）
        img = src.resize((_OUT_SIZE, _OUT_SIZE), Image.NEAREST)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # ── ピクセル格子線 ──（タイルの 1 px = _UPSCALE px に対応）
    for i in range(0, _OUT_SIZE + 1, _UPSCALE):
        draw.line([(i, 0), (i, _OUT_SIZE)], fill=_GRID_COLOR, width=1)
        draw.line([(0, i), (_OUT_SIZE, i)], fill=_GRID_COLOR, width=1)

    # ── 半径円 ──
    cx = center_px * _UPSCALE + _UPSCALE // 2
    cy = center_py * _UPSCALE + _UPSCALE // 2
    r  = radius_px * _UPSCALE
    if r > 0:
        # 太めの円（中→外で 2 ライン）
        for offset, w in ((0, 2), (1, 1)):
            draw.ellipse(
                [(cx - r - offset, cy - r - offset), (cx + r + offset, cy + r + offset)],
                outline=_RADIUS_COLOR, width=w,
            )

    # ── 中心マーカー（小さい十字 + 点）──
    arm = max(6, _UPSCALE * 3)
    draw.line([(cx - arm, cy), (cx + arm, cy)], fill=_CENTER_COLOR, width=2)
    draw.line([(cx, cy - arm), (cx, cy + arm)], fill=_CENTER_COLOR, width=2)
    draw.ellipse([(cx - 2, cy - 2), (cx + 2, cy + 2)], fill=_CENTER_COLOR)

    composed = Image.alpha_composite(img, overlay)
    out = BytesIO()
    composed.save(out, format="PNG")
    return out.getvalue()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: JmaNowcastCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([JmaNowcastTileCamera(coordinator, entry)])


class JmaNowcastTileCamera(JmaNowcastEntity, Camera):
    """JMA 観測タイル + 監視範囲オーバーレイを返す Camera。"""

    _attr_translation_key = "tile"
    _attr_icon = "mdi:map"
    _attr_should_poll = False
    _attr_brand = "JMA"
    _attr_model = "HRPNS tile"
    content_type = "image/png"

    def __init__(self, coordinator: JmaNowcastCoordinator, entry: ConfigEntry) -> None:
        Camera.__init__(self)
        JmaNowcastEntity.__init__(self, coordinator, entry)
        self._attr_unique_id = f"{entry.entry_id}_tile"

    async def async_added_to_hass(self) -> None:
        """coordinator の更新で画像を更新したことを HA に通知する。"""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_update)
        )

    def _handle_update(self) -> None:
        # 状態自体は変わらないが、camera image の差し替えタイミングを HA に通知。
        self.async_write_ha_state()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        coord = self.coordinator
        return await self.hass.async_add_executor_job(
            _render_overlay,
            coord.latest_observation_image,
            coord._px,
            coord._py,
            coord._radius_pixels,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        coord = self.coordinator
        return {
            "observed_at": (
                coord.latest_observation_at.isoformat()
                if coord.latest_observation_at else None
            ),
            "tile":         f"{coord._tile_x}/{coord._tile_y}",
            "center_px":    [coord._px, coord._py],
            "radius_px":    coord._radius_pixels,
            "radius_m":     coord.radius_meters,
        }
