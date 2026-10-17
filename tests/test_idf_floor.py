from tameru.compress_context import compress_context


def test_idf_floor_drops_ubiquitous_server_term():
    lines = [f"[server] GET /api/items/{i} 200 {i}ms" for i in range(400)]
    lines.append(
        "[server] TypeError: Cannot read properties of undefined (reading 'id')\n"
        "    at handler (/app/src/routes.js:42:17)"
    )
    text = "\n".join(lines)

    result = compress_context(
        text,
        ["why does the server crash"],
        ccr=False,
        citations=False,
        min_savings_ratio=0.1,
    )

    assert "routes.js:42:17" in result.compressed_text
    assert "TypeError" in result.compressed_text
    assert len(result.compressed_text) < 0.5 * len(text)
