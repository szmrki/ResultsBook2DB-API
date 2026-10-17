"""
scripts/generate_rules_md.py

競技規則の変遷データ（app/mcp/knowledge/rules/*.yaml）から、
利用者向けの Markdown（app/mcp/knowledge/rules.md）を生成するスクリプト。

なぜ生成するのか:
    規則の変遷は「版」「トピック」「変更点」「原典」の4種類の YAML に分けて持っている。
    人が書いて確認するにはこの形が扱いやすいが、利用者（AI を含む）が読むには
    「トピックごとの年表」のような1つの文書になっている方が分かりやすい。
    YAML を唯一の情報源にして Markdown はそこから作ることで、二重管理を避ける。

生成した rules.md は、MCP リソース rb2db://rules と REST API の /v1/notes/rules で配信する。
rules.md を直接編集しても、次に生成したときに上書きされるので、必ず YAML の方を直すこと。

使い方:
  # rules.md を生成し直す（YAML を直したら必ず実行する）
  uv run python scripts/generate_rules_md.py

  # rules.md が YAML と食い違っていないか確認だけする（食い違っていれば終了コード 1）
  uv run python scripts/generate_rules_md.py --check
"""

import argparse
import re
import sys
from pathlib import Path

import yaml

# リポジトリのルート（このファイルは scripts/ にあるので1つ上）
REPO_ROOT = Path(__file__).resolve().parent.parent

# 入力（YAML のディレクトリ）と出力（配信する Markdown）
RULES_DIR = REPO_ROOT / "app" / "mcp" / "knowledge" / "rules"
OUTPUT = REPO_ROOT / "app" / "mcp" / "knowledge" / "rules.md"

# 表示用の対応表 ─────────────────────────────────────────────────────────
# YAML には短い英語の値で持ち、表示するときに日本語にする。

DISCIPLINE_LABELS = {"four": "4人制", "md": "MD", "both": "4人制・MD 共通"}

TYPE_LABELS = {
    "introduced": "導入",
    "modified": "変更",
    "removed": "廃止",
    "trial": "試験導入",
    "split": "分割",
    "merged": "統合",
}

COVERAGE_LABELS = {
    "full": "確認済み",
    "major_only": "主要トピックのみ",
    "drafted": "確認待ち",
    "pending": "未着手",
    "missing": "原典なし",
}

# データ分析への影響の大きさの並び順（high を先に出す）
RELEVANCE_ORDER = {"high": 0, "medium": 1, "low": 2}


def load_yaml(name: str) -> dict:
    """rules/ 配下の YAML を1つ読み込む。

    Args:
        name: ファイル名（例: "changes.yaml"）

    Returns:
        YAML の中身（辞書）
    """
    with (RULES_DIR / name).open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_all() -> tuple[list[dict], dict[str, dict], dict[str, dict], list[dict]]:
    """4種類の YAML を読み込み、参照が切れていないかを確かめて返す。

    Returns:
        (sources, editions, topics, changes) のタプル。
        editions と topics は id をキーにした辞書（参照しやすくするため）。

    Raises:
        ValueError: 変更点や版が、存在しない版・トピック・原典を参照している場合
    """
    sources = load_yaml("sources.yaml")["sources"]
    editions = {e["id"]: e for e in load_yaml("editions.yaml")["editions"]}
    topics = {t["id"]: t for t in load_yaml("topics.yaml")["topics"]}
    changes = load_yaml("changes.yaml")["changes"]

    # 参照切れを集めて、まとめて報告する（1つずつ直すより早い）
    source_ids = {s["id"] for s in sources}
    errors: list[str] = []
    for e in editions.values():
        errors += [
            f"{e['id']}: 原典 {s} がない" for s in e.get("sources", []) if s not in source_ids
        ]
    for c in changes:
        label = f"変更点 {c['edition']}/{c['topic']}"
        if c["edition"] not in editions:
            errors.append(f"{label}: 版 {c['edition']} がない")
        if c["topic"] not in topics:
            errors.append(f"{label}: トピック {c['topic']} がない")
        if c["source"]["doc"] not in source_ids:
            errors.append(f"{label}: 原典 {c['source']['doc']} がない")
    if errors:
        raise ValueError("YAML の参照が切れています:\n  " + "\n  ".join(errors))
    return sources, editions, topics, changes


def edition_sort_key(edition_id: str) -> str:
    """版を年の順に並べるためのキー（"wcf-2017" → "2017"）。

    Args:
        edition_id: 版の id

    Returns:
        並べ替え用の文字列
    """
    return edition_id.split("-", 1)[1]


def edition_label(edition: dict) -> str:
    """版の表示名を返す（例: "2017 年 10 月版"）。

    document_date があれば年月で、無ければ年だけで表す。

    Args:
        edition: editions.yaml の1件

    Returns:
        表示名
    """
    date = str(edition.get("document_date", ""))
    if len(date) >= 7:  # "2017-10" や "2026-09-01"
        return f"{date[:4]} 年 {int(date[5:7])} 月版"
    return f"{edition_sort_key(edition['id'])} 年版"


