# 演習1: PostgreSQL vs Spark ベンチマーク結果

演習書 `memo/learn/spark_airflow_exercises.html` §6 の測定記録。

**目的**: `memo/olap_analytics_plan.md` の「着手判断は実測から入ること」を満たす。
列指向（OLAP）層を作る価値があるかを、推測ではなく数字で判断する材料にする。

最終更新: 2026-08-09 / 状態: **Q1・Q2 完了**（Q3・Q4 と経路3・4 は未測定）

---

## 測定環境

| 項目 | 値 |
|---|---|
| CPU | Intel Core i7-14700KF（28 論理コア） |
| メモリ | 15 GB |
| OS | WSL2 (Ubuntu 24.04) |
| Java | OpenJDK 17.0.19 |
| PySpark | 4.2.0 |
| PostgreSQL | 18.4（Docker コンテナ、ポート5432を公開） |
| 対象データ | `rb2db_four` の `stones`（1,152,837 行 / 9 列） |

**測定方法**: 各条件を4回実行し、**1回目をウォームアップとして捨てて**残り3回の中央値を採用
（`study/02_benchmark.py` の `measure()`）。

---

## Q1: stones 全件の x, y の平均・標準偏差

```sql
SELECT AVG(x), STDDEV(x), AVG(y), STDDEV(y) FROM stones
```

### 結果

| 経路 | 中央値 | 1分割比 | PG 比 |
|---|---:|---:|---:|
| **経路1: PostgreSQL** | **0.023 秒** | — | 1.0× |
| 経路2: Spark + JDBC（1分割） | 0.742 秒 | 1.0× | 32× 遅い |
| 経路2: Spark + JDBC（4分割） | 0.276 秒 | 2.7× 速い | 12× 遅い |
| 経路2: Spark + JDBC（8分割） | 0.194 秒 | **3.8× 速い** | 8.4× 遅い |
| 経路3: Spark + Parquet | 未測定 | — | — |
| 経路4: DuckDB + Parquet | 未測定 | — | — |

結果の一致（`math.isclose(rel_tol=1e-9)`）は全経路で **OK**。

2回測定して再現性を確認（ブレは1割以内）:

| 経路 | 1回目 | 2回目 |
|---|---:|---:|
| PostgreSQL | 0.025 | 0.023 |
| Spark 1分割 | 0.727 | 0.742 |
| Spark 4分割 | 0.258 | 0.276 |
| Spark 8分割 | 0.183 | 0.194 |

### 考察

**1. 並列度の効果は明確に出た（演習の主目的）。**

1分割 → 8分割で **3.8倍**。演習書 §2-2 の「1パーティションしかなければ 28 コアあっても
1コアしか働かない」が、そのまま数字で確認できた。

伸びは 4分割で 2.7倍、8分割で 3.8倍と**逓減している**。分割数に比例はしない。
JDBC 接続の確立コストと、シャッフルでの集約コストが分割数に応じて増えるため。
`numPartitions` の最適値探索（§6-6）はまだ実施していない。

**2. PostgreSQL が Spark より速い — ただし理由は「Spark が遅い」ではない。**

8.4倍の差がついたが、これは演習書 §6-2 で予告した通りの結果であり異常ではない。
ただし、その要因を実行計画から確認したところ、**予想より PostgreSQL が有利な条件が揃っていた**。

```
Finalize Aggregate (actual time=1004.979..1006.396 rows=1)
  Buffers: shared hit=11875           ← 全てキャッシュヒット。ディスクI/O ゼロ
  -> Gather  Workers Planned: 2       ← PostgreSQL 自身も並列実行している
     -> Parallel Seq Scan on stones (rows=384279 loops=3)
```

判明した2点:

- **PostgreSQL も並列スキャンしていた**（ワーカー2つ + 親で3並列）。
  「PG=逐次 vs Spark=並列」という単純な対比ではなかった。
- **データが全てバッファキャッシュに載っていた**（`shared hit=11875`, `read=0`）。
  157万行 × 該当列は約 93MB で、shared_buffers に収まる規模。
  **ディスクI/O が発生していない**ため、行指向の不利（不要な列も読む）が現れにくい。

→ **この条件下では、列指向の利点が最も出にくい。**
Spark 側は JDBC 転送と JVM のオーバーヘッドを丸ごと負う一方、PG 側はメモリ上で
並列集計するだけで済んでいる。

**3. Exchange（シャッフル）は出るが、コストは小さい。**

