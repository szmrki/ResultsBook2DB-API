"""
scripts/fetch_rule_sources.py

競技規則の原典（PDF）を、台帳 app/mcp/knowledge/rules/sources.yaml に従って
sources/rules/ にダウンロードするスクリプト。

原典の PDF は著作権のため公開リポジトリに置かない（sources/ は .gitignore 済み）。
そのため、作業する人がそれぞれの手元でこのスクリプトを実行して揃える。
台帳が「何をどこから取るか」の唯一の情報源で、このスクリプトはそれに従うだけ。

取得の順番:
    1. 元の URL（公式サイトに今も残っていれば、それが一番確か）
    2. Wayback Machine（元の URL が 404 になっている過去版はこちら）

Wayback Machine は Internet Archive が運営するウェブのアーカイブ。
URL に `id_` を付けると、閲覧用の枠（ツールバー）を付けずに、保存された元のファイルそのものを返す。
    閲覧用: https://web.archive.org/web/20231211164506/http://.../rule.pdf
    原本  : https://web.archive.org/web/20231211164506id_/http://.../rule.pdf

Wayback には同じ URL の保存版が複数あることが多く、古い保存版は 1 MiB で途中から切れていることがある
（当時の収集の上限と思われる）。そのため保存版の一覧（CDX API）を引き、サイズの大きい順に試す。
取得したファイルは「最後まであるか」（PDF の終端の印 %%EOF があるか）も確かめる。

旧 WCF サイト（〜2019）は /download/?dl=<記号> の形でファイルを配っていて、
URL からファイル名が作れない。
しかも同じ記号のまま中身が差し替えられていることがある（サイズの大きい保存版が目当ての版とは限らない）。
そのため台帳では次の項目を使えるようにしてある:
    filename: 保存するファイル名（URL から作れないとき）
    format:   pdf（既定） / doc（Word 形式。旧 Change Log の一部）
    archive:  保存日時まで（14 桁）書いてあれば、その保存版を最優先で試す

保存先:
    sources/rules/<publisher>/<ファイル名>
    （ファイル名は台帳の filename、無ければ url の末尾。分割版は parts に並んだ名前）

使い方:
  # 台帳の全件を取得（既にあるファイルは飛ばす）
  uv run python scripts/fetch_rule_sources.py

  # 特定の原典だけ取得（台帳の id を指定。複数可）
  uv run python scripts/fetch_rule_sources.py wcf-2021-rules wcf-2021-changes

  # 既にあるファイルも取り直す
  uv run python scripts/fetch_rule_sources.py --force
"""

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests
import yaml

# リポジトリのルート（このファイルは scripts/ にあるので1つ上）
REPO_ROOT = Path(__file__).resolve().parent.parent

# 台帳と保存先
LEDGER = REPO_ROOT / "app" / "mcp" / "knowledge" / "rules" / "sources.yaml"
DEST_ROOT = REPO_ROOT / "sources" / "rules"

# HTTP タイムアウト（秒）。PDF は数 MB あるので短すぎないようにする。
TIMEOUT = 120

# リクエストの間隔（秒）。公式サイトや Internet Archive に負荷をかけないための待ち時間。
REQUEST_INTERVAL = 3.0

# 一時的なエラー（5xx・タイムアウト）のときの再試行回数と、待ち時間の基準（秒）。
# 待ち時間は 1 回目 10 秒、2 回目 20 秒…と倍々に伸ばす（指数バックオフ）。
MAX_RETRIES = 3
BACKOFF_BASE = 10.0

# Wayback の保存版を試す最大件数（サイズの大きい順）
MAX_CAPTURES = 3

# 古い保存版が切れるときのサイズ（1 MiB ちょうど）
TRUNCATED_SIZE = 1024 * 1024

# 旧 Word 形式（.doc）のファイルの先頭に必ずある印（OLE 複合ファイルの署名）
DOC_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# サイトによってはブラウザ以外からのアクセスを弾くので、一般的なブラウザを名乗る。
HEADERS = {"User-Agent": "Mozilla/5.0 (rb2db rule-sources fetcher)"}


@dataclass
class Result:
    """1ファイル分の取得結果。

    Attributes:
        source_id: 台帳の id
        filename:  保存したファイル名
        status:    "original" / "wayback" / "skipped" / "missing" / "failed"
                   （missing は台帳の missing_parts に載っている既知の欠落）
        detail:    補足（失敗理由や取得元の URL）
    """

    source_id: str
    filename: str
    status: str
    detail: str = ""


def load_ledger(path: Path) -> list[dict]:
    """台帳（sources.yaml）を読み込んで、原典のリストを返す。

    Args:
        path: 台帳ファイルのパス

    Returns:
        原典ごとの辞書のリスト（id / publisher / url / archive / parts など）
    """
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)["sources"]


