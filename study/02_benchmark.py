""" 演習1: PostgreSQL vs Spark ベンチマーク(Q1: x, y の平均・標準偏差)"""

import inspect
import math
import os
import statistics
import sys
import time
from collections.abc import Callable
from typing import Any

import psycopg2
from dotenv import load_dotenv
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

load_dotenv()

# --- 接続情報 --------------------------------
PG = {
    "host": "localhost", "port": 5432, "dbname": "rb2db_four",
    "user": os.environ["POSTGRES_USER"],
    "password": os.environ["POSTGRES_PASSWORD"],
}

JDBC_URL = "jdbc:postgresql://localhost:5432/rb2db_four"
JDBC_PROPS = {
    "user": PG["user"],
    "password": PG["password"],
    "driver": "org.postgresql.Driver",
}

# 測定回数。1回目はウォームアップとして捨てるので +1 する (§6-7)
N_RUNS = 3

# --- 計測ヘルパ --------------------------------
def measure(
    label: str,
    fn: Callable[[], Any],
    n_runs: int = N_RUNS,
) -> dict[str, Any]:
    """fn を n_runs+1 回実行して、1回目を捨てて中央値を返す。

    Args:
        label: 測定対象のラベル。
        fn: 測定対象の関数。引数なしで呼べること。
            戻り値は結果の妥当性確認に使う。
        n_runs: 採用する試行回数（ウォームアップの1回を除く）。

    Returns:
        以下のキーを持つ dict。
          - label (str): 引数の label をそのまま返す
          - median (float): 実行時間の中央値（秒）
          - times (list[float]): 採用した全計測値（秒）
          - result (Any): 最後の実行の戻り値
    """

    times: list[float] = []
    result: Any = None
    for i in range(n_runs + 1): # +1 はウォームアップ
        t0 = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - t0
        if i > 0: # ウォームアップを除く
            times.append(elapsed)

    median = statistics.median(times)
    print(f"{label:28} {median:7.3f} 秒   (計測値: "
          f"{', '.join(f'{t:.3f}' for t in times)})")
    
    return {"label": label, "median": median, "times": times, "result": result}

# --- 経路1: PostgreSQL で直接 SQL --------------------------------
# 経路1はどのクエリも「SQL を投げて結果を取る」だけなので1関数に共通化する。
# 経路2(Spark)はクエリごとに書き方が変わるため、Q ごとに関数を分ける。
def run_pg(sql: str) -> list[tuple]:
    """PostgreSQL に SQL を投げて全行取得する。

    Args:
        sql: 実行する SELECT 文。

    Returns:
        結果行のリスト。各行はカラム値のタプル。
    """
    # 毎回接続しなおす。接続の使い回しで速く見えるのを避けるため
    with psycopg2.connect(**PG) as conn, conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


# --- 各クエリの SQL --------------------------------
Q1_SQL = """
    SELECT AVG(x) AS avg_x, STDDEV(x) AS std_x,
           AVG(y) AS avg_y, STDDEV(y) AS std_y
    FROM stones
"""

# Q2: shot_order 別の平均距離。NULL と負値の除外は必須(sql_notes.md §2)
Q2_SQL = """
    SELECT shot_order, AVG(distance_from_center) AS avg_dist
    FROM stones
    WHERE shot_order IS NOT NULL AND shot_order > 0
    GROUP BY shot_order ORDER BY shot_order
"""

# Q3: event 別 x shot_order 別の件数(4段 JOIN)
Q3_SQL = """
    SELECT e.name, st.shot_order, COUNT(*) AS n
    FROM stones st
    JOIN shots sh ON st.shot_id = sh.id
    JOIN ends en  ON sh.end_id  = en.id
    JOIN games g  ON en.game_id = g.id
    JOIN events e ON g.event_id = e.id
    WHERE st.shot_order > 0
    GROUP BY e.name, st.shot_order
    ORDER BY e.name, st.shot_order
"""

