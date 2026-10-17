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
