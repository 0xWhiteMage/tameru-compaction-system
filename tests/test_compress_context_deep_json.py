from tameru.compress_context import compress_context


def test_deeply_nested_embedded_json_keeps_original_text():
    text = "Build result: " + '{"child":' * 1100 + "0" + "}" * 1100

    assert compress_context(text, "artifact-release", ccr=False).compressed_text == text