def sentence(text: str) -> str:
    """YAML の折り返し（>-）で入った余分な空白を除き、1行の文にする。

    YAML の >- は改行を空白1つに置き換えるため、日本語の途中で折り返すと
    「から、 4 フィート」のような不要な空白が入る。句読点・括弧の直後の空白と、
    日本語の文字どうしの間の空白を取り除く（「5 投目」のような数字と日本語の間の空白は残す）。

    Args:
        text: YAML から読んだ文字列

    Returns:
        1行にまとめ、不要な空白を除いた文字列
    """
    s = " ".join(str(text).split())
    s = re.sub(r"(?<=[、。「」（）]) ", "", s)  # 句読点・括弧の直後
    s = re.sub(r"(?<=[^\x00-\x7f]) (?=[^\x00-\x7f])", "", s)  # 日本語どうしの間
    return s


def render_header() -> list[str]:
    """文書の冒頭（目的・読み方）を作る。

    Returns:
        Markdown の行のリスト
    """
    return [
        "# rb2db 競技規則の変遷",
        "",
        "<!-- このファイルは scripts/generate_rules_md.py が app/mcp/knowledge/rules/*.yaml から"
        "生成している。直接編集せず、YAML を直して生成し直すこと。 -->",
        "",
        "Results Book に記録される値（盤面・投球・得点）や、その解釈に影響する"
        "競技規則の変更だけをまとめたもの。",
        "**時期をまたいで集計・比較する前に、間に規則変更が挟まっていないかをここで確かめること。**",
        "",
        "- 対象外: スウィーピング・ブラシ、服装、まれな反則への罰則、手続きの細かな変更など"
        "（記録に表れないもの）",
        "- 一次情報源は WCF（World Curling）の規則書。"
        "WCF 版が見つからない年は JCA（日本カーリング協会）の"
        "日本語版で補っている",
        "- 収録範囲は WCF 2011 年 6 月版〜2026 年 9 月版（§3 の版の一覧を参照）",
        "",
        "---",
        "",
    ]


def render_boundaries(
    editions: dict[str, dict], topics: dict[str, dict], changes: list[dict]
) -> list[str]:
    """§1: 影響の大きい変更（relevance: high のトピック）の一覧表を作る。

    Args:
        editions: 版（id → 版）
        topics:   トピック（id → トピック）
        changes:  変更点のリスト

    Returns:
        Markdown の行のリスト
    """
    lines = [
        "## 1. 集計で必ず気をつける境目",
        "",
        "| 版 | 対象 | トピック | 種別 | 内容 |",
        "|---|---|---|---|---|",
    ]
    high = [c for c in changes if topics[c["topic"]]["relevance"] == "high"]
    for c in sorted(high, key=lambda c: edition_sort_key(c["edition"])):
        t = topics[c["topic"]]
        lines.append(
            f"| {edition_label(editions[c['edition']])} "
            f"| {DISCIPLINE_LABELS[t['discipline']]} "
            f"| {t['name_ja']} | {TYPE_LABELS[c['type']]} | {sentence(c['summary_ja'])} |"
        )
    lines += [
        "",
        "それぞれのデータへの影響（どの大会が境目のどちら側か）は §2 を参照。",
        "",
        "---",
        "",
    ]
    return lines


def render_timelines(
    editions: dict[str, dict], topics: dict[str, dict], changes: list[dict]
) -> list[str]:
    """§2: トピックごとの年表を作る。変更のないトピックは最後にまとめる。

    Args:
        editions: 版（id → 版）
        topics:   トピック（id → トピック）
        changes:  変更点のリスト

    Returns:
        Markdown の行のリスト
    """
    lines = ["## 2. トピックごとの年表", ""]

    # 影響の大きい順、同じなら topics.yaml の並び順
    order = list(topics)
    ordered = sorted(
        topics.values(), key=lambda t: (RELEVANCE_ORDER[t["relevance"]], order.index(t["id"]))
    )

    unchanged: list[dict] = []
    for t in ordered:
        items = sorted(
            (c for c in changes if c["topic"] == t["id"]),
            key=lambda c: edition_sort_key(c["edition"]),
        )
        if not items:
            unchanged.append(t)
            continue
        lines += [
            f"### {t['name_ja']}（{t['name_en']}）",
            "",
            f"対象: {DISCIPLINE_LABELS[t['discipline']]}。{sentence(t['description'])}",
            "",
        ]
        for c in items:
            src = c["source"]
            where = " ".join(
                str(x)
                for x in (src.get("rule"), f"p.{src['page']}" if src.get("page") else None)
                if x
            )
            lines.append(
                f"- **{edition_label(editions[c['edition']])}**（{TYPE_LABELS[c['type']]}）"
                f" {sentence(c['summary_ja'])}"
            )
            if c.get("before"):
                lines.append(f"  - 変更前: {sentence(c['before'])}")
            if c.get("after"):
                lines.append(f"  - 変更後: {sentence(c['after'])}")
            lines.append(f"  - データへの影響: {sentence(c['data_impact'])}")
            lines.append(f"  - 出典: {src['doc']}（{where}）")
        lines.append("")

    if unchanged:
        lines += [
            "### 記録に影響する変更が見つかっていないトピック",
            "",
            "確認済みの版（§3）の範囲では、次のトピックに記録へ影響する変更はなかった。",
            "",
        ]
        for t in unchanged:
            lines.append(
                f"- {t['name_ja']}（{DISCIPLINE_LABELS[t['discipline']]}）: "
                f"{sentence(t['description'])}"
            )
        lines.append("")
    lines += ["---", ""]
    return lines