def filenames_of(source: dict) -> list[str]:
    """原典が持つファイル名の一覧を返す。

    分割版（parts あり）はその全部、filename の指定があればそれ、
    どちらも無ければ url の末尾のファイル名1つ。

    Args:
        source: 台帳の1件

    Returns:
        ファイル名のリスト
    """
    if source.get("parts"):
        return list(source["parts"])
    if source.get("filename"):
        return [source["filename"]]
    return [source["url"].rsplit("/", 1)[1]]


def replace_filename(url: str, filename: str) -> str:
    """URL の末尾のファイル名だけを差し替える。

    分割版は台帳に先頭のファイルの URL しか書いていないので、
    同じディレクトリにある残りのファイルの URL をこれで作る。

    Args:
        url:      元の URL（例: https://.../rule-2024-10-1-36.pdf）
        filename: 差し替えるファイル名（例: rule-2024-10-37-62.pdf）

    Returns:
        差し替え後の URL
    """
    return url.rsplit("/", 1)[0] + "/" + filename


def is_complete(content: bytes, fmt: str = "pdf") -> bool:
    """ファイルが目的の形式で、最後まで揃っているかを判定する。

    PDF は先頭が "%PDF"、末尾近くに終端の印 "%%EOF" がある決まり。
    途中で切れたファイルは "%%EOF" を持たない。念のため 1 MiB ちょうどのファイルも疑う。
    Word 形式（doc）は先頭の署名だけを確かめる（終端の印が無いので、切れていても判別しにくい）。

    Args:
        content: ファイルの中身
        fmt:     "pdf" か "doc"

    Returns:
        目的の形式で最後まで揃っていれば True
    """
    if len(content) == TRUNCATED_SIZE:
        return False
    if fmt == "doc":
        return content[:8] == DOC_SIGNATURE
    if content[:4] != b"%PDF":
        return False
    # 終端の印の後ろに改行などが少し付くことがあるので、末尾 1 KB の中を探す
    return b"%%EOF" in content[-1024:]


