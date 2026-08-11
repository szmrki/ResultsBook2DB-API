"""演習3: stones テーブルを Parquet として書きだす。

パーティション設計を3通り作り、サイズと読み取り速度を比較する。
"""

import os
import shutil
import statistics
import time
from pathlib import Path

from dotenv import load_dotenv
from pyspark.sql import DataFrame, SparkSession
from pyspark.sql import functions as F

load_dotenv()

JDBC_URL = "jdbc:postgresql://localhost:5432/rb2db_four"
JDBC_PROPS = {
    "user": os.environ["POSTGRES_USER"],
    "password": os.environ["POSTGRES_PASSWORD"],
    "driver": "org.postgresql.Driver",
}
OUT_DIR = Path("study/parquet")
OUT_DIR.mkdir(exist_ok=True, parents=True)

# 測定回数。1回目はウォームアップとして捨てるので +1 する
# 書き込みはディスクI/O のブレが大きいため、中央値を採る
N_RUNS = 3

spark = (SparkSession.builder
         .appName("rb2db-parquet-export")
         .master("local[*]")
         .config("spark.jars", "study/jars/postgresql.jar")
         .getOrCreate())
spark.sparkContext.setLogLevel("ERROR")

def read_table(name: str, num_partitions: int = 1) -> DataFrame:
    """テーブルをDataFrameとして読む。
    
    Args:
        name: テーブル名
        num_partitions: JDBCの並列読み込み数。stones以外は1でよい。
        
    Returns:
        テーブルのDataFrame    
    """

    if num_partitions == 1:
        return spark.read.jdbc(JDBC_URL, name, properties=JDBC_PROPS)
    return spark.read.jdbc(
        JDBC_URL, name,
        column="id", 
        lowerBound=1,
        upperBound=10_000_000,  # 適当な大きい値
        numPartitions=num_partitions,
        properties=JDBC_PROPS,
    )

def build_stones_enriched() -> DataFrame:
    """stones に event_id / category / game_id を付与した DataFrame を組み立てる。

    分析側が JOIN 不要で使えるよう、大会情報を非正規化して持たせる。

    Returns:
        stones の全列 + event_id + category + event_name + game_id を持つ DataFrame。
    """

    # §6-6の探索結果より、stonesの読み込みは16分割が最速
    stones = read_table("stones", num_partitions=16)
    shots = read_table("shots", num_partitions=1)
    ends = read_table("ends", num_partitions=1)
    games = read_table("games", num_partitions=1)
    events = read_table("events", num_partitions=1)

    return (stones
            .join(shots, stones["shot_id"] == shots["id"])
            .join(ends, shots["end_id"] == ends["id"])
            .join(games, ends["game_id"] == games["id"])
            .join(events, games["event_id"] == events["id"])
            # 保存する列を明示。JOINした後のidが紛れ込むのを防ぐ
            .select(
                stones["id"], stones["shot_id"], stones["color"],
                stones["x"], stones["y"], stones["distance_from_center"],
                stones["inhouse"], stones["insheet"], stones["shot_order"],
                events["id"].alias("event_id"),
                events["name"].alias("event_name"),
                events["category"],
                games["id"].alias("game_id"),   # 小ファイル問題の検証用（2,241件）
            ))

