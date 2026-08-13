"""演習2: update_db.sh と同じ構造の練習用 DAG。

実際の DB 更新や Slack 通知は行わず、ファイル操作だけで
同じ依存関係・同じ冪等性の問題を再現する。
"""

from __future__ import annotations

import json
from datetime import timedelta, datetime
from pathlib import Path

from airflow.sdk import dag, task, get_current_context

WORK_DIR = Path(__file__).parent.parent / "airflow_work"
TARGETS = ["md", "four"]            # update_db.sh と同じ2系統


# @dag = この関数を DAG に変換するデコレータ（TaskFlow API）。
# 付けた関数を「呼ぶ」と DAG が生成され Airflow に登録される。
#   → だからファイル末尾の practice_pipeline() が必須。ないと DAG が存在しない
#
# 旧来の書き方（with DAG(...) + PythonOperator + t1 >> t2）と同じことを、
# 普通の関数呼び出しの形で書ける。依存関係は「戻り値を引数に渡す」ことで表現する
@dag(
    dag_id="practice_pipeline_dynamic",     # UI に出る名前。一意である必要がある
    schedule=None,                  # 手動実行のみ。慣れたら "@daily" などにする
    catchup=False,                  # 過去分をさかのぼって実行しない
                                    # True(既定)だと schedule 設定時に過去分が一斉に走る
    params={"targets": ["md", "four"]},  # <- 実行時に上書きできる規定値
    default_args={
        "retries": 2,               # タスク単位のリトライ (§3-2)
        "retry_delay": timedelta(seconds=10),
    },
    tags=["study"],                 # UI でのフィルタ用ラベル
)
def practice_pipeline_dynamic():
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
    def get_targets() -> list[str]:
        """実行時パラメータから処理対象を取り出す。
        
        Returns:
            処理する系統のリスト(例: ["md"])。
        """
        return get_current_context()["params"]["targets"]


    @task(map_index_template="{{ task.op_kwargs['target'] }}")
    def copy_source(target: str, work_dir: str) -> str:
        """SQLite のコピーに相当するステップ。

        Args:
            target: "md" または "four"。
            work_dir: 作業ディレクトリ。

        Returns:
            target と src_path を持つ dict。
        """

        src = Path(work_dir) / f"{target}_source.txt"
        # 本物では docker cp。ここでは中身のあるファイルを置くだけ
        src.write_text(f"{target}: 5000 rows\n")

        return {"target": target, "src_path": str(src)}


    @task
    def migrate(src: dict) -> dict:
        """DB 投入に相当するステップ。

        Args:
            src: copy_source の戻り値。

        Returns:
            投入結果（target と件数）。XCom で次タスクに渡る。
        """

        rows = int(Path(src["src_path"]).read_text().split()[1])
        return {"target": src["target"], "rows": rows}


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


    # ── 依存関係の組み立て ────────────────────────
    # ここは「DAG の設計図を書く」フェーズ。関数を呼んでいるように見えるが、
    # この時点では中身は実行されない（Spark の遅延評価に似ている。§2-1）
    work_dir = validate()
    targets = get_targets()

    # forループ→ .expand()
    # .partial() = 全タスク共通の引数を先に固定する
    # .expand()  = リストの各要素に対してタスクを1つずつ作る
    #   → タスク数が実行時に決まる（DAG 定義時ではない）
    srcs = copy_source.partial(work_dir=work_dir).expand(target=targets)
    migrated = migrate.expand(src=srcs)
    checked = healthcheck.expand(result=migrated)

    # リストを渡すと「全部の完了を待ってから実行」になる（合流点）
    notify_idempotency(checked)

    
# ← この呼び出しが必須。@dag は「呼ばれて初めて」DAG を登録する
practice_pipeline_dynamic()

