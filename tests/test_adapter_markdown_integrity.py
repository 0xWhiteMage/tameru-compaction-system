import pytest

from tameru.format_adapters import adapt_format


def markdown(text, query="needle"):
    return adapt_format(text, query, format_name="markdown")


@pytest.mark.parametrize("fence", ["````", "~~~~"])
def test_shorter_fence_cannot_expose_a_heading_inside_code(fence):
    text = f"# Intro\n{fence}\nquiet\n{fence[:3]}\n# needle\ninside\n{fence}\n# Other\nquiet"
    result = markdown(text)
    assert result.applied
    assert f"{fence}\nquiet\n{fence[:3]}\n# needle\ninside\n{fence}" in result.text


def test_fence_with_trailing_text_is_not_a_closing_fence():
    text = "# Intro\n```\nquiet\n``` not a close\n# needle\ninside\n```\n# Other\nquiet"
    assert "``` not a close\n# needle\ninside\n```" in markdown(text).text


def test_unterminated_fence_preserves_the_original():
    text = "# needle\nanswer\n# Other\n```\nquiet"
    result = markdown(text)
    assert not result.applied
    assert result.text == text


def test_repeated_heading_text_preserves_each_ancestor_path():
    text = "# A\n## shared\n### needle1\nanswer1\n# B\n## shared\n### needle2\nanswer2\n# C\nquiet"
    result = markdown(text, "needle1 needle2")
    assert result.applied
    assert "# B\n## shared\n\n### needle2" in result.text
    assert result.text.count("## shared") == 2


def test_shared_ancestor_is_emitted_once_for_sibling_matches():
    result = markdown("# A\n## needle1\na\n## needle2\nb\n# Other\nquiet", "needle1 needle2")
    assert result.text.count("# A") == 1


def test_empty_markdown_is_unchanged():
    assert markdown("").text == ""
