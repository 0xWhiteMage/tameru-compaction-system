import pytest

from tameru.agent_formats import DIAGNOSTIC_LINE_RE
from tameru.format_adapters import detect_format
from tameru.compress_context import error_fingerprints

POSITIVE = [
    "src/net/socket.c:58:12: error: 'addrlen' undeclared",
    "src/services/billing.ts(112,7): error TS2322: Type",
    "error[E0382]: borrow of moved value: `config`",
    "e: file:///src/main/kotlin/com/acme/Pricing.kt:23:31 Type mismatch",
    "thread 'tests::parse_header' panicked at src/parser.rs:144:9:",
    "PHP Fatal error:  Uncaught Error: Call to a member function fetch() on bool",
    "NoMethodError (undefined method `price' for nil:NilClass):",
    'Thread 1 "server" received signal SIGSEGV, Segmentation fault.',
    "     Failure/Error: expect(invoice.total).to eq(110)",
    "OrderServiceTest > shouldApplyDiscount() FAILED",
    "    at getUser (/app/src/routes/users.js:31:24)",
    "2026-10-17 11:00:00 エラー 決済サービスへの接続に失敗しました",
    "[2026-10-17 11:00:00] 错误: 数据库连接池已耗尽",
    "2026-10-17 11:00:00 오류 파일 업로드 실패",
    "2026-10-17 11:00:00 FEHLER Zahlung abgelehnt",
]

NEGATIVE = [
    "def error_handler(x):",
    "the error rate is low",
    "Compiling dep v0.1.0",
    "INFO request handled in 12ms",
    "key: value",
    "a,b,c",
]

@pytest.mark.parametrize("line", POSITIVE)
def test_diagnostic_line_re_matches(line):
    assert DIAGNOSTIC_LINE_RE.search(line) is not None

@pytest.mark.parametrize("line", NEGATIVE)
def test_diagnostic_line_re_negative(line):
    assert DIAGNOSTIC_LINE_RE.search(line) is None

GRADLE = (
    "> Task :app:test\n\n"
    "OrderServiceTest > shouldApplyDiscount() FAILED\n"
    "    org.opentest4j.AssertionFailedError: expected: <90.0> but was: <100.0>\n"
    "        at app//com.acme.OrderServiceTest.shouldApplyDiscount(OrderServiceTest.java:52)\n\n"
    "* What went wrong:\n"
    "Execution failed for task ':app:test'.\n"
    "> There were failing tests.\n\n"
    "BUILD FAILED in 41s"
)

RSPEC = (
    "Failures:\n\n"
    "  1) Invoice#total applies tax\n"
    "     Failure/Error: expect(invoice.total).to eq(110)\n\n"
    "       expected: 110\n"
    "            got: 100\n"
    "     # ./spec/models/invoice_spec.rb:19:in `block (2 levels)'\n\n"
    "1001 examples, 1 failure"
)

def test_gradle_not_yaml():
    assert detect_format(GRADLE) != "yaml"

def test_rspec_not_yaml():
    assert detect_format(RSPEC) != "yaml"

def test_comma_log_not_csv():
    lines = [f"2026-10-17 10:00:00,123 INFO worker: batch {i} ok" for i in range(100)]
    text = "\n".join(lines) + "\nTraceback (most recent call last):\n  File \"/srv/app/h.py\", line 57, in handle\n    x = a / b\nZeroDivisionError: division by zero"
    assert detect_format(text) not in ("csv", "tsv")

def test_real_csv_still_csv():
    rows = [f"{i},item{i},{i}" for i in range(50)]
    text = "id,name,qty\n" + "\n".join(rows)
    assert detect_format(text) == "csv"

def test_error_fingerprints_multilang():
    samples = [
        "src/net/socket.c:58:12: error: 'addrlen' undeclared",
        "src/services/billing.ts(112,7): error TS2322: Type",
        "error[E0382]: borrow of moved value: `config`",
        "2026-10-17 11:00:00 エラー 決済サービスへの接続に失敗しました",
    ]
    for text in samples:
        assert error_fingerprints(text)
    assert error_fingerprints("0 errors, build ok\nsrc/a.c:1:1: warning: 0 errors") == {}


