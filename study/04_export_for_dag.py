"""演習4: DAG から呼ばれる Parquet 生成ジョブ。

03_export_parquet.py との違いは「比較しない」こと。
実運用と同じく、決めた1パターンだけを書き出す。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pyspark.sql import DataFrame, SparkSession

load_dotenv()

JDBC_URL = "jdbc:postgresql://localhost:5432/rb2db_four"
JDBC_PROPS = {
    "user": os.environ["POSTGRES_USER"],
    "password": os.environ["POSTGRES_PASSWORD"],
    "driver": "org.postgresql.Driver",
}

# §8-2 の比較で決めた構成: event_id 分割 + zstd
OUT_PATH = Path("study/parquet/stones_dag_output")


def build_stones_enriched(spark: SparkSession) -> DataFrame:
    """stones に大会情報を付与した DataFrame を組み立てる。
    
    Args:
        spark: SparkSession
        
    Returns:
        stones の全列 + event_id / event_name / category / game_id。
    """
    def read(name: str, n: int = 1) -> DataFrame:
        if n == 1:
            return spark.read.jdbc(JDBC_URL, name, properties=JDBC_PROPS)
        return spark.read.jdbc(
            JDBC_URL, name, 
            column="id",
            lowerBound=1,
            upperBound=100_000_000,
            numPartitions=n, 
            properties=JDBC_PROPS,
        )

    stones, shots = read("stones", 16), read("shots")
    ends, games, events = read("ends"), read("games"), read("events")

    return (stones
            .join(shots, stones["shot_id"] == shots["id"])
            .join(ends, shots["end_id"] == ends["id"])
            .join(games, ends["game_id"] == games["id"])
            .join(events, games["event_id"] == events["id"])
            .select(
                stones["id"], stones["shot_id"], stones["color"],
                stones["x"], stones["y"], stones["distance_from_center"],
                stones["inhouse"], stones["insheet"], stones["shot_order"],
                events["id"].alias("event_id"),
                events["name"].alias("event_name"),
                events["category"],
                games["id"].alias("game_id"),
            ))


def main() -> int:
    """Parquet を生成する。
    
    Returns:
        終了コード。成功なら 0。
        # <- DAG はこの終了コードで成否を判断する
    """

    spark = (SparkSession.builder
             .appName("rb2db-dag-export")
             .master("local[*]")
             .config("spark.jars", "study/jars/postgresql.jar")
             .getOrCreate())
    spark.sparkContext.setLogLevel("ERROR")

    try:
        df = build_stones_enriched(spark)
        (df.write                           # 書き出しの開始
         .mode("overwrite")                 # 既存があれば消して書き直す
         .partitionBy("event_id")           # 大会ごとにディレクトリを分ける
         .option("compression", "zstd")     # zstd で圧縮
         .parquet(str(OUT_PATH)))           # ここで初めて実行される
        print(f"[export] {OUT_PATH} に書き出し完了")
        return 0
    finally:
        spark.stop()    # 失敗しても必ず止める


if __name__ == "__main__":
    sys.exit(main())