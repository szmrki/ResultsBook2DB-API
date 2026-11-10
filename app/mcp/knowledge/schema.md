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
| start_date | STRING | 開始日（`YYYY-MM-DD`）。最初の試合の日付 |
| end_date | STRING | 終了日（`YYYY-MM-DD`）。最後の試合の日付 |
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
| date | STRING | 試合日（`YYYY-MM-DD`） |
| start_time | STRING | 開始時刻（`HH:MM`、開催地の現地時刻） |
| stage_type | STRING | ステージの分類。round_robin / playoff / relegation / other |
| stage | STRING | ステージ名。Results Book の表記のまま（例: Round Robin Session 1、Semi-final） |
| group_name | STRING | グループ名（例: A）。グループ分けの無い大会は NULL |
| sheet | STRING | シート名（例: A）。NULL あり |
| team_red | STRING | レッド側チーム名（例: JPN - Japan） |
| team_yellow | STRING | イエロー側チーム名 |
| final_score_red | INTEGER | レッド側最終スコア |
| final_score_yellow | INTEGER | イエロー側最終スコア |

`stage` は表記ゆれがある（`Semi-final` / `SEMIFINAL` / `Semifinal` など）。
予選と決勝トーナメントを分けて集計するときは `stage_type` を使う。

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

1エンドにつき four は最大16投、md は最大10投。
md では加えて、エンド開始時の事前配置ストーンを表す `number = 0` の行が付く。

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER | 投球ID（PK） |
| end_id | INTEGER | 所属エンドID（FK → ends.id） |
| number | INTEGER | 投球番号（four: 1〜16 / md: 1〜10）。md の `0` は事前配置ストーン（下記） |
| color | STRING | 投球チームのストーン色（red / yellow） |
| team | STRING | チーム名（略称） |
| player_name | STRING | 投球選手名（NULL あり） |
| type | STRING | ショットタイプ（下記。NULL あり） |
| turn | STRING | ターン方向（cw=時計回り / ccw=反時計回り） |
| percent_score | INTEGER | 成功率スコア（0/25/50/75/100 の離散値） |
| notes | STRING | 投球の注記（例: Time-out、Measurement、Free Guard Zone violation）。注記の無い投球は NULL |

`notes` が付くのは全投球の約2%（four 9,883投 / md 2,095投）。
1投に複数の注記が付くと、区切りが `; ` のことも空白だけのこともある。

**`number = 0`: 事前配置ストーン（md のみ）**

MD では各エンドの開始時に、両チームのストーンが1個ずつ盤面に置かれる
（ハンマー側がハウス内、非ハンマー側がガード）。
md ではこの「1投目より前の盤面」を、`number = 0` の行として `shots` に持つ。

- 投球ではないので、`color` / `team` / `player_name` / `type` / `turn` / `percent_score` は**すべて NULL**
- 紐づく `stones` は事前配置ストーンの2行で、`shot_order = 0`
- **投球数を数えるときは `number >= 1` で絞ること**

**ショットタイプ（`type` の全14値）**

`type` は大会のショット記録員が1投ずつ手入力したもの。以下の定義は World Curling と CURLIT による
記録員向け研修資料（*Curling Statistics: How to score*, 2026-27 シーズン版）に基づく。
過去シーズンの記録基準がこれと同じだったとは限らない。

*大原則: `type` は「結果」ではなく「狙い」*

記録員は投球の**結果ではなく意図**を入力する。意図は、スキップの指示・スイープ・投球後の選手の反応から記録員が判断する。

- Front を狙ったストーンがハウスに入ってしまった場合は「Draw の成功」ではなく、**「Front の失敗」**として記録される。
- 同じ「ストーンが1個出てシューターが残った」結果でも、どこに残すかを狙っていれば Hit and Roll、狙っていなければ Take-out になる。

そのため `type` だけから盤面の結果は決まらない。結果を見たいときは `stones` の座標と合わせて扱う。
また、この「意図」は記録員から見た客観的な視点を基に選択されるため、**スキップの真の考え**と必ずしも適合しているとは限らない。

*各タイプの定義*

