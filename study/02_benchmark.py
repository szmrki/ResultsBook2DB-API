""" 演習1: PostgreSQL vs Spark ベンチマーク(Q1: x, y の平均・標準偏差)"""

import math
import os
import statistics
import time
from collections.abc import Callable
from typing import Any

import psycopg2
from dotenv import load_dotenv
from pyspark.sql import DataFrame, Row, SparkSession
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
Q1_SQL = """
    SELECT AVG(x) AS avg_x, STDDEV(x) AS std_x,
           AVG(y) AS avg_y, STDDEV(y) AS std_y
    FROM stones
"""

def q1_postgres() -> tuple[float, float, float, float]:
    """PostgreSQL に直接 SQL を投げて結果を1行取得する。

    Returns:
        (avg_x, std_x, avg_y, std_y) の4要素タプル。
    """
    # 毎回接続しなおす。接続の使い回しで速く見えるのを避けるため
    with psycopg2.connect(**PG) as conn, conn.cursor() as cur:
        cur.execute(Q1_SQL)
        return cur.fetchone()

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

def q1_spark_jdbc(num_partitions: int = 1) -> list[Row]:
    """ SparkでQ1と同じ集計を行う。
    
    Args: 
        num_partitions: JDBC の並列読み込み数（§2-2）。

    Returns:
        集計結果の Row を1件だけ含むリスト。
    """
    df = read_stones(num_partitions)
    agg = df.agg(
        F.avg("x").alias("avg_x"), F.stddev("x").alias("std_x"),
        F.avg("y").alias("avg_y"), F.stddev("y").alias("std_y"),
    )

    return agg.collect() # ← アクション。ここで初めて実行される（§2-1）

# --- 実行 --------------------------------
if __name__ == "__main__":
    print("=== Q1: stones の x, y の平均・標準偏差 ===\n")

    # 実行計画を先に確認 (§5-5)
    print("--- 実行計画 ---")
    read_stones(1).agg(F.avg("x")).explain()
    print()

    print("--- 測定 ---")
    results = [
        measure("経路1: PostgreSQL", q1_postgres),
        measure("経路2: Spark + JDBC (1分割)", lambda: q1_spark_jdbc(1)),
        measure("経路2: Spark + JDBC (4分割)", lambda: q1_spark_jdbc(4)),
        measure("経路2: Spark + JDBC (8分割)", lambda: q1_spark_jdbc(8)),
    ]

    # 結果の一致確認。目視で桁を比べず、機械的に判定する
    # 分割数を変えると最下位ビットがずれるため、完全一致(==)では比較できない
    print("\n--- 結果の一致確認 ---")
    pg_row = results[0]["result"]
    for r in results[1:]:
        spark_row = r["result"][0]
        ok = all(
            math.isclose(a, b, rel_tol=1e-9)  # 相対誤差 1e-9 以内なら同一とみなす
            for a, b in zip(pg_row, spark_row, strict=True)
        )
        print(f"{r['label']:28} {'OK' if ok else 'NG'}")

    spark.stop()  # SparkSession を終了