def render_editions(editions: dict[str, dict], changes: list[dict]) -> list[str]:
    """§3: 版の一覧表を作る。

    Args:
        editions: 版（id → 版）
        changes:  変更点のリスト

    Returns:
        Markdown の行のリスト
    """
    lines = [
        "## 3. 版の一覧",
        "",
        "「確認済み」の版で §2 に記載がないトピックは、"
        "その版で記録に影響する変更がなかったことを表す。",
        "「主要トピックのみ」の版は調査の起点で、それより前からの変更は調べていない。",
        "",
        "| 版 | 対応する JCA 版 | 確認状況 | 記録に影響する変更 |",
        "|---|---|---|---|",
    ]
    for eid in sorted(editions, key=edition_sort_key):
        e = editions[eid]
        n = sum(1 for c in changes if c["edition"] == eid)
        jca = e.get("jca_edition", "—")
        lines.append(f"| {edition_label(e)} | {jca} | {COVERAGE_LABELS[e['coverage']]} | {n} 件 |")
    lines += [
        "",
        "- 表紙の日付を施行日の目安としている（本文に施行日の明記がない版がほとんど）。"
        "例外は §2 に書いてある"
        "（5 ロックルールは 2017 年 10 月版で決まり 2018 年 10 月から適用、など）",
        "- JCA 版の年月は日本語版の公開時期で、WCF の施行日とは別物",
        "",
        "---",
        "",
    ]
    return lines


def render_event_mapping() -> list[str]:
    """§4: 大会と版の対応づけの考え方を作る（固定の文章）。

    Returns:
        Markdown の行のリスト
    """
    return [
        "## 4. 大会と版の対応づけ",
        "",
        "`events` には大会の年（`year`）しかなく、開始日がない"
        "（追加予定: szmrki/ResultsBook2DB#30）。"
        "そのため現状は、大会の開催時期と版の日付を比べて判断する。",
        "",
        "- 規則は毎年秋に改定される。秋に開催される大会（ECC・PCCC など）はその年の版、"
        "冬〜春に開催される大会（OWG・WMCC・WWCC・WJCC・WMDCC など）は前年秋の版で行われる、が目安",
        "- 境目に近い大会は §2 の「データへの影響」に大会名で書いてある",
        "",
        "---",
        "",
    ]


def render_sources(sources: list[dict]) -> list[str]:
    """§5: 原典の一覧を作る。

    Args:
        sources: 原典のリスト

    Returns:
        Markdown の行のリスト
    """
    kind_labels = {
        "rules": "規則書",
        "changes": "変更箇所を示した版",
        "notice": "改定案内",
        "trial": "試験ルール",
    }
    lines = [
        "## 5. 原典",
        "",
        "§2 の「出典」の ID と対応する。"
        "元の URL が消えているものは Wayback Machine の保存版を載せている。",
        "",
    ]
    for s in sources:
        name = s.get("title") or kind_labels.get(s["kind"], s["kind"])
        link = s.get("archive") if s.get("status") != "live" and s.get("archive") else s["url"]
        lines.append(f"- `{s['id']}`（{s['publisher'].upper()}・{name}）: {link}")
    lines.append("")
    return lines


def render() -> str:
    """rules.md の本文を組み立てて返す。

    Returns:
        Markdown の本文（末尾に改行1つ）
    """
    sources, editions, topics, changes = load_all()
    lines = (
        render_header()
        + render_boundaries(editions, topics, changes)
        + render_timelines(editions, topics, changes)
        + render_editions(editions, changes)
        + render_event_mapping()
        + render_sources(sources)
    )
    return "\n".join(lines).rstrip("\n") + "\n"


def main() -> int:
    """コマンドライン引数を解釈して、生成または確認を行う。

    Returns:
        終了コード（--check で食い違っていれば 1、それ以外は 0）
    """
    parser = argparse.ArgumentParser(description="規則の変遷データから rules.md を生成する")
    parser.add_argument(
        "--check",
        action="store_true",
        help="生成はせず、rules.md が YAML と食い違っていないか確認する",
    )
    args = parser.parse_args()

    content = render()
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != content:
            print(
                "rules.md が YAML と食い違っています。"
                "uv run python scripts/generate_rules_md.py で生成し直してください。"
            )
            return 1
        print("rules.md は最新です。")
        return 0

    OUTPUT.write_text(content, encoding="utf-8")
    print(f"生成しました: {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