| type 値 | 定義 | 成功とされる状態 |
|---|---|---|
| `Draw` | ハウス内に止める。他のストーンを動かす必要はない（軽く触れるのは可）。カムアラウンドも Draw | ハウス内の狙った位置に止まる |
| `Front` | ハウス手前のガードゾーンに置くストーン。センターガードもコーナーガードも Front | ホグラインを十分越えたハウス手前。ノーティックゾーン下でセンターラインに触れている（ルール上弾かれない）とより良い |
| `Guard` | **他のストーンを守る**位置に置く。ウェイトよりラインが重要 | 守りたいストーンとライン上にあり、近すぎない |
| `Raise` | 他のストーンを意図的に押して動かす（研修資料での名称は Raise / Tap Back）。押すストーンは**自分のストーンでも相手のストーンでもよい**。押したストーンは基本的にプレーに残る | 押したストーンが狙いの位置に収まる |
| `Wick / Soft Peeling` | 2つの用途をまとめたタイプ。**Wick（Split）**: 自分のストーン2個を狙いの位置に散らす。**Soft Peeling**: フリーガードゾーンのストーン（主に相手の Front）を横やハウス後方へ動かす（相手の Front をあえてハウス内に押し込むのも含む） | Wick は2個とも狙いの位置。Soft Peeling は相手のストーンが中央から外れる |
| `Freeze` | 他のストーンにぴったり付けて止める | 対象のストーンから数 cm 以内、ライン上 |
| `Take-out` | ストーンを弾き出し、**投げたストーンはプレーに残る**。止まる位置は問わない | 相手のストーンが出て、シューターが残る |
| `Hit and Roll` | 弾き出したうえで、投げたストーンを**狙いの位置**（ガードの裏、他のストーンの前など）まで転がす。盤面に他のストーンがない状態でハウス内に転がっただけなら Take-out 扱い | シューターが狙いの位置に止まる |
| `Clearing` | ストーンを弾き出し、**投げたストーンも外に出る**。ブランクエンドにするためのクリアや、ハウス手前のストーン2個以上の除去も含む | 対象のストーンとシューターが両方プレーから出る |
| `Double Take-out` | **同じ色のストーン**を2個以上弾き出す（ハウス内の2個、またはハウス手前1個とハウス内1個） | 相手のストーンが2個以上出る |
| `Promotion Take-out` | **局面上に配置された自チームのストーン**を押し当てて相手のストーンを出す（＝色の違うストーンが関わる）。色の違う複数のストーンに当てるショットも含む | 押された自分のストーンが狙いの位置に残る |
| `Through` | **意図的に**通過させる投球。戦術的なスルーのほか、盤面を改善しようがない場面でごく弱く投げたり、バンパーへ投げたりした場合も含む | 成功度・回転方向は記録されない |
| `no statistics` / `not played` | 研修資料には対応する項目がない。ごく少数 | 成功度は記録されない |

`Through` / `no statistics` / `not played` は `percent_score` が NULL になる（詳細は rb2db://sql-notes §4）。
スイーパーがストーンに触れた（Burned stone）、ゴミを拾った（Picked up debris）など、選手の責任でない理由で
評価対象外になった投球は、**`type` は狙いのまま残り**、`percent_score` だけが NULL になって `notes` に理由が入る。

*取り違えやすいペア*

| 迷いやすい組 | 見分け方 |
|---|---|
| Front ／ Guard | **守るストーンがあるか**。エンド序盤に、守るストーンなしでハウス手前に置くストーンは Front |
| Front ／ Draw | 狙いで決まる。序盤の1投目はどちらとも取れることがあり、記録員は選手の反応で判断する |
| Draw ／ Freeze | 近くに寄せるだけなら Draw。結果がきれいなフリーズでも、狙いが「近くに置く」なら Draw のまま |
| Take-out ／ Hit and Roll | **特定の位置に止める必要があるか**。少し転がって位置が変わる程度なら Take-out |
| Take-out ／ Clearing | **投げたストーンが残るべきか**。物理的に残せない配置や、ブランクにしたい場面なら Clearing |
| Double Take-out ／ Clearing | 主目的が「ハウス手前を開ける」なら、結果的に2個出ても Clearing。シューターと相手のストーン1個を同時に出すのも Clearing |
| Double Take-out ／ Promotion Take-out | 関わるストーンが**同じ色**なら Double、**自分のストーンを押して相手を出す**なら Promotion |
| Double Take-out ／ Hit and Roll | 相手のストーンの前に転がって止まるのが狙いなら、結果的に2個動いても Hit and Roll |


## stones テーブル（ストーン座標）

各投球後のシート上に残る全ストーンの座標。1投球につき最大16レコード。
md の `shots.number = 0` に紐づく行だけは、投球後ではなくエンド開始時（事前配置）の盤面を表す。
座標系は DigitalCurling3 のメートル座標系（詳細は rb2db://sql-notes の「座標系」を参照）。

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER | ストーンID（PK） |
| shot_id | INTEGER | 対応投球ID（FK → shots.id） |
| color | STRING | ストーンの色（red / yellow） |
| x | FLOAT | 横方向座標（約 -2.24〜+2.26 m） |
| y | FLOAT | 縦方向座標（約 31.97〜40.38 m） |
| distance_from_center | FLOAT | ハウス中心からの距離（メートル） |
| inhouse | INTEGER | ハウス内フラグ（1=内, 0=外） |
| insheet | INTEGER | シート内フラグ（1=内, 0=外） |
| shot_order | INTEGER | そのストーンが何投目由来か。md の `0` は事前配置ストーン |

## lsds テーブル（Last Stone Draw）

試合前のハンマー権決定投球。ティーへの最接近距離を記録。

| カラム | 型 | 説明 |
|---|---|---|
| id | INTEGER | LSD ID（PK） |
| game_id | INTEGER | 対応試合ID（FK → games.id） |
| team | STRING | チーム名 |
| player_name | STRING | 投球選手名 |
| distance_cm | FLOAT | ティーからの距離（cm、範囲 0〜199.6） |
| turn | STRING | 回転方向（cw / ccw）。各チームが1試合に cw・ccw を1投ずつ投げる |

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
| shots.number | 0〜10（`0` は事前配置ストーン） | 1〜16 |
| rosters.gender | あり | NULL |
| rosters.position / is_skip / is_vice | NULL | あり |
| shots データ充実度 | ほぼ全投球に type・選手名あり（`number = 0` の行を除く） | ほぼ全投球に type・選手名あり |
| 収録規模 | 14大会 / 1,452試合 / 座標約44.7万行 | 85大会 / 4,619試合 / 座標約236万行 |
