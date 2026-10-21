from tameru.compress_context import compress_context, segment_blocks


def test_collapse_lead_block_segmentation():
    blocks = segment_blocks(
        [
            "[\u00d730] [0] GET /a 200 1ms",
            "[last] [29] GET /a 200 2ms",
            "node:internal/process/promises:289",
            "    triggerUncaughtException(err);",
        ]
    )
    assert "node:internal" not in blocks[0]["text"]


def test_error_anchored_query_drops_collapse_lead_block():
    text = "\n".join(f"[{i}] GET /api/items 200 {100 + i}ms" for i in range(30)) + (
        "\nnode:internal/process/promises:289\n"
        "            triggerUncaughtException(err, true /* fromPromise */);\n"
        "            ^\n"
        "\n"
        "Error: connect ECONNREFUSED 127.0.0.1:6379\n"
        "    at TCPConnectWrap.afterConnect [as oncomplete] (node:net:1555:16) {\n"
        "  errno: -111,\n"
        "  code: 'ECONNREFUSED',\n"
        "  syscall: 'connect'\n"
        "}\n"
    )
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert "ECONNREFUSED 127.0.0.1:6379" in r.compressed_text
    assert "GET /api/items" not in r.compressed_text


def test_query_hit_collapse_lead_block_kept():
    text2 = "\n".join(f"[{i}] GET /api/items 200 {100 + i}ms" for i in range(30)) + (
        "\n\nunrelated paragraph about lunch\n"
    )
    r2 = compress_context(text2, "GET /api/items", ccr=False, citations=False)
    assert "GET /api/items" in r2.compressed_text
