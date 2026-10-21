from tameru.compress_context import _prose_key, compress_context


def test_prose_key_digit_runs_and_nfkc():
    assert _prose_key("議事録 0: なし") == _prose_key("議事録 10: なし")
    assert _prose_key("１２月：会議") == _prose_key("12月:会議")
    assert _prose_key("Chapter 3 intro") == _prose_key("Chapter 12 intro")


def test_prose_brief_ja_minutes():
    text = (
        "\n\n".join(f"議事録 {i}: 議論のみ、決定事項なし。" for i in range(12))
        + "\n\n決定: 2026-12-01 から旧APIを停止する。\n\n閉会。\n\n閉会。"
    )
    result = compress_context(text, "", ccr=False, citations=False, prose_brief=True)
    assert not result.fail_open
    assert "2026-12-01" in result.compressed_text
    assert "旧API" in result.compressed_text
    assert "議事録 10" not in result.compressed_text
    assert result.compressed_text.count("閉会。") == 1


def test_prose_brief_zh_minutes():
    text = (
        "\n\n".join(f"第{i}次例会：仅讨论，无结论。" for i in range(12))
        + "\n\n结论：数据库将于2026年11月30日迁移到新集群。\n\n散会。\n\n散会。"
    )
    result = compress_context(text, "", ccr=False, citations=False, prose_brief=True)
    assert not result.fail_open
    assert "2026年11月30日" in result.compressed_text
    assert "新集群" in result.compressed_text
    assert "第10次" not in result.compressed_text
    assert result.compressed_text.count("散会。") == 1


def test_prose_brief_ko_minutes():
    text = (
        "\n\n".join(f"{i}차 회의: 논의만 하고 결정 없음." for i in range(12))
        + "\n\n결정: 결제 서버는 2026-11-15에 교체한다.\n\n회의 종료.\n\n회의 종료."
    )
    result = compress_context(text, "", ccr=False, citations=False, prose_brief=True)
    assert not result.fail_open
    assert "2026-11-15" in result.compressed_text
    assert "결제 서버" in result.compressed_text
    assert result.compressed_text.count("회의 종료.") == 1


def test_prose_brief_repeated_data_paragraph_kept():
    text = "\n\n".join(
        ["Status: nothing new."] * 10
        + ["Status: nothing new. Revenue 12% up.", "End."]
    )
    result = compress_context(text, "", ccr=False, citations=False, prose_brief=True)
    assert not result.fail_open
    assert "12%" in result.compressed_text
