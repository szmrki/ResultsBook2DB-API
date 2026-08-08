# rb2db 定義済みメトリクスの定義集

ラボ内で集計定義を統一するための「正解の参照実装」。
自由SQL（run_query）で集計する際は、以下の定義に合わせること。
将来的にはこれらを定義済みメトリクスツールとして提供する予定。

**掲載の基準値はすべて実データでの実測値（2026-08-08 時点）**。
自分の集計結果がこの桁から大きく外れたら、フィルタの付け忘れを疑うこと。

---

# A. エンド系メトリクス（`ends` テーブル）

**すべて以下のフィルタを必須とする**
（SQL上の注意点 §1「NULL 混入の罠」を参照。NULL はコンシードによる未実施エンド）:

```sql
WHERE score_red IS NOT NULL AND score_yellow IS NOT NULL
```

## A-1. ハンマー差分（hammer advantage）

ハンマー側から見た「そのエンドの得失点差」の平均。ハンマー保持の有利さを表す。

```sql
AVG(
  CASE WHEN color_hammer = 'red' THEN score_red - score_yellow
       WHEN color_hammer = 'yellow' THEN score_yellow - score_red
  END
)
```

## A-2. ハンマー時平均得点（raw 版）

ハンマー側自身の得点の平均。スチールされたエンドは 0 点として分母に含む（raw = 生の平均）。

```sql
AVG(
  CASE WHEN color_hammer = 'red' THEN score_red
       WHEN color_hammer = 'yellow' THEN score_yellow
  END
)
```

## A-3. ブランクエンド率

両者無得点だったエンドの割合。

```sql
AVG( CASE WHEN score_red = 0 AND score_yellow = 0 THEN 1.0 ELSE 0.0 END )
```

## A-4. スチール率（steal-against rate）

非ハンマー側が得点したエンドの割合（ハンマー側にとって「スチールされた」割合）。

```sql
AVG(
  CASE WHEN (color_hammer = 'red'    AND score_yellow > 0)
         OR (color_hammer = 'yellow' AND score_red    > 0)
       THEN 1.0 ELSE 0.0
  END
)
```

## A-5. 全体の基準値（実測）

| 指標 | four | md |
|---|---|---|
| 対象エンド数 | 19,997 | 10,358 |
| ハンマー差分 | 0.791 | 0.714 |
| ハンマー時平均得点（raw） | 1.108 | 1.226 |
| **ブランクエンド率** | **12.5%** | **0.18%** |
| **スチール率** | **21.4%** | **33.9%** |

**md と four は競技性が大きく異なる**。MD はブランクがほぼ発生せず（0.18%）、
スチール率が4人制の1.6倍（33.9%）。**両者を混ぜて集計してはいけない。**

MD でブランクが起きない理由は、ブランクにしてもハンマーが交代する MD ルール
（SQL上の注意点 §5）のため、ブランクを選ぶ戦術的動機が乏しいことによる。

## A-6. パワープレイ効果（md 限定）

`is_power_play` は md のみ有効（four では NULL）。

```sql
SELECT is_power_play,
       AVG(CASE WHEN color_hammer='red' THEN score_red
                WHEN color_hammer='yellow' THEN score_yellow END) AS hammer_pts
FROM ends
WHERE score_red IS NOT NULL AND score_yellow IS NOT NULL
GROUP BY is_power_play
```

実測（md）: PP なし **1.170 点**（8,603エンド）→ PP あり **1.499 点**（1,755エンド）。
**パワープレイでハンマー得点が約 0.33 点上昇する。**

---

# B. ショット系メトリクス（`shots` テーブル）

**すべて以下のフィルタを推奨する**（SQL上の注意点 §4 を参照）:

```sql
WHERE percent_score IS NOT NULL
  AND type NOT IN ('Through', 'no statistics')
```

`Through` と `no statistics` は成功率が構造的に定義できないショット。

## B-1. 平均成功率（avg percent score）

```sql
AVG(percent_score)
```

**注意**: `percent_score` は 0/25/50/75/100 の離散値。100点が63%を占めるため、
単純平均は 80 前後に張り付き、**チーム間の差が出にくい**。
比較目的なら B-2 / B-3 を併用すること。

