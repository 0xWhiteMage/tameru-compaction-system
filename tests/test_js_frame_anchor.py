from tameru.compress_context import _strip_anchor_prefix, compress_context


def test_node_frame_anchor_strips_numbers():
    out = _strip_anchor_prefix("at TCPConnectWrap.afterConnect [as oncomplete] (node:net:1555:16) {")
    assert "(node:net)" in out
    assert "1555" not in out


def test_ts_frame_anchor_keeps_path():
    out = _strip_anchor_prefix("at handler (/app/src/routes/user.ts:42:7)")
    assert out == "at handler (/app/src/routes/user.ts:42:7)"


def test_bare_js_frame_anchor_strips_numbers():
    assert _strip_anchor_prefix("at /app/node_modules/express/lib/router/index.js:284:15") == "at /app/node_modules/express/lib/router/index.js"
    assert _strip_anchor_prefix("at /app/src/server.js:12:5") == "at /app/src/server.js:12:5"
    out = _strip_anchor_prefix("at processTicksAndRejections (node:internal/process/task_queues:95:5)")
    assert "(node:internal/process/task_queues)" in out


def test_jvm_anchor_still_works():
    out = _strip_anchor_prefix("at com.acme.Foo.bar(Foo.java:88)")
    assert "(Foo.java)" in out


def test_js_frame_anchor_does_not_keep_access_log():
    text = (
        "\n".join(f"[{i}] GET /api/items 200 {100 + i}ms" for i in range(30))
        + "\nnode:internal/process/promises:289\n"
        "            triggerUncaughtException(err, true /* fromPromise */);\n"
        "            ^\n\n"
        "Error: connect ECONNREFUSED 127.0.0.1:6379\n"
        "    at TCPConnectWrap.afterConnect [as oncomplete] (node:net:1555:16) {\n"
        "  errno: -111,\n"
        "  code: 'ECONNREFUSED',\n"
        "  syscall: 'connect'\n}\n"
    )
    r = compress_context(text, "", ccr=False, citations=False, anchor_errors=True)
    assert "ECONNREFUSED 127.0.0.1:6379" in r.compressed_text
    assert "[16] GET" not in r.compressed_text
