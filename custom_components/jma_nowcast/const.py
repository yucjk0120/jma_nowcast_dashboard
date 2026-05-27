"""Constants for JMA Nowcast integration."""

DOMAIN = "jma_nowcast"

# Config/Options keys
CONF_USE_HA_HOME      = "use_ha_home"
CONF_LATITUDE         = "latitude"
CONF_LONGITUDE        = "longitude"
CONF_FORECAST_MINUTES = "forecast_minutes"
CONF_THRESHOLD_MM     = "threshold_mm"
CONF_RADIUS_PIXELS    = "radius_pixels"
CONF_SCAN_INTERVAL    = "scan_interval"

# Defaults
DEFAULT_USE_HA_HOME      = True
DEFAULT_FORECAST_MINUTES = [10, 20, 30]
DEFAULT_THRESHOLD_MM     = 1.0
DEFAULT_RADIUS_PIXELS    = 3
DEFAULT_SCAN_INTERVAL    = 5   # minutes

ZOOM = 10
ALL_FORECAST_MINUTES = [10, 20, 30, 60]

# JMA Nowcast API
# targetTimes_N2.json: 予報時刻リスト（basetime + 5〜60分先の validtime）
# N1 は basetime==validtime（実況のみ）なので、本インテグレーションでは使用しない。
JMA_TARGET_TIMES_URL = (
    "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N2.json"
)
# basetime と validtime の間の "none" は member パラメータ（アンサンブル無し）
JMA_TILE_URL = (
    "https://www.jma.go.jp/bosai/jmatile/data/nowc"
    "/{basetime}/none/{validtime}/surf/hrpns/{z}/{x}/{y}.png"
)

# JMA HRPNS color palette (RGB → mm/h) — 2026-05 実タイルから検証済み
JMA_PALETTE: list[tuple[tuple[int, int, int], float]] = [
    ((255, 255, 255),  0.0),
    ((242, 242, 255),  0.0),
    ((160, 210, 255),  0.5),
    (( 33, 140, 255),  1.0),
    ((  0,  65, 255),  5.0),
    ((  0, 200,  50), 10.0),
    ((  0, 130,  30), 20.0),
    ((250, 245,   0), 30.0),
    ((255, 153,   0), 50.0),
    ((255,  40,   0), 80.0),
    ((180,   0, 104), 99.9),
]
