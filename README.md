# JMA Nowcast 降水予測 for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![HA Version](https://img.shields.io/badge/HA-2024.1%2B-blue)](https://www.home-assistant.io/)

気象庁の **高解像度降水ナウキャスト** を使って、10〜60分後の降水を予測し Home Assistant に通知するカスタムインテグレーションです。

## 機能

- 🌧️ **最大60分先**の降水を予測（10/20/30/60分後 を個別ON/OFF）
- 🗺️ **地図で監視位置と半径を設定**（マーカー＋半径円のドラッグ）。HA ホームへのワンクリックリセットも可
- 🎯 **発報カバレッジ** 5 段階（1ピクセルでも / 25% / 50% / 75% / 100%）
- 🕐 **発報クールダウン** — 空振り後・降雨後それぞれ独立に待ち時間を設定可能
- 👁️ **降雨実況** を JMA N1 タイルから取得し記録（HA recorder で履歴化）
- 🖼️ **監視範囲タイル** camera エンティティ — Dashboard に貼って雨雲と自分の半径円を視覚的に確認
- ⚙️ **UIから全設定変更**可能（YAML編集不要）
- 🔔 `binary_sensor` の変化をトリガーにした**自動化**で通知連携
- 🔄 **手動更新ボタン**でいつでも即時確認

## エンティティ一覧

| エンティティ | 種別 | 説明 |
|---|---|---|
| `binary_sensor.jma_nowcast_rain_detected` | Binary Sensor | **降水アラート** (ON/OFF) — 状態機械が管理（v1.2 以降。詳細は下記） |
| `binary_sensor.jma_nowcast_rain_observed` | Binary Sensor | **降雨実況** (ON/OFF) — 今その場所で雨が降っているか (JMA N1 タイル由来) |
| `sensor.jma_nowcast_alert_state` | Sensor (enum) | 状態機械の現在値: `ready` / `alerted` / `raining` / `post_rain_wait` |
| `sensor.jma_nowcast_first_rain_minutes` | Sensor | 最初に雨が来るまでの分数 |
| `sensor.jma_nowcast_summary` | Sensor | 予報サマリー文字列 |
| `sensor.jma_nowcast_10min` | Sensor | 10分後の予測降水量 (mm/h) |
| `sensor.jma_nowcast_20min` | Sensor | 20分後の予測降水量 (mm/h) |
| `sensor.jma_nowcast_30min` | Sensor | 30分後の予測降水量 (mm/h) |
| `sensor.jma_nowcast_60min` | Sensor | 60分後の予測降水量 (mm/h) |
| `button.jma_nowcast_refresh` | Button | 今すぐ確認（手動更新） |
| `camera.jma_nowcast_tile` | Camera | 最新 JMA タイル + 半径円・ピクセル格子のオーバーレイ画像。Dashboard の Picture Entity カードに貼ると監視範囲を視覚化できる |

## インストール

### HACS（推奨）

1. HACS を開く → **カスタムリポジトリ** → このリポジトリの URL を追加（カテゴリ: Integration）
2. 「JMA Nowcast 降水予測」をインストール
3. HA を再起動

### 手動インストール

1. `custom_components/jma_nowcast/` をまるごと `/config/custom_components/` にコピー
2. HA を再起動

## セットアップ

1. **設定 → デバイスとサービス → 統合を追加** → 「JMA Nowcast」を検索
2. 地図上で監視位置（マーカー）と半径（円の縁）を調整 — 初期値は HA ホーム位置・半径 1km
3. 監視する分後・閾値・カバレッジ・更新間隔を確認して送信
4. セットアップ後、**「設定」ボタン**から再調整できます。`HA ホームにリセット` を ON で保存すると位置と半径を初期値に戻せます

## Nest デバイスへの音声通知（自動化例）

