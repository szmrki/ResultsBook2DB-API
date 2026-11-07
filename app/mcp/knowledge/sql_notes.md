# rb2db SQL 上の注意点

分析用SQLを書く際に、ラボ全員が同じ正しい前提を持つための注意点集。
記載の件数はすべて実データでの実測値（four・md とも 2026-11-06 版の DB）。

---

## 1. NULL 混入の罠（最重要）

`ends` の集計では、`score_red` / `score_yellow` が NULL の行が混ざる。
特に `CASE WHEN ... ELSE 0.0 END` は**常に非NULLを返す**ため、
本来除外すべき NULL 行が `AVG()` の分母に入り込み、値が歪む。

**`ends` を集計するときは常に明示的に NULL を除外すること。**

```sql
WHERE score_red IS NOT NULL AND score_yellow IS NOT NULL
```

### NULL の正体は「未実施エンド」

これはランダムな記録漏れではなく、**構造的な意味を持つ NULL**。
試合がコンシード（early concede）で終了し、そのエンドが実施されなかったことを表す。

md の実測（全 11,427 エンド中 822 件が NULL = 7.2%）:

| エンド番号 | NULL 率 |
|---|---|
| 1〜6 | ほぼ 0% |
| 7 | 16.1% |
| **8** | **48.0%** |

MD は8エンド制のため、終盤エンドに集中する。**大会による偏りはなく、全14大会に
3.8%〜9.2% で分布する**（コンシードはどの大会でも起きるため）。

→ 「エンドごとの平均得点」を出すとき、終盤エンドは**母数が実施分だけに減る**点に注意。
NULL を 0 点として扱うと「終盤は得点が少ない」という誤った結論になる。

---

## 2. `shot_order` の値（NULL・負値・0）

`stones.shot_order` は「そのストーンが何投目由来か」を表すが、**NULL と負値が混在する**。
md ではさらに、**`0` が事前配置ストーン**を表す（§9）。

実測:

| 状態 | four（全 2,361,194 行） | md（全 446,885 行） |
|---|---:|---:|
| NULL | 6,648 | 12,549 |
| **負値** | **1,444**（最小 -16） | **354**（最小 -10） |
| 0（事前配置ストーン） | 0 | 138,237 |
| 正常 | 2,353,102（1〜16） | 295,745（1〜10） |

**負値は異常値**であり、集計に含めてはならない。four では**大会による偏りはなく、NULL は全85大会に、負値は61大会に散る**
（特定大会が未対応なのではなく、パース時の記録漏れ由来）。

投げられたストーンだけを対象にするときは、次で絞る。

```sql
WHERE shot_order IS NOT NULL AND shot_order > 0
```

**md で盤面全体を扱うとき（ハウス内のストーンの数など）は、`shot_order = 0` の行も含める。**
事前配置ストーンも盤面上のストーンである。

`shot_order` が1以上のとき、奇数=先攻のストーン、偶数=後攻のストーンを表す。

---

## 3. 「投球直後の着弾点」の取り方

`stones` は**その投球後に盤面に残る全ストーン**（1投球につき最大16行）を持つ。
「N投目がどこに止まったか」を知りたい場合、盤面全体を集計すると意味が変わる。

**その投球で投げられたストーン＝着弾点**は、次の条件で1行に絞れる。

```sql
SELECT st.x, st.y, st.distance_from_center
FROM stones st
JOIN shots sh ON st.shot_id = sh.id
WHERE st.shot_order = sh.number   -- ★ このストーンが、今まさに投げられたストーン
  AND st.shot_order > 0            -- 異常値を除外（§2）
```

four の実測: 該当 489,308 行（平均 x=0.022, y=37.29, ハウス中心からの距離 1.614 m）。
md では該当 64,172 行。md の事前配置ストーン（`shots.number = 0`、§9）は
`shot_order > 0` の条件で外れるので、着弾点には含まれない。

**この条件を付け忘れると、盤面に残る他のストーンまで混ざり、着弾分布が大きく歪む。**

---

## 4. `percent_score` の扱い

`shots.percent_score` は **0/25/50/75/100 の離散値**。連続値ではないので、
平均を取る際は「5段階評価の平均」であることを意識する。

four の実測分布（全 578,682 投球）:

| 値 | 件数 | 割合 |
|---|---|---|
| NULL | 2,679 | 0.5% |
| 0 | 49,551 | 8.6% |
| 25 | 11,001 | 1.9% |
| 50 | 74,821 | 12.9% |
| 75 | 80,171 | 13.9% |
| **100** | **360,459** | **62.3%** |

**100%が62%を占める強い偏り**がある。単純平均は 80 前後に張り付くため、
チーム間比較では平均より**分布や「100%率」のほうが差が出やすい**。

### NULL の正体はショットタイプ

`percent_score` の NULL もランダムではなく、**成功率が定義できないショット**に対応する。