def test_ruby_frame_is_diagnostic():
    assert DIAGNOSTIC_LINE_RE.search("app/models/order.rb:33:in `subtotal'") is not None


def test_indented_assertion_values_are_diagnostic():
    assert DIAGNOSTIC_LINE_RE.search("       expected: 110") is not None
    assert DIAGNOSTIC_LINE_RE.search("    Received: 1") is not None
    assert DIAGNOSTIC_LINE_RE.search("expected: 110") is None


def test_rails_error_line_survives():
    from tameru.compress_context import compress_context

    text = "\n".join(
        f'Started GET "/products/{i}" for 10.0.0.1 at 2026-10-17 10:00:{i % 60:02d} +0000\n'
        f"Completed 200 OK in {i * 13 % 900}ms (Views: 3.1ms | ActiveRecord: 1.2ms)"
        for i in range(70)
    ) + (
        '\nStarted POST "/orders" for 10.0.0.1 at 2026-10-17 10:02:00 +0000\n'
        "Completed 500 Internal Server Error in 12ms\n"
        "\nNoMethodError (undefined method `price' for nil:NilClass):\n"
        "\napp/models/order.rb:33:in `subtotal'\n"
        "app/controllers/orders_controller.rb:12:in `create'"
    )
    r = compress_context(text, ["why does POST /orders 500"], ccr=False, citations=False)
    assert "NoMethodError (undefined method `price'" in r.compressed_text
    assert "order.rb:33" in r.compressed_text


def test_prose_and_python_raise_get_no_diagnostic_exemplars():
    from tameru import compress_context as cc

    paragraphs = [f"Section {i}: the review covers topic {i}." for i in range(30)]
    paragraphs[3] = "Section 3: ERROR is the name of the sentinel enum value."
    paragraphs[5] = "    raise ValueError(\"negative\")"
    paragraphs[7] = "仕様書: エラー処理の方針について説明します。"
    blocks = cc.segment_blocks("\n\n".join(paragraphs).split("\n"))
    scored = cc.score_blocks(blocks, "topic 21", content_type="text")
    assert not any(b["error_exemplar"] for b in scored)


def test_compiler_diagnostic_gets_exemplar_in_text():
    from tameru import compress_context as cc

    paragraphs = [f"gcc -O2 -c src/util{i}.c" for i in range(30)]
    paragraphs[20] = "src/net/socket.c:58:12: error: 'addrlen' undeclared"
    blocks = cc.segment_blocks("\n\n".join(paragraphs).split("\n"))
    scored = cc.score_blocks(blocks, "build", content_type="text")
    assert sum(1 for b in scored if b["error_exemplar"]) == 1


def test_dup_fp_masks_volatile_fields():
    from tameru.compress_context import _dup_fp

    a = "gcc -O2 -c src/util1.c -o build/util1.o\ngcc -O2 -c src/util2.c -o build/util2.o"
    b = "gcc -O2 -c src/util7.c -o build/util7.o\ngcc -O2 -c src/util8.c -o build/util8.o"
    assert _dup_fp(a) == _dup_fp(b)
    assert _dup_fp("alpha beta") != _dup_fp("gamma delta")


def test_hint_prefilter_is_superset_on_positive_lines():
    from tameru.agent_formats import is_diagnostic_line

    for line in POSITIVE:
        assert is_diagnostic_line(line)
    for line in NEGATIVE:
        assert not is_diagnostic_line(line)
    assert is_diagnostic_line("app/models/order.rb:33:in `subtotal'", code_only=True)
    assert not is_diagnostic_line("2026-10-17 11:00:00 FEHLER Zahlung abgelehnt", code_only=True)


def test_anchor_errors_compresses_without_query():
    from tameru.compress_context import compress_context

    text = "\n".join(f"gcc -O2 -c src/util{i}.c -o build/util{i}.o" for i in range(80)) + (
        "\nsrc/net/socket.c:58:12: error: 'addrlen' undeclared (first use in this function)\n"
        "make: *** [Makefile:24: build/socket.o] Error 1"
    )
    off = compress_context(text, [], ccr=False, citations=False)
    on = compress_context(text, [], ccr=False, citations=False, anchor_errors=True)
    assert off.fail_open
    assert not on.fail_open
    assert len(on.compressed_text) < 0.5 * len(text)
    assert "socket.c:58:12: error: 'addrlen' undeclared" in on.compressed_text
    assert on.compression_risk != "low"


