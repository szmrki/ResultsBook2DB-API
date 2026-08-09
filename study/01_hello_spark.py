from pyspark.sql import SparkSession

#SparkSession = Spark の入口。これを作るところからすべてが始まる
spark = (SparkSession.builder
         .appName("rb2db-study")  # ログや Web UI に出る表示名。任意
         .master("local[*]")      # どこで動かすか。local[*]=自マシンの全コア（§1-5）
         .config("spark.jars", "study/jars/postgresql.jar") # JVM に JDBC ドライバを渡す（§2-2）
         .getOrCreate())                                    # 既存があれば再利用、なければ新規作成

#接続情報は .env から読む（パスワードをコードに書かない）
#POSTGRES_USER / POSTGRES_PASSWORD は .env に定義済み
import os
from dotenv import load_dotenv
load_dotenv()

props = {
    "user":     os.environ["POSTGRES_USER"],
    "password": os.environ["POSTGRES_PASSWORD"],
    "driver":   "org.postgresql.Driver",   # jar の中のどのクラスを使うか。PG は常にこれ
}

# jdbc: で始まるのが JDBC 要の書式。§5-3 でポートを公開したので localhost で届く
url = "jdbc:postgresql://localhost:5432/rb2db_four"

# stones テーブルのデータ数を数える
df = spark.read.jdbc(url, "stones", properties=props)   # まだ読まない。計画を立てるだけ（§2-1）
print("df.count(): ", df.count())      # ← アクション。ここで初めて実行される（§2-1）
df.printSchema()       # 列名と型を確認（キャッシュ済みなので再実行されない）

# explain() を見ておく
from pyspark.sql.functions import col

q = df.filter(col("inhouse") == 1).select("x", "y") # inhouse=1 の行だけを抽出して x,y 列だけにする（§2-4）まだ実行されない
q.explain(True)    # 実行計画を確認（§2-4）まだ実行されない