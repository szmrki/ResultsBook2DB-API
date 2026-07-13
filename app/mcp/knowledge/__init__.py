"""同梱する知識ドキュメント（Markdown）を読み込むためのヘルパ。

このパッケージ直下の *.md を MCP リソースとして配信する。
memo/ 配下のドキュメントは Git 管理外のため、配布・Docker ビルドに確実に
含まれるよう、MCP が参照する知識はこのパッケージ内に複製して持つ。
"""

from importlib.resources import files


def load(name: str) -> str:
    """このパッケージ内の Markdown ファイルを文字列として読み込む。

    Args:
        name: ファイル名（例: "schema.md"）。

    Returns:
        ファイルの内容（UTF-8）。
    """
    return files(__package__).joinpath(name).read_text(encoding="utf-8")