def test_anchor_errors_no_errors_still_fails_open():
    from tameru.compress_context import compress_context

    text = "\n".join(f"line {i} of plain output with nothing wrong" for i in range(80))
    r = compress_context(text, [], ccr=False, citations=False, anchor_errors=True)
    assert r.fail_open


def test_anchor_errors_does_not_override_real_query():
    from tameru.compress_context import compress_context

    text = "\n".join(f"gcc -O2 -c src/util{i}.c -o build/util{i}.o" for i in range(80)) + (
        "\nsrc/net/socket.c:58:12: error: 'addrlen' undeclared"
    )
    a = compress_context(text, ["util7.c"], ccr=False, citations=False)
    b = compress_context(text, ["util7.c"], ccr=False, citations=False, anchor_errors=True)
    assert a.compressed_text == b.compressed_text


def test_anchor_region_keeps_python_frames():
    from tameru.compress_context import compress_context

    log = "\n".join(f"2026-10-17 10:{i % 60:02d}:00,123 INFO worker.pool: processed batch {i * 37 % 997} ok" for i in range(150))
    log += (
        "\n2026-10-17 11:00:01,004 ERROR worker.pool: job crashed\nTraceback (most recent call last):\n"
        '  File "/srv/app/worker/pool.py", line 214, in run\n    result = handler(payload)\n'
        '  File "/srv/app/worker/handlers.py", line 57, in handle_invoice\n'
        "    amount = payload['amount'] / payload['qty']\nZeroDivisionError: division by zero\n"
    )
    log += "\n".join(f"2026-10-17 11:{i % 60:02d}:30,555 INFO worker.pool: processed batch {i * 41 % 991} ok" for i in range(60))
    r = compress_context(log, [], ccr=False, citations=False, anchor_errors=True)
    assert not r.fail_open
    assert 'handlers.py", line 57, in handle_invoice' in r.compressed_text
    assert "ZeroDivisionError: division by zero" in r.compressed_text
    assert len(r.compressed_text) < 0.6 * len(log)


def test_make_and_shell_errors_are_diagnostics():
    from tameru.agent_formats import is_diagnostic_line

    assert is_diagnostic_line("make: *** [Makefile:24: build/socket.o] Error 1", code_only=True)
    assert is_diagnostic_line("./scripts/migrate.sh: line 42: psql: command not found", code_only=True)
    assert is_diagnostic_line("tar: dist/x: Cannot open: Permission denied", code_only=True)
    assert not is_diagnostic_line("make all", code_only=True)


def test_long_python_trace_keeps_culprit_frame():
    from tameru.compress_context import preprocess_logs

    lines = ["2026-10-17 10:00:00 INFO start", "Traceback (most recent call last):"]
    for i in range(6):
        lines += [f'  File "/srv/app/m{i}.py", line {10 + i}, in f{i}', f"    g{i}()"]
    lines += ['  File "/srv/app/handlers.py", line 57, in handle_invoice', "    a / b", "ZeroDivisionError: division by zero"]
    out = "\n".join(preprocess_logs(lines))
    assert 'handlers.py", line 57, in handle_invoice' in out
    assert "ZeroDivisionError: division by zero" in out
    assert "frames omitted" in out

def test_identifier_repeated_within_a_line_is_not_a_bridge():
    from tameru.compress_context import compress_context

    text = "\n".join(f"gcc -O2 -Wall -c src/util{i}.c -o build/util{i}.o" for i in range(80)) + (
        "\nsrc/net/socket.c: In function 'open_conn':\n"
        "src/net/socket.c:58:12: error: 'addrlen' undeclared (first use in this function)\n"
        "make: *** [Makefile:24: build/socket.o] Error 1"
    )
    r = compress_context(text, ["why does make fail"], ccr=False, citations=False)
    assert not r.fail_open
    assert len(r.compressed_text) < 0.5 * len(text)
    assert "socket.c:58:12: error: 'addrlen' undeclared" in r.compressed_text


