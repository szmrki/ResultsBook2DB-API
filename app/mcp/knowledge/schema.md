# rb2db スキーマ解説

カーリング国際公式大会の実試合データ。2系統のDBがある。

- `md`   : ミックスダブルス（2人制）
- `four` : 4人制（Men / Women / Junior Men / Junior Women）

両DBは同一の8テーブル構成。リレーションは以下（すべて `ON DELETE CASCADE`）。

```
events  →  games  →  ends  →  shots  →  stones
   │              ↑
   │            lsds（game 単位）
   ├──  standings（event 単位）
   └──  rosters   （event 単位）
```

- `events`（大会）→ `games`（試合）→ `ends`（エンド）→ `shots`（投球）→ `stones`（ストーン座標）
- `lsds`（Last Stone Draw）は `games` 配下
- `standings` 大会順位 と `rosters` 出場選手 は `events` 直下。`games` を経由しない

---

## events テーブル（大会・最上位）

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER | 大会ID（PK） |
| name | STRING | 大会コード（例: WMDCC2023）、UNIQUE |
| year | INTEGER | 開催年 |
| category | STRING | カテゴリ（MD / Men / Women / Junior Men / Junior Women） |
| location | STRING | 開催地。例 Aberdeen, Scotland。NULL あり |
| venue | STRING | 会場名。例 Curl Aberdeen。NULL あり |

## games テーブル（試合）

`team_red` / `team_yellow` はストーンの色に対応する。

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER | 試合ID（PK） |
| event_id | INTEGER | 所属大会ID（FK → events.id） |
| page | INTEGER | ソース元スコアシートのページ番号 |
| team_red | STRING | レッド側チーム名（例: JPN - Japan） |
| team_yellow | STRING | イエロー側チーム名 |
| final_score_red | INTEGER | レッド側最終スコア |
| final_score_yellow | INTEGER | イエロー側最終スコア |

## ends テーブル（エンド）

通常1試合8〜10エンド。延長は既存データで最大12エンド。

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER | エンドID（PK） |
| game_id | INTEGER | 所属試合ID（FK → games.id） |
| page | INTEGER | ソース元ページ番号 |
| number | INTEGER | エンド番号（1〜12） |
| color_hammer | STRING | ハンマー保持チームのストーン色（red / yellow） |
| score_red | INTEGER | そのエンドのレッド得点 |
| score_yellow | INTEGER | そのエンドのイエロー得点 |
| is_power_play | INTEGER | パワープレイフラグ 1=ON, 0=OFF（**md のみ。four では NULL**） |

## shots テーブル（投球）

1エンドにつき最大16投。

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER | 投球ID（PK） |
| end_id | INTEGER | 所属エンドID（FK → ends.id） |
| number | INTEGER | 投球番号（1〜16） |
| color | STRING | 投球チームのストーン色（red / yellow） |
| team | STRING | チーム名（略称） |
| player_name | STRING | 投球選手名（NULL あり） |
| type | STRING | ショットタイプ（下記。NULL あり） |
| turn | STRING | ターン方向（cw=時計回り / ccw=反時計回り） |
| percent_score | INTEGER | 成功率スコア（0/25/50/75/100 の離散値） |

**ショットタイプ（`type` の全14値）**


| type 値 | 説明 | four | md |
|---|---|---:|---:|
| Draw | ハウス内に止めるショット | 91,607 | 30,126 |
| Take-out | 相手ストーンを弾き出すショット | 50,797 | 4,325 |
| Front | ハウス手前付近に止めるショット。ガード | 27,749 | 475 |
| Hit and Roll | 当てた後にシューターを転がして止めたい位置に止める | 21,545 | 2,304 |
| Double Take-out | 相手ストーン2個を同時にテイクアウト | 21,092 | 4,594 |
| Clearing | クリアリング | 20,896 | 2,019 |
| Guard | ガード（ハウス手前に置くショット） | 17,344 | 4,138 |
| Raise | 味方ストーンを押し込むショット | 11,176 | 7,343 |
| Promotion Take-out | 味方ストーンを押してテイクアウト | 8,828 | 2,561 |
| Wick / Soft Peeling | ストーンをかすらせてずらすショット | 2,050 | 979 |
| Freeze | 相手ストーンの直前に止めるショット | 346 | 226 |
| Through | 意図的にスルーするショット。ショットスコアが定義されない | 838 | 237 |
| no statistics | 統計対象外 | 14 | 2 |
| not played | 投球なし | 0 | 1 |