# Q4: inhouse=1 に絞った座標集計(述語プッシュダウン)
Q4_SQL = """
    SELECT AVG(x) AS avg_x, AVG(y) AS avg_y, COUNT(*) AS n
    FROM stones WHERE inhouse = 1
"""

# --- 経路2: Spark + JDBC --------------------------------
spark = (SparkSession.builder
         .appName("rb2db-benchmark")  # ログや Web UI に出る表示名。任意
         .master("local[*]")      # どこで動かすか。local[*]=自マシンの全コア（§1-5）
         .config("spark.jars", "study/jars/postgresql.jar") # JVM に JDBC ドライバを渡す（§2-2）
         .getOrCreate())                                    # 既存があれば再利用、なければ新規作成
spark.sparkContext.setLogLevel("ERROR") # WARN を抑えて結果を読みやすく


def read_stones(num_partitions: int = 1) -> DataFrame:
    """stones を DataFrame として読む。

    Args:
        num_partitions: JDBC の並列読み込み数。1 なら分割しない（§2-2）。

    Returns:
        stones テーブルの DataFrame。この時点では読み込みは実行されない（§2-1）。
    """
    if num_partitions == 1:
        return spark.read.jdbc(JDBC_URL, "stones", properties=JDBC_PROPS)
    return spark.read.jdbc(
        JDBC_URL, "stones",
        column="id",                      # 分割の基準列 (数値である必要がある)
        lowerBound=1,
        upperBound=1_152_837,             # four の stones 件数
        numPartitions=num_partitions,     # 分割数
        properties=JDBC_PROPS,
    )

def q1_spark_jdbc(num_partitions: int = 1) -> DataFrame:
    """Spark で Q1 と同じ集計を行う DataFrame を組み立てる。

    Args:
        num_partitions: JDBC の並列読み込み数（§2-2）。

    Returns:
        集計結果の DataFrame。この時点では実行されない（§2-1）。
        実行するのは呼び出し側の collect()。
    """
    df = read_stones(num_partitions)
    return df.agg(
        F.avg("x").alias("avg_x"), F.stddev("x").alias("std_x"),
        F.avg("y").alias("avg_y"), F.stddev("y").alias("std_y"),
    )


# --- 経路2: Q2 (groupBy → Exchange hashpartitioning が出るはず) ----------
def q2_spark_jdbc(num_partitions: int = 1) -> DataFrame:
    """Spark で Q2(shot_order 別の平均距離)の DataFrame を組み立てる。

    Args:
        num_partitions: JDBC の並列読み込み数（§2-2）。

    Returns:
        shot_order ごとの集計結果の DataFrame。実行は呼び出し側の collect()。
    """
    df = read_stones(num_partitions)
    # NULL と負値の除外は必須(sql_notes.md §2)
    return (df.filter(F.col("shot_order").isNotNull() & (F.col("shot_order") > 0))
              .groupBy("shot_order")
              .agg(F.avg("distance_from_center").alias("avg_dist"))
              .orderBy("shot_order"))


# --- 経路2: Q3 (4段 JOIN → シャッフルが何回出るか) ----------------------
def q3_spark_jdbc(num_partitions: int = 1) -> DataFrame:
    """Spark で Q3(event 別 x shot_order 別の件数)の DataFrame を組み立てる。

    Args:
        num_partitions: JDBC の並列読み込み数（§2-2）。

    Returns:
        event 名と shot_order ごとの件数の DataFrame。実行は呼び出し側の collect()。
    """
    # TODO: shots / ends / games / events も spark.read.jdbc() で読み、
    #       .join() で繋いでから groupBy する
    raise NotImplementedError