def test_progress_glyph_line_compacts():
    from tameru.compress_context import _compact_progress_line

    assert _compact_progress_line("." * 900 + "F" + "." * 100) == "[progress x1001: .=1000 F=1 | F@901]"
    assert _compact_progress_line("." * 63 + " 63 / 630 ( 10%)") == "[progress x63: .=63] 63 / 630 ( 10%)"
    assert _compact_progress_line("......") == "......"
    assert _compact_progress_line("a normal line") == "a normal line"
    once = _compact_progress_line("." * 50 + "E")
    assert _compact_progress_line(once) == once


def test_rspec_dots_compressed_with_facts():
    from tameru.compress_context import compress_context

    text = "." * 900 + "F" + "." * 100 + (
        "\n\nFailures:\n\n  1) Invoice#total applies tax\n     Failure/Error: expect(invoice.total).to eq(110)\n\n"
        "       expected: 110\n            got: 100\n\n     # ./spec/models/invoice_spec.rb:19:in `block (2 levels)'\n\n"
        "Finished in 4.2 seconds\n1001 examples, 1 failure"
    )
    r = compress_context(text, ["why is rspec failing"], ccr=False, citations=False)
    assert len(r.compressed_text) < 0.5 * len(text)
    for fact in ("expected: 110", "got: 100", "invoice_spec.rb:19", "1001 examples, 1 failure"):
        assert fact in r.compressed_text


def test_bracket_prefixed_logs_do_not_route_json():
    from tameru.compress_context import route_content_type

    lines = [f"[server] GET /api/items/{i} 200 {i}ms" for i in range(60)]
    assert route_content_type(lines) != "json"
    lines = [f"[{i:3d}/400] Building CXX object src/mod{i}.cpp.o" for i in range(60)]
    assert route_content_type(lines) != "json"


def test_real_json_still_routes_json():
    import json as _json
    from tameru.compress_context import route_content_type

    text = _json.dumps([{"id": i, "name": f"n{i}"} for i in range(30)], indent=1)
    assert route_content_type(text.split("\n")) == "json"
    nd = [_json.dumps({"id": i, "v": i * 2}) for i in range(30)]
    assert route_content_type(nd) == "json"


def test_progress_line_with_pytest_file_prefix():
    from tameru.compress_context import _compact_progress_line
    line = "tests/test_db.py " + "." * 50 + "F" + "." * 9 + " [100%]"
    assert _compact_progress_line(line) == "tests/test_db.py [progress x60: .=59 F=1 | F@51] [100%]"


def test_progress_line_prefix_requires_glyph_run():
    from tameru.compress_context import _compact_progress_line
    assert _compact_progress_line("tests/test_db.py ... [100%]") == "tests/test_db.py ... [100%]"

def test_anchor_region_skips_repetitive_indented_rows():
    from tameru.compress_context import _anchor_regions
    text = "\n".join(f" PASS  src/c/W{i}.test.tsx ({i} ms)" for i in range(20)) + "\n FAIL  src/hooks/useCart.test.ts\n  ● useCart › removes item\n\n      at Object.<anonymous> (src/hooks/useCart.test.ts:31:24)"
    regions = _anchor_regions(text, 8)
    assert regions and not any("PASS" in r for r in regions)
    assert any("useCart.test.ts" in r for r in regions)

def test_anchor_region_bridges_blank_before_assertion_detail():
    from tameru.compress_context import _anchor_regions
    text = "\n".join(f" PASS  src/c/W{i}.test.tsx ({i} ms)" for i in range(20)) + "\n FAIL  src/hooks/useCart.test.ts\n  ● useCart › removes item\n\n    expect(received).toHaveLength(expected)\n\n    Expected length: 0\n    Received length: 1\n\n      at Object.<anonymous> (src/hooks/useCart.test.ts:31:24)\n\nTests:       1 failed, 20 passed, 21 total"
    joined = "\n".join(_anchor_regions(text, 8))
    assert "Received length: 1" in joined and "useCart.test.ts:31:24" in joined and "PASS" not in joined
def test_paragraph_prose_with_ascii_commas_is_not_csv():
    from tameru.compress_context import _looks_like_csv
    text = "\n\n".join(["本季度销售情况总体平稳,各区域按计划推进,没有需要特别说明的事项。"] * 10)
    assert not _looks_like_csv(text)
    assert _looks_like_csv("a,b,c\n" + "\n".join(f"{i},x{i},y{i}" for i in range(10)))
