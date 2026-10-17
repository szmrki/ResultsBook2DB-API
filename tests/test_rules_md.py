"""
競技規則の変遷データ（app/mcp/knowledge/rules/*.yaml）と、そこから生成する rules.md のテスト。

rules.md は scripts/generate_rules_md.py が YAML から生成し、MCP リソース rb2db://rules と
/v1/notes/rules で配信している。YAML が唯一の情報源なので、次の3点を守りたい。

  1. YAML の参照が切れていないこと（存在しない版・トピック・原典を指していない）
  2. rules.md が YAML と食い違っていないこと（YAML を直して生成し忘れると、古い内容が配信される）
  3. 「確認済み」の版に、人が確認していない変更点が残っていないこと
"""

from scripts import generate_rules_md as gen


def test_yaml_references_are_valid() -> None:
    """YAML の参照が切れていないことを確認する。

    load_all() は参照切れがあると ValueError を投げるので、例外が出なければ合格。
    """
    # Act
    sources, editions, topics, changes = gen.load_all()

    # Assert: 中身が空でないこと（読み込み自体が空振りしていないか）
    assert sources and editions and topics and changes


def test_rules_md_is_up_to_date() -> None:
    """rules.md が YAML から生成した内容と一致することを確認する。

    失敗したら `uv run python scripts/generate_rules_md.py` で生成し直してコミットする。
    """
    # Arrange: いまの YAML から生成した内容
    expected = gen.render()

    # Act: リポジトリに置かれている rules.md
    actual = gen.OUTPUT.read_text(encoding="utf-8")

    # Assert
    assert actual == expected, "rules.md が古い。scripts/generate_rules_md.py で生成し直すこと"


def test_full_editions_have_only_verified_changes() -> None:
    """確認状況が full の版の変更点が、すべて verified: true であることを確認する。

    full は「全変更点を人が確認済み」の意味なので、未確認の変更点が残っていたら矛盾。
    """
    # Arrange
    _sources, editions, _topics, changes = gen.load_all()

    # Act: full の版に属する、未確認の変更点を集める
    unverified = [
        f"{c['edition']}/{c['topic']}"
        for c in changes
        if editions[c["edition"]]["coverage"] == "full" and not c.get("verified")
    ]

    # Assert
    assert unverified == [], f"確認済みの版に未確認の変更点がある: {unverified}"