def wayback_candidates(source: dict, original_url: str) -> list[str]:
    """Wayback Machine から原本を取るための URL の候補を、試す順に返す。

    台帳の archive に保存日時が 14 桁で書いてあれば、それを最優先で試す
    （版を確かめて選んだ保存版）。
    続いて CDX API（保存版の一覧を返す API）で保存版を引き、サイズの大きい順に並べる。
    CDX の length は圧縮後のサイズだが、大小の比較には使える。
    CDX が使えないときは、台帳の archive にある日時（無ければ「どれでもよい」の "2"）を使う。
    Wayback は指定した日時に最も近い保存版に自動で飛ぶ。

    Args:
        source:       台帳の1件
        original_url: 取りたいファイルの元の URL

    Returns:
        `id_` 付きの Wayback の URL のリスト
    """

    # URL に `id_` を付けると、閲覧用の枠を付けずに原本そのものを返す
    def raw(timestamp: str) -> str:
        return f"https://web.archive.org/web/{timestamp}id_/{original_url}"

    # archive の <日時> 部分。https://web.archive.org/web/<日時>/<元のURL> の形
    m = re.match(r"https?://web\.archive\.org/web/(\d+)", source.get("archive", ""))
    ledger_ts = m.group(1) if m else ""
    pinned = [raw(ledger_ts)] if len(ledger_ts) == 14 else []

    try:
        resp = requests.get(
            "http://web.archive.org/cdx/search/cdx",
            params={
                "url": original_url,
                "filter": "statuscode:200",  # 正常に保存できたものだけ
                "fl": "timestamp,length",  # 欲しい列: 保存日時とサイズ
            },
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        rows = [line.split() for line in resp.text.splitlines() if line.strip()]
        # 1行は "<日時> <サイズ>"。数字でない行（エラーページなど）は捨てる
        captures = [(ts, int(n)) for ts, n in rows if ts.isdigit() and n.isdigit()]
    except (requests.RequestException, ValueError):
        captures = []

    if captures:
        captures.sort(key=lambda c: c[1], reverse=True)  # サイズの大きい順
        by_size = [raw(ts) for ts, _ in captures[:MAX_CAPTURES]]
        return pinned + [u for u in by_size if u not in pinned]

    # CDX が使えなかったときの予備: 台帳の archive の日時（無ければ "2"）を使う
    return pinned or [raw(ledger_ts or "2")]


def download(url: str, fmt: str = "pdf") -> bytes | None:
    """URL からファイルを取得する。目的の形式でない・途中で切れている場合は None を返す。

    一時的なエラー（5xx・タイムアウト・接続エラー）は、間隔を空けて再試行する。
    404 などは再試行しても変わらないので、すぐに諦める。

    Args:
        url: 取得する URL
        fmt: "pdf" か "doc"

    Returns:
        ファイルの中身（バイト列）。取得できない・目的の形式でない場合は None
    """
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            resp = None  # タイムアウト・接続エラーは一時的なものとして再試行する

        if resp is not None and resp.status_code < 500:
            # 2xx でも中身が PDF とは限らない（エラーページの HTML が返ることがある）。
            # 途中で切れた PDF も使えないので、最後まで揃っているかまで確かめる。
            if resp.ok and is_complete(resp.content, fmt):
                return resp.content
            return None

        # ここに来るのは 5xx か通信エラー。最後の試行でなければ待ってからやり直す。
        if attempt < MAX_RETRIES:
            wait = BACKOFF_BASE * (2**attempt)
            print(
                f"    一時的なエラー。{wait:.0f} 秒待って再試行します"
                f"（{attempt + 1}/{MAX_RETRIES}）"
            )
            time.sleep(wait)
    return None


def fetch_source(source: dict, force: bool) -> list[Result]:
    """原典1件（分割版なら全ファイル）を取得して保存する。

    Args:
        source: 台帳の1件
        force:  True なら既にあるファイルも取り直す

    Returns:
        ファイルごとの取得結果
    """
    results: list[Result] = []
    dest_dir = DEST_ROOT / source["publisher"]
    dest_dir.mkdir(parents=True, exist_ok=True)

    for filename in filenames_of(source):
        dest = dest_dir / filename
        # 既にあっても、途中で切れているファイルは取り直す
        fmt = source.get("format", "pdf")
        if dest.exists() and not force and is_complete(dest.read_bytes(), fmt):
            results.append(Result(source["id"], filename, "skipped", "既にあります"))
            continue

        # filename を指定した原典は URL がファイル名と無関係なので、url をそのまま使う
        if source.get("filename"):
            original_url = source["url"]
        else:
            original_url = replace_filename(source["url"], filename)
        print(f"  {source['id']}: {filename}")

        # 1. 元の URL
        content = download(original_url, fmt)
        status = "original"
        time.sleep(REQUEST_INTERVAL)

        # 2. Wayback Machine（保存版をサイズの大きい順に試す）
        if content is None:
            status = "wayback"
            for url in wayback_candidates(source, original_url):
                time.sleep(REQUEST_INTERVAL)
                content = download(url, fmt)
                if content is not None:
                    break

        if content is None:
            # 台帳で「取得できない」と分かっているファイルは失敗扱いにしない
            if filename in source.get("missing_parts", []):
                reason = "既知の欠落（台帳の missing_parts）"
                results.append(Result(source["id"], filename, "missing", reason))
            else:
                reason = "元の URL・Wayback とも取得できず"
                results.append(Result(source["id"], filename, "failed", reason))
            continue

        dest.write_bytes(content)
        size_kb = len(content) / 1024
        results.append(Result(source["id"], filename, status, f"{size_kb:,.0f} KB"))
    return results


def print_summary(results: list[Result]) -> None:
    """取得結果を一覧で表示する。

    Args:
        results: 全ファイルの取得結果

    Returns:
        None
    """
    labels = {
        "original": "取得（元の URL）",
        "wayback": "取得（Wayback）",
        "skipped": "スキップ",
        "missing": "欠落（既知）",
        "failed": "失敗",
    }
    print("\n=== 結果 ===")
    for r in results:
        print(f"{labels[r.status]:<16} {r.source_id:<18} {r.filename}  {r.detail}")

    failed = [r for r in results if r.status == "failed"]
    print(f"\n合計 {len(results)} ファイル / 失敗 {len(failed)}")
    if failed:
        print("失敗した原典は、台帳の archive の URL をブラウザで開いて保存版を確認してください。")


def main() -> int:
    """コマンドライン引数を解釈して取得を実行する。

    Returns:
        終了コード（失敗が1件でもあれば 1、なければ 0）
    """
    parser = argparse.ArgumentParser(description="競技規則の原典 PDF を台帳に従って取得する")
    parser.add_argument("ids", nargs="*", help="取得する原典の id（省略時は全件）")
    parser.add_argument("--force", action="store_true", help="既にあるファイルも取り直す")
    args = parser.parse_args()

    sources = load_ledger(LEDGER)
    if args.ids:
        unknown = set(args.ids) - {s["id"] for s in sources}
        if unknown:
            print(f"台帳にない id です: {', '.join(sorted(unknown))}")
            return 1
        sources = [s for s in sources if s["id"] in args.ids]

    print(f"保存先: {DEST_ROOT.relative_to(REPO_ROOT)}/")
    results: list[Result] = []
    for source in sources:
        results.extend(fetch_source(source, args.force))

    print_summary(results)
    return 1 if any(r.status == "failed" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