| type | 件数 | うち percent_score が NULL |
|---|---|---|
| `Through` | 2,223 | **2,209（99%）** |
| `no statistics` | 51 | **50（98%）** |
| `not played` | 12 | **12（100%）** |
| その他 | — | 計 408 件。各タイプに少数ずつ散る。うち 340 件は注記（§10）の付いた投球 |

`turn`（ターン方向）の NULL 1,139 件も、**1,099 件が `Through`、36 件が `no statistics`**、3 件が `not played`（残り1件は `type` も NULL）。
→ 成功率やターンを集計するときは `type NOT IN ('Through', 'no statistics')` で
除外するか、NULL 除外で足りる。

---

## 5. ブランクエンドの表現

ブランクエンド（どちらも得点しなかったエンド）は次で表現する。

```sql
score_red = 0 AND score_yellow = 0
```

**4人制ルール**: ブランクエンドが起こった場合次のエンドでも**ハンマー（後攻権）は交代しない**。 
**MD ルール**: ブランクエンドでも**ハンマー（後攻権）は交代する**。
ただし、エンド終了時の配置が両チーム同距離でNo1ストーンの色が決定できない倍に限り、次のエンドでもハンマーは引き継がれる。
MD のハンマー推移を追う集計ではこの違いに注意。

---

## 6. 結合による行重複

`stones` は1投球につき最大16行ある最大テーブル（four で約236万行、md で約44.7万行）。
上位テーブルと JOIN すると行が急増しうる。集計前に粒度（1行が何を表すか）を意識する。

階層は `events` → `games` → `ends` → `shots` → `stones`。
`stones` から `events` まで遡るには3段の JOIN が必要。

---

## 7. 座標系

`stones` の座標系は DigitalCurling3 のメートル座標系。シートのセンターラインを原点とする。
（単位はメートル。以前フィートと誤記されていたが、値はメートルとして解釈すること。）

- `x`: 横方向（-2.375 ~ 2.375 m, x=0がセンターライン）
- `y`: 縦方向（実データ範囲 約 31.97〜40.38 m）
- Hog Line: y = 32.004
- Tee Line: y = 38.405
- Back Line: y = 40.234
- ハウス半径: 1.829 m
- ストーン半径: 0.145 m 
- `distance_from_center`: ハウス中心からの距離（メートル、実データ範囲 約 0〜6.7 m）
- `inhouse` / `insheet`: ハウス内 / シート内フラグ（1/0）

---

## 8. LSD の回転方向（`lsds.turn`）

LSD では、各チームが時計回り（`cw`）と反時計回り（`ccw`）を1投ずつ投げる。
`lsds.turn` はその回転方向を表す。

- 実測: 試合×チームごとに、必ず `cw` 1投・`ccw` 1投（four・md とも例外なし）
- LSD の記録が無い試合もある（four 621 試合、md 67 試合）。LSD を使う集計の母数に注意


```sql
-- チームごとの、回転方向別の LSD 平均距離
SELECT team, turn, AVG(distance_cm) AS avg_cm, COUNT(*) AS n
FROM lsds
GROUP BY team, turn
```

---

## 9. md の事前配置ストーン（`shots.number = 0`）

MD では各エンドの開始時に、両チームのストーンが1個ずつ盤面に置かれる
（ハンマー側がハウス内、非ハンマー側がガード）。
md ではこの**1投目より前の盤面**を、`shots.number = 0` の行と、それに紐づく `stones` 2行で持つ。
four には存在しない。

md の実測:

| 項目 | 値 |
|---|---|
| `number = 0` の行 | 7,402（1エンドに1行） |
| 紐づく `stones` | 14,804（必ず2行。すべて `shot_order = 0`） |

置かれる位置（平均）:

| | 通常エンド（5,740） | パワープレイ（1,662） |
|---|---|---|
| ハンマー側のストーン（ハウス内） | \|x\| 0.01 / y 38.86 | \|x\| 1.26 / y 38.25 |
| 非ハンマー側のストーン（ガード） | \|x\| 0.01 / y 35.06 | \|x\| 1.08 / y 35.06 |

### 集計時の注意

**(1) 投球数を数えるときは `number >= 1` で絞る。**
`number = 0` は投球ではない。絞らないと、事前配置のあるエンドは1エンド11行になる（投球は最大10）。

```sql
SELECT end_id, COUNT(*) AS n_shots
FROM shots
WHERE number >= 1
GROUP BY end_id
```

**(2) `number = 0` の行は、投球の属性がすべて NULL。**
`color` / `team` / `player_name` / `type` / `turn` / `percent_score` が NULL になる。
`AVG(percent_score)` は NULL を無視するので影響を受けないが、`COUNT(*)` を分母にする割合や、
`type` / `color` で `GROUP BY` したときの NULL のグループには `number = 0` が混ざる。
`percent_score IS NOT NULL` で絞っていれば自動的に除外される。