```yaml
automation:
  - alias: "雨の接近を音声通知"
    trigger:
      - platform: state
        entity_id: binary_sensor.jma_nowcast_rain_detected
        from: "off"
        to: "on"
    action:
      - service: tts.google_translate_say
        target:
          entity_id:
            - media_player.nesthubmax
            - media_player.toire
        data:
          language: "ja"
          message: >
            {% set mins = state_attr('binary_sensor.jma_nowcast_rain_detected', 'first_rain_in_minutes') %}
            約 {{ mins }} 分後に雨が降る予測です。洗濯物や傘のご準備をお願いします。
```

## 設定項目

| 設定 | デフォルト (新規) | デフォルト (マイグレ) | 説明 |
|---|---|---|---|
| 監視位置と半径 | HA ホーム / 1000 m | (既存値) | 地図のマーカー位置と円の半径（メートル） |
| HA ホームにリセット | OFF | OFF | OptionsFlow のみ。ON のまま保存で初期値に戻る |
| 監視する分後 | 10, 20, 30 | (既存値) | チェックする予測時間帯（複数選択。最大60分） |
| 発報閾値 (mm/h) | 1.0 | (既存値) | この値以上で降水と判定 |
| 発報カバレッジ | 1ピクセルでも | (既存値) | `any` / `25%` / `50%` / `75%` / `100%` のいずれかを満たすと発報 |
| 空振りクールダウン (分) | **30** | **0** (旧挙動) | 発報後に雨が観測されなかった場合の待ち時間 |
| 降雨後クールダウン (分) | **60** | **0** (旧挙動) | 観測された雨が止んでから次の発報を許可するまでの待ち時間 |
| 更新間隔 (分) | 5 | 5 | センサー更新頻度（5分推奨） |

### カバレッジについて
半径円内のピクセルのうち、何 % が「閾値以上」の予測になったら降水ありとするかを選びます。
- `1ピクセルでも` — 雨雲のかすめ通りでも反応する最も敏感な設定
- `25% / 50% / 75%` — エリアの一定割合をカバーしたら発報
- `100%` — 円全域で予測されたときだけ発報（誤発報を最も抑える）

### 発報ステートマシン (v1.2 以降)

`binary_sensor.jma_nowcast_rain_detected` は単純な「予測 ON/OFF」ではなく、
以下の状態機械によって ON/OFF が決まります。クールダウンを 0 にすれば
ほぼ旧 v1.1 と等価な挙動になります。

```
READY (alert OFF / 発報可能)
  └─ 予測で発報条件成立 → ALERTED (alert ON)
ALERTED (alert ON / 発報中・実況待ち)
  ├─ 実況で雨を観測 → RAINING (alert ON 継続)
  └─ 空振りクールダウン経過まで雨なし → READY (空振り終了)
RAINING (alert ON / 降雨中)
  └─ 実況で雨が止む → POST_RAIN_WAIT (alert OFF)
POST_RAIN_WAIT (alert OFF / 降雨後待機)
  ├─ 再び雨を観測 → RAINING (alert 再 ON)
  └─ 降雨後クールダウン経過 → READY
```

`sensor.jma_nowcast_alert_state` で現在の状態を確認できます。
attributes に `last_alert_at` / `last_rain_observed_at` / `rain_ended_at` などのタイムスタンプも入っています。

## 監視範囲タイル (camera) を Dashboard に表示する

`camera.jma_nowcast_tile` は最新の JMA 観測タイル (250m メッシュ) に
監視範囲の半径円とピクセル格子線を重ねた PNG を返します。Picture Entity
カードに貼ると、自分の監視範囲を視覚化できます。

```yaml
type: picture-entity
entity: camera.jma_nowcast_tile
camera_view: live
show_state: false
show_name: false
```

## 必要要件

- Home Assistant 2024.1 以上
- Python パッケージ: `Pillow`（HA が自動インストール）

## データソース

- [気象庁 高解像度降水ナウキャスト](https://www.jma.go.jp/bosai/nowc/)
- 250mメッシュ、最大60分先まで5分刻みで予測

## ライセンス

MIT License