件数は 2026-09-05 時点の実測。
`Through` / `no statistics` は成功率が定義できず `percent_score` が NULL になる

## stones テーブル（ストーン座標）

各投球後のシート上に残る全ストーンの座標。1投球につき最大16レコード。
座標系は DigitalCurling3 のメートル座標系（詳細は rb2db://sql-notes の「座標系」を参照）。

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER | ストーンID（PK） |
| shot_id | INTEGER | 対応投球ID（FK → shots.id） |
| color | STRING | ストーンの色（red / yellow） |
| x | FLOAT | 横方向座標（約 -2.24〜+2.26 m） |
| y | FLOAT | 縦方向座標（約 31.97〜40.51 m） |
| distance_from_center | FLOAT | ハウス中心からの距離（メートル） |
| inhouse | INTEGER | ハウス内フラグ（1=内, 0=外） |
| insheet | INTEGER | シート内フラグ（1=内, 0=外） |
| shot_order | INTEGER | そのストーンが何投目由来か　|

## lsds テーブル（Last Stone Draw）

試合前のハンマー権決定投球。ティーへの最接近距離を記録。

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER | LSD ID（PK） |
| game_id | INTEGER | 対応試合ID（FK → games.id） |
| team | STRING | チーム名 |
| player_name | STRING | 投球選手名（↻ 記号でターン方向を表す場合あり） |
| distance_cm | FLOAT | ティーからの距離（cm、範囲 0.1〜199.6） |

## standings テーブル（大会順位）

大会ごとの最終順位表。`events` 直下で `games` を経由しない。md / four 同一スキーマ。
1大会につき参加チーム数ぶんの行を持つ。`rank` は同一大会内で重複しうる。

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER | 順位ID（PK） |
| event_id | INTEGER | 所属大会ID（FK → events.id） |
| rank | INTEGER | 順位。1〜 |
| team | STRING | チーム名。国コード略称、例 SCO |

## rosters テーブル（出場選手）

大会ごとの出場メンバー。`events` 直下。role が player か coach かを持つ。
md / four でカラム構成が異なり、片方のみ保持で他方は NULL。

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER | ロスターID（PK） |
| event_id | INTEGER | 所属大会ID（FK → events.id） |
| team | STRING | チーム名。国コード略称、例 SCO |
| player_name | STRING | 選手・コーチ名。例 MOUAT Bruce |
| role | STRING | 役割。player / coach |
| position | INTEGER | ポジション番号 1〜5。four のみ、coach と md は NULL |
| is_skip | INTEGER | スキップフラグ 1/0。four のみ、md は NULL |
| is_vice | INTEGER | バイススキップフラグ 1/0。four のみ、md は NULL |
| gender | STRING | 性別 Male / Female。md のみ、coach と four は NULL |

---

## md / four の差異まとめ

| 項目 | md | four |
|---|---|---|
| カテゴリ | MD のみ | Men / Women / Junior Men / Junior Women |
| ends.is_power_play | あり | NULL |
| stones.shot_order | あり。未対応の大会のみ NULL | あり。未対応の大会のみ NULL |
| rosters.gender | あり | NULL |
| rosters.position / is_skip / is_vice | NULL | あり |
| shots データ充実度 | 大会により NULL 多し | ほぼ全投球に type・選手名あり |
| 収録規模 | 13大会 / 1,419試合 / 座標約41.8万行 | 42大会 / 2,241試合 / 座標約115万行 |
