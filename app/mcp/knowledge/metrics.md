# rb2db 定義済みメトリクスの定義集

ラボ内で集計定義を統一するための「正解の参照実装」。
自由SQL（run_query）で集計する際は、以下の定義に合わせること。
将来的にはこれらを定義済みメトリクスツールとして提供する予定。

**すべて `ends` テーブルを対象とし、以下のフィルタを必須とする**
（SQL上の注意点「NULL 混入の罠」を参照）:

```sql
WHERE score_red IS NOT NULL AND score_yellow IS NOT NULL
```

---

## 1. ハンマー差分（hammer advantage）

ハンマー側から見た「そのエンドの得失点差」の平均。ハンマー保持の有利さを表す。

```sql
AVG(
  CASE WHEN color_hammer = 'red' THEN score_red - score_yellow
       WHEN color_hammer = 'yellow' THEN score_yellow - score_red
  END
)
```

## 2. ハンマー時平均得点（raw 版）

ハンマー側自身の得点の平均。スチールされたエンドは 0 点として分母に含む（raw = 生の平均）。

```sql
AVG(
  CASE WHEN color_hammer = 'red' THEN score_red
       WHEN color_hammer = 'yellow' THEN score_yellow
  END
)
```

## 3. ブランクエンド率

両者無得点だったエンドの割合。

```sql
AVG( CASE WHEN score_red = 0 AND score_yellow = 0 THEN 1.0 ELSE 0.0 END )
```

## 4. スチール率（steal-against rate）

非ハンマー側が得点したエンドの割合（ハンマー側にとって「スチールされた」割合）。

```sql
AVG(
  CASE WHEN (color_hammer = 'red'    AND score_yellow > 0)
         OR (color_hammer = 'yellow' AND score_red    > 0)
       THEN 1.0 ELSE 0.0
  END
)
```