```
HashAggregate(functions=[avg(x)])              ← 最終集計
  Exchange SinglePartition                     ← シャッフル
    HashAggregate(functions=[partial_avg(x)])  ← 各パーティションで部分集計
      Scan JDBCRelation
```

`groupBy` がないのに `Exchange` が出るのは、Spark の集計が**常に2段構成**のため
（部分集計 → 集約）。分割数が1でも計画は同じ形になる。

転送されるのは**部分集計の結果だけ**（157万行ではない）なので、実コストは極小。
Q2（`groupBy`）では `hashpartitioning` に変わり、性質が変わるはず。

---

## Q2: shot_order 別の平均距離（GROUP BY）

```sql
SELECT shot_order, AVG(distance_from_center)
FROM stones
WHERE shot_order IS NOT NULL AND shot_order > 0
GROUP BY shot_order ORDER BY shot_order
```

### 結果

| 経路 | 中央値 | Q1 との比 |
|---|---:|---:|
| 経路1: PostgreSQL | 0.038 秒 | 1.6× 遅い |
| 経路2: Spark + JDBC（1分割） | 0.598 秒 | **0.8×（速い）** |
| 経路2: Spark + JDBC（4分割） | 0.255 秒 | 0.9× |
| 経路2: Spark + JDBC（8分割） | 0.191 秒 | 1.0× |

一致確認は全経路 **OK**（16行 × 2列）。

### 考察

**1. シャッフルが2回に増えたが、Q1 より速い。**

```
Exchange rangepartitioning(shot_order, 200)   ← orderBy のため
Exchange hashpartitioning(shot_order, 200)    ← groupBy のため
```

Q1 の `Exchange SinglePartition` 1回に対し、Q2 は2回。にもかかわらず 1分割で
Q1 より速い（0.598 vs 0.744 秒）。**シャッフル回数だけでは速度は決まらない。**

理由は転送量。`PushedFilters` に NULL・負値の除外が降りており、
異常値 3,180 件（`sql_notes.md` §2）は**転送すらされていない**。

```
PushedFilters: [*IsNotNull(shot_order), *GreaterThan(shot_order,0)]
ReadSchema: struct<distance_from_center:double,shot_order:int>
```

**2. PostgreSQL 側は Q1 より遅くなった**（0.024 → 0.038 秒）。
GROUP BY のハッシュ集計が加わったぶん。ただし依然として Spark の5倍速い。

**3. 並列度の効果は Q1 と同傾向**（1→8分割で 3.1倍）。
Q1 の 3.8倍よりやや小さいのは、シャッフルのコストが分割数に応じて増えるため。

---

## 現時点の暫定結論

**「PostgreSQL は 157万行程度なら十分速い」という仮説が、Q1・Q2 で裏付けられた。**

`memo/olap_analytics_plan.md` の警告 —

> 「OLTP だから遅いはず」は決めつけ。150万行程度なら適切なインデックスで
> PostgreSQL でも案外速い可能性がある。

— は正しかった。**0.02〜0.04秒は体感で待ち時間がなく、これを速くする動機は薄い。**

ただし**この結論はまだ早い**。理由は3つ。

1. **経路3（Parquet）を測っていない。** 列指向の効果はこれを測らないと分からない。
   現状の PG vs Spark+JDBC は「転送方式の比較」であって「行指向 vs 列指向の比較」ではない。
2. **Q1・Q2 は列指向が有利なはずのクエリ**（2列だけ読む集計）。それでもキャッシュ全ヒットのため
   差が出ていない。Q3（4段 JOIN）など重いクエリで傾向が変わる可能性。
3. **単発クエリしか測っていない。** analytics の実運用は「全大会横断で集計を何度も回す」形。
   キャッシュに載らない規模・パターンでは結果が変わりうる。

→ **判断は Q3・Q4 と経路3・4 の測定後に行う。**

---

## 次にやること

- [x] Q2（`shot_order` 別 GROUP BY）— `Exchange hashpartitioning` を確認
- [ ] Q3（4段 JOIN）— JOIN ごとのシャッフル数を確認
- [ ] Q4（`inhouse=1` 絞り込み）— 述語プッシュダウンの効果
- [ ] `numPartitions` の最適値探索（1/2/4/8/16/32）— 演習書 §6-6
- [ ] 経路3: Spark + Parquet（演習3の後）
- [ ] 経路4: DuckDB + Parquet（演習書 §8-5）
- [ ] 全て揃ったら `memo/olap_analytics_plan.md` に結論を反映
