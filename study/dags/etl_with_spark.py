"""演習2: update_db.sh と同じ構造の練習用 DAG。

実際の DB 更新や Slack 通知は行わず、ファイル操作だけで
同じ依存関係・同じ冪等性の問題を再現する。
"""

from __future__ import annotations

import json
from datetime import timedelta, datetime
from pathlib import Path

from airflow.sdk import dag, task, get_current_context

import subprocess

REPO_ROOT = Path(__file__).parent.parent.parent # study/dags -> リポジトリ直下

WORK_DIR = Path(__file__).parent.parent / "airflow_work"
TARGETS = ["md", "four"]            # update_db.sh と同じ2系統

# @dag = この関数を DAG に変換するデコレータ（TaskFlow API）。
# 付けた関数を「呼ぶ」と DAG が生成され Airflow に登録される。
#   → だからファイル末尾の practice_pipeline() が必須。ないと DAG が存在しない
#
# 旧来の書き方（with DAG(...) + PythonOperator + t1 >> t2）と同じことを、
# 普通の関数呼び出しの形で書ける。依存関係は「戻り値を引数に渡す」ことで表現する
@dag(
    dag_id="etl_with_spark",     # UI に出る名前。一意である必要がある
    schedule=None,                  # 手動実行のみ。慣れたら "@daily" などにする
    catchup=False,                  # 過去分をさかのぼって実行しない
                                    # True(既定)だと schedule 設定時に過去分が一斉に走る
    default_args={
        "retries": 2,               # タスク単位のリトライ (§3-2)
        "retry_delay": timedelta(seconds=10),
    },
    tags=["study"],                 # UI でのフィルタ用ラベル
)
def etl_with_spark():
    """update_db.sh の5ステップを DAG として組み直したもの。"""

    # @task = この関数を1つのタスクにするデコレータ。3つのことが起きる:
    #   ① UI のグラフに箱1つとして現れる（task_id は関数名になる）
    #   ② 戻り値が自動で XCom に入る（§3-5。明示的な push は不要）
    #   ③ 呼び出しの引数に他タスクの戻り値を渡すと、それが依存関係になる
    #      → t1 >> t2 と書かなくても Airflow が順序を理解する

    @task
    def validate() -> str:
        """入力の前提を確認する（本物では .env や SQLite の存在確認）。

        Returns:
            確認できた作業ディレクトリのパス。
        """

        WORK_DIR.mkdir(parents=True, exist_ok=True)
        return str(WORK_DIR)


    @task
    def copy_source(target: str, work_dir: str) -> str:
        """SQLite のコピーに相当するステップ。

        Args:
            target: "md" または "four"。
            work_dir: 作業ディレクトリ。

        Returns:
            コピー先のパス。
        """

        src = Path(work_dir) / f"{target}_source.txt"
        # 本物では docker cp。ここでは中身のあるファイルを置くだけ
        src.write_text(f"{target}: 5000 rows\n")

        return str(src)


    @task
    def migrate(target: str, src_path: str) -> dict:
        """DB 投入に相当するステップ。

        Args:
            target: "md" または "four"。
            src_path: copy_source が返したパス。

        Returns:
            投入結果（target と件数）。XCom で次タスクに渡る。
        """

        rows = int(Path(src_path).read_text().split()[1])
        return {"target": target, "rows": rows}


    @task
    def healthcheck(result: dict) -> dict:
        """疎通確認に相当するステップ。

        Args:
            result: migrate の戻り値。

        Returns:
            検証済みの result。

        Raises:
            ValueError: 件数が 0 の場合。
        """

        if result["rows"] <= 0:
            raise ValueError(f"{result['target']}: 件数が 0")
        return result


    @task
    def notify(results: list[dict]) -> None:
        """Slack 通知に相当するステップ。

        Args:
            results: 各 target の healthcheck の戻り値。
        """

        # 本物では notify_update.py。ここでは標準出力に書くだけ
        total = sum(r["rows"] for r in results)
        print(f"[通知] {len(results)} 系統 / 合計 {total} 行")


    @task
    def notify_with_diff(results: list[dict]) -> None:
        """前回との差分を通知する (update_db.sh:107 と同じ構造)。
        
        Args:
            results: 各 target の healthcheckの戻り値。
        """

        prev_file = WORK_DIR / "prev.json"
        current = {r["target"]: r["rows"] for r in results}

        if prev_file.exists():
            prev = json.loads(prev_file.read_text())
            diff = {k: current[k] - prev.get(k, 0) for k in current}
            print(f"[通知] 差分: {diff}")
        else:
            print(f"[通知] 初回: {current}")

        # <- ここが問題。通知後にprevを上書きしている
        prev_file.write_text(json.dumps(current))


    @task
    def notify_idempotency(results: list[dict]) -> None:
        """前日のファイルとの差分を通知する
        
        Args:
            results: 各 target の healthcheckの戻り値。
        """
        ds: str = get_current_context()["ds"]    # "2026-08-12 形式"　ISO フォーマット
        # yesterday = (date.fromisoformat(ds) - timedelta(days=1)).isoformat()  # これでもいい。これにするならimport date が必要
        yesterday = datetime.strftime(
            datetime.strptime(ds, "%Y-%m-%d") - timedelta(days=1), 
            "%Y-%m-%d"
            )
        yesterday_file = WORK_DIR / f"snapshot_{yesterday}.json"
        current = {r["target"]: r["rows"] for r in results}

        if yesterday_file.exists():
            prev = json.loads(yesterday_file.read_text())
            diff = {k: current[k] - prev.get(k, 0) for k in current}
            print(f"[通知] 差分: {diff}")
        else:
            print(f"[通知] 初回: {current}")

        today_file = WORK_DIR / f"snapshot_{ds}.json"
        today_file.write_text(json.dumps(current))


    @task
    def export_parquet() -> str:
        """Spark ジョブを起動して Parquet を生成する。
        
        Returns:
            出力先のパス。
            
        Raises:
            RuntimeError: Spark ジョブが0以外で終了した場合。
        """

        # Airflow は「起動して結果を見る」だけ。計算方法には関与しない
        result = subprocess.run(
            ["uv", "run", "python", "study/04_export_for_dag.py"],
            cwd=REPO_ROOT,
            capture_output=True, 
            text=True,
        )
        print(result.stdout)    # Airflowのログに出す
        if result.returncode != 0:
            print(result.stderr)
            raise RuntimeError(f"Spark ジョブ失敗 (exit={result.returncode})")
        return "study/parquet/stones_dag_output"


    @task
    def verify_parquet(path: str) -> dict:
        """生成された Parquet を検証する。

        Args:
            path: export_parquet が返した出力先。

        Returns:
            ファイル数と合計サイズ。

        Raises:
            ValueError: ファイルが1つも生成されていない場合。
        """

        out = REPO_ROOT / path
        files = list(out.rglob("*.parquet"))
        if not files:
            raise ValueError(f"{path}: Parquet が生成されていない")
        size_mb = sum(f.stat().st_size for f in files) / 1024 / 1024
        print(f"[verify] {len(files)} ファイル / {size_mb:.1f} MB")
        return {"files": len(files), "size_mb": round(size_mb, 1)}
    

    # ── 依存関係の組み立て ────────────────────────
    # ここは「DAG の設計図を書く」フェーズ。関数を呼んでいるように見えるが、
    # この時点では中身は実行されない（Spark の遅延評価に似ている。§2-1）
    work_dir = validate()


    checked = []
    # この for ループは「定義時」に展開されるので、タスク数は常に2で固定。
    # 実行時に「md だけ」を選ぶことはできない → §7-7 で .expand() に発展させる
    for target in TARGETS:
        # md と four は独立なので並列に走る（§3-3。shell では直列だった）
        #
        # .override(task_id=...) が必要な理由:
        #   task_id は既定で関数名になるため、同じ @task を2回呼ぶと
        #   "copy_source" が重複してエラーになる。呼ぶたびに別名を付ける
        src = copy_source.override(task_id=f"copy_{target}")(target, work_dir)
        migrated = migrate.override(task_id=f"migrate_{target}")(target, src)
        checked.append(
            healthcheck.override(task_id=f"healthcheck_{target}")(migrated)
        )

    # リストを渡すと「全部の完了を待ってから実行」になる（合流点）
    # notify_idempotency(checked)
    notify(checked)

    # Spark ジョブは healthcheck の後に走らせたい（DB 更新前に Parquet を
    # 作ってしまうと、古いデータで生成されることになる）。
    #
    # ただし export_parquet は checked の「値」を必要としない。
    # 引数で渡さないと Airflow は依存なしと判断し、validate 直後に走り出す。
    #   → 「値は渡さないが順序は決めたい」ときは >> で明示する
    exported = export_parquet()
    checked >> exported          # checked（リスト）が全部終わってから exported
    verify_parquet(exported)

    
# ← この呼び出しが必須。@dag は「呼ばれて初めて」DAG を登録する
etl_with_spark()
