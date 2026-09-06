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
# 監視範囲タイル camera に JMA ピクセル格子をオーバーレイ描画するかどうか
CONF_SHOW_GRID             = "show_grid"

# ── Alert Audio (TTS) 設定 ────────────────────────────────────────────────
# 発報時に TTS で読み上げる音声通知の設定。バケットごとに有効/メッセージを
# 別々に指定できる。tts_entity と targets (media_player) は全バケット共通。
CONF_ALERT_TTS_ENTITY      = "alert_tts_entity"
CONF_ALERT_TARGETS         = "alert_targets"
CONF_ALERT_10_ENABLED      = "alert_10_enabled"
CONF_ALERT_10_MESSAGE      = "alert_10_message"
CONF_ALERT_20_ENABLED      = "alert_20_enabled"
CONF_ALERT_20_MESSAGE      = "alert_20_message"
CONF_ALERT_30_ENABLED      = "alert_30_enabled"
CONF_ALERT_30_MESSAGE      = "alert_30_message"
CONF_ALERT_60_ENABLED      = "alert_60_enabled"
CONF_ALERT_60_MESSAGE      = "alert_60_message"

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
DEFAULT_SHOW_GRID             = False
# Alert audio デフォルト。バケットごとに文言を分ける。
# テンプレートには次の 2 記法を使える (自動判定):
#   単純置換 (str.format_map): {mm} など単一波かっこ
#   Jinja2 (HA 標準):          {{mm}} や {% if rain_60 %}...{% endif %}
# 提供される変数 (Jinja/format_map 両対応):
#   minutes           ─ このバケットの分数 (10/20/30/60)
#   mm                ─ このバケットの予想 mm/h (範囲内最大値、float)
#   mm_10 mm_20 mm_30 mm_60 ─ 各バケットの予想 mm/h (float, 未計測=0.0)
#   rain_10 rain_20 rain_30 rain_60 ─ 各バケットに雨あり判定 (bool)
#   first_min         ─ first_rain_in_minutes (int)
#   observed_mm       ─ 現在の実況降水量 (float)
#   stops_at          ─ first_min 以降で最初に雨が止むバケット (int|None)
#   still_raining_60  ─ 60 分後も雨が続くか (bool、= rain_60)
#   test              ─ テスト再生かどうか (bool)
DEFAULT_ALERT_TTS_ENTITY      = ""       # 空 = 未設定 (発報しない)
DEFAULT_ALERT_TARGETS: list[str] = []    # 空 = 未設定 (発報しない)
DEFAULT_ALERT_10_ENABLED      = False
DEFAULT_ALERT_10_MESSAGE      = "約10分後に{mm}ミリ毎時の雨が降る予想です。"
DEFAULT_ALERT_20_ENABLED      = False
DEFAULT_ALERT_20_MESSAGE      = "約20分後に{mm}ミリ毎時の雨が降る予想です。"
DEFAULT_ALERT_30_ENABLED      = False
DEFAULT_ALERT_30_MESSAGE      = "約30分後に{mm}ミリ毎時の雨が降る予想です。"
DEFAULT_ALERT_60_ENABLED      = False
DEFAULT_ALERT_60_MESSAGE      = "約60分後に{mm}ミリ毎時の雨が降る予想です。"
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

# JMA HRPNS color palette (RGB → mm/h)
# 各色バンドの「上限 (max) 値」で表現する規約:
#   例) 薄水色 (0.1〜1 mm/h 帯) → 1.0 mm/h として扱う
#       水色    (1〜5 mm/h 帯)  → 5.0 mm/h
#       ...
#       紫      (80 mm/h 以上)  → 80.0+ (上限なし)
# 検証済み (2026-05): (160,210,255) 以降の値は実タイルで確認。
# 補足 (2026-09):
#   - RGB(255,255,255) は JMA タイルで alpha=0 (完全透明) として現れ
#     "雨なし領域" を意味する (analyzer 側で alpha<50 は skip)。
#   - RGB(242,242,255) は alpha=255 の不透明色で「意図的に描画された
#     弱雨マーカー」。従来 0.0 にしていたが、camera 画像で薄水色が
#     見えるのに sensor が 0 になり誤解を招くため、
#     JMA HRPNS レジェンドの 0.1〜1 mm/h 帯として **上限 1.0** に修正。
JMA_PALETTE: list[tuple[tuple[int, int, int], float]] = [
    # 透明 (雨なし) — analyzer は alpha<50 で skip するので実質使われない
    ((255, 255, 255),   0.0),
    # 0.1〜1 mm/h band → 上限 1.0
    ((242, 242, 255),   1.0),
    # 1〜5 mm/h band → 上限 5.0
    ((160, 210, 255),   5.0),
    # 5〜10 mm/h band → 上限 10.0
    (( 33, 140, 255),  10.0),
    # 10〜20 mm/h band → 上限 20.0
    ((  0,  65, 255),  20.0),
    # 20〜30 mm/h band 前半 (extra 中間色) → 25.0
    ((  0, 200,  50),  25.0),
    # 20〜30 mm/h band 後半 → 上限 30.0
    ((  0, 130,  30),  30.0),
    # 30〜50 mm/h band → 上限 50.0
    ((250, 245,   0),  50.0),
    # 50〜80 mm/h band → 上限 80.0
    ((255, 153,   0),  80.0),
    # 80 mm/h以上 (extra) → 90 として区別 (次の紫との中間段階)
    ((255,  40,   0),  90.0),
    # 80 mm/h以上 (最上位・紫) → 上限なしのため 99.9 を代表値に
    ((180,   0, 104),  99.9),
]