def export(
    df: DataFrame,
    name: str,
    partition_by: list[str] | None,
    n_runs: int = N_RUNS,
    compression: str | None = None,
) -> dict:
    """DataFrame を Parquet として書きだし、所要時間とサイズを返す。

    書き込みはディスクI/O を伴うため実行ごとのブレが大きい。
    measure()（02_benchmark.py）と同じく複数回測って中央値を採る。

    Args:
        df: 書き出す DataFrame。
        name: 出力先ディレクトリ名(OUT_DIR配下)。
        partition_by: パーティション列。None なら分割しない。
        n_runs: 採用する試行回数（ウォームアップの1回を除く）。
        compression: 圧縮形式（"snappy" / "zstd" など）。None なら既定の snappy。

    Returns:
        name / seconds / times / size_mb / files / avg_kb を含む dict。
    """
    path = OUT_DIR / name

    # ── writer を段階的に組み立てる ──────────────────
    # df.write は DataFrameWriter を返す。mode() や partitionBy() は
    # 設定を書き込んで「自分自身」を返す（DataFrame と違い不変ではない）。
    # だから .mode(...).partitionBy(...) と繋いでも、変数に受けて
    # 条件分岐しても同じ。ここは partitionBy の有無を切り替えたいので分ける
    writer = df.write.mode("overwrite")
    if partition_by:
        # *partition_by は「リストを個別の引数に展開」する記法。
        #   ["a", "b"] → partitionBy("a", "b")
        # partitionBy はリストではなく可変長引数を取るため必要
        writer = writer.partitionBy(*partition_by)
    if compression:
        writer = writer.option("compression", compression)

    # ── 計測（1回目はウォームアップとして捨てる）──────
    times: list[float] = []
    for i in range(n_runs + 1):
        # 前回の出力が残っていると、サイズやファイル数が混ざる
        # rmtree = ディレクトリを中身ごと削除（rm -rf 相当）
        if path.exists():
            shutil.rmtree(path)

        # parquet() が「アクション」。ここで初めて実行される（§2-1）
        t0 = time.perf_counter()
        writer.parquet(str(path))        # Path は str に変換（Spark は文字列パスを期待する）
        if i > 0:                        # ウォームアップを除く
            times.append(time.perf_counter() - t0)

    elapsed = statistics.median(times)

    # ── 出力の集計 ─────────────────────────────────
    # Parquet は「1ファイル」ではなく「ディレクトリ」として出力される。
    # 中に part-00000-....parquet が並び、partitionBy すると
    # event_id=1/ のようなサブディレクトリに分かれる。
    # rglob = 再帰的にパターン一致（サブディレクトリも探索）
    files = list(path.rglob("*.parquet"))

    # stat().st_size がファイルサイズ（バイト）。1024で2回割って MB に
    size_mb = sum(f.stat().st_size for f in files) / 1024 / 1024

    # 平均ファイルサイズも出す。小ファイル問題は「ファイル数」ではなく
    # 「1ファイルが小さすぎること」が本質なので、これを見ないと判断できない
    avg_kb = size_mb * 1024 / len(files) if files else 0

    # ブレを判断できるよう、中央値だけでなく全計測値も出す
    spread = ", ".join(f"{t:.2f}" for t in times)
    print(f"{name:24} {elapsed:6.2f} 秒  {size_mb:7.2f} MB  "
          f"{len(files):5d} ファイル  平均 {avg_kb:8.1f} KB   [{spread}]")
    return {"name": name, "seconds": elapsed, "times": times,
            "size_mb": size_mb, "files": len(files), "avg_kb": avg_kb}


# --- 実行 ------------
if __name__ == "__main__":
    df = build_stones_enriched()
    df.cache()
    print(f"対象: {df.count():,} 行\n")

    # 最初の1件は JOIN の実行やファイルシステムの準備が乗るため、
    # export() 内のウォームアップだけでは吸収しきれない。捨て測定を1回入れる
    print("--- 事前ウォームアップ（結果は捨てる）---")
    export(df, "_warmup", None, n_runs=1)

    # export() が内部で n_runs+1 回測って中央値を採るので、
    # 逆順での再測定は不要になった（順序の影響は中央値に吸収される）
    print("\n--- パーティション設計の比較 ---")
    results = [
        export(df, "stones_flat",     None),            # 分割なし
        export(df, "stones_by_cat",   ["category"]),    # 4分割
        export(df, "stones_by_event", ["event_id"]),    # 42分割
        export(df, "stones_by_game",  ["game_id"]),     # 1,891分割 ← 小ファイル問題
    ]

    print("\n--- 圧縮形式の比較（分割なしで）---")
    for codec in ("snappy", "zstd"):
        export(df, f"stones_{codec}", None, compression=codec)

    shutil.rmtree(OUT_DIR / "_warmup", ignore_errors=True)  # 後片付け
    spark.stop()