実測（four・全体）: **80.67**（273,238投球）

## B-2. 完全成功率（perfect rate）

100点だったショットの割合。平均より分布の違いが出やすい。

```sql
AVG( CASE WHEN percent_score = 100 THEN 1.0 ELSE 0.0 END )
```

実測（four・全体）: **63.31%**

## B-3. 良ショット率（good rate）

75点以上（=概ね成功）の割合。

```sql
AVG( CASE WHEN percent_score >= 75 THEN 1.0 ELSE 0.0 END )
```

実測（four・全体）: **77.54%**

## B-4. ショットタイプ別の成功率

```sql
SELECT type,
       COUNT(*) AS n,
       AVG(percent_score) AS avg_pct,
       AVG(CASE WHEN percent_score = 100 THEN 1.0 ELSE 0.0 END) AS perfect_rate
FROM shots
WHERE percent_score IS NOT NULL
  AND type NOT IN ('Through', 'no statistics')
GROUP BY type
ORDER BY n DESC
```

タイプごとに難易度が異なるため、**チーム比較ではタイプ構成の違いを考慮すること**
（難しいショットを多投するチームは平均が下がる）。

---

# C. 座標系メトリクス（`stones` テーブル）

**着弾点を対象にする場合は、必ず以下の条件を付ける**
（SQL上の注意点 §3 を参照。付け忘れると盤面に残る他の石が混入する）:

```sql
FROM stones st
JOIN shots sh ON st.shot_id = sh.id
WHERE st.shot_order = sh.number   -- ★ 着弾点に限定
  AND st.shot_order > 0            -- 異常値を除外
```

四人制の対象行数は 234,206 行。

## C-1. 平均着弾距離

ハウス中心（ティー）からの距離の平均。

```sql
AVG(st.distance_from_center)
```

実測（four・全着弾点）: **1.605 m**

## C-2. インハウス率

着弾点がハウス内に収まった割合。

```sql
AVG( CASE WHEN st.inhouse = 1 THEN 1.0 ELSE 0.0 END )
```

実測（four・全着弾点）: **70.60%**

> ⚠️ **`insheet` はフィルタとして使えない。** 実測では非NULL行 1,149,914 行の
> **すべてが `insheet = 1`**（`insheet = 0` は0件）。シート外に出た石は
> レコード自体が存在しないため、`insheet` で絞る意味はない。

## C-3. 着弾点の分布（可視化用）

```sql
SELECT st.x, st.y, st.distance_from_center, st.inhouse, sh.type, sh.percent_score
FROM stones st
JOIN shots sh ON st.shot_id = sh.id
WHERE st.shot_order = sh.number AND st.shot_order > 0
  AND sh.number = 2               -- N投目に限定する場合
```

座標系は DigitalCurling3 メートル座標（SQL上の注意点 §7）。
ハウス中心は (x=0, y≈38.405)。プロットする際は y 軸上向き。

---

# D. その他の注意

## D-1. md / four を混ぜない

A-5 のとおり **md と four は競技性が構造的に異なる**。
DB が分かれているのは意図的な設計であり、横断集計する場合は必ず系統を明示すること。

## D-2. カテゴリ別集計（four）

four は4カテゴリを含む。混ぜると解釈を誤る。

| category | 大会数 | 収録年 |
|---|---|---|
| Men | 16 | 2022–2026 |
| Women | 16 | 2022–2026 |
| Junior Men | 5 | 2022–2026 |
| Junior Women | 5 | 2022–2026 |

```sql
JOIN events e ON g.event_id = e.id
WHERE e.category = 'Women'
```

## D-3. FE / SE（Force Efficiency / Steal Efficiency）

**FE(Force Efficiency)**：
自チームが先攻時に相手に1点をとらせた割合
"相手チーム(後攻)が1点をとったエンド数 / 相手チーム(後攻)が得点したエンド数"で計算される

**SE(Steal Efficiency)**:
自チームが先攻時に得点をとった割合(スチールした割合)
"自チーム(先攻)が得点をとったエンド数 / 自チームが先攻であった総エンド数"で計算される
