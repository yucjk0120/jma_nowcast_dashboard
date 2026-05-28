"""Constants for JMA Nowcast integration."""

DOMAIN = "jma_nowcast"

# ── Config/Options keys ───────────────────────────────────────────────────
# 保存される ConfigEntry のキー
CONF_LATITUDE              = "latitude"
CONF_LONGITUDE             = "longitude"
CONF_RADIUS_METERS         = "radius_meters"
CONF_FORECAST_MINUTES      = "forecast_minutes"
CONF_THRESHOLD_MM          = "threshold_mm"
CONF_TRIGGER_COVERAGE      = "trigger_coverage"
CONF_NO_RAIN_COOLDOWN_MIN  = "no_rain_cooldown_min"
CONF_POST_RAIN_COOLDOWN_MIN = "post_rain_cooldown_min"
CONF_SCAN_INTERVAL         = "scan_interval"

# フォーム専用キー（保存はされない）
CONF_LOCATION         = "location"        # LocationSelector の返却 dict
CONF_RESET_TO_HOME    = "reset_to_home"   # ボタン代わりのチェックボックス

# ── Legacy keys (v1 → v2 マイグレーション用) ─────────────────────────────
CONF_USE_HA_HOME      = "use_ha_home"     # v1 で使用、v2 で廃止
CONF_RADIUS_PIXELS    = "radius_pixels"   # v1 で使用、v2 で radius_meters に置換

# ── Defaults ──────────────────────────────────────────────────────────────
DEFAULT_RADIUS_METERS         = 1000  # 1 km（zoom=10 で約 8px@lat35°）
DEFAULT_FORECAST_MINUTES      = [10, 20, 30]
DEFAULT_THRESHOLD_MM          = 1.0
DEFAULT_TRIGGER_COVERAGE      = "any"
DEFAULT_NO_RAIN_COOLDOWN_MIN  = 30   # 新規セットアップ時のデフォルト
DEFAULT_POST_RAIN_COOLDOWN_MIN = 60  # 新規セットアップ時のデフォルト
DEFAULT_SCAN_INTERVAL         = 5    # minutes
# v2→v3 マイグレーション時のクールダウン値（旧挙動を維持するため 0）
MIGRATION_NO_RAIN_COOLDOWN_MIN  = 0
MIGRATION_POST_RAIN_COOLDOWN_MIN = 0

# ── 範囲制約 ──────────────────────────────────────────────────────────────
MIN_RADIUS_METERS = 100      # 100 m
MAX_RADIUS_METERS = 20000    # 20 km
MIN_COOLDOWN_MIN  = 0
MAX_COOLDOWN_MIN  = 240      # 4 h

# ── Tile / 列挙 ───────────────────────────────────────────────────────────
ZOOM = 10
ALL_FORECAST_MINUTES = [10, 20, 30, 60]

# ── カバレッジプリセット ──────────────────────────────────────────────────
# 「半径内のうち何 % のピクセルが閾値超えで発報するか」
COVERAGE_ANY           = "any"
COVERAGE_QUARTER       = "quarter"
COVERAGE_HALF          = "half"
COVERAGE_THREE_QUARTER = "three_quarter"
COVERAGE_ALL           = "all"

ALL_COVERAGE_OPTIONS = [
    COVERAGE_ANY,
    COVERAGE_QUARTER,
    COVERAGE_HALF,
    COVERAGE_THREE_QUARTER,
    COVERAGE_ALL,
]

# ── 発報ステートマシン ────────────────────────────────────────────────────
ALERT_STATE_READY            = "ready"             # alert OFF / 発報可能
ALERT_STATE_ALERTED          = "alerted"           # alert ON / 予測で発報・実況待ち
ALERT_STATE_RAINING          = "raining"           # alert ON / 実況で降雨中
ALERT_STATE_POST_RAIN_WAIT   = "post_rain_wait"    # alert OFF / 降雨後クールダウン

ALL_ALERT_STATES = [
    ALERT_STATE_READY,
    ALERT_STATE_ALERTED,
    ALERT_STATE_RAINING,
    ALERT_STATE_POST_RAIN_WAIT,
]

# プリセット → 必要なカバレッジ比率（wet_pixels / total_pixels の閾値）
# any は「1 ピクセルでも超えていれば」なので別扱い（コード側で wet > 0 で判定）
COVERAGE_RATIOS = {
    COVERAGE_ANY:           0.0,   # 特殊扱い: wet > 0
    COVERAGE_QUARTER:       0.25,
    COVERAGE_HALF:          0.50,
    COVERAGE_THREE_QUARTER: 0.75,
    COVERAGE_ALL:           1.00,
}

# ── Base map (GSI / 国土地理院) ──────────────────────────────────────────
# 監視範囲タイル camera で JMA オーバーレイの下に敷くベースマップ。
# 利用規約: https://maps.gsi.go.jp/development/ichiran.html (出典明記必要)
GSI_PALE_TILE_URL = "https://cyberjapandata.gsi.go.jp/xyz/pale/{z}/{x}/{y}.png"
GSI_MAX_ZOOM = 18
# 取得済みタイルのディスクキャッシュ位置 (hass.config.path 起点)。
# GSI 淡色は実質不変なので、HA 再起動を跨いで永続化する。
# ユーザーがクリアしたければ /config 配下のこのディレクトリを削除すればよい。
GSI_PALE_CACHE_SUBDIR = "jma_nowcast_cache/gsi_pale"

# ── 監視範囲タイル camera ────────────────────────────────────────────────
# 各カメラエンティティで「監視範囲の円が画像幅の 1/R になる」R の一覧。
# R が大きいほど広域 (ズームアウト) になる。
TILE_CAMERA_SCALES: list[int] = [4, 8, 16, 32]
# 出力 PNG の一辺 (px)。1024 = 2^10 で 4/8/16/32 全てで割り切れ、
# 半径円の画素数が小数にならない (128/64/32/16 px)。
# 2048 や 3000 だと PIL 合成 + PNG エンコード + HA フロントエンド転送が
# 体感で重かったので、Picture カード表示として十分な 1024 に下げた。
TILE_CAMERA_OUTPUT_PX = 1024
# JMA オーバーレイ画像の不透明度 (0=透明 / 255=不透明)。
# 既定 160 ≒ 63% でベースマップの地物と雨雲の両方が読める。
TILE_CAMERA_OVERLAY_ALPHA = 160

# ── JMA Nowcast API ───────────────────────────────────────────────────────
# N2: 予報時刻リスト（basetime + 5〜60分先の validtime）。発報判定に使う。
# N1: 実況時刻リスト（basetime==validtime）。「降雨実績」判定に使う。
JMA_TARGET_TIMES_URL = (
    "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N2.json"
)
JMA_OBSERVATION_TARGET_URL = (
    "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"
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