# --- 経路2: Q4 (述語プッシュダウンの効果) -------------------------------
def q4_spark_jdbc(num_partitions: int = 1) -> DataFrame:
    """Spark で Q4(inhouse=1 に絞った座標集計)の DataFrame を組み立てる。

    Args:
        num_partitions: JDBC の並列読み込み数（§2-2）。

    Returns:
        集計結果の DataFrame。実行は呼び出し側の collect()。
    """
    # TODO: df.filter(F.col("inhouse") == 1).agg(...) を書く
    raise NotImplementedError


# --- 測定ブロック --------------------------------
def run_query(
    title: str,
    sql: str,
    spark_fn: Callable[[int], DataFrame],
    partitions: tuple[int, ...] = (1, 4, 8),
) -> list[dict[str, Any]]:
    """1つのクエリについて経路1・経路2を測定し、結果の一致を確認する。

    Args:
        title: 見出しに出すクエリの説明。
        sql: 経路1(PostgreSQL)に投げる SQL。
        spark_fn: 経路2(Spark)の DataFrame を組み立てる関数。分割数を引数に取る。
        partitions: 測定する JDBC 分割数のタプル。

    Returns:
        measure() の戻り値のリスト。先頭が経路1、以降が経路2。
    """
    print(f"\n=== {title} ===\n")

    # 実行計画は測定対象そのものから取る。これで Q ごとに正しい計画が出る
    print("--- 実行計画 ---")
    spark_fn(1).explain()

    print("\n--- 測定 ---")
    results = [measure("経路1: PostgreSQL", lambda: run_pg(sql))]
    for p in partitions:
        # collect() が「アクション」。ここで初めて実行される（§2-1）
        results.append(
            measure(f"経路2: Spark + JDBC ({p}分割)", lambda p=p: spark_fn(p).collect())
        )

    # 結果の一致確認。目視で桁を比べず、機械的に判定する
    # 分割数を変えると最下位ビットがずれるため、完全一致(==)では比較できない
    print("\n--- 結果の一致確認 ---")
    pg_rows = results[0]["result"]
    for r in results[1:]:
        spark_rows = r["result"]
        ok = len(pg_rows) == len(spark_rows) and all(
            math.isclose(a, b, rel_tol=1e-9) if isinstance(a, float) else a == b
            for pg_row, sp_row in zip(pg_rows, spark_rows, strict=True)
            for a, b in zip(pg_row, sp_row, strict=True)
        )
        print(f"{r['label']:28} {'OK' if ok else 'NG'}")

    return results


# --- 実行 --------------------------------
# 測定対象の一覧。キーはコマンドライン引数に使う
QUERIES = {
    "q1": ("Q1: stones の x, y の平均・標準偏差", Q1_SQL, q1_spark_jdbc),
    "q2": ("Q2: shot_order 別の平均距離 (GROUP BY)", Q2_SQL, q2_spark_jdbc),
    "q3": ("Q3: event 別 x shot_order 別の件数 (4段 JOIN)", Q3_SQL, q3_spark_jdbc),
    "q4": ("Q4: inhouse=1 の座標集計 (述語プッシュダウン)", Q4_SQL, q4_spark_jdbc),
}

if __name__ == "__main__":
    # 引数でクエリを選べる: uv run python study/02_benchmark.py q2
    # 省略時は実装済みのものを全て実行する
    targets = sys.argv[1:] or list(QUERIES)

    # 実行計画は run_query() が Q ごとに表示する
    for key in targets:
        if key not in QUERIES:
            print(f"\n[skip] 未知のクエリ: {key}")
            continue
        title, sql, spark_fn = QUERIES[key]
        # 未実装のものは経路1を測る前にスキップする(見出しの二重表示を避ける)。
        # 関数の中身に NotImplementedError があるかで判定する
        if "NotImplementedError" in inspect.getsource(spark_fn):
            print(f"\n=== {title} ===")
            print(f"[未実装] {spark_fn.__name__} を実装してください")
            continue
        run_query(title, sql, spark_fn)

    spark.stop()  # SparkSession を終了