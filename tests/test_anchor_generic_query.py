

def test_maven_like_plain_path_already_wins_does_not_get_worse():
    text = (
        "\n".join(
            f"[INFO] Running com.acme.Mod{i}Test\n[INFO] Tests run: 5, Failures: 0, Errors: 0, Skipped: 0, Time elapsed: 0.{i} s"
            for i in range(60)
        )
        + "\n[ERROR] Tests run: 12, Failures: 1, Errors: 0, Skipped: 0 <<< FAILURE! - in com.acme.TaxTest\n[ERROR] com.acme.TaxTest.vatRounding  Time elapsed: 0.02 s  <<< FAILURE!\norg.opentest4j.AssertionFailedError: expected: <19.99> but was: <20.0>\n[INFO] BUILD FAILURE"
    )
    a = compress_context(text, ["why does mvn test fail"], ccr=False, citations=False, min_savings_ratio=0.1, anchor_errors=True)
    b = compress_context(text, ["why does mvn test fail"], ccr=False, citations=False, min_savings_ratio=0.1, anchor_errors=False)
    assert len(a.compressed_text) <= len(b.compressed_text) and "expected: <19.99> but was: <20.0>" in a.compressed_text
from tameru.compress_context import compress_context


def test_anchor_generic_query():
    text = "\n".join(
        f"npm http fetch GET 200 https://registry.npmjs.org/pkg-{i} {i}ms (cache hit)"
        for i in range(300)
    ) + "\nnpm ERR! code ERESOLVE\nnpm ERR! ERESOLVE unable to resolve dependency tree\nnpm ERR! Found: react@18.3.1"
    r = compress_context(
        text,
        ["why does npm install fail"],
        ccr=False,
        citations=False,
        min_savings_ratio=0.1,
        anchor_errors=True,
    )
    assert "unable to resolve dependency tree" in r.compressed_text
    assert "react@18.3.1" in r.compressed_text
    assert len(r.compressed_text) < 0.3 * len(text)

    r_off = compress_context(
        text,
        ["why does npm install fail"],
        ccr=False,
        citations=False,
        min_savings_ratio=0.1,
        anchor_errors=False,
    )
    assert "react@18.3.1" in r_off.compressed_text