**(3) WMDCC2016 には `number = 0` が無い。**
ほかの13大会では、ストーンの座標があるエンドのほぼすべて（7,413 エンド中 7,402）にある。
初期局面を使う分析は、WMDCC2017 以降を対象にする。

**(4) 事前配置ストーンは、投球後の盤面にも `shot_order = 0` で残る。**
`number >= 1` の投球に紐づく `stones` にも、盤面に残っている限り `shot_order = 0` の行として現れる
（`shot_order = 0` は全 138,237 行。うち `number = 0` に紐づくのは 14,804 行）。

### 取得例

```sql
-- 各エンドの事前配置ストーン（エンド開始時の盤面）
SELECT sh.end_id, st.color, st.x, st.y, st.inhouse
FROM shots sh
JOIN stones st ON st.shot_id = sh.id
WHERE sh.number = 0
```

REST API では `GET /v1/md/shots?number=0` で該当の行を、
`GET /v1/md/shots/{id}/stones` でそのストーンを取得できる。

---

## 10. 投球の注記（`shots.notes`）

Shot by Shot のページで、投球の図の下に書かれた注記を Results Book の文字列のまま持つ。
注記の無い投球は NULL（空文字ではない）。

注記のある投球は four 9,883 投、md 2,095 投（全投球の約2%）。主な中身:

| 種類 | 例（four の件数 / md の件数） |
|---|---|
| 進行 | `Time-out`（4,762 / 1,397）、`Measurement`（896 / 300） |
| 違反 | `Free Guard Zone violation`（401 / 14）、`Did not pass the hog line`（319 / 27）、`Hog line violation`（253 / 45）、`No-Tick Zone violation`（223 / 0）、`Stone removal violation`（10 / 127）、`Burned stone`（149 / 32） |
| 種別の細分 | `Slow Take-out`（1,775 / 41）、`Soft Peeling`（409 / 31）、`Split`（167 / 9）、`In-Wick`（65 / 21） |
| 投球中の出来事 | `Picked up debris`（ゴミをかんだ。223 / 34） |

大文字小文字・ハイフン・空白の表記ゆれは、生成側で今の公式の表記に揃えてある
（例: `hogline` → `hog line`、`No tick` → `No-Tick`）。

**(1) 1投に複数の注記が付くと、区切りが揃っていない。**
`; ` のこと（`Time-out; Time-out`）、空白だけのこと（`Soft Peeling Free Guard Zone violation`）、
`, ` のこと（`Split, Time-out`）がある。**`notes = 'Time-out'` のような完全一致では取りこぼす**ので、
特定の注記の有無は部分一致で判定する。

```sql
-- タイムアウトを取った投球（複数の注記が付いた投球も含む）
SELECT COUNT(*) FROM shots WHERE notes LIKE '%Time-out%'   -- four: 4,919
```

REST API では `GET /v1/{four,md}/shots?has_notes=true` で注記のある投球を、
`?notes=Time-out` で部分一致の絞り込みができる。

---

## 11. 試合のステージと日時（`games` / `events`）

**(1) ステージは `stage_type` で分ける。** `stage` は Results Book の表記のままで、
同じ意味でも `Semi-final` / `SEMIFINAL` / `Semifinal` / `Semi-final 1 v 4` のように揺れる。
予選と決勝トーナメントを分けるときは、方式によらない4分類の `stage_type` を使う。

| stage_type | four | md | 中身 |
|---|---:|---:|---|
| `round_robin` | 4,231 | 1,281 | 総当たり（Round Robin Session N） |
| `playoff` | 378 | 125 | 準決勝・決勝・タイブレーク・予選突破戦など |
| `relegation` | 10 | 12 | 入れ替え戦（World Challenge・Relegation Game） |
| `other` | 0 | 34 | md の B-side や順位決定戦（Classification など） |

**(2) `group_name` があるのは、グループ分けのある大会だけ。**
four は 2 大会（60 試合）だけ、md は 11 大会（1,163 試合）。それ以外は NULL。
`sheet` も一部 NULL（four 187 試合、md 63 試合）。

**(3) `games.start_time` は開催地の現地時刻（`HH:MM`）。** タイムゾーンの情報は無い。
大会をまたいで時刻を比べるときは注意。

**(4) `events.start_date` / `end_date` は、最初と最後の試合の日付。**
開会式や練習日を含む公式の会期とは一致しないことがある。
大会がどの版の競技規則で行われたかは、`start_date` と規則の版の日付で判断する（rb2db://rules の §4）。

```sql
-- 5 ロックルールの適用（2018 年 10 月）以降に始まった大会
SELECT name, start_date FROM events WHERE start_date >= '2018-10-01'
```

日付はすべて `YYYY-MM-DD` の文字列。ISO 形式なので文字列のまま大小比較・範囲指定ができる。
